import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {discoverProviderRpc} from '../src/provider.mjs';

test('Windows API discovery does not treat an inaccessible control socket as an absent runtime',{skip:process.platform!=='win32'},()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-discovery-'));
 const bin=path.join(home,'packages','app-server-daemon','releases','0.162.1-x86_64-pc-windows-msvc','bin');fs.mkdirSync(bin,{recursive:true});fs.writeFileSync(path.join(bin,'codex.exe'),'fixture, not executable');fs.mkdirSync(path.join(home,'app-server-control'));
 // existsSync is false both for an absent entry and the actual AF_UNIX EACCES
 // reparse point. Connection, not a regular-file read, determines availability.
 const rpc=discoverProviderRpc(home);assert.ok(rpc);assert.equal(rpc.executable,path.join(bin,'codex.exe'));assert.equal(rpc.args.at(-1),path.join(home,'app-server-control','app-server-control.sock'));
});
