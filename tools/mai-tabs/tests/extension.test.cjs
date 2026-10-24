// mai-tabs 0.2 extension core against a fake browser. Run: node --test tests/extension.test.cjs (from tools/mai-tabs).
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const core = require('../extension/core.js');

function fakeBrowser() {
  const b = { tabs: new Map(), groups: new Map(), next: 100, nextGroup: 1, calls: [] };
  b.api = {
    create: async (o) => { const t = { id: b.next++, url: '', pendingUrl: o.url, active: !!o.active, discarded: false, groupId: -1, gets: 0 }; b.tabs.set(t.id, t); b.calls.push(['create', o.url]); return { ...t }; },
    discard: async (id) => { const t = b.tabs.get(id); if (!t) throw new Error('No tab with id: ' + id); if (t.active) throw new Error('cannot discard the active tab'); b.tabs.delete(id); const n = { ...t, id: b.next++, discarded: true, lost: !t.url }; b.tabs.set(n.id, n); b.calls.push(['discard', id]); return n; },
    remove: async (id) => { if (!b.tabs.delete(id)) throw new Error('No tab with id: ' + id); b.calls.push(['remove', id]); },
    get: async (id) => { const t = b.tabs.get(id); if (!t) return null; if (++t.gets >= 3 && !t.url) { t.url = t.pendingUrl; } return { ...t }; },
    group: async (o) => { const gid = o.groupId != null ? o.groupId : b.nextGroup++; if (!b.groups.has(gid)) b.groups.set(gid, { id: gid, title: '' }); o.tabIds.forEach((i) => { b.tabs.get(i).groupId = gid; }); return gid; },
    updateGroup: async (gid, o) => { Object.assign(b.groups.get(gid), o); },
    findGroup: async (title) => { for (const g of b.groups.values()) if (g.title === title) return g.id; return null; },
  };
  return b;
}

test('report keeps what the server needs and nothing undefined', () => {
  const r = core.report([{ id: 1, windowId: 2, url: 'https://a.example/', title: 'A', groupId: 3, lastAccessed: 5.6 }, { id: 2, pendingUrl: 'https://b.example/' }], [{ id: 3, title: 'G' }], 'inst12345');
  assert.strictEqual(r.instance, 'inst12345');
  assert.deepStrictEqual(r.tabs[0], { id: 1, windowId: 2, url: 'https://a.example/', title: 'A', discarded: false, active: false, pinned: false, audible: false, groupId: 3, lastAccessed: 6 });
  assert.strictEqual(r.tabs[1].url, 'https://b.example/');
  assert.strictEqual(r.tabs[1].groupId, -1);
  assert.deepStrictEqual(r.groups, [{ id: 3, title: 'G', color: '' }]);
});

test('open as a named group, asleep, and reuse the group the next time', async () => {
  const b = fakeBrowser();
  const cmd = { id: 9, group: '논문', steps: [{ do: 'open', url: 'https://arxiv.org/abs/1', asleep: true }, { do: 'open', url: 'https://arxiv.org/abs/2', asleep: true }] };
  const res = await core.run(cmd, b.api);
  assert.deepStrictEqual(res, { id: 9, ok: true, done: 2, failed: 0, note: '' });
  const opened = [...b.tabs.values()];
  assert.strictEqual(opened.length, 2);
  assert.ok(opened.every((t) => t.discarded && !t.lost && t.groupId === 1), JSON.stringify(opened));   // grouped before sleeping, slept after the address came
  assert.strictEqual(b.groups.get(1).title, '논문');
  await core.run({ id: 10, group: '논문', steps: [{ do: 'open', url: 'https://arxiv.org/abs/3' }] }, b.api);
  assert.strictEqual(b.groups.size, 1);
  assert.ok([...b.tabs.values()].every((t) => t.groupId === 1));
});

test('a group that cannot be made is a failure, not a quiet success', async () => {
  const b = fakeBrowser();
  b.api.group = async () => { throw new Error('No tab with id: 1'); };
  const res = await core.run({ id: 4, group: 'G', steps: [{ do: 'open', url: 'https://ok.example/' }] }, b.api);
  assert.deepStrictEqual([res.ok, res.done], [false, 1]);
  assert.match(res.note, /group: No tab/);
});

test('a page that never gets an address is left awake and reported', async () => {
  const b = fakeBrowser();
  b.api.get = async (id) => ({ ...b.tabs.get(id) });         // the address never commits
  const res = await core.run({ id: 5, steps: [{ do: 'open', url: 'https://ok.example/', asleep: true }] }, b.api, { tries: 3 });
  assert.strictEqual(res.ok, false);
  assert.match(res.note, /left awake/);
  assert.ok([...b.tabs.values()].every((t) => !t.discarded));
});

test('a failed step is counted and the others still run', async () => {
  const b = fakeBrowser();
  b.tabs.set(5, { id: 5, active: true, discarded: false });
  b.tabs.set(6, { id: 6, active: false, discarded: false });
  const res = await core.run({ id: 1, steps: [{ do: 'discard', tab: 5 }, { do: 'discard', tab: 6 }, { do: 'remove', tab: 77 }, { do: 'discard', tab: 88 }] }, b.api);
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.done, 1);
  assert.strictEqual(res.failed, 3);
  assert.match(res.note, /tab 5 left alone: it is the tab in front/);
  assert.ok(!b.tabs.has(6) && [...b.tabs.values()].some((t) => t.discarded && t.url === undefined));   // tab 6 slept (under a new id)
});

test('only web addresses are opened', async () => {
  const b = fakeBrowser();
  const res = await core.run({ id: 2, steps: [{ do: 'open', url: 'javascript:alert(1)' }, { do: 'open', url: 'file:///C:/x' }, { do: 'open', url: 'https://ok.example/' }] }, b.api);
  assert.strictEqual(res.done, 1);
  assert.strictEqual(res.failed, 2);
  assert.deepStrictEqual(b.calls, [['create', 'https://ok.example/']]);
});

test('an unknown step is a failure, not a silent skip', async () => {
  const b = fakeBrowser();
  const res = await core.run({ id: 3, steps: [{ do: 'format' }] }, b.api);
  assert.deepStrictEqual([res.ok, res.done, res.failed], [false, 0, 1]);
});

test('Chrome declining to discard (undefined) is a failure', async () => {
  // review finding 2: chrome.tabs.discard resolves to undefined when it could not discard
  const b = fakeBrowser();
  b.tabs.set(6, { id: 6, url: 'https://a.example/x', active: false, discarded: false });
  b.api.discard = async () => undefined;
  const res = await core.run({ id: 1, steps: [{ do: 'discard', tab: 6, url: 'https://a.example/x' }, { do: 'open', url: 'https://a.example/y', asleep: true }] }, b.api);
  assert.deepStrictEqual([res.ok, res.done, res.failed], [false, 1, 1]);
  assert.match(res.note, /did not put tab 6 to sleep/);
  assert.match(res.note, /did not put the new tab to sleep/);
});

test('a tab is checked again right before it is closed or put to sleep', async () => {
  // review finding 1: the plan is up to 30 s old
  const b = fakeBrowser();
  b.tabs.set(1, { id: 1, url: 'https://a.example/x', active: true });
  b.tabs.set(2, { id: 2, url: 'https://a.example/other' });
  b.tabs.set(3, { id: 3, url: 'https://a.example/x', pinned: true });
  b.tabs.set(4, { id: 4, url: 'https://a.example/x', audible: true });
  b.tabs.set(5, { id: 5, url: 'https://www.a.example/x/' });
  const steps = [1, 2, 3, 4, 5, 9].map((t) => ({ do: 'remove', tab: t, url: 'https://a.example/x' }));
  const res = await core.run({ id: 2, steps }, b.api);
  assert.deepStrictEqual([res.done, res.failed], [1, 5]);
  assert.deepStrictEqual([...b.tabs.keys()].sort(), [1, 2, 3, 4]);
  for (const why of ['in front', 'another page', 'pinned', 'playing sound', 'gone']) assert.ok(res.note.includes(why), why);
});
