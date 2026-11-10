import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as cli from '../src/cli.mjs';
import {saveUnits,readJson} from '../src/store.mjs';

const account='codex:local';
function fixture(t){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-sync-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const home=path.join(root,'codex'),base=path.join(root,'mai');
 fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 const rollout=(id,rows)=>fs.writeFileSync(path.join(home,'sessions',`rollout-${id}.jsonl`),[{type:'session_meta',payload:{id}},...rows].map(x=>JSON.stringify(x)).join('\n')+'\n');
 rollout('one',[]);rollout('two',[]);rollout('other',[]);
 return {home,base,rollout};
}
test('one native account read fills two idle gauges without writing quota history or inventing token usage',async t=>{
 const f=fixture(t),now=Date.now();let calls=0;
 const readQuota=async()=>{calls++;return {observedAt:now,primary:{used_percent:23,window_minutes:10080,resets_at:Math.floor(now/1000)+7200},secondary:null};};
 const result=await cli.syncGauge({...f,account,sessions:['one','two'],readQuota});
 assert.equal(calls,1);assert.equal(result.observed,2);assert.equal(result.quotaUpdated,2);
 for(const sessionId of ['one','two']){
  assert.match(cli.show({...f,sessionId,now:now+1,cols:100}),/7 days.*23%/);
  const m=cli.metrics({...f,sessionId});assert.equal(m.session.requests,0);assert.equal(m.quota.fiveHours,null);assert.equal(m.session.usd,null);
 }
 assert.equal(fs.existsSync(path.join(f.base,'limits.json')),false);
 assert.equal(fs.existsSync(path.join(f.base,'units','other.json')),false);
});
test('sync follows each owned rollout independently and refuses a different account',async t=>{
 const f=fixture(t),now=Date.now();
 saveUnits(f.base,'other',{account:'codex:foreign',provider:{at:1},state:{}});
 const file=path.join(f.base,'units','other.json'),before=fs.readFileSync(file);
 await cli.syncGauge({...f,account,sessions:['one','two']});
 f.rollout('one',[{type:'turn_context',payload:{model:'gpt-6.1-sol',turn_id:'turn1'}},{timestamp:new Date(now).toISOString(),type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{total_tokens:120},last_token_usage:{input_tokens:100,cached_input_tokens:40,output_tokens:20},model_context_window:200}}}]);
 const result=await cli.syncGauge({...f,account,sessions:['one','two','other']});
 assert.deepEqual(result.failed,['other']);
 assert.deepEqual(cli.metrics({...f,sessionId:'one'}).session.tokens,{input:100,cache:40,output:20,total:120});
 assert.equal(cli.metrics({...f,sessionId:'two'}).session.requests,0);
 assert.deepEqual(fs.readFileSync(file),before);
 const own=readJson(path.join(f.base,'units','one.json'));assert.equal((own.codex.events??[]).length,0);
});
test('stale native responses do not replace newer account data or thread billing evidence',async t=>{
 const f=fixture(t),now=Date.now(),file=path.join(f.base,'units','one.json');
 await cli.syncGauge({...f,account,sessions:['one']});
 const old=readJson(file).codex;
 saveUnits(f.base,'one',{...old,provider:{threadId:'one',kind:'provider-estimate',status:'available',usdMicros:123000,at:now-100}});
 const sample=(observedAt,used_percent)=>({observedAt,primary:{used_percent,window_minutes:10080,resets_at:Math.floor(now/1000)+7200},secondary:null});
 for(const r of [sample(now,31),sample(now-200,92)]){
  await cli.syncGauge({...f,account,sessions:['one'],readQuota:async()=>r});
 }
 const m=cli.metrics({...f,sessionId:'one'});
 assert.equal(m.session.usd,0.123);
 assert.equal(m.quota.sevenDays.used_percent,31);
 assert.equal(m.quota.observedAt,now);
});
