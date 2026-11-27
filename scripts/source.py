#!/usr/bin/env python3
"""Bounded read-only fetches from the user-specified source, never a gambling transaction."""
from __future__ import annotations
import json,re,time,urllib.request,urllib.error,hashlib
from http.client import HTTPException
from datetime import datetime,timedelta
from .storage import epoch,dumps,sha,PARSER_VERSION

SOURCE='https://macaujc.com/macaujc2/'
LATEST='https://macaumarksix.com/api/macaujc2.com'
HISTORY='https://history.macaumarksix.com/history/macaujc2/y/{year}'
PERIOD='https://history.macaumarksix.com/history/macaujc2/expect/{expect}'
ALIASES={'龍':'龙','馬':'马','雞':'鸡','豬':'猪'};ZOD=set('鼠牛虎兔龙蛇马羊猴鸡狗猪')
RED={1,2,7,8,12,13,18,19,23,24,29,30,34,35,40,45,46};BLUE={3,4,9,10,14,15,20,25,26,31,36,37,41,42,47,48}

def normalize(raw,year=None):
 if not isinstance(raw,dict):raise ValueError('record must be object')
 exp=str(raw.get('expect','')).strip()
 if not re.fullmatch(r'\d{7}',exp) or int(exp[4:])<1:raise ValueError('bad period')
 if raw.get('type') is not None and str(raw['type'])!='8':raise ValueError('unexpected lottery type')
 when=str(raw.get('openTime','')).strip();datetime.strptime(when,'%Y-%m-%d %H:%M:%S')
 if when[:4]!=exp[:4]:raise ValueError('wrong period/date year')
 if year is not None and int(exp[:4])!=year:raise ValueError('wrong requested year')
 values=raw.get('numbers',raw.get('openCode',''))
 if not isinstance(values,(str,list)):raise ValueError('numbers must be list or CSV text')
 values=values if isinstance(values,list) else values.split(',')
 if len(values)!=7:raise ValueError('incomplete 7-ball draw')
 if any(isinstance(n,bool) or not re.fullmatch(r'\d{1,2}',str(n).strip()) for n in values):raise ValueError('invalid number')
 nums=list(map(int,values))
 if any(n<1 or n>49 for n in nums) or len(set(nums))!=7:raise ValueError('duplicate/out-of-range number')
 z=raw.get('zodiac',[])
 if not isinstance(z,(str,list)):raise ValueError('zodiac must be list or CSV text')
 z=z if isinstance(z,list) else z.split(',');z=[ALIASES.get(x,x) for x in z]
 if len(z)!=7 or any(x not in ZOD for x in z):raise ValueError('invalid/missing zodiac')
 waves=raw.get('wave',[])
 if waves is None:waves=[]
 if not isinstance(waves,(str,list)):raise ValueError('wave must be list or CSV text')
 waves=waves if isinstance(waves,list) else waves.split(',')
 if not waves:waves=['red' if n in RED else 'blue' if n in BLUE else 'green' for n in nums]
 if len(waves)!=7 or any(w not in ['red','blue','green'] for w in waves):raise ValueError('invalid wave')
 return {'expect':exp,'openTime':when,'year':int(exp[:4]),'numbers':nums,'zodiac':z,'wave':waves,'type':'8'}

def decode_payload(payload):
 if isinstance(payload,list):return payload
 if isinstance(payload,dict) and str(payload.get('code'))=='200' and payload.get('result') is not False and isinstance(payload.get('data'),list):return payload['data']
 raise ValueError('API payload status/data invalid')

def fetch(url,now,year=None):
 for attempt in range(2):
  try:
   request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (Tom historical inference)','Accept':'application/json','Referer':SOURCE})
   with urllib.request.urlopen(request,timeout=20) as response:body=response.read(10*1024*1024+1);status=response.status
   if len(body)>10*1024*1024:raise ValueError('response too large')
   text=body.decode('utf-8-sig');raw=json.loads(text);rows=[];errors=[]
   for index,item in enumerate(decode_payload(raw)):
    try:
     row=normalize(item,year)
     if epoch(row['openTime'])>now:raise ValueError('future result')
     rows.append(row)
    except (ValueError,TypeError) as e:errors.append({'index':index,'expect':str(item.get('expect','')) if isinstance(item,dict) else '', 'error':str(e)})
   seen={};valid=[]
   for row in rows:
    old=seen.get(row['expect'])
    if old:
     if old!=row:errors.append({'expect':row['expect'],'error':'conflicting duplicate within response'})
    else:seen[row['expect']]=row;valid.append(row)
   conflicting={e['expect'] for e in errors if 'conflicting duplicate' in e['error']}
   valid=[r for r in valid if r['expect'] not in conflicting]
   record={'id':'sha256:'+hashlib.sha256(body).hexdigest(),'url':url,'fetchedAt':now,'httpStatus':status,'rawSha':'sha256:'+hashlib.sha256(body).hexdigest(),'rawJson':text,'errors':errors,'validCount':len(valid)}
   return valid,record
  except (OSError,ValueError,HTTPException) as e:
   if attempt or (isinstance(e,urllib.error.HTTPError) and e.code in [401,403]):raise RuntimeError(type(e).__name__+': '+str(e)) from e
   wait=1
   if isinstance(e,urllib.error.HTTPError) and e.code==429:
    try:wait=max(1,min(5,int(e.headers.get('Retry-After','1'))))
    except (ValueError,TypeError):wait=1
   time.sleep(wait)
 raise AssertionError('unreachable')

def expected_successor(row):
 """Daily-source assumption, versioned; never infer skipped periods from today's clock."""
 target_time=datetime.strptime(row['openTime'][:10]+' 21:32:32','%Y-%m-%d %H:%M:%S')+timedelta(days=1)
 year=target_time.year;year_of_issue=int(row['expect'][:4]);period=int(row['expect'][4:])
 if year==year_of_issue:exp=f'{year}{period+1:03d}'
 else:exp=f'{year}001'
 return exp,epoch(target_time.strftime('%Y-%m-%d %H:%M:%S'))

def gap_between(previous,newer):
 """Source can contain old known gaps; check only forward ingestion from latest confirmed draw."""
 if newer['expect']<=previous['expect']:return None
 exp,_=expected_successor(previous)
 if newer['expect']!=exp:return {'after':previous['expect'],'nextExpected':exp,'received':newer['expect'],'error':'new forward issue gap'}
 return None
