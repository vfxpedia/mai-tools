import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {observe} from '../src/hook.mjs';
import {planInstall,applyInstall} from '../src/install.mjs';

function fixture(count=1){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-review-')),home=path.join(root,'codex'),base=path.join(root,'mai');
 fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 const transcript=path.join(home,'sessions','rollout-self.jsonl'),rows=[{type:'session_meta',payload:{id:'self'}}];
 for(let i=1;i<=count;i++)rows.push(...turn(i));
 fs.writeFileSync(transcript,rows.map(x=>JSON.stringify(x)).join('\n')+'\n');
 return {root,home,base,transcript,codexHome:home,sessionId:'self',account:'codex:test'};
}
function turn(i){return [{type:'turn_context',payload:{turn_id:'t'+i,model:'test'}},{type:'event_msg',timestamp:'2026-10-14T00:00:00Z',payload:{type:'token_count',info:{total_token_usage:{total_tokens:i*12},last_token_usage:{input_tokens:10,cached_input_tokens:4,output_tokens:2}}}}];}
const units=f=>JSON.parse(fs.readFileSync(path.join(f.base,'units','self.json'),'utf8')).codex;
const cost=f=>JSON.parse(fs.readFileSync(path.join(f.base,'costlog','2026-10-14','self.json'),'utf8'));

test('blocked token-only costlog is durable and retries the old turn after a new turn arrives',async()=>{
 const f=fixture(),lock=path.join(f.base,'costlog','2026-10-14','self.json.gauge-lock');
 fs.mkdirSync(path.dirname(lock),{recursive:true});fs.writeFileSync(lock,JSON.stringify({pid:process.pid,host:os.hostname(),nonce:'fixture-live'}));
 await observe({...f,full:true});
 assert.ok(Object.keys(units(f).pendingTurns??{}).includes('t1'),'failed token-only write must stay pending');
 fs.unlinkSync(lock);fs.appendFileSync(f.transcript,turn(2).map(x=>JSON.stringify(x)).join('\n')+'\n');
 await observe(f);await observe(f);
 assert.deepEqual(cost(f).events.map(x=>x.turn_id).sort(),['t1','t2']);
 assert.equal(Object.keys(units(f).pendingTurns??{}).length,0);
});

test('one increment persists all completed turns, not just the last turn',async()=>{
 const f=fixture(6);await observe(f);
 assert.equal(cost(f).events.length,6);
 assert.equal(cost(f).events.reduce((n,x)=>n+x.totalTokens,0),72);
});

test('cold hook reduction obeys a record budget and advances only through processed rows',async()=>{
 const f=fixture(1400),began=performance.now();await observe({...f,recordBudget:40});
 const c=units(f);assert.ok(c.state.requests>0&&c.state.requests<1400);
 assert.equal(c.cursor.offset,Buffer.from(fs.readFileSync(f.transcript,'utf8').split('\n').slice(0,40).join('\n')+'\n').length);
 assert.ok(performance.now()-began<1500,'the known cold fixture must finish below the native 2-second timeout');
});

test('paused full scan resumes instead of rereading the same prefix',async()=>{
 const f=fixture(60);let last=0,done=false;
 for(let i=0;i<20;i++){
  const r=await observe({...f,full:true,recordBudget:20});
  if(i===0)assert.equal(r.historyComplete,false,'the known budget must force a pause before testing resume');
  assert.ok(r.cursor>last,'each scan must make forward progress');last=r.cursor;
  if(r.historyComplete){done=true;break;}
 }
 assert.equal(done,true);assert.equal(units(f).state.requests,60);assert.equal(cost(f).events.length,60);
});

test('full scan also makes durable forward progress across an actual elapsed-time deadline',async()=>{
 const f=fixture(10000),first=await observe({...f,full:true,budgetMs:5});
 assert.equal(first.historyComplete,false);
 // A loaded host may consume a 5ms budget in open/hash alone. The next scan
 // must still resume, with enough time to perform measurable reduction.
 const second=await observe({...f,full:true,budgetMs:100});assert.ok(second.cursor>first.cursor);
 const finished=await observe({...f,full:true});assert.equal(finished.historyComplete,true);assert.equal(finished.requests,10000);
 assert.equal(cost(f).events.length,10000);
});

test('the actual default cold observation stays below 2 seconds and can finish incrementally',async()=>{
 const f=fixture(1400),began=performance.now(),first=await observe(f);
 assert.ok(performance.now()-began<1500);assert.ok(first.requests>0&&first.requests<1400);
 for(let i=0;i<10&&units(f).state.requests<1400;i++)await observe(f);
 assert.equal(units(f).state.requests,1400);assert.equal(cost(f).events.length,1400);
});

test('installed root and native hook commands launch without Node on PATH, including spaces',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods spaced review ')),home=path.join(root,'codex home');fs.mkdirSync(home);
 const source=path.resolve(import.meta.dirname,'..');
 applyInstall(planInstall({codexHome:home,source,account:'codex:test',mode:'native'}),path.join(root,'backup'));
 const version=JSON.parse(fs.readFileSync(path.join(source,'package.json'))).version;
 const command=JSON.parse(fs.readFileSync(path.join(home,'plugins','cache','mai-codex-local','mai-codex-gauge',version,'hooks.json'))).hooks.Stop[0].hooks[0].command;
 assert.ok(!command.startsWith('node '),'installed commands must bind the approved Node executable');
 const env={...process.env,PATH:process.platform==='win32'?path.join(process.env.SystemRoot,'System32'):'/usr/bin:/bin',CODEX_HOME:home,HOME:root,USERPROFILE:root,CODEX_THREAD_ID:''};
 const shells=process.platform==='win32'?[[path.join(process.env.SystemRoot,'System32/WindowsPowerShell/v1.0/powershell.exe'),['-NoProfile','-NonInteractive','-Command',command]],[path.join(process.env.SystemRoot,'System32/cmd.exe'),['/d','/s','/c',command]]]:[['/bin/sh',['-c',command]],['/bin/bash',['-c',command]]];
 // A positive payload catches launchers that print {} while losing stdin.
 const sessions=path.join(home,'sessions');fs.mkdirSync(sessions);fs.writeFileSync(path.join(sessions,'rollout-self.jsonl'),JSON.stringify({type:'session_meta',payload:{id:'self'}})+'\n');
 const payload=JSON.stringify({session_id:'self',hook_event_name:'PreToolUse',turn_id:'t',cwd:root});
 for(const [shell,args] of shells){
  // Native COMSPEC fallback uses raw_arg with the whole command wrapped.
  const cmd=process.platform==='win32'&&shell.endsWith('cmd.exe');
  const invocation=cmd?[...args.slice(0,-1),'"'+args.at(-1)+'"']:args;
  const r=spawnSync(shell,invocation,{env,input:payload,encoding:'utf8',timeout:5000,windowsHide:true,windowsVerbatimArguments:cmd});assert.equal(r.status,0,r.stderr);assert.deepEqual(JSON.parse(r.stdout),{});
 }
 assert.equal(JSON.parse(fs.readFileSync(path.join(root,'.mai','units','self.json'))).codex.events.length,2,'positive stdin must survive both shells');
 const f=fixture();applyInstall(planInstall({codexHome:f.home,source,account:'codex:test',mode:'hooks'}),path.join(f.root,'backup'));
 const rootCommand=JSON.parse(fs.readFileSync(path.join(f.home,'hooks.json'))).hooks.Stop[0].hooks[0].command;
 assert.ok(!rootCommand.startsWith('node '));
});
