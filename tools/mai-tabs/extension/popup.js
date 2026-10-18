/* Popup: reads windows and tab groups, builds the export with export.js, checks it, and requests a file download. No network, no storage.
 * A download request is not a file that arrived: the message says "requested", and the owner compares the counts with the file (M3). */
(function () {
  'use strict';
  var statusEl = document.getElementById('status');

  function browserInfo() {
    var m = /(Edg|Chrome|Firefox)\/([0-9.]+)/.exec(navigator.userAgent);
    return { name: m ? (m[1] === 'Edg' ? 'edge' : m[1].toLowerCase()) : 'unknown', version: m ? m[2] : '' };
  }

  function stamp(d) {
    function p(n) { return String(n).padStart(2, '0'); }
    return d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate()) + 'T' + p(d.getUTCHours()) + p(d.getUTCMinutes()) + p(d.getUTCSeconds()) + 'Z';
  }

  async function run() {
    statusEl.textContent = 'Reading tabs...';
    var windows = await chrome.windows.getAll({ populate: true });
    var groups = [];
    var groupsError = null;
    var groupsSupported = !!(chrome.tabGroups && chrome.tabGroups.query);
    if (groupsSupported) {
      try { groups = await chrome.tabGroups.query({}); } catch (e) { groupsError = e && e.message ? e.message : String(e); }
    }
    var now = new Date();
    var data = MaiTabs.buildExport({
      browser: browserInfo(), nowIso: now.toISOString().replace(/\.[0-9]+Z$/, 'Z'),
      windows: windows, groups: groups, groupsError: groupsError, groupsSupported: groupsSupported
    });
    var problems = MaiTabs.consistencyProblems(data);
    if (problems.length) {
      statusEl.textContent = 'Not saved: the export is inconsistent (' + problems[0] + ')';
      return;
    }
    var blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'mai-tabs-' + stamp(now) + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    statusEl.textContent = 'Download requested: ' + data.counts.tabs + ' tabs, ' + data.counts.windows + ' windows, ' + data.counts.groups + ' groups as ' + a.download +
      (data.collection.complete ? '' : '. INCOMPLETE: ' + data.collection.notes.join('; ')) + '. Check that the file exists.';
  }

  document.getElementById('export').addEventListener('click', function () {
    run().catch(function (e) { statusEl.textContent = 'Failed: ' + e.message; });
  });
})();
