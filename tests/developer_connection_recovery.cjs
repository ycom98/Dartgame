// Developer regression: isolated mocked HTTP, no real app state or camera access.
const fs=require('fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch(process.env.DART_CHROME?{executablePath:process.env.DART_CHROME}:undefined);
 const results=[];
 try{
  const page=await browser.newPage();let offline=false,rejectScore=false;
  const html=fs.readFileSync('static/index.html','utf8');
  const state={game:{names:['A','B'],scores:[301,301],player:0,darts:[],winner:null,bust:false,turn:1},camera_game:false,vision:{fresh:false,aligned:false,verified:false,phase:'unavailable',message:'Camera intentionally unavailable',version:0}};
  await page.route('http://127.0.0.1:9876/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:html});
   if(offline)return route.abort();
   if(path==='/api/throw'&&rejectScore)return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Invalid board score'})});
   return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
  });
  await page.goto('http://127.0.0.1:9876/?t=isolated-recovery-test');
  await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Camera setup unavailable');
  offline=true;await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Server disconnected');
  offline=false;await page.waitForFunction(()=>document.getElementById('setupTitle').textContent==='Camera setup unavailable');
  const recovered=await page.evaluate(()=>!document.getElementById('manual').disabled&&getComputedStyle(document.getElementById('error')).display==='none');
  if(!recovered)throw Error('Recovered connection retained network banner or disabled score controls');
  results.push({name:'successful recovery clears network error and reenables manual controls',pass:true});
  rejectScore=true;await page.locator('#value').selectOption('20');await page.locator('#manual').click();
  await page.waitForFunction(()=>document.getElementById('error').textContent==='Invalid board score');
  await page.waitForTimeout(1300);
  const retained=await page.evaluate(()=>document.getElementById('error').textContent==='Invalid board score'&&getComputedStyle(document.getElementById('error')).display!=='none');
  if(!retained)throw Error('Successful heartbeat erased action validation error');
  results.push({name:'successful heartbeat preserves score validation error',pass:true});
  fs.writeFileSync(require('./qa_output.cjs').file('developer-recovery-results.json'),JSON.stringify({isolated:true,results},null,2)+'\n');
  console.log(JSON.stringify({results},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
