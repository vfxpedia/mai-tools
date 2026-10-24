/* mai-tabs 0.2 background worker. Every 30 seconds, and two seconds after any tab change, it sends the open tabs to the local library
 * server and carries out the actions the server hands back (open, sleep, close), then reports each result.
 * The server address is fixed to this computer (127.0.0.1); the page on a phone talks to the server, never to the browser. */
importScripts('core.js');

var SERVER = 'http://127.0.0.1:28766';
var busy = false, again = false, timer = null;

async function post(path, body) {
  var r = await fetch(SERVER + path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Mai-Tabs': '1' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(path + ' ' + r.status);
  return r.json();
}

async function groupsAll() {
  try { return await chrome.tabGroups.query({}); } catch (e) { return []; }
}

var api = {
  create: function (o) { return chrome.tabs.create(o); },
  discard: function (id) { return chrome.tabs.discard(id); },
  remove: function (id) { return chrome.tabs.remove(id); },
  get: async function (id) { try { return await chrome.tabs.get(id); } catch (e) { return null; } },
  group: function (o) { return chrome.tabs.group(o); },
  updateGroup: function (id, o) { return chrome.tabGroups.update(id, o); },
  findGroup: async function (title) {
    var g = (await groupsAll()).filter(function (x) { return x.title === title; });
    return g.length ? g[0].id : null;
  }
};

async function syncOnce() {
  var tabs = await chrome.tabs.query({});
  var answer = await post('/api/sync', MaiTabsCore.report(tabs, await groupsAll()));
  var status = { at: Date.now(), ok: true, counts: answer.counts, error: null };
  for (var i = 0; i < (answer.commands || []).length; i++) {
    var res = await MaiTabsCore.run(answer.commands[i], api);
    await post('/api/ack', res);
    status.last_action = res;
  }
  await chrome.storage.local.set({ status: status });
  return (answer.commands || []).length;
}

async function sync() {
  if (busy) { again = true; return; }
  busy = true;
  try {
    var ran = await syncOnce();
    if (ran) await syncOnce();                 // report the tabs as the actions left them
  } catch (e) {
    await chrome.storage.local.set({ status: { at: Date.now(), ok: false, error: String(e && e.message || e) } });
  } finally {
    busy = false;
    if (again) { again = false; soon(); }
  }
}

function soon() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(function () { timer = null; sync(); }, 2000);
}

chrome.alarms.create('mai-tabs-sync', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(function (a) { if (a.name === 'mai-tabs-sync') sync(); });
chrome.runtime.onStartup.addListener(sync);
chrome.runtime.onInstalled.addListener(sync);
chrome.tabs.onCreated.addListener(soon);
chrome.tabs.onRemoved.addListener(soon);
chrome.tabs.onUpdated.addListener(function (id, info) { if (info.url || info.title || info.discarded !== undefined || info.groupId !== undefined) soon(); });
chrome.runtime.onMessage.addListener(function (m, s, reply) {
  if (m && m.type === 'sync-now') { sync().then(function () { reply({ ok: true }); }); return true; }
  return false;
});
