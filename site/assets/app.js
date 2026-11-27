/* Read-only publication viewer. There is deliberately no training or prediction engine. */
(() => {
  'use strict';
  const CACHE_KEY = 'tom-inference-publication-v1';
  const PAGE_SIZE = 20;
  const NUMBER_SIZES = [36, 24, 16, 8, 4];
  const ZODIAC_SIZES = [9, 6, 4, 2];
  const $ = id => document.getElementById(id);
  const list = value => Array.isArray(value) ? value : [];
  const text = value => value === undefined || value === null || value === '' ? '—' : String(value);
  const isNumeric = value => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value));
  const fixed = (value, digits = 4) => isNumeric(value) ? Number(value).toFixed(digits) : '—';
  const percent = value => isNumeric(value) ? `${(Number(value) * 100).toFixed(1)}%` : '—';
  const pad = value => String(value).padStart(2, '0');
  const set = (id, value) => { $(id).textContent = text(value); };
  const state = { snapshot: null, offline: true, error: '', conflict: '', cache: '尚未写入', cacheFailed: false, numberSize: 16, zodiacSize: 6, historyPage: 0, query: '', loading: false };

  function node(tag, content, className) {
    const result = document.createElement(tag);
    if (content !== undefined && content !== null) result.textContent = String(content);
    if (className) result.className = className;
    return result;
  }
  function replace(id, children) { $(id).replaceChildren(...children); }
  function empty(message) { return node('p', message, 'empty'); }
  function emptyRow(columns, message) {
    const row = node('tr'); const cell = node('td', message, 'empty'); cell.colSpan = columns; row.append(cell); return row;
  }
  function toEpoch(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : NaN;
    if (typeof value !== 'string' || !value) return NaN;
    // Raw draw timestamps are source-local UTC+8, never browser-local time.
    const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value) ? value.replace(' ', 'T') + '+08:00' : value;
    return Date.parse(normalized);
  }
  function time(value) {
    const epoch = toEpoch(value);
    if (!Number.isFinite(epoch)) return '—';
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(epoch)).replaceAll('/', '-');
  }
  function count(value) { return isNumeric(value) ? Number(value).toLocaleString('zh-CN') : '—'; }
  function validateSnapshot(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.schemaVersion !== 1 || !value.publication || typeof value.publication.snapshotId !== 'string' || !value.publication.snapshotId) throw new Error('发布 JSON 的 schemaVersion / snapshotId 无效');
    if (value.currentForecast && (!value.currentForecast.prediction || !value.currentForecast.targetExpect || !value.currentForecast.digest)) throw new Error('中央冻结预测缺少目标、摘要或 prediction');
    return value;
  }
  function envelopeList(snapshot) {
    return [...list(snapshot.forecasts), snapshot.currentForecast].filter(item => item && item.targetExpect && item.digest);
  }
  function digestConflict(incoming) {
    const known = new Map(envelopeList(state.snapshot || {}).map(item => [String(item.targetExpect), item.digest]));
    for (const item of envelopeList(incoming)) {
      const expect = String(item.targetExpect);
      if (known.has(expect) && known.get(expect) !== item.digest) return `第 ${text(item.targetExpect)} 期中央 digest 冲突；${state.snapshot ? '保留上次完整发布快照' : '等待中央核对发布'}，不修改冻结候选。`;
      known.set(expect, item.digest);
    }
    return '';
  }
  function renderNotice() {
    const messages = [];
    if (state.conflict) messages.push(state.conflict);
    if (state.error) messages.push(state.error);
    if (state.offline && state.snapshot) messages.push(`正在显示完整上次发布快照 · 发布时间 ${time(state.snapshot.publication.generatedAt)}（UTC+8），不是实时数据。`);
    if (state.cacheFailed) messages.push('本机缓存写入失败；当前页面仍保留完整快照，关闭页面后离线副本可能不可用。');
    $('notice').hidden = messages.length === 0;
    set('notice', messages.join('\n'));
    set('cache-state', state.cache);
    set('connection-label', state.conflict ? '摘要冲突 · 保留原发布' : state.offline ? (state.snapshot ? '离线 · 上次发布快照' : '等待中央发布') : '已同步中央发布');
  }
  function persist(snapshot) {
    try {
      // Store the complete JSON, not derived sets, partial rows or a fabricated projection.
      window.localStorage.setItem(CACHE_KEY, JSON.stringify(snapshot));
      state.cache = `完整快照已缓存 · ${time(snapshot.publication.generatedAt)}`;
      state.cacheFailed = false;
    } catch (error) {
      state.cache = `写入失败 · ${error.name || 'StorageError'}`;
      state.cacheFailed = true;
    }
  }
  async function refreshSnapshot() {
    if (state.loading) return;
    state.loading = true;
    const controller = new AbortController();
    let timer;
    try {
      const read = async () => {
        const response = await fetch('./data.json', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return validateSnapshot(await response.json());
      };
      const timeout = new Promise((_, reject) => {
        timer = window.setTimeout(() => { reject(new Error('请求超时')); controller.abort(); }, 12000);
      });
      const incoming = await Promise.race([read(), timeout]);
      const previous = state.snapshot;
      if (previous && toEpoch(incoming.publication.generatedAt) < toEpoch(previous.publication.generatedAt)) {
        throw new Error('发布节点返回了比当前快照更早的数据');
      }
      const conflict = digestConflict(incoming);
      if (conflict) {
        state.conflict = conflict; state.error = ''; state.offline = true; renderNotice(); return;
      }
      state.snapshot = incoming; state.offline = false; state.error = ''; state.conflict = '';
      persist(incoming); renderSnapshot();
    } catch (error) {
      state.offline = true;
      state.error = `发布读取失败（${text(error.message)}），${state.snapshot ? '保留上次完整发布。' : '暂无可展示的真实发布数据。'}`;
      if (window.location.protocol === 'file:') state.error += ' 本地 file:// 请在仓库根目录运行 python3 -m http.server 8000 后访问 http://localhost:8000/site/，或打开部署后的 GitHub Pages 网址。';
      renderNotice();
    } finally { window.clearTimeout(timer); state.loading = false; }
  }
  function ballClass(wave) {
    return ({ red: 'red', blue: 'blue', green: 'green', '红': 'red', '紅': 'red', '蓝': 'blue', '藍': 'blue', '绿': 'green', '綠': 'green' })[wave] || '';
  }
  function drawBall(number, zodiac, wave, special) {
    const wrap = node('div', null, `ball-wrap${special ? ' special' : ''}`);
    const ball = node('span', isNumeric(number) ? pad(number) : text(number), `ball ${ballClass(wave)}`);
    ball.setAttribute('aria-label', `${special ? '特别号' : '正码'} ${text(number)} ${text(zodiac)}`);
    wrap.append(ball, node('span', `${text(zodiac)}${special ? ' · 特' : ''}`, 'ball-zodiac'));
    return wrap;
  }
  function renderDraw() {
    const draw = state.snapshot.latestDraw;
    if (!draw) { replace('latest-balls', [empty('中央尚未发布开奖')]); return; }
    set('latest-expect', `第 ${text(draw.expect)} 期`);
    set('latest-time', `${time(draw.openTime)} UTC+8`);
    replace('latest-balls', list(draw.numbers).map((number, index) => drawBall(number, list(draw.zodiac)[index], list(draw.wave)[index], index === 6)));
  }
  function forecastExpired() {
    const snapshot = state.snapshot;
    if (!snapshot || !snapshot.currentForecast) return false;
    const forecast = snapshot.currentForecast;
    const expected = toEpoch(forecast.expectedOpenTime);
    const drawn = snapshot.latestDraw && String(snapshot.latestDraw.expect).localeCompare(String(forecast.targetExpect), 'en', { numeric: true }) >= 0;
    return drawn || (Number.isFinite(expected) && Date.now() >= expected);
  }
  function tick() {
    if (!state.snapshot) return;
    const schedule = state.snapshot.nextDraw;
    const epoch = schedule && toEpoch(schedule.expectedOpenTime);
    const remaining = epoch - Date.now();
    const countdown = $('countdown');
    countdown.classList.toggle('is-expired', Number.isFinite(epoch) && remaining <= 0);
    if (!Number.isFinite(epoch)) {
      countdown.textContent = '--:--:--'; set('schedule-label', '中央尚未发布预计时间');
    } else {
      set('schedule-label', `第 ${text(schedule.expect)} 期 · 预计 ${time(epoch)} UTC+8${schedule.estimated ? '（估计）' : ''}`);
      if (remaining <= 0) {
        const sync = state.snapshot.publication.sync || {};
        countdown.textContent = sync.blocked ? '有冲突或缺期，等待核对' : sync.success === false ? '取数失败，保留已发布开奖' : '等待中央确认并发布开奖结果';
      }
      else {
        const seconds = Math.floor(remaining / 1000);
        const hours = Math.floor(seconds / 3600);
        countdown.replaceChildren(node('b', pad(hours)), node('span', ':'), node('b', pad(Math.floor(seconds % 3600 / 60))), node('span', ':'), node('b', pad(seconds % 60)));
        for (const part of countdown.querySelectorAll('b')) part.style.fontWeight = '400';
      }
    }
    const expired = forecastExpired();
    $('forecast-expired').hidden = !expired;
    set('forecast-state', expired ? '已过预计时间 · 原预测保留' : state.snapshot.currentForecast ? '已冻结 · 不可覆盖' : '等待发布');
  }
  function renderCandidates() {
    const prediction = state.snapshot?.currentForecast?.prediction;
    for (const group of ['number', 'zodiac']) {
      const isNumber = group === 'number';
      const size = isNumber ? state.numberSize : state.zodiacSize;
      const values = prediction && prediction[isNumber ? 'numberSets' : 'zodiacSets'];
      const candidates = values && list(values[String(size)]);
      $(`${group}-tabs`).querySelectorAll('button').forEach(button => {
        const selected = Number(button.dataset.size) === size;
        button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
      });
      set(`${group}-count`, candidates ? `已发布 ${candidates.length} ${isNumber ? '码' : '肖'}` : '中央待发布');
      replace(`${group}-candidates`, candidates && candidates.length ? candidates.map((value, index) => {
        const item = node('span', isNumber && isNumeric(value) ? pad(value) : text(value), `candidate-${group}`);
        if (!isNumber) item.prepend(node('small', pad(index + 1)));
        return item;
      }) : [empty('暂无该层中央候选')]);
    }
  }
  function renderForecast() {
    const forecast = state.snapshot.currentForecast;
    renderCandidates();
    if (!forecast) {
      set('forecast-expect', '中央尚未发布');
      for (const id of ['forecast-trained', 'forecast-version', 'forecast-created', 'forecast-digest', 'forecast-fingerprint', 'forecast-source', 'mapping-note', 'model-note']) set(id, '—');
      replace('score-grid', []); return;
    }
    const prediction = forecast.prediction;
    set('forecast-expect', `第 ${text(forecast.targetExpect)} 期`);
    set('forecast-trained', `训练截止 ${text(prediction.trainingThrough)} · ${count(prediction.trainingCount)} 条`);
    set('forecast-version', `模型 ${text(forecast.modelVersion || prediction.version)}`);
    set('forecast-created', `冻结 ${time(forecast.createdAt)} UTC+8`);
    set('forecast-digest', forecast.digest);
    set('forecast-fingerprint', prediction.trainingFingerprint);
    set('forecast-source', forecast.source === 'legacy-import' ? 'legacy-import · 历史导入，不补造开奖前成绩' : text(forecast.source));
    set('mapping-note', prediction.mappingNote || '生肖候选及映射由中央快照提供，页面不自行换年映射。');
    set('model-note', prediction.modelNote || '模型说明尚未发布');
    replace('score-grid', list(prediction.probabilities).map((score, index) => {
      const cell = node('div', null, 'score-cell'); cell.append(node('b', pad(index + 1)), node('span', fixed(score, 4))); return cell;
    }));
  }
  function metric(label, value) {
    const item = node('div', null, 'metric'); item.append(node('strong', count(value)), node('span', label)); return item;
  }
  function renderTraining() {
    const training = state.snapshot.training;
    if (!training) { replace('training-metrics', [empty('暂无中央训练状态')]); replace('model-weights', [empty('暂无发布权重')]); return; }
    set('training-version', training.modelVersion);
    replace('training-metrics', [metric('训练样本', training.trainingCount), metric('Softmax 更新', training.softmaxUpdates), metric('权重更新', training.weightUpdates), metric('训练事件', training.eventCount)]);
    const models = list(training.models).length ? training.models : list(state.snapshot.currentForecast?.prediction?.models);
    replace('model-weights', models.length ? models.map(model => {
      const item = node('div', null, 'weight-item');
      const heading = node('div', null, 'weight-heading'); heading.append(node('span', model.name || model.id), node('b', percent(model.weight)));
      const track = node('div', null, 'weight-track'); const fill = node('div', null, 'weight-fill');
      fill.style.width = `${isNumeric(model.weight) ? Math.max(0, Math.min(100, Number(model.weight) * 100)) : 0}%`;
      track.append(fill); item.append(heading, track); return item;
    }) : [empty('暂无发布权重')]);
    set('training-time', `训练截止第 ${text(training.throughExpect)} 期 · 最后训练 ${time(training.lastTrainingAt || state.snapshot.publication.lastTrainingAt)} UTC+8`);
    set('training-fingerprint', training.trainingFingerprint); set('trace-hash', training.traceHash);
  }
  function settlementEligible(item, envelopes) {
    const envelope = envelopes.get(String(item.expect));
    // Eligibility is issued by the server, not reconstructed from historical results.
    return item.status === 'settled' && item.eligible === true && !!envelope && envelope.source !== 'legacy-import' && item.forecastDigest === envelope.digest;
  }
  function mark(value) { return value === true ? '命中' : value === false ? '未中' : '—'; }
  function liveStat(label, hits, total) {
    const result = node('div', null, 'live-stat'); result.append(node('strong', total ? `${hits}/${total}` : '—'), node('span', `${label} · ${total ? percent(hits / total) : '尚无有效结算'}`)); return result;
  }
  function renderRecords() {
    const snapshot = state.snapshot;
    const envelopes = new Map();
    for (const envelope of envelopeList(snapshot)) envelopes.set(String(envelope.targetExpect), envelope);
    const settlements = new Map();
    for (const item of list(snapshot.settlements)) {
      const previous = settlements.get(String(item.expect));
      if (!previous || Number(item.revision || 0) >= Number(previous.revision || 0)) settlements.set(String(item.expect), item);
    }
    const eligible = [...settlements.values()].filter(item => settlementEligible(item, envelopes));
    set('settlement-count', `${eligible.length} 期有效结算`);
    function aggregate(group, size) {
      const valid = eligible.filter(item => typeof item[group]?.[size] === 'boolean');
      return [valid.filter(item => item[group][size]).length, valid.length];
    }
    const focused = snapshot.system?.focus === 'six-zodiac';
    $('number-result-heading').hidden = focused;
    replace('live-summary', [...(focused ? [] : [liveStat('16 码实时', ...aggregate('numberHits', '16'))]), liveStat('6 肖前瞻', ...aggregate('zodiacHits', '6'))]);
    const review = snapshot.sixReview;
    $('six-review').hidden = !review;
    if (review) {
      const range = review.wilson95 ? ` · 95% Wilson 区间 ${review.wilson95.map(percent).join('–')}` : '';
      set('six-review', `六肖 ${review.hits}/${review.total} · 冻结映射覆盖基线 ${percent(review.coverageBaseline)}${range} · 映射与实际不一致 ${review.mappingMismatchCount} 期 · ${review.shadow.pairedTotal ? `同期对照：现行 ${review.shadow.liveHits}/${review.shadow.pairedTotal}，候选 ${review.shadow.shadowHits}/${review.shadow.pairedTotal}` : '并行候选尚无前瞻开奖样本'}（仅观察，不替换当前策略）`);
    }
    const resultColumns = focused ? [['zodiacHits', '6']] : [['numberHits', '16'], ['zodiacHits', '6']];
    const expects = [...new Set([...envelopes.keys(), ...settlements.keys()])].sort((a, b) => b.localeCompare(a, 'en', { numeric: true }));
    replace('forecast-records', expects.length ? expects.slice(0, 30).map(expect => {
      const envelope = envelopes.get(expect); const settled = settlements.get(expect); const row = node('tr');
      const valid = settled && settlementEligible(settled, envelopes);
      let status = '等待开奖';
      if (envelope?.source === 'legacy-import') status = '历史导入 · 不计分';
      else if (settled?.status === 'late') status = '延迟记录 · 不计分';
      else if (settled && !valid) status = '未纳入实时统计';
      else if (valid) status = `已结算 · r${settled.revision || 1}`;
      row.append(node('td', expect), node('td', settled ? `${text(settled.actualNumber)} / ${text(settled.actualZodiac)}` : '—'));
      for (const [group, size] of resultColumns) {
        const value = valid ? settled[group]?.[size] : undefined;
        row.append(node('td', mark(value), value === true ? 'hit' : value === false ? 'miss' : 'pending'));
      }
      row.append(node('td', status, valid ? 'hit' : 'pending')); return row;
    }) : [emptyRow(3 + resultColumns.length, '暂无中央预测记录；不补造历史命中')]);
    set('records-note', expects.length > 30 ? `展示最近 30 / ${expects.length} 期，完整记录见发布 JSON。` : `共 ${expects.length} 期发布记录，${eligible.length} 期纳入实时统计。`);
  }
  function hitText(value) { return value ? `${text(value.hits)} / ${text(value.total)} · ${percent(value.rate)}` : '—'; }
  function renderBacktest() {
    const report = state.snapshot?.backtest;
    if (!report) { replace('backtest-rows', [emptyRow(6, '暂无中央滚动回测报告')]); return; }
    const split = report.split || {};
    set('backtest-count', `${count(split.testCount)} 期留出集`);
    set('backtest-split', `${text(report.modelVersion)} · 第 ${text(split.testFirst)} — ${text(split.testLast)} 期 · ${text(split.method)}`);
    const focused = state.snapshot.system?.focus === 'six-zodiac';
    $('backtest-number-control').hidden = focused;
    $('backtest-zodiac-control').hidden = focused;
    $('backtest-number-heading').hidden = focused;
    const numberSize = $('backtest-number-size').value;
    const zodiacSize = focused ? '6' : $('backtest-zodiac-size').value;
    replace('backtest-rows', list(report.algorithms).length ? report.algorithms.map(algorithm => {
      const row = node('tr'); const number = algorithm.numberHits?.[numberSize]; const zodiac = algorithm.zodiacHits?.[zodiacSize];
      const numberCell = node('td', hitText(number)); numberCell.hidden = focused;
      const interval = focused ? zodiac : number;
      row.append(node('td', algorithm.name || algorithm.id), numberCell, node('td', interval ? `${percent(interval.baseline)} / ${percent(interval.wilsonLow)}–${percent(interval.wilsonHigh)}` : '—'), node('td', hitText(zodiac)), node('td', fixed(algorithm.logLoss)), node('td', fixed(algorithm.brier)));
      if (algorithm.id === 'ensemble') row.className = 'ensemble-row';
      return row;
    }) : [emptyRow(6, '回测算法报告待发布')]);
    const notes = [...list(report.notes), `均匀分布 Log loss ${fixed(report.uniformLogLoss)}。命中区间为中央发布的 Wilson 区间，历史回测不等于未来结果。`];
    replace('backtest-notes', notes.map(note => node('p', text(note))));
    $('legacy-backtest-note').hidden = !state.snapshot.legacyBacktest;
  }
  function searchableDraw(draw) { return [draw.expect, draw.openTime, ...list(draw.numbers).map(number => isNumeric(number) ? pad(number) : text(number)), ...list(draw.zodiac)].join(' ').toLowerCase(); }
  function historyRows() {
    return list(state.snapshot?.draws).filter(draw => !state.query || searchableDraw(draw).includes(state.query)).slice().sort((a, b) => String(b.expect).localeCompare(String(a.expect), 'en', { numeric: true }));
  }
  function renderHistory() {
    const rows = historyRows(); const pages = Math.ceil(rows.length / PAGE_SIZE);
    state.historyPage = Math.max(0, Math.min(state.historyPage, pages - 1));
    const slice = rows.slice(state.historyPage * PAGE_SIZE, (state.historyPage + 1) * PAGE_SIZE);
    replace('history-rows', slice.length ? slice.map(draw => {
      const row = node('tr'); const numbers = node('div', null, 'mini-balls');
      list(draw.numbers).forEach((number, index) => {
        const ball = node('span', isNumeric(number) ? pad(number) : text(number), `mini-ball ${ballClass(list(draw.wave)[index])}`);
        ball.title = `${index === 6 ? '特别号' : '正码'} · ${text(list(draw.zodiac)[index])}`; numbers.append(ball);
      });
      const cell = node('td'); cell.append(numbers); row.append(node('td', draw.expect), node('td', time(draw.openTime)), cell); return row;
    }) : [emptyRow(3, state.query ? '没有匹配的历史开奖' : '暂无历史开奖')]);
    set('history-result-count', `${rows.length} 条匹配 · 每页 ${PAGE_SIZE} 条`);
    set('history-page', pages ? `${state.historyPage + 1} / ${pages}` : '0 / 0');
    $('history-prev').disabled = state.historyPage === 0; $('history-next').disabled = !pages || state.historyPage + 1 >= pages;
  }
  function renderHistoryStats() {
    const snapshot = state.snapshot; const draws = list(snapshot.draws); const coverage = snapshot.coverage || {};
    set('history-total', `${count(draws.length)} 条`);
    function stat(value, label, small) { const result = node('div', null, 'history-stat'); result.append(node('strong', text(value), small ? 'small' : ''), node('span', label)); return result; }
    replace('history-stats', [stat(count(draws.length), '已发布历史样本'), stat(draws[0]?.openTime || coverage.rangeStart || '—', '覆盖起点', true), stat(draws[draws.length - 1]?.openTime || coverage.rangeEnd || '—', '覆盖终点', true)]);
    const frequencies = Array(49).fill(0);
    for (const draw of draws) {
      const special = Number(list(draw.numbers)[6]);
      if (Number.isInteger(special) && special >= 1 && special <= 49) frequencies[special - 1]++;
    }
    const maximum = Math.max(1, ...frequencies);
    replace('history-frequency', frequencies.map((frequency, index) => {
      const item = node('div', null, 'frequency-item'); item.append(node('b', pad(index + 1)), node('span', `${frequency} 次`));
      const bar = node('i'); bar.style.width = `${frequency / maximum * 100}%`; item.append(bar); return item;
    }));
    const warnings = [...list(coverage.warnings), ...list(coverage.errors)];
    set('coverage-note', `数据覆盖以中央发布为准${warnings.length ? ` · ${warnings.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('；')}` : ' · 未补造缺失开奖'}`);
    renderHistory();
  }
  function renderPublication() {
    const snapshot = state.snapshot; const publication = snapshot.publication; const sync = publication.sync || {};
    set('publication-time', `快照生成 ${time(publication.generatedAt)} UTC+8`);
    set('snapshot-id', publication.snapshotId);
    set('sync-time', `${time(sync.checkedAt)} / ${time(sync.lastSuccess)} UTC+8`);
    set('source-label', sync.source || snapshot.coverage?.source);
    const warnings = list(sync.warnings).map(item => typeof item === 'string' ? item : JSON.stringify(item));
    if (sync.blocked) warnings.unshift('有新期数据冲突或缺期，未继续入库。');
    if (sync.success === false) warnings.unshift('中央源同步未成功；本页仅展示已发布快照，请核对最后成功时间。');
    replace('publication-warnings', warnings.map(warning => node('li', warning)));
    $('download-snapshot').disabled = false;
    $('download-forecast').disabled = !snapshot.currentForecast;
    $('download-csv').disabled = !list(snapshot.draws).length;
  }
  function renderSnapshot() {
    const focused = state.snapshot.system?.focus === 'six-zodiac';
    document.documentElement.classList.toggle('six-focus', focused);
    $('number-column').hidden = focused;
    $('zodiac-tabs').hidden = focused;
    if (focused) state.zodiacSize = 6;
    renderDraw(); renderForecast(); renderTraining(); renderRecords(); renderBacktest(); renderHistoryStats(); renderPublication(); tick(); renderNotice();
  }
  function download(filename, content, mime) {
    const blob = new Blob([content], { type: mime }); const url = URL.createObjectURL(blob);
    const anchor = node('a'); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function csvCell(value) {
    let string = value === null || value === undefined ? '' : String(value);
    // Spreadsheet formula injection also applies to exported external text.
    if (/^[=+\-@\t\r]/.test(string)) string = "'" + string;
    return '"' + string.replaceAll('"', '""') + '"';
  }
  function bindEvents() {
    for (const group of ['number', 'zodiac']) {
      const tabs = $(`${group}-tabs`);
      tabs.addEventListener('click', event => {
        const button = event.target.closest('button[data-size]'); if (!button || !tabs.contains(button)) return;
        const size = Number(button.dataset.size);
        if (state.snapshot?.system?.focus === 'six-zodiac' || !(group === 'number' ? NUMBER_SIZES : ZODIAC_SIZES).includes(size)) return;
        state[group === 'number' ? 'numberSize' : 'zodiacSize'] = size; renderCandidates();
      });
      tabs.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        const buttons = [...tabs.querySelectorAll('button')]; const current = buttons.indexOf(document.activeElement);
        if (current < 0) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].click(); buttons[next].focus();
      });
    }
    $('history-search').addEventListener('input', event => { state.query = event.target.value.trim().toLowerCase(); state.historyPage = 0; renderHistory(); });
    $('history-prev').addEventListener('click', () => { if (state.historyPage > 0) { state.historyPage--; renderHistory(); } });
    $('history-next').addEventListener('click', () => { state.historyPage++; renderHistory(); });
    for (const id of ['backtest-number-size', 'backtest-zodiac-size']) $(id).addEventListener('change', renderBacktest);
    $('download-snapshot').addEventListener('click', () => { if (state.snapshot) download('tom-publication.json', JSON.stringify(state.snapshot, null, 2), 'application/json;charset=utf-8'); });
    $('download-forecast').addEventListener('click', () => { if (state.snapshot?.currentForecast) download(`tom-forecast-${state.snapshot.currentForecast.targetExpect}.json`, JSON.stringify(state.snapshot.currentForecast, null, 2), 'application/json;charset=utf-8'); });
    $('download-csv').addEventListener('click', () => {
      if (!state.snapshot) return;
      const header = ['expect', 'openTime', 'n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'special', 'zodiac1', 'zodiac2', 'zodiac3', 'zodiac4', 'zodiac5', 'zodiac6', 'specialZodiac'];
      const rows = list(state.snapshot.draws).map(draw => [draw.expect, draw.openTime, ...Array.from({ length: 7 }, (_, i) => list(draw.numbers)[i]), ...Array.from({ length: 7 }, (_, i) => list(draw.zodiac)[i])]);
      download('tom-draws.csv', '\ufeff' + [header, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n'), 'text/csv;charset=utf-8');
    });
    window.addEventListener('online', refreshSnapshot);
    window.addEventListener('offline', () => { state.offline = true; renderNotice(); });
  }
  bindEvents();
  try {
    const cached = window.localStorage.getItem(CACHE_KEY);
    if (cached) {
      state.snapshot = validateSnapshot(JSON.parse(cached)); state.cache = '已读取完整上次发布快照'; renderSnapshot();
    }
  } catch (error) { state.cache = `缓存读取失败 · ${error.name || 'StorageError'}`; renderNotice(); }
  refreshSnapshot();
  window.setInterval(refreshSnapshot, 60000);
  window.setInterval(tick, 1000);
})();
