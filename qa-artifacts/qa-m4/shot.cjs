// usage: node shot.cjs origin token displayToken outPrefix
const {chromium} = require('playwright');
const [origin, token, display, prefix] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const phone = await browser.newPage({viewport: {width: 390, height: 844}, deviceScaleFactor: 2, isMobile: true, hasTouch: true});
  phone.on('pageerror', e => errors.push('control: ' + e.message));
  await phone.goto(origin + '/control?t=' + token);
  await phone.waitForTimeout(2500);
  const info = await phone.evaluate(() => {
    const q = s => document.querySelector(s);
    const panel = q('#camera-panel');
    return {
      headline: q('#pending')?.textContent, detail: q('#pending-detail')?.textContent,
      panelCheck: panel?.classList.contains('check'),
      headlineColor: q('#pending') && getComputedStyle(q('#pending')).color,
      markers: [...document.querySelectorAll('#tap-board .pending-marker')].map(m => ({cls: m.getAttribute('class'),
        dash: getComputedStyle(m).strokeDasharray, stroke: getComputedStyle(m).stroke})),
      acceptVisible: q('#accept') && getComputedStyle(q('#accept')).visibility,
      scrollW: document.documentElement.scrollWidth,
      tapBoardTop: q('#tap-board')?.getBoundingClientRect().top,
    };
  });
  await phone.screenshot({path: prefix + '-control-390.png', fullPage: true});
  const tv = await browser.newPage({viewport: {width: 1920, height: 1080}});
  tv.on('pageerror', e => errors.push('tv: ' + e.message));
  await tv.goto(origin + '/play?t=' + display);
  await tv.waitForTimeout(2500);
  const tvInfo = await tv.evaluate(() => ({text: document.body.innerText.slice(0, 600),
    pendingShown: /then|Camera:|possibly hidden|check/i.test(document.body.innerText),
    scrollW: document.documentElement.scrollWidth, scrollH: document.documentElement.scrollHeight}));
  await tv.screenshot({path: prefix + '-tv-1080.png'});
  console.log(JSON.stringify({info, tvInfo, errors}));
  await browser.close();
})();
