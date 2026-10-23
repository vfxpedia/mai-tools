// Execute the production renderer. The DOM double records visibility and nesting, not CSS geometry.
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
function element(tag) {
  const e = { tag, children: [], style: {}, className: '', textContent: '', open: false, listeners: {} };
  e.appendChild = n => { e.children.push(n); return n; };
  e.removeChild = n => e.children.splice(e.children.indexOf(n), 1);
  e.setAttribute = () => {};
  e.addEventListener = (name, fn) => { e.listeners[name] = fn; };
  Object.defineProperty(e, 'firstChild', { get: () => e.children[0] || null });
  return e;
}
function run(c) {
  const live = element('div'), status = element('span'); let ready = false;
  const document = { getElementById: id => ready ? (id === 'live' ? live : status) : null,
    createElement: element, createElementNS: (ns, tag) => element(tag) };
  const box = { document, innerWidth: c.width || 390, Date, Math, JSON, console, isFinite, setTimeout: () => 0 };
  box.window = box;
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../mai_watch/viewer-connection.js'), 'utf8'), box);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../mai_watch/viewer-live.js'), 'utf8'), box);
  ready = true;
  const gpu = (index, processes) => ({ index, uuid: 'GPU-' + index, name: 'Example GPU', util_pct: 30,
    vram_used_mib: 4096, vram_total_mib: 16384, temperature_c: 50, power_w: 80, processes });
  const state = box.MaiLive;
  state.samples = [{ t: new Date().toISOString(), cpu_pct: 25, cpu_per_core: [10, 20, 30, 40],
    ram_pct: 50, ram_used_gib: 32, ram_total_gib: 64, ram_processes: [], cpu_processes: c.cpu_processes, nics: [], disks: [],
    gpus: [gpu(0, c.processes), gpu(1, [])] }];
  if (c.peak_samples) state.samples = c.peak_samples.map(s => Object.assign({}, state.samples[0],
    {t: new Date(Date.now() - s.age_s * 1000).toISOString(), gpus: s.gpus}));
  state.slow = { paths: [], disks: [], usage: { available: false } };
  state.judgments = [{ kind: 'gpu_hot', subject: 'GPU-0', level: 'warn', text: 'GPU temperature needs attention' }];
  state.diagnostics = c.diagnostics;
  state.incidents = c.incidents || [];
  state.draw();
  if (c.open_warning) {
    function find(n) { if ((n.className || '').includes('warning-evidence')) return n; for (const x of n.children) { const v = find(x); if (v) return v; } }
    const w = find(live); w.open = true; if (w.listeners.toggle) w.listeners.toggle();
    state.draw();
  }
  const nodes = [];
  function visit(n, hidden) {
    const closed = hidden || (n.tag === 'details' && !n.open);
    nodes.push({ cls: n.className, tag: n.tag, text: n.textContent, closed, open: n.open });
    n.children.forEach(ch => visit(ch, closed));
  }
  visit(live, false);
  return nodes;
}
let input = '';
process.stdin.on('data', x => input += x).on('end', () => console.log(JSON.stringify(run(JSON.parse(input)))));
