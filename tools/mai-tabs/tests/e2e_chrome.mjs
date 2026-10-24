// End-to-end check in a real Chrome (DESIGN.md section 12.6). Not part of CI: it needs Chrome on this machine.
// It uses a throwaway profile and data folder, a copy of the extension pointed at a free port, and local test pages, then drives the
// library through its HTTP API and checks what the browser actually did. Nothing touches the owner's profile or library.
//   node tests/e2e_chrome.mjs [--chrome <path>] [--headful]
// Chrome 137+ ignores --load-extension, so the extension is loaded with the DevTools command Extensions.loadUnpacked over a pipe.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const tool = path.resolve(here, '..');
const args = process.argv.slice(2);
const chromePath = args.includes('--chrome') ? args[args.indexOf('--chrome') + 1] : ({
  win32: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  darwin: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
}[process.platform] || 'google-chrome');
const headful = args.includes('--headful');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

const free = () => new Promise((ok) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const results = [];
function check(name, cond, detail) { results.push({ name, ok: !!cond }); console.log((cond ? 'ok   ' : 'FAIL ') + name + (detail ? '  ' + detail : '')); }

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mai-tabs-e2e-'));
const procs = [];
let chrome;
try {
  const libPort = await free(), pagePort = await free();
  const pages = path.join(tmp, 'pages'), home = path.join(tmp, 'home'), ext = path.join(tmp, 'ext'), profile = path.join(tmp, 'profile');
  fs.mkdirSync(pages); fs.mkdirSync(home); fs.cpSync(path.join(tool, 'extension'), ext, { recursive: true });
  for (const n of [1, 2, 3, 4]) fs.writeFileSync(path.join(pages, `p${n}.html`), `<!doctype html><title>Page ${n}</title><p>page ${n}`);
  for (const f of ['background.js', 'manifest.json']) {
    const p = path.join(ext, f);
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replaceAll('127.0.0.1:28766', '127.0.0.1:' + libPort));
  }
  procs.push(spawn(python, ['-m', 'mai_tabs', 'serve', '--port', String(libPort), '--home', home], { cwd: tool, stdio: 'ignore' }));
  procs.push(spawn(python, ['-m', 'http.server', String(pagePort), '--bind', '127.0.0.1', '--directory', pages], { stdio: 'ignore' }));
  const lib = 'http://127.0.0.1:' + libPort, page = (n) => `http://127.0.0.1:${pagePort}/p${n}.html`;
  for (let i = 0; i < 50; i++) { try { if ((await fetch(lib + '/healthz')).ok) break; } catch {} await sleep(200); }
  const view = async () => (await fetch(lib + '/api/view')).json();
  const command = async (body) => (await fetch(lib + '/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Mai-Tabs': '1' }, body: JSON.stringify(body) })).json();
  async function until(what, fn, ms = 40000) {
    const end = Date.now() + ms;
    let last;
    while (Date.now() < end) { last = await fn(); if (last) return last; await sleep(500); }
    check(what, false, 'timed out');
    try {
      console.log('  live tabs: ' + JSON.stringify(JSON.parse(fs.readFileSync(path.join(home, 'live.json'), 'utf8')).tabs.map((t) => [t.item, t.discarded, t.group])));
      console.log('  last actions: ' + JSON.stringify((await view()).commands.slice(0, 2).map((c) => [c.action, c.state, c.result])));
    } catch {}
    throw new Error('timed out: ' + what);
  }

  chrome = spawn(chromePath, [...(headful ? [] : ['--headless=new']), '--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-pipe', '--enable-unsafe-extension-debugging', 'about:blank'], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const toChrome = chrome.stdio[3], fromChrome = chrome.stdio[4];
  let buf = '', nextId = 1;
  const waiting = new Map();
  fromChrome.on('data', (d) => {
    buf += d.toString('utf8');
    let i;
    while ((i = buf.indexOf('\0')) >= 0) {
      const msg = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
      if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
    }
  });
  const cdp = (method, params = {}) => new Promise((ok, bad) => {
    const id = nextId++;
    waiting.set(id, (m) => (m.error ? bad(new Error(method + ': ' + m.error.message)) : ok(m.result)));
    toChrome.write(JSON.stringify({ id, method, params }) + '\0');
  });

  const loaded = await cdp('Extensions.loadUnpacked', { path: ext });
  check('extension loads in Chrome ' + (await cdp('Browser.getVersion')).product, loaded && loaded.id, loaded && loaded.id);
  for (const n of [1, 2, 2, 3]) await cdp('Target.createTarget', { url: page(n), background: true });

  let v = await until('tabs reach the library', async () => { const x = await view(); return x.items.length === 3 && x.live.tabs >= 4 && x; });
  const byTitle = (x, t) => x.items.find((i) => i.title === t);
  check('a page open twice is one item', byTitle(v, 'Page 2').open_tabs === 2 && v.live.duplicates === 1);

  const p1 = byTitle(v, 'Page 1').id, p2 = byTitle(v, 'Page 2').id, p3 = byTitle(v, 'Page 3').id;
  const sleepCmd = await command({ action: 'sleep', items: [p1] });
  check('sleep is planned for one tab', sleepCmd.steps && sleepCmd.steps.length === 1, JSON.stringify(sleepCmd.steps));
  v = await until('Page 1 is asleep in Chrome', async () => { const x = await view(); const it = byTitle(x, 'Page 1'); return it.open_tabs === 1 && it.awake_tabs === 0 && x; });
  check('sleeping keeps the tab', byTitle(v, 'Page 1').open_tabs === 1);

  await command({ action: 'dedupe', items: [] });
  v = await until('duplicate closed', async () => { const x = await view(); return byTitle(x, 'Page 2').open_tabs === 1 && x; });
  check('dedupe leaves one copy and no duplicates', v.live.duplicates === 0);

  await command({ action: 'close', items: [p3] });
  v = await until('Page 3 closed', async () => { const x = await view(); return byTitle(x, 'Page 3').open_tabs === 0 && x; });
  check('a closed page stays in the library', !!byTitle(v, 'Page 3'));

  await command({ action: 'open', items: [p3, p2], group: 'E2E 묶음', asleep: true });
  v = await until('group opened', async () => { const x = await view(); return byTitle(x, 'Page 3').open_tabs === 1 && byTitle(x, 'Page 2').open_tabs === 2 && x; });
  const live = JSON.parse(fs.readFileSync(path.join(home, 'live.json'), 'utf8'));
  const group = live.groups.find((g) => g.title === 'E2E 묶음');
  const inGroup = group ? live.tabs.filter((t) => t.group === group.id) : [];
  check('opened as one named tab group', group && inGroup.length === 2, group ? `${inGroup.length} tabs in group` : 'no group');
  check('opened asleep', inGroup.length === 2 && inGroup.every((t) => t.discarded), JSON.stringify(inGroup.map((t) => t.discarded)));

  v = await until('memory measured after the sleep', async () => { const x = await view(); const c = x.commands.find((k) => k.id === sleepCmd.id); return c && c.after && x; }, 45000);
  const ch = v.commands.find((k) => k.id === sleepCmd.id).after.change;
  check('before and after are both measured', ch && ch.browser_mib !== null && ch.seconds >= 15, JSON.stringify(ch));
  const done = v.commands.filter((c) => c.state === 'done').length;
  check('every action was acknowledged', done === v.commands.length, `${done}/${v.commands.length}`);
} catch (e) {
  check('run finished', false, String(e && e.stack || e));
} finally {
  try { chrome && chrome.kill(); } catch {}
  for (const p of procs) { try { p.kill(); } catch {} }
  await sleep(1500);
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch {}
  const failed = results.filter((r) => !r.ok).length;
  console.log(`${results.length - failed}/${results.length} checks passed`);
  process.exitCode = failed || !results.length ? 1 : 0;
}
