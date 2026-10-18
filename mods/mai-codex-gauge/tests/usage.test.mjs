import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {reduceRecord,readIncrement,newState} from '../src/usage.mjs';
const u={input_tokens:100,cached_input_tokens:60,cache_write_input_tokens:10,output_tokens:20,reasoning_output_tokens:8,total_tokens:120};
const rec=(cum=120,usage=u)=>({timestamp:'2026-10-09T00:00:01Z',type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{...usage,total_tokens:cum},last_token_usage:usage,model_context_window:258400}}});
test('replay, cumulative dedupe, turn model and reset epochs',()=>{
 let s=newState('own'); s=reduceRecord(s,{type:'turn_context',payload:{turn_id:'t1',model:'gpt-6.1-sol'}},0);
 s=reduceRecord(s,rec(),10); s=reduceRecord(s,rec(),20); assert.equal(s.requests,1); assert.equal(s.turns.t1.requests,1);
 s=reduceRecord(s,{type:'turn_context',payload:{turn_id:'t2',model:'unknown'}},30); s=reduceRecord(s,rec(240),40);
 assert.equal(s.requests,2); assert.equal(s.coverage,'complete'); assert.equal(s.turns.t2.estimatedCostUsd,null);
 s=reduceRecord(s,rec(120),50); assert.equal(s.epoch,1); assert.equal(s.requests,3);
 s=reduceRecord(s,rec(360),40); assert.equal(s.requests,3);
});
test('fork inherited records excluded and first cumulative gap is disclosed',()=>{
 let s=newState('child'); s=reduceRecord(s,{timestamp:'2026-10-09T00:00:00Z',type:'session_meta',payload:{id:'child',forked_from_id:'parent'}},0);
 s=reduceRecord(s,{...rec(),timestamp:'2026-10-08T00:00:00Z'},1); assert.equal(s.requests,0);
 s=reduceRecord(s,{type:'turn_context',payload:{model:'gpt-6.1-sol',turn_id:'new'}},2);
 s=reduceRecord(s,rec(12000),3); assert.equal(s.requests,1); assert.equal(s.inheritedTokens,11880);
 let p=reduceRecord(newState('x'),rec(12000),0); assert.equal(p.coverage,'partial'); assert.equal(p.gapTokens,11880);
});
test('JSONL partial tail and replaced/shrunk source do not silently skip',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-usage-')); const f=path.join(dir,'s.jsonl');
 fs.writeFileSync(f,'{"a":1}\n{"b":'); let x=readIncrement(f,null,10000,1000); assert.equal(x.records.length,1); assert.equal(x.cursor.offset,8); assert.equal(x.incomplete,true);
 fs.appendFileSync(f,'2}\n'); x=readIncrement(f,x.cursor,10000,1000); assert.equal(x.records[0].record.b,2); assert.equal(x.incomplete,false);
 fs.writeFileSync(f,'{}\n'); x=readIncrement(f,x.cursor,10000,1000); assert.equal(x.changed,true); assert.equal(x.records.length,0);
});
test('production reduction tracks tokens without making a new local cost estimate',()=>{
 let s=newState('own');s=reduceRecord(s,{type:'turn_context',payload:{turn_id:'one',model:'gpt-6.1-sol'}},0);s=reduceRecord(s,rec(),10);
 assert.equal(s.turns.one.total,120);assert.equal(s.turns.one.estimatedCostUsd,null);assert.equal(s.knownCostUsd,null);
});
test('runtime token observer operates with just the telemetry module',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-only-telemetry-')),file=path.join(dir,'usage.mjs');
 fs.copyFileSync(new URL('../src/usage.mjs',import.meta.url),file);
 const module=await import(pathToFileURL(file).href);const state=module.reduceRecord(module.newState('self'),rec(),0);
 assert.equal(state.requests,1);assert.equal(state.estimatedCostUsd,null);
});
test('oversized non-metric JSONL record cannot stall a full scan',()=>{
 const d=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-large-')),f=path.join(d,'s.jsonl');const large=[{type:'response_item',payload:{}},{type:'compacted',payload:{}},{type:'event_msg',payload:{type:'item_completed'}}].map(x=>({...x,payload:{...x.payload,text:'x'.repeat(50000)}}));fs.writeFileSync(f,large.map(x=>JSON.stringify(x)).join('\n')+'\n'+JSON.stringify(rec())+'\n');let c=null,last,all=[];
 for(let i=0;i<30;i++){last=readIncrement(f,c,10000,1000);c=last.cursor;all.push(...last.records);if(!last.incomplete)break;}
 assert.equal(last.incomplete,false);assert.equal(all.filter(x=>x.record.payload?.type==='token_count').length,1);
});
