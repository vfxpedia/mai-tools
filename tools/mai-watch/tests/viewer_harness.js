// Runs the real inline script of mai_watch/viewer.html against a tiny fake DOM and fake fetch, once per case.
// stdin: JSON list of cases {hb, snapshot, snapshot_status, events, now_ms}. stdout: JSON list of what the page showed.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const dir = path.join(__dirname, '..', 'mai_watch');
const html = fs.readFileSync(path.join(dir, 'viewer.html'), 'utf8');
const healthSrc = fs.readFileSync(path.join(dir, 'viewer-health.js'), 'utf8');
const inline = html.split('<script>')[1].split('</script>')[0];
const ids = Array.from(html.matchAll(/id="([a-z]+)"/g)).map(m => m[1]);

function makeEl() {
  const e = { style: {}, className: '', children: [], _text: '', colSpan: 1, attrs: {}, listeners: {} };
  e.appendChild = c => { e.children.push(c); return c; };
  e.removeChild = c => { e.children.splice(e.children.indexOf(c), 1); return c; };
  e.setAttribute = (k, v) => { e.attrs[k] = String(v); };
  e.removeAttribute = k => { delete e.attrs[k]; };
  e.addEventListener = (k, f) => { e.listeners[k] = f; };
  Object.defineProperty(e, 'firstChild', { get: () => e.children[0] || null });
  Object.defineProperty(e, 'textContent', { get: () => e._text, set: v => { e._text = String(v); e.children = []; } });
  return e;
}
function allText(e) { return e._text + e.children.map(allText).join(' '); }

async function runCase(c) {
  const els = {};
  ids.forEach(i => { els[i] = makeEl(); });
  const document = { getElementById: i => els[i], createElement: () => makeEl(), body: makeEl() };
  const localStorage = { getItem: () => null, setItem: () => {} };
  let timer = null;
  const responses = {
    'collector_heartbeat.json': c.hb === null ? { status: 404, body: '' } : { status: 200, body: JSON.stringify(c.hb) },
    'snapshot.json': { status: c.snapshot_status || 200, body: typeof c.snapshot === 'string' ? c.snapshot : JSON.stringify(c.snapshot) },
    'events.jsonl': { status: 200, body: c.events || '' },
  };
  const fetch = url => {
    const r = responses[url.split('?')[0]];
    return Promise.resolve({ ok: r.status >= 200 && r.status < 300, status: r.status, json: () => Promise.resolve(JSON.parse(r.body)), text: () => Promise.resolve(r.body) });
  };
  const RealDate = Date;
  const FakeDate = function () { return new RealDate(c.now_ms); };
  FakeDate.now = () => c.now_ms;
  FakeDate.parse = RealDate.parse;
  const sandbox = { document, localStorage, fetch, Date: FakeDate, Math, JSON, Promise, Object, Array, String, Number, isNaN, isFinite, setInterval: () => 0, console };
  sandbox.window = sandbox; sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(healthSrc, sandbox);
  vm.runInContext(inline, sandbox);
  await new Promise(r => setTimeout(r, 30));
  return {
    error_shown: els.error.style.display === 'block',
    error: els.error._text,
    pill: els.collector._text,
    pill_class: els.collector.className,
    device_rows: els.devices.children.length,
    alerts_text: allText(els.alerts),
    alert_parts: els.alerts.children.length,
    theme_label: els.theme._text,
    workload_text: allText(els.workloads),
  };
}

let input = '';
process.stdin.on('data', d => input += d).on('end', async () => {
  const out = [];
  for (const c of JSON.parse(input)) out.push(await runCase(c));
  console.log(JSON.stringify(out));
});
