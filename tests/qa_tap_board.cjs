// M1-11 tap-the-board scoring on /control: every scoring region, Miss, the 600 ms double-tap guard,
// and hit-box sizes at 360x740. Own ephemeral server, no camera.
const fs = require('fs');
const path = require('path');
const net = require('net');
const {spawn} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const artifacts = require('./qa_output.cjs').dir;
const token = 'tap-board-qa';
const results = [], errors = [];
let browser, server;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(ok, message) { if (!ok) throw Error(message); }
async function waitFor(fn, limit = 6000) {
  const end = Date.now() + limit;
  while (Date.now() < end) { if (await fn()) return; await pause(30); }
  throw Error('Timed out: ' + String(fn));
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

(async () => {
  fs.mkdirSync(artifacts, {recursive: true});
  const port = await new Promise(resolve => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
  let output = '';
  server = spawn(python, ['-B', '-c', 'import server;server.app=server.App("' + token + '");server.vision=None;' +
    'server.vision_error="QA no camera";server.main()', '--host', '127.0.0.1', '--port', String(port)],
  {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  server.stdout.on('data', chunk => { output += chunk; });
  server.stderr.on('data', chunk => errors.push('server: ' + chunk.toString().trim()));
  await waitFor(() => output.includes('Computer:'), 10000);
  const origin = 'http://127.0.0.1:' + port;
  async function api(endpoint, body) {
    const options = {headers: {Authorization: 'Bearer ' + token}};
    if (body !== undefined) { options.method = 'POST'; options.body = JSON.stringify(body); }
    return (await fetch(origin + '/api/' + endpoint, options)).json();
  }
  async function newGame() {
    const state = await api('state');
    return api('game', {names: ['Tap A', 'Tap B'], start: 501, double_out: false, camera: false,
      expected_revision: state.revision});
  }
  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);

  // Screen position of a hit region's target point.
  async function target(page, key) {
    return page.evaluate(k => {
      const hit = document.querySelector(`#tap-board .hit-region[data-key="${k}"]`);
      const [x, y] = hit.dataset.target.split(',').map(Number);
      const svg = hit.ownerSVGElement, p = svg.createSVGPoint();
      p.x = x; p.y = y;
      const screen = p.matrixTransform(svg.getScreenCTM());
      return {x: screen.x, y: screen.y};
    }, key);
  }

  await run('tapping each of the 62 scoring regions records that dart', async () => {
    const page = await browser.newPage({viewport: {width: 1100, height: 1000}});
    page.on('pageerror', error => errors.push(error.message));
    await newGame();
    await page.goto(origin + '/control?t=' + token);
    await page.waitForSelector('#tap-board .hit-region');
    const keys = [];
    for (const n of [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]) keys.push('Si' + n, 'D' + n, 'T' + n);
    keys.push('25', '50');
    check(keys.length === 62, 'region list');
    const misses = [];
    for (const key of keys) {
      let state = await api('state');
      const g = state.game;
      if (g.winner !== null) state = await newGame();
      else if (g.bust || g.darts.length === 3) state = await api('next', {expected_revision: state.revision});
      await waitFor(async () => !(await page.locator('#tap-board').getAttribute('class')).includes('disabled'));
      const before = state.revision;
      const point = await target(page, key);
      await page.mouse.click(point.x, point.y);
      await waitFor(async () => (await api('state')).revision === before + 1);
      const after = (await api('state')).game;
      const dart = after.darts[after.darts.length - 1];
      const expected = key === '25' ? [25, 1] : key === '50' ? [25, 2] :
        [Number(key.replace(/\D/g, '')), key.startsWith('T') ? 3 : key.startsWith('D') ? 2 : 1];
      if (!dart || dart.value !== expected[0] || dart.multiplier !== expected[1]) misses.push({key, dart});
      await pause(620);  // past the 600 ms duplicate-tap guard
    }
    check(misses.length === 0, 'Wrong darts: ' + JSON.stringify(misses));
    await page.screenshot({path: path.join(artifacts, 'M1-11-control-1100.png'), fullPage: true});
    await page.close();
    return {regions: keys.length};
  });

  await run('Miss records 0 and a double tap within 600 ms records one dart', async () => {
    const page = await browser.newPage({viewport: {width: 1100, height: 1000}});
    page.on('pageerror', error => errors.push(error.message));
    let state = await newGame();
    await page.goto(origin + '/control?t=' + token);
    await page.waitForSelector('#tap-board .hit-region');
    await waitFor(async () => !(await page.locator('#miss').isDisabled()));
    await page.locator('#miss').click();
    await waitFor(async () => (await api('state')).revision === state.revision + 1);
    state = await api('state');
    check(state.game.darts[0].value === 0 && state.game.darts[0].score === 0, 'Miss scored 0');
    await pause(650);
    const point = await target(page, 'T20');
    await page.mouse.click(point.x, point.y);
    await pause(100);
    await page.mouse.click(point.x, point.y);
    await pause(900);
    const after = await api('state');
    check(after.revision === state.revision + 1 && after.game.darts.length === 2, 'Double tap recorded ' +
      (after.game.darts.length - 1) + ' darts');
    await page.close();
    return {darts: after.game.darts};
  });

  await run('at 360x740 every hit region is at least 24 x 24 px and taps work by touch', async () => {
    const context = await browser.newContext({viewport: {width: 360, height: 740}, isMobile: true, hasTouch: true});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const state = await newGame();
    await page.goto(origin + '/control?t=' + token);
    await page.waitForSelector('#tap-board .hit-region');
    const boxes = await page.$$eval('#tap-board .hit-region', nodes => nodes.map(n => {
      const r = n.getBoundingClientRect();
      return {key: n.dataset.key, width: r.width, height: r.height};
    }));
    check(boxes.length === 82, 'Expected 82 hit regions, got ' + boxes.length);
    const small = boxes.filter(b => b.width < 24 || b.height < 24);
    check(small.length === 0, 'Too small: ' + JSON.stringify(small));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(overflow <= 0, 'Horizontal overflow ' + overflow + ' px');
    // Live demo finding: on a phone the controller shows compact status, not the full scoreboard (was ~5,300 px).
    const pageHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    check(await page.locator('#match').isHidden(), 'Full scoreboard hidden on a phone');
    check(await page.locator('#compact-status').textContent().then(t => t.includes('Tap A') && t.includes('501')), 'Compact status');
    check(pageHeight < 2400, 'Controller page is ' + pageHeight + ' px tall at 360 px');
    await page.locator('#tap-board').scrollIntoViewIfNeeded();
    await waitFor(async () => !(await page.locator('#tap-board').getAttribute('class')).includes('disabled'));
    const point = await target(page, 'D16');
    await page.touchscreen.tap(point.x, point.y);
    await waitFor(async () => (await api('state')).revision === state.revision + 1);
    const dart = (await api('state')).game.darts[0];
    check(dart.value === 16 && dart.multiplier === 2, 'Touch tap recorded ' + JSON.stringify(dart));
    await page.screenshot({path: path.join(artifacts, 'M1-11-control-360.png'), fullPage: true});
    const smallest = boxes.reduce((a, b) => Math.min(a.width, a.height) < Math.min(b.width, b.height) ? a : b);
    await context.close();
    return {smallest};
  });

  // QA Q1: what you see is what you tap. Samples the VISIBLE board (painted pixel colour, sector from the
  // point's angle) at region middles, on a grid and 3 px from every wire (closer, antialiasing blends the
  // painted colours), against the element a tap there hits, and taps a subset for real. The QA defect zones
  // were 4-8 px wide.
  await run('the visible board and the recorded score agree everywhere, including next to wires', async () => {
    const context = await browser.newContext({viewport: {width: 360, height: 740}, isMobile: true, hasTouch: true,
      deviceScaleFactor: 1});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    let state = await newGame();
    await page.goto(origin + '/control?t=' + token);
    await page.waitForSelector('#tap-board .hit-region');
    await page.locator('#tap-board').scrollIntoViewIfNeeded();
    await waitFor(async () => !(await page.locator('#tap-board').getAttribute('class')).includes('disabled'));
    const shot = (await page.screenshot()).toString('base64');
    const samples = await page.evaluate(async png => {
      const svg = document.querySelector('#tap-board svg'), ctm = svg.getScreenCTM(), scale = ctm.a;
      const image = new Image();
      await new Promise(resolve => { image.onload = resolve; image.src = 'data:image/png;base64,' + png; });
      const canvas = document.createElement('canvas');
      canvas.width = image.width; canvas.height = image.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(image, 0, 0);
      const box = svg.getBoundingClientRect(), cx = box.left + box.width / 2, cy = box.top + box.height / 2;
      const fills = {'#a34440': 'red', '#548274': 'green', '#c6bfa9': 'cream', '#25322e': 'dark'};
      const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
      const nearest = pixel => Object.entries(fills).map(([hex, name]) =>
        [rgb(hex).reduce((sum, v, i) => sum + (v - pixel[i]) ** 2, 0), name]).sort((a, b) => a[0] - b[0])[0];
      // Points in board units (viewBox, centre 220,220): radii 1.5 px either side of every ring edge, region
      // middles, and a grid; angles at sector middles and 1.5 px from each radial wire.
      const pad = 3 / scale, edges = [16, 40, 100, 132, 170, 204], points = [];
      for (let k = 0; k < 20; k++) {
        const middle = k * 18;
        for (const r of [8, 28, 70, 116, 151, 187, ...edges.flatMap(e => [e - pad, e + pad]).filter(r => r < 204 && r > 0)]) {
          const wire = Math.asin(Math.min(1, pad / Math.max(r, 1))) * 180 / Math.PI;
          for (const a of r > 40 ? [middle, middle - 9 + wire, middle + 9 - wire] : [middle]) points.push([r, a]);
        }
      }
      for (let x = 22; x < 420; x += 9) for (let y = 22; y < 420; y += 9) {
        const r = Math.hypot(x - 220, y - 220), a = Math.atan2(x - 220, 220 - y) * 180 / Math.PI;
        const fromRadialWire = r * Math.sin(Math.abs(((a + 9) % 18 + 18) % 18 - 9 > 0 ? 9 - (((a + 9) % 18 + 18) % 18 - 9) : ((a + 9) % 18 + 18) % 18) * Math.PI / 180);
        if (r < 202 && edges.every(e => Math.abs(r - e) > pad) && (r < 40 || fromRadialWire > pad)) points.push([r, a]);
      }
      const sectors = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];
      return points.map(([r, a]) => {
        const sx = cx + Math.sin(a * Math.PI / 180) * r * scale, sy = cy - Math.cos(a * Math.PI / 180) * r * scale;
        const element = document.elementFromPoint(sx, sy)?.closest('.hit-region');
        const [distance, colour] = nearest(ctx.getImageData(Math.round(sx), Math.round(sy), 1, 1).data);
        const sector = sectors[Math.floor((((a % 360) + 360 + 9) % 360) / 18) % 20];
        return {r: +r.toFixed(2), a: +a.toFixed(2), x: sx, y: sy, colour, distance, sector,
          key: element?.dataset.key, value: element ? +element.dataset.value : null,
          multiplier: element ? +element.dataset.multiplier : null, fill: element?.getAttribute('fill')};
      });
    }, shot);
    const fills = {'#a34440': 'red', '#548274': 'green', '#c6bfa9': 'cream', '#25322e': 'dark'};
    const wrong = samples.filter(p => {
      if (!p.key) return true;                                   // a visible board point that records nothing
      if (fills[p.fill] !== p.colour) return true;               // the tap hits a region not painted there
      const ringColour = p.colour === 'red' || p.colour === 'green';
      if (p.value === 25) return !ringColour;
      if (ringColour !== (p.multiplier > 1)) return true;        // a single shown, a double/treble recorded (or back)
      return p.value !== p.sector;                               // another sector than the one shown
    });
    check(wrong.length === 0, wrong.length + ' of ' + samples.length + ' visible points record another score: ' +
      JSON.stringify(wrong.slice(0, 5)));
    // Real taps next to wires, checked through the API.
    const nearWire = samples.filter(p => p.r % 1 !== 0 && p.r < 204).filter((p, i) => i % 9 === 0).slice(0, 24);
    const tapped = [], boardTop = async () => (await page.locator('#tap-board svg').boundingBox()).y;
    const top = await boardTop();
    for (const p of nearWire) {
      state = await api('state');
      const g = state.game;
      if (g.winner !== null) state = await newGame();
      else if (g.bust || g.darts.length === 3) state = await api('next', {expected_revision: state.revision});
      await waitFor(async () => !(await page.locator('#tap-board').getAttribute('class')).includes('disabled'));
      check(Math.abs(await boardTop() - top) < 0.5, 'The board moved ' + (await boardTop() - top) + ' px during play');
      await page.touchscreen.tap(p.x, p.y);
      await waitFor(async () => (await api('state')).revision === state.revision + 1);
      const darts = (await api('state')).game.darts, dart = darts[darts.length - 1];
      tapped.push({...p, recorded: [dart.value, dart.multiplier]});
      check(dart.value === p.value && dart.multiplier === p.multiplier,
        'Tap at r=' + p.r + ' a=' + p.a + ' (' + p.colour + ' ' + p.key + ') recorded ' + JSON.stringify(dart));
      await pause(620);
    }
    await context.close();
    return {visiblePointsChecked: samples.length, nearWireTaps: tapped.length};
  });

  await run('keypad entry is still available as a fallback', async () => {
    const page = await browser.newPage({viewport: {width: 1100, height: 1000}});
    page.on('pageerror', error => errors.push(error.message));
    const state = await newGame();
    await page.goto(origin + '/control?t=' + token);
    await page.waitForSelector('#keypad');
    check(await page.locator('#keypad summary').textContent() === 'Keypad entry', 'Keypad summary');
    await waitFor(async () => !(await page.locator('#record').isDisabled()));
    await page.locator('#value').selectOption('19');
    await page.locator('[data-ring="3"]').click();
    await page.locator('#record').click();
    await waitFor(async () => (await api('state')).revision === state.revision + 1);
    check((await api('state')).game.darts[0].score === 57, 'Keypad T19');
    await page.close();
    return {ok: true};
  });
})().catch(error => { results.push({name: 'tap board harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    if (server) {
      server.kill('SIGTERM');
      await new Promise(resolve => { if (server.exitCode !== null) return resolve(); server.once('exit', resolve); setTimeout(resolve, 2000); });
    }
    fs.mkdirSync(artifacts, {recursive: true});
    fs.writeFileSync(path.join(artifacts, 'M1-11-tap-board-results.json'), JSON.stringify({testOnly: true, results, errors}, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
