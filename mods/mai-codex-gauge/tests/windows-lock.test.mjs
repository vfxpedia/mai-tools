import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawn} from 'node:child_process';import {atomicUpdate} from '../src/store.mjs';
test('Windows temporary sharing lock cannot discard the completed atomic update',{skip:process.platform!=='win32'},async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mods-file-lock-')),file=path.join(root,'self.json');fs.writeFileSync(file,JSON.stringify({id:'self',count:1}));
 const command=`$s=[IO.File]::Open('${file.replaceAll("'","''")}',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite);[Console]::WriteLine('ready');[Threading.Thread]::Sleep(120);$s.Dispose()`;
 const child=spawn('powershell.exe',['-NoProfile','-Command',command],{stdio:['ignore','pipe','pipe'],windowsHide:true});const closed=new Promise(resolve=>child.once('close',resolve));
 await new Promise((resolve,reject)=>{let buffer='';child.stdout.on('data',part=>{buffer+=part;if(buffer.includes('ready'))resolve();});child.once('error',reject);child.once('exit',code=>{if(!buffer.includes('ready'))reject(Error('lock fixture did not start: '+code));});});
 const result=atomicUpdate(file,'self',old=>({...old,count:2}));assert.equal(result.written,true);assert.equal(JSON.parse(fs.readFileSync(file,'utf8')).count,2);assert.equal(await closed,0);
 assert.deepEqual(fs.readdirSync(root),['self.json']);
});
