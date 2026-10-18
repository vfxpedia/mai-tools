import path from 'node:path';
import {safePath,validateId,atomicUpdate,readJson} from './store.mjs';

const events=new Set(['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt','PreCompact','PostCompact']);
const codes=new Set(['session_id_mismatch','gauge_config_missing','input_failed','configuration_failed','observation_failed','policy_failed']);
const errorCodes=new Set(['ENOENT','EACCES','EPERM','EIO','EBUSY','EEXIST','EINVAL','ENOTDIR']);
const reasons=new Set(['invalid transcript reference','transcript outside sessions','metadata exceeds read budget','transcript owner mismatch','unique own transcript not found','source changed, full scan required','account changed, verify alias before writing','gauge writer busy or external edit','session writer busy or external edit','checkpoint writer busy or external edit','invalid session schema','owner mismatch','invalid shared JSON schema','costlog account/schema mismatch','symlink/junction refused']);
const safeId=value=>{try{return validateId(value);}catch{return null;}};
function safeFailure(value){
 if(!value||!Number.isFinite(value.at)||value.at<0||!events.has(value.event)||!codes.has(value.code)||typeof value.codexHome!=='string')throw Error('invalid hook diagnostic');
 return {at:value.at,event:value.event,code:value.code,codexHome:value.codexHome,environmentSessionId:safeId(value.environmentSessionId),errorCode:errorCodes.has(value.errorCode)?value.errorCode:null,reason:reasons.has(value.reason)?value.reason:null};
}

// Failure evidence lives apart from sessions/units/costlog. A rejected input
// must never look like a successful lifecycle event or alter another session.
export function recordHookFailure({base,sessionId,event,code,codexHome,environmentSessionId,errorCode,reason}){
 validateId(sessionId);
 const entry=safeFailure({at:Date.now(),event,code,codexHome:path.resolve(codexHome),environmentSessionId,errorCode,reason});
 return atomicUpdate(safePath(base,'hook-diagnostics',`${sessionId}.json`),sessionId,old=>{
  if(old&&(old.schemaVersion!==1||!Array.isArray(old.failures)))throw Error('invalid hook diagnostic schema');
  const failures=(old?.failures??[]).map(safeFailure);
  return {sessionId,schemaVersion:1,failures:[...failures,entry].slice(-32)};
 });
}

export function readHookDiagnostics(base,sessionId){
 const empty={status:'none observed',latestFailure:null,recentFailures:[]};
 if(!sessionId)return empty;
 try{
  const data=readJson(safePath(base,'hook-diagnostics',`${validateId(sessionId)}.json`));
  if(!data)return empty;
  if(data.sessionId!==sessionId||data.schemaVersion!==1||!Array.isArray(data.failures))throw Error('invalid hook diagnostic schema');
  const failures=data.failures.slice(-32).map(safeFailure);
  return {status:'failure evidence recorded; not activation',latestFailure:failures.at(-1)??null,recentFailures:failures};
 }catch{return {status:'unreadable diagnostic evidence',latestFailure:null,recentFailures:[]};}
}
