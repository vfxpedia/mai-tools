/* Live panel of the viewer (DESIGN.md sections 9c to 9e). Reads live.json from `mai-watch live` about once a second and draws CPU, RAM,
 * GPU and VRAM with their recent history, then watched paths, disk I/O, network and AI session usage. A value the sampler could not read is shown as unknown, never as 0. When the server has no
 * live sampler (plain `serve`), the panel stays hidden and the rest of the page works as before. */
(function (root) {
  'use strict';
  var state = { active: false, interval: 1, history: 600, samples: [], host: null, timer: null };
  root.MaiLive = state;

  function $(id) { return document.getElementById(id); }
  function el(tag, text, cls) { var e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function fmt(v, digits, unit) { return v === null || v === undefined ? 'unknown' : v.toFixed(digits) + (unit || ''); }
  function ms(iso) { return Date.parse(iso); }

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

  function spark(times, values, max) {
    var NS = 'http://www.w3.org/2000/svg', w = 300, h = 48;
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'spark');
    var now = times.length ? times[times.length - 1] : Date.now();
    // the window grows with the data up to the kept history, so a fresh start fills the graph instead of a sliver at the right edge
    var span = times.length ? (now - times[0]) / 1000 : 0;
    var windowS = Math.min(state.history, Math.max(60, span));
    var gap = Math.max(3 * state.interval, 5) * 1000;
    sparkPoints(times, values, now, windowS, max, w, h, gap).forEach(function (pts) {
      var line = document.createElementNS(NS, 'polyline');
      line.setAttribute('points', pts);
      svg.appendChild(line);
    });
    return svg;
  }

  function tile(title, big, detail, times, values, max, alarm) {
    var t = el('div', undefined, 'tile');
    var head = el('div', undefined, 'tile-head');
    head.appendChild(el('span', title, 'tile-title'));
    head.appendChild(el('span', big, 'tile-big' + (alarm ? ' hot' : '')));
    t.appendChild(head);
    t.appendChild(spark(times, values, max));
    t.appendChild(el('div', detail, 'tile-detail mono'));
    return t;
  }

  function coreStrip(per) {
    var s = el('div', undefined, 'cores');
    (per || []).forEach(function (v) {
      var c = el('span', undefined, 'core');
      c.style.opacity = String(0.15 + 0.85 * Math.max(0, Math.min(100, v)) / 100);
      c.title = v.toFixed(0) + '%';
      s.appendChild(c);
    });
    return s;
  }

  function gpuDetail(g) {
    var parts = [];
    if (g.temperature_c !== null && g.temperature_c !== undefined) parts.push(g.temperature_c + ' C');
    if (g.power_w !== null && g.power_w !== undefined) parts.push(g.power_w.toFixed(0) + (g.power_limit_w ? ' / ' + g.power_limit_w.toFixed(0) : '') + ' W');
    if (g.sm_clock_mhz !== null && g.sm_clock_mhz !== undefined) parts.push('SM ' + g.sm_clock_mhz + (g.sm_clock_max_mhz ? ' / ' + g.sm_clock_max_mhz : '') + ' MHz');
    if (g.mem_activity_pct !== null && g.mem_activity_pct !== undefined) parts.push('memory activity ' + g.mem_activity_pct + '%');
    if (g.throttle === null) parts.push('clock limit: unknown');
    else if (g.throttle !== undefined) {
      // gpu_idle only means the clocks are low because there is no work; it is not a slowdown
      var real = g.throttle.filter(function (x) { return x !== 'gpu_idle'; });
      parts.push(real.length ? 'clock limited by ' + real.join(', ') : (g.throttle.length ? 'clocks low: no work' : 'no clock limit'));
    }
    return parts.join('  ·  ');
  }

  function rate(v) { return v === null || v === undefined ? 'unknown' : (v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2)) + ' MiB/s'; }
  function ago(sec) { return sec === null || sec === undefined ? 'unknown' : sec < 90 ? Math.round(sec) + ' s' : sec < 5400 ? Math.round(sec / 60) + ' min' : sec < 172800 ? (sec / 3600).toFixed(1) + ' h' : (sec / 86400).toFixed(1) + ' days'; }
  function untilText(iso) {
    if (!iso) return 'reset time unknown';
    var s = (Date.parse(iso) - Date.now()) / 1000;
    return isFinite(s) ? 'resets in ' + ago(Math.max(0, s)) : 'reset time unknown';
  }

  function sinceIso(iso) { var t = Date.parse(iso || ''); return isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null; }

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

  function bar(pct, cls) {
    var b = el('span', undefined, 'meter' + (cls ? ' ' + cls : ''));
    var f = el('span', undefined, 'meter-fill');
    f.style.width = (pct === null || pct === undefined ? 0 : Math.max(0, Math.min(100, pct))) + '%';
    b.appendChild(f);
    return b;
  }

  function storage(slow) {
    var box = el('div', undefined, 'live-block');
    box.appendChild(el('h3', 'Storage: watched folders'));
    var rows = (slow.paths || []).map(function (p) {
      var free = el('span', p.free_gib === null || p.free_gib === undefined ? 'unknown' : p.free_gib.toFixed(p.free_gib < 100 ? 1 : 0) + ' GiB free', 'strong');
      var st = p.state === 'ok' ? 'answers in ' + p.answer_ms + ' ms' : p.state + (p.error ? ': ' + p.error : '') + (p.waiting_s ? ' (waiting ' + p.waiting_s + ' s)' : '');
      if (p.checked_at) st += ', checked ' + ago(sinceIso(p.checked_at)) + ' ago';
      var used = el('span', undefined, 'meter-cell');
      used.appendChild(bar(p.used_pct, p.state !== 'ok' ? 'off' : p.used_pct >= 95 ? 'hot' : ''));
      used.appendChild(el('span', p.used_pct === null || p.used_pct === undefined ? 'unknown' : p.used_pct.toFixed(1) + '% used'));
      var row = [p.path, free, used, p.total_gib === null || p.total_gib === undefined ? 'unknown' : p.total_gib.toFixed(0) + ' GiB', st];
      return row;
    });
    box.appendChild(table(['folder', 'free', 'used', 'size', 'state'], rows, 'compact'));
    if (slow.paths_dropped && slow.paths_dropped.length) box.appendChild(el('p', slow.paths_dropped.length + ' more folders not watched (limit 64)', 'warn live-problems'));
    return box;
  }

  function io(list, times) {
    var box = el('div', undefined, 'live-block');
    var last = list[list.length - 1];
    box.appendChild(el('h3', 'Network (each adapter on its own; adapters are not added together)'));
    var nics = (last.nics || []).map(function (n) {
      var find = function (s) { return (s.nics || []).filter(function (x) { return x.nic === n.nic; })[0]; };
      var both = list.map(function (s) { var x = find(s); return x && x.rx_mib_s !== null && x.tx_mib_s !== null ? x.rx_mib_s + x.tx_mib_s : null; });
      var top = Math.max(1, Math.max.apply(null, both.filter(function (v) { return v !== null; }).concat([0])));
      return [n.nic, rate(n.rx_mib_s), rate(n.tx_mib_s), n.link_mbps ? (n.link_mbps >= 1000 ? (n.link_mbps / 1000).toFixed(n.link_mbps % 1000 ? 1 : 0) + ' Gbps' : n.link_mbps + ' Mbps') : 'unknown', spark(times, both, top)];
    });
    if (!last.nics) box.appendChild(el('p', 'network: unknown (needs psutil)', 'mono'));
    else box.appendChild(table(['adapter', 'receive', 'send', 'link speed (as the OS reports it)', 'receive + send, scaled to its own peak'], nics, 'compact'));
    box.appendChild(el('h3', 'Disk activity'));
    var disks = (last.disks || []).map(function (d) { return [d.disk, rate(d.read_mib_s), rate(d.write_mib_s)]; });
    if (!last.disks) box.appendChild(el('p', 'disk activity: unknown (needs psutil)', 'mono'));
    else box.appendChild(table(['disk', 'read', 'write'], disks, 'compact'));
    return box;
  }

  function usageBlock(u) {
    var box = el('div', undefined, 'live-block');
    box.appendChild(el('h3', 'AI sessions: plan limits and today\'s use'));
    if (!u) { box.appendChild(el('p', 'reading...', 'mono')); return box; }
    if (!u.available) { box.appendChild(el('p', u.reason || 'no usage source', 'mono')); return box; }
    var lim = (u.limits || []).map(function (r) {
      function cell(w) {
        var c = el('span', undefined, 'meter-cell');
        if (!w) { c.appendChild(el('span', 'not recorded')); return c; }
        c.appendChild(bar(w.pct, w.pct !== null && w.pct >= 90 ? 'hot' : ''));
        c.appendChild(el('span', (w.pct === null ? 'unknown' : w.pct + '%') + ', ' + untilText(w.reset) + ', read ' + ago(sinceIso(w.read_at)) + ' ago' + (w.note ? ' (' + w.note + ')' : '')));
        return c;
      }
      return [r.engine + ' (' + r.account + ')', cell(r.five_hour), cell(r.seven_day)];
    });
    if (u.limits === null) box.appendChild(el('p', u.limits_problem || 'limits unknown', 'mono'));
    else box.appendChild(table(['account', '5-hour window', '7-day window'], lim, 'compact'));
    var all = u.sessions || [];
    var busy = all.filter(function (r) { return (r.turns_today || 0) > 0 || r.last_active_s < 3600; });
    var quiet = all.filter(function (r) { return busy.indexOf(r) < 0; });
    // a sum over fewer turns than were made says so: it is a known part, not the total
    function cover(known, all) { return all && known < all ? ' (' + known + ' of ' + all + ' turns known)' : ''; }
    function sesRows(list) { return list.map(function (r) {
      return [r.name || r.id.slice(0, 8), r.engine || 'unknown', r.context_pct === null || r.context_pct === undefined ? 'unknown' : r.context_pct + '%',
        r.turns_today === null ? 'no record today' : String(r.turns_today),
        r.cost_usd_today === null ? 'unknown' : '$' + r.cost_usd_today.toFixed(2) + cover(r.cost_turns, r.turns_today),
        r.tokens_today === null ? 'unknown' : (r.tokens_today / 1e6).toFixed(1) + ' M' + cover(r.token_turns, r.turns_today), ago(r.last_active_s) + ' ago', r.doing || ''];
    }); }
    var head = ['session', 'engine', 'context', 'turns today', 'cost today (API price estimate)', 'tokens today', 'last active', 'doing'];
    box.appendChild(table(head, sesRows(busy), 'compact'));
    if (u.read_at) box.appendChild(el('p', 'usage read ' + ago(sinceIso(u.read_at)) + ' ago' + (u.problems && u.problems.length ? '; ' + u.problems.join('; ') : ''), 'mono'));
    if (quiet.length) {
      var det = el('details'); det.appendChild(el('summary', quiet.length + ' quiet sessions (no turn today and idle for over an hour)'));
      det.appendChild(table(head, sesRows(quiet), 'compact')); box.appendChild(det);
    }
    return box;
  }

  function draw() {
    var box = $('live'), list = state.samples;
    clear(box);
    if (!list.length) { box.appendChild(el('p', 'waiting for the first sample...', 'mono')); return; }
    var last = list[list.length - 1], times = list.map(function (s) { return ms(s.t); });
    var lag = (Date.now() - times[times.length - 1]) / 1000;
    var status = $('live-status');
    if (lag > Math.max(3 * state.interval, 5)) { status.className = 'pill bad'; status.textContent = 'live stopped: last sample ' + Math.round(lag) + ' s ago'; }
    else { status.className = 'pill ok'; status.textContent = 'live, every ' + state.interval + ' s, last ' + Math.round(lag) + ' s ago'; }
    var spanS = Math.min(state.history, Math.max(60, (times[times.length - 1] - times[0]) / 1000));
    status.textContent += ', graphs show the last ' + (spanS >= 120 ? Math.round(spanS / 60) + ' min' : Math.round(spanS) + ' s');
    if (state.host && state.host.available === false) status.textContent += '; CPU, RAM, disks and network unknown: ' + state.host.reason;
    var grid = el('div', undefined, 'tiles');
    var cpu = tile('CPU', fmt(last.cpu_pct, 0, '%'), (state.host && state.host.logical_cpus ? state.host.logical_cpus + ' logical CPUs' : ''),
      times, list.map(function (s) { return s.cpu_pct; }), 100, last.cpu_pct !== null && last.cpu_pct >= 90);
    if (last.cpu_per_core) cpu.appendChild(coreStrip(last.cpu_per_core));
    grid.appendChild(cpu);
    grid.appendChild(tile('RAM', fmt(last.ram_pct, 0, '%'),
      fmt(last.ram_used_gib, 1) + ' / ' + fmt(last.ram_total_gib, 1) + ' GiB used' + (last.swap_total_gib ? ', swap ' + fmt(last.swap_used_gib, 1) + ' / ' + fmt(last.swap_total_gib, 1) + ' GiB' : ''),
      times, list.map(function (s) { return s.ram_pct; }), 100, last.ram_pct !== null && last.ram_pct >= 90));
    (last.gpus || []).forEach(function (g) {
      var find = function (s) { return (s.gpus || []).filter(function (x) { return x.uuid === g.uuid; })[0]; };
      var gtimes = times, util = list.map(function (s) { var x = find(s); return x ? x.util_pct : null; });
      var vram = list.map(function (s) { var x = find(s); return x && x.vram_used_mib !== null && x.vram_total_mib ? 100 * x.vram_used_mib / x.vram_total_mib : null; });
      grid.appendChild(tile('GPU ' + g.index + ' ' + g.name, fmt(g.util_pct, 0, '%'), gpuDetail(g), gtimes, util, 100, false));
      var vpct = g.vram_used_mib !== null && g.vram_total_mib ? 100 * g.vram_used_mib / g.vram_total_mib : null;
      grid.appendChild(tile('VRAM ' + g.index, fmt(vpct, 0, '%'),
        (g.vram_used_mib === null ? 'unknown' : (g.vram_used_mib / 1024).toFixed(1)) + ' / ' + (g.vram_total_mib === null ? 'unknown' : (g.vram_total_mib / 1024).toFixed(1)) + ' GiB used',
        gtimes, vram, 100, vpct !== null && vpct >= 95));
    });
    if (!last.gpus) grid.appendChild(tile('GPU', 'unknown', 'no GPU reading', times, [], 100, false));
    box.appendChild(grid);
    var more = el('div', undefined, 'live-more');
    if (state.slow) more.appendChild(storage(state.slow));
    more.appendChild(io(list, times));
    if (state.slow) more.appendChild(usageBlock(state.slow.usage));
    box.appendChild(more);
    if (last.problems && last.problems.length) box.appendChild(el('div', last.problems.join('; '), 'warn live-problems'));
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
  if (typeof module !== 'undefined') module.exports = { sparkPoints: sparkPoints };
})(typeof window !== 'undefined' ? window : this);
