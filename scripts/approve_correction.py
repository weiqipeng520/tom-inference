#!/usr/bin/env python3
"""Explicit maintainer correction, preserving the old draw and all frozen forecasts."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from . import storage as st
from .source import normalize
from .pipeline import run
ROOT=Path(__file__).resolve().parents[1]

def approve(root,expect,replacement,reason,approved_by,now=None):
 if not reason.strip() or not approved_by.strip():raise ValueError('correction reason and reviewer required')
 now=int(time.time()*1000) if now is None else now;root=Path(root);row=normalize(replacement)
 if row['expect']!=expect:raise ValueError('replacement must match requested period')
 db=st.connect(root/'database/tom.sqlite')
 try:
  with db:
   db.execute('CREATE TABLE IF NOT EXISTS draw_revisions(expect TEXT NOT NULL,revision INTEGER NOT NULL,changed_at INTEGER NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,old_json TEXT NOT NULL,new_json TEXT NOT NULL,PRIMARY KEY(expect,revision))')
   old=db.execute('SELECT payload_json FROM draws WHERE expect=?',(expect,)).fetchone()
   if not old:raise ValueError('cannot correct a missing original draw')
   old_json=old[0];new_json=st.dumps(row)
   if old_json==new_json:return {'changed':False}
   rev=db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM draw_revisions WHERE expect=?',(expect,)).fetchone()[0]
   db.execute('INSERT INTO draw_revisions VALUES(?,?,?,?,?,?,?)',(expect,rev,now,approved_by,reason,old_json,new_json))
   db.execute('UPDATE draws SET open_time=?,payload_json=?,payload_sha=?,received_at=?,source=? WHERE expect=?',(row['openTime'],new_json,st.sha(new_json),now,'approved-correction',expect))
   st.set_meta(db,'last_business_change',now)
 finally:db.close()
 # Full replay is automatically detected from input/prefix hashes. Forecasts remain SQL-immutable.
 return run(root,offline=True,now=now)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--expect',required=True);p.add_argument('--replacement',type=Path,required=True);p.add_argument('--reason',required=True);p.add_argument('--reviewer',required=True);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();approve(a.root,a.expect,json.loads(a.replacement.read_text()),a.reason,a.reviewer)
