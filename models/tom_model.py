#!/usr/bin/env python3
"""Deterministic prequential models for Tom inference system; standard-library only."""
from __future__ import annotations
import hashlib,json,math
from collections import deque
from datetime import datetime,timedelta

VERSION='tom-online-2.1'
ZODIAC=list('鼠牛虎兔龙蛇马羊猴鸡狗猪')
ALIASES={'龍':'龙','馬':'马','雞':'鸡','豬':'猪'}
MODELS=['dirichlet','exponential','markov','online_softmax','uniform_expert']
MODEL_NAMES={'dirichlet':'Dirichlet长短窗收缩','exponential':'90期半衰衰减','markov':'一阶Markov回退','online_softmax':'在线多项逻辑回归','uniform_expert':'均匀收缩专家'}
PARAMS={'long_window':730,'short_window':90,'dirichlet_prior':98.0,'short_prior':98.0,'short_mix':0.35,'half_life':90.0,'decay_prior':49.0,'markov_prior':98.0,'hedge_burnin':90,'hedge_eta':0.08,'weight_floor':0.03,'softmax_eta':0.03,'softmax_decay':0.0004,'softmax_warmup':45,'logloss_clip':1e-12}
FEATURE_COUNT=148

def canonical(row):
 nums=list(map(int,row['numbers']));z=[ALIASES.get(x,x) for x in row.get('zodiac',[])];return {'expect':str(row['expect']),'openTime':str(row['openTime']),'numbers':nums,'zodiac':z}

def canonical_history(records):
 rows=[canonical(r) for r in records];rows.sort(key=lambda r:r['expect']);result=[];seen={}
 for r in rows:
  if len(r['expect'])!=7 or not r['expect'].isdigit() or int(r['expect'][4:])<1:raise ValueError('bad expect')
  if len(r['numbers'])!=7 or any(not isinstance(x,int) or not 1<=x<=49 for x in r['numbers']) or len(set(r['numbers']))!=7:raise ValueError('bad draw numbers '+r['expect'])
  if r['openTime'][:4]!=r['expect'][:4]:raise ValueError('expect and date year differ '+r['expect'])
  if r['zodiac'] and (len(r['zodiac'])!=7 or any(x not in ZODIAC for x in r['zodiac'])):raise ValueError('bad zodiac '+r['expect'])
  if r['expect'] in seen:
   if seen[r['expect']]!=r:raise ValueError('conflicting expect '+r['expect'])
   continue
  seen[r['expect']]=r
  if result and r['openTime']<result[-1]['openTime']:raise ValueError('time/expect chronology mismatch '+r['expect'])
  result.append(r)
 return result

def fingerprint(rows):
 b=json.dumps({'model':VERSION,'params':PARAMS,'history':[[r['expect'],r['openTime'],r['numbers'],r['zodiac']] for r in rows]},ensure_ascii=False,separators=(',',':')).encode();return 'sha256:'+hashlib.sha256(b).hexdigest()

def new_state():
 return {'version':VERSION,'params':PARAMS,'n':0,'log_loss_sum':[0.0]*len(MODELS),'score_count':0,'long':[0]*49,'short':[0]*49,'ewma':[0.0]*49,'ewma_total':0.0,'previous':-1,'trans':[[0]*49 for _ in range(49)],'trans_total':[0]*49,'queue':[],'loss':[0.0]*len(MODELS),'online_weights':[[0.0]*FEATURE_COUNT for _ in range(49)],'softmax_updates':0,'train_loss':0.0,'train_brier':0.0,'trace_hash':'0'*64}

def _normal(values):
 total=sum(values)
 if total<=0:return [1/49]*49
 return [max(0.0,x)/total for x in values]

def _softmax(logits):
 peak=max(logits);vals=[math.exp(max(-40,min(0,x-peak))) for x in logits];return _normal(vals)

def features(state):
 n=state['n'];x=[1.0]
 x.extend([1.0 if i==state['previous'] else 0.0 for i in range(49)])
 den_short=max(1,min(PARAMS['short_window'],n));x.extend(v/den_short for v in state['short'])
 den_long=max(1,min(PARAMS['long_window'],n));x.extend(v/den_long for v in state['long'])
 # Exact length is part of the versioned model schema.
 assert len(x)==FEATURE_COUNT
 return x

def forecast(state):
 n=state['n'];nl=min(n,PARAMS['long_window']);ns=min(n,PARAMS['short_window'])
 prior=[(c+PARAMS['dirichlet_prior']/49)/(nl+PARAMS['dirichlet_prior']) for c in state['long']]
 d=[(1-PARAMS['short_mix'])*p+PARAMS['short_mix']*(state['short'][i]+PARAMS['short_prior']*p)/(ns+PARAMS['short_prior']) for i,p in enumerate(prior)]
 exp=[(c+PARAMS['decay_prior']/49)/(state['ewma_total']+PARAMS['decay_prior']) for c in state['ewma']]
 prev=state['previous'];mk=prior[:] if prev<0 else [(state['trans'][prev][i]+PARAMS['markov_prior']*prior[i])/(state['trans_total'][prev]+PARAMS['markov_prior']) for i in range(49)]
 x=features(state);logits=[sum(w*xi for w,xi in zip(row,x)) for row in state['online_weights']];soft=_softmax(logits)
 ps=[_normal(d),_normal(exp),_normal(mk),soft,[1/49]*49]
 losses=state['loss'];floor=PARAMS['weight_floor']/len(MODELS);raw=[math.exp(max(-50,min(50,-PARAMS['hedge_eta']*(l-min(losses))))) for l in losses]
 total=sum(raw);weights=[floor+(1-PARAMS['weight_floor'])*r/total for r in raw]
 mixed=_normal([sum(weights[j]*ps[j][i] for j in range(len(MODELS))) for i in range(49)])
 return {'models':ps,'weights':weights,'probabilities':mixed,'features':x,'scores':{k:v for k,v in zip(MODELS,ps)}}

def _stable_json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def observe(state,row,pred):
 n=state['n'];target=int(row['numbers'][6])-1;actual=row['expect'];x=pred['features']
 if n>=PARAMS['hedge_burnin']:
  for j,p in enumerate(pred['models']):
   loss=-math.log(max(PARAMS['logloss_clip'],p[target]));state['loss'][j]+=loss;state['log_loss_sum'][j]+=loss
  state['score_count']+=1
 # Online multinomial SGD: predict first, score, then reveal the draw and train.
 if n>=PARAMS['softmax_warmup']:
  p=pred['models'][3];lr=PARAMS['softmax_eta']/math.sqrt(1+n/500);decay=1-lr*PARAMS['softmax_decay'];row_losses=state['online_weights']
  for k,w in enumerate(row_losses):
   err=p[k]-(1.0 if k==target else 0.0)
   for j,xj in enumerate(x):w[j]=w[j]*decay-lr*err*xj
  state['softmax_updates']+=1;state['train_loss']-=math.log(max(PARAMS['logloss_clip'],p[target]))
  state['train_brier']+=sum((p[k]-(1.0 if k==target else 0.0))**2 for k in range(49))
 trace={'expect':actual,'actual':target+1,'probabilities':pred['probabilities']}
 state['trace_hash']=hashlib.sha256((state['trace_hash']+_stable_json(trace)).encode()).hexdigest()
 decay=0.5**(1/PARAMS['half_life'])
 for i in range(49):state['ewma'][i]*=decay
 state['ewma'][target]+=1;state['ewma_total']=state['ewma_total']*decay+1
 state['queue'].append(target);state['long'][target]+=1;state['short'][target]+=1
 if n>=PARAMS['long_window']:state['long'][state['queue'][n-PARAMS['long_window']]]-=1
 if n>=PARAMS['short_window']:state['short'][state['queue'][n-PARAMS['short_window']]]-=1
 if state['previous']>=0:state['trans'][state['previous']][target]+=1;state['trans_total'][state['previous']]+=1
 state['previous']=target;state['n']=n+1
 if n+1>PARAMS['hedge_burnin']:
  mean=sum(state['loss'])/len(MODELS);state['loss']=[l-mean for l in state['loss']]

def train(records,state=None):
 rows=canonical_history(records);s=state if state is not None else new_state()
 if s.get('version')!=VERSION or s.get('params')!=PARAMS:raise ValueError('model state version mismatch')
 if s['n']>len(rows):raise ValueError('state is ahead of draw history')
 # Replay from scratch if the saved-prefix fingerprint differs; otherwise train only new outcomes.
 if s['n']:
  prefix=rows[:s['n']]
  saved=s.get('through_fingerprint')
  if not saved or saved!=fingerprint(prefix):s=new_state()
 for row in rows[s['n']:]:observe(s,row,forecast(s))
 s['through_expect']=rows[-1]['expect'] if rows else None;s['through_fingerprint']=fingerprint(rows)
 return s

def _map(rows):
 residue=[None]*12;offset=None;through=None
 for row in reversed(rows[-90:]):
  pairs=[]
  for n,z in zip(row['numbers'],row.get('zodiac') or []):
   z=ALIASES.get(z,z)
   if z:pairs.append(((n-1)%12,z))
  offs={(ZODIAC.index(z)+r)%12 for r,z in pairs}
  if len(offs)!=1:continue
  cur=next(iter(offs))
  if offset is not None and offset!=cur:break
  if any(residue[r] and residue[r]!=z for r,z in pairs):break
  offset=cur;through=through or row['expect']
  for r,z in pairs:residue[r]=z
 if offset is None:raise ValueError('no zodiac map')
 anchor=next(i for i,z in enumerate(residue) if z);zi=ZODIAC.index(residue[anchor]);inferred=0
 for r,z in enumerate(residue):
  if z is None:residue[r]=ZODIAC[(zi-(r-anchor))%12];inferred+=1
 mapping={str(n):residue[(n-1)%12] for n in range(1,50)}
 return mapping,through,inferred

def generate(records,target_expect,state=None,trained=None):
 target=str(target_expect)
 if len(target)!=7 or not target.isdigit():raise ValueError('bad target expect')
 rows=canonical_history([r for r in records if str(r.get('expect',''))<target])
 if not rows:raise ValueError('no training history')
 s=train(rows,state) if state else train(rows)
 pred=forecast(s);order=sorted(range(49),key=lambda i:(-pred['probabilities'][i],i+1));ranking=[i+1 for i in order]
 m,zthrough,inferred=_map(rows);zp={z:sum(pred['probabilities'][n-1] for n in range(1,50) if m[str(n)]==z) for z in ZODIAC};zrank=sorted(ZODIAC,key=lambda z:(-zp[z],ZODIAC.index(z)))
 top=[{'id':k,'name':MODEL_NAMES[k],'weight':pred['weights'][i],'log_loss':s['log_loss_sum'][i]/s['score_count'] if s['score_count'] else None,'probabilities':pred['models'][i]} for i,k in enumerate(MODELS)]
 return {'version':VERSION,'targetExpect':target,'trainingThrough':rows[-1]['expect'],'trainingCount':len(rows),'trainingFingerprint':fingerprint(rows),'numberRanking':ranking,'numberSets':{str(k):ranking[:k] for k in (36,24,16,8,4)},'zodiacRanking':zrank,'zodiacSets':{str(k):zrank[:k] for k in (9,6,4,2)},'models':top,'probabilities':pred['probabilities'],'zodiacProbabilities':zp,'zodiacMap':m,'mappingNote':f'Predictor map uses only outcomes through {zthrough}; inferred residues={inferred}. Lunar-year boundary is held until observations confirm a new offset.','modelNote':'Prequential fixed-hyperparameter models: Dirichlet, exponential decay, Markov fallback, online softmax SGD, adaptive Hedge. Training labels are only already observed specials. Historical performance can remain at the uniform baseline or worse.','trainingState':{'n':s['n'],'throughExpect':s['through_expect'],'fingerprint':s['through_fingerprint'],'weightUpdates':max(0,s['n']-PARAMS['hedge_burnin']),'softmaxUpdates':s['softmax_updates'],'onlineLogLoss':s['train_loss']/max(1,s['softmax_updates']),'onlineBrier':s['train_brier']/max(1,s['softmax_updates']),'traceHash':s['trace_hash']}}

def _wilson(h,n):
 if not n:return [0,1]
 z=1.959963984540054;p=h/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;w=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [max(0,c-w),min(1,c+w)]
def backtest(records,holdout=365,burnin=365):
 rows=canonical_history(records);first=max(burnin,len(rows)-holdout)
 if first>=len(rows):raise ValueError('insufficient history')
 s=new_state();acc={k:{'num':{n:0 for n in (36,24,16,8,4)},'zod':{n:0 for n in (9,6,4,2)},'base':{n:0.0 for n in (9,6,4,2)},'loss':0.0,'brier':0.0} for k in MODELS+['ensemble','uniform']};mismatch=0;cuts={}
 for t,row in enumerate(rows):
  f=forecast(s)
  if t>=first:
   mapping,_,_=_map(rows[:t]);actual=row['numbers'][6];az=ALIASES.get(row['zodiac'][6],row['zodiac'][6]);
   if not az:raise ValueError(row['expect']+' missing true zodiac')
   if mapping[str(actual)]!=az:mismatch+=1
   ps={k:f['models'][i] for i,k in enumerate(MODELS)};ps['ensemble']=f['probabilities'];ps['uniform']=[1/49]*49
   for name,p in ps.items():
    a=acc[name];a['loss']-=math.log(max(1e-12,p[actual-1]));a['brier']+=sum((v-(1 if i==actual-1 else 0))**2 for i,v in enumerate(p))
    ranking=sorted(range(1,50),key=lambda n:(-p[n-1],n));
    zprob={z:sum(p[n-1] for n in range(1,50) if mapping[str(n)]==z) for z in ZODIAC};zr=sorted(ZODIAC,key=lambda z:(-zprob[z],ZODIAC.index(z)))
    if name=='uniform':continue
    for k in a['num']:
     if actual in ranking[:k]:a['num'][k]+=1
    for k in a['zod']:
     selected=zr[:k];covered=sum(mapping[str(n)] in selected for n in range(1,50));a['base'][k]+=covered/49
     if az in selected:a['zod'][k]+=1
  observe(s,row,f)
 count=len(rows)-first;out=[]
 for name,a in acc.items():
  num={};zod={}
  if name!='uniform':
   for k,h in a['num'].items():lo,hi=_wilson(h,count);num[str(k)]={'hits':h,'total':count,'rate':h/count,'baseline':k/49,'wilsonLow':lo,'wilsonHigh':hi,'lift':(h/count)/(k/49)}
   for k,h in a['zod'].items():lo,hi=_wilson(h,count);base=a['base'][k]/count;zod[str(k)]={'hits':h,'total':count,'rate':h/count,'baseline':base,'wilsonLow':lo,'wilsonHigh':hi,'lift':(h/count)/base if base else 0}
  out.append({'id':name,'name':MODEL_NAMES.get(name,'逐期对数损失融合' if name=='ensemble' else '独立均匀基线'),'numberHits':num,'zodiacHits':zod,'logLoss':a['loss']/count,'brier':a['brier']/count})
 return {'modelVersion':VERSION,'split':{'testFirst':rows[first]['expect'],'testLast':rows[-1]['expect'],'testCount':count,'burnIn':burnin,'method':'strict chronological prequential walk-forward, predict before update'},'algorithms':out,'uniformLogLoss':math.log(49),'zodiacMapMismatches':mismatch,'onlineTrainingUpdates':len(rows),'notes':['Each target is predicted only from earlier verified draws.','Model scores are retrospective and do not imply predictive advantage.']}
