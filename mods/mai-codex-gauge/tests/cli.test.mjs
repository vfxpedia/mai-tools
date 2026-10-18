import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {show,watch} from '../src/cli.mjs';import {saveSession,saveUnits} from '../src/store.mjs';
test('show reads without rewriting, missing data not zero; corrupt schema diagnosed',()=>{
 const b=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-show-'));saveSession(b,'self',{at:1,cwd:'X:/repo',doing:'Build gauge'});saveUnits(b,'self',{account:'codex:test',state:{last:null,turns:{},knownCostUsd:0,historyComplete:false}});
 const f=path.join(b,'units','self.json'),before=fs.readFileSync(f);const s=show({base:b,sessionId:'self',cols:80,now:1000});assert.match(s,/no data yet/);assert.match(s,/Build gauge/);assert.deepEqual(fs.readFileSync(f),before);
 fs.writeFileSync(f,'{"sessionId":"other","codex":{}}');assert.throws(()=>show({base:b,sessionId:'self',cols:80}));assert.throws(()=>show({base:b,sessionId:'../self',cols:80}));
});
test('TTY watch emits Claude colors while redirected watch emits no terminal escapes',async()=>{
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-watch-'));saveSession(base,'self',{at:1,cwd:'X:/repo',doing:'Build gauge'});
 for(const isTTY of [true,false]){let frame='';await watch({base,sessionId:'self',once:true,output:{isTTY,columns:80,write:s=>{frame+=s;}}});
  assert.equal(frame.split('context').length-1,1);assert.equal(frame.trim().split('\n').length,5);
  if(isTTY){assert.ok(frame.startsWith('\x1b[H\x1b[2J'));assert.match(frame,/\x1b\[38;2;153;204;255mBuild gauge/);}else assert.doesNotMatch(frame,/\x1b/);
 }
});
test('TTY refresh after resize clears the old frame rather than appending duplicate rows',async()=>{
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-refresh-'));saveSession(base,'self',{at:1,cwd:'X:/repo',doing:'A long current job to verify the narrow refresh'});
 const signal={aborted:false},frames=[],output={isTTY:true,columns:120,write:s=>{if(!s.startsWith('\x1b[H\x1b[2J'))return;frames.push(s);output.columns=40;if(frames.length===2)signal.aborted=true;}};
 await watch({base,sessionId:'self',output,signal});assert.equal(frames.length,2);
 for(const frame of frames){assert.ok(frame.startsWith('\x1b[H\x1b[2J'));assert.equal(frame.split('context').length-1,1);}
 assert.doesNotMatch(frames[1],/─/);
});
test('continuous TTY display isolates its screen and restores the shell after abort, never for redirected output',async()=>{
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-screen-'));saveSession(base,'self',{at:1,cwd:'X:/repo',doing:'Build gauge'});
 for(const isTTY of [true,false]){const signal={aborted:false},writes=[];await watch({base,sessionId:'self',signal,output:{isTTY,columns:80,write:s=>{writes.push(s);if(s.includes('context'))signal.aborted=true;}}});
  if(isTTY){assert.equal(writes[0],'\x1b[?1049h');assert.equal(writes.at(-1),'\x1b[0m\x1b[?1049l');assert.equal(writes.filter(s=>s.includes('context')).length,1);}else assert.doesNotMatch(writes.join(''),/\x1b/);
 }
});
test('stored API observation is displayed, foreign observation and local fallback are refused',()=>{
 const b=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-show-')),state={last:null,turns:{one:{requests:1,estimatedCostUsd:99}},knownCostUsd:123,historyComplete:true};
 saveUnits(b,'self',{account:'codex:test',state,provider:{threadId:'self',at:1000,status:'available',kind:'provider-estimate',usdMicros:1250000,sessionUsd:99}});
 const s=show({base:b,sessionId:'self',cols:100,now:1000});assert.match(s,/\$1.250/);assert.match(s,/API est/);assert.doesNotMatch(s,/\$99|\$123/);
 // Bypass the producer deliberately to test a forged file at the consumer boundary.
 fs.writeFileSync(path.join(b,'units','self.json'),JSON.stringify({sessionId:'self',codex:{account:'codex:test',state,provider:{threadId:'other',at:1000,status:'available',kind:'provider-estimate',usdMicros:1250000}}}));
 assert.match(show({base:b,sessionId:'self',cols:100,now:1000}),/API unavailable/);
});
