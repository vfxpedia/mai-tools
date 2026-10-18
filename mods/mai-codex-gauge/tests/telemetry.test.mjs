import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {reduceRecord,newState} from '../src/usage.mjs';import {handleHook} from '../src/hook.mjs';import {readJson,saveSession} from '../src/store.mjs';
import * as cli from '../src/cli.mjs';import * as provider from '../src/provider.mjs';import {bandRows,renderRows,cells} from '../src/band.mjs';
function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-tokens-')),home=path.join(root,'codex'),base=path.join(root,'mai');fs.mkdirSync(path.join(home,'sessions'),{recursive:true});const transcript=path.join(home,'sessions','rollout-self.jsonl');let cumulative=0;
 const append=record=>fs.appendFileSync(transcript,JSON.stringify(record)+'\n');append({type:'session_meta',payload:{id:'self'}});
 const turn=id=>append({type:'turn_context',payload:{turn_id:id,model:'new-model-not-in-any-table'}});
 const request=(input,cache,output)=>append({timestamp:new Date().toISOString(),type:'event_msg',payload:{type:'token_count',info:{model_context_window:10000,total_token_usage:{total_tokens:cumulative+=input+output},last_token_usage:{input_tokens:input,cached_input_tokens:cache,output_tokens:output}}}});
 let pct=10;const sample=()=>({threadId:'self',at:Date.now(),kind:'provider-estimate',status:'unavailable',sessionUsd:null,usdMicros:null,turnUsd:null,creditsMicros:null,groups:[],reason:'USD not provided',quotaStatus:'received',rateLimits:{observedAt:Date.now(),primary:{used_percent:pct,window_minutes:10080,resets_at:2000000000},secondary:null}});
 const env={base,codexHome:home,account:'codex:test',sessionId:'self',quiet:true,providerReader:async()=>sample()};const event=(name,id)=>({session_id:'self',turn_id:id,hook_event_name:name,cwd:root,transcript_path:transcript});
 return {root,home,base,transcript,turn,request,env,event,pct:n=>pct=n};}
test('a plain Codex home displays its last engine quota sample without an Orca provider',async()=>{
 const f=fixture();f.turn('a');
 fs.appendFileSync(f.transcript,JSON.stringify({timestamp:new Date().toISOString(),type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{total_tokens:120},last_token_usage:{input_tokens:100,cached_input_tokens:40,output_tokens:20},model_context_window:1000},rate_limits:{primary:{used_percent:7,window_minutes:10080,resets_at:2000000000},secondary:null}}})+'\n');
 await handleHook(f.event('Stop','a'),{...f.env,providerReader:async()=>{throw Error('No managed provider in a plain home');}});
 const m=cli.metrics({base:f.base,sessionId:'self'});assert.equal(m.quota.sevenDays?.used_percent,7);assert.equal(m.quota.fiveHours,null);assert.equal(m.session.usd,null);
 const limits=path.join(f.base,'limits.json'),before=fs.readFileSync(limits);
 assert.match(cli.show({base:f.base,sessionId:'self',cols:120}),/7 days.*7%/);
 assert.match(cli.show({base:f.base,sessionId:'self',cols:120}),/5 hours.*not provided/);
 assert.deepEqual(fs.readFileSync(limits),before);
});
test('two native turns persist exact input/cache/output without USD or external lookup',async()=>{
 const f=fixture();f.turn('a');await handleHook(f.event('UserPromptSubmit','a'),f.env);f.request(100,40,20);f.request(200,90,30);f.pct(12);await handleHook(f.event('Stop','a'),f.env);
 f.turn('b');await handleHook(f.event('UserPromptSubmit','b'),f.env);f.request(500,300,70);f.pct(13);await handleHook(f.event('Stop','b'),f.env);
 assert.equal(typeof cli.metrics,'function','metrics command must expose complete token numbers');
 const m=cli.metrics({base:f.base,sessionId:'self'});assert.deepEqual(m.session.tokens,{input:800,cache:430,output:120,total:920});assert.deepEqual(m.turn.tokens,{input:500,cache:300,output:70,total:570});
 assert.equal(m.turn.id,'b');assert.equal(m.session.usd,null);assert.equal(m.turn.usd,null);assert.equal(m.quota.fiveHours,null);assert.equal(m.quota.sevenDays.used_percent,13);
 assert.equal(m.turn.quotaChange.scope,'account');assert.equal(m.turn.quotaChange.windows.seven_day.deltaPercentagePoints,1);
 const log=readJson(path.join(f.base,'costlog',fs.readdirSync(path.join(f.base,'costlog'))[0],'self.json'));
 assert.deepEqual(log.events.map(e=>[e.inputTokens,e.cachedInputTokens,e.outputTokens,e.costUsd,e.quotaChange.windows.seven_day.deltaPercentagePoints]),[[300,130,50,null,2],[500,300,70,null,1]]);
 await handleHook(f.event('Stop','b'),f.env);assert.equal(cli.metrics({base:f.base,sessionId:'self'}).turn.quotaChange.windows.seven_day.deltaPercentagePoints,1);
 f.turn('c');await handleHook(f.event('UserPromptSubmit','c'),f.env);assert.equal(cli.metrics({base:f.base,sessionId:'self'}).turn.tokens,null,'new turn must not show previous turn as current');
});
test('account quota delta rejects missing baseline, reset, decrease and reversed time; zero is measured',()=>{
 assert.equal(typeof provider.quotaTurnDelta,'function');
 const q=(pct,time=100,reset=2000000000)=>({observedAt:time,primary:{used_percent:pct,window_minutes:10080,resets_at:reset},secondary:null});
 assert.equal(provider.quotaTurnDelta(null,q(12)).windows.seven_day,null);
 assert.equal(provider.quotaTurnDelta(q(10),q(12,200)).windows.seven_day.deltaPercentagePoints,2);
 assert.equal(provider.quotaTurnDelta(q(10),q(10,200)).windows.seven_day.deltaPercentagePoints,0);
 for(const after of [q(12,200,2000000001),q(9,200),q(12,99)])assert.equal(provider.quotaTurnDelta(q(10),after).windows.seven_day,null);
 assert.equal(provider.quotaTurnDelta(q(10),q(12,200)).windows.five_hour,null);
});
test('a busy costlog retries the retained quota evidence without a new API sample',async()=>{
 const f=fixture();f.turn('a');await handleHook(f.event('UserPromptSubmit','a'),f.env);f.request(100,40,20);await handleHook(f.event('PostToolUse','a'),f.env);
 const date=fs.readdirSync(path.join(f.base,'costlog'))[0],logFile=path.join(f.base,'costlog',date,'self.json'),lock=logFile+'.gauge-lock';
 fs.writeFileSync(lock,'test writer');f.pct(12);try{await handleHook(f.event('Stop','a'),f.env);}finally{fs.unlinkSync(lock);}
 assert.equal(cli.metrics({base:f.base,sessionId:'self'}).turn.quotaChange.windows.seven_day.deltaPercentagePoints,2);
 f.turn('b');let calls=0;await handleHook(f.event('PostToolUse','b'),{...f.env,providerReader:async()=>{calls++;throw Error('idle must not query');}});
 assert.equal(calls,0);assert.equal(readJson(logFile).events[0].quotaChange?.windows.seven_day.deltaPercentagePoints,2);
});
test('the five-row display prioritizes measured tokens and labels quota change as account-wide',async()=>{
 const f=fixture();f.turn('a');await handleHook(f.event('UserPromptSubmit','a'),f.env);f.request(100,40,20);f.pct(12);await handleHook(f.event('Stop','a'),f.env);saveSession(f.base,'self',{at:Date.now(),doing:'Telemetry verification'});
 for(const cols of [40,56,80,120,200]){const lines=cli.show({base:f.base,sessionId:'self',cols}).split('\n');assert.equal(lines.length,5);assert.match(lines[3],/T 100\/40\/20/);assert.match(lines[3],/S 100\/40\/20/);for(const line of lines)assert.ok(cells(line)<=cols);assert.doesNotMatch(lines.join('\n'),/\$/);}
 assert.match(cli.show({base:f.base,sessionId:'self',cols:120}),/account.*7d\+2pp/);
 assert.match(cli.show({base:f.base,sessionId:'self',cols:120}),/5 hours.*not provided/);
});
test('provided USD remains engine-estimated and displayed only after measured token fields',()=>{
 const m={cp:20,tokens:100,window:1000,limits:[],turn:{input:100,read:40,out:20,requests:1},tokenTotals:{input:100,cache:40,output:20,total:120},provider:{kind:'provider-estimate',status:'available',sessionUsd:1.5,turnUsd:.2},current:'Work'};
 const line=renderRows(bandRows(m,200),200,false).split('\n')[3];assert.match(line,/T 100\/40\/20.*S 100\/40\/20/);assert.match(line,/engine est.*\$0.200.*\[\$1.500\]/);
});
