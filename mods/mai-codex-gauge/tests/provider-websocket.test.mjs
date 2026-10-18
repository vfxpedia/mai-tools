import test from 'node:test';import assert from 'node:assert/strict';
import {readProviderUsage,normalizeRateLimits} from '../src/provider.mjs';

function server(mode='ok'){
 return String.raw`const crypto=require('node:crypto');let b=Buffer.alloc(0),up=false;const mode=${JSON.stringify(mode)};
 const send=q=>{const p=Buffer.from(JSON.stringify(q)),h=Buffer.alloc(p.length<126?2:4);h[0]=129;if(p.length<126)h[1]=p.length;else{h[1]=126;h.writeUInt16BE(p.length,2);}process.stdout.write(Buffer.concat([h,p]));};
 process.stdin.on('data',s=>{b=Buffer.concat([b,s]);if(!up){const n=b.indexOf('\r\n\r\n');if(n<0)return;const key=/Sec-WebSocket-Key: ([^\r]+)/i.exec(b.subarray(0,n).toString())[1],accept=crypto.createHash('sha1').update(key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');process.stdout.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+(mode==='bad'?'INVALID':accept)+'\r\n\r\n');b=b.subarray(n+4);up=true;}
 while(b.length>=2){let len=b[1]&127,off=2;if(len===126){if(b.length<4)return;len=b.readUInt16BE(2);off=4;}if(!(b[1]&128))process.exitCode=2;if(b.length<off+4+len)return;const mask=b.subarray(off,off+4),p=Buffer.from(b.subarray(off+4,off+4+len));for(let i=0;i<len;i++)p[i]^=mask[i%4];b=b.subarray(off+4+len);const q=JSON.parse(p.toString());if(q.method==='initialize')send({id:q.id,result:{}});else if(q.method==='account/usage/read')send({id:q.id,result:{threadUsage:mode==='null'?null:{threadId:q.params.threadId,estimatedUsageUsdMicros:1234567,groups:[]}}});else if(q.method==='account/rateLimits/read')send({id:q.id,result:{rateLimits:{limitId:'codex',primary:{usedPercent:8,windowDurationMins:10080,resetsAt:2000000000},secondary:null}}});else if(q.method!=='initialized')process.exitCode=3;}});`;
}
test('managed WebSocket proxy validates Upgrade and reads both actual USD and quota',async()=>{
 const v=await readProviderUsage({executable:process.execPath,args:['-e',server()],transport:'websocket',includeLimits:true,sessionId:'self',timeoutMs:2000});
 assert.equal(v.sessionUsd,1.234567);assert.equal(v.rateLimits.primary.window_minutes,10080);assert.equal(v.rateLimits.primary.used_percent,8);assert.equal(v.rateLimits.secondary,null);assert.equal(v.quotaStatus,'received');
});
test('null thread billing stays null but does not discard valid limits or invent five hours',async()=>{
 const v=await readProviderUsage({executable:process.execPath,args:['-e',server('null')],transport:'websocket',includeLimits:true,sessionId:'self',timeoutMs:2000});
 assert.equal(v.sessionUsd,null);assert.equal(v.reason,'no thread billing route');assert.equal(v.rateLimits.primary.window_minutes,10080);assert.equal(v.rateLimits.secondary,null);
});
test('forged WebSocket Upgrade is rejected before sending account requests',async()=>{
 const v=await readProviderUsage({executable:process.execPath,args:['-e',server('bad')],transport:'websocket',includeLimits:true,sessionId:'self',timeoutMs:1000});
 assert.equal(v.status,'unavailable');assert.equal(v.reason,'RPC WebSocket upgrade refused');assert.equal(v.rateLimits,undefined);
});
test('malformed quota is unavailable, distinct from explicit null windows',()=>{
 for(const rateLimits of [[],{}, {primary:{usedPercent:'8',windowDurationMins:300,resetsAt:2000000000},secondary:null}, {primary:null,secondary:{usedPercent:8,windowDurationMins:300,resetsAt:-1}}, {primary:null,secondary:{usedPercent:8,windowDurationMins:300,resetsAt:Infinity}}])assert.equal(normalizeRateLimits({rateLimits}),null);
 const valid=normalizeRateLimits({rateLimits:{primary:null,secondary:null}},1000);
 assert.deepEqual(valid,{observedAt:1000,primary:null,secondary:null});
});
