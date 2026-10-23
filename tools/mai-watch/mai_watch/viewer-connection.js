/* Bounded reads and one polling loop per source. No telemetry or remote control. */
(function (root) {
  'use strict';
  function read(url, kind, signal) {
    return root.fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 't=' + root.Date.now(),
      {cache: 'no-store', signal: signal}).then(function (r) {
      if (!r.ok) { var e = new Error(url.split('?')[0] + ' returned ' + r.status); e.status = r.status; throw e; }
      return kind === 'text' ? r.text() : r.json();
    });
  }
  function createLoop(o) {
    var generation = 0, timer, deadline, controller, busy = false, stopped = true;
    function stop() {
      stopped = true; generation++; busy = false;
      root.clearTimeout(timer); root.clearTimeout(deadline);
      if (controller) controller.abort();
    }
    function requestNow(replace) {
      if (stopped || (busy && !replace)) return;
      root.clearTimeout(timer); root.clearTimeout(deadline);
      var g = ++generation;
      if (controller) controller.abort();
      controller = new root.AbortController();
      var signal = controller.signal;
      busy = true;
      var timeout = new Promise(function (_, reject) {
        deadline = root.setTimeout(function () {
          reject(new Error('Request timed out after 6 s')); controller.abort();
        }, 6000);
      });
      var failed = false;
      Promise.race([Promise.resolve().then(function () { return o.task(signal); }), timeout]).then(function (data) {
        if (g === generation && !stopped) o.onData(data);
      }).catch(function (e) {
        if (g !== generation || stopped) return;
        failed = true;
        if (o.onError) o.onError(e);
      }).finally(function () {
        if (g !== generation || stopped) return;
        busy = false; root.clearTimeout(deadline);
        timer = root.setTimeout(requestNow, failed ? 3000 : Math.max(500, o.interval()));
      });
    }
    return {start: function () { stopped = false; requestNow(); }, requestNow: requestNow, stop: stop};
  }
  var loops = [], bound = false, resumeTimer;
  function bind(loop) {
    loops.push(loop);
    if (bound) return;
    bound = true;
    function resume() {
      if (root.document.hidden) return;
      root.clearTimeout(resumeTimer);
      resumeTimer = root.setTimeout(function () { loops.forEach(function (p) { p.requestNow(true); }); }, 250);
    }
    root.document.addEventListener('visibilitychange', resume);
    root.addEventListener('pageshow', resume);
    root.addEventListener('online', resume);
  }
  function freshness(now, received, measured, interval, error) {
    var receivedAge = typeof received === 'number' ? Math.max(0, (now - received) / 1000) : null;
    var sampleAge = typeof measured === 'number' && isFinite(measured) ? (now - measured) / 1000 : null;
    var limit = Math.max(3 * interval, 5), kind;
    if (error) kind = 'disconnected';
    else if (receivedAge === null) kind = 'waiting';
    else if (sampleAge === null || sampleAge < -2 * interval) kind = 'unknown';
    else if (receivedAge > limit || sampleAge > limit) kind = 'stale';
    else kind = 'live';
    return {kind: kind, receivedAge: receivedAge, sampleAge: sampleAge === null ? null : Math.max(0, sampleAge)};
  }
  function mountRefresh() {
    var button = root.document.getElementById('refresh');
    if (!button) return;
    button.addEventListener('click', function () {
      if (button.disabled) return;
      button.disabled = true; button.textContent = 'Reloading…';
      root.location.reload();
    });
  }
  root.MaiWatchConnection = {read: read, createLoop: createLoop, bind: bind, freshness: freshness, mountRefresh: mountRefresh};
})(typeof window !== 'undefined' ? window : globalThis);
