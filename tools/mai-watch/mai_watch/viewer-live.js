/* Live panel of the viewer (DESIGN.md section 9c). Reads live.json from `python -m mai_watch live` about once a second and draws CPU, RAM,
 * GPU and VRAM with their recent history. A value the sampler could not read is shown as unknown, never as 0. When the server has no
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

  /* Pure: polyline points for values in [0, max] over the time window, null values break the line. Exported for tests. */
  function sparkPoints(times, values, now, windowS, max, w, h) {
    var segs = [], cur = [];
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
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
    sparkPoints(times, values, now, windowS, max, w, h).forEach(function (pts) {
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
      grid.appendChild(tile('GPU ' + g.index + ' ' + g.name, fmt(g.util_pct, 0, '%'),
        (g.temperature_c === null ? '' : g.temperature_c + ' C  ') + (g.power_w === null ? '' : g.power_w.toFixed(0) + ' W'), gtimes, util, 100, false));
      var vpct = g.vram_used_mib !== null && g.vram_total_mib ? 100 * g.vram_used_mib / g.vram_total_mib : null;
      grid.appendChild(tile('VRAM ' + g.index, fmt(vpct, 0, '%'),
        (g.vram_used_mib === null ? 'unknown' : (g.vram_used_mib / 1024).toFixed(1)) + ' / ' + (g.vram_total_mib === null ? 'unknown' : (g.vram_total_mib / 1024).toFixed(1)) + ' GiB used',
        gtimes, vram, 100, vpct !== null && vpct >= 95));
    });
    if (!last.gpus) grid.appendChild(tile('GPU', 'unknown', 'no GPU reading', times, [], 100, false));
    box.appendChild(grid);
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
      state.active = true; state.interval = d.interval_s; state.history = d.history_s; state.host = d.host;
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
