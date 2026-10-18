import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {pathToFileURL} from 'node:url';
import {safePath,validateId,readJson,saveSession} from './store.mjs';
import {bandRows,renderRows,freshLimits,pace,recentRate} from './band.mjs';
import {normalizeProviderUsage,readProviderUsage} from './provider.mjs';
import {sessionTokens,tallyTokens} from './telemetry.mjs';
function ownQuota(c){
 const candidates=[c.provider?.rateLimits,c.state?.rate].filter(x=>x&&Number.isFinite(x.observedAt)&&x.observedAt<=Date.now()).sort((a,b)=>b.observedAt-a.observedAt);
 const valid=x=>x&&Number.isFinite(x.used_percent)&&x.used_percent>=0&&x.used_percent<=100&&Number.isSafeInteger(x.window_minutes)&&x.window_minutes>0&&Number.isFinite(x.resets_at);
 for(const sample of candidates)if([sample.primary,sample.secondary].some(valid))return {...sample,primary:valid(sample.primary)?sample.primary:null,secondary:valid(sample.secondary)?sample.secondary:null};
 return null;
}
export function metrics({base,sessionId}){
 validateId(sessionId);const units=readJson(safePath(base,'units',`${sessionId}.json`));if(units&&units.sessionId!==sessionId)throw Error('owner mismatch');
 const c=units?.codex??{},s=c.state??{},t=s.turnId?s.turns?.[s.turnId]:null,p=c.provider,valid=p?.threadId===sessionId&&p.status==='available'&&Number.isSafeInteger(p.usdMicros)&&p.usdMicros>=0;
 const delta=c.providerTurns?.[s.turnId],turnUsd=valid&&delta?.kind==='provider-estimate-delta'&&delta.turnId===s.turnId&&Number.isSafeInteger(delta.beforeUsdMicros)&&Number.isSafeInteger(delta.afterUsdMicros)&&delta.beforeUsdMicros>=0&&delta.afterUsdMicros>=delta.beforeUsdMicros?(delta.afterUsdMicros-delta.beforeUsdMicros)/1e6:null;
 const quota=ownQuota(c),windows=[quota?.primary,quota?.secondary].filter(Boolean);
 return {sessionId,source:'Codex token_count',session:{...sessionTokens(s),requests:s.requests??0,usd:valid?p.usdMicros/1e6:null},turn:{id:s.turnId??null,tokens:tallyTokens(t),requests:t?.requests??0,usd:turnUsd,quotaChange:c.quotaTurns?.[s.turnId]??null},quota:{scope:'account',observedAt:quota?.observedAt??null,fiveHours:windows.find(x=>x.window_minutes===300)??null,sevenDays:windows.find(x=>x.window_minutes===10080)??null},usdSource:valid?'engine estimate':null};
}
export function show({base,sessionId,cols=80,now=Date.now(),color=false}){
 validateId(sessionId);const session=readJson(safePath(base,'sessions',`${sessionId}.json`)),units=readJson(safePath(base,'units',`${sessionId}.json`));
 if(session&&session.id!==sessionId||units&&units.sessionId!==sessionId)throw Error('owner mismatch');
 const c=units?.codex??{},s=c.state??{},l=s.last,raw=readJson(safePath(base,'limits.json'))??{},samples=raw[c.account]??{};
 const quota=ownQuota(c),own=quota&&Number.isFinite(quota.observedAt)&&quota.observedAt<=now?[quota.primary,quota.secondary].filter(x=>x&&[300,10080].includes(x.window_minutes)&&Number.isFinite(x.used_percent)&&x.used_percent>=0&&x.used_percent<=100&&Number.isFinite(x.resets_at)).map(x=>({kind:x.window_minutes===300?'five_hour':'seven_day',percentUsed:x.used_percent,resetsAt:new Date(x.resets_at*1000).toISOString()})):[];
 const limits=freshLimits(own,samples,now).map(x=>({...x,name:x.kind==='five_hour'?'5 hours':x.kind==='seven_day'?'7 days':x.kind,pct:x.percentUsed,pace:pace(x,now,recentRate(samples[x.kind]??[],x.resetsAt,now,x.kind)),reset:resetDuration(Date.parse(x.resetsAt)-now)}));
 const turn=s.turnId?s.turns?.[s.turnId]??null:null;
 const providerRecord=c.provider,provider=providerRecord?.kind==='provider-estimate'&&Number.isFinite(providerRecord.at)&&providerRecord.at<=now?normalizeProviderUsage({threadUsage:{threadId:providerRecord.threadId,estimatedUsageUsdMicros:providerRecord.usdMicros,estimatedUsageCreditsMicros:providerRecord.creditsMicros,groups:providerRecord.groups}},sessionId,providerRecord.at):null;
 if(provider){provider.reason=providerRecord.reason;const evidence=c.providerTurns?.[s.turnId];if(provider.status==='available'&&evidence?.kind==='provider-estimate-delta'&&evidence.turnId===s.turnId&&Number.isSafeInteger(evidence.beforeUsdMicros)&&Number.isSafeInteger(evidence.afterUsdMicros)&&evidence.beforeUsdMicros>=0&&evidence.afterUsdMicros>=evidence.beforeUsdMicros)provider.turnUsd=(evidence.afterUsdMicros-evidence.beforeUsdMicros)/1e6;}
 const m={cp:l?.window&&Number.isFinite(l.usage.input_tokens)?Math.round(l.usage.input_tokens/l.window*100):null,tokens:l?.usage.input_tokens??null,window:l?.window??0,limits,turn,tokenTotals:sessionTokens(s).tokens,quotaChange:c.quotaTurns?.[s.turnId]??null,provider,requests:s.requests,current:session?.doing??'',job:session?.waiting??'',outside:session?.outside??0,diagnostic:Object.keys(c.pendingTurns??{}).length?'token log pending':c.diagnostic??(s.historyComplete===false?'partial history':'')};
 m.quotaMissing=quota||providerRecord?.quotaStatus==='received'?{'5 hours':'not provided','7 days':'not provided'}:null;
 return renderRows(bandRows(m,cols),cols,color);
}
function resetDuration(ms){if(!Number.isFinite(ms)||ms<=0)return '';const h=Math.floor(ms/3600000),m=Math.floor(ms%3600000/60000);return h>=24?`${Math.floor(h/24)}d${h%24}h`:h?`${h}h${m}m`:m?`${m}m`:`${Math.max(1,Math.floor(ms/1000))}s`;}
async function displayScreen(options,output,run){
 const alternate=output.isTTY&&!options.once,controller=new AbortController(),signal=options.signal??controller.signal;
 const interrupt=()=>controller.abort(),listen=alternate&&!options.signal&&output===process.stdout;
 if(alternate)output.write('\x1b[?1049h');if(listen)process.on('SIGINT',interrupt);
 try{return await run(signal);}finally{if(listen)process.off('SIGINT',interrupt);if(alternate)output.write('\x1b[0m\x1b[?1049l');}
}
export async function watch(options){let previous='';const output=options.output??process.stdout;return displayScreen(options,output,async signal=>{do{let text;try{text=show({...options,cols:options.cols??output.columns??80,now:Date.now(),color:!!output.isTTY});}catch{text='Gauge read failed; normal work is unaffected.';}if(text!==previous){output.write((output.isTTY?'\x1b[H\x1b[2J':'')+text+'\n');previous=text;}if(options.once)return;await new Promise(resolve=>setTimeout(resolve,1000));}while(!signal.aborted);});}
export async function live(options){
 const {observe}=await import('./hook.mjs'),output=options.output??process.stdout;let previous='',diagnostic='';
 return displayScreen(options,output,async signal=>{do{
  try{await observe({...options,full:false});diagnostic='';}catch{diagnostic='Observation unavailable; normal work continues.';}
  let text;try{text=show({...options,cols:options.cols??output.columns??80,now:Date.now(),color:!!output.isTTY});}catch{text='Gauge read failed; normal work continues.';}
  if(diagnostic)text+='\n'+diagnostic;
  if(text!==previous){output.write((output.isTTY?'\x1b[H\x1b[2J':'')+text+'\n');previous=text;}
  if(options.once)return;await new Promise(resolve=>setTimeout(resolve,2000));
 }while(!signal.aborted);});
}
export async function main(args=process.argv.slice(2)){
 const command=args.shift()??'show', opts={};for(let i=0;i<args.length;i++){const a=args[i];if(!a.startsWith('--'))throw Error('invalid argument');opts[a.slice(2)]=args[i+1]?.startsWith('--')||!args[i+1]?true:args[++i];}
 const base=opts.base??path.join(os.homedir(),'.mai'),sessionId=opts.session??process.env.CODEX_THREAD_ID;
 if(command==='api'){if(typeof opts.exe!=='string'||!path.isAbsolute(opts.exe))throw Error('absolute native executable required');if(!['proxy','stdio'].includes(opts.transport??'proxy'))throw Error('invalid transport');const args=['app-server',...(opts.transport==='stdio'?['--stdio']:['proxy']),...(opts.sock&&opts.transport!=='stdio'?['--sock',String(opts.sock)]:[])];const value=await readProviderUsage({executable:opts.exe,args,sessionId,timeoutMs:Number(opts.timeout??3000),includeLimits:true});let record=null;if(opts.record){const {saveProvider}=await import('./store.mjs');const saved=saveProvider(base,sessionId,opts.account,value);record={written:saved.written,reason:saved.reason};}return console.log(JSON.stringify(record?{...value,record}:value));}
 if(command==='watch')return watch({base,sessionId,cols:opts.cols?Number(opts.cols):undefined,once:!!opts.once});
 if(command==='live')return live({base,sessionId,codexHome:opts.home??process.env.CODEX_HOME,account:opts.account,cols:opts.cols?Number(opts.cols):undefined,once:!!opts.once});
 if(command==='show')return console.log(show({base,sessionId,cols:Number(opts.cols??process.stdout.columns??80)}));
 if(command==='metrics')return console.log(JSON.stringify(metrics({base,sessionId}),null,2));
 if(command==='status'){validateId(sessionId);saveSession(base,sessionId,{at:Date.now(),cwd:process.cwd(),...(opts.name?{name:opts.name,titled:true}:{}),...(opts.doing?{doing:opts.doing}:{}),...(opts.issues?{issues:opts.issues.split(',')}:{}),...(opts.next?{next:opts.next}:{}),...(opts.waiting!==undefined?{waiting:opts.waiting}:{}),handle:process.env.ORCA_TERMINAL_HANDLE??null});return console.log('Session status saved.');}
 if(command==='scan'||command==='observe'||command==='diagnose'){if(opts.rebuild!==undefined&&(command!=='scan'||!['true',true].includes(opts.rebuild)))throw Error('--rebuild true requires scan');const {observe}=await import('./hook.mjs');const result=await observe({base,sessionId,transcript:opts.transcript,codexHome:opts.home??process.env.CODEX_HOME,account:opts.account,full:command==='scan',rebuild:!!opts.rebuild});return console.log(JSON.stringify(result));}
 throw Error('commands: show, watch, live, status, scan, observe, diagnose, api');
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)main().catch(()=>{console.error('Gauge command failed. Run diagnose or inspect the private source state.');process.exitCode=1;});
