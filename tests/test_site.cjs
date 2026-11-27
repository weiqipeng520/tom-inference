'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let JSDOM, VirtualConsole;
for (const candidate of ['jsdom', path.join(__dirname, '../.test-tools/node_modules/jsdom'), '/root/workspace/macaujc-predict-20261119/.test-tools/node_modules/jsdom']) {
  try { ({ JSDOM, VirtualConsole } = require(candidate)); break; } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
}
if (!JSDOM) throw new Error('jsdom is missing. Install: npm install --prefix .test-tools jsdom@26.1.0');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'site/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'site/assets/app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'site/assets/style.css'), 'utf8');
const CACHE_KEY = 'tom-inference-publication-v1';
const clone = value => JSON.parse(JSON.stringify(value));

// Complete, synthetic public schema fixtures only. Never read or change data/ or the DB.
function fixture() {
  const now = Date.now();
  const numbers = Array.from({ length: 49 }, (_, i) => i + 1);
  const zodiacs = ['马', '蛇', '龙', '兔', '虎', '牛', '鼠', '猪', '狗', '鸡', '猴', '羊'];
  const probabilities = numbers.map(() => 1 / 49);
  const numberSets = Object.fromEntries([36, 24, 16, 8, 4].map(size => [size, numbers.slice(0, size)]));
  const zodiacSets = Object.fromEntries([9, 6, 4, 2].map(size => [size, zodiacs.slice(0, size)]));
  const models = ['dirichlet', 'exponential', 'markov', 'online_softmax'].map((id, i) => ({ id, name: ['Dirichlet 平滑', '指数衰减', 'Markov 转移', 'Online Softmax'][i], weight: [0.1, 0.2, 0.3, 0.4][i], probabilities: [...probabilities] }));
  const zodiacMap = Object.fromEntries(numbers.map((number, i) => [number, zodiacs[i % 12]]));
  const envelope = (expect, source = 'central') => ({
    targetExpect: expect, createdAt: now - 7200000, expectedOpenTime: now + 3600000, digest: `sha256-forecast-${expect}`, source, modelVersion: 'tom-online-2.0',
    prediction: { targetExpect: expect, trainingThrough: '2026322', trainingCount: 2372, trainingFingerprint: 'sha256-training-fixture', version: 'tom-online-2.0', numberRanking: [...numbers], numberSets: clone(numberSets), zodiacRanking: [...zodiacs], zodiacSets: clone(zodiacSets), models: clone(models), probabilities: [...probabilities], zodiacMap: { ...zodiacMap }, mappingNote: '测试中央生肖映射', modelNote: '独立 fixture：中央只读模型评分' }
  });
  const currentForecast = envelope('2026323');
  const forecasts = [envelope('2026319', 'legacy-import'), envelope('2026320'), envelope('2026321'), envelope('2026322'), clone(currentForecast)];
  const metric = (size, total, base) => ({ hits: Math.floor(total * base), total, rate: Math.floor(total * base) / total, baseline: base, wilsonLow: Math.max(0, base - 0.06), wilsonHigh: Math.min(1, base + 0.06) });
  const backtest = { modelVersion: 'tom-online-2.0', split: { testFirst: '2025323', testLast: '2026322', testCount: 365, method: 'walk-forward：每期仅用过去数据' }, algorithms: [...models, { id: 'ensemble', name: '中央融合' }, { id: 'uniform', name: '均匀基线' }].map(item => ({ id: item.id, name: item.name, numberHits: Object.fromEntries([36, 24, 16, 8, 4].map(size => [size, metric(size, 365, size / 49)])), zodiacHits: Object.fromEntries([9, 6, 4, 2].map(size => [size, metric(size, 365, size / 12)])), logLoss: 3.8918, brier: 0.9796 })), uniformLogLoss: 3.8918, notes: ['留出集滚动评估，不补造实时命中'] };
  const draws = Array.from({ length: 43 }, (_, i) => ({ expect: String(2026280 + i), openTime: `2026-11-${String(i % 18 + 1).padStart(2, '0')} 21:32:32`, year: 2026, numbers: [47, 31, 43, 17, 8, 30, i === 42 ? 7 : i % 49 + 1], zodiac: ['猴', '鼠', '鼠', '虎', '猪', '牛', '鼠'], wave: ['blue', 'blue', 'green', 'green', 'red', 'red', 'red'] }));
  return {
    schemaVersion: 1, system: { name: 'Tom推演系统', version: '3.0.0' },
    publication: { snapshotId: 'sha256-snapshot-fixture', generatedAt: new Date(now - 10000).toISOString(), lastTrainingAt: new Date(now - 7200000).toISOString(), sync: { checkedAt: new Date(now - 10000).toISOString(), success: true, lastSuccess: new Date(now - 10000).toISOString(), warnings: [], source: 'https://example.test/draw-source' } },
    latestDraw: clone(draws.at(-1)), nextDraw: { expect: '2026323', expectedOpenTime: now + 3600000, estimated: true, timezone: 'Asia/Shanghai' }, currentForecast, forecasts,
    settlements: [
      { expect: '2026319', status: 'settled', actualNumber: 5, actualZodiac: '鼠', observedAt: now, numberHits: { 36: true, 24: true, 16: true, 8: true, 4: false }, zodiacHits: { 9: true, 6: true, 4: false, 2: false }, forecastDigest: 'sha256-forecast-2026319', revision: 1, eligible: true },
      { expect: '2026320', status: 'settled', actualNumber: 42, actualZodiac: '鼠', observedAt: now, numberHits: { 36: false, 24: false, 16: false, 8: false, 4: false }, zodiacHits: { 9: true, 6: false, 4: false, 2: false }, forecastDigest: 'sha256-forecast-2026320', revision: 1, eligible: true },
      { expect: '2026321', status: 'late', actualNumber: 4, actualZodiac: '鼠', observedAt: now, numberHits: { 36: true, 24: true, 16: true, 8: true, 4: true }, zodiacHits: { 9: true, 6: true, 4: true, 2: true }, forecastDigest: 'sha256-forecast-2026321', revision: 1, eligible: true },
      { expect: '2026322', status: 'settled', actualNumber: 7, actualZodiac: '鼠', observedAt: now, numberHits: { 36: true, 24: true, 16: true, 8: true, 4: false }, zodiacHits: { 9: true, 6: true, 4: false, 2: false }, forecastDigest: 'sha256-forecast-2026322', revision: 1, eligible: true }
    ],
    training: { modelVersion: 'tom-online-2.0', throughExpect: '2026322', trainingCount: 2372, lastTrainingAt: new Date(now - 7200000).toISOString(), softmaxUpdates: 2327, weightUpdates: 2282, trainingFingerprint: 'sha256-training-fixture', traceHash: 'sha256-trace-fixture', models: models.map(({ id, name, weight }) => ({ id, name, weight })), eventCount: 1 },
    backtest, legacyBacktest: { note: '仅归档的旧报告' }, draws,
    coverage: { source: 'https://example.test/draw-source', rangeStart: '2020-05-18 21:32:32', rangeEnd: '2026-11-18 21:32:32', total: draws.length, warnings: [], errors: [] }
  };
}
async function flush() { await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)); }
async function openViewer(t, options = {}) {
  const errors = [];
  const console = new VirtualConsole(); console.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, { url: options.url || 'https://example.test/site/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: console });
  t.after(() => dom.window.close());
  const win = dom.window; const requests = []; const intervals = []; const downloads = [];
  const queue = [...(options.responses || [fixture()])];
  const storage = new Map(options.cached ? [[CACHE_KEY, JSON.stringify(options.cached)]] : []);
  Object.defineProperty(win, 'localStorage', { value: { getItem: key => storage.get(key) || null, setItem: (key, value) => { if (options.storageFail) { const error = new Error('quota exceeded'); error.name = 'QuotaExceededError'; throw error; } storage.set(key, value); } } });
  win.fetch = async (url, init) => {
    requests.push({ url, init }); const response = queue.shift();
    if (response?.stall) return new Promise(() => {});
    if (response instanceof Error) throw response;
    if (response && response.httpError) return { ok: false, status: response.httpError };
    if (response && response.invalidJSON) return { ok: true, status: 200, json: async () => { throw new SyntaxError('bad JSON'); } };
    return { ok: true, status: 200, json: async () => clone(response) };
  };
  win.setInterval = (fn, delay) => { intervals.push({ fn, delay }); return intervals.length; };
  const nativeTimeout = win.setTimeout.bind(win);
  win.setTimeout = (fn, delay) => delay === 12000 ? nativeTimeout(fn, options.fastTimeout ? 10 : delay) : (fn(), 1);
  win.Blob = Blob;
  win.URL.createObjectURL = blob => { downloads.push({ blob }); return `blob:fixture-${downloads.length}`; };
  win.URL.revokeObjectURL = () => {};
  win.HTMLAnchorElement.prototype.click = function () { const entry = downloads.at(-1); if (entry) entry.filename = this.download; };
  win.eval(script); await flush();
  assert.equal(errors.length, 0, errors.map(error => error.message).join('\n'));
  return { win, doc: win.document, requests, intervals, storage, downloads, queue, errors, refresh: async response => { queue.push(response); const timer = intervals.find(item => item.delay === 60000); assert.ok(timer, '60 second publication timer exists'); await timer.fn(); await flush(); } };
}

test('schema fixture has all candidate dimensions and 49-dimensional model scores', () => {
  const snapshot = fixture();
  assert.equal(snapshot.currentForecast.prediction.numberRanking.length, 49);
  assert.equal(snapshot.currentForecast.prediction.zodiacRanking.length, 12);
  assert.equal(snapshot.currentForecast.prediction.probabilities.length, 49);
  snapshot.currentForecast.prediction.models.forEach(model => assert.equal(model.probabilities.length, 49));
  for (const size of [36, 24, 16, 8, 4]) assert.equal(snapshot.currentForecast.prediction.numberSets[size].length, size);
  for (const size of [9, 6, 4, 2]) assert.equal(snapshot.currentForecast.prediction.zodiacSets[size].length, size);
});

test('title, central publication, seven latest balls, weights, history and backtest render', async t => {
  const page = await openViewer(t);
  assert.equal(page.doc.title, 'Tom推演系统');
  assert.equal(page.doc.querySelector('h1').textContent, 'Tom推演系统');
  assert.match(page.doc.body.textContent, /中央发布 · 全站一致/);
  assert.match(page.doc.body.textContent, /不进行本地训练、选号或重排/);
  assert.equal(page.doc.querySelectorAll('#latest-balls .ball').length, 7);
  assert.equal(page.doc.querySelector('#latest-balls .special .ball').textContent, '07');
  assert.match(page.doc.querySelector('#latest-time').textContent, /UTC\+8/);
  assert.equal(page.doc.querySelectorAll('#score-grid .score-cell').length, 49);
  assert.equal(page.doc.querySelectorAll('.weight-item').length, 4);
  assert.match(page.doc.querySelector('#model-weights').textContent, /40\.0%/);
  assert.equal(page.doc.querySelectorAll('#backtest-rows tr').length, 6);
  assert.match(page.doc.querySelector('#backtest-split').textContent, /walk-forward/);
  assert.equal(page.doc.querySelectorAll('#history-rows tr').length, 20);
  assert.match(page.doc.querySelector('#history-total').textContent, /43/);
  assert.equal(page.doc.querySelectorAll('#history-frequency .frequency-item').length, 49);
  assert.match(page.doc.querySelectorAll('#history-frequency .frequency-item')[6].textContent, /2 次/);
  assert.equal(page.doc.querySelector('#legacy-backtest-note').hidden, false);
  assert.equal(page.doc.querySelector('#notice').hidden, true);
});

test('two independent visitors read exactly the same frozen sets at every layer', async t => {
  const snapshot = fixture(); const original = JSON.stringify(snapshot);
  const a = await openViewer(t, { responses: [snapshot] }); const b = await openViewer(t, { responses: [snapshot] });
  for (const group of ['number', 'zodiac']) for (const size of group === 'number' ? [36, 24, 16, 8, 4] : [9, 6, 4, 2]) {
    for (const page of [a, b]) page.doc.querySelector(`#${group}-tabs [data-size="${size}"]`).click();
    const selector = `#${group}-candidates .candidate-${group}`;
    assert.equal(a.doc.querySelectorAll(selector).length, size);
    assert.equal(b.doc.querySelectorAll(selector).length, size);
    assert.deepEqual([...a.doc.querySelectorAll(selector)].map(item => item.textContent), [...b.doc.querySelectorAll(selector)].map(item => item.textContent));
    assert.equal(a.doc.querySelector(`#${group}-tabs [aria-selected="true"]`).dataset.size, String(size));
  }
  assert.equal(JSON.stringify(snapshot), original, 'source fixture stays untouched');
  assert.equal(a.doc.querySelector('#forecast-digest').textContent, snapshot.currentForecast.digest);
});

test('only local data.json is fetched, no-store and a 60s interval are mandatory', async t => {
  const page = await openViewer(t);
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, './data.json'); assert.equal(page.requests[0].init.cache, 'no-store');
  await page.refresh(fixture());
  assert.equal(page.requests.length, 2);
  assert.ok(page.requests.every(item => item.url === './data.json' && item.init.cache === 'no-store'));
  assert.ok(page.intervals.some(item => item.delay === 1000), 'countdown is updated independently');
});

test('HTTP error and malformed JSON keep all previously displayed content and the complete cache', async t => {
  const snapshot = fixture(); const page = await openViewer(t, { responses: [snapshot] });
  const fields = ['latest-balls', 'number-candidates', 'zodiac-candidates', 'forecast-records', 'model-weights', 'history-rows', 'backtest-rows'];
  const before = fields.map(id => page.doc.getElementById(id).textContent);
  const stored = page.storage.get(CACHE_KEY);
  assert.deepEqual(JSON.parse(stored), snapshot, 'entire publication JSON cached, including draws/report/records');
  await page.refresh({ httpError: 503 });
  assert.deepEqual(fields.map(id => page.doc.getElementById(id).textContent), before);
  assert.equal(page.storage.get(CACHE_KEY), stored);
  assert.match(page.doc.querySelector('#notice').textContent, /HTTP 503/);
  assert.match(page.doc.querySelector('#notice').textContent, /上次发布快照/);
  assert.match(page.doc.querySelector('#publication-time').textContent, /快照生成/);
  await page.refresh({ invalidJSON: true });
  assert.deepEqual(fields.map(id => page.doc.getElementById(id).textContent), before);
  assert.equal(page.storage.get(CACHE_KEY), stored);
  await page.refresh(snapshot);
  assert.equal(page.doc.querySelector('#notice').hidden, true);
});

test('new offline visitor restores entire cached snapshot and has working archive/backtest/downloads', async t => {
  const snapshot = fixture(); const page = await openViewer(t, { cached: snapshot, responses: [new Error('network offline')] });
  assert.equal(page.doc.querySelectorAll('#latest-balls .ball').length, 7);
  assert.equal(page.doc.querySelectorAll('#number-candidates .candidate-number').length, 16);
  assert.equal(page.doc.querySelectorAll('#backtest-rows tr').length, 6);
  assert.equal(page.doc.querySelectorAll('#history-rows tr').length, 20);
  assert.match(page.doc.querySelector('#connection-label').textContent, /离线/);
  assert.match(page.doc.querySelector('#notice').textContent, /发布时间/);
  page.doc.querySelector('#download-snapshot').click();
  assert.deepEqual(JSON.parse(await page.downloads[0].blob.text()), snapshot);
});

test('same-period digest conflict preserves the previous entire publication and download', async t => {
  const snapshot = fixture(); const page = await openViewer(t, { responses: [snapshot] });
  const changed = clone(snapshot); changed.publication.snapshotId = 'sha256-conflicting-snapshot'; changed.currentForecast.digest = 'sha256-conflict'; changed.currentForecast.prediction.numberSets[16] = Array.from({ length: 16 }, (_, i) => i + 20); changed.latestDraw.numbers[0] = 1;
  await page.refresh(changed);
  assert.match(page.doc.querySelector('#notice').textContent, /digest 冲突/);
  assert.equal(page.doc.querySelector('#forecast-digest').textContent, snapshot.currentForecast.digest);
  assert.equal(page.doc.querySelector('#latest-balls .ball').textContent, '47');
  assert.equal(page.doc.querySelector('#snapshot-id').textContent, snapshot.publication.snapshotId);
  assert.deepEqual(JSON.parse(page.storage.get(CACHE_KEY)), snapshot);
  page.doc.querySelector('#download-snapshot').click();
  assert.deepEqual(JSON.parse(await page.downloads[0].blob.text()), snapshot);
});

test('internally conflicting first publication is not accepted or cached', async t => {
  const snapshot = fixture(); snapshot.forecasts.at(-1).digest = 'sha256-contradicting-history';
  const page = await openViewer(t, { responses: [snapshot] });
  assert.match(page.doc.querySelector('#notice').textContent, /digest 冲突/);
  assert.equal(page.doc.querySelectorAll('#number-candidates .candidate-number').length, 0);
  assert.equal(page.storage.size, 0);
  assert.equal(page.doc.querySelector('#download-snapshot').disabled, true);
});

test('a new target can be published by the central snapshot, never by the client', async t => {
  const snapshot = fixture(); const page = await openViewer(t, { responses: [snapshot] });
  const next = clone(snapshot); next.currentForecast.targetExpect = '2026324'; next.currentForecast.prediction.targetExpect = '2026324'; next.currentForecast.digest = 'sha256-next'; next.forecasts.push(clone(next.currentForecast)); next.publication.snapshotId = 'sha256-next-snapshot'; next.nextDraw.expect = '2026324';
  await page.refresh(next);
  assert.match(page.doc.querySelector('#forecast-expect').textContent, /2026324/);
  assert.equal(page.doc.querySelector('#forecast-digest').textContent, 'sha256-next');
});

test('expired prediction and schedule are held, waiting label is prominent and no next period is fabricated', async t => {
  const snapshot = fixture(); snapshot.currentForecast.expectedOpenTime = Date.now() - 1000; snapshot.nextDraw.expectedOpenTime = Date.now() - 1000;
  const page = await openViewer(t, { responses: [snapshot] });
  assert.equal(page.doc.querySelector('#forecast-expired').hidden, false);
  assert.match(page.doc.querySelector('#forecast-expired').textContent, /等待中央训练\/下一期/);
  assert.match(page.doc.querySelector('#countdown').textContent, /等待中央确认并发布开奖结果/);
  assert.match(page.doc.querySelector('#forecast-expect').textContent, /2026323/);
  assert.doesNotMatch(page.doc.querySelector('#forecast-expect').textContent, /2026324/);
  const before = page.doc.querySelector('#number-candidates').textContent;
  page.intervals.find(item => item.delay === 1000).fn();
  assert.equal(page.doc.querySelector('#number-candidates').textContent, before);
  assert.equal(page.doc.querySelector('#forecast-digest').textContent, snapshot.currentForecast.digest);
});

test('history search, pagination and backtest layer controls actually work', async t => {
  const page = await openViewer(t);
  page.doc.querySelector('#history-next').click();
  assert.equal(page.doc.querySelector('#history-page').textContent, '2 / 3');
  page.doc.querySelector('#history-next').click();
  assert.equal(page.doc.querySelectorAll('#history-rows tr').length, 3);
  const search = page.doc.querySelector('#history-search'); search.value = '2026322'; search.dispatchEvent(new page.win.Event('input'));
  assert.equal(page.doc.querySelectorAll('#history-rows tr').length, 1);
  assert.match(page.doc.querySelector('#history-rows').textContent, /2026322/);
  assert.equal(page.doc.querySelector('#history-page').textContent, '1 / 1');
  search.value = 'no-such-draw'; search.dispatchEvent(new page.win.Event('input'));
  assert.match(page.doc.querySelector('#history-rows').textContent, /没有匹配/);
  const before = page.doc.querySelector('#backtest-rows').textContent;
  const select = page.doc.querySelector('#backtest-number-size'); select.value = '4'; select.dispatchEvent(new page.win.Event('change'));
  assert.notEqual(page.doc.querySelector('#backtest-rows').textContent, before);
  assert.match(page.doc.querySelector('#backtest-rows').textContent, /8\.2%/);
});

test('realtime excludes legacy imports, late settlements, duplicate old revisions and digest mismatch', async t => {
  const snapshot = fixture();
  snapshot.settlements.push({ ...clone(snapshot.settlements[3]), revision: 0, numberHits: { 16: false }, zodiacHits: { 6: false } });
  const page = await openViewer(t, { responses: [snapshot] });
  assert.match(page.doc.querySelector('#settlement-count').textContent, /^2 期有效/);
  assert.match(page.doc.querySelector('#live-summary').textContent, /1\/2/);
  assert.match(page.doc.querySelector('#forecast-records').textContent, /历史导入 · 不计分/);
  assert.match(page.doc.querySelector('#forecast-records').textContent, /延迟记录 · 不计分/);
  const mismatch = clone(snapshot); mismatch.settlements[3].forecastDigest = 'wrong-digest';
  await page.refresh(mismatch);
  assert.match(page.doc.querySelector('#settlement-count').textContent, /^1 期有效/);
});

test('malicious external text is rendered as text, never inserted as markup', async t => {
  const snapshot = fixture(); const attack = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>';
  snapshot.training.models[0].name = attack;
  snapshot.currentForecast.prediction.mappingNote = attack;
  snapshot.currentForecast.prediction.modelNote = attack;
  snapshot.backtest.algorithms[0].name = attack;
  snapshot.backtest.notes.push(attack);
  snapshot.publication.sync.warnings.push(attack);
  snapshot.publication.sync.source = attack;
  snapshot.coverage.warnings.push(attack);
  snapshot.draws[0].expect = attack;
  const page = await openViewer(t, { responses: [snapshot] });
  assert.equal(page.win.__pwned, undefined);
  assert.equal(page.doc.querySelectorAll('img').length, 0);
  assert.equal(page.doc.querySelectorAll('script').length, 1, 'only the declared local app script exists');
  for (const id of ['model-weights', 'mapping-note', 'model-note', 'backtest-rows', 'backtest-notes', 'publication-warnings', 'source-label', 'coverage-note']) assert.ok(page.doc.getElementById(id).textContent.includes(attack), id);
});

test('file protocol with no prior data gives serving instructions without inventing data', async t => {
  const page = await openViewer(t, { url: 'file:///project/site/index.html', responses: [new Error('Failed to fetch')] });
  assert.match(page.doc.querySelector('#notice').textContent, /python3 -m http\.server 8000/);
  assert.match(page.doc.querySelector('#notice').textContent, /GitHub Pages/);
  assert.equal(page.doc.querySelectorAll('#latest-balls .ball').length, 0);
  assert.equal(page.doc.querySelectorAll('#number-candidates .candidate-number').length, 0);
  assert.equal(page.doc.querySelector('#download-snapshot').disabled, true);
});

test('storage failure is visible but does not discard a valid snapshot', async t => {
  const page = await openViewer(t, { storageFail: true });
  assert.equal(page.doc.querySelectorAll('#latest-balls .ball').length, 7);
  assert.match(page.doc.querySelector('#notice').textContent, /缓存写入失败/);
  assert.match(page.doc.querySelector('#cache-state').textContent, /QuotaExceededError/);
  assert.equal(page.doc.querySelector('#download-snapshot').disabled, false);
});

test('JSON, current frozen envelope, CSV and DB links are complete and spreadsheet-safe', async t => {
  const snapshot = fixture(); snapshot.draws[0].expect = '=1+1';
  const page = await openViewer(t, { responses: [snapshot] });
  page.doc.querySelector('#download-forecast').click();
  assert.deepEqual(JSON.parse(await page.downloads[0].blob.text()), snapshot.currentForecast);
  assert.equal(page.downloads[0].filename, 'tom-forecast-2026323.json');
  page.doc.querySelector('#download-csv').click();
  const csv = await page.downloads[1].blob.text();
  assert.match(csv, /specialZodiac/); assert.match(csv, /"'=1\+1"/);
  assert.equal(csv.trim().split('\r\n').length, snapshot.draws.length + 1);
  assert.equal(page.doc.querySelector('a[download]').getAttribute('href'), './data/tom.sqlite');
});

test('static assets stay local, rendering is text-only and client has no inference implementation', () => {
  const dom = new JSDOM(html);
  for (const element of dom.window.document.querySelectorAll('script[src],link[href]')) assert.match(element.getAttribute('src') || element.getAttribute('href'), /^\.\/assets\//);
  assert.doesNotMatch(html + css, /https?:\/\/(?:[^\s"']+\.)?(?:unpkg|jsdelivr|cdnjs|googleapis|gstatic)\./i);
  assert.doesNotMatch(css, /@import|url\(\s*['"]?https?:/i);
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function|Math\.random|crypto\.getRandomValues/);
  assert.doesNotMatch(script, /function\s+(?:train|predict|generateForecast|fitModel|softmax|sampleNumbers)\b/i);
  assert.equal((script.match(/\bfetch\(/g) || []).length, 1);
  assert.match(script, /fetch\('\.\/data\.json', \{ cache: 'no-store', signal: controller\.signal \}\)/);
  assert.match(css, /grid-template-columns:1\.12fr 1fr/);
  assert.match(css, /@media\(max-width:330px\)/);
  assert.match(css, /\.table-scroll\{overflow-x:auto/);
  // Large tables may scroll inside their bounded region, never set the page width.
  assert.match(css, /\.panel\{min-width:0/);
  assert.match(css, /\.shell\{max-width:1256px;margin:auto/);
  assert.doesNotMatch(css, /(?:^|[;{])(?:width|min-width):100vw/);
  for (const rule of dom.window.document.styleSheets) assert.ok(rule);
  dom.window.close();
});


test('a timed-out publication request releases the polling lock', async t => {
  const page = await openViewer(t, { responses: [{ stall: true }], fastTimeout: true });
  await new Promise(resolve => setTimeout(resolve, 35));
  assert.match(page.doc.querySelector('#notice').textContent, /请求超时/);
  assert.equal(page.requests[0].init.signal.aborted, true);
  await page.refresh(fixture());
  assert.equal(page.requests.length, 2);
  assert.equal(page.doc.querySelector('#connection-label').textContent, '已同步中央发布');
});
