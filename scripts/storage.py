#!/usr/bin/env python3
"""SQLite authoritative ledger. Forecasts are append-only at the SQL level."""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone

CST=timezone(timedelta(hours=8));PARSER_VERSION='tom-parser-1';SCHEMA_VERSION=1

def dumps(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(value):return 'sha256:'+hashlib.sha256((dumps(value) if not isinstance(value,str) else value).encode()).hexdigest()
def iso(ms):return datetime.fromtimestamp(ms/1000,CST).isoformat(timespec='seconds')
def epoch(value):return int(datetime.strptime(value,'%Y-%m-%d %H:%M:%S').replace(tzinfo=CST).timestamp()*1000)

DDL='''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draws(expect TEXT PRIMARY KEY,open_time TEXT NOT NULL,payload_json TEXT NOT NULL,payload_sha TEXT NOT NULL,received_at INTEGER NOT NULL,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS forecasts(expect TEXT PRIMARY KEY,created_at INTEGER NOT NULL,expected_open_at INTEGER NOT NULL,origin TEXT NOT NULL,model_version TEXT NOT NULL,training_through TEXT NOT NULL,digest TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,training_hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_forecast_update BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT,'frozen forecast cannot be updated'); END;
CREATE TRIGGER IF NOT EXISTS immutable_forecast_delete BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT,'frozen forecast cannot be deleted'); END;
CREATE TABLE IF NOT EXISTS settlements(expect TEXT NOT NULL,revision INTEGER NOT NULL,forecast_digest TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(expect,revision),FOREIGN KEY(expect) REFERENCES forecasts(expect));
CREATE TABLE IF NOT EXISTS training_runs(id TEXT PRIMARY KEY,model_version TEXT NOT NULL,through_expect TEXT NOT NULL,input_sha TEXT NOT NULL,created_at INTEGER NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training_events(expect TEXT NOT NULL,model_version TEXT NOT NULL,draw_sha TEXT NOT NULL,created_at INTEGER NOT NULL,before_sha TEXT NOT NULL,after_sha TEXT NOT NULL,PRIMARY KEY(expect,model_version,draw_sha));
CREATE TABLE IF NOT EXISTS model_state(model_version TEXT PRIMARY KEY,through_expect TEXT NOT NULL,input_sha TEXT NOT NULL,state_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fetch_audit(id TEXT PRIMARY KEY,url TEXT NOT NULL,fetched_at INTEGER NOT NULL,http_status INTEGER,raw_sha TEXT NOT NULL,raw_json TEXT NOT NULL,parser_version TEXT NOT NULL,errors_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draw_conflicts(id TEXT PRIMARY KEY,expect TEXT NOT NULL,old_sha TEXT NOT NULL,new_sha TEXT NOT NULL,payload_json TEXT NOT NULL,seen_at INTEGER NOT NULL,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS publication_receipts(expect TEXT NOT NULL,digest TEXT NOT NULL,first_published_at INTEGER NOT NULL,github_run_id TEXT,commit_sha TEXT,PRIMARY KEY(expect,digest),FOREIGN KEY(expect) REFERENCES forecasts(expect));
'''

def connect(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(path,timeout=30);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
 version=db.execute('PRAGMA user_version').fetchone()[0]
 if version==0:
  db.execute('PRAGMA journal_mode=DELETE');db.executescript(DDL);db.execute(f'PRAGMA user_version={SCHEMA_VERSION}');db.commit()
 elif version!=SCHEMA_VERSION:raise ValueError('Unsupported database schema version '+str(version))
 return db

def get_meta(db,key,default=None):
 row=db.execute('SELECT value_json FROM meta WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else default

def set_meta(db,key,value):
 text=dumps(value);old=db.execute('SELECT value_json FROM meta WHERE key=?',(key,)).fetchone()
 if old and old[0]==text:return False
 db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',(key,text));return True

def draws(db):return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM draws ORDER BY expect')]

def insert_draw(db,row,received,source):
 text=dumps(row);digest=sha(text);old=db.execute('SELECT payload_sha FROM draws WHERE expect=?',(row['expect'],)).fetchone()
 if old:
  if old[0]==digest:return 'same'
  key=sha({'expect':row['expect'],'old':old[0],'new':digest});db.execute('INSERT OR IGNORE INTO draw_conflicts VALUES(?,?,?,?,?,?,?)',(key,row['expect'],old[0],digest,text,received,source));return 'conflict'
 db.execute('INSERT INTO draws VALUES(?,?,?,?,?,?)',(row['expect'],row['openTime'],text,digest,received,source));return 'inserted'

def validate_forecast(envelope):
 p=envelope['prediction'];target=p['targetExpect']
 if not target.isdigit() or len(target)!=7 or not p['trainingThrough']<target:raise ValueError('invalid forecast training cutoff')
 if envelope['createdAt']>=envelope['expectedOpenTime']:raise ValueError('forecast at or after deadline')
 if sorted(p['numberRanking'])!=list(range(1,50)):raise ValueError('bad number ranking')
 for k in [36,24,16,8,4]:
  if p['numberSets'][str(k)]!=p['numberRanking'][:k]:raise ValueError('bad number set')
 for k in [9,6,4,2]:
  if p['zodiacSets'][str(k)]!=p['zodiacRanking'][:k]:raise ValueError('bad zodiac set')
 if len(p['probabilities'])!=49 or any(not 0<=x<=1 for x in p['probabilities']) or abs(sum(p['probabilities'])-1)>1e-6:raise ValueError('bad probabilities')
 return envelope

def lock_forecast(db,envelope):
 validate_forecast(envelope);p=envelope['prediction'];target=p['targetExpect'];old=db.execute('SELECT payload_json FROM forecasts WHERE expect=?',(target,)).fetchone()
 if old:return json.loads(old[0]),False
 expected=sha({'createdAt':envelope['createdAt'],'expectedOpenTime':envelope['expectedOpenTime'],'source':envelope['source'],'prediction':p})
 if envelope.get('digest') and envelope.get('origin')!='legacy-import' and envelope['digest']!=expected:raise ValueError('forecast digest mismatch')
 envelope=dict(envelope);envelope['digest']=envelope.get('digest') or expected;envelope['targetExpect']=target;envelope['modelVersion']=p['version'];envelope['origin']=envelope.get('origin','central');text=dumps(envelope)
 db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?,?,?,?,?)',(target,envelope['createdAt'],envelope['expectedOpenTime'],envelope['origin'],p['version'],p['trainingThrough'],envelope['digest'],text,p['trainingFingerprint']))
 return envelope,True

def forecasts(db):return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM forecasts ORDER BY expect')]

def latest_settlements(db):
 return [json.loads(r[0]) for r in db.execute('SELECT s.payload_json FROM settlements s INNER JOIN (SELECT expect,MAX(revision) AS rev FROM settlements GROUP BY expect) x ON s.expect=x.expect AND s.revision=x.rev ORDER BY s.expect')]

def settle(db,received):
 actual={r['expect']:r for r in draws(db)};changes=0
 for env in forecasts(db):
  target=env['targetExpect'];row=actual.get(target)
  if not row:continue
  p=env['prediction'];actual_hash=sha(row);prior=db.execute('SELECT revision,payload_json FROM settlements WHERE expect=? ORDER BY revision DESC LIMIT 1',(target,)).fetchone()
  before=env['createdAt']<epoch(row['openTime']);receipt=db.execute('SELECT first_published_at,commit_sha,github_run_id FROM publication_receipts WHERE expect=? AND digest=?',(target,env['digest'])).fetchone();published_before=bool(receipt and receipt['first_published_at']<epoch(row['openTime']))
  # An imported seed has no independent central public-release receipt.
  eligible=before and published_before and env['origin']=='central'
  if prior:
   prior_payload=json.loads(prior['payload_json'])
   if prior_payload['actualFingerprint']==actual_hash and prior_payload.get('publicationVerified')==published_before and prior_payload.get('eligible')==eligible:continue
  actual_z=row['zodiac'][6];revision=(prior['revision']+1 if prior else 1)
  s={'expect':target,'revision':revision,'status':'settled' if before else 'late','eligible':eligible,'generatedBeforeDraw':before,'publicationVerified':published_before,'origin':env['origin'],'actualNumber':row['numbers'][6],'actualZodiac':actual_z,'actualFingerprint':actual_hash,'observedAt':received,'forecastDigest':env['digest'],'numberHits':{str(k):row['numbers'][6] in p['numberSets'][str(k)] for k in [36,24,16,8,4]},'zodiacHits':{str(k):actual_z in p['zodiacSets'][str(k)] for k in [9,6,4,2]},'mappingChanged':p['zodiacMap'][str(row['numbers'][6])]!=actual_z,'publicationNote':'已收到公开部署回执且早于开奖' if eligible else '无开奖前中央部署回执，列为已记录核验，不计已公开前瞻命中'}
  db.execute('INSERT INTO settlements VALUES(?,?,?,?)',(target,revision,env['digest'],dumps(s)));changes+=1
 return changes

def integrity(db):
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failed')
 if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('SQLite foreign key failed')
 for row in db.execute('SELECT expect,digest,payload_json FROM forecasts ORDER BY expect'):
  env=validate_forecast(json.loads(row['payload_json']))
  if env['targetExpect']!=row['expect'] or env['prediction']['targetExpect']!=row['expect'] or env['digest']!=row['digest']:
   raise ValueError('frozen forecast metadata mismatch')
  if env.get('origin')=='central':
   expected=sha({'createdAt':env['createdAt'],'expectedOpenTime':env['expectedOpenTime'],'source':env['source'],'prediction':env['prediction']})
   if env['digest']!=expected:raise ValueError('frozen forecast digest mismatch')
 return True
