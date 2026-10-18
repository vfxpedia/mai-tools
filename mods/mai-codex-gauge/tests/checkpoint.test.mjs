import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {recordIssueReceipt} from '../src/checkpoint.mjs';
import {saveSession,readJson} from '../src/store.mjs';

function fixture(){const base=fs.mkdtempSync(path.join(os.tmpdir(),'gauge-receipt-'));saveSession(base,'self',{at:100,doing:'Check cost',issues:['example/repo-a#30'],next:'Install'});fs.mkdirSync(path.join(base,'units'));fs.writeFileSync(path.join(base,'units','self.json'),JSON.stringify({sessionId:'self',units:[],codex:{contextPolicy:{epoch:0,checkpoints:[{level:75,epoch:0,at:100,issues:['example/repo-a#30'],issueStatus:'requested'}]}}}));return base;}
const url='https://github.com/example/repo-a/issues/30#issuecomment-123';
const valid={id:123,html_url:url,created_at:'2026-10-12T00:00:00Z',body:'Checked API return. Source: private transcript, retained. Next: install.'};
test('receipt requires actual readback from the owning Issue, saves hash but no comment body',async()=>{
 const base=fixture();let requested;
 await recordIssueReceipt({base,sessionId:'self',url,now:Date.parse('2026-10-13T00:00:00Z'),readComment:async endpoint=>{requested=endpoint;return valid;}});
 assert.equal(requested,'repos/example/repo-a/issues/comments/123');
 const c=readJson(path.join(base,'units','self.json')).codex.contextPolicy.checkpoints[0];assert.equal(c.issueStatus,'verified');assert.equal(c.receipt.url,url);assert.equal(c.receipt.bodySha256.length,64);assert.equal(c.receipt.body,undefined);
});
test('wrong Issue, forged readback, empty comment and future receipt do not mark it saved',async()=>{
 for(const [link,comment] of [[url.replace('/30#','/31#'),valid],[url,{...valid,html_url:url.replace('/30#','/31#')}],[url,{...valid,body:''}],[url,{...valid,created_at:'2099-01-01T00:00:00Z'}]]){
  const base=fixture(),before=fs.readFileSync(path.join(base,'units','self.json'));
  await assert.rejects(recordIssueReceipt({base,sessionId:'self',url:link,readComment:async()=>comment}));assert.deepEqual(fs.readFileSync(path.join(base,'units','self.json')),before);
 }
});
