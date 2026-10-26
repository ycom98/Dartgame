const {run}=require('./manual_qa_common.cjs');
run('presentation-developer',async({page,origin,token,api,game,assert,until,pause})=>{
 await page.goto(origin+'/control?t='+token);
 await page.locator('#names input').nth(0).fill('Alex');await page.locator('#names input').nth(1).fill('Maya');
 await page.locator('#setup button[type=submit]').click();await until(async()=>!!await game());
 for(let i=0;i<3;i++){await page.locator('[data-ring="3"]').click();await page.locator('#record').click();await until(async()=>(await game()).darts.length===i+1);}
 assert((await game()).scores[0]===121,'180 deducted');await until(async()=>(await page.locator('#handoff').textContent()).includes('Next player'));
 await page.locator('#cancel').click();await pause(4300);assert((await game()).player===0,'Pause cancels handoff');
 await page.locator('#next').click();await until(async()=>(await game()).player===1);
 const state=(await api('state')).data;
 const display=await page.context().browser().newPage();await display.goto(origin+state.presentation_path);await display.waitForSelector('.hero .score');
 assert(await display.locator('.hero h1').textContent().then(x=>x.includes('Maya')),'Live spectator reflects current player');
 await display.setViewportSize({width:1920,height:1080});await display.screenshot({path:require('./qa_output.cjs').file('developer-presentation-tv.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Controller fits mobile');
 await display.close();const before=JSON.stringify(await game());await page.goto(origin+'/showcase');await page.waitForSelector('.hero');await page.locator('#pause').click();
 assert((await page.locator('.demo').textContent()).includes('DEMO'),'Showcase identified');assert(JSON.stringify(await game())===before,'Showcase isolated');
 return 'Start, 180, paused countdown, manual handoff, live view, mobile fit, isolated showcase';
});
