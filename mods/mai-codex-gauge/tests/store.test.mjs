import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawn,spawnSync} from 'node:child_process';
import {atomicUpdate,saveSession,saveTurn,saveLimits,safePath,saveProvider,saveUnits} from '../src/store.mjs';
const temp=()=>fs.mkdtempSync(path.join(os.tmpdir(),'gauge-store-'));
const e={at:1000,cwd:'X:/repo',name:'automatic',handle:null};
test('turn without ID remains unique and midnight cannot double-count a turn',()=>{
 const b=temp(),at=Date.UTC(2026,9,9,23,59),t={turn_id:'one',startedAt:at,at,requests:1,total:120,estimatedCostUsd:1,coverage:'complete'};
 saveTurn(b,'self','codex:test',t);saveTurn(b,'self','codex:test',{...t,at:at+120000,requests:2});
 const days=fs.readdirSync(path.join(b,'costlog'));assert.equal(days.length,1);
 saveTurn(b,'self','codex:test',{...t,turn_id:null,key:'request:0:120'});saveTurn(b,'self','codex:test',{...t,turn_id:null,key:'request:0:240'});
 const events=JSON.parse(fs.readFileSync(path.join(b,'costlog',days[0],'self.json'))).events;assert.equal(events.length,3);assert.equal(events.find(x=>x.turn_id==='one').requests,2);
});
test('own file, title, startedAt and event ordering',()=>{
 const b=temp();fs.mkdirSync(path.join(b,'sessions'));const other=path.join(b,'sessions','claude.json');fs.writeFileSync(other,'{"id":"claude"}');const before=fs.readFileSync(other);
 saveSession(b,'self',e);let f=path.join(b,'sessions','self.json'),s=JSON.parse(fs.readFileSync(f));s.name='Human title';s.titled=true;fs.writeFileSync(f,JSON.stringify(s));
 saveSession(b,'self',{...e,at:2000});s=JSON.parse(fs.readFileSync(f));assert.equal(s.name,'Human title');assert.equal(s.startedAt,1000);
 saveSession(b,'self',{...e,at:500,doing:'old'});assert.equal(JSON.parse(fs.readFileSync(f)).updatedAt,2000);assert.deepEqual(fs.readFileSync(other),before);
 assert.throws(()=>saveSession(b,'../escape',e));fs.writeFileSync(f,'{"id":"other"}');assert.throws(()=>saveSession(b,'self',e));
});
test('a terminated lock owner is recovered without losing its evidence or the complete JSON',()=>{
 const b=temp(),f=path.join(b,'self.json'),lock=`${f}.gauge-lock`;
 fs.writeFileSync(f,JSON.stringify({id:'self',value:1}));
 const exited=spawnSync(process.execPath,['-e','process.exit(0)']);assert.equal(exited.status,0);
 const abandoned={pid:exited.pid,host:os.hostname(),nonce:'known-dead-owner',at:Date.now()};
 fs.writeFileSync(lock,JSON.stringify(abandoned));
 const result=atomicUpdate(f,'self',old=>({...old,value:2}));
 assert.equal(result.written,true);assert.equal(JSON.parse(fs.readFileSync(f)).value,2);
 assert.equal(fs.existsSync(lock),false);
 const evidence=fs.readdirSync(b).filter(x=>x.startsWith('self.json.gauge-lock.abandoned-'));
 assert.equal(evidence.length,1);assert.deepEqual(JSON.parse(fs.readFileSync(path.join(b,evidence[0]))),abandoned);
});
test('live, foreign-host and unowned legacy locks are never stolen; session writes report contention',()=>{
 for(const owner of ['',JSON.stringify({pid:process.pid,host:os.hostname(),nonce:'live',at:1}),JSON.stringify({pid:123,host:'foreign-host',nonce:'foreign',at:1})]){
  const b=temp();saveSession(b,'self',e);const f=path.join(b,'sessions','self.json'),lock=`${f}.gauge-lock`,before=fs.readFileSync(f);
  fs.writeFileSync(lock,owner);
  assert.throws(()=>saveSession(b,'self',{...e,at:2000}),/session writer busy or external edit/);
  assert.deepEqual(fs.readFileSync(f),before);assert.equal(fs.readFileSync(lock,'utf8'),owner);
 }
});
test('junction/symlink and owner mismatch denied',()=>{
 const b=temp(),o=temp();fs.symlinkSync(o,path.join(b,'sessions'),'junction');assert.throws(()=>safePath(b,'sessions','self.json'));
 const f=path.join(o,'self.json');fs.writeFileSync(f,'{"id":"other"}');assert.throws(()=>atomicUpdate(f,'self',x=>x));
});
test('idle never writes, account distinct, windows not swapped, concurrent samples retained',async()=>{
 const b=temp(),f=path.join(b,'limits.json');fs.writeFileSync(f,JSON.stringify({default:{five_hour:[{at:1,pct:20,reset:'r'}]}}));const before=fs.readFileSync(f);
 const ob={observedAt:1000,primary:{used_percent:7,window_minutes:10080,resets_at:2000},secondary:null};
 assert.equal(saveLimits(b,'codex:test',ob,false).written,false);assert.deepEqual(fs.readFileSync(f),before);
 await Promise.all([Promise.resolve().then(()=>saveLimits(b,'codex:test',ob,true)),Promise.resolve().then(()=>saveLimits(b,'codex:test',{...ob,observedAt:1100,primary:{...ob.primary,used_percent:8}},true))]);
 const j=JSON.parse(fs.readFileSync(f));assert.equal(j.default.five_hour.length,1);assert.equal(j['codex:test'].seven_day.length,2);assert.equal(j['codex:test'].five_hour,undefined);assert.equal(j.accounts,undefined);
 const bytes=fs.readFileSync(f);saveLimits(b,'codex:test',{...ob,observedAt:900},true);assert.deepEqual(fs.readFileSync(f),bytes);
});
test('failed write leaves complete JSON; turn replaces and actual cost remains null',()=>{
 const b=temp(),f=path.join(b,'self.json');fs.writeFileSync(f,'{"id":"self","v":1}');assert.throws(()=>atomicUpdate(f,'self',()=>{throw Error('disk failure');}));assert.equal(JSON.parse(fs.readFileSync(f)).v,1);
 const t={turn_id:'t',at:Date.UTC(2026,9,9),requests:1,total:120,estimatedCostUsd:.000291,coverage:'complete'};saveTurn(b,'self','codex:test',t);saveTurn(b,'self','codex:test',{...t,requests:2});
 const c=JSON.parse(fs.readFileSync(path.join(b,'costlog','2026-10-09','self.json')));assert.equal(c.events.length,1);assert.equal(c.events[0].costUsd,null);assert.equal(c.events[0].requests,2);assert.equal(c.events.reduce((a,x)=>a+(typeof x.costUsd==='number'?x.costUsd:0),0),0);
});
test('two real processes preserve independent account samples',async()=>{
 const b=temp(),module=new URL('../src/store.mjs',import.meta.url).href;
 const code=`import {saveLimits} from ${JSON.stringify(module)};const r=saveLimits(process.argv[1],process.argv[2],{observedAt:1000,primary:{used_percent:7,window_minutes:10080,resets_at:2000000000}},true);if(!r.written)process.exitCode=1;`;
 await Promise.all(['codex:a','codex:b'].map(account=>new Promise((resolve,reject)=>{const child=spawn(process.execPath,['--input-type=module','-e',code,b,account],{stdio:'ignore'});child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(Error('child writer failed')));})));const j=JSON.parse(fs.readFileSync(path.join(b,'limits.json')));assert.equal(j['codex:a'].seven_day.length,1);assert.equal(j['codex:b'].seven_day.length,1);
});
test('provider writes preserve units, refuse foreign account and never regress the sample',()=>{
 const b=temp();saveUnits(b,'self',{account:'codex:test',state:{requests:3},events:[{at:1}]});
 const value={threadId:'self',at:2000,kind:'provider-estimate',status:'available',usdMicros:1250000,sessionUsd:1.25,turnUsd:null,groups:[],reason:null};
 assert.equal(saveProvider(b,'self','codex:test',value).written,true);const f=path.join(b,'units','self.json');const bytes=fs.readFileSync(f);const j=JSON.parse(bytes);assert.equal(j.codex.state.requests,3);assert.equal(j.codex.provider.sessionUsd,1.25);
 assert.equal(saveProvider(b,'self','codex:test',{...value,at:1000}).written,false);assert.deepEqual(fs.readFileSync(f),bytes);
 assert.throws(()=>saveProvider(b,'self','codex:other',value));assert.throws(()=>saveProvider(b,'self','codex:test',{...value,threadId:'other'}));assert.deepEqual(fs.readFileSync(f),bytes);
 saveUnits(b,'self',{account:'codex:test',state:{requests:4},provider:{...value,at:1000}});
 const updated=JSON.parse(fs.readFileSync(f));assert.equal(updated.codex.state.requests,4);assert.equal(updated.codex.provider.at,2000);
 assert.throws(()=>saveProvider(b,'self','codex:test',{...value,at:3000,usdMicros:-1}));
 assert.equal(saveProvider(b,'self','codex:test',{...value,at:3000,usdMicros:0,sessionUsd:999}).value.codex.provider.sessionUsd,0);
 assert.throws(()=>saveUnits(b,'self',{account:'codex:other'}));
});

test('store below a linked system folder works; a link at or inside the store is still refused',()=>{
 const real=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-link-real-')),above=path.join(os.tmpdir(),'gauge-link-above-'+process.pid+'-'+Date.now());
 fs.symlinkSync(real,above,process.platform==='win32'?'junction':'dir');
 const store=path.join(above,'store');fs.mkdirSync(store);
 assert.equal(safePath(store,'sessions','a.json'),path.resolve(store,'sessions','a.json'));
 const outside=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-link-out-'));
 fs.symlinkSync(outside,path.join(store,'sessions'),process.platform==='win32'?'junction':'dir');
 assert.throws(()=>safePath(store,'sessions','a.json'),/symlink\/junction refused/);
 const linkedStore=path.join(os.tmpdir(),'gauge-link-store-'+process.pid+'-'+Date.now());
 fs.symlinkSync(real,linkedStore,process.platform==='win32'?'junction':'dir');
 assert.throws(()=>safePath(linkedStore,'sessions','a.json'),/symlink\/junction refused/);
});
