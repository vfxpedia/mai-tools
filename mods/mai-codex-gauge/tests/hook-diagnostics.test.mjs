import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {handleHook} from '../src/hook.mjs';
import {doctor} from '../src/setup.mjs';

function fixture(){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-hook-diagnostic-'));
 const home=path.join(root,'codex'),base=path.join(root,'mai');
 fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 const transcript=path.join(home,'sessions','rollout-self.jsonl');
 fs.writeFileSync(transcript,JSON.stringify({type:'session_meta',payload:{id:'self'}})+'\n');
 fs.writeFileSync(path.join(home,'mai-codex-gauge.json'),JSON.stringify({account:'codex:isolated',mode:'hooks'}));
 const input={session_id:'self',hook_event_name:'UserPromptSubmit',transcript_path:transcript,cwd:root,prompt:'PRIVATE_PROMPT_NOT_TO_STORE',tool_input:{command:'PRIVATE_COMMAND_NOT_TO_STORE'}};
 const environment={base,codexHome:home,sessionId:'self',account:'codex:isolated',quiet:true,providerReader:async()=>({threadId:'self',at:Date.now(),kind:'provider-estimate',status:'unavailable',reason:'USD not provided'})};
 return {root,home,base,transcript,input,environment};
}

test('a mismatched hook session is rejected with a doctor reason, not counted as activation',async()=>{
 const f=fixture();
 assert.deepEqual(await handleHook(f.input,{...f.environment,sessionId:'old-window'}),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics?.latestFailure?.code,'session_id_mismatch');
 assert.equal(d.hookDiagnostics.latestFailure.environmentSessionId,'old-window');
 assert.equal(d.hookDiagnostics.latestFailure.event,'UserPromptSubmit');
 assert.equal(d.hookDiagnostics.latestFailure.codexHome,path.resolve(f.home));
 assert.equal(Number.isFinite(d.hookDiagnostics.latestFailure.at),true);
 assert.equal(d.handlerEventsObserved,0);
 assert.equal(d.activation,'not observed');
 for(const directory of ['units','sessions','costlog'])assert.equal(fs.existsSync(path.join(f.base,directory)),false);
 assert.equal(fs.readFileSync(f.transcript,'utf8'),JSON.stringify({type:'session_meta',payload:{id:'self'}})+'\n');
 const saved=JSON.stringify(d.hookDiagnostics);
 assert.equal(saved.includes('PRIVATE_PROMPT_NOT_TO_STORE'),false);
 assert.equal(saved.includes('PRIVATE_COMMAND_NOT_TO_STORE'),false);
});

test('missing gauge configuration is diagnosed without an invented native event',async()=>{
 const f=fixture();fs.unlinkSync(path.join(f.home,'mai-codex-gauge.json'));
 const {account,...environment}=f.environment;
 assert.deepEqual(await handleHook(f.input,environment),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics?.latestFailure?.code,'gauge_config_missing');
 assert.equal(d.handlerEventsObserved,0);
});

test('an observation failure persists a safe stage code rather than private payloads or raw errors',async()=>{
 const f=fixture();
 const missing=path.join(f.home,'sessions','PRIVATE_FILE_NAME.jsonl');
 assert.deepEqual(await handleHook({...f.input,transcript_path:missing},f.environment),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics?.latestFailure?.code,'observation_failed');
 assert.equal(d.hookDiagnostics.latestFailure.errorCode,'ENOENT');
 assert.equal(d.handlerEventsObserved,0);
 assert.equal(JSON.stringify(d.hookDiagnostics).includes('PRIVATE_FILE_NAME'),false);
});
test('a blocked session-state writer is a safe explicit policy diagnostic, not an unexplained failure',async()=>{
 const f=fixture();fs.mkdirSync(path.join(f.base,'sessions'),{recursive:true});
 fs.writeFileSync(path.join(f.base,'sessions','self.json.gauge-lock'),'');
 assert.deepEqual(await handleHook(f.input,f.environment),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics.latestFailure.code,'policy_failed');
 assert.equal(d.hookDiagnostics.latestFailure.reason,'session writer busy or external edit');
 assert.notEqual(d.activation,'not observed');
});

test('doctor distinguishes a foreign rollout owner from missing files without logging payloads',async()=>{
 const f=fixture();
 const foreign=path.join(f.home,'sessions','PRIVATE_CHAT_TRANSCRIPT.jsonl');
 fs.writeFileSync(foreign,JSON.stringify({type:'session_meta',payload:{id:'other'}})+'\n');
 await handleHook({...f.input,transcript_path:foreign},f.environment);
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics.latestFailure.reason,'transcript owner mismatch');
 assert.equal(JSON.stringify(d.hookDiagnostics).includes('PRIVATE_CHAT_TRANSCRIPT'),false);
 assert.equal(d.handlerEventsObserved,0);
});

test('accepted hooks stay observable and failure diagnostics are bounded and isolated by input session',async()=>{
 const f=fixture();
 for(let i=0;i<40;i++)await handleHook(f.input,{...f.environment,sessionId:'old-window'});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics?.recentFailures?.length,32);
 assert.equal(doctor({home:f.home,base:f.base,sessionId:'other'}).hookDiagnostics.latestFailure,null);
 await handleHook(f.input,f.environment);
 assert.equal(doctor({home:f.home,base:f.base,sessionId:'self'}).handlerEventsObserved,1);
});

test('a real Node child with stale CODEX_THREAD_ID records the incoming owner and the actual CODEX_HOME',()=>{
 const f=fixture();
 const program=`import fs from 'node:fs'; import {handleHook} from ${JSON.stringify(new URL('../src/hook.mjs',import.meta.url).href)}; const input=JSON.parse(fs.readFileSync(0,'utf8')); console.log(JSON.stringify(await handleHook(input,{base:process.argv[1],quiet:true})));`;
 const result=spawnSync(process.execPath,['--input-type=module','-e',program,f.base],{
  encoding:'utf8',input:JSON.stringify(f.input),windowsHide:true,
  env:{CODEX_HOME:f.home,CODEX_THREAD_ID:'old-window',...(process.env.SYSTEMROOT?{SYSTEMROOT:process.env.SYSTEMROOT}:{})}
 });
 assert.equal(result.status,0,result.stderr);assert.deepEqual(JSON.parse(result.stdout),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics.latestFailure.code,'session_id_mismatch');
 assert.equal(d.hookDiagnostics.latestFailure.environmentSessionId,'old-window');
 assert.equal(d.hookDiagnostics.latestFailure.codexHome,path.resolve(f.home));
 assert.equal(d.handlerEventsObserved,0);
 assert.equal(fs.existsSync(path.join(f.base,'hook-diagnostics','old-window.json')),false);
});

test('malformed diagnostic evidence is reported without exposing its contents or replacing a foreign owner',async()=>{
 const f=fixture(),directory=path.join(f.base,'hook-diagnostics');fs.mkdirSync(directory,{recursive:true});
 const file=path.join(directory,'self.json'),original=JSON.stringify({sessionId:'other',schemaVersion:1,failures:[],privateValue:'DO_NOT_ECHO'});
 fs.writeFileSync(file,original);
 assert.deepEqual(await handleHook(f.input,{...f.environment,sessionId:'old-window'}),{});
 const d=doctor({home:f.home,base:f.base,sessionId:'self'});
 assert.equal(d.hookDiagnostics.status,'unreadable diagnostic evidence');
 assert.equal(JSON.stringify(d).includes('DO_NOT_ECHO'),false);
 assert.equal(fs.readFileSync(file,'utf8'),original);
});
