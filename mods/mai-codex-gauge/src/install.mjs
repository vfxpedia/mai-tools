import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {safePath} from './store.mjs';
import {hookCommand,isGaugeCommand,resolveHookRuntime} from './hook-command.mjs';

const hash = bytes => bytes === null ? null : crypto.createHash('sha256').update(bytes).digest('hex');
const read = file => {try {return fs.readFileSync(file);} catch (e) {if (e.code === 'ENOENT') return null; throw e;}};
const retiredOwnFiles = ['prices.json']; // Exact obsolete asset only; never folders or shared caches.
const files = ['package.json', 'plugin.json', 'hooks.json', 'types.d.ts',
  'README.md', '.agents/plugins/marketplace.json', 'src/usage.mjs', 'src/store.mjs',
  'src/band.mjs', 'src/cli.mjs', 'src/hook.mjs', 'src/hook-diagnostics.mjs', 'src/install.mjs', 'src/provider.mjs', 'src/context-policy.mjs',
  '.codex-plugin/plugin.json', 'src/setup.mjs', 'src/checkpoint.mjs', 'src/telemetry.mjs', 'src/native-rpc.mjs', 'src/native-trust.mjs', 'src/hook-command.mjs', 'bin/mai-codex-mods.mjs',
  'skills/mai-codex-continuity/SKILL.md'];
const version=JSON.parse(fs.readFileSync(new URL('../package.json',import.meta.url),'utf8')).version;
const selector = 'mai-codex-gauge@mai-codex-local';
const footer = ['model-with-reasoning', 'context-remaining', 'five-hour-limit', 'weekly-limit'];

function allowedTarget(home, file) {
  const relative = path.relative(home, file).replaceAll('\\', '/');
  const prefix = ['mai-codex-gauge/', ...[...new Set([version,'0.2.1','0.2.0','0.1.0'])].map(v=>`plugins/cache/mai-codex-local/mai-codex-gauge/${v}/`)];
  if (!['config.toml', 'hooks.json', 'mai-codex-gauge.json','skills/mai-codex-continuity/SKILL.md'].includes(relative) && !prefix.some(p => relative.startsWith(p) && [...files,...retiredOwnFiles].includes(relative.slice(p.length)))) throw Error('target not gauge-owned');
  return ownPath(home, relative);
}

function ownPath(home, relative) {
  if (relative.split(/[\\/]/).some(x => !x || x === '..') || path.isAbsolute(relative)) throw Error('invalid install target');
  const target = path.resolve(home, relative);
  safePath(home, ...relative.split(/[\\/]/));   // every folder from the Codex home down to the target, so a link inside the home is refused
  return target;
}

function configure(original, product, native) {
  let text = original;
  if (/\[features\][\s\S]*?\bplugins\s*=\s*false/.test(text.split(/\n\[(?!features\])/)[0])) throw Error('plugins disabled by user');
  const marketplace = `[marketplaces.mai-codex-local]\nsource_type = "local"\nsource = ${JSON.stringify(product)}\n`;
  const plugin = `[plugins."${selector}"]\nenabled = true\n`;
  for (const [header, block] of native ? [['[marketplaces.mai-codex-local]', marketplace], [`[plugins."${selector}"]`, plugin]] : []) {
    const i = text.indexOf(header);
    if (i < 0) text += `\n${block}`;
    else {
      const end = text.indexOf('\n[', i + header.length);
      if (text.slice(i, end < 0 ? text.length : end).trim() !== block.trim()) throw Error('existing plugin configuration differs; review required');
    }
  }
  if (!/^\s*status_line\s*=/m.test(text) && !/^\s*tui\.status_line\s*=/m.test(text)) {
    const line = `status_line = ${JSON.stringify(footer)}\n`;
    if (/^\[tui\]\r?$/m.test(text)) text = text.replace(/^\[tui\]\r?\n/m, `[tui]\n${line}`);
    else text += `\n[tui]\n${line}`;
  }
  return text;
}

export function planInstall({codexHome, source, account, mode = 'native', maskNative = false}) {
  if (!/^codex:[\w-]+$/.test(account ?? '')) throw Error('explicit account alias required');
  const home = path.resolve(codexHome), root = path.resolve(source);
  if (!['native', 'companion', 'product', 'hooks'].includes(mode)) throw Error('invalid install mode');
  safePath(path.dirname(home), path.basename(home));
  const changes = [];
  function add(relative, content) {
    const file = ownPath(home, relative), before = read(file), after = Buffer.from(content);
    if (hash(before) !== hash(after)) changes.push({path: file, beforeHash: hash(before), afterHash: hash(after), content: after.toString('base64')});
  }
  const product = path.join(home, 'mai-codex-gauge');
  for(const retired of retiredOwnFiles){
    const targets=[path.join('mai-codex-gauge',retired),...(mode==='native'?[path.join('plugins','cache','mai-codex-local','mai-codex-gauge',version,retired)]:[])];
    for(const relative of targets){const file=ownPath(home,relative),before=read(file);if(before!==null)changes.push({path:file,beforeHash:hash(before),afterHash:null,content:null});}
  }
  for (const relative of files) {
    const input = ownPath(root, relative), bytes = read(input);
    if (!bytes) throw Error(`missing package file: ${relative}`);
    const generated=(target)=>{
      if(relative!=='hooks.json'||!['native','hooks'].includes(mode))return bytes;
      const desired=JSON.parse(bytes);for(const groups of Object.values(desired.hooks))for(const group of groups)for(const handler of group.hooks)handler.command=hookCommand(path.join(target,'src','hook.mjs'));
      return JSON.stringify(desired,null,2)+'\n';
    };
    add(path.join('mai-codex-gauge', relative), generated(product));
    if (mode === 'native') {const cache=path.join('plugins','cache','mai-codex-local','mai-codex-gauge',version);add(path.join(cache,relative),generated(path.join(home,cache)));}
  }
  if(mode!=='product'&&mode!=='hooks'){const cfg = read(ownPath(home, 'config.toml'));add('config.toml', configure(cfg?.toString('utf8') ?? '', product, mode === 'native'));}
  if(mode==='hooks'){
    const skillsRoot=path.join(home,'skills');
    // Orca may share both plugins and skills with the general home. The hook's
    // continuity reference remains available inside the private product copy.
    if(!fs.existsSync(skillsRoot)||!fs.lstatSync(skillsRoot).isSymbolicLink()){
      const skill='skills/mai-codex-continuity/SKILL.md',skillBytes=read(ownPath(root,skill)),existingSkill=read(ownPath(home,skill));
      if(existingSkill&&hash(existingSkill)!==hash(skillBytes))throw Error('existing continuity skill differs; scoped review required');
      add(skill,skillBytes);
    }
    const nativeConfig=read(ownPath(home,'config.toml'))?.toString('utf8')??'';
    const mask=`[plugins."${selector}"]\nenabled = false\n`,maskStart=nativeConfig.indexOf(`[plugins."${selector}"]`);
    if(maskStart>=0){const header=`[plugins."${selector}"]`,end=nativeConfig.indexOf('\n[',maskStart+header.length),stop=end<0?nativeConfig.length:end,existing=nativeConfig.slice(maskStart,stop).trim();
      if(existing!==mask.trim()){
        if(maskNative===true&&existing===`${header}\nenabled = true`)add('config.toml',nativeConfig.slice(0,maskStart)+mask+nativeConfig.slice(stop));
        else throw Error('gauge plugin already configured; do not duplicate handlers');
      }
    }
    else if(/^\s*(?:\[plugins[^\r\n]*|plugins\.[^\r\n]*)mai-codex-gauge/m.test(nativeConfig))throw Error('gauge plugin already configured; do not duplicate handlers');
    // A shared plugin junction can expose the default home's enabled cache
    // even without a local plugin table. Mask only our own native plugin in
    // this home so one event has one gauge handler. Do not change the cache.
    if(maskStart<0)add('config.toml',nativeConfig+'\n'+mask);
    const cfg=read(ownPath(home,'mai-codex-gauge.json'));if(cfg&&JSON.parse(cfg).mode==='native')throw Error('native plugin already configured; do not duplicate handlers');if(cfg&&JSON.parse(cfg).account!==account)throw Error('account differs');
    const original=read(ownPath(home,'hooks.json')),old=original?JSON.parse(original):{hooks:{}};
    if(!old||typeof old!=='object'||Array.isArray(old)||!old.hooks||typeof old.hooks!=='object'||Array.isArray(old.hooks))throw Error('invalid existing hooks');
    const desired=JSON.parse(read(ownPath(root,'hooks.json'))),next=structuredClone(old);
    for(const [event,groups] of Object.entries(desired.hooks)){
      if(next.hooks[event]&&!Array.isArray(next.hooks[event]))throw Error('invalid event hooks');
      next.hooks[event]??=[];
      for(const group of groups){const g=structuredClone(group),script=path.join(product,'src','hook.mjs');for(const handler of g.hooks)handler.command=hookCommand(script);
        const own=next.hooks[event].filter(x=>x.hooks?.some(h=>isGaugeCommand(h.command)));
        // Encoded Windows commands contain no plaintext product name. Identify
        // our exact previous generated group as well as the legacy command.
        const previousRuntime=cfg?JSON.parse(cfg).hookRuntime:null;
        const previous=structuredClone(g);for(const handler of previous.hooks)handler.command=previousRuntime?hookCommand(script,previousRuntime):'node '+JSON.stringify(script.replaceAll('\\','/'));
        const generatedOwn=next.hooks[event].filter(x=>JSON.stringify(x)===JSON.stringify(g)||JSON.stringify(x)===JSON.stringify(previous));
        const found=[...new Set([...own,...generatedOwn])];
        if(found.length){if(found.length!==1||![JSON.stringify(g),JSON.stringify(previous)].includes(JSON.stringify(found[0])))throw Error('existing gauge handler differs; scoped review required');next.hooks[event][next.hooks[event].indexOf(found[0])]=g;}
        else next.hooks[event].push(g);
      }
    }
    if(JSON.stringify(next)!==JSON.stringify(old))add('hooks.json',JSON.stringify(next,null,2)+'\n');
  }
  if(mode==='product'){const old=read(ownPath(home,'mai-codex-gauge.json'));if(old){const existing=JSON.parse(old.toString('utf8'));if(existing.account!==account)throw Error('account differs');return {version:1,home,selector,mode,hooksTrust:'unchanged',changes};}}
  const existing=read(ownPath(home,'mai-codex-gauge.json'));
  if(existing&&JSON.parse(existing).account!==account)throw Error('account differs');
  add('mai-codex-gauge.json', JSON.stringify({...existing?JSON.parse(existing):{},version: 1, account, source: product, mode,...(['native','hooks'].includes(mode)?{hookRuntime:resolveHookRuntime()}:{})}, null, 2) + '\n');
  // The native CLI was measured in an isolated home: these two configuration
  // tables and this versioned cache are its complete local-install writes.
  // Installing does not approve hooks or reload an already-running process.
  return {version: 1, home, selector, mode, hooksTrust: ['native','hooks'].includes(mode) ? 'requires native review' : 'not installed', changes};
}

function replace(file, bytes) {
  safePath(path.dirname(file), path.basename(file));
  fs.mkdirSync(path.dirname(file), {recursive: true});
  const tmp = `${file}.${crypto.randomUUID()}.tmp`, fd = fs.openSync(tmp, 'wx', 0o600);
  try {fs.writeFileSync(fd, bytes); fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
  try {fs.renameSync(tmp, file);} finally {if (fs.existsSync(tmp)) fs.unlinkSync(tmp);}
}

export function applyInstall(plan, backupDir) {
  if (plan.version !== 1 || !path.isAbsolute(plan.home)) throw Error('invalid install plan');
  const backup = path.resolve(backupDir);
  safePath(path.dirname(backup), path.basename(backup));
  if (fs.existsSync(path.join(backup, 'manifest.json'))) throw Error('backup already used');
  for (const c of plan.changes) {
    const rel = path.relative(plan.home, c.path);
    if (allowedTarget(plan.home, c.path) !== c.path || hash(read(c.path)) !== c.beforeHash || (c.content===null?!retiredOwnFiles.includes(path.basename(c.path))||c.afterHash!==null:hash(Buffer.from(c.content,'base64'))!==c.afterHash)) throw Error('pre-install conflict');
  }
  fs.mkdirSync(backup, {recursive: true});
  const manifest = {version: 1, home: plan.home, backup, selector: plan.selector, at: Date.now(), files: []};
  for (const [i, c] of plan.changes.entries()) {
    const bytes = read(c.path), copy = bytes === null ? null : path.join(backup, `${i}.before`);
    if (copy) fs.writeFileSync(copy, bytes, {flag: 'wx', mode: 0o600});
    manifest.files.push({path: c.path, beforeHash: c.beforeHash, afterHash: c.afterHash, backup: copy});
  }
  // Persist recovery evidence before modifying configuration or the package.
  fs.writeFileSync(path.join(backup, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', {flag: 'wx', mode: 0o600});
  for (const c of plan.changes) {
    if (hash(read(c.path)) !== c.beforeHash) throw Error('install conflict; inspect manifest before recovery');
    if(c.content===null)fs.unlinkSync(c.path);else replace(c.path, Buffer.from(c.content, 'base64'));
  }
  return manifest;
}

export function rollback(manifest) {
  if (manifest.version !== 1 || !Array.isArray(manifest.files)) throw Error('invalid rollback manifest');
  const conflicts = [];
  for (const f of manifest.files) {
    const rel = path.relative(manifest.home, f.path);
    if (allowedTarget(manifest.home, f.path) !== f.path) throw Error('rollback escape');
    if (hash(read(f.path)) !== f.afterHash) conflicts.push(f.path);
    if (f.backup && (path.dirname(f.backup) !== manifest.backup || hash(read(f.backup)) !== f.beforeHash)) throw Error('damaged backup');
  }
  if (conflicts.length) return {restored: false, conflicts, reason: 'newer edits preserved; manual scoped review required'};
  for (const f of [...manifest.files].reverse()) {
    if (hash(read(f.path)) !== f.afterHash) throw Error('rollback concurrent edit');
    if (f.backup) replace(f.path, fs.readFileSync(f.backup));
    else fs.unlinkSync(f.path); // Only exact manifest-owned files, never folders/history.
  }
  return {restored: true, files: manifest.files.length};
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try {
    const [command, home, account, backup] = process.argv.slice(2);
    if (command === 'rollback') console.log(JSON.stringify(rollback(JSON.parse(fs.readFileSync(home, 'utf8')))));
    else {
      const plan = planInstall({codexHome: home, source: path.resolve(import.meta.dirname, '..'), account, mode: command.endsWith('-hooks')?'hooks':command.endsWith('-product') ? 'product' : command.endsWith('-companion') ? 'companion' : 'native'});
      if (['apply', 'apply-companion', 'apply-product','apply-hooks'].includes(command)) console.log(JSON.stringify({manifest: path.join(applyInstall(plan, backup).backup, 'manifest.json'), files: plan.changes.length}));
      else if (['plan', 'plan-companion', 'plan-product','plan-hooks'].includes(command)) console.log(JSON.stringify({home: plan.home, mode: plan.mode, hooksTrust: plan.hooksTrust, changes: plan.changes.map(x => ({path: x.path, beforeHash: x.beforeHash, afterHash: x.afterHash}))}, null, 2));
      else throw Error('commands: plan HOME ACCOUNT; apply HOME ACCOUNT BACKUP; rollback MANIFEST');
    }
  } catch {console.error('Installation refused. Check the private plan or manifest; no automatic overwrite.'); process.exitCode = 1;}
}
