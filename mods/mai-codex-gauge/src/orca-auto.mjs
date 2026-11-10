import fs from 'node:fs';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {atomicUpdate,readJson,safePath,validateId} from './store.mjs';

const keyFormat=/^[\w-]{1,128}:[\w-]{1,128}$/;
const terminalFormat=/^term_[\w-]{1,128}$/;
const accountFormat=/^codex:[\w-]+$/;
const bucket=(base)=>safePath(base,'orca-gauge');
const fileFor=(base,id)=>safePath(bucket(base),`${validateId(id)}.json`);
const samePane=(a,b)=>a?.paneKey===b.paneKey&&a?.handle===b.handle&&a?.home===b.home&&a?.account===b.account;

export async function registerOrca({base,home,account,sessionId,paneKey,handle,transcript}){
 if(!keyFormat.test(paneKey??'')||!terminalFormat.test(handle??'')||!path.isAbsolute(home??'')||!accountFormat.test(account??''))return false;
 try{
  const {findTranscript,validateTranscript}=await import('./hook.mjs');
  transcript=transcript?validateTranscript(transcript,home,sessionId):findTranscript(home,sessionId);
  const entry={sessionId,paneKey,handle,home:path.resolve(home),account,transcript,at:Date.now()};
  const result=atomicUpdate(fileFor(base,sessionId),sessionId,old=>samePane(old,entry)?{...old,at:entry.at}:entry,{waitMs:30});
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
export async function reconcileOrca({base,home,account,entry,node=process.execPath,run}){
 if(![entry,node,base].every(p=>typeof p==='string'&&path.isAbsolute(p)))throw Error('invalid Orca gauge launcher');
 const layout=await run(['terminal','list','--include-visual-layouts','--json']);
 const sessions=[],attached=[];
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
  // Never split a tab already containing a companion or any unrelated pane.
  // A restored layout is authoritative even while its shell is reconnecting.
  if(handles.length!==1||registration.attempted===handle)continue;
  const claim=atomicUpdate(fileFor(base,sessionId),sessionId,old=>{
   if(!samePane(old,registration)||old.attempted===handle)return null;
   return {...old,attempted:handle};
  },{waitMs:40});
  if(!claim.written)continue;
  try{
   const command=`${quote(node)} ${quote(entry)} watch --session ${validateId(sessionId)} --base ${quote(base)}`;
   const result=await run(['terminal','split','--terminal',handle,'--direction','horizontal','--command',command,'--json']);
   if(terminalFormat.test(result?.split?.handle??'')&&result.split.tabId===tabId)attached.push(sessionId);
  }catch{/* A lost split response may still have created the pane. Never replay it. */}
 }
 return {sessions,attached};
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
