import copy,hashlib,json,shutil,sqlite3,tempfile,unittest
from pathlib import Path
from scripts import pipeline as p,storage as s
from scripts.source import normalize,expected_successor,gap_between
from scripts.mark_published import mark
from scripts.verify import verify
ROOT=Path(__file__).resolve().parents[1]
NOW=s.epoch('2026-11-19 10:00:00')

def new_actual(period,date):
 return {'expect':period,'openTime':date+' 21:32:32','year':int(period[:4]),'numbers':[1,2,3,4,5,6,49],'zodiac':['马','蛇','龙','兔','虎','牛','马'],'wave':['red','red','blue','blue','green','green','green'],'type':'8'}

class PipelineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name)/'base';(cls.base/'seed').mkdir(parents=True)
  for name in ['draws.json','forecast-seed.json','backtest-results.json']:shutil.copy2(ROOT/'seed'/name,cls.base/'seed'/name)
  p.run(cls.base,offline=True,now=NOW)
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def fixture(self):
  tmp=tempfile.TemporaryDirectory();root=Path(tmp.name)/'repo';shutil.copytree(self.base,root);self.addCleanup(tmp.cleanup);return root
 def test_initial_seed_preserved_not_repredicted(self):
  root=self.fixture();seed=json.loads((root/'seed/forecast-seed.json').read_text())['entries'][0];db=s.connect(root/'database/tom.sqlite');f=s.forecasts(db)[0];db.close();self.assertEqual(f['prediction'],seed['prediction']);self.assertEqual(f['digest'],seed['digest']);self.assertEqual(f['origin'],'legacy-import')
 def test_no_new_draw_no_duplicate_training_or_forecast(self):
  root=self.fixture();db=root/'database/tom.sqlite';before=db.read_bytes();snap=(root/'site/data.json').read_bytes();result=p.run(root,offline=True,now=NOW+3600000)
  self.assertFalse(result['trained']);self.assertFalse(result['newForecast']);self.assertEqual(before,db.read_bytes());self.assertEqual(snap,(root/'site/data.json').read_bytes())
 def test_forecast_database_update_delete_blocked(self):
  root=self.fixture();db=s.connect(root/'database/tom.sqlite')
  with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE forecasts SET digest='bad'")
  with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM forecasts')
  db.close()
 def test_actual_updates_training_and_new_central_forecast(self):
  root=self.fixture();now=s.epoch('2026-11-19 22:00:00');r=p.run(root,now=now,incoming=[new_actual('2026323','2026-11-19')]);self.assertEqual(r['forecastTarget'],'2026324');self.assertTrue(r['trained']);self.assertTrue(r['newForecast']);snap=json.loads((root/'site/data.json').read_text());self.assertEqual(snap['training']['trainingCount'],2373);self.assertEqual(snap['training']['softmaxUpdates'],2328);self.assertEqual(snap['settlements'][0]['eligible'],False)
  db=s.connect(root/'database/tom.sqlite');self.assertEqual(db.execute('SELECT COUNT(*) FROM training_events').fetchone()[0],1);db.close();self.assertTrue(verify(root)['passed'])
 def test_repeated_actual_is_idempotent_and_frozen(self):
  root=self.fixture();row=new_actual('2026323','2026-11-19');now=s.epoch('2026-11-19 22:00:00');p.run(root,now=now,incoming=[row]);f=(root/'database/forecasts/2026324.json').read_bytes();r=p.run(root,now=now+60000,incoming=[row]);self.assertFalse(r['trained']);self.assertFalse(r['newForecast']);self.assertEqual(f,(root/'database/forecasts/2026324.json').read_bytes())
 def test_source_gap_blocks_advancing(self):
  root=self.fixture();r=p.run(root,now=s.epoch('2026-11-20 22:00:00'),incoming=[new_actual('2026324','2026-11-20')]);self.assertTrue(r['gaps']);self.assertEqual(r['latest'],'2026322');self.assertFalse(r['newForecast'])
 def test_batch_two_draws_observes_each_and_no_missed_backfill_forecast(self):
  root=self.fixture();r=p.run(root,now=s.epoch('2026-11-20 22:00:00'),incoming=[new_actual('2026323','2026-11-19'),new_actual('2026324','2026-11-20')]);self.assertEqual(r['forecastTarget'],'2026325');db=s.connect(root/'database/tom.sqlite');self.assertEqual(db.execute('SELECT COUNT(*) FROM training_events').fetchone()[0],2);self.assertIsNone(db.execute("SELECT 1 FROM forecasts WHERE expect='2026324'").fetchone());db.close()
 def test_past_deadline_does_not_generate_retrospective_forecast(self):
  root=self.fixture();r=p.run(root,now=s.epoch('2026-11-21 22:00:00'),incoming=[new_actual('2026323','2026-11-19')]);self.assertIsNone(r['forecastTarget']);self.assertEqual(r['status'],'target-deadline-passed-awaiting-draw')
 def test_conflicting_actual_quarantined_not_overwritten(self):
  root=self.fixture();db=s.connect(root/'database/tom.sqlite');last=s.draws(db)[-1];db.close();bad=copy.deepcopy(last);bad['numbers']=[1,2,3,4,5,6,49];r=p.run(root,now=NOW,incoming=[bad]);self.assertTrue(r['conflicts']);db=s.connect(root/'database/tom.sqlite');self.assertEqual(s.draws(db)[-1],last);self.assertEqual(db.execute('SELECT COUNT(*) FROM draw_conflicts').fetchone()[0],1);db.close()
 def test_forecast_published_receipt_enables_only_future_front_test(self):
  root=self.fixture();p.run(root,now=s.epoch('2026-11-19 22:00:00'),incoming=[new_actual('2026323','2026-11-19')]);self.assertEqual(mark(root,'test-run','test-commit',now=s.epoch('2026-11-19 22:01:00')),1)
  p.run(root,now=s.epoch('2026-11-20 22:00:00'),incoming=[new_actual('2026324','2026-11-20')]);snap=json.loads((root/'site/data.json').read_text());item=next(x for x in snap['settlements'] if x['expect']=='2026324');self.assertTrue(item['eligible']);self.assertTrue(item['publicationVerified'])
 def test_source_validation_numbers_type_and_year(self):
  r=new_actual('2026323','2026-11-19')
  for change in [{'type':'1'},{'numbers':[1,2,3,4,5,6,6]},{'openTime':'2025-11-19 21:32:32'},{'numbers':[1,2,3,4,5,6,50]}]:
   bad={**r,**change}
   with self.assertRaises(ValueError):normalize(bad)
 def test_utc8_explicit_schedule(self):
  target,when=expected_successor(new_actual('2026365','2026-12-31'));self.assertEqual(target,'2027001');self.assertEqual(s.iso(when),'2027-01-01T21:32:32+08:00')
 def test_snapshot_is_single_self_contained_publication(self):
  root=self.fixture();snap=json.loads((root/'site/data.json').read_text());db=s.connect(root/'database/tom.sqlite');self.assertEqual(snap['forecasts'],s.forecasts(db));db.close();copy_=copy.deepcopy(snap);h=copy_['publication'].pop('snapshotId');self.assertEqual(s.sha(copy_),h)

 def test_endpoint_disagreement_blocks_forward_ingestion(self):
  from unittest.mock import patch
  root=self.fixture();db=s.connect(root/'database/tom.sqlite');a=new_actual('2026323','2026-11-19');b=copy.deepcopy(a);b['numbers']=[7,8,9,10,11,12,13]
  def fetch_stub(url,now,year=None):
   row=a if '/history/' in url else b
   return [row],{'id':url,'url':url,'fetchedAt':now,'httpStatus':200,'rawSha':s.sha(row),'rawJson':s.dumps(row),'errors':[]}
  with patch.object(p,'fetch',side_effect=fetch_stub):batch,sync=p.acquire(db,s.epoch('2026-11-19 22:00:00'))
  self.assertTrue(sync['blocked']);self.assertFalse(any(r['expect']=='2026323' for r in batch));db.close()
 def test_freeze_rechecks_actual_clock_after_model_generation(self):
  from unittest.mock import patch
  root=self.fixture();now=s.epoch('2026-11-19 22:00:00');p.run(root,now=now,incoming=[new_actual('2026323','2026-11-19')]);db=s.connect(root/'database/tom.sqlite')
  # test a new period via an isolated temporary DB without an existing forecast
  with tempfile.TemporaryDirectory() as td:
   fresh=s.connect(Path(td)/'test.sqlite');row=new_actual('2026323','2026-11-19');s.insert_draw(fresh,row,now,'test');target,deadline=expected_successor(row)
   state=None
   with patch.object(p.model,'generate',return_value={}):env,created,status=p.next_forecast(fresh,state,deadline-1,clock=lambda:deadline+1)
   self.assertIsNone(env);self.assertFalse(created);self.assertEqual(status,'target-deadline-passed-awaiting-draw');fresh.close()
  db.close()

 def test_receipt_restored_after_settlement_requalifies_with_revision(self):
  root=self.fixture();p.run(root,now=s.epoch('2026-11-19 22:00:00'),incoming=[new_actual('2026323','2026-11-19')]);p.run(root,now=s.epoch('2026-11-20 22:00:00'),incoming=[new_actual('2026324','2026-11-20')]);db=s.connect(root/'database/tom.sqlite');env=next(x for x in s.forecasts(db) if x['targetExpect']=='2026324');self.assertFalse(next(x for x in s.latest_settlements(db) if x['expect']=='2026324')['eligible'])
  with db:db.execute('INSERT INTO publication_receipts VALUES(?,?,?,?,?)',('2026324',env['digest'],s.epoch('2026-11-19 22:01:00'),'recovered-run','commit'));self.assertEqual(s.settle(db,s.epoch('2026-11-20 22:10:00')),1)
  item=next(x for x in s.latest_settlements(db) if x['expect']=='2026324');self.assertTrue(item['eligible']);self.assertEqual(item['revision'],2);db.close()
 def test_null_number_source_field_is_structured_error(self):
  for key in ['numbers','zodiac']:
   with self.assertRaises(ValueError):normalize({**new_actual('2026323','2026-11-19'),key:None})
 def test_future_label_strictly_blocked(self):
  root=self.fixture();db=s.connect(root/'database/tom.sqlite')
  with self.assertRaises(ValueError):p.ingest(db,[new_actual('2026323','2026-11-19')],s.epoch('2026-11-19 21:32:02'))
  db.close()

if __name__=='__main__':unittest.main(verbosity=2)
