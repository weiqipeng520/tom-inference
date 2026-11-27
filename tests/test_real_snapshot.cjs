'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
let domLib;
for (const name of [path.join(__dirname, '../.test-tools/node_modules/jsdom'), 'jsdom']) {
  try { domLib = require(name); break; } catch (err) { if (err.code !== 'MODULE_NOT_FOUND') throw err; }
}
if (!domLib) throw Error('Install jsdom test dependency');
const { JSDOM, VirtualConsole } = domLib;
const site = path.resolve(process.argv[2] || path.join(__dirname, '../site'));
const html = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(site, 'assets/app.js'), 'utf8');
const snapshot = JSON.parse(fs.readFileSync(path.join(site, 'data.json'), 'utf8'));
const visitors = [];
function open() {
  const errors = [], vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.message));
  const dom = new JSDOM(html, { url: 'https://tom-example.github.io/tom-inference/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
  visitors.push(dom);
  dom.window.fetch = async url => {
    assert.equal(url, './data.json');
    return { ok: true, status: 200, json: async () => structuredClone(snapshot) };
  };
  dom.window.eval(script);
  return { doc: dom.window.document, errors };
}
(async () => {
  try {
    const a = open(), b = open();
    await new Promise(resolve => setImmediate(resolve));
    const focused = snapshot.system?.focus === 'six-zodiac';
    for (const { doc, errors } of [a, b]) {
      assert.deepEqual(errors, []);
      assert.equal(doc.title, 'Tom推演系统');
      assert.equal(doc.getElementById('forecast-digest').textContent, snapshot.currentForecast?.digest ?? '—');
      assert.equal(doc.querySelectorAll('#latest-balls .ball').length, 7);
      assert.equal(doc.querySelectorAll('#model-weights .weight-item').length, snapshot.training.models.length);
      assert.equal(doc.querySelectorAll('#score-grid .score-cell').length, snapshot.currentForecast ? 49 : 0);
      assert.equal(doc.querySelectorAll('#backtest-rows tr').length, snapshot.backtest.algorithms.length);
      assert.equal(doc.getElementById('history-total').textContent, `${snapshot.draws.length.toLocaleString('zh-CN')} 条`);
      if (focused) {
        for (const id of ['number-column', 'zodiac-tabs', 'backtest-number-control', 'backtest-zodiac-control']) assert.equal(doc.getElementById(id).hidden, true, id);
        assert.equal(doc.getElementById('six-review').hidden, false);
        assert.deepEqual([...doc.querySelectorAll('#zodiac-candidates .candidate-zodiac')].map(el => el.lastChild.textContent), snapshot.currentForecast?.prediction.zodiacSets['6'] ?? []);
      }
    }
    if (!focused && snapshot.currentForecast) {
      for (const [group, sizes] of [['number', [36, 24, 16, 8, 4]], ['zodiac', [9, 6, 4, 2]]]) {
        for (const n of sizes) {
          for (const {doc} of [a, b]) doc.querySelector(`#${group}-tabs [data-size="${n}"]`).click();
          const get = doc => [...doc.querySelectorAll(`#${group}-candidates .candidate-${group}`)].map(el => el.textContent);
          assert.equal(get(a.doc).length, n);
          assert.deepEqual(get(a.doc), get(b.doc));
        }
      }
    }
    console.log(JSON.stringify({ passed: true, realDraws: snapshot.draws.length, currentTarget: snapshot.currentForecast?.targetExpect, independentVisitorsAgree: true, focused }));
  } finally { visitors.forEach(dom => dom.window.close()); }
})().catch(err => { console.error(err); process.exitCode = 1; });
