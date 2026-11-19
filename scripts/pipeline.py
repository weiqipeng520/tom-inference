#!/usr/bin/env python3
"""One-writer train, freeze, settle and publish. Run from repository root."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,shutil,sys,time
from pathlib import Path
from . import storage as st
from .source import normalize,fetch,expected_successor,gap_between,LATEST,HISTORY,PERIOD,SOURCE
from models import tom_model as model

ROOT=Path(__file__).resolve().parents[1]

def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);text=st.dumps(value)+'\n'
 if not path.exists() or path.read_text(encoding='utf-8')!=text:path.write_text(text,encoding='utf-8')

def bootstrap(db,root,now):
 if db.execute('SELECT COUNT(*) FROM draws').fetchone()[0]:return False
 bundle=read_json(root/'seed/draws.json')
 for row in bundle['records']:st.insert_draw(db,normalize(row),now,'imported-history')
 st.set_meta(db,'coverage',bundle['meta'])
 seed=read_json(root/'seed/forecast-seed.json')
 for e in seed['entries']:
  envelope={'targetExpect':e['prediction']['targetExpect'],'createdAt':e['createdAt'],'expectedOpenTime':e['expectedOpenTime'],'source':'legacy-release-seed','origin':'legacy-import','modelVersion':e['prediction']['version'],'prediction':e['prediction'],'digest':e['digest'],'importNote':'原发布种子原样保留；时间为声明生成时间，无中央公开部署回执，不计已验证前瞻成绩'}
  st.lock_forecast(db,envelope)
 st.set_meta(db,'legacy_backtest',read_json(root/'seed/backtest-results.json'))
 st.set_meta(db,'system_created_at',now);return True

def audit_fetch(db,record):
 try:
  semantic=json.loads(record['rawJson'])
  if isinstance(semantic,dict):semantic={k:v for k,v in semantic.items() if k not in ['timestamp','serverTime','requestId']}
 except (ValueError,TypeError):semantic=record['rawJson']
 key=st.sha({'url':record['url'],'semantic':semantic})
 db.execute('INSERT OR IGNORE INTO fetch_audit VALUES(?,?,?,?,?,?,?,?)',(key,record['url'],record['fetchedAt'],record['httpStatus'],record['rawSha'],record['rawJson'],st.PARSER_VERSION,st.dumps(record['errors'])))

def acquire(db,now):
 current=st.draws(db);last=current[-1];year=int(st.iso(now)[:4]);warnings=[];success=False;audits=[];rows={};blocked_expects=set();block_forward=False
 for url,requested_year in [(HISTORY.format(year=year),year),(LATEST,None)]:
  try:
   parsed,record=fetch(url,now,requested_year);audit_fetch(db,record);audits.append(record['id']);success=success or bool(parsed)
   for error in record['errors']:
    # Known old source anomalies stay visible; malformed new observations block advancement below.
    warnings.append({'url':url,**error})
    if str(error.get('expect',''))>=last['expect'] or 'conflicting' in error.get('error',''):
     block_forward=True;blocked_expects.add(str(error.get('expect','')))
   for row in parsed:
    old=rows.get(row['expect'])
    if old and old!=row:
     warnings.append({'expect':row['expect'],'error':'conflicting rows from source endpoints'});blocked_expects.add(row['expect']);block_forward=True
    elif row['expect'] not in blocked_expects:rows[row['expect']]=row
  except RuntimeError as e:warnings.append({'url':url,'error':str(e)})
 # Recover only gaps after the latest DB record, never re-create old forecasts.
 forward=sorted([r for r in rows.values() if r['expect']>last['expect']],key=lambda r:r['expect'])
 if forward:
  cursor=last
  for candidate in forward:
   hops=0
   while gap_between(cursor,candidate) and hops<32:
    expect,_=expected_successor(cursor)
    if expect>=candidate['expect']:break
    url=PERIOD.format(expect=expect)
    try:
     parsed,record=fetch(url,now,int(expect[:4]));audit_fetch(db,record);match=[r for r in parsed if r['expect']==expect]
     if len(match)!=1:break
     rows[expect]=match[0];cursor=match[0];hops+=1
    except RuntimeError:break
   cursor=candidate
 if blocked_expects:rows={k:r for k,r in rows.items() if k not in blocked_expects}
 if block_forward:rows={k:r for k,r in rows.items() if k<=last['expect']}
 return list(rows.values()),{'success':success,'blocked':block_forward,'blockedExpects':sorted(blocked_expects),'checkedAt':st.iso(now),'lastSuccess':st.iso(now) if success else None,'source':SOURCE,'warnings':warnings,'audits':audits}

def ingest(db,rows,now,source='specified-api'):
 added=[];conflicts=[];gaps=[];current=st.draws(db);last=current[-1] if current else None
 for row in sorted(rows,key=lambda r:r['expect']):
  row=normalize(row)
  if st.epoch(row['openTime'])>now:raise ValueError('future actual result')
  exists=db.execute('SELECT payload_json FROM draws WHERE expect=?',(row['expect'],)).fetchone()
  if exists:
   result=st.insert_draw(db,row,now,source)
   if result=='conflict':conflicts.append(row['expect'])
   continue
  # Late historical repairs are imported as history only; trigger replay, never retrospective public forecasts.
  if last and row['expect']>last['expect']:
   gap=gap_between(last,row)
   if gap:gaps.append(gap);continue
  result=st.insert_draw(db,row,now,source)
  if result=='inserted':added.append(row['expect'])
  if not last or row['expect']>last['expect']:last=row
 return added,conflicts,gaps

def train_db(db,now):
 rows=st.draws(db);input_sha=model.fingerprint(model.canonical_history(rows));old=db.execute('SELECT * FROM model_state WHERE model_version=?',(model.VERSION,)).fetchone()
 if old and old['input_sha']==input_sha:return json.loads(old['state_json']),False
 old_state=json.loads(old['state_json']) if old else None;canonical=model.canonical_history(rows);replay=bool(old_state and model.fingerprint(canonical[:old_state['n']])!=old_state.get('through_fingerprint'))
 state=model.new_state() if replay or not old_state else old_state
 start=state['n'];event_rows=[]
 for row in canonical[start:]:
  fc=model.forecast(state);before=state['trace_hash'];model.observe(state,row,fc)
  if old_state:event_rows.append((row['expect'],model.VERSION,st.sha(row),now,before,state['trace_hash']))
 state['through_expect']=canonical[-1]['expect'];state['through_fingerprint']=input_sha
 backtest=model.backtest(rows,holdout=min(365,max(1,len(rows)-365)),burnin=min(365,len(rows)-1))
 code_sha='sha256:'+hashlib.sha256((ROOT/'models/tom_model.py').read_bytes()).hexdigest()
 train_id=st.sha({'model':model.VERSION,'input':input_sha,'code':code_sha})
 current=model.forecast(state)
 manifest={'id':train_id,'modelVersion':model.VERSION,'throughExpect':canonical[-1]['expect'],'trainingCount':len(canonical),'lastTrainingAt':st.iso(now),'softmaxUpdates':state['softmax_updates'],'weightUpdates':max(0,state['n']-model.PARAMS['hedge_burnin']),'trainingFingerprint':input_sha,'traceHash':state['trace_hash'],'models':[{'id':name,'name':model.MODEL_NAMES[name],'weight':current['weights'][i]} for i,name in enumerate(model.MODELS)],'eventCount':len(event_rows),'replayed':replay,'bootstrap':not bool(old),'codeSha256':code_sha,'parameters':model.PARAMS,'python':sys.version.split()[0],'method':'predict -> score -> observe label -> SGD/statistics/Hedge update; no future labels','backtest':backtest}
 db.execute('INSERT OR IGNORE INTO training_runs VALUES(?,?,?,?,?,?)',(train_id,model.VERSION,canonical[-1]['expect'],input_sha,now,st.dumps(manifest)))
 db.executemany('INSERT OR IGNORE INTO training_events VALUES(?,?,?,?,?,?)',event_rows)
 db.execute('INSERT INTO model_state VALUES(?,?,?,?) ON CONFLICT(model_version) DO UPDATE SET through_expect=excluded.through_expect,input_sha=excluded.input_sha,state_json=excluded.state_json',(model.VERSION,canonical[-1]['expect'],input_sha,st.dumps(state)))
 st.set_meta(db,'training_manifest',manifest);return state,True

def next_forecast(db,state,now,blocked=False,clock=None):
 rows=st.draws(db);target,deadline=expected_successor(rows[-1]);old=db.execute('SELECT payload_json FROM forecasts WHERE expect=?',(target,)).fetchone()
 if old:return json.loads(old[0]),False,'frozen-existing'
 if blocked:return None,False,'source-gap-or-conflict'
 if now>=deadline:return None,False,'target-deadline-passed-awaiting-draw'
 if deadline-now>26*3600000:return None,False,'source-ahead-of-clock'
 p=model.generate(rows,target,state=copy.deepcopy(state));created_at=clock() if clock else now
 if created_at>=deadline:return None,False,'target-deadline-passed-awaiting-draw'
 envelope={'targetExpect':target,'createdAt':created_at,'expectedOpenTime':deadline,'source':'central-github-action','origin':'central','prediction':p,'modelVersion':model.VERSION,'releaseEvidence':'生成时间由runner记录；首次Pages部署由独立receipt记入数据库'}
 env,created=st.lock_forecast(db,envelope);return env,created,'frozen-existing'

def snapshot(db,root,now):
 rows=st.draws(db);all_forecasts=st.forecasts(db);latest=rows[-1];target,deadline=expected_successor(latest);current=next((f for f in all_forecasts if f['targetExpect']==target),None);training=st.get_meta(db,'training_manifest',{});backtest=training.get('backtest');training={k:v for k,v in training.items() if k!='backtest'}
 base={'schemaVersion':1,'system':{'name':'Tom推演系统','version':'3.0.0'},'publication':{'generatedAt':st.iso(st.get_meta(db,'last_business_change',now)),'lastTrainingAt':training.get('lastTrainingAt'),'sync':st.get_meta(db,'sync',{}),'consistency':'同一期号只有一个冻结digest；同snapshotId读取相同数据。Pages部署/CDN传播可能短暂显示旧版，页面会标明版本。'},'latestDraw':latest,'nextDraw':{'expect':target,'expectedOpenTime':deadline,'estimated':True,'timezone':'Asia/Shanghai','scheduleVersion':'daily-source-assumption-1','timeBasis':'指定来源未声明时区；按业务配置UTC+8解释，默认每日21:32:32估算'},'currentForecast':current,'forecasts':all_forecasts,'settlements':st.latest_settlements(db),'training':training,'backtest':backtest,'legacyBacktest':st.get_meta(db,'legacy_backtest'),'draws':rows,'coverage':st.get_meta(db,'coverage',{}),'runtime':{'status':st.get_meta(db,'runtime_status','ready'),'firstPublicationReceipts':[dict(r) for r in db.execute('SELECT * FROM publication_receipts ORDER BY expect')],'sourceConflictCount':db.execute('SELECT COUNT(*) FROM draw_conflicts').fetchone()[0],'centralLedger':'SQLite database/tom.sqlite, written by one serialized GitHub Actions workflow; visitors read-only'}}
 base['publication']['snapshotId']=st.sha(base);write_json(root/'site/data.json',base)
 for env in all_forecasts:
  path=root/'database/forecasts'/f"{env['targetExpect']}.json"
  if path.exists() and read_json(path)!=env:raise ValueError('frozen file conflict '+str(path))
  write_json(path,env)
  write_json(root/'site/data/forecasts'/f"{env['targetExpect']}.json",env)
 if backtest:write_json(root/'reports/backtest.json',backtest)
 write_json(root/'database/training/latest.json',training)
 return base

def run(root=ROOT,offline=False,now=None,incoming=None):
 root=Path(root);fixed_now=now is not None;now=int(time.time()*1000) if now is None else now;clock=(lambda:now) if fixed_now else (lambda:int(time.time()*1000));db=st.connect(root/'database/tom.sqlite');result={}
 try:
  with db:
   seeded=bootstrap(db,root,now)
   if incoming is not None:batch=incoming;sync={'success':True,'checkedAt':st.iso(now),'lastSuccess':st.iso(now),'warnings':[],'source':'test-fixture'}
   elif offline:batch=[];sync=st.get_meta(db,'sync',{'success':False,'checkedAt':st.iso(now),'lastSuccess':None,'warnings':['离线构建：当前为打包时中央快照，启用Actions后首次同步指定来源'],'source':SOURCE})
   else:batch,sync=acquire(db,now)
   added,conflicts,gaps=ingest(db,batch,now)
   if conflicts:sync['warnings'].append({'error':'draw conflicts quarantined, original retained','expects':conflicts})
   if gaps:sync['warnings'].extend(gaps)
   sync_changed=False;previous_sync=st.get_meta(db,'sync')
   if seeded or added or conflicts or gaps or sync.get('blocked') or previous_sync is None or previous_sync.get('success')!=sync['success'] or previous_sync.get('blocked')!=sync.get('blocked'):sync_changed=st.set_meta(db,'sync',sync)
   state,trained=train_db(db,now);settled=st.settle(db,now)
   forecast,created,status=next_forecast(db,state,clock(),bool(conflicts or gaps or sync.get('blocked') or (not offline and not sync.get('success'))),clock=clock)
   status_changed=st.set_meta(db,'runtime_status',status)
   changed=seeded or bool(added) or trained or settled or created or sync_changed or status_changed
   if changed:st.set_meta(db,'last_business_change',now)
   st.integrity(db)
  content=snapshot(db,root,now);db.commit();st.integrity(db);db.close();db=None
  # Copy closed rollback-journal SQLite file: no WAL sidecar needed for persistence.
  export=root/'site/data/tom.sqlite';export.parent.mkdir(parents=True,exist_ok=True);source=root/'database/tom.sqlite'
  if not export.exists() or hashlib.sha256(export.read_bytes()).digest()!=hashlib.sha256(source.read_bytes()).digest():shutil.copy2(source,export)
  result={'changed':bool(changed),'added':added,'trained':trained,'newForecast':created,'forecastTarget':forecast['targetExpect'] if forecast else None,'conflicts':conflicts,'gaps':gaps,'status':status,'snapshotId':content['publication']['snapshotId'],'latest':content['latestDraw']['expect']}
  print(st.dumps(result));return result
 finally:
  if db is not None:db.close()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args();run(args.root,args.offline)
if __name__=='__main__':main()
