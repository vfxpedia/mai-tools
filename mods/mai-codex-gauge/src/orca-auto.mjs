import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {atomicUpdate,readJson,safePath,validateId} from './store.mjs';

const keyFormat=/^[\w-]{1,128}:[\w-]{1,128}$/;
const terminalFormat=/^term_[\w-]{1,128}$/;
const accountFormat=/^codex:[\w-]+$/;
const bucket=(base)=>safePath(base,'orca-gauge');
const fileFor=(base,id)=>safePath(bucket(base),`${validateId(id)}.json`);
const samePane=(a,b)=>a?.paneKey===b.paneKey&&a?.handle===b.handle&&a?.home===b.home&&a?.account===b.account;
const titleFor=(id)=>`mai-codex-gauge ${validateId(id)}`;
const restoreFile=(base,attempt)=>safePath(base,'orca-gauge','restore-claims',`${createHash('sha256').update(attempt).digest('hex')}.json`);

export async function registerOrca({base,home,account,sessionId,paneKey,handle,transcript}){
 if(!keyFormat.test(paneKey??'')||!terminalFormat.test(handle??'')||!path.isAbsolute(home??'')||!accountFormat.test(account??''))return false;
 try{
  const {findTranscript,validateTranscript}=await import('./hook.mjs');
  transcript=transcript?validateTranscript(transcript,home,sessionId):findTranscript(home,sessionId);
  const entry={sessionId,paneKey,handle,home:path.resolve(home),account,transcript,at:Date.now()};
  const result=atomicUpdate(fileFor(base,sessionId),sessionId,old=>{
   if(samePane(old,entry))return {...old,at:entry.at};
   return old?.paneKey===paneKey&&old.home===entry.home&&old.account===account
    ?{...entry,restoreAttempt:old.restoreAttempt}:entry;
  },{waitMs:30});
  return result.written||result.reason==='no change';
 }catch{return false;}
}

export function readOrcaRegistrations({base,home,account}){
 let files;try{files=fs.readdirSync(bucket(base),{withFileTypes:true});}catch(error){if(error.code==='ENOENT')return [];throw error;}
 const entries=[];
 for(const f of files){
  if(!f.isFile()||!/^[\w-]+\.json$/.test(f.name))continue;
  try{
   const file=fileFor(base,f.name.slice(0,-5));if(fs.statSync(file).size>8192)continue;
   const r=readJson(file);
   if(r?.sessionId!==f.name.slice(0,-5)||r.home!==path.resolve(home)||r.account!==account||!keyFormat.test(r.paneKey)||!terminalFormat.test(r.handle)||!Number.isFinite(r.at))continue;
   entries.push(r);
  }catch{/* A malformed record never becomes a CLI command. */}
 }
 return entries.sort((a,b)=>b.at-a.at).slice(0,128);
}

const quote=(value)=>`'${value.replaceAll("'","'\\''")}'`;
function groupTabs(node){
 if(node?.type==='group')return node.tabs??[];
 return node?.type==='split'?[...groupTabs(node.first),...groupTabs(node.second)]:[];
}
function paneHandles(node){
 if(node?.type==='terminal')return [node.handle];
 return node?.type==='pane-split'?[...paneHandles(node.first),...paneHandles(node.second)]:[null];
}
function emptyShell(screen,pane){
 if(screen?.handle!==pane.handle||screen.status!=='running'||screen.source!=='screen'||screen.truncated!==false||
    screen.limited===true||screen.draft||!Array.isArray(screen.tail)||!screen.tail.every(line=>typeof line==='string'))return false;
 const last=screen.tail.findLastIndex(line=>line.trim());
 if(last<0||screen.tailRows?.[last]?.wrapped)return false;
 const prompt=/^[\w.-]+@[\w.-]+:(.+)\$[ \t]*$/.exec(screen.tail[last]);
 const cwd=pane.worktreePath,home=os.homedir();
 return Boolean(prompt&&(prompt[1]===cwd||cwd===home&&prompt[1]==='~'||cwd.startsWith(home+'/')&&prompt[1]==='~'+cwd.slice(home.length)));
}
export async function reconcileOrca({base,home,account,entry,node=process.execPath,run}){
 if(![entry,node,base].every(p=>typeof p==='string'&&path.isAbsolute(p)))throw Error('invalid Orca gauge launcher');
 const layout=await run(['terminal','list','--include-visual-layouts','--json']);
 const sessions=[],attached=[],restored=[],titleFailures=[];
 if(layout?.truncated!==false||!Array.isArray(layout.terminals)||!Array.isArray(layout.visualLayouts))throw Error('complete Orca topology unavailable');
 const allTabs=layout.visualLayouts.flatMap(x=>groupTabs(x.root)),bindings=new Map();
 const watch=(id)=>`${quote(node)} ${quote(entry)} watch --session ${validateId(id)} --base ${quote(base)}`;
 for(const registration of readOrcaRegistrations({base,home,account})){
  const {sessionId,paneKey,handle}=registration;
  if(bindings.has(paneKey))continue;
  const [tabId,leafId]=paneKey.split(':');
  const row=layout.terminals.find(x=>x.handle===handle&&x.tabId===tabId&&x.leafId===leafId&&x.agentIdentity==='codex'&&x.connected===true);
  if(!row)continue;
  const tab=allTabs.find(x=>x.tabId===tabId),handles=paneHandles(tab?.panes);
  if(!handles.includes(handle))continue;
  bindings.set(paneKey,registration);sessions.push(sessionId);
  if(handles.length!==1||registration.attempted===handle)continue;
  const title=titleFor(sessionId),command=watch(sessionId);
  const claim=atomicUpdate(fileFor(base,sessionId),sessionId,old=>{
   if(!samePane(old,registration)||old.attempted===handle)return null;
   return {...old,attempted:handle};
  },{waitMs:40});
  if(!claim.written)continue;
  try{
   const result=await run(['terminal','split','--terminal',handle,'--direction','horizontal','--command',command,'--json']);
   const companion=result?.split?.handle;
   if(terminalFormat.test(companion??'')&&companion!==handle&&result.split.tabId===tabId){
    attached.push(sessionId);
    try{
     const receipt=await run(['terminal','set-pane-title','--terminal',companion,'--title',title,'--json']);
     if(receipt?.paneTitle?.title!==title)titleFailures.push(sessionId);
    }catch{titleFailures.push(sessionId);}
   }
  }catch{/* A lost split response may still have created the pane. Never replay it. */}
 }
 // Orca restores the titled companion before a resumed Codex necessarily runs SessionStart.
 // The title can recover an existing split, never create one or assert hook registration.
 const registeredSessions=new Set(sessions);
 for(const {tabId,panes} of allTabs){
  if(panes?.type!=='pane-split'||panes.direction!=='horizontal'||panes.first?.type!=='terminal'||panes.second?.type!=='terminal')continue;
  const upper=panes.first.handle,lower=panes.second.handle;
  if(!terminalFormat.test(upper??'')||!terminalFormat.test(lower??'')||upper===lower)continue;
  const row=layout.terminals.find(x=>x.handle===upper&&x.tabId===tabId&&x.agentIdentity==='codex'&&x.connected===true&&x.executionHostId==='local'&&!x.orphaned);
  if(!row?.worktreeId||!keyFormat.test(`${tabId}:${row.leafId}`)||typeof row.leafId!=='string')continue;
  const pane=layout.terminals.find(x=>x.handle===lower&&x.tabId===tabId&&x.worktreeId===row.worktreeId);
  if(pane?.connected!==true||pane.writable!==true||pane.orphaned===true||pane.agentIdentity!=null||pane.executionHostId!=='local'||
     typeof pane.worktreePath!=='string'||!path.isAbsolute(pane.worktreePath)||!/^[-\w]{1,128}$/.test(pane.incarnationId??''))continue;
  const sessionId=/^mai-codex-gauge ([a-zA-Z0-9][a-zA-Z0-9_-]{0,127})$/.exec(pane.paneTitle??'')?.[1];
  if(!sessionId||pane.paneTitle!==titleFor(sessionId))continue;
  const binding=bindings.get(`${tabId}:${row.leafId}`);
  if(binding?binding.sessionId!==sessionId:registeredSessions.has(sessionId)||layout.terminals.filter(x=>x.paneTitle===pane.paneTitle).length!==1)continue;
  const attempt=`${lower}:${pane.incarnationId}`;
  if(binding?.restoreAttempt===attempt)continue; // Respect claims written by the previous release.
  try{
   const file=restoreFile(base,attempt),record={id:lower,sessionId,home:path.resolve(home),account};
   const previous=readJson(file);
   if(previous){
    if(!binding&&Object.keys(record).every(key=>previous[key]===record[key]))sessions.push(sessionId);
    continue;
   }
   const screen=await run(['terminal','read','--terminal',lower,'--screen','--json']);
   if(!emptyShell(screen?.terminal,pane))continue;
   if(!binding){
    const units=readJson(safePath(base,'units',`${sessionId}.json`));
    if(units&&(units.sessionId!==sessionId||units.codex?.account&&units.codex.account!==account))continue;
    const {findTranscript}=await import('./hook.mjs');findTranscript(home,sessionId);
   }
   // Both paths claim the same shell before sending. Never replay an ambiguous send.
   const claim=atomicUpdate(file,lower,old=>old?null:record,{waitMs:40});
   if(!claim.written)continue;
   if(!binding)sessions.push(sessionId);
   const receipt=await run(['terminal','send','--terminal',lower,'--text',watch(sessionId),'--enter','--json']);
   if(receipt?.send?.accepted===true&&receipt.send.handle===lower)restored.push(sessionId);
  }catch{/* Fail closed, or preserve the claim if the input may have arrived. */}
 }
 return {sessions,attached,restored,titleFailures};
}

const exec=promisify(execFile);
export function orcaRunner(executable){
 if(process.platform!=='linux'||!path.isAbsolute(executable)||path.basename(executable)==='orca'&&executable!==process.env.ORCA_CLI_COMMAND)throw Error('use the exact Linux Orca CLI or orca-ide');
 return async (args)=>{
  const {stdout}=await exec(executable,args,{timeout:4500,maxBuffer:2*1024*1024,windowsHide:true});
  const r=JSON.parse(stdout);
  if(r?.ok!==true)throw Error('Orca command refused');
  return r.result;
 };
}
