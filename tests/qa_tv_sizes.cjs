// M3 UI-07: the TV (/play) fits one screen at 1280x720, 1920x1080 and 3840x2160 (lobby, match, game shot),
// shows a styled reconnect banner when the Mac stops answering, and has a calm reduced-motion variant.
// Own ephemeral server, no camera.
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const {spawn} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const output = require('./qa_output.cjs');
const token = 'tv-sizes-qa';
const results = [], errors = [];
let browser, server;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(ok, message) { if (!ok) throw Error(message); }
async function waitFor(fn, limit = 6000) {
  const end = Date.now() + limit;
  while (Date.now() < end) { if (await fn()) return; await pause(40); }
  throw Error('Timed out: ' + String(fn).slice(0, 160));
}
async function run(name, fn) {
  const before = errors.length;
  try {
    const detail = await fn();
    check(errors.length === before, 'Page error: ' + errors.slice(before).join('; '));
    results.push({name, pass: true, detail});
  } catch (error) {
    results.push({name, pass: false, error: error.stack});
  }
}

const SIZES = [[1280, 720], [1920, 1080], [3840, 2160]];

(async () => {
  const port = await new Promise(resolve => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
  let started = '';
  const stateFile = process.env.DART_STATE_FILE || path.join(os.tmpdir(), 'dart-qa-' + process.pid + '-' + Date.now(), 'match.json');
  server = spawn(python, ['-B', '-c', 'import server;server.app=server.App("' + token + '");server.vision=None;' +
    'server.vision_error="QA no camera";server.main()', '--host', '127.0.0.1', '--port', String(port)],
  {cwd: root, env: {...process.env, DART_STATE_FILE: stateFile}, stdio: ['ignore', 'pipe', 'pipe']});
  server.stdout.on('data', chunk => { started += chunk; });
  server.stderr.on('data', chunk => errors.push('server: ' + chunk.toString().trim()));
  await waitFor(() => started.includes('Computer:'), 10000);
  const origin = 'http://127.0.0.1:' + port;
  async function api(endpoint, body) {
    const headers = {Authorization: 'Bearer ' + token};
    if (body === undefined) return (await fetch(origin + '/api/' + endpoint, {headers})).json();
    const state = await (await fetch(origin + '/api/state', {headers})).json();
    const response = await fetch(origin + '/api/' + endpoint, {method: 'POST', headers, body: JSON.stringify({expected_revision: state.revision, ...body})});
    return response.json();
  }
  async function throws(...darts) {
    for (const [value, multiplier] of darts) await api('throw', {value, multiplier});
  }
  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  const display = (await api('state')).presentation_path;

  async function measure(scene, ready) {
    const sizes = {};
    for (const [width, height] of SIZES) {
      const page = await browser.newPage({viewport: {width, height}});
      page.on('pageerror', error => errors.push(width + ': ' + error.message));
      await page.goto(origin + display);
      await page.waitForSelector(ready);
      await pause(scene === 'win' ? 4300 : 1800);  // after the stage animations
      const fit = await page.evaluate(() => ({
        overflowX: document.documentElement.scrollWidth - innerWidth,
        overflowY: document.documentElement.scrollHeight - innerHeight,
        score: document.querySelector('.hero .score')?.getBoundingClientRect().height || 0,
      }));
      check(fit.overflowX <= 0, `${scene} ${width}x${height}: horizontal overflow ${fit.overflowX}px`);
      check(fit.overflowY <= 1, `${scene} ${width}x${height}: page scrolls by ${fit.overflowY}px`);
      await page.screenshot({path: output.file(`ui-tv-${scene}-${width}x${height}.png`)});
      sizes[`${width}x${height}`] = fit;
      await page.close();
    }
    return sizes;
  }

  await run('lobby fits one screen at every TV size', async () => {
    await api('lobby', {open: true, players: ['Kapil', 'Maya', 'Jordan', 'Sam'], start: 501, double_out: true});
    return measure('lobby', '.lobby-live');
  });

  await run('a match with a checkout fits one screen at every TV size', async () => {
    await api('game', {names: ['Kapil', 'Maya', 'Jordan', 'Sam'], camera: false, start: 301, double_out: true});
    await throws([20, 3], [20, 3], [20, 3]);
    for (let player = 0; player < 3; player++) {
      await api('next', {});
      await throws([20, 1], [5, 1], [1, 1]);
    }
    await api('next', {});
    await throws([20, 3]);
    const sizes = await measure('match', '.checkout-line.has-route');
    check(sizes['3840x2160'].score > sizes['1920x1080'].score * 1.5, 'the score grows on a 4K screen');
    return sizes;
  });

  await run('the game-shot screen with statistics fits one screen at every TV size', async () => {
    await throws([11, 3], [14, 2]);
    check((await api('state')).game.winner === 0, 'Kapil won');
    return measure('win', '.match-stats');
  });

  await run('styled reconnect banner while the Mac does not answer; it clears by itself', async () => {
    const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
    page.on('pageerror', error => errors.push('banner: ' + error.message));
    await page.goto(origin + display);
    await page.waitForSelector('.hero .score');
    check(await page.locator('#reconnect').isHidden(), 'no banner while connected');
    await page.route('**/api/state', route => route.abort());
    await waitFor(async () => await page.locator('#reconnect').isVisible(), 8000);
    check((await page.locator('#reconnect').textContent()).includes('Reconnecting'), 'banner text');
    check(await page.locator('.hero .score').isVisible(), 'the last score stays on screen');
    await page.screenshot({path: output.file('ui-tv-reconnect-1920x1080.png')});
    await page.unroute('**/api/state');
    await waitFor(async () => await page.locator('#reconnect').isHidden(), 8000);
    await page.close();
    return {ok: true};
  });

  await run('reduced motion: no stage overlays, the score shows at once, BUST stays readable', async () => {
    const context = await browser.newContext({viewport: {width: 1920, height: 1080}, reducedMotion: 'reduce'});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push('reduced: ' + error.message));
    await api('game', {names: ['Kapil', 'Maya'], camera: false, start: 301, double_out: true});
    await page.goto(origin + display);
    await page.waitForSelector('.hero .score');
    await throws([20, 3], [20, 3], [20, 3]);
    await waitFor(async () => (await page.locator('.hero .score').textContent()) === '121');
    check(await page.locator('.match-stage.visible').count() === 0, 'no stage overlay');
    await api('next', {});
    await throws([20, 3], [20, 3], [20, 3], [20, 3]);  // the fourth is refused: Maya's turn is over
    await api('next', {});
    await throws([20, 3], [20, 3]);  // Kapil: 1 left in double out, bust
    await waitFor(async () => (await page.locator('.bust-badge').count()) === 1);
    const animation = await page.locator('.bust-badge').evaluate(e => getComputedStyle(e).animationName);
    check(animation === 'none', 'no stamp animation: ' + animation);
    await page.screenshot({path: output.file('ui-tv-reduced-motion-bust-1920x1080.png')});
    await context.close();
    return {ok: true};
  });
})().catch(error => { results.push({name: 'tv sizes harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    if (server) {
      server.kill('SIGTERM');
      await new Promise(resolve => { if (server.exitCode !== null) return resolve(); server.once('exit', resolve); setTimeout(resolve, 2000); });
    }
    fs.writeFileSync(output.file('ui-tv-sizes-results.json'), JSON.stringify({results, errors}, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
