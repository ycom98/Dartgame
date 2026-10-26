// Independent QA. Isolated ephemeral HTTP server, fresh Chrome profile, no real media.
const fs=require('fs'),path=require('path'),net=require('net'),{spawn}=require('child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),token='presentation-qa-only',delay=ms=>new Promise(r=>setTimeout(r,ms));
const result={checks:[],screenshots:[],errors:[]};
function assert(v,m){if(!v)throw Error(m)}
async function until(fn,ms=6000){let end=Date.now()+ms;while(Date.now()<end){if(await fn())return;await delay(40)}throw Error('Timed out: '+String(fn).slice(0,140))}
let child,browser,context,origin;
async function api(action,body,auth=token){let r=await fetch(origin+'/api/'+action,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+auth,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return{status:r.status,data:await r.json()}}
async function state(){return(await api('state')).data}
async function begin(start=301,double=false){let r=await api('game',{names:['Ada','Lin'],camera:false,start,double_out:double});assert(r.status===200,'start game');await delay(1200);return r.data}
async function dart(v,m=1){let s=await state();let r=await api('throw',{value:v,multiplier:m,expected_revision:s.revision});assert(r.status===200,'api throw '+JSON.stringify(r));return r.data}
async function next(){let s=await state(),r=await api('next',{expected_revision:s.revision});assert(r.status===200,'api next');return r.data}
async function undo(){let s=await state(),r=await api('undo',{expected_revision:s.revision});assert(r.status===200,'api undo');return r.data}
async function check(name,fn){await fn();result.checks.push(name);fs.writeFileSync(require('./qa_output.cjs').file('presentation-results.json'),JSON.stringify(result,null,2))}
(async()=>{try{
const port=await new Promise(r=>{let s=net.createServer();s.listen(0,'127.0.0.1',()=>{let p=s.address().port;s.close(()=>r(p))})});let startup='',stderr='';
child=spawn(process.env.DART_PYTHON||root+'/.venv/bin/python',['-B','-c','import server;server.app=server.App("'+token+'");server.vision=None;server.vision_error="QA no camera";server.main()','--http','--host','127.0.0.1','--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});child.stdout.on('data',d=>startup+=d);child.stderr.on('data',d=>stderr+=d);await until(()=>startup.includes('Computer:'));origin='http://127.0.0.1:'+port;
browser=await chromium.launch(process.env.DART_CHROME?{executablePath:process.env.DART_CHROME}:undefined);context=await browser.newContext({viewport:{width:1280,height:900}});
await context.addInitScript(()=>{window.mediaCalls=0;Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:()=>{window.mediaCalls++;throw Error('QA forbids camera')}}})});
context.on('page',p=>p.on('pageerror',e=>result.errors.push(e.message)));
context.setDefaultTimeout(6000);let host=await context.newPage();host.on('dialog',d=>d.accept());host.on('response',async r=>{if(r.url().includes('/api/')&&r.request().method()==='POST')result.lastPosts=(result.lastPosts||[]).concat([{status:r.status(),body:r.request().postData(),response:await r.text()}]).slice(-8)});await host.goto(origin+'/control?t='+token);await begin();
let s=await state(),view=s.presentation_path||('/play?t='+token);const spectators=[await context.newPage(),await context.newPage()];const spectatorWrites=[];for(let p of spectators){p.on('request',r=>{if(r.method()!=='GET')spectatorWrites.push(r.url())});await p.goto(origin+view)}
const spectatorSync=async n=>{for(let p of spectators)await until(async()=>await p.locator('.hero .score').textContent()===String(n))};

await check('delayed old poll cannot roll controller back after successful score',async()=>{
 await host.locator('#auto').uncheck();let release,captured=false;let gate=new Promise(r=>release=r);await host.route('**/api/state',async route=>{let response=await route.fetch();captured=true;await gate;await route.fulfill({response});});await until(()=>captured);await host.locator('#record').click();await until(async()=>(await state()).game.darts.length===1);await until(async()=>await host.locator('.hero .score').textContent()==='281');release();await delay(300);assert(await host.locator('.hero .score').textContent()==='281','stale state rolled back score');await host.unroute('**/api/state');
});
await check('lost mutation acknowledgement reconciles once without repeating dart',async()=>{
 await begin();let posts=0;await host.route('**/api/throw',async route=>{posts++;await route.fetch();await route.abort('failed')});await host.locator('#record').click();await until(async()=>await host.locator('.hero .score').textContent()==='281');await delay(1600);assert(posts===1,'lost ack retried POST');assert((await state()).game.darts.length===1,'lost ack doubled dart');await host.unroute('**/api/throw');
});
await check('501 four long names layouts and real reduced-motion animation suppression',async()=>{
 await api('game',{names:['Alexandria Catherine Northwood','Maximilian Bartholomew Kings','Christopher Sebastian Johnson','Elizabeth Alexandra Montgomery'],start:501,camera:false});await delay(1200);let p=spectators[0];for(let width of [320,390,736,1280,1920]){await p.setViewportSize({width,height:1080});assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'long names overflow '+width);assert(await p.locator('.player').count()===4,'four standings visible');await host.setViewportSize({width,height:1080});assert(await host.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'host long names overflow '+width)}await p.emulateMedia({reducedMotion:'reduce'});await p.evaluate(()=>document.querySelector('.hero .score').classList.add('score-pop'));assert(await p.locator('.hero .score').evaluate(e=>getComputedStyle(e).animationName)==='none','reduced motion disables animation');
});
assert(result.errors.length===0,'browser errors');result.pass=true;
}catch(e){result.pass=false;result.failure=e.stack;process.exitCode=1}finally{if(browser)await browser.close();if(child)child.kill('SIGTERM');fs.writeFileSync(require('./qa_output.cjs').file('presentation-resilience-results.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2))}})();
