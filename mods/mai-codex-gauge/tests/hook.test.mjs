import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {handleHook,observe,validateTranscript} from '../src/hook.mjs';import {saveSession,readJson} from '../src/store.mjs';
function setup(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-hook-')),home=path.join(root,'codex'),base=path.join(root,'mai');fs.mkdirSync(path.join(home,'sessions'),{recursive:true});const transcript=path.join(home,'sessions','rollout-self.jsonl');fs.writeFileSync(transcript,[{type:'session_meta',timestamp:'2026-10-09T00:00:00Z',payload:{id:'self'}},{type:'turn_context',payload:{model:'gpt-6.1-sol',turn_id:'t'}},{timestamp:'2026-10-09T00:00:01Z',type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{total_tokens:120},last_token_usage:{input_tokens:100,cached_input_tokens:60,cache_write_input_tokens:10,output_tokens:20},model_context_window:200},rate_limits:{primary:{used_percent:7,window_minutes:10080,resets_at:2000000000}}}}].map(x=>JSON.stringify(x)).join('\n')+'\n');return {home,base,transcript,environment:{codexHome:home,base,account:'codex:test',sessionId:'self',handle:null}};}
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
test('full scan, events, turn cost and compact reference without blocking or altering original',async()=>{
 const f=setup(),before=hash(f.transcript);await observe({...f,sessionId:'self',codexHome:f.home,account:'codex:test',full:true});saveSession(f.base,'self',{at:Date.now(),doing:'Build gauge',issues:['vfxpedia/mai-os#30']});
 for(const event of ['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt','PreCompact','PostCompact']){const out=await handleHook({session_id:'self',hook_event_name:event,transcript_path:f.transcript,cwd:'X:/repo',turn_id:'t',tool_input:{command:'SECRET_NOT_TO_STORE'},prompt:'PRIVATE_PROMPT',source:'compact'},f.environment);assert.notEqual(out.continue,false);assert.notEqual(out.decision,'block');if(event==='SessionStart')assert.match(out.hookSpecificOutput.additionalContext,/Build gauge/);if(event==='PostCompact')assert.equal(out.hookSpecificOutput,undefined);}
 const units=readJson(path.join(f.base,'units','self.json'));assert.equal(units.codex.state.requests,1);assert.equal(hash(f.transcript),before);assert.equal(JSON.stringify(units).includes('SECRET_NOT_TO_STORE'),false);assert.equal(JSON.stringify(units).includes('PRIVATE_PROMPT'),false);assert.ok(units.codex.compacts.length>=1);
});
test('malformed, foreign session and source path fail open without private values',async()=>{
 const f=setup();assert.deepEqual(await handleHook(null,f.environment),{});assert.deepEqual(await handleHook({session_id:'other',hook_event_name:'Stop'},f.environment),{});
 assert.throws(()=>validateTranscript(path.join(f.home,'../outside.jsonl'),f.home,'self'));
 const foreign=path.join(f.home,'sessions','other.jsonl');fs.writeFileSync(foreign,JSON.stringify({type:'session_meta',payload:{id:'other'}})+'\n');assert.throws(()=>validateTranscript(foreign,f.home,'self'));
 const out=await handleHook({session_id:'self',hook_event_name:'Stop',transcript_path:foreign},f.environment);assert.deepEqual(out,{});
});
test('partial hook scan stays partial; no first hook full historical loop; idle limits bytes stay',async()=>{
 const f=setup();const x=await observe({...f,codexHome:f.home,sessionId:'self',account:'codex:test',full:false});assert.equal(x.historyComplete,false);
 const limits=path.join(f.base,'limits.json'),before=fs.existsSync(limits)?hash(limits):null;await observe({...f,codexHome:f.home,sessionId:'self',account:'codex:test'});assert.equal(fs.existsSync(limits)?hash(limits):null,before);
});
test('native display transcript outside CODEX_HOME is not mistaken for the owned metric rollout',async()=>{
 const f=setup(),outside=path.join(path.dirname(f.home),'PRIVATE_CHAT_TRANSCRIPT.md');
 fs.writeFileSync(outside,'PRIVATE_CONTENT_NOT_TO_READ');
 const before=hash(outside);
 await handleHook({session_id:'self',hook_event_name:'PreToolUse',transcript_path:outside,turn_id:'t'},f.environment);
 const d=readJson(path.join(f.base,'units','self.json'));
 assert.equal(d?.codex?.events?.length,1);
 assert.equal(d.codex.state.requests,1);
 assert.equal(d.codex.source,f.transcript);
 assert.equal(hash(outside),before);
 assert.equal(JSON.stringify(d).includes('PRIVATE_CONTENT_NOT_TO_READ'),false);
});
test('temporary backlog recovers complete coverage without another manual full scan',async()=>{
 const f=setup(),opts={...f,codexHome:f.home,sessionId:'self',account:'codex:test'};assert.equal((await observe({...opts,full:true})).historyComplete,true);
 fs.appendFileSync(f.transcript,JSON.stringify({type:'compacted',payload:{text:'x'.repeat(2200000)}})+'\n');assert.equal((await observe(opts)).historyComplete,false);
 let result;for(let i=0;i<4;i++){result=await observe(opts);if(result.historyComplete)break;}assert.equal(result.historyComplete,true);assert.equal(result.requests,1);
});
