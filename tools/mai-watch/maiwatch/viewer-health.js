/* Health of the collector as the viewer must judge it. Pure function, so Node tests can run it against the same cases as the Python
 * `maiwatch check` (tests/test_maiwatch.py compares both). A fresh heartbeat is not enough: the snapshot must come from the same
 * collector run and cycle, have its structure, and not be from the future (independent review M03, W4). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MaiWatchHealth = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$/;
  var SNAPSHOT_SCHEMA = 'maiwatch-snapshot-v1';

  function ms(s) {
    if (typeof s !== 'string' || !TIME.test(s)) return NaN;
    return Date.parse(s);
  }

  /* hb: parsed collector_heartbeat.json or null, snap: parsed snapshot.json or null. Returns a list of {type, detail}; empty means healthy. */
  function health(hb, snap, nowMs) {
    var out = [];
    var last = NaN, interval = NaN;
    if (!hb || typeof hb !== 'object') {
      out.push({ type: 'collector_missing', detail: 'no heartbeat' });
      hb = null;
    } else {
      last = ms(hb.last_cycle_at);
      interval = hb.interval_s;
      if (isNaN(last) || typeof interval !== 'number' || !isFinite(interval) || interval <= 0) {
        out.push({ type: 'collector_missing', detail: 'heartbeat time or interval is not valid' });
        hb = null;
      } else {
        var age = (nowMs - last) / 1000;
        if (age < -2 * interval) out.push({ type: 'collector_clock', detail: 'heartbeat is ' + Math.round(-age) + ' s in the future' });
        else if (age > 3 * interval) out.push({ type: 'collector_stale', detail: 'last cycle ' + Math.round(age) + ' s ago' });
      }
    }
    if (!snap || typeof snap !== 'object') {
      out.push({ type: 'snapshot_missing', detail: 'no snapshot' });
      return out;
    }
    var problems = [];
    if (snap.schema !== SNAPSHOT_SCHEMA) {
      problems.push('schema is not ' + SNAPSHOT_SCHEMA);
    } else {
      ['devices', 'workloads', 'invalid', 'alerts'].forEach(function (k) { if (!Array.isArray(snap[k])) problems.push(k + ' missing or not a list'); });
      var gen = ms(snap.generated_at);
      if (isNaN(gen)) {
        problems.push('generated_at is not a valid time');
      } else {
        if (hb) {
          if (Math.abs(gen - last) / 1000 > 1.5 * interval) problems.push('generated_at does not belong to the heartbeat cycle');
          var c = snap.collector || {};
          if (c.pid !== hb.pid || c.started_at !== hb.started_at) problems.push('snapshot comes from a different collector run than the heartbeat');
        }
        if ((gen - nowMs) / 1000 > 2 * (hb ? interval : 10)) problems.push('generated_at is in the future');
      }
    }
    if (problems.length) out.push({ type: 'snapshot_invalid', detail: problems.join('; ') });
    return out;
  }

  /* Problems with the shape of a snapshot, before anything is drawn from it. Empty list means every list the page reads is a list. */
  function structureProblems(snap) {
    if (!snap || typeof snap !== 'object') return ['snapshot is not an object'];
    if (snap.schema !== SNAPSHOT_SCHEMA) return ['schema is not ' + SNAPSHOT_SCHEMA];
    var out = [];
    ['devices', 'workloads', 'invalid', 'alerts'].forEach(function (k) { if (!Array.isArray(snap[k])) out.push(k + ' missing or not a list'); });
    return out;
  }

  return { health: health, structureProblems: structureProblems };
});
