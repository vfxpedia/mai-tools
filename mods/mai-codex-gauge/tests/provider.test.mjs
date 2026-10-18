import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeProviderUsage, providerTurnDelta, readProviderUsage} from '../src/provider.mjs';

const response = (threadId='self', usd=1234567) => ({summary:{lifetimeTokens:null}, threadUsage:{threadId,estimatedUsageUsdMicros:usd,estimatedUsageCreditsMicros:2400000,groups:[{model:'changing-model',inputTokens:100,cachedInputTokens:60,netNewInputTokens:40,outputTokens:20,totalTokens:120,estimatedUsageCreditsMicros:2400000}]}});

test('provider USD is sourced from micros, never from local conversion',()=>{
 const value=normalizeProviderUsage(response(),'self',1000);
 assert.equal(value.sessionUsd,1.234567);assert.equal(value.kind,'provider-estimate');assert.equal(value.at,1000);
 assert.equal(value.groups[0].inputTokens,100);assert.equal(value.groups[0].costUsd,undefined);
 assert.equal(value.creditsMicros,2400000);
});
test('explicit zero is different from missing, unsafe or foreign provider cost',()=>{
 assert.equal(normalizeProviderUsage(response('self',0),'self',1000).sessionUsd,0);
 for(const usd of [null,undefined,'123',-1,NaN,Number.MAX_SAFE_INTEGER+1]){const raw=response();raw.threadUsage.estimatedUsageUsdMicros=usd;assert.equal(normalizeProviderUsage(raw,'self',1000).sessionUsd,null);}
 assert.equal(normalizeProviderUsage({summary:{},threadUsage:null},'self',1000).sessionUsd,null);
 assert.equal(normalizeProviderUsage(response('other'),'self',1000).sessionUsd,null);
 assert.throws(()=>normalizeProviderUsage(response(),'../escape',1000));
});
test('only verified exclusive turn boundaries permit a provider delta',()=>{
 const before=normalizeProviderUsage(response('self',1000000),'self',1000),after=normalizeProviderUsage(response('self',1250000),'self',2000);
 const boundary={threadId:'self',turnId:'one',startedAt:1100,endedAt:1900,exclusive:true};
 assert.equal(providerTurnDelta(before,after,boundary).turnUsd,.25);
 for(const patch of [{exclusive:false},{turnId:null},{threadId:'other'},{startedAt:900},{endedAt:2100}])assert.equal(providerTurnDelta(before,after,{...boundary,...patch}).turnUsd,null);
 assert.equal(providerTurnDelta(null,after,boundary).turnUsd,null);
 assert.equal(providerTurnDelta(before,normalizeProviderUsage(response('self',900000),'self',2000),boundary).turnUsd,null);
 assert.equal(providerTurnDelta(before,normalizeProviderUsage(response('self',null),'self',2000),boundary).turnUsd,null);
 assert.equal(providerTurnDelta({...before,at:undefined},after,boundary).turnUsd,null);
 assert.equal(providerTurnDelta(before,{...after,at:NaN},boundary).turnUsd,null);
});

// A real subprocess handles the wire protocol. No OpenAI auth, account files or model calls.
function server(mode){
 return String.raw`let b='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>{b+=s;let n;while((n=b.indexOf('\n'))>=0){const q=JSON.parse(b.slice(0,n));b=b.slice(n+1);if(q.method==='initialize'){process.stdout.write(JSON.stringify({id:q.id,result:{userAgent:'fixture'}})+'\n');}else if(q.method==='account/usage/read'){if(${JSON.stringify(mode)}==='timeout')continue;if(q.params.threadId!=='self'){process.stdout.write(JSON.stringify({id:q.id,error:{message:'wrong ID'}})+'\n');continue;}const result=${JSON.stringify(response())};const msg=${JSON.stringify(mode)}==='error'?{id:q.id,error:{message:'PRIVATE_ERROR_DO_NOT_LEAK'}}:{id:q.id,result};const line=JSON.stringify(msg)+'\n';process.stdout.write(line.slice(0,15));process.stdout.write(line.slice(15));}}});`;
}
test('read-only RPC handles chunked replies and asks only for its own thread',async()=>{
 const value=await readProviderUsage({executable:process.execPath,args:['-e',server('ok')],sessionId:'self',timeoutMs:2000});
 assert.equal(value.sessionUsd,1.234567);assert.equal(value.status,'available');
});
test('RPC failure or timeout returns unavailable without exposing server error',async()=>{
 for(const mode of ['error','timeout']){
  const value=await readProviderUsage({executable:process.execPath,args:['-e',server(mode)],sessionId:'self',timeoutMs:300});
  assert.equal(value.sessionUsd,null);assert.equal(value.status,'unavailable');assert.equal(JSON.stringify(value).includes('PRIVATE_ERROR'),false);assert.equal(value.reason,mode==='timeout'?'RPC timeout':'RPC usage unavailable');
 }
});
test('malformed scalar RPC reply is rejected without an unhandled exception',async()=>{
 const value=await readProviderUsage({executable:process.execPath,args:['-e',"process.stdin.once('data',()=>process.stdout.write('null\\n'));process.stdin.resume();"],sessionId:'self',timeoutMs:1000});
 assert.equal(value.status,'unavailable');assert.equal(value.reason,'RPC invalid response');
});
test('an unsolicited usage response cannot establish cost before initialization',async()=>{
 const code=`process.stdin.once('data',()=>process.stdout.write(JSON.stringify({id:2,result:${JSON.stringify(response())}})+'\\n'));process.stdin.resume();`;
 const value=await readProviderUsage({executable:process.execPath,args:['-e',code],sessionId:'self',timeoutMs:300});
 assert.equal(value.status,'unavailable');assert.equal(value.sessionUsd,null);
});

test('malformed native hook data cannot crash the observer or discard a valid cost sample',async()=>{
 const code=`let b='';process.stdin.on('data',s=>{b+=s;let n;while((n=b.indexOf('\\n'))>=0){const q=JSON.parse(b.slice(0,n));b=b.slice(n+1);if(q.id===1)process.stdout.write(JSON.stringify({id:1,result:{}})+'\\n');if(q.id===2)process.stdout.write(JSON.stringify({id:2,result:${JSON.stringify(response())}})+'\\n');if(q.id===4)process.stdout.write(JSON.stringify({id:4,result:{data:[null]}})+'\\n');}});`;
 const value=await readProviderUsage({executable:process.execPath,args:['-e',code],sessionId:'self',timeoutMs:1000,includeHooks:true});
 assert.equal(value.sessionUsd,1.234567);assert.equal(value.hooksStatus,'unavailable');assert.deepEqual(value.nativeHooks,[]);
});
