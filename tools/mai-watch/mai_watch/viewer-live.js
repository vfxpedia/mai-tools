/* Live panel of the viewer (DESIGN.md sections 9c to 9f). Reads live.json from `mai-watch` about once a second.
 * Order on the page carries the meaning: first what needs attention (the judgment list the server computes, the same one /status.json
 * gives agents), then the GPUs as wide rows, then the host in a smaller band, then storage sorted by free space, then AI sessions.
 * Rows that show nothing (idle disks, adapters with no link and no traffic, quiet sessions) are folded. A value the sampler could not
 * read is shown as unknown, never as 0. Without a live sampler (plain `serve`) the panel stays hidden. */
(function (root) {
  'use strict';
  var state = { active: false, interval: 1, history: 600, samples: [], host: null, slow: null, judgments: [], disks: {}, timer: null, open: {} };
  root.MaiLive = state;

  function $(id) { return document.getElementById(id); }
  function el(tag, text, cls) { var e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function known(v) { return v !== null && v !== undefined; }
  function fmt(v, digits, unit) { return known(v) ? v.toFixed(digits) + (unit || '') : 'unknown'; }
  function ms(iso) { return Date.parse(iso); }
  function sinceIso(iso) { var t = Date.parse(iso || ''); return isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null; }
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
    return Math.min(state.history, Math.max(60, span));
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
    if (!list.length) { box.appendChild(el('div', 'Nothing needs attention right now.', 'att-row ok-row')); return box; }
    list.forEach(function (f) {
      var row = el('div', undefined, 'att-row lvl-' + f.level);
      row.appendChild(el('span', f.level === 'bad' ? 'act now' : f.level === 'warn' ? 'look soon' : 'note', 'att-level'));
      row.appendChild(el('span', f.text, 'att-text'));
      box.appendChild(row);
    });
    return box;
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
    var facts = el('div', undefined, 'gpu-facts mono');
    facts.appendChild(el('div', (known(g.temperature_c) ? g.temperature_c + ' C' : 'temperature unknown') + '  ·  ' + (known(g.power_w) ? g.power_w.toFixed(0) : '?') + (g.power_limit_w ? ' / ' + g.power_limit_w.toFixed(0) : '') + ' W'));
    facts.appendChild(el('div', known(g.sm_clock_mhz) ? 'SM ' + g.sm_clock_mhz + (g.sm_clock_max_mhz ? ' / ' + g.sm_clock_max_mhz : '') + ' MHz' : 'clock unknown'));
    facts.appendChild(el('div', limitText(g)));
    row.appendChild(facts);
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

  /* Pure: 'active' when a rate above 0.01 MiB/s was seen in the window, 'idle' when rates were read and all were at or below it,
   * 'unknown' when no rate was read at all (first reading, counter reset). Unknown is never called idle (review R11). Exported for tests. */
  function activity(list, key, field, name, a, b) {
    var seen = false, moving = false;
    list.forEach(function (s) {
      (s[key] || []).forEach(function (x) {
        if (x[field] !== name) return;
        [x[a], x[b]].forEach(function (v) {
          if (v === null || v === undefined || !isFinite(v)) return;
          seen = true;
          if (v > 0.01) moving = true;
        });
      });
    });
    return moving ? 'active' : seen ? 'idle' : 'unknown';
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
        var line = el('div', undefined, 'meter-cell');
        line.appendChild(meter(x.pct, known(x.pct) && x.pct >= 80 ? 'hot' : ''));
        line.appendChild(el('span', known(x.pct) ? x.pct + '%' : 'unknown', 'strong'));
        c.appendChild(line);
        // the gauge records the plan limit when a session takes a turn; this is the age of that reading, not a live measurement
        c.appendChild(el('div', (x.reset && isFinite(Date.parse(x.reset)) ? 'resets in ' + ago(Math.max(0, (Date.parse(x.reset) - Date.now()) / 1000)) : 'reset unknown') + ' · reading ' + ago(sinceIso(x.read_at)) + ' old' + (x.note ? ' · ' + x.note : ''), 'quiet'));
        lim.appendChild(c);
      });
    });
    box.appendChild(lim);
    function cover(known_, all) { return all && known_ < all ? ' (' + known_ + ' of ' + all + ' turns)' : ''; }
    var head = ['session', 'engine', 'context', 'turns today', 'cost today, API price', 'tokens today', 'last active', 'doing'];
    var rows = function (list) {
      return list.map(function (r) {
        return [r.name || r.id.slice(0, 8), r.engine || 'unknown', known(r.context_pct) ? r.context_pct + '%' : 'unknown',
          known(r.turns_today) ? String(r.turns_today) : 'no record',
          known(r.cost_usd_today) ? '$' + r.cost_usd_today.toFixed(2) + cover(r.cost_turns, r.turns_today) : 'unknown',
          known(r.tokens_today) ? (r.tokens_today / 1e6).toFixed(1) + ' M' + cover(r.token_turns, r.turns_today) : 'unknown',
          ago(r.last_active_s) + ' ago', r.doing || ''];
      });
    };
    var all = u.sessions || [];
    var busy = all.filter(function (r) { return r.last_active_s < 3600; });
    var quiet = all.filter(function (r) { return busy.indexOf(r) < 0; });
    if (busy.length) box.appendChild(table(head, rows(busy), 'compact'));
    else box.appendChild(el('p', 'no session active in the last hour', 'quiet'));
    if (quiet.length) box.appendChild(fold(quiet.length + ' sessions idle for over an hour', table(head, rows(quiet), 'compact'), 'sessions-quiet'));
    if (u.problems && u.problems.length) box.appendChild(el('p', u.problems.join('; '), 'quiet'));
    return box;
  }

  function draw() {
    var box = $('live'), list = state.samples;
    clear(box);
    if (!list.length) { box.appendChild(el('p', 'waiting for the first sample...', 'quiet')); return; }
    var last = list[list.length - 1], times = list.map(function (s) { return ms(s.t); });
    var lag = (Date.now() - times[times.length - 1]) / 1000;
    var status = $('live-status');
    if (lag > Math.max(3 * state.interval, 5)) { status.className = 'pill bad'; status.textContent = 'stopped: last sample ' + Math.round(lag) + ' s ago'; }
    else { status.className = 'pill ok'; status.textContent = 'live, every ' + state.interval + ' s'; }
    var spanS = windowS(times);
    status.textContent += ' · graphs show ' + (spanS >= 120 ? Math.round(spanS / 60) + ' min' : Math.round(spanS) + ' s');
    if (state.host && state.host.available === false) status.textContent += ' · CPU, RAM, disks and network unknown: ' + state.host.reason;

    box.appendChild(attention());

    var gpus = el('section', undefined, 'gpus');
    (last.gpus || []).forEach(function (g) { gpus.appendChild(gpuRow(g, list, times)); });
    if (!last.gpus) gpus.appendChild(el('div', 'GPU unknown: no nvidia-smi reading', 'att-row lvl-info'));
    else {
      var legend = el('div', undefined, 'legend quiet');
      legend.appendChild(el('span', 'use', 'u-key')); legend.appendChild(el('span', 'VRAM', 'v-key'));
      gpus.appendChild(legend);
    }
    box.appendChild(gpus);

    var band = el('section', undefined, 'host-band');
    var c = hostCard('CPU', fmt(last.cpu_pct, 0, '%'), state.host && state.host.logical_cpus ? state.host.logical_cpus + ' logical CPUs' : '', times, list.map(function (s) { return s.cpu_pct; }), last.cpu_per_core ? cores(last.cpu_per_core) : null);
    band.appendChild(c);
    band.appendChild(hostCard('RAM', fmt(last.ram_pct, 0, '%'), fmt(last.ram_used_gib, 1) + ' / ' + fmt(last.ram_total_gib, 1) + ' GiB' + (last.swap_total_gib ? ' · swap ' + fmt(last.swap_used_gib, 1) + ' / ' + fmt(last.swap_total_gib, 1) : ''), times, list.map(function (s) { return s.ram_pct; })));
    band.appendChild(ioBand(list));
    box.appendChild(band);

    if (state.slow) box.appendChild(storage(state.slow));
    if (state.slow) box.appendChild(usageBlock(state.slow.usage));
  }

  function poll() {
    var since = state.samples.length ? state.samples[state.samples.length - 1].t : '';
    fetch('live.json?since=' + encodeURIComponent(since) + '&t=' + Date.now(), { cache: 'no-store' }).then(function (r) {
      if (r.status === 404) { state.active = false; $('live-section').style.display = 'none'; return null; }
      if (!r.ok) throw new Error('live.json returned ' + r.status);
      return r.json();
    }).then(function (d) {
      if (!d) return;
      if (d.schema !== 'mai-watch-live-v1') throw new Error('live.json has an unknown schema');
      var wasActive = state.active;
      state.active = true; state.interval = d.interval_s; state.history = d.history_s; state.host = d.host; state.slow = d.slow || null;
      state.judgments = d.judgments || []; state.disks = d.disks || {};
      $('live-section').style.display = 'block';
      state.samples = state.samples.concat(d.samples);
      var cutoff = Date.now() - state.history * 1000;
      state.samples = state.samples.filter(function (s) { return ms(s.t) >= cutoff; });
      draw();
      if (!wasActive && root.maiWatchTick) root.maiWatchTick();
      state.timer = setTimeout(poll, Math.max(500, state.interval * 1000));
    }).catch(function (e) {
      var status = $('live-status');
      if (status) { status.className = 'pill bad'; status.textContent = 'live view cannot read live.json: ' + e.message; }
      state.timer = setTimeout(poll, 3000);
    });
  }

  if (typeof document !== 'undefined' && document.getElementById && document.getElementById('live')) poll();
  if (typeof module !== 'undefined') module.exports = { sparkPoints: sparkPoints, activity: activity };
})(typeof window !== 'undefined' ? window : this);
