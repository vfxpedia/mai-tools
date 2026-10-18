import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {planInstall,applyInstall,rollback} from '../src/install.mjs';
import {isGaugeCommand} from '../src/hook-command.mjs';
const source=path.resolve(import.meta.dirname,'..');
function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-install-')),home=path.join(root,'codex');fs.mkdirSync(home);const config='model = "gpt-6.1-sol"\nnotify = ["existing-notify"]\n\n[features]\nplugins = true\n';fs.writeFileSync(path.join(home,'config.toml'),config);fs.writeFileSync(path.join(home,'hooks.json'),JSON.stringify({hooks:Object.fromEntries(Array.from({length:9},(_,i)=>['E'+i,[{hooks:[{type:'command',command:'existing-orca'}]}]]))}));return {root,home,config};}
test('dry run, application, idempotence, original hooks preserved and rollback bytes exact',()=>{
 const f=fixture(),before=fs.readFileSync(path.join(f.home,'hooks.json'));const plan=planInstall({codexHome:f.home,source,account:'codex:test'});assert.equal(fs.existsSync(path.join(f.home,'mai-codex-gauge.json')),false);
 const m=applyInstall(plan,path.join(f.root,'backup'));assert.deepEqual(fs.readFileSync(path.join(f.home,'hooks.json')),before);assert.match(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),/existing-notify/);
 const twice=planInstall({codexHome:f.home,source,account:'codex:test'});assert.equal(twice.changes.length,0);
 assert.equal(rollback(m).restored,true);assert.equal(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),f.config);assert.deepEqual(fs.readFileSync(path.join(f.home,'hooks.json')),before);
});
test('before-apply external edit refused; after-apply edit survives rollback',()=>{
 const f=fixture(),p=planInstall({codexHome:f.home,source,account:'codex:test'});fs.appendFileSync(path.join(f.home,'config.toml'),'# foreign edit\n');assert.throws(()=>applyInstall(p,path.join(f.root,'backup')));
 const m=applyInstall(planInstall({codexHome:f.home,source,account:'codex:test'}),path.join(f.root,'backup2'));fs.appendFileSync(path.join(f.home,'config.toml'),'# newer foreign edit\n');assert.equal(rollback(m).restored,false);assert.match(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),/newer foreign edit/);
});
test('shared histories not part of rollback and existing footer not replaced',()=>{
 const f=fixture();fs.appendFileSync(path.join(f.home,'config.toml'),'\n[tui]\nstatus_line = ["model-name"]\n');const p=planInstall({codexHome:f.home,source,account:'codex:test'});assert.ok(p.changes.every(x=>x.path.startsWith(f.home)));const m=applyInstall(p,path.join(f.root,'backup'));assert.match(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),/status_line = \["model-name"\]/);assert.equal(rollback(m).restored,true);
});
test('forged manifest cannot touch auth, sessions, shared history or outside home',()=>{
 const f=fixture(),content='fixture, not credentials',afterHash=crypto.createHash('sha256').update(content).digest('hex');for(const relative of ['auth.json','sessions/one.jsonl','../escape']){const target=path.resolve(f.home,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,content);assert.throws(()=>rollback({version:1,home:f.home,backup:path.join(f.root,'b'),files:[{path:target,beforeHash:null,afterHash,backup:null}]}));assert.equal(fs.readFileSync(target,'utf8'),content);}
});
test('companion mode does not cross an Orca shared plugin junction',()=>{
 const f=fixture(),shared=path.join(f.root,'shared-plugins');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'plugins'),'junction');
 assert.throws(()=>planInstall({codexHome:f.home,source,account:'codex:test'}));
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'companion'});assert.ok(p.changes.every(x=>!path.relative(f.home,x.path).startsWith('plugins')));
 const m=applyInstall(p,path.join(f.root,'backup'));assert.equal(fs.readdirSync(shared).length,0);assert.equal(rollback(m).restored,true);assert.equal(fs.readdirSync(shared).length,0);
});
test('product-only upgrade keeps config hooks trust and shared plugin cache byte-identical',()=>{
 const f=fixture(),shared=path.join(f.root,'shared-plugins');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'plugins'),'junction');
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'product'});
 assert.ok(p.changes.some(x=>x.path.endsWith('provider.mjs')));assert.ok(p.changes.every(x=>!['config.toml','hooks.json'].includes(path.relative(f.home,x.path))&&!path.relative(f.home,x.path).startsWith('plugins')));
 const m=applyInstall(p,path.join(f.root,'backup'));assert.equal(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),f.config);assert.equal(fs.readdirSync(shared).length,0);assert.equal(rollback(m).restored,true);
});

test('native user hooks attach without crossing shared cache, preserving every Orca handler and reversible bytes',()=>{
 const f=fixture(),shared=path.join(f.root,'shared-plugins');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'plugins'),'junction');
 const file=path.join(f.home,'hooks.json'),before=fs.readFileSync(file),old=JSON.parse(before);
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'});assert.equal(p.hooksTrust,'requires native review');
 assert.ok(p.changes.every(x=>!path.relative(f.home,x.path).startsWith('plugins')));
 const m=applyInstall(p,path.join(f.root,'backup')),installed=JSON.parse(fs.readFileSync(file));
 for(const [event,groups] of Object.entries(old.hooks))assert.deepEqual(installed.hooks[event].slice(0,groups.length),groups);
 assert.equal(isGaugeCommand(installed.hooks.UserPromptSubmit.at(-1).hooks[0].command),true);
 assert.equal(planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'}).changes.length,0);
 assert.equal(rollback(m).restored,true);assert.deepEqual(fs.readFileSync(file),before);assert.equal(fs.readdirSync(shared).length,0);
});
test('root-hook mode masks the inherited native gauge in this home only, without modifying shared cache',()=>{
 const f=fixture(),shared=path.join(f.root,'shared-plugins');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'plugins'),'junction');
 const inherited=path.join(shared,'inherited.json');fs.writeFileSync(inherited,'{"keep":true}');const original=fs.readFileSync(inherited);
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'}),m=applyInstall(p,path.join(f.root,'mask-backup'));
 assert.match(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),/\[plugins\."mai-codex-gauge@mai-codex-local"\]\s+enabled = false/);
 assert.deepEqual(fs.readFileSync(inherited),original);
 assert.equal(planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'}).changes.length,0);
 assert.equal(rollback(m).restored,true);assert.equal(fs.readFileSync(path.join(f.home,'config.toml'),'utf8'),f.config);assert.deepEqual(fs.readFileSync(inherited),original);
});
test('root hooks refuse an existing gauge plugin even when the auxiliary mode field is absent',()=>{
 const f=fixture();fs.appendFileSync(path.join(f.home,'config.toml'),'\n[plugins."mai-codex-gauge@mai-codex-local"]\nenabled = true\n');
 fs.writeFileSync(path.join(f.home,'mai-codex-gauge.json'),JSON.stringify({version:1,account:'codex:test'}));
 const before=fs.readFileSync(path.join(f.home,'hooks.json'));
 assert.throws(()=>planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'}),/plugin.*configured/);
 assert.deepEqual(fs.readFileSync(path.join(f.home,'hooks.json')),before);
});
test('explicit inherited-plugin mask changes only the exact owned enable block and can be rolled back',()=>{
 const f=fixture();fs.appendFileSync(path.join(f.home,'config.toml'),'\n[plugins."mai-codex-gauge@mai-codex-local"]\nenabled = true\n\n[plugins."other@keep"]\nenabled = true\n');
 const original=fs.readFileSync(path.join(f.home,'config.toml'));
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks',maskNative:true}),m=applyInstall(p,path.join(f.root,'explicit-mask-backup'));
 const text=fs.readFileSync(path.join(f.home,'config.toml'),'utf8');
 assert.match(text,/mai-codex-gauge@mai-codex-local"\]\s+enabled = false/);
 assert.match(text,/other@keep"\]\s+enabled = true/);
 assert.equal(rollback(m).restored,true);assert.deepEqual(fs.readFileSync(path.join(f.home,'config.toml')),original);
});

test('upgrade retires the obsolete own JSON asset with an exact backup and reversible deletion',()=>{
 const f=fixture(),obsolete=path.join(f.home,'mai-codex-gauge','prices.json'),original=Buffer.from('{"legacy":true}\n');
 fs.mkdirSync(path.dirname(obsolete),{recursive:true});fs.writeFileSync(obsolete,original);
 const p=planInstall({codexHome:f.home,source,account:'codex:test',mode:'product'});
 assert.deepEqual(fs.readFileSync(obsolete),original,'plan must not delete');
 const m=applyInstall(p,path.join(f.root,'retirement-backup'));
 assert.equal(fs.existsSync(obsolete),false,'installation must remove the retired asset');
 assert.equal(planInstall({codexHome:f.home,source,account:'codex:test',mode:'product'}).changes.length,0);
 assert.equal(rollback(m).restored,true);assert.deepEqual(fs.readFileSync(obsolete),original);
});
