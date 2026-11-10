import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
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
    screen.limited===true||screen.draft||!Array.isArray(screen.tail)||!screen.tail.every(line=>typeof line==='string')||
    screen.tailRows?.some(row=>row.wrapped))return false;
 const lines=screen.tail.filter(line=>line.trim());
 if(lines.length!==1)return false;
 const prompt=/^[\w.-]+@[\w.-]+:(.+)\$[ \t]*$/.exec(lines[0]);
 const cwd=pane.worktreePath,home=os.homedir();
 return Boolean(prompt&&(prompt[1]===cwd||cwd===home&&prompt[1]==='~'||cwd.startsWith(home+'/')&&prompt[1]==='~'+cwd.slice(home.length)));
}
export async function reconcileOrca({base,home,account,entry,node=process.execPath,run}){
 if(![entry,node,base].every(p=>typeof p==='string'&&path.isAbsolute(p)))throw Error('invalid Orca gauge launcher');
 const layout=await run(['terminal','list','--include-visual-layouts','--json']);
 const sessions=[],attached=[],restored=[],titleFailures=[];
 if(layout?.truncated!==false||!Array.isArray(layout.terminals)||!Array.isArray(layout.visualLayouts))throw Error('complete Orca topology unavailable');
 const allTabs=layout.visualLayouts.flatMap(x=>groupTabs(x.root)),seen=new Set();
 for(const registration of readOrcaRegistrations({base,home,account})){
  const {sessionId,paneKey,handle}=registration;
  if(seen.has(paneKey))continue;
  const [tabId,leafId]=paneKey.split(':');
  const row=layout.terminals.find(x=>x.handle===handle&&x.tabId===tabId&&x.leafId===leafId&&x.agentIdentity==='codex'&&x.connected===true);
  if(!row)continue;
  const tab=allTabs.find(x=>x.tabId===tabId),handles=paneHandles(tab?.panes);
  if(!handles.includes(handle))continue;
  seen.add(paneKey);sessions.push(sessionId);
  const title=titleFor(sessionId),command=`${quote(node)} ${quote(entry)} watch --session ${validateId(sessionId)} --base ${quote(base)}`;
  if(handles.length!==1){
   // A reconnecting or unrelated pane is not authority to send shell input.
   const lower=tab.panes?.type==='pane-split'&&tab.panes.direction==='horizontal'&&tab.panes.first?.type==='terminal'&&tab.panes.first.handle===handle&&tab.panes.second?.type==='terminal'?tab.panes.second.handle:null;
   if(!terminalFormat.test(lower??'')||lower===handle)continue;
   const pane=layout.terminals.find(x=>x.handle===lower&&x.tabId===tabId&&x.worktreeId===row.worktreeId&&x.paneTitle===title);
   if(!pane?.worktreeId||pane.connected!==true||pane.writable!==true||pane.orphaned===true||pane.agentIdentity!=null||pane.executionHostId!=='local'||
      typeof pane.worktreePath!=='string'||!path.isAbsolute(pane.worktreePath)||!/^[-\w]{1,128}$/.test(pane.incarnationId??''))continue;
   const attempt=`${pane.handle}:${pane.incarnationId}`;
   if(registration.restoreAttempt===attempt)continue;
   try{
    const screen=await run(['terminal','read','--terminal',lower,'--screen','--json']);
    if(!emptyShell(screen?.terminal,pane))continue;
    // Record before sending, so a timeout or service restart never repeats input.
    const claim=atomicUpdate(fileFor(base,sessionId),sessionId,old=>samePane(old,registration)&&old.restoreAttempt!==attempt?{...old,restoreAttempt:attempt}:null,{waitMs:40});
    if(!claim.written)continue;
    const receipt=await run(['terminal','send','--terminal',lower,'--text',command,'--enter','--json']);
    if(receipt?.send?.accepted===true&&receipt.send.handle===lower)restored.push(sessionId);
   }catch{/* The send may have arrived; never replay the claim. */}
   continue;
  }
  if(registration.attempted===handle)continue;
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
