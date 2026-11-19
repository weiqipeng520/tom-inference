import copy,json,math,unittest
from pathlib import Path
from models import tom_model as m
ROOT=Path(__file__).resolve().parents[1]
ROWS=json.loads((ROOT/'seed/draws.json').read_text())['records']

class ModelTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.state=m.train(ROWS)
 def test_probability_weight_normalized(self):
  f=m.forecast(self.state)
  self.assertAlmostEqual(sum(f['probabilities']),1,12);self.assertAlmostEqual(sum(f['weights']),1,12)
  self.assertEqual(len(f['models']),5);self.assertTrue(all(x>0 for x in f['probabilities']))
 def test_honest_feature_window_normalizers(self):
  x=m.features(self.state);self.assertEqual(len(x),m.FEATURE_COUNT)
  self.assertAlmostEqual(sum(x[50:99]),1,12);self.assertAlmostEqual(sum(x[99:148]),1,12)
 def test_training_resumes_exactly(self):
  prefix=m.train(ROWS[:-2]);resumed=m.train(ROWS,prefix)
  self.assertEqual(resumed,self.state)
 def test_new_outcome_updates_sgd_weights(self):
  before=m.train(ROWS[:-1]);weights=copy.deepcopy(before['online_weights']);after=m.train(ROWS,before)
  self.assertNotEqual(weights,after['online_weights']);self.assertEqual(after['softmax_updates'],len(ROWS)-m.PARAMS['softmax_warmup'])
 def test_deterministic_generation_and_nested_sets(self):
  p=m.generate(ROWS,'2026323',copy.deepcopy(self.state));q=m.generate(ROWS,'2026323',copy.deepcopy(self.state));self.assertEqual(p,q)
  for k in [36,24,16,8,4]:self.assertEqual(p['numberSets'][str(k)],p['numberRanking'][:k])
  for k in [9,6,4,2]:self.assertEqual(p['zodiacSets'][str(k)],p['zodiacRanking'][:k])
 def test_future_rows_excluded_before_result_validation(self):
  prefix=ROWS[:-1];future=copy.deepcopy(ROWS[-1]);future['numbers']=['junk'];future['openTime']='bad';future['zodiac']=[]
  self.assertEqual(m.generate(prefix,'2026322'),m.generate(prefix+[future],'2026322'))
 def test_training_prefix_change_replays(self):
  old=m.train(ROWS[:-1]);changed=copy.deepcopy(ROWS);changed[0]['numbers'][-1]=49 if 49 not in changed[0]['numbers'] else 1
  if len(set(changed[0]['numbers']))!=7:self.skipTest('fixture selected duplicate')
  self.assertEqual(m.train(changed,old),m.train(changed))
 def test_predict_then_observe_no_current_leakage(self):
  prefix=m.train(ROWS[:-1]);pred=m.forecast(prefix);unchanged=copy.deepcopy(pred);m.observe(prefix,m.canonical(ROWS[-1]),pred)
  self.assertEqual(pred,unchanged);self.assertNotEqual(pred['probabilities'],m.forecast(prefix)['probabilities'])
 def test_single_period_backtest_matches_prefix_prediction(self):
  # One target after burn-in; independently compare proper scores to forecast(prefix).
  subset=ROWS[-500:];prefix=m.train(subset[:-1]);p=m.forecast(prefix)['probabilities'];target=subset[-1]['numbers'][6]-1
  report=m.backtest(subset,holdout=1,burnin=365);a=next(x for x in report['algorithms'] if x['id']=='ensemble')
  self.assertAlmostEqual(a['logLoss'],-math.log(p[target]),12)
  self.assertAlmostEqual(a['brier'],sum((x-(1 if i==target else 0))**2 for i,x in enumerate(p)),12)
 def test_uniform_baseline_is_math_not_advertising(self):
  result=m.backtest(ROWS[-400:],holdout=10,burnin=365);a=next(x for x in result['algorithms'] if x['id']=='uniform');self.assertAlmostEqual(a['logLoss'],math.log(49),12)
 def test_training_state_version_checked(self):
  state=copy.deepcopy(self.state);state['version']='mismatched'
  with self.assertRaises(ValueError):m.train(ROWS,state)

if __name__=='__main__':unittest.main(verbosity=2)
