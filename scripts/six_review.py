"""Score only published-before-draw six-zodiac sets; never change the live strategy."""
from models.tom_model import ZODIAC, _wilson

SHADOW_ID = 'softmax-shrink-six-v1'


def shadow_six(prediction):
    """Use fixed weights, independent of the seven released results."""
    mapping = prediction['zodiacMap']
    softmax = next(m['probabilities'] for m in prediction['models'] if m['id'] == 'online_softmax')
    score = dict.fromkeys(ZODIAC, 0.0)
    for i, (p, q) in enumerate(zip(prediction['probabilities'], softmax), 1):
        score[mapping[str(i)]] += 0.35 * p + 0.35 * q + 0.30 / 49
    ranked = sorted(ZODIAC, key=lambda z: (-score[z], ZODIAC.index(z)))
    return {'id': SHADOW_ID, 'six': ranked[:6]}


def report(forecasts, settlements):
    by_expect = {f['targetExpect']: f for f in forecasts}
    samples, paired = [], []
    for result in settlements:
        env = by_expect.get(result['expect'])
        if not env or env.get('origin') != 'central' or result.get('status') != 'settled' or result.get('eligible') is not True or env['digest'] != result.get('forecastDigest'):
            continue
        p = env['prediction']
        selected, mapping = p.get('zodiacSets', {}).get('6', []), p.get('zodiacMap', {})
        actual = result.get('actualZodiac')
        if len(selected) != 6 or len(set(selected)) != 6 or not set(selected) <= set(ZODIAC) or actual not in ZODIAC:
            continue
        if set(mapping) != {str(i) for i in range(1, 50)} or not set(mapping.values()) <= set(ZODIAC):
            continue
        # This is coverage under the frozen number-to-zodiac mapping, not an observed hit rate.
        baseline = sum(z in selected for z in mapping.values()) / 49
        samples.append((actual in selected, baseline, result.get('mappingChanged') is True))
        shadow = p.get('shadowSix') or {}
        six = shadow.get('six', [])
        if shadow.get('id') == SHADOW_ID and len(six) == len(set(six)) == 6 and set(six) <= set(ZODIAC):
            paired.append((actual in selected, actual in six, sum(z in six for z in mapping.values()) / 49))
    total = len(samples)
    hits = sum(x[0] for x in samples)
    n = len(paired)
    return {'hits': hits, 'total': total, 'coverageBaseline': sum(x[1] for x in samples) / total if total else None,
            'wilson95': _wilson(hits, total) if total else None, 'mappingMismatchCount': sum(x[2] for x in samples),
            'shadow': {'id':SHADOW_ID,'pairedTotal':n,'liveHits':sum(x[0] for x in paired),
                       'shadowHits':sum(x[1] for x in paired),'coverageBaseline':sum(x[2] for x in paired)/n if n else None,
                       'decision':'observe_only'}}
