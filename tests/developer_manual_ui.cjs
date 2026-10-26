// Developer regression: real isolated API; no camera and no live8443 mutations.
const fs=require('fs'),{spawn}=require('child_process');
const {chromium}=require('/Users/kapilgandhi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const token='developer-manual-ui-only';let browser,child;const results=[];
 try{
  child=spawn('.venv/bin/python',['-B','-u','-c','import server; from http.server import ThreadingHTTPServer; server.app=server.App("'+token+'"); server.vision=None; server.vision_error="Camera intentionally unavailable"; h=ThreadingHTTPServer(("127.0.0.1",0),server.Handler); print(h.server_port,flush=True); h.serve_forever()']);
  const port=await new Promise((resolve,reject)=>{child.stdout.once('data',b=>resolve(Number(b.toString().trim())));child.once('error',reject);});
  const origin='http://127.0.0.1:'+port;
  async function game(){return(await(await fetch(origin+'/api/state',{headers:{Authorization:'Bearer '+token}})).json()).game;}
  async function until(fn){for(let i=0;i<100;i++){if(await fn())return;await pause(50);}throw Error('Condition timed out');}
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/?t='+token);await page.locator('#cameraGame').uncheck();await page.locator('#newGame').click();await until(async()=>!!(await game()));
  async function dart(v,m=1){
   const n=(await game()).darts.length;await page.locator('#value').selectOption(String(v));
   if(v!==0)await page.locator('#multiplier').selectOption(String(m));
   await page.locator('#manual').click();await until(async()=>(await game()).darts.length===n+1);
  }
  async function next(){const player=(await game()).player;await page.locator('#next').click();await until(async()=>(await game()).player!==player);}
  for(let i=0;i<3;i++)await dart(20,3);await next();
  for(let i=0;i<3;i++)await dart(0);await next();
  await dart(20,3);await dart(20,3);await dart(1);
  await page.waitForFunction(()=>document.getElementById('turnStatus').textContent.includes('wins!'));
  if((await game()).scores[0]!==0||!await page.locator('#manual').isDisabled())throw Error('301 did not finish correctly');
  results.push({name:'full manual301 succeeds without camera; winner disables further throws',pass:true});
  await page.locator('#newGame').click();await until(async()=>(await game()).darts.length===0);
  await dart(20,3);await page.locator('#value').selectOption('0');
  if(!await page.locator('#multiplier').isDisabled()||await page.locator('#multiplier').inputValue()!=='1')throw Error('Miss did not normalize priorTriple');
  await dart(0);if((await game()).scores[0]!==241)throw Error('Miss score changed incorrectly');
  results.push({name:'T20 followed by Miss records zero with Single automatically',pass:true});
  await page.locator('#value').selectOption('20');await page.locator('#multiplier').selectOption('3');await page.locator('#value').selectOption('25');
  const tripleDisabled=await page.locator('#multiplier option[value="3"]').evaluate(option=>option.disabled);
  if(await page.locator('#multiplier').inputValue()!=='1'||!tripleDisabled||!(await page.locator('#manualScoreHelp').textContent()).includes('reset'))throw Error('Bull priorTriple normalization not explicit');
  await dart(25);if((await game()).scores[0]!==216)throw Error('Outerbull wrong');
  results.push({name:'Bull disables Triple, explains Single reset and records25',pass:true});
  page.once('dialog',dialog=>dialog.accept());await page.locator('#newGame').click();await until(async()=>(await game()).darts.length===0);
  await dart(25,2);if((await game()).scores[0]!==251)throw Error('Innerbull wrong');
  results.push({name:'Bull Double records50',pass:true});
  if(errors.length)throw Error(errors.join(';'));
  fs.writeFileSync('qa-artifacts/developer-manual-ui-results.json',JSON.stringify({isolated:true,results,errors},null,2)+'\n');
  console.log(JSON.stringify({results,errors},null,2));
 }finally{if(browser)await browser.close();if(child)child.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
