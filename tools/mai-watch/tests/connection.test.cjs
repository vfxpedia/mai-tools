const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const file = path.join(__dirname, '../mai_watch/viewer-connection.js');
const flush = async () => { for (let i=0;i<30;i++) await Promise.resolve(); };
function env(fetcher) {
  let now=0, id=0; const jobs=new Map(), events={}, docEvents={};
  const button={disabled:false,textContent:'Reload page',addEventListener:(name,fn)=>button[name]=fn};
  const root={AbortController,Promise,Date:{now:()=>now},fetch:fetcher,
    setTimeout:(fn,ms)=>{jobs.set(++id,{at:now+ms,fn});return id},clearTimeout:n=>jobs.delete(n),
    document:{hidden:false,addEventListener:(n,fn)=>docEvents[n]=fn,getElementById:()=>button},
    addEventListener:(n,fn)=>events[n]=fn,location:{reload:()=>root.reloads++},reloads:0};
  root.window=root; root.globalThis=root;
  if(fs.existsSync(file))vm.runInNewContext(fs.readFileSync(file,'utf8'),root);
  const api=root.MaiWatchConnection||{};
  async function advance(ms){const until=now+ms;for(;;){let next=[...jobs].filter(([,j])=>j.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;now=next[1].at;jobs.delete(next[0]);next[1].fn();await flush()}now=until;await flush()}
  return {root,api,advance,events,docEvents,button,jobs};
}
function loop(e, options){assert.equal(typeof e.api.createLoop,'function','bounded reconnect loop is required');return e.api.createLoop(options)}
test('a stalled response body times out and the next request succeeds',async()=>{
  let calls=0;const values=[],errors=[];const e=env(()=>Promise.resolve({ok:true,json:()=>++calls===1?new Promise(()=>{}):Promise.resolve(7)}));
  const p=loop(e,{task:s=>e.api.read('live.json','json',s),onData:x=>values.push(x),onError:x=>errors.push(x.message),interval:()=>1000});
  p.start();await flush();await e.advance(6000);assert.equal(errors.length,1);assert.match(errors[0],/timed out/);
  await e.advance(3000);assert.deepEqual(values,[7]);p.stop();
});
test('requestNow does not overlap an in-flight request',async()=>{
  let done,calls=0;const e=env();const p=loop(e,{task:()=>{calls++;return new Promise(r=>done=r)},onData:()=>{},interval:()=>1000});
  p.start();p.requestNow();p.requestNow();await flush();assert.equal(calls,1);done(1);await flush();await e.advance(1000);assert.equal(calls,2);p.stop();
});
test('a response from before resume cannot replace current data',async()=>{
  let old,calls=0;const values=[];const e=env();const p=loop(e,{task:()=>++calls===1?new Promise(r=>old=r):Promise.resolve('new'),onData:v=>values.push(v),interval:()=>1000});
  p.start();await flush();p.requestNow(true);await flush();old('old');await flush();assert.deepEqual(values,['new']);p.stop();
});
test('resume event bursts make one immediate replacement, not duplicate loops',async()=>{
  let calls=0;const e=env();const p=loop(e,{task:()=>{calls++;return Promise.resolve(1)},onData:()=>{},interval:()=>1000});
  assert.equal(typeof e.api.bind,'function');e.api.bind(p);p.start();await flush();
  e.root.document.hidden=true;e.docEvents.visibilitychange();await e.advance(250);assert.equal(calls,1);
  e.root.document.hidden=false;e.docEvents.visibilitychange();e.events.pageshow();e.events.online();await e.advance(250);assert.equal(calls,2);
  await e.advance(1000);assert.equal(calls,3);p.stop();
});
test('HTTP failure is reported and recovers after retry',async()=>{
  let calls=0;const got=[],errors=[];const e=env(()=>Promise.resolve(++calls===1?{ok:false,status:503}:{ok:true,json:()=>Promise.resolve(4)}));
  const p=loop(e,{task:s=>e.api.read('live.json','json',s),onData:x=>got.push(x),onError:x=>errors.push(x.status),interval:()=>1000});
  p.start();await flush();assert.deepEqual(errors,[503]);await e.advance(3000);assert.deepEqual(got,[4]);p.stop();
});
test('fresh HTTP data does not make old measurements look live',()=>{
  const e=env();assert.equal(typeof e.api.freshness,'function');const f=e.api.freshness(10000,10000,0,1,null);
  assert.equal(f.kind,'stale');assert.equal(f.receivedAge,0);assert.equal(f.sampleAge,10);
});
test('age changes without a new response and errors remain disconnected',()=>{
  const e=env();assert.equal(typeof e.api.freshness,'function');assert.equal(e.api.freshness(2000,1000,1000,1,null).kind,'live');
  assert.equal(e.api.freshness(8000,1000,1000,1,null).kind,'stale');
  assert.equal(e.api.freshness(2000,1000,1000,1,'offline').kind,'disconnected');
  assert.equal(e.api.freshness(0,null,null,1,null).kind,'waiting');
  assert.equal(e.api.freshness(0,0,10000,1,null).kind,'unknown');
});
test('reload button prevents repeated activation and reloads the page',()=>{
  const e=env();assert.equal(typeof e.api.mountRefresh,'function');e.api.mountRefresh();e.button.click();e.button.click();
  assert.equal(e.root.reloads,1);assert.equal(e.button.disabled,true);assert.match(e.button.textContent,/Reloading/);
});
test('stopping a loop cancels its retries and prevents old data from rendering',async()=>{
  let done,calls=0;const values=[];const e=env();const p=loop(e,{task:()=>{calls++;return new Promise(r=>done=r)},onData:x=>values.push(x),interval:()=>1000});
  p.start();await flush();p.stop();done(5);await flush();await e.advance(100000);
  p.requestNow(true);assert.equal(calls,1);assert.deepEqual(values,[]);
});
test('a malformed JSON body is an error, not a successful receipt',async()=>{
  const got=[],errors=[];const e=env(()=>Promise.resolve({ok:true,json:()=>Promise.reject(new SyntaxError('invalid JSON'))}));
  const p=loop(e,{task:s=>e.api.read('live.json','json',s),onData:x=>got.push(x),onError:x=>errors.push(x.message),interval:()=>1000});
  p.start();await flush();assert.deepEqual(got,[]);assert.deepEqual(errors,['invalid JSON']);p.stop();
});
