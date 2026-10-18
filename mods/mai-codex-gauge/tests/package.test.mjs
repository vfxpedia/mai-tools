import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const npmCli=process.env.MAI_NPM_TEST_CLI;
test('actual tarball installs through offline npm exec, repeats without changes and rolls back',{skip:!npmCli},()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-package-')),home=path.join(root,'codex');fs.mkdirSync(home);
 const env={...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,ORCA_TERMINAL_HANDLE:'',CODEX_THREAD_ID:'',npm_config_cache:path.join(root,'npm-cache')};
 const run=(args)=>spawnSync(process.execPath,[npmCli,...args],{cwd:path.resolve(import.meta.dirname,'..'),encoding:'utf8',timeout:30000,env,windowsHide:true});
 const packed=run(['pack','--ignore-scripts','--json','--pack-destination',root]);assert.equal(packed.status,0,packed.stderr);
 const data=JSON.parse(packed.stdout)[0],tarball=path.join(root,data.filename);
 assert.ok(data.files.some(x=>x.path==='.codex-plugin/plugin.json'));assert.ok(data.files.some(x=>x.path==='bin/mai-codex-mods.mjs'));
 assert.ok(!data.files.some(x=>x.path.startsWith('tests/')||x.path.includes('auth')));
 const command=['exec','--offline','--yes','--ignore-scripts','--package',tarball,'--','mai-codex-mods'];
 const installed=run([...command,'install','--account','codex:test']);assert.equal(installed.status,0,installed.stderr);
 const receipt=JSON.parse(installed.stdout);assert.equal(receipt.mode,'native');assert.ok(receipt.changedFiles>0);assert.ok(receipt.manifest);
 const twice=run([...command,'install','--account','codex:test']);assert.equal(twice.status,0,twice.stderr);assert.equal(JSON.parse(twice.stdout).changedFiles,0);
 const doctor=run([...command,'doctor','--session','self','--base',path.join(root,'mai')]);assert.equal(doctor.status,0,doctor.stderr);assert.equal(JSON.parse(doctor.stdout).activation,'not observed');
 const undo=run([...command,'rollback','--manifest',receipt.manifest]);assert.equal(undo.status,0,undo.stderr);assert.equal(JSON.parse(undo.stdout).restored,true);
 assert.equal(fs.existsSync(path.join(home,'config.toml')),false);assert.equal(fs.existsSync(path.join(home,'mai-codex-gauge.json')),false);
});
