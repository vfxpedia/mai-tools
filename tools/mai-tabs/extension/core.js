/* mai-tabs 0.2 core: builds the tab report and carries out actions through an api object, so the same code runs in the extension and
 * under Node with a fake browser (tests/extension.test.cjs). No network here; background.js does the fetches.
 *
 * api: { create({url, active, windowId}) -> tab, discard(tabId), remove(tabId), group({tabIds, windowId?, groupId?}) -> groupId,
 *        updateGroup(groupId, {title, collapsed}), findGroup(title) -> groupId|null, get(tabId) -> tab|null } */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MaiTabsCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function report(tabs, groups, instance) {
    return {
      instance: instance,
      tabs: (tabs || []).map(function (t) {
        return { id: t.id, windowId: t.windowId, url: t.url || t.pendingUrl || '', title: t.title || '', discarded: !!t.discarded,
                 active: !!t.active, pinned: !!t.pinned, audible: !!t.audible, groupId: typeof t.groupId === 'number' ? t.groupId : -1,
                 lastAccessed: typeof t.lastAccessed === 'number' ? Math.round(t.lastAccessed) : null };
      }),
      groups: (groups || []).map(function (g) { return { id: g.id, title: g.title || '', color: g.color || '' }; })
    };
  }

  function isWebUrl(u) { return /^https?:\/\//i.test(String(u || '')); }

  function samePage(a, b) {
    try {
      var x = new URL(a), y = new URL(b);
      var h = function (u) { return u.hostname.toLowerCase().replace(/^www\./, ''); };
      return x.protocol === y.protocol && h(x) === h(y) && x.port === y.port && x.pathname.replace(/\/+$/, '') === y.pathname.replace(/\/+$/, '');
    } catch (e) { return false; }
  }

  /* The plan was made from a report up to 30 s old, so right before closing or sleeping a tab it is read again: it must still exist,
   * still show the planned page, and not have become the tab the owner is looking at, a pinned tab or one playing sound. */
  function refuse(tab, step) {
    if (!tab) return 'it is gone';
    if (tab.active) return 'it is the tab in front';
    if (tab.pinned) return 'it is pinned';
    if (tab.audible) return 'it is playing sound';
    if (step.url && !samePage(tab.url || tab.pendingUrl || '', step.url)) return 'it shows another page now';
    return null;
  }

  function wait(ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); }

  /* A tab put to sleep before its address has committed loses the address, so wait until the browser reports one (at most ~5 s). */
  async function whenAddressed(api, id, tries) {
    for (var i = 0; i < (tries || 50); i++) {
      var t = await api.get(id);
      if (!t) return false;
      if (isWebUrl(t.url) && t.status !== 'unloaded') return true;
      await wait(100);
    }
    return false;
  }

  /* Runs one action. Every step is tried; a failed step is counted, never hidden. A group is made before anything is put to sleep,
   * because Chrome gives a tab a new id when it sleeps. Returns {id, ok, done, failed, note}. */
  async function run(cmd, api, opts) {
    var done = 0, failed = 0, notes = [], opened = [], toSleep = [];
    var tries = opts && opts.tries;
    function fail(e) { failed++; if (notes.length < 5) notes.push(String(e && e.message || e)); }
    for (var i = 0; i < (cmd.steps || []).length; i++) {
      var s = cmd.steps[i];
      try {
        if (s.do === 'open') {
          if (!isWebUrl(s.url)) throw new Error('not a web address');
          var t = await api.create({ url: s.url, active: false });
          opened.push(t.id);
          if (s.asleep) toSleep.push(t.id);
        } else if (s.do === 'discard' || s.do === 'remove') {
          var cur = await api.get(s.tab);
          var why = refuse(cur, s);
          if (why) throw new Error('tab ' + s.tab + ' left alone: ' + why);
          if (s.do === 'remove') await api.remove(s.tab);
          else if (!cur.discarded && !(await api.discard(s.tab))) throw new Error('Chrome did not put tab ' + s.tab + ' to sleep');
        } else {
          throw new Error('unknown step ' + s.do);
        }
        done++;
      } catch (e) { fail(e); }
    }
    var groupOk = true;
    if (cmd.group && opened.length) {
      try {
        var existing = await api.findGroup(cmd.group);
        var gid = await api.group(existing === null ? { tabIds: opened } : { tabIds: opened, groupId: existing });
        await api.updateGroup(gid, { title: cmd.group, collapsed: false });
      } catch (e) { groupOk = false; notes.push('group: ' + String(e && e.message || e)); }
    }
    for (var j = 0; j < toSleep.length; j++) {
      try {
        if (!(await whenAddressed(api, toSleep[j], tries))) throw new Error('page did not start loading, left awake');
        if (!(await api.discard(toSleep[j]))) throw new Error('Chrome did not put the new tab to sleep');
      } catch (e) { groupOk = false; notes.push('sleep: ' + String(e && e.message || e)); }
    }
    return { id: cmd.id, ok: failed === 0 && groupOk, done: done, failed: failed, note: notes.join('; ') };
  }

  return { report: report, run: run, isWebUrl: isWebUrl, samePage: samePage, refuse: refuse };
});
