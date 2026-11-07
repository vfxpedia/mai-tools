/* Tabs (owner 11/03 · 11/07): Resources is always there; GPU 작업 and 작업 appear only when the server has their data (each script
 * probes its own JSON and calls add). One tab is shown at a time, and only the shown tab polls. The choice is kept in this browser and
 * can be asked for in the address: #gpu or #work. */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc || !doc.getElementById('tabs')) return;
  var panes = {}, current = 'live', wanted = null;
  try { wanted = root.localStorage.getItem('mai-watch-tab'); } catch (_) { wanted = null; }
  var m = /#(gpu|work)\b/.exec(root.location.hash || '');
  if (m) wanted = m[1];

  function buttons() { return doc.querySelectorAll('.tabs [data-tab]'); }

  function show(name) {
    current = name !== 'live' && panes[name] ? name : 'live';
    buttons().forEach(function (b) { b.setAttribute('aria-selected', String(b.getAttribute('data-tab') === current)); });
    doc.body.setAttribute('data-tab', current);
    try { root.localStorage.setItem('mai-watch-tab', current); } catch (_) {}
    Object.keys(panes).forEach(function (k) { if (k === current) panes[k].start(); else panes[k].stop(); });
  }

  function add(name, pane) {
    panes[name] = pane;
    var b = doc.querySelector('.tabs [data-tab="' + name + '"]');
    if (b) b.hidden = false;
    doc.getElementById('tabs').hidden = false;
    if (wanted === name) show(name);
  }

  buttons().forEach(function (b) { b.addEventListener('click', function () { show(b.getAttribute('data-tab')); }); });
  doc.body.setAttribute('data-tab', 'live');
  root.MaiWatchTabs = { add: add, show: show, current: function () { return current; } };
})(typeof window !== 'undefined' ? window : globalThis);
