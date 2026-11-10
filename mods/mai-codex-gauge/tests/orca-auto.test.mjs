import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as auto from '../src/orca-auto.mjs';
import {handleHook} from '../src/hook.mjs';

const tabId='tab-a',leafId='leaf-a',handle='term_original',paneKey=`${tabId}:${leafId}`;
const primary={tabId,leafId,handle,agentIdentity:'codex',connected:true,worktreeId:'worktree-a',executionHostId:'local'};
const visible=(panes,terminals=[primary])=>({terminals,truncated:false,visualLayouts:[{root:{type:'group',tabs:[{tabId,panes}]}}]});
const term=(handle)=>({type:'terminal',handle});
function fixture(t){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-orca-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const home=path.join(root,'codex'),base=path.join(root,'mai');
 fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 fs.writeFileSync(path.join(home,'sessions','rollout-session-a.jsonl'),'{"type":"session_meta","payload":{"id":"session-a"}}\n');
 return {home,base,account:'codex:local',sessionId:'session-a',paneKey,handle,entry:path.join(root,'cli.mjs'),node:process.execPath};
}
test('SessionStart registration requires exact Orca identity and owned rollout',async t=>{
 const f=fixture(t);
 assert.equal(await auto.registerOrca({...f,paneKey:'tab-a;untrusted'}),false);
 assert.equal(await auto.registerOrca({...f,sessionId:'missing'}),false);
 assert.equal(await auto.registerOrca(f),true);
 const entries=auto.readOrcaRegistrations(f);
 assert.equal(entries.length,1);assert.equal(entries[0].paneKey,paneKey);
});
test('only native SessionStart handler registers the hook session and matching pane',{skip:process.platform!=='linux'},async t=>{
 const f=fixture(t),env={...f,codexHome:f.home,quiet:true,providerReader:async()=>null};
 const input={session_id:f.sessionId,cwd:f.home};
 await handleHook({...input,hook_event_name:'UserPromptSubmit'},env);
 assert.deepEqual(auto.readOrcaRegistrations(f),[]);
 const result=await handleHook({...input,hook_event_name:'SessionStart'},env);
 assert.equal(result.hookSpecificOutput?.hookEventName,'SessionStart');
 const [record]=auto.readOrcaRegistrations(f);
 assert.equal(record?.handle,handle);
 assert.equal(record?.paneKey,paneKey);
});
test('reconciliation splits only the correct solo Codex pane and never repeats a pending request',async t=>{
 const f=fixture(t),calls=[];
 await auto.registerOrca(f);
 const run=async args=>{calls.push(args);if(args[1]==='list')return visible(term(handle));if(args[1]==='split')throw Error('ambiguous transport');throw Error('unexpected command');};
 await auto.reconcileOrca({...f,run});
 await auto.reconcileOrca({...f,run});
 const splits=calls.filter(a=>a[1]==='split');assert.equal(splits.length,1);
 assert.deepEqual(splits[0].slice(0,6),['terminal','split','--terminal',handle,'--direction','horizontal']);
 assert.match(splits[0].at(-2),/watch --session session-a/);
});
test('existing companion is left alone and stale or foreign pane never receives a split',async t=>{
 const f=fixture(t);await auto.registerOrca(f);
 const graph={type:'pane-split',first:term(handle),second:term('term_gauge')};
 const companion={handle:'term_gauge',tabId,leafId:'leaf-gauge',connected:true,agentIdentity:null};
 for(const [layout,want] of [[visible(graph,[primary,companion]),['session-a']],[visible(term('term_replaced'),[{...primary,handle:'term_replaced'}]),[]]]){
  const run=async args=>{if(args[1]==='list')return layout;throw Error('unexpected write');};
  assert.deepEqual((await auto.reconcileOrca({...f,run})).sessions,want);
 }
});
test('a truncated topology is not considered a healthy no-op',async t=>{
 const f=fixture(t);await auto.registerOrca(f);
 await assert.rejects(auto.reconcileOrca({...f,run:async args=>{
  assert.equal(args[1],'list');
  return {...visible(term(handle)),truncated:true};
 }}),/complete Orca topology unavailable/);
});
test('new split gets the exact session title on the companion only',async t=>{
 const f=fixture(t),titles=[];await auto.registerOrca(f);
 const run=async args=>{
  if(args[1]==='list')return visible(term(handle));
  if(args[1]==='split')return {split:{handle:'term_new_gauge',tabId}};
  if(args[1]==='set-pane-title'){titles.push(args);return {paneTitle:{title:'mai-codex-gauge session-a'}};}
  throw Error('unexpected call');
 };
 const result=await auto.reconcileOrca({...f,run});
 assert.deepEqual(result.attached,['session-a']);
 assert.deepEqual(result.titleFailures,[]);
 assert.deepEqual(titles,[['terminal','set-pane-title','--terminal','term_new_gauge','--title','mai-codex-gauge session-a','--json']]);
});
const restored={handle:'term_gauge',tabId,leafId:'leaf-gauge',paneTitle:'mai-codex-gauge session-a',
 connected:true,writable:true,executionHostId:'local',worktreeId:'worktree-a',worktreePath:'/work/gauge',incarnationId:'incarnation-a'};
const lower={type:'pane-split',direction:'horizontal',first:term(handle),second:term(restored.handle)};
const prompt='jay@ai-lx01:/work/gauge$ ';
const blankScreen={handle:restored.handle,status:'running',source:'screen',tail:['',prompt,''],truncated:false,limited:false};
test('a restored shell can have wrapped history above its final empty prompt',async t=>{
 const f=fixture(t);await auto.registerOrca(f);
 const run=async args=>{
  if(args[1]==='list')return visible(lower,[primary,restored]);
  if(args[1]==='read')return {terminal:{...blankScreen,
   tail:[prompt+'node old-watch --session session-a',' continued',prompt,''],
   tailRows:[{wrapped:false},{wrapped:true},{wrapped:false},{wrapped:false}]}};
  if(args[1]==='send')return {send:{handle:restored.handle,accepted:true}};
  throw Error('unexpected command');
 };
 assert.deepEqual((await auto.reconcileOrca({...f,run})).restored,['session-a']);
});
test('a titled local Codex split recovers without SessionStart and keeps the same at-most-once guard',async t=>{
 const f=fixture(t),sends=[];
 const run=async args=>{
  if(args[1]==='list')return visible(lower,[primary,restored]);
  if(args[1]==='read')return {terminal:blankScreen};
  if(args[1]==='send'){sends.push(args);return {send:{handle:restored.handle,accepted:true}};}
  throw Error('unexpected command');
 };
 assert.deepEqual(auto.readOrcaRegistrations(f),[]);
 const first=await auto.reconcileOrca({...f,run});
 assert.deepEqual(first.restored,['session-a']);
 assert.deepEqual(first.sessions,['session-a']);
 assert.deepEqual(auto.readOrcaRegistrations(f),[]);
 await auto.registerOrca(f);
 assert.deepEqual((await auto.reconcileOrca({...f,run})).restored,[]);
 assert.equal(sends.length,1);
 assert.deepEqual(sends[0].slice(0,5),['terminal','send','--terminal','term_gauge','--text']);
 assert.match(sends[0][5],/watch --session session-a --base /);
});
test('title-only recovery rejects a missing or foreign rollout and an unrelated upper pane',async t=>{
 const f=fixture(t),sends=[];
 const sessions=path.join(f.home,'sessions');
 fs.writeFileSync(path.join(sessions,'rollout-session-b.jsonl'),'{"type":"session_meta","payload":{"id":"another-owner"}}\n');
 for(const [upper,pane] of [
  [primary,{...restored,paneTitle:'mai-codex-gauge session-b'}],
  [primary,{...restored,paneTitle:'mai-codex-gauge missing'}],
  [primary,{...restored,paneTitle:'mai-codex-gauge session-a\n'}],
  [{...primary,agentIdentity:'claude'},restored],
  [{...primary,executionHostId:'remote'},restored]
 ]){
  const run=async args=>{
   if(args[1]==='list')return visible(lower,[upper,pane]);
   if(args[1]==='read')return {terminal:blankScreen};
   sends.push(args);return {};
  };
  assert.deepEqual((await auto.reconcileOrca({...f,run})).sessions,[]);
 }
 assert.deepEqual(sends,[]);
});
test('a valid but conflicting title does not override a current SessionStart binding',async t=>{
 const f=fixture(t);await auto.registerOrca(f);
 fs.writeFileSync(path.join(f.home,'sessions','rollout-session-b.jsonl'),'{"type":"session_meta","payload":{"id":"session-b"}}\n');
 const run=async args=>{
  assert.equal(args[1],'list');
  return visible(lower,[primary,{...restored,paneTitle:'mai-codex-gauge session-b'}]);
 };
 const result=await auto.reconcileOrca({...f,run});
 assert.deepEqual(result.sessions,['session-a']);
 assert.deepEqual(result.restored,[]);
});
test('only the exact restored companion receives watch, once per shell even after an ambiguous receipt',async t=>{
 const f=fixture(t),sends=[];await auto.registerOrca(f);
 let incarnation=restored.incarnationId;
 const run=async args=>{
  if(args[1]==='list')return visible(lower,[primary,{...restored,incarnationId:incarnation}]);
  if(args[1]==='read')return {terminal:blankScreen};
  if(args[1]==='send'){
   sends.push(args);
   if(incarnation==='incarnation-a')throw Error('ambiguous transport');
   return {send:{handle:'term_gauge',accepted:true}};
  }
  throw Error('unexpected command');
 };
 assert.deepEqual((await auto.reconcileOrca({...f,run})).restored,[]);
 await auto.reconcileOrca({...f,run});
 assert.equal(sends.length,1);
 assert.deepEqual(sends[0].slice(0,5),['terminal','send','--terminal','term_gauge','--text']);
 assert.match(sends[0][5],/watch --session session-a --base /);
 assert.deepEqual(sends[0].slice(6),['--enter','--json']);
 incarnation='incarnation-b';
 assert.deepEqual((await auto.reconcileOrca({...f,run})).restored,['session-a']);
 assert.equal(sends.length,2);
});
test('untitled, foreign, occupied and unverifiable panes never receive terminal input',async t=>{
 const f=fixture(t);await auto.registerOrca(f);
 const cases=[
  [{...restored,paneTitle:undefined},blankScreen],
  [{...restored,paneTitle:'mai-codex-gauge session-b'},blankScreen],
  [{...restored,agentIdentity:'codex'},blankScreen],
  [{...restored,tabId:'elsewhere'},blankScreen],
  [restored,{...blankScreen,tail:[prompt+'echo $']}],
  [restored,{...blankScreen,tail:[prompt,'command still running']}],
  [restored,{...blankScreen,tail:[prompt],tailRows:[{wrapped:true}]}],
  [restored,{...blankScreen,tail:['context 80%','turn T 100']}],
  [restored,{...blankScreen,source:'screen-unavailable'}],
  [restored,{...blankScreen,draft:'something'}]
 ];
 for(const [row,screen] of cases){
  const writes=[];
  const run=async args=>{
   if(args[1]==='list')return visible(lower,[primary,row]);
   if(args[1]==='read')return {terminal:screen};
   writes.push(args);return {};
  };
  await auto.reconcileOrca({...f,run});
  assert.deepEqual(writes,[]);
 }
});
