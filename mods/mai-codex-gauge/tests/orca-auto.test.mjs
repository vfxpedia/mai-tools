import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as auto from '../src/orca-auto.mjs';
import {handleHook} from '../src/hook.mjs';

const tabId='tab-a',leafId='leaf-a',handle='term_original',paneKey=`${tabId}:${leafId}`;
const primary={tabId,leafId,handle,agentIdentity:'codex',connected:true};
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
