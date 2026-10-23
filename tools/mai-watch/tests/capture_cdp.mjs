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
  await call('Page.enable');
  if(mode==='recovery'||mode==='product')await call('Page.addScriptToEvaluateOnNewDocument',{source:`
    window.__liveRequests=0;window.__hold=false;window.__oldSamples=false;window.__liveStatus=0;window.__snapshotRequests=0;window.__snapshotError=false;
    const realFetch=window.fetch.bind(window);
    window.fetch=function(url,options){
      if(String(url).startsWith('snapshot.json')){window.__snapshotRequests++;if(window.__snapshotError)return Promise.resolve({ok:false,status:503});}
      if(!String(url).startsWith('live.json'))return realFetch(url,options);
      window.__liveRequests++;
      if(window.__liveStatus)return Promise.resolve({ok:false,status:window.__liveStatus});
      if(window.__hold)return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
      return realFetch(url,options).then(async r=>{
        if(!window.__oldSamples)return r;
        const data=await r.json();data.samples.forEach(s=>s.t=new Date(Date.parse(s.t)-20000).toISOString());
        return {ok:true,status:200,json:()=>Promise.resolve(data)};
      });
    };`});
  await call('Page.navigate',{url});
  let result;
  for(let i=0;i<100;i++){
    const expression=mode==='live'?"document.querySelectorAll('.gpu-row').length===2 && JSON.stringify({width:innerWidth,height:innerHeight})":"document.getElementById('layout-check')?.textContent";
    const r=await call('Runtime.evaluate',{expression,returnByValue:true});
    if(r.result?.value){result=JSON.parse(r.result.value);break;}await delay(100);
  }
  if(!result)throw Error('Layout never became ready');
  if(result.width!==Number(w)||result.height!==Number(h))throw Error('Viewport mismatch');
  if(mode==='recovery'||mode==='product'){
    async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;}
    function check(ok,message){if(!ok)throw Error(message);}
    check(await evaluate("typeof window.__liveRequests==='number'"),'Fault injection did not attach before page scripts');
    const buttons=await evaluate(`JSON.stringify([...document.querySelectorAll('.header-actions button')].map(e=>({id:e.id,h:e.getBoundingClientRect().height})))`);
    check(JSON.parse(buttons).length===2 && JSON.parse(buttons).every(b=>b.h>=44),'Reload/theme targets missing or too small');
    if(mode==='product'){
      check(await evaluate("document.querySelector('.cpu-processes').textContent.includes('compute-0.exe')"),'CPU processes missing');
      await evaluate("document.getElementById('graph-range').value='60';document.getElementById('graph-range').dispatchEvent(new Event('change'));document.getElementById('view-focus').value='cpu';document.getElementById('view-focus').dispatchEvent(new Event('change'))");
      check(await evaluate("MaiLive.range===60 && document.getElementById('live-section').getAttribute('data-focus')==='cpu'"),'Preferences not applied');
      await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:profile});
      await evaluate("document.getElementById('diagnostic-download').click()");
      let exported;
      for(let i=0;i<30;i++){try{exported=JSON.parse(await fs.readFile(path.join(profile,'mai-watch-diagnostic.json'),'utf8'));break;}catch{await delay(100);}}
      check(exported?.schema==='mai-watch-diagnostic-v1','Actual diagnostic download failed');
      check(await evaluate("document.querySelector('.view-options').textContent.includes('Settings stay')"),'Privacy guidance missing');
      await call('Page.reload');await delay(2500);
      check(await evaluate("MaiLive.range===60 && document.getElementById('view-focus').value==='cpu'"),'Preferences lost on reload');
      await evaluate("document.getElementById('graph-range').value='600';document.getElementById('graph-range').dispatchEvent(new Event('change'))");
      result.product='CPU / preferences / real diagnostic download PASS';
    }
    await evaluate('window.__hold=true');await delay(2200);
    check(await evaluate("Number(document.getElementById('live-freshness').textContent.match(/Received (\\d+) s/)[1])>=1"),'Freshness stopped aging while the request was pending');
    await delay(5300);
    check(await evaluate("document.getElementById('live-status').textContent.startsWith('disconnected')"),'Hung request did not become disconnected: '+await evaluate("JSON.stringify({badge:document.getElementById('live-status').textContent,requests:window.__liveRequests,hold:window.__hold,error:window.MaiLive.error,hidden:document.hidden})"));
    const count=await evaluate('window.__liveRequests');
    await evaluate("window.__hold=false;window.dispatchEvent(new Event('online'));window.dispatchEvent(new Event('pageshow'));document.dispatchEvent(new Event('visibilitychange'))");
    await delay(650);
    check(await evaluate('window.__liveRequests')===count+1,'Resume created duplicate requests');
    check(await evaluate("document.getElementById('live-status').textContent.startsWith('live,')"),'Resume did not recover live state');
    await evaluate("window.__oldSamples=true;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('live-status').textContent.startsWith('stale')"),'Fresh HTTP response hid stale measurement');
    await evaluate("window.__oldSamples=false;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('live-status').textContent.startsWith('live,')"),'Fresh samples did not recover');
    await evaluate("window.__liveStatus=404;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('live-section').style.display!=='none' && document.getElementById('live-status').textContent.startsWith('disconnected')"),'Temporary 404 permanently hid an established live view');
    await evaluate("window.__liveStatus=0;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('live-status').textContent.startsWith('live,')"),'Temporary 404 did not recover');
    const snapshotCount=await evaluate('window.__snapshotRequests');
    await evaluate("window.__snapshotError=true;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('error').textContent.includes('503')"),'Workload HTTP failure was not shown');
    await delay(3300);
    check(await evaluate('window.__snapshotRequests')>=snapshotCount+2,'Workload HTTP failure did not use the retry interval');
    await evaluate("window.__snapshotError=false;window.dispatchEvent(new Event('online'))");await delay(650);
    check(await evaluate("document.getElementById('error').style.display==='none'"),'Workload view did not recover');
    await evaluate("document.getElementById('theme').click()");
    const theme=await evaluate("document.getElementById('theme').textContent"), origin=await evaluate('performance.timeOrigin');
    await evaluate("document.getElementById('refresh').click()");await delay(2300);
    check(await evaluate('performance.timeOrigin')!==origin,'Reload button did not navigate');
    check(await evaluate("document.getElementById('theme').textContent")===theme,'Reload lost saved theme');
    // Use dark in the evidence; preferences were already checked above.
    await evaluate("document.getElementById('theme').click()");
    const final=await evaluate("document.getElementById('layout-check')?.textContent");
    check(!!final,'Reload did not restore the viewer');
    result=JSON.parse(final);result.recovery='PASS: age timer, timeout, resume burst, stale measurement, workload HTTP retry, recovery, reload and theme';
    if(mode==='product')result.product='PASS: CPU processes, local preferences survive reload, real diagnostic JSON download';
  }
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
