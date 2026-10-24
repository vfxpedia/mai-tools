/* Live panel of the viewer (DESIGN.md sections 9c to 9f). Reads live.json from `mai-watch` about once a second.
 * Order on the page carries the meaning: first what needs attention (the judgment list the server computes, the same one /status.json
 * gives agents), then the GPUs as wide rows, then the host in a smaller band, then storage sorted by free space, then AI sessions.
 * Rows that show nothing (idle disks, adapters with no link and no traffic, quiet sessions) are folded. A value the sampler could not
 * read is shown as unknown, never as 0. Without a live sampler (plain `serve`) the panel stays hidden. */
(function (root) {
  'use strict';
  var state = { active: false, interval: 1, history: 600, range: 600, samples: [], host: null, slow: null, judgments: [], disks: {}, open: {}, lastReceivedAt: null, error: null, diagnostics: null, incidents: [] };
  root.MaiLive = state;

  function $(id) { return document.getElementById(id); }
  function el(tag, text, cls) { var e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function known(v) { return v !== null && v !== undefined; }
  function fmt(v, digits, unit) { return known(v) ? v.toFixed(digits) + (unit || '') : 'unknown'; }
  function ms(iso) { return Date.parse(iso); }
  function sinceIso(iso) { var t = Date.parse(iso || ''); return isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null; }
  // plan limit text and meter class from the percent and the age of the reading in seconds (10/20)
  function limitLabel(pct, age) {
    if (!known(pct)) return { cls: '', text: 'unknown' };
    if (!known(age) || age > 1800) return { cls: 'off', text: pct + '% · old reading (' + ago(age) + ' ago), may have reset' };
    return { cls: pct >= 80 ? 'hot' : '', text: pct + '%' };
  }
  function ago(sec) { return !known(sec) ? 'unknown' : sec < 90 ? Math.round(sec) + ' s' : sec < 5400 ? Math.round(sec / 60) + ' min' : sec < 172800 ? (sec / 3600).toFixed(1) + ' h' : (sec / 86400).toFixed(1) + ' days'; }
  function rate(v) { return !known(v) ? 'unknown' : (v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2)) + ' MiB/s'; }
  function gib(mib) { return known(mib) ? (mib / 1024).toFixed(1) : 'unknown'; }

  /* Pure: polyline points for values in [0, max] over the time window. A null value breaks the line, and so does a gap between two
   * samples longer than maxGapMs, so time that was not observed never looks like a steady reading. Exported for tests. */
  function sparkPoints(times, values, now, windowS, max, w, h, maxGapMs) {
    var segs = [], cur = [], prevT = null;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (maxGapMs && prevT !== null && times[i] - prevT > maxGapMs && cur.length) { segs.push(cur.join(' ')); cur = []; }
      prevT = times[i];
      if (v === null || v === undefined || !isFinite(v)) { if (cur.length) { segs.push(cur.join(' ')); cur = []; } continue; }
      var x = w - (now - times[i]) / 1000 / windowS * w;
      if (x < 0) continue;
      var y = h - Math.max(0, Math.min(max, v)) / max * h;
      cur.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    if (cur.length) segs.push(cur.join(' '));
    return segs;
  }
  state.sparkPoints = sparkPoints;

  function windowS(times) {
    // the window grows with the data up to the kept history, so a fresh start fills the graph instead of a sliver at the right edge
    var span = times.length ? (times[times.length - 1] - times[0]) / 1000 : 0;
    return Math.min(state.history, state.range, Math.max(60, span));
  }

  /* One graph, one or more series. Each series: {values, cls}. All share the time axis and the 0..max scale. */
  function graph(times, series, max, cls) {
    var NS = 'http://www.w3.org/2000/svg', w = 600, h = 60;
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'spark ' + (cls || ''));
    var now = times.length ? times[times.length - 1] : Date.now();
    var gap = Math.max(3 * state.interval, 5) * 1000;
    series.forEach(function (s) {
      sparkPoints(times, s.values, now, windowS(times), max, w, h, gap).forEach(function (pts) {
        var line = document.createElementNS(NS, 'polyline');
        line.setAttribute('points', pts);
        line.setAttribute('class', s.cls || '');
        svg.appendChild(line);
      });
    });
    return svg;
  }

  function meter(pct, cls) {
    var b = el('span', undefined, 'meter' + (cls ? ' ' + cls : ''));
    var f = el('span', undefined, 'meter-fill');
    f.style.width = (known(pct) ? Math.max(0, Math.min(100, pct)) : 0) + '%';
    b.appendChild(f);
    return b;
  }

  function table(head, rows, cls) {
    var t = el('table', undefined, cls || ''), tr = el('tr');
    head.forEach(function (h) { tr.appendChild(el('th', h)); });
    t.appendChild(tr);
    rows.forEach(function (r) {
      var row = el('tr');
      r.forEach(function (c) { var td = el('td'); if (c && c.nodeType) td.appendChild(c); else td.textContent = c; row.appendChild(td); });
      t.appendChild(row);
    });
    var wrap = el('div', undefined, 'scroll'); wrap.appendChild(t); return wrap;
  }

  /* A folded group keeps the reader's choice across redraws: the page is rebuilt every second, so the open state lives in state.open
   * under a stable key (review R12). */
  function fold(summary, node, key) {
    var d = el('details', undefined, 'fold');
    if (key && state.open[key]) d.open = true;
    d.addEventListener('toggle', function () { if (key) state.open[key] = d.open; });
    d.appendChild(el('summary', summary)); d.appendChild(node); return d;
  }

  /* ---------- 1. what needs attention ---------- */
  function attention() {
    var box = el('div', undefined, 'attention');
    var list = state.judgments || [];
    var bad = list.filter(function (f) { return f.level === 'bad'; }).length;
    var warn = list.filter(function (f) { return f.level === 'warn'; }).length;
    var bar = el('div', undefined, 'attention-summary');
    bar.appendChild(el('strong', 'Now ' + bad + ' · soon ' + warn));
    if (!list.length) { bar.appendChild(el('span', ' · all clear', 'quiet')); box.appendChild(bar); return box; }
    var rows = el('div', undefined, 'attention-rows');
    list.forEach(function (f) {
      var row = el('div', undefined, 'att-row lvl-' + f.level);
      row.appendChild(el('span', f.level === 'bad' ? 'act now' : f.level === 'warn' ? 'look soon' : 'note', 'att-level'));
      var text = el('span', f.text, 'att-text'); row.appendChild(text);
      var body = el('div');
      body.appendChild(el('p', 'Observed ' + ago(f.observed_s) + ' continuously in this collector; first seen ' + (f.first_observed_at || 'unknown'), 'quiet'));
      var evidence = f.evidence || {};
      Object.keys(evidence).forEach(function (key) {
        body.appendChild(el('div', key + ': ' + (evidence[key] === null ? 'unknown' : String(evidence[key])), 'quiet'));
      });
      body.appendChild(el('p', f.next_check || 'Check the source and timestamp before taking action.', 'quiet'));
      var explanation = fold('Details', body, 'warning:' + f.kind + '|' + f.subject);
      explanation.className += ' warning-evidence'; text.appendChild(explanation);
      rows.appendChild(row);
    });
    box.appendChild(bar);
    box.appendChild(rows);
    return box;
  }

  function mobileFold(label, node, key) {
    var d = el('details', undefined, 'mobile-fold');
    var mobile = typeof root.innerWidth === 'number' && root.innerWidth <= 560;
    d.open = state.open[key] === undefined ? (!mobile || state.expandTables === true) : state.open[key];
    d.addEventListener('toggle', function () { state.open[key] = d.open; });
    d.appendChild(el('summary', label)); d.appendChild(node); return d;
  }

  /* ---------- 2. GPUs ---------- */
  function limitText(g) {
    if (g.throttle === null) return 'clock limit unknown';
    if (g.throttle === undefined) return '';
    var real = g.throttle.filter(function (x) { return x !== 'gpu_idle'; });
    return real.length ? 'clock held back: ' + real.join(', ') : g.throttle.length ? 'clocks low: no work' : 'no clock limit';
  }

  function gpuRow(g, list, times) {
    var find = function (s) { return (s.gpus || []).filter(function (x) { return x.uuid === g.uuid; })[0]; };
    var util = list.map(function (s) { var x = find(s); return x ? x.util_pct : null; });
    var vram = list.map(function (s) { var x = find(s); return x && known(x.vram_used_mib) && x.vram_total_mib ? 100 * x.vram_used_mib / x.vram_total_mib : null; });
    var vpct = known(g.vram_used_mib) && g.vram_total_mib ? 100 * g.vram_used_mib / g.vram_total_mib : null;
    var row = el('div', undefined, 'gpu-row');
    var id = el('div', undefined, 'gpu-id');
    id.appendChild(el('div', 'GPU ' + g.index, 'gpu-index'));
    id.appendChild(el('div', g.name, 'gpu-name'));
    row.appendChild(id);
    var nums = el('div', undefined, 'gpu-nums');
    var u = el('div', undefined, 'gpu-num'); u.appendChild(el('span', fmt(g.util_pct, 0, '%'), 'num-big')); u.appendChild(el('span', 'use', 'num-label u-key')); nums.appendChild(u);
    var v = el('div', undefined, 'gpu-num'); v.appendChild(el('span', gib(g.vram_used_mib) + ' / ' + gib(g.vram_total_mib) + ' GiB', 'num-mid')); v.appendChild(el('span', 'VRAM ' + fmt(vpct, 0, '%'), 'num-label v-key')); nums.appendChild(v);
    row.appendChild(nums);
    row.appendChild(graph(times, [{ values: vram, cls: 'line-vram' }, { values: util, cls: 'line-util' }], 100, 'gpu-graph'));
    var facts = el('div', undefined, 'gpu-facts mono'), current = el('div', undefined, 'gpu-current');
    current.appendChild(el('div', (known(g.temperature_c) ? g.temperature_c + ' C' : 'temperature unknown') + '  ·  ' + (known(g.power_w) ? g.power_w.toFixed(0) : '?') + (g.power_limit_w ? ' / ' + g.power_limit_w.toFixed(0) : '') + ' W'));
    current.appendChild(el('div', known(g.sm_clock_mhz) ? 'SM ' + g.sm_clock_mhz + (g.sm_clock_max_mhz ? ' / ' + g.sm_clock_max_mhz : '') + ' MHz' : 'clock unknown'));
    current.appendChild(el('div', limitText(g)));
    facts.appendChild(current);
    var now = Date.now(), seconds = Math.min(state.range, state.history), temp = null, power = null, oldest = now, count = 0;
    state.samples.forEach(function (s) {
      var t = ms(s.t);
      if (!isFinite(t) || t < now - seconds * 1000 || t > now) return;
      var x = find(s);
      if (!x) return;
      var valid = function (v) { return typeof v === 'number' && isFinite(v) && v >= 0; };
      var ht = valid(x.temperature_c), hp = valid(x.power_w);
      if (ht) temp = temp === null ? x.temperature_c : Math.max(temp, x.temperature_c);
      if (hp) power = power === null ? x.power_w : Math.max(power, x.power_w);
      if (ht || hp) { oldest = Math.min(oldest, t); count++; }
    });
    var peaks = el('div', undefined, 'gpu-peaks');
    peaks.appendChild(el('div', '최근 ' + Math.round(seconds / 60) + '분 최고', 'gpu-peak-title'));
    function peakLine(label, value, kind) {
      var line = el('div', undefined, 'gpu-peak-line');
      line.appendChild(el('span', label, 'gpu-peak-label'));
      line.appendChild(el('strong', value, 'gpu-peak-value ' + kind));
      return line;
    }
    peaks.appendChild(peakLine('최고 온도', temp === null ? '미확인' : temp.toFixed(0) + '°C', 'peak-temperature'));
    peaks.appendChild(peakLine('최대 소비전력', power === null ? '미확인' : power.toFixed(0) + ' W', 'peak-power'));
    var span = count ? (now - oldest) / 1000 : 0;
    var spanLabel = span < 90 ? Math.round(span) + '초' : Math.round(span / 60) + '분';
    if (span < seconds - Math.max(5, 3 * state.interval)) {
      peaks.appendChild(el('div', count ? '관측 ' + spanLabel : '측정 대기', 'gpu-peak-coverage'));
    }
    var detail = el('div', '관측 ' + (count ? spanLabel : '미확인') + ' · 표본 ' + count + '개. 누락 구간은 추정하지 않습니다. 수집기 재시작 시 초기화됩니다.', 'gpu-peak-detail');
    var disclosure = fold('측정 상세', detail, 'gpu-peaks:' + g.uuid);
    disclosure.className += ' gpu-peak-disclosure';
    peaks.appendChild(disclosure);
    facts.appendChild(peaks);
    row.appendChild(facts);
    // Also protect a new viewer reading a still-running sampler's older payload.
    var procs = g.processes;
    if (Array.isArray(procs)) procs = procs.filter(function (p) {
      return p && typeof p.vram_mib === 'number' && isFinite(p.vram_mib) && p.vram_mib > 0 &&
        typeof p.process === 'string' && p.process.trim() && p.process.trim().charAt(0) !== '[';
    }).sort(function (a, b) { return b.vram_mib - a.vram_mib || (a.pid || 0) - (b.pid || 0); }).slice(0, 3);
    var procBox = el('div', undefined, 'gpu-processes');
    if (procs === null || procs === undefined) procBox.appendChild(el('span', 'Process list unknown', 'quiet'));
    else if (!procs.length) procBox.appendChild(el('span', 'No verified compute process · unreadable VRAM is not evidence of no work', 'quiet'));
    else procs.forEach(function (p) {
      var name = p.run_name ? p.process + ' · run ' + p.run_name : p.process + ' · run unknown';
      var elapsed = known(p.elapsed_s) ? 'running ' + ago(p.elapsed_s) : 'elapsed unknown';
      procBox.appendChild(el('div', name + ' · ' + elapsed + ' · ' + gib(p.vram_mib) + ' GiB VRAM', 'gpu-process'));
    });
    row.appendChild(procBox);
    return row;
  }

  /* ---------- 3. host band ---------- */
  function cores(per) {
    var s = el('div', undefined, 'cores');
    (per || []).forEach(function (v) {
      var c = el('span', undefined, 'core');
      c.style.opacity = String(0.15 + 0.85 * Math.max(0, Math.min(100, v)) / 100);
      c.title = v.toFixed(0) + '%';
      s.appendChild(c);
    });
    return s;
  }

  function hostCard(title, big, detail, times, values, extra) {
    var c = el('div', undefined, 'host-card');
    var head = el('div', undefined, 'host-head');
    head.appendChild(el('span', title, 'host-title'));
    head.appendChild(el('span', big, 'num-mid'));
    c.appendChild(head);
    c.appendChild(graph(times, [{ values: values, cls: 'line-util' }], 100, 'host-graph'));
    c.appendChild(el('div', detail, 'host-detail mono'));
    if (extra) c.appendChild(extra);
    return c;
  }

  /* Pure: 'unknown' when either current rate is unread (first reading, a counter reset, one side missing): an earlier zero never
   * covers a current unknown. Only when both current rates are read: 'active' when a rate above 0.01 MiB/s was seen in the window,
   * else 'idle'. Only idle rows are ever folded (review R11). Exported for tests. */
  function activity(list, key, field, name, a, b) {
    var ok = function (v) { return v !== null && v !== undefined && isFinite(v); };
    var current = null, moving = false;
    list.forEach(function (s) {
      (s[key] || []).forEach(function (x) {
        if (x[field] !== name) return;
        current = x;
        if ((ok(x[a]) && x[a] > 0.01) || (ok(x[b]) && x[b] > 0.01)) moving = true;
      });
    });
    if (!current || !ok(current[a]) || !ok(current[b])) return 'unknown';
    return moving ? 'active' : 'idle';
  }
  state.activity = activity;

  function diskName(d) {
    var m = state.disks && state.disks[d];
    if (!m) return d;
    return (m.places && m.places.length ? m.places.join(' ') + ' ' : '') + (m.model || d);
  }

  function ioBand(list) {
    var last = list[list.length - 1], box = el('div', undefined, 'io');
    var nicRow = function (n) { return [n.nic, n.kind || 'unknown', rate(n.rx_mib_s), rate(n.tx_mib_s), n.link_mbps ? (n.link_mbps >= 1000 ? (n.link_mbps / 1000) + ' Gbps' : n.link_mbps + ' Mbps') : 'unknown']; };
    if (!last.nics) box.appendChild(el('p', 'network unknown (needs psutil)', 'mono'));
    else {
      // folded only when the OS calls it virtual AND rates were read and stayed at zero; unknown rates stay in view
      var quietVirtual = last.nics.filter(function (n) { return n.kind === 'virtual' && activity(list, 'nics', 'nic', n.nic, 'rx_mib_s', 'tx_mib_s') === 'idle'; });
      var shown = last.nics.filter(function (n) { return quietVirtual.indexOf(n) < 0; });
      var nicHead = ['adapter', 'kind', 'receive', 'send', 'link'];
      box.appendChild(el('h3', 'Network'));
      box.appendChild(table(nicHead, shown.map(nicRow), 'compact'));
      if (quietVirtual.length) box.appendChild(fold(quietVirtual.length + ' virtual adapters with no traffic', table(nicHead, quietVirtual.map(nicRow), 'compact'), 'nics-virtual'));
    }
    if (!last.disks) box.appendChild(el('p', 'disk activity unknown (needs psutil)', 'mono'));
    else {
      var diskRow = function (d) { return [diskName(d.disk), rate(d.read_mib_s), rate(d.write_mib_s)]; };
      var cls = function (d) { return activity(list, 'disks', 'disk', d.disk, 'read_mib_s', 'write_mib_s'); };
      var idle = last.disks.filter(function (d) { return cls(d) === 'idle'; });
      var shown = last.disks.filter(function (d) { return idle.indexOf(d) < 0; });          // active and unknown both stay in view
      box.appendChild(el('h3', 'Disk activity'));
      if (shown.length) box.appendChild(table(['disk', 'read', 'write'], shown.map(diskRow), 'compact'));
      else box.appendChild(el('p', 'every disk was read and moved no data in the graph window', 'quiet'));
      if (idle.length) box.appendChild(fold(idle.length + ' disks that moved no data', table(['disk', 'read', 'write'], idle.map(diskRow), 'compact'), 'disks-idle'));
    }
    return box;
  }

  /* ---------- 4. storage ---------- */
  function storage(slow) {
    var box = el('section', undefined, 'live-block');
    box.appendChild(el('h3', 'Storage'));
    var paths = (slow.paths || []).slice().sort(function (a, b) {
      var fa = known(a.free_gib) ? a.free_gib : -1, fb = known(b.free_gib) ? b.free_gib : -1;
      return fa - fb;                               // least free first; unreachable (-1) on top
    });
    var rows = paths.map(function (p) {
      var free = el('span', known(p.free_gib) ? p.free_gib.toFixed(p.free_gib < 100 ? 1 : 0) + ' GiB free' : p.state, 'strong');
      var used = el('span', undefined, 'meter-cell');
      used.appendChild(meter(p.used_pct, p.state !== 'ok' ? 'off' : p.used_pct >= 95 ? 'hot' : ''));
      used.appendChild(el('span', known(p.used_pct) ? p.used_pct.toFixed(1) + '%' : 'unknown'));
      var st = p.state === 'ok' ? p.answer_ms + ' ms' : p.state + (p.error ? ': ' + p.error : '') + (p.waiting_s ? ' (' + p.waiting_s + ' s)' : '');
      if (p.checked_at) st += ', ' + ago(sinceIso(p.checked_at)) + ' ago';
      return [p.label || p.path, free, used, known(p.total_gib) ? p.total_gib.toFixed(0) + ' GiB' : 'unknown', st];
    });
    box.appendChild(table(['folder', 'free', 'used', 'size', 'answer, checked'], rows, 'compact'));
    if (slow.paths_dropped && slow.paths_dropped.length) box.appendChild(el('p', slow.paths_dropped.length + ' more folders not watched (limit 64)', 'quiet'));
    return box;
  }

  /* ---------- 5. AI sessions ---------- */
  function usageBlock(u) {
    var box = el('section', undefined, 'live-block');
    box.appendChild(el('h3', 'AI sessions'));
    if (!u) { box.appendChild(el('p', 'reading...', 'quiet')); return box; }
    if (!u.available) { box.appendChild(el('p', u.reason || 'no usage source', 'quiet')); return box; }
    var lim = el('div', undefined, 'limits');
    (u.limits || []).forEach(function (r) {
      [['five_hour', '5-hour'], ['seven_day', '7-day']].forEach(function (w) {
        var x = r[w[0]], c = el('div', undefined, 'limit');
        c.appendChild(el('div', r.engine + ' · ' + w[1], 'limit-name'));
        if (!x) { c.appendChild(el('div', 'not recorded by the gauge', 'quiet')); lim.appendChild(c); return; }
        // a reading older than 30 min is shown as old, grey, never hot: codex records only when a codex turn runs, so after an
        // early reset the page kept showing 86 % hot for 10 h (10/20)
        var lab = limitLabel(x.pct, sinceIso(x.read_at));
        var line = el('div', undefined, 'meter-cell');
        line.appendChild(meter(x.pct, lab.cls));
        line.appendChild(el('span', lab.text, 'strong'));
        c.appendChild(line);
        // the gauge records the plan limit when a session takes a turn; this is the age of that reading, not a live measurement
        c.appendChild(el('div', (x.reset && isFinite(Date.parse(x.reset)) ? 'resets in ' + ago(Math.max(0, (Date.parse(x.reset) - Date.now()) / 1000)) : 'reset unknown') + ' · reading ' + ago(sinceIso(x.read_at)) + ' old' + (x.note ? ' · ' + x.note : ''), 'quiet'));
        lim.appendChild(c);
      });
    });
    box.appendChild(lim);
    function cover(known_, all) { return all && known_ < all ? ' (' + known_ + ' of ' + all + ' turns)' : ''; }
    var head = ['session', 'engine', 'context', 'turns today', 'cost today, API price', 'tokens today', 'last active', 'doing'];
    var entries = function (list) {
      return list.map(function (r) {
        return { name: r.name || r.id.slice(0, 8), engine: r.engine || 'unknown', context: known(r.context_pct) ? r.context_pct + '%' : 'unknown',
          turns: known(r.turns_today) ? String(r.turns_today) : 'no record',
          cost: known(r.cost_usd_today) ? '$' + r.cost_usd_today.toFixed(2) + cover(r.cost_turns, r.turns_today) : 'unknown',
          tokens: known(r.tokens_today) ? (r.tokens_today / 1e6).toFixed(1) + ' M' + cover(r.token_turns, r.turns_today) : 'unknown',
          active: ago(r.last_active_s) + ' ago', doing: r.doing || '' };
      });
    };
    function sessionViews(list) {
      var items = entries(list), cards = el('div', undefined, 'session-cards');
      items.forEach(function (item) {
        var card = el('article', undefined, 'session-card');
        var title = el('div', undefined, 'session-card-head');
        title.appendChild(el('strong', item.name, 'session-card-name'));
        title.appendChild(el('span', item.engine, 'session-engine'));
        card.appendChild(title);
        [['Context', item.context], ['Turns today', item.turns], ['Cost today', item.cost], ['Tokens today', item.tokens], ['Last active', item.active], ['Doing', item.doing || 'unknown']].forEach(function (field) {
          var line = el('div', undefined, 'session-card-field');
          line.appendChild(el('span', field[0], 'session-card-label'));
          line.appendChild(el('span', field[1], 'session-card-value'));
          card.appendChild(line);
        });
        cards.appendChild(card);
      });
      var rows = items.map(function (item) { return [item.name, item.engine, item.context, item.turns, item.cost, item.tokens, item.active, item.doing]; });
      var desktop = table(head, rows, 'compact session-table');
      desktop.className += ' session-table-wrap';
      var group = el('div', undefined, 'session-list');
      group.appendChild(desktop); group.appendChild(cards);
      return group;
    }
    var all = u.sessions || [];
    var busy = all.filter(function (r) { return r.last_active_s < 3600; });
    var quiet = all.filter(function (r) { return busy.indexOf(r) < 0; });
    if (busy.length) box.appendChild(sessionViews(busy));
    else box.appendChild(el('p', 'no session active in the last hour', 'quiet'));
    if (quiet.length) box.appendChild(fold(quiet.length + ' sessions idle for over an hour', sessionViews(quiet), 'sessions-quiet'));
    if (u.problems && u.problems.length) box.appendChild(el('p', u.problems.join('; '), 'quiet'));
    return box;
  }

  function usageHighlights(u) {
    var box = el('div', undefined, 'usage-highlights');
    ['claude', 'codex'].forEach(function (engine) {
      var record = u && u.available && (u.limits || []).filter(function (r) { return r.engine === engine; })[0];
      var card = el('div', undefined, 'usage-highlight');
      card.appendChild(el('strong', engine === 'claude' ? 'Claude' : 'Codex'));
      if (!record) card.appendChild(el('span', 'unknown', 'quiet'));
      else [['five_hour', '5h'], ['seven_day', '7d']].forEach(function (w) {
        var x = record[w[0]];
        card.appendChild(el('span', w[1] + ' ' + (x ? x.pct + '%' : 'unknown')));
      });
      box.appendChild(card);
    });
    return box;
  }

  function updateStatus() {
    var last = state.samples[state.samples.length - 1];
    var f = root.MaiWatchConnection.freshness(Date.now(), state.lastReceivedAt, last ? ms(last.t) : null, state.interval, state.error);
    var status = $('live-status'), detail = $('live-freshness');
    if (!status) return;
    status.className = 'pill ' + (f.kind === 'live' ? 'ok' : f.kind === 'waiting' ? 'warn' : 'bad');
    status.textContent = f.kind === 'live' ? 'live, every ' + state.interval + ' s' :
      f.kind === 'disconnected' ? 'disconnected · retrying' : f.kind === 'stale' ? 'stale data' :
      f.kind === 'waiting' ? 'waiting for data' : 'measurement time unknown';
    var times = state.samples.map(function (s) { return ms(s.t); });
    if (times.length) { var span = windowS(times); status.textContent += ' · graphs show ' + (span >= 120 ? Math.round(span / 60) + ' min' : Math.round(span) + ' s'); }
    if (state.host && state.host.available === false) status.textContent += ' · CPU, RAM, disks and network unknown: ' + state.host.reason;
    if (detail) detail.textContent = 'Received ' + (f.receivedAge === null ? 'unknown' : Math.floor(f.receivedAge) + ' s ago') +
      ' · measured ' + (f.sampleAge === null ? 'unknown' : Math.floor(f.sampleAge) + ' s ago') + (state.error ? ' · ' + state.error : '');
  }

  function draw() {
    var box = $('live'), all = state.samples, end = all.length ? ms(all[all.length - 1].t) : 0;
    var list = all.filter(function (s) { return ms(s.t) >= end - state.range * 1000; });
    clear(box);
    if (!list.length) { box.appendChild(el('p', 'waiting for the first sample...', 'quiet')); return; }
    var last = list[list.length - 1], times = list.map(function (s) { return ms(s.t); });
    updateStatus();

    var overview = el('div', undefined, 'overview');
    var gpus = el('section', undefined, 'gpus');
    (last.gpus || []).forEach(function (g) { gpus.appendChild(gpuRow(g, list, times)); });
    if (!last.gpus) gpus.appendChild(el('div', 'GPU unknown: no nvidia-smi reading', 'att-row lvl-info'));
    else {
      var legend = el('div', undefined, 'legend quiet');
      legend.appendChild(el('span', 'use', 'u-key')); legend.appendChild(el('span', 'VRAM', 'v-key'));
      gpus.appendChild(legend);
    }
    overview.appendChild(gpus);
    overview.appendChild(attention());
    box.appendChild(overview);

    if (state.slow) box.appendChild(usageHighlights(state.slow.usage));

    var band = el('section', undefined, 'host-band');
    var c = hostCard('CPU', fmt(last.cpu_pct, 0, '%'), state.host && state.host.logical_cpus ? state.host.logical_cpus + ' logical CPUs' : '', times, list.map(function (s) { return s.cpu_pct; }), last.cpu_per_core ? cores(last.cpu_per_core) : null);
    c.className += ' cpu-card';
    if (last.cpu_processes === null || last.cpu_processes === undefined) c.appendChild(el('p', 'Top CPU processes unknown · waiting for two scans or access denied', 'quiet'));
    else c.appendChild(table(['top CPU process', 'PID', 'CPU %'], last.cpu_processes.slice(0, 3).map(function (p) { return [p.process, String(p.pid), fmt(p.cpu_pct, 1)]; }), 'compact cpu-processes'));
    c.appendChild(el('p', '1 core = 100% · scan age ' + ago(last.cpu_process_age_s), 'quiet'));
    band.appendChild(c);
    var ram = hostCard('RAM', fmt(last.ram_pct, 0, '%'), fmt(last.ram_used_gib, 1) + ' / ' + fmt(last.ram_total_gib, 1) + ' GiB' + (last.swap_total_gib ? ' · swap ' + fmt(last.swap_used_gib, 1) + ' / ' + fmt(last.swap_total_gib, 1) : ''), times, list.map(function (s) { return s.ram_pct; }));
    var top = last.ram_processes;
    if (top === null || top === undefined) ram.appendChild(el('p', 'Top RAM processes unknown', 'quiet'));
    else ram.appendChild(table(['top RAM process', 'PID', 'RSS MiB'], top.map(function (p) { return [p.process, String(p.pid), p.rss_mib.toFixed(1)]; }), 'compact'));
    ram.appendChild(el('p', 'Graphs: up to ' + Math.round(Math.min(state.range, state.history) / 60) + ' minutes of retained samples', 'quiet'));
    band.appendChild(ram);
    band.appendChild(ioBand(list));
    box.appendChild(band);

    if (state.slow) box.appendChild(mobileFold('Storage', storage(state.slow), 'storage'));
    if (state.slow) box.appendChild(mobileFold('AI sessions and recent activity', usageBlock(state.slow.usage), 'sessions'));
    if (state.diagnostics) {
      var diagnostics = el('section', undefined, 'live-block');
      diagnostics.appendChild(el('p', 'Read-only local monitor. No internet authentication. Export excludes names, paths, commands and logs.', 'quiet'));
      (state.diagnostics.checks || []).forEach(function (check) {
        diagnostics.appendChild(el('p', check.source + ' · ' + check.state + ': ' + check.reason + '. ' + check.next_check, 'quiet'));
      });
      box.appendChild(fold('Capability diagnostics and unknown values', diagnostics, 'diagnostics'));
    }
    var incidents = el('section', undefined, 'live-block');
    incidents.appendChild(el('p', 'At most 256 incidents / 24 hours in memory. Resets on collector restart. Unknown is not cleared.', 'quiet'));
    incidents.appendChild(table(['last observed', 'state', 'finding'], state.incidents.map(function (f) {
      return [new Date(f.last_seen * 1000).toISOString(), f.state, f.text];
    }), 'compact'));
    box.appendChild(fold('Incident history (' + state.incidents.length + ')', incidents, 'incidents'));
  }

  state.draw = function () { draw(); };      // lets a browser check redraw from samples it set itself (review R11 DOM regression)

  function poll(signal) {
    var since = state.samples.length ? state.samples[state.samples.length - 1].t : '';
    return root.MaiWatchConnection.read('live.json?since=' + encodeURIComponent(since), 'json', signal);
  }
  if (typeof document !== 'undefined' && document.getElementById && document.getElementById('live')) {
    function preference(key, fallback) { try { var v = root.localStorage.getItem('mai-watch-' + key); return v === null ? fallback : v; } catch (_) { return fallback; } }
    function save(key, value) { try { root.localStorage.setItem('mai-watch-' + key, value); } catch (_) {} }
    var range = $('graph-range'), focus = $('view-focus'), expand = $('expand-tables'), download = $('diagnostic-download');
    if (range) {
      range.value = preference('range', '600');
      if (['60', '300', '600'].indexOf(range.value) < 0) range.value = '600';
      state.range = Number(range.value);
      range.addEventListener('change', function () { state.range = Number(range.value); save('range', range.value); draw(); });
    }
    function setFocus(value) {
      if (['balanced', 'cpu', 'gpu', 'ai'].indexOf(value) < 0) value = 'balanced';
      $('live-section').setAttribute('data-focus', value);
      return value;
    }
    if (focus) {
      focus.value = setFocus(preference('focus', 'balanced'));
      focus.addEventListener('change', function () { save('focus', setFocus(focus.value)); });
    }
    if (expand) {
      expand.checked = preference('tables', 'false') === 'true'; state.expandTables = expand.checked;
      expand.addEventListener('change', function () { state.expandTables = expand.checked; state.open = {}; save('tables', String(expand.checked)); draw(); });
    }
    if (download) download.addEventListener('click', function () {
      if (download.disabled) return;
      download.disabled = true;
      var controller = new root.AbortController();
      var deadline;
      var timeout = new Promise(function (_, reject) { deadline = root.setTimeout(function () { reject(new Error('Diagnostic timeout')); controller.abort(); }, 6000); });
      Promise.race([root.MaiWatchConnection.read('diagnostic.json', 'json', controller.signal), timeout]).then(function (d) {
        if (!d || d.schema !== 'mai-watch-diagnostic-v1') throw new Error('Invalid diagnostic document');
        var url = root.URL.createObjectURL(new root.Blob([JSON.stringify(d, null, 2)], {type: 'application/json'}));
        var a = el('a'); a.href = url; a.download = 'mai-watch-diagnostic.json'; a.click();
        root.setTimeout(function () { root.URL.revokeObjectURL(url); }, 1000);
        $('diagnostic-result').textContent = 'Downloaded identity-free diagnostics. Review before sharing.';
      }).catch(function () { $('diagnostic-result').textContent = 'Diagnostic download failed; no file was created.'; }).finally(function () { root.clearTimeout(deadline); download.disabled = false; });
    });
    var loop = root.MaiWatchConnection.createLoop({task: poll, interval: function () { return state.interval * 1000; }, onData: function (d) {
      if (!d || d.schema !== 'mai-watch-live-v1' || !Array.isArray(d.samples) ||
          typeof d.interval_s !== 'number' || !isFinite(d.interval_s) || d.interval_s <= 0 ||
          typeof d.history_s !== 'number' || !isFinite(d.history_s) || d.history_s <= 0) throw new Error('live.json has an invalid schema or timing');
      var wasActive = state.active;
      state.active = true; state.interval = d.interval_s; state.history = d.history_s; state.host = d.host; state.slow = d.slow || null;
      state.judgments = d.judgments || []; state.disks = d.disks || {};
      state.diagnostics = d.diagnostics || null; state.incidents = d.incidents || [];
      $('live-section').style.display = 'block';
      state.samples = state.samples.concat(d.samples);
      var cutoff = Date.now() - state.history * 1000;
      state.samples = state.samples.filter(function (s) { return ms(s.t) >= cutoff; });
      state.lastReceivedAt = Date.now(); state.error = null;
      draw();
      if (!wasActive && root.maiWatchTick) root.maiWatchTick();
    }, onError: function (e) {
      if (e.status === 404 && !state.active) { $('live-section').style.display = 'none'; loop.stop(); return; }
      state.error = e.message; updateStatus();
    }});
    root.MaiWatchConnection.bind(loop); loop.start();
    root.setInterval(updateStatus, 1000);
  }
  if (typeof module !== 'undefined') module.exports = { sparkPoints: sparkPoints, activity: activity, limitLabel: limitLabel };
})(typeof window !== 'undefined' ? window : this);
