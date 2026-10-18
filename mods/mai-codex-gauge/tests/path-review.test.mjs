// Regressions for the independent review of 8b4f747 (three findings). Each case failed on 7669d0f.
import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
import {safePath} from '../src/store.mjs';
import {validateTranscript} from '../src/hook.mjs';

const temp=()=>fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'gauge-path-review-')));
const link=(target,at)=>fs.symlinkSync(target,at,process.platform==='win32'?'junction':'dir');
const PKG=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');

function transcriptAt(dir,id){
 fs.mkdirSync(dir,{recursive:true});const f=path.join(dir,`rollout-${id}.jsonl`);
 fs.writeFileSync(f,JSON.stringify({type:'session_meta',payload:{id}})+'\n');return f;
}

test('explicit transcript under a link two folders above the file is refused; the same layout without a link passes',()=>{
 const t=temp(),home=path.join(t,'home'),outside=path.join(t,'outside');
 fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 transcriptAt(path.join(outside,'month'),'self');
 link(outside,path.join(home,'sessions','year'));
 assert.throws(()=>validateTranscript(path.join(home,'sessions','year','month','rollout-self.jsonl'),home,'self'),/symlink|junction/);
 const plain=transcriptAt(path.join(home,'sessions','2026','10'),'self');
 assert.equal(validateTranscript(plain,home,'self'),plain);
});

test('safePath refuses drive-relative and absolute components on every system',()=>{
 const t=temp();
 for(const bad of ['Z:outside.json','C:','c:x'])assert.throws(()=>safePath(t,bad),/unsafe path component/,bad);
 assert.equal(safePath(t,'units','a.json'),path.join(t,'units','a.json'));
});

test('a script reached through a linked folder runs main exactly as through its real path',()=>{
 const t=temp(),via=path.join(t,'linked-package');link(PKG,via);
 const env={...process.env,CODEX_HOME:path.join(t,'codex-home')};fs.mkdirSync(env.CODEX_HOME);
 for(const script of ['src/setup.mjs','src/cli.mjs']){
  const run=root=>spawnSync(process.execPath,[path.join(root,script),'no-such-command'],{encoding:'utf8',env,cwd:t});
  const real=run(PKG),linked=run(via);
  assert.ok((real.stdout+real.stderr).trim().length>0,`${script} real path printed nothing`);
  assert.deepEqual({status:linked.status,out:linked.stdout,err:linked.stderr},{status:real.status,out:real.stdout,err:real.stderr},script);
 }
});
