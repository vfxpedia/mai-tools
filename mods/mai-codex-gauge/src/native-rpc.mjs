import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {clientFrame,serverFrame} from './provider.mjs';

// No general execution, authentication or model-request API is exposed here.
const allowed=new Set(['hooks/list','config/batchWrite']);
export async function nativeRpc(options,method,params){
 if(!allowed.has(method))throw Error('native RPC method not permitted');
 const {executable,args=[],environment=process.env,timeoutMs=5000,transport=args.includes('proxy')?'websocket':'stdio'}=options;
 if(!path.isAbsolute(executable)||!args.every(x=>typeof x==='string')||!['websocket','stdio'].includes(transport)||!Number.isSafeInteger(timeoutMs)||timeoutMs<50||timeoutMs>10000)throw Error('invalid native RPC options');
 return new Promise((resolve,reject)=>{
  let done=false,ready=transport==='stdio',buffer=Buffer.alloc(0),fragment=null,phase='initialize';
  const key=crypto.randomBytes(16).toString('base64'),accept=crypto.createHash('sha1').update(key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  const child=spawn(executable,args,{env:environment,stdio:['pipe','pipe','pipe'],windowsHide:true});
  const finish=(error,result)=>{if(done)return;done=true;clearTimeout(timer);child.stdin.end();child.stdout.destroy();child.stderr.destroy();child.unref();error?reject(Error(error)):resolve(result);};
  const timer=setTimeout(()=>finish('native RPC timeout'),timeoutMs);
  const send=q=>child.stdin.write(transport==='websocket'?clientFrame(JSON.stringify(q)):JSON.stringify(q)+'\n');
  const init=()=>send({id:1,method:'initialize',params:{clientInfo:{name:'mai_codex_mods_review',version:'0.2.2'},capabilities:{experimentalApi:true}}});
  const message=bytes=>{
   let msg;try{msg=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return finish('native RPC invalid response');}
   if(!msg||typeof msg!=='object'||Array.isArray(msg))return finish('native RPC invalid response');
   if(phase==='initialize'&&msg.id===1){if(msg.error)return finish('native RPC initialize refused');phase='request';send({method:'initialized',params:{}});send({id:2,method,params});}
   else if(phase==='request'&&msg.id===2){msg.error?finish('native RPC operation refused'):finish(null,msg.result);}
  };
  child.on('error',()=>finish('native RPC launch unavailable'));child.on('exit',()=>{if(!done)finish('native RPC closed before response');});child.stdin.on('error',()=>finish('native RPC write unavailable'));child.stderr.resume();
  child.stdout.on('data',part=>{
   if(done)return;buffer=Buffer.concat([buffer,part]);if(buffer.length>1048576)return finish('native RPC response exceeds budget');
   if(!ready){const n=buffer.indexOf('\r\n\r\n');if(n<0){if(buffer.length>16384)finish('native RPC upgrade refused');return;}
    const h=buffer.subarray(0,n).toString('ascii'),headers=Object.fromEntries(h.split('\r\n').slice(1).map(x=>{const i=x.indexOf(':');return [x.slice(0,i).toLowerCase(),x.slice(i+1).trim()];}));
    if(!/^HTTP\/1\.[01] 101(?: |$)/.test(h)||headers['sec-websocket-accept']!==accept||headers.upgrade?.toLowerCase()!=='websocket'||!headers.connection?.toLowerCase().split(/\s*,\s*/).includes('upgrade'))return finish('native RPC upgrade refused');
    buffer=buffer.subarray(n+4);ready=true;init();
   }
   if(transport==='stdio'){let n;while(!done&&(n=buffer.indexOf(10))>=0){const line=buffer.subarray(0,n);buffer=buffer.subarray(n+1);if(line.toString().trim())message(line);}return;}
   try{let f;while(!done&&(f=serverFrame(buffer))){buffer=buffer.subarray(f.consumed);if(f.opcode===8)return finish('native RPC closed before response');if(f.opcode===9){child.stdin.write(clientFrame(f.payload,10));continue;}if(f.opcode===10)continue;
    if(f.opcode===1){if(fragment)throw Error();fragment=f.payload;}else if(f.opcode===0&&fragment)fragment=Buffer.concat([fragment,f.payload]);else throw Error();
    if(fragment.length>1048576)throw Error();if(f.fin){const bytes=fragment;fragment=null;message(bytes);}
   }}catch{finish('native RPC invalid frame');}
  });
  if(transport==='stdio')init();else child.stdin.write(`GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ${key}\r\n\r\n`);
 });
}
