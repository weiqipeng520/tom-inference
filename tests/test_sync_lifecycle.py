import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import pipeline as p, storage as st, source

ROOT = Path(__file__).resolve().parents[1]


class SyncLifecycleTests(unittest.TestCase):
    def test_unchanged_draw_refreshes_clock_and_failure_preserves_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'database').mkdir()
            db_path = root/'database/tom.sqlite'
            shutil.copyfile(ROOT/'database/tom.sqlite', db_path)
            db = st.connect(db_path)
            try:
                draw = st.draws(db)[-1]
                previous = st.get_meta(db, 'sync', {})
                original = st.forecasts(db)
            finally:
                db.close()
            first = st.epoch(draw['openTime']) + 3600000
            ok = {'success': True, 'blocked': False, 'checkedAt': st.iso(first),
                  'lastSuccess': st.iso(first), 'source': source.SOURCE, 'warnings': []}
            with patch.object(p, 'acquire', return_value=([draw], ok)):
                result = p.run(root, now=first)
            report = json.loads((root/'site/data.json').read_text())
            self.assertEqual(result['added'], [])
            self.assertEqual(report['publication']['sync']['checkedAt'], st.iso(first))
            self.assertEqual(report['publication']['sync']['lastSuccess'], st.iso(first))
            self.assertEqual(report['coverage']['rangeEnd'], draw['openTime'])
            second = first + 600000
            failure = {**ok, 'success': False, 'lastSuccess': None, 'checkedAt': st.iso(second)}
            with patch.object(p, 'acquire', return_value=([], failure)):
                p.run(root, now=second)
            report = json.loads((root/'site/data.json').read_text())
            sync = report['publication']['sync']
            self.assertEqual(sync['checkedAt'], st.iso(second))
            self.assertEqual(sync['lastSuccess'], st.iso(first))
            self.assertFalse(sync['success'])
            self.assertEqual(report['latestDraw'], draw)
            self.assertEqual(report['forecasts'][:len(original)], original)
