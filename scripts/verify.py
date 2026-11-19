#!/usr/bin/env python3
"""Read-only verification of the authority DB, immutable exports and Pages snapshot."""
from __future__ import annotations
import hashlib,json,math,sqlite3
from pathlib import Path
from . import storage as st
from models import tom_model as model
ROOT=Path(__file__).resolve().parents[1]

def verify(root=ROOT):
 root=Path(root);path=root/'database/tom.sqlite';db=sqlite3.connect(f'file:{path}?mode=ro',uri=True);db.row_factory=sqlite3.Row
 try:
  st.integrity(db);snap=json.loads((root/'site/data.json').read_text(encoding='utf-8'));copy=json.loads(json.dumps(snap));expected=copy['publication'].pop('snapshotId');assert st.sha(copy)==expected,'snapshot digest mismatch'
  assert snap['schemaVersion']==1 and snap['system']['name']=='Tom推演系统'
  rows=st.draws(db);assert snap['draws']==rows;assert snap['latestDraw']==rows[-1]
  fs=st.forecasts(db);assert snap['forecasts']==fs
  for f in fs:
   st.validate_forecast(f);target=f['targetExpect'];file=json.loads((root/'database/forecasts'/f'{target}.json').read_text());assert file==f;assert json.loads((root/'site/data/forecasts'/f'{target}.json').read_text())==f
  assert snap['currentForecast'] is None or snap['currentForecast']['targetExpect']==snap['nextDraw']['expect']
  model_record=db.execute('SELECT state_json,input_sha FROM model_state WHERE model_version=?',(model.VERSION,)).fetchone();state=json.loads(model_record['state_json']);normalized=model.canonical_history(rows);assert state['n']==len(rows);assert state['through_fingerprint']==model.fingerprint(normalized)==model_record['input_sha']
  weights=model.forecast(state)['weights'];assert abs(sum(weights)-1)<1e-8
  if (root/'site/data/tom.sqlite').exists():assert (root/'site/data/tom.sqlite').read_bytes()==path.read_bytes(),'SQLite download differs from authority'
  for s in snap['settlements']:assert any(f['targetExpect']==s['expect'] and f['digest']==s['forecastDigest'] for f in fs)
  for a in snap['backtest']['algorithms']:
   assert math.isfinite(a['logLoss']) and math.isfinite(a['brier'])
  return {'passed':True,'draws':len(rows),'forecasts':len(fs),'settlements':len(snap['settlements']),'snapshotId':expected,'trainedThrough':state['through_expect'],'modelVersion':model.VERSION,'sqliteIntegrity':'ok','foreignKeys':'ok','forecastFilesImmutable':True}
 finally:db.close()

if __name__=='__main__':print(st.dumps(verify()))
