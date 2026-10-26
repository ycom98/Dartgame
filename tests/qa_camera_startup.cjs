// Independent camera-startup QA. Media comes only from generated canvases, never a webcam.
const fs=require('fs'),path=require('path'),net=require('net');
const {spawn}=require('child_process');
const {chromium}=require('/Users/kapilgandhi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),artifacts=path.join(root,'qa-artifacts');
const results=[],errors=[];let browser,server;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const token='independent-camera-startup-qa';
function check(ok,message){if(!ok)throw Error(message);}
async function waitFor(fn,limit=5000){const end=Date.now()+limit;while(Date.now()<end){if(await fn())return;await pause(40);}throw Error('Timed out: '+String(fn));}
async function installMock(page,mode='success'){
  await page.addInitScript(({initialMode})=>{
    const qa=window.__cameraQA={mode:initialMode,calls:[],streams:[],pending:[],pendingPlays:[],holdPlay:false};
    const originalPlay=HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play=function(){if(qa.holdPlay)return new Promise(resolve=>qa.pendingPlays.push(resolve));return originalPlay.call(this);};
    qa.makeStream=request=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
      const ctx=canvas.getContext('2d');const media=canvas.captureStream(10);
      const track=media.getVideoTracks()[0];let tick=0;
      function draw(){ctx.fillStyle='#12452f';ctx.fillRect(0,0,640,480);ctx.fillStyle='white';ctx.font='28px sans-serif';ctx.fillText('SYNTHETIC QA CAMERA '+request,35,110);ctx.fillRect(20+(tick++%20),220,80,80);}
      draw();const timer=setInterval(draw,100);const originalStop=track.stop.bind(track);
      track.stop=()=>{clearInterval(timer);originalStop();};
      const originalSettings=track.getSettings.bind(track);
      track.getSettings=()=>({...originalSettings(),deviceId:'qa-rear-main'});
      qa.streams.push({request,media,track});
      return media;
    };
    qa.resolvePending=index=>{const pending=qa.pending[index];const media=qa.makeStream(pending.request);pending.resolve(media);return media.id;};
    qa.audit=()=>({calls:qa.calls.length,streams:qa.streams.map(s=>({request:s.request,id:s.media.id,readyState:s.track.readyState})),
      videoStream:document.getElementById('video')?.srcObject?.id||null,
      status:document.getElementById('phoneStatus')?.textContent,error:document.getElementById('error')?.textContent,
      startDisabled:document.getElementById('startCamera')?.disabled,stopDisabled:document.getElementById('stopCamera')?.disabled});
    qa.stopAll=()=>qa.streams.forEach(s=>s.track.stop());
    const media={
      getUserMedia:constraints=>{
        const request=qa.calls.length+1;qa.calls.push({request,constraints});
        if(qa.mode==='deny')return Promise.reject(new DOMException('Denied by synthetic QA scenario','NotAllowedError'));
        if(qa.mode==='pending')return new Promise((resolve,reject)=>qa.pending.push({request,resolve,reject}));
        return Promise.resolve(qa.makeStream(request));
      },
      enumerateDevices:async()=>[
        {kind:'videoinput',label:'Synthetic rear main',deviceId:'qa-rear-main'},
        {kind:'videoinput',label:'Synthetic rear alternate',deviceId:'qa-rear-alt'}
      ]
    };
    if(qa.mode==='missing-api')delete media.getUserMedia;
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:media});
  },{initialMode:mode});
}
let origin;
async function createPage(mode='success',configure){
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const page=await context.newPage();page.setDefaultTimeout(5000);
  page.on('pageerror',error=>errors.push(error.message));
  await installMock(page,mode);
  if(configure)await configure(page);
  await page.goto(origin+'/phone?t='+token);
  await page.waitForFunction(()=>!document.getElementById('startCamera').disabled);
  return{page,context};
}
async function audit(page){return page.evaluate(()=>window.__cameraQA.audit());}
async function started(page){
  await page.waitForFunction(()=>document.getElementById('phoneStatus').textContent.includes('Streaming locally'));
  const state=await audit(page);
  check(state.videoStream&&state.startDisabled&&!state.stopDisabled,'Successful startup must show video with Stop available');
  return state;
}
async function stopped(page){
  await page.waitForFunction(()=>!document.getElementById('startCamera').disabled);
  const state=await audit(page);
  check(!state.videoStream,'Stopped/cancelled camera must not own the video element');
  check(state.streams.every(s=>s.readyState==='ended'),'Stopped/cancelled tracks must end');
  return state;
}
async function run(name,fn){
  const before=errors.length;
  try{const detail=await fn();check(errors.length===before,'Unexpected page error: '+errors.slice(before).join('; '));results.push({name,pass:true,detail});}
  catch(error){results.push({name,pass:false,error:error.stack});}
}
(async()=>{
  fs.mkdirSync(artifacts,{recursive:true});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  let output='';
  server=spawn(path.join(root,'.venv/bin/python'),['-B','-c','import server;server.app=server.App("'+token+'");server.main()','--http','--host','127.0.0.1','--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',chunk=>output+=chunk.toString());
  server.stderr.on('data',chunk=>errors.push('QA server: '+chunk.toString().trim()));
  await waitFor(()=>output.includes('Computer:'),10000);
  origin='http://127.0.0.1:'+port;
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  const baseline=process.argv.includes('--baseline');
  if(!baseline)await run('synthetic rear camera starts, uploads frames and stops cleanly',async()=>{
    const{page,context}=await createPage();let uploads=0;page.on('request',r=>{if(r.url().endsWith('/api/frame'))uploads++;});
    try{
      await page.locator('#startCamera').click();const state=await started(page);
      await waitFor(()=>uploads>0);
      const constraint=await page.evaluate(()=>window.__cameraQA.calls[0].constraints);
      check(constraint.audio===false&&constraint.video.facingMode?.ideal==='environment','Must request rear camera without microphone');
      await page.screenshot({path:path.join(artifacts,'camera-startup-synthetic.png'),fullPage:true});
      await page.locator('#stopCamera').click();await stopped(page);
      const count=uploads;await pause(850);check(uploads===count,'Stopped camera must not keep uploading');
      return{uploads,streamCount:state.streams.length};
    }finally{await context.close();}
  });
  if(!baseline)await run('permission denial is actionable and retry succeeds',async()=>{
    const{page,context}=await createPage('deny');
    try{
      await page.locator('#startCamera').click();
      await page.waitForFunction(()=>!document.getElementById('startCamera').disabled&&/permission|denied/i.test(document.getElementById('error').textContent+' '+document.getElementById('phoneStatus').textContent));
      check((await audit(page)).streams.length===0,'Denied permission must not leave a stream');
      await page.evaluate(()=>window.__cameraQA.mode='success');await page.locator('#startCamera').click();await started(page);
      return{retry:'streaming'};
    }finally{await context.close();}
  });
  await run('pending permission shows progress and cancellation cleans a late stream',async()=>{
    const{page,context}=await createPage('pending');
    try{
      await page.locator('#startCamera').click();await page.waitForFunction(()=>window.__cameraQA.calls.length===1);
      const waiting=await audit(page);
      check(/permission|allow|waiting|camera access/i.test(waiting.status),'Pending permission must replace the misleading Camera off status');
      check(!waiting.stopDisabled,'Pending camera permission must expose cancel/stop');
      if(!baseline)await page.screenshot({path:path.join(artifacts,'camera-permission-pending.png'),fullPage:true});
      await page.locator('#stopCamera').click();await stopped(page);
      await page.evaluate(()=>window.__cameraQA.resolvePending(0));await pause(200);
      const state=await stopped(page);check(state.streams.length===1,'Late synthetic grant must be exercised');
      return{lateTrack:state.streams[0].readyState,status:state.status};
    }finally{await context.close();}
  });
  if(!baseline)await run('cancelled old permission cannot replace a newer successful stream',async()=>{
    const{page,context}=await createPage('pending');
    try{
      await page.locator('#startCamera').click();await page.waitForFunction(()=>window.__cameraQA.calls.length===1);
      await page.locator('#stopCamera').click();await stopped(page);
      await page.evaluate(()=>window.__cameraQA.mode='success');await page.locator('#startCamera').click();const newer=await started(page);
      await page.evaluate(()=>window.__cameraQA.resolvePending(0));await pause(250);
      const state=await audit(page);
      check(state.videoStream===newer.videoStream,'Old permission result must not replace current video');
      check(state.streams.find(s=>s.request===1)?.readyState==='ended','Old late stream must be stopped');
      check(state.streams.find(s=>s.request===2)?.readyState==='live','Newer accepted stream must remain live');
      return{oldTrack:'ended',currentTrack:'live'};
    }finally{await context.close();}
  });
  if(!baseline)await run('reset failure gives feedback and permits a successful retry',async()=>{
    const{page,context}=await createPage('success',async page=>{
      await page.route('**/api/camera/reset',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"Synthetic QA reset unavailable"}'}));
    });
    try{
      await page.locator('#startCamera').click();
      await page.waitForFunction(()=>!document.getElementById('startCamera').disabled&&/reset|server|unavailable|connect/i.test(document.getElementById('error').textContent+' '+document.getElementById('phoneStatus').textContent));
      check((await audit(page)).calls===0,'Reset failure must not request the camera');
      await page.unroute('**/api/camera/reset');await page.locator('#startCamera').click();await started(page);
      return{retry:'streaming'};
    }finally{await context.close();}
  });
  if(!baseline)await run('hung reset is bounded, releases startup and allows retry',async()=>{
    let release;
    const{page,context}=await createPage('success',async page=>{
      await page.route('**/api/camera/reset',async route=>{await new Promise(resolve=>release=resolve);await route.fulfill({status:200,contentType:'application/json',body:'{}'}).catch(()=>{});});
    });
    try{
      const startedAt=Date.now();await page.locator('#startCamera').click();
      await page.waitForFunction(()=>!document.getElementById('startCamera').disabled,undefined,{timeout:13000});
      const state=await audit(page);
      check(/timed out|timeout|server|Wi-Fi|connection/i.test(state.status+' '+state.error),'Reset timeout needs actionable feedback');
      check(state.calls===0,'Hung reset must not reach getUserMedia');
      const elapsed=Date.now()-startedAt;check(elapsed<13000,'Reset wait must be bounded');
      release?.();await page.unroute('**/api/camera/reset');
      await page.locator('#startCamera').click();await started(page);
      return{timeoutElapsedMs:elapsed,retry:'streaming'};
    }finally{release?.();await context.close();}
  });
  if(!baseline)await run('cancelled playback cannot start an abandoned stream after retry',async()=>{
    const{page,context}=await createPage();
    try{
      await page.evaluate(()=>window.__cameraQA.holdPlay=true);
      await page.locator('#startCamera').click();await page.waitForFunction(()=>window.__cameraQA.pendingPlays.length===1);
      check(!(await audit(page)).stopDisabled,'Starting preview must remain cancellable');
      await page.locator('#stopCamera').click();await stopped(page);
      await page.evaluate(()=>window.__cameraQA.holdPlay=false);
      await page.locator('#startCamera').click();const newer=await started(page);
      await page.evaluate(()=>window.__cameraQA.pendingPlays[0]());await pause(250);
      const state=await audit(page);
      check(state.videoStream===newer.videoStream,'Late playback must not replace the current stream');
      check(state.streams.find(s=>s.request===1)?.readyState==='ended','Abandoned preview track must end');
      check(state.streams.find(s=>s.request===2)?.readyState==='live','Current preview must stay live');
      return{oldPlayback:'discarded',currentTrack:'live'};
    }finally{await context.close();}
  });
  if(!baseline)await run('ended event from a stopped old track does not stop the restarted camera',async()=>{
    const{page,context}=await createPage();
    try{
      await page.locator('#startCamera').click();await started(page);
      await page.locator('#stopCamera').click();await stopped(page);
      await page.locator('#startCamera').click();const newer=await started(page);
      await page.evaluate(()=>window.__cameraQA.streams[0].track.dispatchEvent(new Event('ended')));
      await pause(250);const state=await audit(page);
      check(state.videoStream===newer.videoStream,'Old ended event must not stop new video');
      check(state.streams[1].readyState==='live','New track must stay live');
      return{currentTrack:'live'};
    }finally{await context.close();}
  });
  if(!baseline)await run('missing camera API explains secure-context requirement without locking retry',async()=>{
    const{page,context}=await createPage('missing-api');
    try{
      await page.locator('#startCamera').click();
      await page.waitForFunction(()=>!document.getElementById('startCamera').disabled&&/HTTPS|secure|camera API|browser/i.test(document.getElementById('error').textContent+' '+document.getElementById('phoneStatus').textContent));
      const state=await audit(page);check(state.calls===0,'Missing API must not request media');
      return{diagnostic:'actionable'};
    }finally{await context.close();}
  });
})().catch(error=>results.push({name:'camera QA harness completion',pass:false,error:error.stack}))
.finally(async()=>{
  if(browser)await browser.close();
  if(server){server.kill('SIGTERM');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(resolve,1500);});}
  fs.mkdirSync(artifacts,{recursive:true});
  const evidence={testOnly:true,media:'Generated canvas.captureStream returned by mocked getUserMedia; no actual webcam',network:'Own ephemeral localhost app; no HTTPS trust bypass; live8443 untouched',results,errors};
  fs.writeFileSync(path.join(artifacts,process.argv.includes('--baseline')?'camera-startup-baseline.json':'camera-startup-results.json'),JSON.stringify(evidence,null,2)+'\n');
  console.log(JSON.stringify(evidence,null,2));process.exitCode=results.some(r=>!r.pass)||errors.length?1:0;
});

