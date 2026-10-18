import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {pathToFileURL} from 'node:url';
import {newState,readIncrement,reduceRecord} from './usage.mjs';
import {validateId,safePath,atomicUpdate,readJson,saveSession,saveTurns,saveLimits,isEntry} from './store.mjs';
import {otherSessionsText,updateContextPolicy} from './context-policy.mjs';
import {refreshProvider} from './provider.mjs';
import {recordHookFailure} from './hook-diagnostics.mjs';
const events=new Set(['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt','PreCompact','PostCompact']);
export function validateTranscript(file,home,id){
 validateId(id);if(typeof file!=='string'||typeof home!=='string'||file.split(/[\\/]/).includes('..'))throw Error('invalid transcript reference');
 const root=path.resolve(home,'sessions'),target=path.resolve(file),relative=path.relative(root,target);if(relative.startsWith('..')||path.isAbsolute(relative))throw Error('transcript outside sessions');
 safePath(path.resolve(home),'sessions',...relative.split(/[\\/]/));const fd=fs.openSync(target,'r');
 try{const b=Buffer.alloc(Math.min(fs.fstatSync(fd).size,8*1024*1024));fs.readSync(fd,b,0,b.length,0);const end=b.indexOf(10);if(end<0)throw Error('metadata exceeds read budget');const meta=JSON.parse(b.subarray(0,end).toString('utf8'));if(meta.type!=='session_meta'||(meta.payload?.id??meta.payload?.session_id)!==id)throw Error('transcript owner mismatch');}finally{fs.closeSync(fd);}return target;
}
export function findTranscript(home,id){validateId(id);const root=safePath(path.resolve(home),'sessions');const found=[];function walk(p){for(const e of fs.readdirSync(p,{withFileTypes:true})){if(e.isSymbolicLink())continue;const f=path.join(p,e.name);if(e.isDirectory())walk(f);else if(e.name.endsWith(`${id}.jsonl`))found.push(f);}}walk(root);if(found.length!==1)throw Error('unique own transcript not found');return validateTranscript(found[0],home,id);}
const turnVersion=t=>`${t.at}:${t.requests}:${t.input}:${t.read}:${t.out}:${t.total}`;
export async function observe({base=path.join(os.homedir(),'.mai'),sessionId,transcript,codexHome=process.env.CODEX_HOME,account,full=false,rebuild=false,event=null,providerReader=null,rpc=null,budgetMs=full?20000:400,recordBudget=full?100000:400}){
 validateId(sessionId);if(!/^codex:[\w-]+$/.test(account??''))throw Error('verified local account alias required');
 if(!Number.isFinite(budgetMs)||budgetMs<1||budgetMs>20000||!Number.isSafeInteger(recordBudget)||recordBudget<1||recordBudget>100000)throw Error('invalid observation budget');
 const source=transcript?validateTranscript(transcript,codexHome,sessionId):findTranscript(codexHome,sessionId),file=safePath(base,'units',`${sessionId}.json`),began=performance.now();let fresh=false;
 const result=atomicUpdate(file,sessionId,old=>{
 if(old?.codex?.account&&old.codex.account!==account)throw Error('account changed, verify alias before writing');
 const previous=old?.codex??{},c={...previous,account,source};
 const reset=full&&(rebuild||!previous.fullScan?.pending||previous.source!==source);
 let state=reset?newState(sessionId):(previous.state??newState(sessionId)),cursor=reset?null:previous.cursor??null,processed=0;
 c.pendingTurns={...(previous.pendingTurns??{})};
 const originVerified=full||previous.state?.historyOriginVerified===true||previous.state?.historyComplete===true;
 if(previous.source&&previous.source!==source&&!full)throw Error('source changed, full scan required');
 do{
 const remaining=Math.max(1,budgetMs-(performance.now()-began)),chunk=readIncrement(source,cursor,1024*1024,Math.min(full?500:150,remaining/2),{maxRecords:recordBudget-processed,onRecord:(record,byteOffset)=>{
  state=reduceRecord(state,record,byteOffset,{mutate:true});if(state.freshRequest){fresh=true;const key=state.turnId??state.last.turnId??`request:${state.epoch}:${state.watermark}`;c.pendingTurns[key]=turnVersion(state.turns[key]);}
 }});processed+=chunk.count??0;if(chunk.changed){c.diagnostic='source replaced or shrunk; full scan required';state.historyComplete=false;state.historyOriginVerified=false;break;}
 const advance=chunk.cursor.offset-(cursor?.offset??0);cursor=chunk.cursor;
 state.historyOriginVerified=originVerified;state.historyComplete=!chunk.incomplete&&originVerified;
 if(!chunk.incomplete)c.diagnostic=null;
 if(!advance&&chunk.incomplete)c.diagnostic='record exceeds read budget or incomplete tail';
 if(!chunk.incomplete||!advance||!full)break;
 if(processed>=recordBudget||performance.now()-began>=budgetMs/2){c.diagnostic='full scan paused at cursor; run scan again';break;}
 }while(full);
 if(full||previous.fullScan?.pending)c.fullScan={pending:!state.historyComplete};
 c.state=state;c.cursor=cursor;c.observedAt=Date.now();c.lastEvent=event?.hook_event_name??'observe';
 if(event){c.events=[...(c.events??[]),{event:event.hook_event_name,at:Date.now(),turnId:event.turn_id??null,offset:cursor?.offset??null}].slice(-128);
 if(['PreCompact','PostCompact'].includes(event.hook_event_name)){const key=`${event.hook_event_name}:${event.turn_id??''}:${event.trigger??''}:${cursor?.offset??0}`;c.compacts??=[];if(!c.compacts.some(x=>x.key===key))c.compacts.push({key,event:event.hook_event_name,trigger:event.trigger??'unknown',at:Date.now(),source,offset:cursor?.offset??0,unitReference:file});c.compacts=c.compacts.slice(-100);}}
 return {...(old??{sessionId,units:[]}),codex:c};
 },{waitMs:Math.min(100,budgetMs)});if(!result.written)throw Error('gauge writer busy or external edit');
 const c=result.value.codex,s=c.state;
 // Mark dirty turns before advancing the durable cursor. Token-only failures
 // retry independently of the current turn, and one increment may contain
 // multiple completed turns. Batch a UTC day's writes, avoiding quadratic I/O.
 const batches=new Map(),acked={};
 for(const [key,tally] of Object.entries(s.turns)){
  const evidence=c.providerTurns?.[tally.turn_id],quota=c.quotaTurns?.[tally.turn_id];
  if(!Object.hasOwn(c.pendingTurns,key)&&(!evidence||evidence.costlogSaved)&&(!quota||quota.costlogSaved))continue;
  const date=new Date(tally.startedAt??tally.at).toISOString().slice(0,10);if(!batches.has(date))batches.set(date,[]);
  batches.get(date).push({...tally,...(quota?{quotaChange:quota}:{}),...(evidence?{providerCost:evidence}:{})});
 }
 for(const tallies of batches.values()){
  if(performance.now()-began>=budgetMs)break;
  const saved=saveTurns(base,sessionId,account,tallies,{waitMs:Math.min(100,Math.max(0,budgetMs-(performance.now()-began)))});
  if(saved.written||saved.reason==='no change')for(const tally of tallies)acked[tally.key]=turnVersion(tally);
 }
 if(Object.keys(acked).length)atomicUpdate(file,sessionId,old=>{
  if(old?.codex?.account!==account)throw Error('pending turn owner changed');const next={...old.codex,pendingTurns:{...old.codex.pendingTurns}};
  for(const [key,version] of Object.entries(acked))if(next.state.turns[key]&&turnVersion(next.state.turns[key])===version){delete next.pendingTurns[key];const id=next.state.turns[key].turn_id;
   if(c.providerTurns?.[id]&&JSON.stringify(next.providerTurns?.[id])===JSON.stringify(c.providerTurns[id]))next.providerTurns={...next.providerTurns,[id]:{...next.providerTurns[id],costlogSaved:true}};
   if(c.quotaTurns?.[id]&&JSON.stringify(next.quotaTurns?.[id])===JSON.stringify(c.quotaTurns[id]))next.quotaTurns={...next.quotaTurns,[id]:{...next.quotaTurns[id],costlogSaved:true}};
  }return {...old,codex:next};
 },{waitMs:Math.min(100,Math.max(0,budgetMs-(performance.now()-began)))});
 const pending=Object.keys(readJson(file)?.codex?.pendingTurns??{}).length;
 // Only new completed requests supply samples. Rate-only/idle events cannot refresh their age.
 if(fresh&&s.rate&&s.last?.at===s.rate.observedAt)saveLimits(base,account,s.rate,true);
 try{await refreshProvider({base,sessionId,account,codexHome,event,freshRequest:fresh,providerReader,rpc,timeoutMs:event?Math.max(50,Math.min(500,1100-(performance.now()-began))):undefined});}catch{/* Read-only telemetry failure must not stop work. */}
 return {requests:s.requests,knownCostUsd:s.knownCostUsd,estimatedCostUsd:s.estimatedCostUsd,historyComplete:s.historyComplete,coverage:s.coverage,cursor:c.cursor?.offset,elapsedMs:Math.round(performance.now()-began),pendingTurns:pending,diagnostic:pending?'token costlog persistence pending':c.diagnostic??null};
}
export async function handleHook(input,environment={}){
 let id=null,home,base,expected,stage='input';
 const fail=(code,error=null)=>{
  let saved=false;
  if(id)try{saved=recordHookFailure({base,sessionId:id,event:input.hook_event_name,code,codexHome:home,environmentSessionId:expected,errorCode:error?.code,reason:error?.message}).written;}catch{/* Diagnostics cannot stop normal work. */}
  if(!environment.quiet)process.stderr.write(`mai-codex-gauge: observation unavailable (${code}; diagnostic ${saved?'recorded':'unavailable'}); normal work continues.\n`);
  return {};
 };
 try{
 if(!input||!events.has(input.hook_event_name))return {};
 home=environment.codexHome??process.env.CODEX_HOME??path.join(os.homedir(),'.codex');base=environment.base??path.join(os.homedir(),'.mai');
 id=validateId(input.session_id);expected=environment.sessionId??process.env.CODEX_THREAD_ID;if(expected&&id!==expected)return fail('session_id_mismatch');
 stage='configuration';
 const cfg=environment.account?environment:readJson(safePath(home,'mai-codex-gauge.json'));if(!cfg?.account)return fail('gauge_config_missing');
 stage='observation';
 // Native hooks may point at a display/export transcript outside sessions.
 // Never open that reference as metric input. Find this session's owned rollout
 // instead; references inside sessions still undergo the strict owner check.
 const relative=typeof input.transcript_path==='string'?path.relative(path.resolve(home,'sessions'),path.resolve(input.transcript_path)):null;
 const rollout=relative!==null&&!relative.startsWith('..')&&!path.isAbsolute(relative)?input.transcript_path:findTranscript(home,id);
 await observe({base,sessionId:id,transcript:rollout,codexHome:home,account:cfg.account,event:input,providerReader:environment.providerReader,rpc:cfg.providerRpc});
 stage='policy';
 const at=Date.now(),session=saveSession(base,id,{at,cwd:input.cwd??'',handle:environment.handle??process.env.ORCA_TERMINAL_HANDLE??null});
 const policyOutput=updateContextPolicy(base,id,input,session,at);
 if(input.hook_event_name==='SessionStart'){
 const units=readJson(safePath(base,'units',`${id}.json`));const text=`[MAI Codex continuity]\nWork: ${session.doing||'not set'}\nIssues: ${session.issues.join(', ')||'not set'}\nNext: ${session.next||'not set'}\nWaiting: ${session.waiting||'none'}\nFull original: ${units.codex.source}\nRead position: ${units.codex.cursor?.offset??0}\nShared unit index: ${safePath(base,'units',`${id}.json`)}\nThe index is not a substitute for the original. Reopen evidence before deciding. Do not declare unfinished work complete.`;
 const reference=path.join(home,'mai-codex-gauge','skills','mai-codex-continuity','SKILL.md');
 return {hookSpecificOutput:{hookEventName:'SessionStart',additionalContext:text+'\nOperating command reference (read when a checkpoint is pending): '+reference+'\n'+(policyOutput.systemMessage??'')+'\n'+otherSessionsText(base,id,at)}};
 }return policyOutput;
 }catch(e){return fail(`${stage}_failed`,e);}
}
if(isEntry(import.meta.url)){let raw='',tooLarge=false;process.stdin.setEncoding('utf8');process.stdin.on('data',s=>{if(raw.length+s.length>1024*1024)tooLarge=true;else raw+=s;});process.stdin.on('end',async()=>{let input=null;try{if(!tooLarge)input=JSON.parse(raw);}catch{}const out=await handleHook(input);process.stdout.write(JSON.stringify(out)+'\n');});}
