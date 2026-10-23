// Isolated Chrome, built-in Node WebSocket, no browser packages or installed extensions.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const [browser,url,w,h,output,mode] = process.argv.slice(2);
const profile = await fs.mkdtemp(path.join(os.tmpdir(),'mai-watch-cdp-'));
const child = spawn(browser,['--headless','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
let socket, closeBrowser;
const delay = ms => new Promise(r=>setTimeout(r,ms));
try {
  let port;
  for(let i=0;i<100;i++){try{port=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await delay(100);}}
  if(!port)throw Error('Owned Chrome did not expose its debugging port');
  const target = await (await fetch('http://127.0.0.1:'+port+'/json/new?about:blank',{method:'PUT'})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let id=0; const pending=new Map();
  socket.addEventListener('message',event=>{const m=JSON.parse(event.data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}});
  function call(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error('CDP timeout: '+method));},10000);pending.set(n,{resolve:v=>{clearTimeout(timer);resolve(v)},reject:e=>{clearTimeout(timer);reject(e)}});socket.send(JSON.stringify({id:n,method,params}));});}
  closeBrowser=()=>call('Browser.close').catch(()=>{});
  await call('Emulation.setDeviceMetricsOverride',{width:Number(w),height:Number(h),deviceScaleFactor:1,mobile:Number(w)===390});
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
  await call('Page.navigate',{url});
  let result;
  for(let i=0;i<100;i++){
    const expression=mode==='live'?"document.querySelectorAll('.gpu-row').length===2 && JSON.stringify({width:innerWidth,height:innerHeight})":"document.getElementById('layout-check')?.textContent";
    const r=await call('Runtime.evaluate',{expression,returnByValue:true});
    if(r.result?.value){result=JSON.parse(r.result.value);break;}await delay(100);
  }
  if(!result)throw Error('Layout never became ready');
  if(result.width!==Number(w)||result.height!==Number(h))throw Error('Viewport mismatch');
  const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await fs.writeFile(output,Buffer.from(shot.data,'base64'));
  console.log(JSON.stringify(result));
  // Only this newly created browser is closed, never a user's browser or dashboard process.
  await closeBrowser();
  closeBrowser=null;
} finally {
  if(closeBrowser && socket?.readyState===WebSocket.OPEN)await closeBrowser();
  socket?.close();
  if(child.exitCode===null)await Promise.race([new Promise(r=>child.once('exit',r)),delay(3000)]);
  if(child.exitCode!==null && profile.startsWith(path.join(os.tmpdir(),'mai-watch-cdp-')))
    await fs.rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:200}).catch(()=>{});
}
