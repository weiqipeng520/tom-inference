from datetime import datetime, timedelta
from http.client import IncompleteRead
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import pipeline as p, storage as st, source, approve_correction as correction, six_review
def new_actual(period, day):
    return source.normalize({'expect':period,'openTime':day+' 21:32:32','numbers':[1,2,3,4,5,6,49],
            'zodiac':['马','蛇','龙','兔','虎','牛','马'],'type':'8'})

ROOT = Path(__file__).resolve().parents[1]
NOW = st.epoch('2026-11-27 10:50:00')

def successor(draw):
    expect, when=source.expected_successor(draw)
    return new_actual(expect,st.iso(when)[:10]), when+3600000


class NextVersionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/'database/tom.sqlite'
        self.path.parent.mkdir()
        shutil.copyfile(ROOT/'database/tom.sqlite', self.path)

    def test_old_endpoint_conflict_does_not_block_new_draw(self):
        with st.connect(self.path) as db:
            tip = st.draws(db)[-1]
            draw,now = successor(tip)
            def record(warnings): return {'id':'test', 'errors':warnings}
            responses = [([tip], record([{'expect':'2021001','error':'conflicting duplicate within response'}])), ([draw], record([]))]
            with patch.object(p, 'fetch', side_effect=responses), patch.object(p, 'audit_fetch'):
                rows, sync = p.acquire(db, now)
            self.assertIn(draw, rows)
            self.assertTrue(sync['success'])
            self.assertFalse(sync['blocked'])
            self.assertEqual(sync['blockedExpects'], ['2021001'])

    def test_conflict_at_confirmed_tip_blocks_forward(self):
        with st.connect(self.path) as db:
            tip = st.draws(db)[-1]
            conflicting = {**tip, 'numbers': list(reversed(tip['numbers']))}
            draw,now = successor(tip)
            added, conflicts, _ = p.ingest(db,[draw, conflicting],now)
            self.assertEqual(added,[])
            self.assertEqual(conflicts,[tip['expect']])
            self.assertEqual(st.draws(db)[-1],tip)

    def test_incomplete_http_body_retries(self):
        with patch('urllib.request.urlopen', side_effect=IncompleteRead(b'')) as get, patch.object(source.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'IncompleteRead'):
                source.fetch(source.LATEST,NOW)
        self.assertEqual(get.call_count,2)

    def test_correction_future_rejected_and_failed_retrain_rolls_back(self):
        with st.connect(self.path) as db:
            before = st.draws(db)[-1]
        now = st.epoch(before['openTime'])
        fixed = {**before,'openTime':(datetime.strptime(before['openTime'],'%Y-%m-%d %H:%M:%S')-timedelta(seconds=1)).isoformat(sep=' ')}
        future = {**before,'openTime':(datetime.strptime(before['openTime'],'%Y-%m-%d %H:%M:%S')+timedelta(seconds=1)).isoformat(sep=' ')}
        with self.assertRaisesRegex(ValueError,'future'):
            correction.approve(self.root,before['expect'],future,'test','reviewer',now)
        with patch.object(p,'train_db',side_effect=RuntimeError('retrain failed')):
            with self.assertRaisesRegex(RuntimeError,'retrain failed'):
                correction.approve(self.root,before['expect'],fixed,'test','reviewer',now)
        with st.connect(self.path) as db:
            self.assertEqual(st.draws(db)[-1],before)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='draw_revisions'").fetchone())

    def test_repeat_correction_finishes_failed_snapshot_export(self):
        with st.connect(self.path) as db:
            before = st.draws(db)[-1]
        # Only presentation metadata changes; training inputs are unchanged.
        now=st.epoch(before['openTime'])+3600000
        fixed = {**before,'wave': ['green' if w!='green' else 'red' for w in before['wave']]}
        write = p.write_json
        def fail_final(path, value):
            if path == self.root/'site/data.json': raise OSError('simulated export failure')
            write(path,value)
        with patch.object(p,'write_json',side_effect=fail_final):
            with self.assertRaisesRegex(OSError,'simulated export failure'):
                correction.approve(self.root,before['expect'],fixed,'test','reviewer',now)
        result=correction.approve(self.root,before['expect'],fixed,'test','reviewer',now)
        self.assertFalse(result['corrected'])
        self.assertEqual(p.read_json(self.root/'site/data.json')['latestDraw'],fixed)
        with st.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM draw_revisions').fetchone()[0],1)

    def test_six_metrics_only_use_the_matching_frozen_envelopes(self):
        zodiac=six_review.ZODIAC
        ranking=zodiac[:6]
        prediction={'zodiacMap':{str(n):zodiac[(n-1)%12] for n in range(1,50)},
                    'zodiacSets':{'6':ranking},'probabilities':[1/49]*49,
                    'models':[{'id':'online_softmax','probabilities':[1/49]*49}]}
        live={'targetExpect':'2026331','origin':'central','digest':'live','prediction':prediction}
        hit={'expect':'2026331','status':'settled','eligible':True,'forecastDigest':'live','actualZodiac':ranking[0]}
        initial=six_review.report([live],[hit])
        self.assertEqual((initial['hits'],initial['total']),(1,1))
        self.assertAlmostEqual(initial['coverageBaseline'],25/49)
        self.assertEqual(initial['shadow']['pairedTotal'],0)
        prediction['shadowSix']=six_review.shadow_six(prediction)
        paired=six_review.report([live],[hit])['shadow']
        self.assertEqual((paired['pairedTotal'],paired['liveHits'],paired['shadowHits']),(1,1,1))
        self.assertEqual(paired['decision'],'observe_only')
        for change in ({'forecastDigest':'other'},{'eligible':False},{'status':'late'}):
            self.assertEqual(six_review.report([live],[hit | change])['total'],0)
