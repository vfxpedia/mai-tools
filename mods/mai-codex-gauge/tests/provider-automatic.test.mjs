import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {handleHook,observe} from '../src/hook.mjs';import {saveSession,readJson} from '../src/store.mjs';import {show} from '../src/cli.mjs';
function fixture(){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-api-')),home=path.join(root,'codex'),base=path.join(root,'mai');fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 const transcript=path.join(home,'sessions','rollout-self.jsonl');fs.writeFileSync(transcript,JSON.stringify({type:'session_meta',payload:{id:'self'}})+'\n'+JSON.stringify({type:'turn_context',payload:{turn_id:'t',model:'changing-model'}})+'\n');
 let total=0;const append=()=>fs.appendFileSync(transcript,JSON.stringify({timestamp:new Date().toISOString(),type:'event_msg',payload:{type:'token_count',info:{model_context_window:10000,total_token_usage:{total_tokens:total+=120},last_token_usage:{input_tokens:100,output_tokens:20}}}})+'\n');
 const event=hook_event_name=>({session_id:'self',hook_event_name,transcript_path:transcript,cwd:'X:/repo',turn_id:'t'});
 return {base,home,transcript,append,event,env:{base,codexHome:home,account:'codex:test',sessionId:'self',quiet:true}};
}
function sample(usd=1000000){return {threadId:'self',at:Date.now(),kind:'provider-estimate',status:usd===null?'unavailable':'available',usdMicros:usd,sessionUsd:usd===null?null:usd/1e6,turnUsd:null,groups:[],reason:usd===null?'no thread billing route':null,quotaStatus:'received',rateLimits:{observedAt:Date.now(),primary:{used_percent:8,window_minutes:10080,resets_at:2000000000},secondary:null}};}
test('observation automatically reads real API for fresh requests, idle does not fabricate quota samples',async()=>{
 const f=fixture();f.append();let calls=0;const providerReader=async()=>{calls++;return sample(null);};
 await observe({...f.env,transcript:f.transcript,providerReader});assert.equal(calls,1);
 const limitsFile=path.join(f.base,'limits.json'),before=fs.readFileSync(limitsFile);const p=readJson(path.join(f.base,'units','self.json')).codex.provider;
 assert.equal(p.sessionUsd,null);assert.equal(p.rateLimits.primary.window_minutes,10080);
 await observe({...f.env,transcript:f.transcript,providerReader});assert.equal(calls,1);assert.deepEqual(fs.readFileSync(limitsFile),before);
 saveSession(f.base,'self',{at:Date.now(),doing:'API verification'});
 assert.match(show({base:f.base,sessionId:'self',cols:100}),/5 hours.*not provided/);assert.match(show({base:f.base,sessionId:'self',cols:100}),/turn.*USD not provided/);
});
test('native prompt and stop boundaries store per-turn API delta and session API USD without local conversion',async()=>{
 const f=fixture();let value=1000000;const env={...f.env,providerReader:async()=>sample(value)};
 await handleHook(f.event('UserPromptSubmit'),env);f.append();value=1250000;await handleHook(f.event('Stop'),env);
 const u=readJson(path.join(f.base,'units','self.json'));assert.equal(u.codex.provider.sessionUsd,1.25);assert.equal(u.codex.provider.turnUsd,.25);
 const logs=fs.readdirSync(path.join(f.base,'costlog'));const log=readJson(path.join(f.base,'costlog',logs[0],'self.json'));
 assert.equal(log.events[0].costUsd,.25);assert.equal(log.events[0].costSource,'provider-estimate-delta');
 await handleHook(f.event('PostToolUse'),env);assert.equal(readJson(path.join(f.base,'costlog',logs[0],'self.json')).events[0].costUsd,.25);
 assert.match(show({base:f.base,sessionId:'self',cols:100}),/\$0\.250.*\[\$1\.250\]/);
});
test('missing baseline, API null and duplicate Stop never invent a turn cost',async()=>{
 const f=fixture();f.append();await handleHook(f.event('Stop'),{...f.env,providerReader:async()=>sample(1000000)});
 assert.equal(readJson(path.join(f.base,'units','self.json')).codex.provider.turnUsd,null);
 await handleHook(f.event('UserPromptSubmit'),{...f.env,providerReader:async()=>sample(null)});await handleHook(f.event('Stop'),{...f.env,providerReader:async()=>sample(2000000)});
 assert.equal(readJson(path.join(f.base,'units','self.json')).codex.provider.turnUsd,null);
});
test('first prompt renders the supplied quota without writing an idle account sample',async()=>{
 const f=fixture();await handleHook(f.event('UserPromptSubmit'),{...f.env,providerReader:async()=>sample(null)});
 assert.equal(fs.existsSync(path.join(f.base,'limits.json')),false);
 const output=show({base:f.base,sessionId:'self',cols:100});
 assert.match(output,/7 days.*8%/);assert.match(output,/5 hours.*not provided/);
});
test('confirmed API turn cost retries the costlog write after a temporary lock',async()=>{
 const f=fixture();let value=1000000;const env={...f.env,providerReader:async()=>sample(value)};
 await handleHook(f.event('UserPromptSubmit'),env);f.append();await handleHook(f.event('PostToolUse'),env);
 const directory=path.join(f.base,'costlog',fs.readdirSync(path.join(f.base,'costlog'))[0]);
 const lock=path.join(directory,'self.json.gauge-lock');fs.writeFileSync(lock,'fixture');
 try{value=1250000;await handleHook(f.event('Stop'),env);}finally{fs.unlinkSync(lock);}
 assert.equal(readJson(path.join(f.base,'units','self.json')).codex.providerTurns.t.turnUsd,.25);
 await handleHook(f.event('PostToolUse'),env);
 assert.equal(readJson(path.join(directory,'self.json')).events[0].costUsd,.25);
});
test('already persisted previous-turn evidence is not rewritten or blocked on every later hook',async()=>{
 const f=fixture();let value=1000000;const env={...f.env,providerReader:async()=>sample(value)};
 await handleHook(f.event('UserPromptSubmit'),env);f.append();value=1250000;await handleHook(f.event('Stop'),env);
 fs.appendFileSync(f.transcript,JSON.stringify({type:'turn_context',payload:{turn_id:'later',model:'changing-model'}})+'\n');
 const log=path.join(f.base,'costlog',fs.readdirSync(path.join(f.base,'costlog'))[0],'self.json'),lock=log+'.gauge-lock',before=fs.readFileSync(log);
 fs.writeFileSync(lock,'fixture');
 try{await observe({...f.env,transcript:f.transcript});}finally{fs.unlinkSync(lock);}
 assert.deepEqual(fs.readFileSync(log),before);
});
