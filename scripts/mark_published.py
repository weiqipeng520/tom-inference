#!/usr/bin/env python3
"""Record successful Pages deployment receipts, never prediction generation claims."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from .storage import connect,dumps,iso
ROOT=Path(__file__).resolve().parents[1]

def mark(root=ROOT,run_id=None,commit_sha=None,now=None):
 root=Path(root);now=int(time.time()*1000) if now is None else now
 # This file is the artifact actually deployed by the current workflow.
 snapshot=json.loads((root/'site/data.json').read_text(encoding='utf-8'));db=connect(root/'database/tom.sqlite');added=0
 try:
  with db:
   for env in snapshot['forecasts']:
    if env.get('origin')!='central':continue
    old=db.execute('SELECT digest FROM forecasts WHERE expect=?',(env['targetExpect'],)).fetchone()
    if not old or old['digest']!=env['digest']:raise ValueError('deployed forecast mismatches current DB')
    cursor=db.execute('INSERT OR IGNORE INTO publication_receipts VALUES(?,?,?,?,?)',(env['targetExpect'],env['digest'],now,run_id,commit_sha));added+=cursor.rowcount
 finally:db.close()
 print(dumps({'publishedReceiptsAdded':added,'publishedAt':iso(now),'githubRunId':run_id,'commitSha':commit_sha}));return added

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run-id');p.add_argument('--commit-sha');p.add_argument('--root',type=Path,default=ROOT);args=p.parse_args();mark(args.root,args.run_id,args.commit_sha)
