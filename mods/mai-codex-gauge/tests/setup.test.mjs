import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const source=path.resolve(import.meta.dirname,'..');
const run=(args,env={})=>spawnSync(process.execPath,[path.join(source,'src/setup.mjs'),...args],{encoding:'utf8',env:{...process.env,...env}});
function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-setup-')),home=path.join(root,'codex');fs.mkdirSync(home);fs.writeFileSync(path.join(home,'hooks.json'),JSON.stringify({hooks:{SessionStart:[{hooks:[{type:'command',command:'original-orca'}]}]}}));return {root,home};}

test('one-command plan is read-only, install is idempotent, rollback restores original hooks',()=>{
 const f=fixture(),before=fs.readFileSync(path.join(f.home,'hooks.json'));
 const options=['--home',f.home,'--account','codex:test','--mode','hooks'];
 const dry=run(['plan',...options]);assert.equal(dry.status,0,dry.stderr);assert.equal(fs.existsSync(path.join(f.home,'mai-codex-gauge.json')),false);
 const install=run(['install',...options]);assert.equal(install.status,0,install.stderr);const receipt=JSON.parse(install.stdout);assert.ok(receipt.manifest);assert.equal(receipt.trust,'review in /hooks');
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(f.home,'hooks.json'))).hooks.SessionStart[0],JSON.parse(before).hooks.SessionStart[0]);
 assert.ok(fs.existsSync(path.join(f.home,'skills','mai-codex-continuity','SKILL.md')));
 const twice=run(['install',...options]);assert.equal(twice.status,0,twice.stderr);assert.equal(JSON.parse(twice.stdout).changedFiles,0);
 const undo=run(['rollback','--manifest',receipt.manifest]);assert.equal(undo.status,0,undo.stderr);assert.equal(JSON.parse(undo.stdout).restored,true);assert.deepEqual(fs.readFileSync(path.join(f.home,'hooks.json')),before);
});
test('Orca compatibility install cannot overwrite a pre-existing foreign skill',()=>{
 const f=fixture(),directory=path.join(f.home,'skills','mai-codex-continuity');fs.mkdirSync(directory,{recursive:true});const file=path.join(directory,'SKILL.md');fs.writeFileSync(file,'foreign skill');
 const result=run(['install','--home',f.home,'--account','codex:test','--mode','hooks']);assert.notEqual(result.status,0);assert.equal(fs.readFileSync(file,'utf8'),'foreign skill');assert.equal(fs.existsSync(path.join(f.home,'mai-codex-gauge.json')),false);
});
test('auto mode respects own CODEX_HOME and a shared Orca plugin junction',()=>{
 const f=fixture(),shared=path.join(f.root,'shared');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'plugins'),'junction');
 const r=run(['install','--account','codex:test'],{CODEX_HOME:f.home});assert.equal(r.status,0,r.stderr);assert.equal(JSON.parse(r.stdout).mode,'hooks');assert.deepEqual(fs.readdirSync(shared),[]);
});
test('Orca shared skills junction stays untouched while the package reference remains available',()=>{
 const f=fixture(),shared=path.join(f.root,'shared-skills');fs.mkdirSync(shared);fs.symlinkSync(shared,path.join(f.home,'skills'),'junction');
 const result=run(['install','--home',f.home,'--account','codex:test','--mode','hooks']);assert.equal(result.status,0,result.stderr);
 assert.deepEqual(fs.readdirSync(shared),[]);assert.ok(fs.existsSync(path.join(f.home,'mai-codex-gauge','skills','mai-codex-continuity','SKILL.md')));
});
test('install refuses absent account and unknown flags without mutation',()=>{
 const f=fixture();for(const args of [['install','--home',f.home],['install','--home',f.home,'--account','codex:test','--typo','x']])assert.notEqual(run(args).status,0);
 assert.equal(fs.existsSync(path.join(f.home,'mai-codex-gauge')),false);
});
test('doctor cannot promote an installed handler or fixture cost into native activation',()=>{
 const f=fixture();assert.equal(run(['install','--home',f.home,'--account','codex:test','--mode','hooks']).status,0);
 const r=run(['doctor','--home',f.home,'--base',path.join(f.root,'mai'),'--session','self']);assert.equal(r.status,0,r.stderr);const d=JSON.parse(r.stdout);
 assert.equal(d.installed,true);assert.equal(d.handlerEventsObserved,0);assert.equal(d.activation,'not observed');assert.equal(d.cost.session,'not observed');assert.equal(d.inlineFiveRows,'unsupported by native statusline');
});
test('native package contains native hook manifest and a runnable installer bin',()=>{
 const f=fixture();const r=run(['install','--home',f.home,'--account','codex:test','--mode','native']);assert.equal(r.status,0,r.stderr);
 const product=path.join(f.home,'mai-codex-gauge'),manifest=JSON.parse(fs.readFileSync(path.join(product,'.codex-plugin','plugin.json')));
 assert.equal(manifest.hooks,'./hooks.json');assert.equal(manifest.name,'mai-codex-gauge');
 const pkg=JSON.parse(fs.readFileSync(path.join(product,'package.json')));const b=spawnSync(process.execPath,[path.join(product,pkg.bin['mai-codex-mods']),'--help'],{encoding:'utf8'});assert.equal(b.status,0,b.stderr);assert.match(b.stdout,/install.*doctor.*rollback/s);
});
test('the packaged metrics command shows exact values and trust cannot be silently approved',()=>{
 const f=fixture(),base=path.join(f.root,'mai');fs.mkdirSync(path.join(base,'units'),{recursive:true});
 fs.writeFileSync(path.join(base,'units','self.json'),JSON.stringify({sessionId:'self',codex:{state:{turnId:'t',historyComplete:true,turns:{t:{input:123,read:100,out:7,total:130,requests:1}}}}}));
 const metrics=run(['metrics','--base',base,'--session','self']);assert.equal(metrics.status,0,metrics.stderr);assert.deepEqual(JSON.parse(metrics.stdout).session.tokens,{input:123,cache:100,output:7,total:130});
 const before=fs.readFileSync(path.join(f.home,'hooks.json'));const trust=run(['trust','--home',f.home,'--approve','false']);assert.notEqual(trust.status,0);assert.match(trust.stderr,/approve expects true/);assert.deepEqual(fs.readFileSync(path.join(f.home,'hooks.json')),before);
});
