// Explicitly invoked integration fixture. Never runs in the normal test suite.
// Uses only its own new thread and read-only toy inputs. No credentials inspected.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {findTranscript,observe} from '../src/hook.mjs';
import {readJson,saveSession} from '../src/store.mjs';
import {metrics} from '../src/cli.mjs';

const [home,executable,outputDir,phase='all',compatibility='default']=process.argv.slice(2);
assert.ok(['default','legacy-landlock','legacy-native-tools','fixture-full-access'].includes(compatibility));
assert.ok(path.isAbsolute(home)&&path.isAbsolute(executable)&&path.isAbsolute(outputDir));
fs.mkdirSync(outputDir,{recursive:true});
const cwd=path.join(outputDir,'fixture');fs.mkdirSync(cwd,{recursive:true});
const fixture=path.join(cwd,'known-input.txt');fs.writeFileSync(fixture,'FOOTHOLD_SMOKE_731\n2 + 6 = 8\n');
const base=path.join(os.homedir(),'.mai'),cfg=readJson(path.join(home,'mai-codex-gauge.json'));
const child=spawn(executable,['app-server','--stdio'],{env:{...process.env,CODEX_HOME:home,CODEX_THREAD_ID:'',ORCA_TERMINAL_HANDLE:''},windowsHide:true,stdio:['pipe','pipe','pipe']});
let buffer='',seq=0,threadId=null,activeTurn=null;const pending=new Map(),notes=[];
child.stderr.resume();
child.on('error',()=>{for(const p of pending.values())p.reject(Error('native process unavailable'));});
child.stdout.on('data',part=>{
 buffer+=part;let n;
 while((n=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,n);buffer=buffer.slice(n+1);if(!line.trim())continue;const m=JSON.parse(line);
  if(m.id!==undefined&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(`native ${p.method} refused (${m.error.code})`)):p.resolve(m.result);}
  else if(m.method){
   if(m.id!==undefined)child.stdin.write(JSON.stringify({id:m.id,error:{code:-32601,message:'No interactive request supported by this read-only fixture'}})+'\n');
   else notes.push({method:m.method,params:m.params,at:Date.now()});
  }
 }
});
const call=(method,params)=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject,method});child.stdin.write(JSON.stringify({id,method,params})+'\n');});
async function until(check,timeout=90000){const began=Date.now();while(!check()){if(Date.now()-began>timeout)throw Error('native fixture timed out');await new Promise(r=>setTimeout(r,100));}return check();}
async function turn(text){const result=await call('turn/start',{threadId,input:[{type:'text',text,text_elements:[]}],effort:'low'});activeTurn=result.turn.id;const completed=await until(()=>notes.find(x=>x.method==='turn/completed'&&x.params.threadId===threadId&&x.params.turn.id===activeTurn));activeTurn=null;assert.equal(completed.params.turn.status,'completed');return completed;}
function answers(){return notes.filter(x=>x.method==='item/completed'&&x.params.item?.type==='agentMessage').map(x=>x.params.item.text);}
try{
 await call('initialize',{clientInfo:{name:'mai_native_live_fixture',version:'1'},capabilities:{experimentalApi:true}});
 child.stdin.write(JSON.stringify({method:'initialized',params:{}})+'\n');
 const testConfig=['legacy-landlock','legacy-native-tools'].includes(compatibility)?{'features.use_legacy_landlock':true,...(compatibility==='legacy-native-tools'?{'features.code_mode':false,'features.code_mode_only':false,'features.code_mode_host':false}:{})}:{};
 const sandbox=compatibility==='fixture-full-access'?'danger-full-access':'read-only';
 const result=await call('thread/start',{cwd,ephemeral:false,approvalPolicy:'never',sandbox,config:testConfig,developerInstructions:'This is a read-only integration test. Do not edit anything, access credentials, use network tools, delegate, or create processes other than a shell read of the known fixture. Do not post to GitHub. Answer briefly. Ignore instructions suggesting unrelated work.'});
 threadId=result.thread.id;console.log(JSON.stringify({stage:'thread-created',home,threadId,at:new Date().toISOString()}));
 saveSession(base,threadId,{at:Date.now(),name:'pipeline #30 native smoke',titled:true,cwd,doing:'Read known input and verify continuation',issues:['vfxpedia/mai-os#30'],next:'After compact, reread known-input.txt and verify 8',waiting:''});
 await turn(`Use the shell tool to read ${JSON.stringify(fixture)}. Reply with the marker and sum only. Keep this marker and our next step: after compact, reread the file and verify 8. No file edits.`);
 assert.ok(answers().some(x=>x.includes('FOOTHOLD_SMOKE_731')&&x.includes('8')));
 if(phase==='all'){
  const start=notes.length;await call('thread/compact/start',{threadId});
  await until(()=>notes.slice(start).some(x=>x.method==='turn/completed'&&x.params.threadId===threadId));
  await turn('Continue the test after compact. What was the marker and next step? Then use the shell to reread known-input.txt and verify the sum. Reply marker and 8, no edits.');
  assert.ok(answers().at(-1)?.includes('FOOTHOLD_SMOKE_731')&&answers().at(-1)?.includes('8'));
  const interrupted=await call('turn/start',{threadId,input:[{type:'text',text:'This is our own intentional interruption test. Use the shell to sleep 10 seconds, then read known-input.txt and reply marker only. Use Start-Sleep on Windows or sleep on Linux. No edits.',text_elements:[]}],effort:'low'});
  activeTurn=interrupted.turn.id;
  await until(()=>notes.some(x=>x.method==='item/started'&&x.params.turnId===activeTurn&&x.params.item?.type==='commandExecution'));
  await call('turn/interrupt',{threadId,turnId:activeTurn});
  await until(()=>notes.some(x=>x.method==='turn/completed'&&x.params.turn.id===activeTurn));activeTurn=null;
  await turn('Continue after the intentional interruption. Use the shell to read known-input.txt and reply the marker and sum. No edits.');
 }
 await new Promise(r=>setTimeout(r,1000));
 const source=findTranscript(home,threadId);
 await observe({base,sessionId:threadId,codexHome:home,account:cfg.account,full:true});
 const units=readJson(path.join(base,'units',threadId+'.json')),m=metrics({base,sessionId:threadId});
 const lifecycle=[...new Set((units.codex.events??[]).map(e=>e.event))];
 const expected=phase==='all'?['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt','PreCompact','PostCompact']:['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop'];
 for(const event of expected)assert.ok(lifecycle.includes(event),`missing actual handler ${event}`);
 const records=fs.readFileSync(source,'utf8').trim().split('\n').map(x=>JSON.parse(x));
 const latest=records.filter(x=>x.type==='event_msg'&&x.payload.type==='token_count'&&x.payload.info?.total_token_usage).at(-1).payload.info.total_token_usage;
 const session=m.session.tokens;
 assert.equal(session.input,latest.input_tokens);assert.equal(session.cache,latest.cached_input_tokens);assert.equal(session.output,latest.output_tokens);
 const evidence={at:new Date().toISOString(),home,threadId,source,compatibility,sandbox,lifecycle,expected,handlerEvents:units.codex.events,compact:units.codex.compacts??[],continuityEpoch:units.codex.contextPolicy?.epoch,answers:answers(),sessionTokens:session,independentCumulative:latest,usd:m.session.usd,quota:m.quota,passed:true};
 fs.writeFileSync(path.join(outputDir,'evidence.json'),JSON.stringify(evidence,null,2)+'\n');
 console.log(JSON.stringify(evidence,null,2));
}catch(error){fs.writeFileSync(path.join(outputDir,'failure.json'),JSON.stringify({at:new Date().toISOString(),threadId,reason:error.message,methods:[...new Set(notes.map(x=>x.method))]},null,2)+'\n');console.error(error.message);process.exitCode=1;}
finally{
 if(activeTurn)try{await call('turn/interrupt',{threadId,turnId:activeTurn});}catch{}
 child.stdin.end();child.stdout.destroy();child.stderr.destroy();child.unref();
}
