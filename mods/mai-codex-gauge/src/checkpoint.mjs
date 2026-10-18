import crypto from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {safePath,readJson,atomicUpdate,validateId} from './store.mjs';

const execute=promisify(execFile);
export async function readGitHubComment(endpoint){
 try{const {stdout}=await execute('gh',['api',endpoint],{timeout:10000,maxBuffer:1024*1024,windowsHide:true});return JSON.parse(stdout);}
 catch{throw Error('GitHub readback failed; no receipt was saved');}
}

// Read back an existing comment. Never post, copy transcripts to GitHub, or compact.
export async function recordIssueReceipt({base,sessionId,url,now=Date.now(),readComment=readGitHubComment}){
 validateId(sessionId);
 const match=/^https:\/\/github\.com\/([\w-]+)\/([\w.-]+)\/issues\/([1-9]\d*)#issuecomment-([1-9]\d*)$/.exec(url??'');
 if(!match)throw Error('an exact GitHub Issue comment URL is required');
 const [,owner,repo,number,commentId]=match,issue=`${owner}/${repo}#${number}`;
 const session=readJson(safePath(base,'sessions',`${sessionId}.json`));
 const owns=s=>s?.id===sessionId&&s.issues?.some(x=>x===issue||x===`https://github.com/${owner}/${repo}/issues/${number}`);
 if(!owns(session))throw Error('comment does not belong to the current work Issue');
 const comment=await readComment(`repos/${owner}/${repo}/issues/comments/${commentId}`),createdAt=Date.parse(comment?.created_at);
 if(String(comment?.id)!==commentId||comment?.html_url!==url||typeof comment?.body!=='string'||!comment.body.trim()||!Number.isFinite(createdAt)||createdAt>now)throw Error('GitHub readback did not verify the receipt');
 const receipt={url,issue,verifiedAt:now,createdAt,bodySha256:crypto.createHash('sha256').update(comment.body).digest('hex')};
 const result=atomicUpdate(safePath(base,'units',`${sessionId}.json`),sessionId,old=>{
  if(!owns(readJson(safePath(base,'sessions',`${sessionId}.json`))))throw Error('work Issue changed during readback');
  const p=old?.codex?.contextPolicy;if(!p||!Array.isArray(p.checkpoints))throw Error('no context checkpoint to verify');
  let count=0;
  const checkpoints=p.checkpoints.map(c=>{if(c.level>=75&&c.issueStatus==='requested'&&createdAt>=c.at&&c.issues?.some(x=>x===issue||x===`https://github.com/${owner}/${repo}/issues/${number}`)){count++;return {...c,issueStatus:'verified',receipt};}return c;});
  if(!count)throw Error('receipt predates pending checkpoints or nothing is pending');
  return {...old,codex:{...old.codex,contextPolicy:{...p,checkpoints}}};
 });
 if(!result.written)throw Error('receipt could not be saved');
 return {verified:true,receipt};
}
