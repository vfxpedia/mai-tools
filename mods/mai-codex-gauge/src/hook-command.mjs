import path from 'node:path';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
const runtimes=new Map();
export function resolveHookRuntime(runtime=process.execPath){
 if(!path.isAbsolute(runtime))throw Error('absolute hook runtime required');
 if(process.platform!=='win32')return runtime;
 if(runtimes.has(runtime))return runtimes.get(runtime);
 let alias=runtime.replaceAll('\\','/');
 if(!/^[A-Za-z]:\/[A-Za-z0-9_./~+-]+$/.test(alias)){
  const shell=path.join(process.env.SystemRoot??'C:/Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  const text=`$f=New-Object -ComObject Scripting.FileSystemObject; $f.GetFile('${runtime.replaceAll("'","''")}').ShortPath`;
  const result=spawnSync(shell,['-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(text,'utf16le').toString('base64')],{encoding:'utf8',timeout:5000,windowsHide:true});
  if(result.status!==0)throw Error('approved Node runtime alias unavailable');alias=result.stdout.trim().replaceAll('\\','/');
 }
 if(!/^[A-Za-z]:\/[A-Za-z0-9_./~+-]+$/.test(alias)||fs.realpathSync.native(alias).toLowerCase()!==fs.realpathSync.native(runtime).toLowerCase())throw Error('safe Node runtime alias unavailable; installation refused');
 runtimes.set(runtime,alias);return alias;
}

export function isGaugeCommand(command){
 if(typeof command!=='string')return false;
 if(command.includes('mai-codex-gauge'))return true;
 const encoded=command.match(/\/WindowsPowerShell\/v1\.0\/powershell\.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ([A-Za-z0-9+/=]+)$/);
 return !!encoded&&Buffer.from(encoded[1],'base64').toString('utf16le').includes('mai-codex-gauge');
}

// Bind the installation's Node runtime, not a transient bootstrap PATH. The
// Windows command is valid under both cmd and PowerShell without an additional
// interpreter on the 2-second hook path. Resolve and verify the runtime's safe
// Windows alias once at installation, not on each event.
export function hookCommand(script,runtime=process.execPath){
 if(!path.isAbsolute(script)||!path.isAbsolute(runtime))throw Error('absolute hook runtime and script required');
 if(process.platform==='win32'){
  if(/["$`%!&<>|\r\n]/.test(script))throw Error('unsupported Windows hook path metacharacter');
  return `${resolveHookRuntime(runtime)} ${JSON.stringify(script.replaceAll('\\','/'))}`;
 }
 const literal=s=>"'"+s.replaceAll("'","'\\''")+"'";
 return `${literal(runtime)} ${literal(script)}`;
}
