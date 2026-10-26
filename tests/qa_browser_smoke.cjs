// Isolated automated QA of this local application. Never uses the user's browser profile.
const fs=require('fs');
const path=require('path');
const net=require('net');
const {spawn,execFileSync}=require('child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'), python=process.env.DART_PYTHON||path.join(root,'.venv/bin/python');
const artifactDir=require('./qa_output.cjs').dir;
const token='isolated-browser-qa-only';
const results=[], errors=[];
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser,child,feedTimer;
function check(name,condition,detail){results.push({name,pass:!!condition,detail});}
async function waitCheck(fn,timeout=5000){const start=Date.now();while(Date.now()-start<timeout){if(await fn())return;await pause(50);}throw Error('Timed out waiting for QA condition');}
(async()=>{
  fs.mkdirSync(artifactDir,{recursive:true});
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  let startup='';
  child=spawn(python,['-B','-c','import server; server.app=server.App("'+token+'"); server.main()','--http','--host','127.0.0.1','--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
  child.stdout.on('data',chunk=>{startup+=chunk.toString();});
  child.stderr.on('data',chunk=>{errors.push('Server stderr: '+chunk.toString().trim());});
  await waitCheck(async()=>startup.includes('Computer:'),10000);
  const origin='http://127.0.0.1:'+port;
  async function api(endpoint,body,raw){
    const options={headers:{Authorization:'Bearer '+token}};
    if(body!==undefined||raw!==undefined){options.method='POST';options.body=raw===undefined?JSON.stringify(body):raw;}
    const response=await fetch(origin+'/api/'+endpoint,options);
    const data=await response.json();if(!response.ok)throw Error(data.error||String(response.status));return data;
  }
  async function game(){return(await api('state')).game;}
  async function resetManual(page){
    await api('game',{names:['QA A','QA B'],camera:false,start:301});
    await page.reload();await page.waitForSelector('#players .score');
    await page.locator('#cameraGame').uncheck();
    await page.locator('#value').selectOption('20');await page.locator('#multiplier').selectOption('3');
    await pause(700);
  }
  browser=await chromium.launch(process.env.DART_CHROME?{executablePath:process.env.DART_CHROME}:undefined);
  const page=await browser.newPage({viewport:{width:1100,height:1000}});
  page.on('pageerror',error=>errors.push('Desktop: '+error.message));
  await page.goto(origin+'/?t='+token);await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Connect your phone');
  check('camera game disabled before calibration',await page.locator('#newGame').isDisabled());
  await page.screenshot({path:path.join(artifactDir,'setup-desktop.png'),fullPage:true});
  await resetManual(page);
  await page.locator('#manual').dblclick({delay:100});
  await pause(900);
  let current=await game();
  check('normal 100ms double-click records one intended dart',current.darts.length===1,{darts:current.darts.length,scores:current.scores});
  await resetManual(page);
  await page.route('**/api/throw',async route=>{await pause(300);await route.continue();});
  await page.locator('#manual').dblclick({delay:80});
  await pause(1000);
  current=await game();
  check('double-click while score request pending records one dart',current.darts.length===1,{darts:current.darts.length});
  await page.unroute('**/api/throw');
  const imageCode=[
    'import cv2, numpy as np, sys',
    'rng=np.random.default_rng(8741)',
    'image=np.full((800,800,3),70,np.uint8)',
    'for _ in range(1500):',
    ' x,y=rng.integers(165,636,2)',
    ' if (x-400)**2+(y-400)**2<230**2: cv2.circle(image,(int(x),int(y)),int(rng.integers(2,6)),tuple(int(v) for v in rng.integers(0,256,3)),-1)',
    'sys.stdout.buffer.write(cv2.imencode(".png",image)[1].tobytes())'
  ].join('\n');
  const syntheticPng=execFileSync(python,['-B','-c',imageCode],{cwd:root});
  await api('frame',undefined,syntheticPng);
  feedTimer=setInterval(()=>{api('frame',undefined,syntheticPng).catch(error=>errors.push('Synthetic upload: '+error.message));},600);
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Ready to calibrate');
  await page.locator('#calibrate').click();
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent.includes('0/4'));
  const box=await page.locator('#board').boundingBox();
  let releaseImage;
  const imageGate=new Promise(resolve=>{releaseImage=resolve;});
  let holdLiveImage=true;
  await page.route('**/api/image',async route=>{if(holdLiveImage)await imageGate;await route.continue();});
  for(const [x,y]of [[400,150],[650,400],[400,650],[150,400]]){
    await page.locator('#board').click({position:{x:x/800*box.width,y:y/800*box.height}});
  }
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Check the live markers');
  check('four browser-selected calibration points reach overlay review',await page.locator('#verify').isVisible());
  check('overlay verification waits until current live image is drawn',await page.locator('#verify').isDisabled());
  holdLiveImage=false;releaseImage();
  await page.waitForFunction(()=>!document.getElementById('verify').disabled);
  await page.unroute('**/api/image');
  await page.screenshot({path:path.join(artifactDir,'setup-overlay-review.png'),fullPage:true});
  await page.locator('#verify').click();
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Ready to play');
  check('verified guide tells user to start game',/Calibration verified.*Start game/.test(await page.locator('#guide').textContent()));
  await page.locator('#cameraGame').check();
  check('verified overlay enables camera game',!(await page.locator('#newGame').isDisabled()));
  await page.screenshot({path:path.join(artifactDir,'setup-ready.png'),fullPage:true});
  await page.route('**/api/state',route=>route.abort());
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Server disconnected');
  check('server disconnect disables camera-game start',await page.locator('#newGame').isDisabled());
  check('server disconnect disables score controls',await page.locator('#manual').isDisabled()&&await page.locator('#confirm').isDisabled());
  await page.unroute('**/api/state');
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Ready to play');
  clearInterval(feedTimer);feedTimer=null;
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Camera disconnected',undefined,{timeout:8000});
  check('stopped synthetic feed disables camera-game start',await page.locator('#newGame').isDisabled());
  const phone=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  phone.on('pageerror',error=>errors.push('Phone route: '+error.message));
  await phone.goto(origin+'/phone?t='+token);
  await phone.waitForSelector('#phone #startCamera');
  check('phone route shows rear-camera controls',await phone.locator('#startCamera').isVisible());
  const sizing=await phone.evaluate(()=>({width:document.documentElement.clientWidth,content:document.documentElement.scrollWidth,layoutWidth:innerWidth}));
  check('phone route has no horizontal overflow',sizing.content<=sizing.width,sizing);
  await phone.screenshot({path:path.join(artifactDir,'setup-phone.png'),fullPage:true});
  check('no uncaught application browser errors',errors.length===0,errors);
})().catch(error=>{results.push({name:'browser harness completion',pass:false,detail:error.stack});})
.finally(async()=>{
  if(feedTimer)clearInterval(feedTimer);
  if(browser)await browser.close();
  if(child){child.kill('SIGTERM');await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);setTimeout(resolve,2000);});}
  fs.mkdirSync(artifactDir,{recursive:true});
  fs.writeFileSync(path.join(artifactDir,'browser-results.json'),JSON.stringify({testOnly:true,environment:'Isolated headless Chrome; localhost HTTP; synthetic images; no physical camera',results,errors},null,2)+'\n');
  console.log(JSON.stringify({results,errors},null,2));
  process.exitCode=results.some(result=>!result.pass)?1:0;
});
