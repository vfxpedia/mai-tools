import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {planInstall,applyInstall} from '../src/install.mjs';
import {readProviderUsage} from '../src/provider.mjs';

const executable=process.env.MAI_CODEX_TEST_EXE;
test('real native CLI recognizes the installed local plugin without a model call',{skip:!executable},async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-native-plugin-')),home=path.join(root,'codex');fs.mkdirSync(home);
 applyInstall(planInstall({codexHome:home,source:path.resolve(import.meta.dirname,'..'),account:'codex:test',mode:'native'}),path.join(root,'backup'));
 const result=spawnSync(executable,['plugin','list','--json'],{encoding:'utf8',timeout:25000,env:{...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,ORCA_TERMINAL_HANDLE:'',CODEX_THREAD_ID:''},windowsHide:true});
 assert.equal(result.status,0,result.stderr);const data=JSON.parse(result.stdout);
 const own=data.installed?.find(x=>x.name==='mai-codex-gauge');
 assert.ok(own,JSON.stringify(data));assert.equal(own.installed,true);assert.equal(own.enabled,true);
 const version=JSON.parse(fs.readFileSync(path.join(home,'mai-codex-gauge','package.json'),'utf8')).version;
 assert.ok(fs.existsSync(path.join(home,'plugins','cache','mai-codex-local','mai-codex-gauge',version,'.codex-plugin','plugin.json')));
 const native=await readProviderUsage({executable,args:['app-server','--stdio'],sessionId:'self',includeHooks:true,timeoutMs:5000,environment:{...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,ORCA_TERMINAL_HANDLE:'',CODEX_THREAD_ID:''}});
 assert.equal(native.hooksStatus,'received');assert.equal(native.nativeHooks.length,8,JSON.stringify(native));
 assert.ok(native.nativeHooks.every(x=>x.pluginId==='mai-codex-gauge@mai-codex-local'&&x.trustStatus==='untrusted'));
});
