/* mai-tabs 0.2 background worker. Every 30 seconds, and two seconds after any tab change, it sends the open tabs to the local library
 * server and carries out the actions the server hands back (open, sleep, close), then reports each result.
 * It talks only to the server's extension port on this computer (127.0.0.1:28771), which is never exposed to other devices; the page on
 * a phone talks to the server, never to the browser. Each browser profile has its own random instance id, so actions planned from one
 * profile's tabs are only handed to that profile. */
importScripts('core.js');

var SERVER = 'http://127.0.0.1:28771';
var timer = null;

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

async function instanceId() {
  var d = await chrome.storage.local.get('instance');
  if (d.instance) return d.instance;
  var bytes = crypto.getRandomValues(new Uint8Array(12));
  var id = Array.from(bytes, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  await chrome.storage.local.set({ instance: id });
  return id;
}

async function syncOnce() {
  var tabs = await chrome.tabs.query({});
  var answer = await post('/api/sync', MaiTabsCore.report(tabs, await groupsAll(), await instanceId()));
  var status = { at: Date.now(), ok: true, counts: answer.counts, error: null };
  for (var i = 0; i < (answer.commands || []).length; i++) {
    var res = await MaiTabsCore.run(answer.commands[i], api);
    await post('/api/ack', res);
    status.last_action = res;
  }
  await chrome.storage.local.set({ status: status });
  return (answer.commands || []).length;
}

/* One sync at a time. A call that arrives while one is running waits for the next full sync, so "send now" in the popup reports a sync
 * that started after the button was pressed, never the one already under way. */
var running = null, queued = null;
function sync() {
  if (running) {
    if (!queued) queued = running.then(function () { queued = null; return sync(); });
    return queued;
  }
  running = (async function () {
    try {
      var ran = await syncOnce();
      if (ran) await syncOnce();                 // report the tabs as the actions left them
    } catch (e) {
      await chrome.storage.local.set({ status: { at: Date.now(), ok: false, error: String(e && e.message || e) } });
    }
  })().finally(function () { running = null; });
  return running;
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
