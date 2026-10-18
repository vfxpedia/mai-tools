import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {planInstall,applyInstall} from '../src/install.mjs';import {trustGaugeHooks} from '../src/native-trust.mjs';import {nativeRpc} from '../src/native-rpc.mjs';
import {spawn} from 'node:child_process';
import {spawnSync} from 'node:child_process';
import {hookCommand} from '../src/hook-command.mjs';
const executable=process.env.MAI_CODEX_TEST_EXE;
test('portable setup trusts exact handlers using an explicit executable without an Orca daemon',{skip:!executable},()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-portable-trust-')),home=path.join(root,'codex');fs.mkdirSync(home);
 applyInstall(planInstall({codexHome:home,source:path.resolve(import.meta.dirname,'..'),account:'codex:test',mode:'native'}),path.join(root,'backup'));
 const run=(args)=>spawnSync(process.execPath,[path.resolve(import.meta.dirname,'../src/setup.mjs'),...args],{encoding:'utf8',timeout:15000,windowsHide:true,env:{...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,CODEX_THREAD_ID:''}});
 const refused=run(['trust','--home',home,'--exe',executable]);assert.equal(refused.status,0,refused.stderr);assert.equal(JSON.parse(refused.stdout).approved,false);
 const approved=run(['trust','--home',home,'--exe',executable,'--approve','true']);assert.equal(approved.status,0,approved.stderr);assert.equal(JSON.parse(approved.stdout).verified,true);
 const d=run(['doctor','--home',home,'--session','self','--native','true','--exe',executable]);assert.equal(d.status,0,d.stderr);const out=JSON.parse(d.stdout);
 assert.equal(out.native.nativeHooks.length,8);assert.ok(out.native.nativeHooks.every(h=>h.trustStatus==='trusted'));assert.equal(out.handlerEventsObserved,0);
 const outside=run(['doctor','--home',home,'--native','true','--exe',executable]);assert.equal(outside.status,0,outside.stderr);assert.equal(JSON.parse(outside.stdout).handlerEventsObserved,0);
});
test('native plugin review trusts exactly its eight hashes in an isolated real Codex home',{skip:!executable},async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-native-activation-')),home=path.join(root,'codex');fs.mkdirSync(home);
 applyInstall(planInstall({codexHome:home,source:path.resolve(import.meta.dirname,'..'),account:'codex:test',mode:'native'}),path.join(root,'backup'));
 const options={executable,args:['app-server','--stdio'],timeoutMs:5000,environment:{...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,CODEX_THREAD_ID:'',ORCA_TERMINAL_HANDLE:''}};
 const rpc=(method,params)=>nativeRpc(options,method,params);
 const before=await rpc('hooks/list',{cwds:[root]});assert.equal(before.data.flatMap(d=>d.hooks).length,8);assert.ok(before.data.flatMap(d=>d.hooks).every(h=>h.trustStatus==='untrusted'));
 const result=await trustGaugeHooks({home,cwd:root,approved:true,rpc});assert.equal(result.verified,true);assert.equal(result.changed,8);
 const after=await rpc('hooks/list',{cwds:[root]});assert.ok(after.data.flatMap(d=>d.hooks).every(h=>h.trustStatus==='trusted'));
 assert.equal((await trustGaugeHooks({home,cwd:root,approved:true,rpc})).changed,0);
});
async function startWithoutModel(options,cwd){
 return new Promise((resolve,reject)=>{
  const child=spawn(options.executable,['app-server','--stdio'],{env:options.environment,stdio:['pipe','pipe','pipe'],windowsHide:true});let buffer='',thread=null,turn=null,done=false;const notes=[];
  const finish=(error)=>{if(done)return;done=true;clearTimeout(timer);child.stdin.end();child.stdout.destroy();child.stderr.destroy();child.unref();error?reject(Error(error)):resolve({thread,turn,notes});};
  const timer=setTimeout(()=>finish('native SessionStart was not observed: '+JSON.stringify(notes)),8000);
  const send=q=>child.stdin.write(JSON.stringify(q)+'\n');child.stderr.resume();child.on('error',()=>finish('native launch unavailable'));child.stdin.on('error',()=>finish('native write unavailable'));
  child.stdout.on('data',part=>{buffer+=part;let n;while(!done&&(n=buffer.indexOf('\n'))>=0){let m;try{m=JSON.parse(buffer.slice(0,n));}catch{return finish('invalid native fixture response');}buffer=buffer.slice(n+1);
   if(m.id===1){if(m.error)return finish('native initialize refused');send({method:'initialized',params:{}});send({id:2,method:'thread/start',params:{cwd,ephemeral:false}});}
   else if(m.id===2){if(m.error)return finish('native thread creation refused');thread=m.result.thread;send({id:3,method:'turn/start',params:{threadId:thread.id,input:[{type:'text',text:'Offline lifecycle test. The approved test hook cancels this before any model request.',text_elements:[]}]}});}
   else if(m.id===3&&m.error)return finish('offline turn was refused before hooks');
   else if(m.method==='hook/completed')notes.push(m.params);
   else if(m.method==='turn/completed')turn=m.params.turn;
   if(thread&&turn&&notes.some(x=>x.threadId===thread.id&&x.run?.eventName==='sessionStart'))finish();
  }});
  send({id:1,method:'initialize',params:{clientInfo:{name:'mai_offline_hook_test',version:'1'},capabilities:{experimentalApi:true}}});
 });
}
test('trusted SessionStart and UserPromptSubmit fire through the real engine without a model call',{skip:!executable},async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-native-fire-')),home=path.join(root,'codex');fs.mkdirSync(home);
 applyInstall(planInstall({codexHome:home,source:path.resolve(import.meta.dirname,'..'),account:'codex:test',mode:'native'}),path.join(root,'backup'));
 // This isolated guard cancels UserPromptSubmit before a model request. No login
 // or credentials are copied, and no billable model invocation is permitted.
 const stopFile=path.join(root,'offline-stop.cjs');fs.writeFileSync(stopFile,"process.stdin.resume();process.stdin.on('end',()=>process.stdout.write(JSON.stringify({continue:false,stopReason:'Offline hook test: no model request'})));\n");
 const version=JSON.parse(fs.readFileSync(path.join(home,'mai-codex-gauge','package.json'),'utf8')).version;
 const hooksFile=path.join(home,'plugins','cache','mai-codex-local','mai-codex-gauge',version,'hooks.json'),hooks=JSON.parse(fs.readFileSync(hooksFile,'utf8'));
 hooks.hooks.UserPromptSubmit[0].hooks.push({type:'command',command:hookCommand(stopFile),timeout:5});fs.writeFileSync(hooksFile,JSON.stringify(hooks));
 const options={executable,args:['app-server','--stdio'],timeoutMs:5000,environment:{...process.env,CODEX_HOME:home,USERPROFILE:root,HOME:root,CODEX_THREAD_ID:'',ORCA_TERMINAL_HANDLE:''}};
 await trustGaugeHooks({home,cwd:root,approved:true,rpc:(method,params)=>nativeRpc(options,method,params)});
 const inventory=await nativeRpc(options,'hooks/list',{cwds:[root]}),guard=inventory.data.flatMap(d=>d.hooks).find(h=>h.command.includes('offline-stop.cjs'));
 assert.ok(guard);await nativeRpc(options,'config/batchWrite',{edits:[{keyPath:'hooks.state',value:{[guard.key]:{trusted_hash:guard.currentHash}},mergeStrategy:'upsert'}],reloadUserConfig:true});
 const result=await startWithoutModel(options,root),base=path.join(root,'.mai');
 const ownFile=path.join(base,'units',result.thread.id+'.json');assert.ok(fs.existsSync(ownFile),JSON.stringify(result.notes));
 const own=JSON.parse(fs.readFileSync(ownFile,'utf8'));
 assert.equal(own.codex.events[0].event,'SessionStart');assert.equal(own.sessionId,result.thread.id);assert.equal(own.codex.account,'codex:test');
 assert.ok(own.codex.events.some(e=>e.event==='UserPromptSubmit'&&e.turnId===result.turn.id));assert.equal(result.turn.status,'completed');
 assert.match(JSON.stringify(result.notes),/Offline hook test: no model request/);assert.ok(!result.turn.items.some(x=>x.type==='agentMessage'));
 assert.deepEqual(fs.readdirSync(path.join(base,'sessions')),[result.thread.id+'.json']);assert.equal(own.codex.state.requests,0);
});
