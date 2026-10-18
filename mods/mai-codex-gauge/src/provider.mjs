import path from 'node:path';
import {spawn} from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import {validateId,safePath,readJson,atomicUpdate,saveProvider,saveLimits,saveTurn} from './store.mjs';
import {isGaugeCommand} from './hook-command.mjs';

const micros = n => Number.isSafeInteger(n) && n >= 0;
const groupFields=['model','reasoningEffort','speed','inputTokens','cachedInputTokens','netNewInputTokens','outputTokens','totalTokens','estimatedUsageCreditsMicros'];
function unavailable(id,at,reason){return {threadId:id,at,status:'unavailable',kind:'provider-estimate',sessionUsd:null,usdMicros:null,turnUsd:null,creditsMicros:null,groups:[],reason};}

export function normalizeProviderUsage(response,sessionId,at=Date.now()){
 validateId(sessionId);if(!Number.isFinite(at)||at<0)throw Error('invalid observation time');
 const raw=response?.threadUsage;
 if(!raw||raw.threadId!==sessionId)return unavailable(sessionId,at,raw?'thread mismatch':'no thread billing route');
 if(!micros(raw.estimatedUsageUsdMicros))return unavailable(sessionId,at,'USD not provided');
 const groups=Array.isArray(raw.groups)?raw.groups.filter(x=>x&&typeof x==='object'&&!Array.isArray(x)).map(x=>Object.fromEntries(groupFields.filter(k=>['model','reasoningEffort','speed'].includes(k)?typeof x[k]==='string':micros(x[k])).map(k=>[k,x[k]]))):[];
 return {threadId:sessionId,at,status:'available',kind:'provider-estimate',sessionUsd:raw.estimatedUsageUsdMicros/1e6,usdMicros:raw.estimatedUsageUsdMicros,turnUsd:null,creditsMicros:micros(raw.estimatedUsageCreditsMicros)?raw.estimatedUsageCreditsMicros:null,groups,reason:null};
}

export function providerTurnDelta(before,after,boundary){
 const empty={turnUsd:null,reason:'verified turn baseline unavailable'};
 if(!before||!after||!boundary?.exclusive||!boundary.turnId||before.status!=='available'||after.status!=='available')return empty;
 if(before.threadId!==boundary.threadId||after.threadId!==boundary.threadId||!micros(before.usdMicros)||!micros(after.usdMicros)||after.usdMicros<before.usdMicros)return empty;
 if(!Number.isFinite(before.at)||!Number.isFinite(after.at)||before.at<0||after.at<0||!Number.isFinite(boundary.startedAt)||!Number.isFinite(boundary.endedAt)||boundary.endedAt<boundary.startedAt||before.at>boundary.startedAt||after.at<boundary.endedAt||after.at<before.at)return empty;
 return {turnUsd:(after.usdMicros-before.usdMicros)/1e6,kind:'provider-estimate-delta',turnId:boundary.turnId,reason:null};
}

// These are rounded account-window readings. Parallel sessions can contribute.
// Never label their difference as this thread's exclusive consumption.
export function quotaTurnDelta(before,after){
 const result={scope:'account',source:'Codex account/rateLimits/read',beforeAt:before?.observedAt??null,afterAt:after?.observedAt??null,windows:{five_hour:null,seven_day:null}};
 if(!Number.isFinite(before?.observedAt)||!Number.isFinite(after?.observedAt)||before.observedAt<0||after.observedAt<before.observedAt)return result;
 for(const [name,minutes] of [['five_hour',300],['seven_day',10080]]){
  const a=[before.primary,before.secondary].find(x=>x?.window_minutes===minutes),b=[after.primary,after.secondary].find(x=>x?.window_minutes===minutes);
  if(!a||!b||![a.used_percent,b.used_percent].every(n=>Number.isFinite(n)&&n>=0&&n<=100)||!Number.isSafeInteger(a.resets_at)||a.resets_at!==b.resets_at||b.used_percent<a.used_percent)continue;
  result.windows[name]={beforePercent:a.used_percent,afterPercent:b.used_percent,deltaPercentagePoints:b.used_percent-a.used_percent,resetsAt:b.resets_at};
 }
 return result;
}

// Discovery uses only owned runtime filenames, never credentials or another session's settings.
export function discoverProviderRpc(home){
 try{
  const sock=path.join(home,'app-server-control','app-server-control.sock'),releases=path.join(home,'packages','app-server-daemon','releases');
  // Windows AF_UNIX sockets report EACCES to Node's stat/existsSync even
  // while the native proxy can connect. Check the owned directory on Windows;
  // the bounded, read-only RPC connection proves socket availability.
  if(process.platform==='win32'?!fs.existsSync(path.dirname(sock)):!fs.existsSync(sock))return null;
  const versions=fs.readdirSync(releases).filter(x=>/^\d+\.\d+\.\d+-[\w-]+$/.test(x)).sort((a,b)=>b.localeCompare(a,undefined,{numeric:true}));
  for(const v of versions){const executable=path.join(releases,v,'bin',process.platform==='win32'?'codex.exe':'codex');if(fs.existsSync(executable))return {executable,args:['app-server','proxy','--sock',sock],timeoutMs:1200};}
 }catch{}return null;
}

export function persistProviderCost(base,sessionId,account,tally,cost){
 const saved=saveTurn(base,sessionId,account,{...tally,providerCost:cost});
 if(saved.written)atomicUpdate(safePath(base,'units',`${validateId(sessionId)}.json`),sessionId,old=>{
  if(old?.codex?.account!==account)throw Error('provider cost owner changed');
  const current=old.codex.providerTurns?.[tally.turn_id];
  if(!current||current.beforeUsdMicros!==cost.beforeUsdMicros||current.afterUsdMicros!==cost.afterUsdMicros||current.afterAt!==cost.afterAt)return null;
  return {...old,codex:{...old.codex,providerTurns:{...old.codex.providerTurns,[tally.turn_id]:{...current,costlogSaved:true}}}};
 });
 return saved;
}

export function persistQuotaChange(base,sessionId,account,tally,quotaChange){
 const saved=saveTurn(base,sessionId,account,{...tally,quotaChange});
 if(saved.written)atomicUpdate(safePath(base,'units',`${validateId(sessionId)}.json`),sessionId,old=>{
  if(old?.codex?.account!==account)throw Error('quota evidence owner changed');
  const current=old.codex.quotaTurns?.[tally.turn_id];
  if(!current||current.beforeAt!==quotaChange.beforeAt||current.afterAt!==quotaChange.afterAt||JSON.stringify(current.windows)!==JSON.stringify(quotaChange.windows))return null;
  return {...old,codex:{...old.codex,quotaTurns:{...old.codex.quotaTurns,[tally.turn_id]:{...current,costlogSaved:true}}}};
 });
 return saved;
}

export async function refreshProvider({base,sessionId,account,codexHome,event=null,freshRequest=false,providerReader=null,rpc=null,timeoutMs=undefined}){
 const file=safePath(base,'units',`${validateId(sessionId)}.json`),before=readJson(file)?.codex;
 if(!before||before.account!==account)throw Error('provider observer owner mismatch');
 const boundary=['UserPromptSubmit','Stop'].includes(event?.hook_event_name);
 if(!freshRequest&&!boundary)return null;
 const options=rpc??discoverProviderRpc(codexHome);if(!providerReader&&!options)return null;
 // Repeated polling does not query or sample account limits while a session is idle.
 const sample=await (providerReader?providerReader():readProviderUsage({...options,...(timeoutMs===undefined?{}:{timeoutMs:Math.round(Math.min(options.timeoutMs??1200,timeoutMs))}),sessionId,includeLimits:true}));
 saveProvider(base,sessionId,account,sample);
 if(freshRequest&&sample.rateLimits&&before.state?.last?.at!==null)saveLimits(base,account,{...sample.rateLimits,observedAt:before.state.last.at},true);
 const endedAt=Date.now(),turnId=event?.turn_id??null;let cost=null,quotaChange=null;
 const r=atomicUpdate(file,sessionId,old=>{
  if(old.codex.account!==account)throw Error('provider account changed');
  const c={...old.codex};
  if(event?.hook_event_name==='UserPromptSubmit'){
   // Captured before this native prompt hook returns to the engine. No companion polling baseline.
   c.providerTurnStart={sample,turnId,startedAt:endedAt,source:'native-UserPromptSubmit',consumed:false};
  }else if(event?.hook_event_name==='Stop'){
   const start=c.providerTurnStart,valid=start&&!start.consumed&&start.source==='native-UserPromptSubmit'&&turnId&&start.turnId===turnId&&c.state?.turnId===turnId;
   const delta=providerTurnDelta(start?.sample,sample,{threadId:sessionId,turnId,startedAt:start?.startedAt,endedAt:sample.at,exclusive:!!valid});
   if(valid){c.providerTurnStart={...start,consumed:true};quotaChange=quotaTurnDelta(start.sample.rateLimits,sample.rateLimits);c.quotaTurns={...(c.quotaTurns??{}),[turnId]:quotaChange};if(delta.turnUsd!==null){cost={...delta,beforeUsdMicros:start.sample.usdMicros,afterUsdMicros:sample.usdMicros,beforeAt:start.sample.at,afterAt:sample.at};c.providerTurns={...(c.providerTurns??{}),[turnId]:cost};}}
   if(c.provider?.at===sample.at)c.provider={...c.provider,turnUsd:delta.turnUsd,turnId:delta.turnUsd!==null?turnId:null};
  }
  return {...old,codex:c};
 });
 if(quotaChange&&r.written){const tally=r.value.codex.state.turns[turnId];if(tally)persistQuotaChange(base,sessionId,account,tally,quotaChange);}
 if(cost&&r.written){const tally=r.value.codex.state.turns[turnId];if(tally){const saved=persistProviderCost(base,sessionId,account,tally,cost);if(!saved.written&&saved.reason!=='no change')throw Error('provider cost persistence pending');}}
 return sample;
}

// No auth file access, model requests, thread/resume, account refresh or raw error logging.
// Use the native executable's own authenticated read-only surface. EOF closes our client.
export function normalizeRateLimits(response,at=Date.now()){
 const limits=response?.rateLimits;
 if(!limits||typeof limits!=='object'||Array.isArray(limits)||limits.limitId&&limits.limitId!=='codex'||!Number.isFinite(at)||at<0||!Object.hasOwn(limits,'primary')||!Object.hasOwn(limits,'secondary'))return null;
 const valid=l=>l===null||l&&typeof l==='object'&&!Array.isArray(l)&&Number.isFinite(l.usedPercent)&&l.usedPercent>=0&&l.usedPercent<=100&&Number.isSafeInteger(l.windowDurationMins)&&l.windowDurationMins>0&&Number.isSafeInteger(l.resetsAt)&&l.resetsAt>=0&&l.resetsAt<=8640000000000;
 if(!valid(limits.primary)||!valid(limits.secondary))return null;
 const window=l=>l===null?null:{used_percent:l.usedPercent,window_minutes:l.windowDurationMins,resets_at:l.resetsAt};
 return {observedAt:at,primary:window(limits.primary),secondary:window(limits.secondary)};
}

export function clientFrame(payload,opcode=1){
 const data=Buffer.isBuffer(payload)?payload:Buffer.from(payload),len=data.length;
 if(len>1024*1024)throw Error('frame budget');
 const header=Buffer.alloc(len<126?2:len<65536?4:10);header[0]=128|opcode;header[1]=128|(len<126?len:len<65536?126:127);
 if(len>=65536)header.writeBigUInt64BE(BigInt(len),2);else if(len>=126)header.writeUInt16BE(len,2);
 const mask=crypto.randomBytes(4),masked=Buffer.from(data);for(let i=0;i<len;i++)masked[i]^=mask[i%4];
 return Buffer.concat([header,mask,masked]);
}
export function serverFrame(buffer){
 if(buffer.length<2)return null;if(buffer[0]&112||buffer[1]&128)throw Error('invalid server frame');
 let len=buffer[1]&127,off=2;if(len===126){if(buffer.length<4)return null;len=buffer.readUInt16BE(2);off=4;}else if(len===127){if(buffer.length<10)return null;const n=buffer.readBigUInt64BE(2);if(n>1048576n)throw Error('frame budget');len=Number(n);off=10;}
 if(len>1024*1024)throw Error('frame budget');if(buffer.length<off+len)return null;
 const opcode=buffer[0]&15,fin=!!(buffer[0]&128);if(opcode>=8&&(!fin||len>125))throw Error('invalid control frame');
 return {opcode,fin,payload:buffer.subarray(off,off+len),consumed:off+len};
}

export async function readProviderUsage({executable,args=['app-server','proxy'],sessionId,timeoutMs=3000,environment=process.env,transport=args.includes('proxy')?'websocket':'stdio',includeLimits=false,includeHooks=false}){
 validateId(sessionId);if(!path.isAbsolute(executable)||!Array.isArray(args)||!args.every(x=>typeof x==='string')||!Number.isSafeInteger(timeoutMs)||timeoutMs<50||timeoutMs>10000)throw Error('invalid RPC options');
 return new Promise(resolve=>{
  if(!['websocket','stdio'].includes(transport))throw Error('invalid transport');
  let child,finished=false,buffer=Buffer.alloc(0),timer,phase='initializing',upgraded=transport==='stdio',fragment=null,usage=null,quota=null,quotaStatus=includeLimits?'pending':'not-requested',hooksStatus=includeHooks?'pending':'not-requested',nativeHooks=[],hookDiagnostics=[];
  const key=crypto.randomBytes(16).toString('base64'),accept=crypto.createHash('sha1').update(key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  const finish=value=>{if(finished)return;finished=true;clearTimeout(timer);child?.stdin.end();child?.stdout.destroy();child?.stderr.destroy();child?.unref();resolve(value);};
  const fail=reason=>finish(unavailable(sessionId,Date.now(),reason));
  try{child=spawn(executable,args,{env:environment,stdio:['pipe','pipe','pipe'],windowsHide:true});}catch{return fail('RPC launch unavailable');}
  const send=q=>{if(!finished)child.stdin.write(transport==='websocket'?clientFrame(JSON.stringify(q)):JSON.stringify(q)+'\n');};
  const complete=()=>{if(usage&&quotaStatus!=='pending'&&hooksStatus!=='pending')finish({...usage,...(includeLimits?{quotaStatus,rateLimits:quota}: {}),...(includeHooks?{hooksStatus,nativeHooks,hookDiagnostics}: {})});};
  timer=setTimeout(()=>{if(usage){if(quotaStatus==='pending')quotaStatus='unavailable';if(hooksStatus==='pending')hooksStatus='unavailable';complete();}else fail('RPC timeout');},timeoutMs);
  child.on('error',()=>fail('RPC launch unavailable'));child.on('exit',()=>{if(!finished)fail('RPC closed before response');});child.stdin.on('error',()=>fail('RPC write unavailable'));
  child.stderr.resume();
  const message=msg=>{
   if(!msg||typeof msg!=='object'||Array.isArray(msg))return fail('RPC invalid response');
   if(msg.id===1&&phase==='initializing'){if(msg.error)return fail('RPC initialize refused');phase='reading';send({method:'initialized',params:{}});send({id:2,method:'account/usage/read',params:{threadId:sessionId}});if(includeLimits)send({id:3,method:'account/rateLimits/read',params:{}});if(includeHooks)send({id:4,method:'hooks/list',params:{cwds:[]}});}
   else if(msg.id===2&&phase==='reading'){usage=msg.error?unavailable(sessionId,Date.now(),'RPC usage unavailable'):normalizeProviderUsage(msg.result,sessionId);complete();}
   else if(msg.id===3&&phase==='reading'&&includeLimits){quota=msg.error?null:normalizeRateLimits(msg.result);quotaStatus=quota?'received':'unavailable';complete();}
   else if(msg.id===4&&phase==='reading'&&includeHooks){
    const data=msg.result?.data;
    hooksStatus=!msg.error&&Array.isArray(data)&&data.every(x=>x&&typeof x==='object'&&!Array.isArray(x)&&Array.isArray(x.hooks)&&Array.isArray(x.errors)&&Array.isArray(x.warnings))?'received':'unavailable';
    if(hooksStatus==='received')hookDiagnostics=data.map(x=>({hookCount:x.hooks?.length??0,errorCount:x.errors?.length??0,warningCount:x.warnings?.length??0}));
    if(hooksStatus==='received')nativeHooks=data.flatMap(x=>Array.isArray(x.hooks)?x.hooks:[]).filter(h=>h?.pluginId==='mai-codex-gauge@mai-codex-local'||isGaugeCommand(h?.command)).map(h=>({event:h.eventName,pluginId:h.pluginId??null,enabled:h.enabled===true,trustStatus:['trusted','untrusted','modified','managed'].includes(h.trustStatus)?h.trustStatus:'unknown',sourcePath:h.sourcePath}));
    complete();
   }
  };
  const parse=bytes=>{let msg;try{msg=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return fail('RPC invalid response');}message(msg);};
  const initialize=()=>send({id:1,method:'initialize',params:{clientInfo:{name:'mai_codex_gauge',version:'0.2.2'},capabilities:{experimentalApi:true}}});
  child.stdout.on('data',part=>{
   if(finished)return;buffer=Buffer.concat([buffer,part]);if(buffer.length>1024*1024)return fail('RPC response exceeds budget');
   if(!upgraded){const n=buffer.indexOf('\r\n\r\n');if(n<0){if(buffer.length>16384)fail('RPC WebSocket upgrade refused');return;}const header=buffer.subarray(0,n).toString('ascii'),fields=header.split('\r\n').slice(1).map(x=>x.split(/:\s*/,2));const headers=Object.fromEntries(fields.map(([k,v])=>[k.toLowerCase(),v]));if(!/^HTTP\/1\.[01] 101(?: |$)/.test(header)||headers['sec-websocket-accept']!==accept||headers.upgrade?.toLowerCase()!=='websocket'||!headers.connection?.toLowerCase().split(/\s*,\s*/).includes('upgrade'))return fail('RPC WebSocket upgrade refused');buffer=buffer.subarray(n+4);upgraded=true;initialize();}
   if(transport==='stdio'){let n;while(!finished&&(n=buffer.indexOf(10))>=0){const line=buffer.subarray(0,n);buffer=buffer.subarray(n+1);if(line.toString().trim())parse(line);}return;}
   try{let frame;while(!finished&&(frame=serverFrame(buffer))){buffer=buffer.subarray(frame.consumed);if(frame.opcode===8)return fail('RPC closed before response');if(frame.opcode===9){child.stdin.write(clientFrame(frame.payload,10));continue;}if(frame.opcode===10)continue;if(frame.opcode===1){if(fragment)throw Error('overlap');fragment=frame.payload;}else if(frame.opcode===0&&fragment)fragment=Buffer.concat([fragment,frame.payload]);else throw Error('unsupported frame');if(fragment.length>1024*1024)throw Error('budget');if(frame.fin){const data=fragment;fragment=null;parse(data);}}}catch{fail('RPC invalid WebSocket frame');}
  });
  if(transport==='websocket')child.stdin.write(`GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ${key}\r\n\r\n`);else initialize();
 });
}
