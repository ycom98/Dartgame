// M1-13 camera setup QA: the Mac setup page against a pulled sim stream (no phone, no browser camera).
// Scenario A follows the plan's acceptance flow: server started with --camera dir:<sim frames>, then
// test connection -> freeze -> four clicks -> verify, counting user actions, and checks the drawn r=170 ring
// against the sim camera's own projection. Scenario B types a phone address for a fake IP Webcam stream.
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const {spawn, execFileSync} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const artifacts = require('./qa_output.cjs').dir;
const token = 'camera-setup-qa';
const results = [], errors = [];
const children = [];
let browser;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(ok, message) { if (!ok) throw Error(message); }
async function waitFor(fn, limit = 8000) {
  const end = Date.now() + limit;
  while (Date.now() < end) { if (await fn()) return; await pause(50); }
  throw Error('Timed out: ' + String(fn));
}
async function run(name, fn) {
  const before = errors.length;
  try {
    const detail = await fn();
    check(errors.length === before, 'Unexpected page error: ' + errors.slice(before).join('; '));
    results.push({name, pass: true, detail});
  } catch (error) {
    results.push({name, pass: false, error: error.stack});
  }
}
function freePort() {
  return new Promise(resolve => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}
function start(args, ready) {
  const child = spawn(python, args, {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  children.push(child);
  let output = '';
  child.stdout.on('data', chunk => { output += chunk.toString(); });
  child.stderr.on('data', chunk => { errors.push('child stderr: ' + chunk.toString().trim()); });
  return waitFor(() => output.includes(ready), 15000).then(() => child);
}

// Sim frames and the sim camera's ground truth, written by Python.
const SIM_CODE = `
import json, math, sys, cv2, numpy as np
from sim import camera_for_mount
from sim.scene import calibration_points, render_clean
folder = sys.argv[1]
camera = camera_for_mount('left', 1280, 720)
cv2.imwrite(folder + '/frame-000.png', render_clean(camera, []))
angles = [2 * math.pi * i / 72 for i in range(72)]
ring = camera.project_plane(np.array([[170 * math.cos(a), 170 * math.sin(a)] for a in angles]))
print(json.dumps({'points': calibration_points(camera).tolist(), 'ring170': np.asarray(ring).tolist()}))
`;

(async () => {
  fs.mkdirSync(artifacts, {recursive: true});
  const simFolder = fs.mkdtempSync(path.join(os.tmpdir(), 'dart-sim-'));
  const truth = JSON.parse(execFileSync(python, ['-B', '-c', SIM_CODE, simFolder], {cwd: root}).toString());
  const port = await freePort(), fakePort = await freePort();
  // No --http flag: plain HTTP is the default now.
  await start(['-B', '-c', 'import server;server.app=server.App("' + token + '");server.main()',
    '--host', '127.0.0.1', '--port', String(port), '--camera', 'dir:' + simFolder + '?loop=1&fps=10'], 'Computer:');
  const origin = 'http://127.0.0.1:' + port;
  async function api(endpoint, body) {
    const options = {headers: {Authorization: 'Bearer ' + token}};
    if (body !== undefined) { options.method = 'POST'; options.body = JSON.stringify(body); }
    const response = await fetch(origin + '/api/' + endpoint, options);
    return response.json();
  }
  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(error.message));
  const title = () => page.locator('#setupTitle').textContent();

  await run('static pages contain no browser camera code', async () => {
    const hits = fs.readdirSync(path.join(root, 'static'))
      .filter(name => fs.readFileSync(path.join(root, 'static', name), 'utf8').includes('getUserMedia'));
    check(hits.length === 0, 'getUserMedia found in ' + hits.join(', '));
    return {checked: fs.readdirSync(path.join(root, 'static')).length};
  });

  await run('A: source -> freeze -> four clicks -> verify reaches ready in at most 7 actions', async () => {
    await page.goto(origin + '/?t=' + token);
    await waitFor(async () => await title() === 'Ready to calibrate');
    await waitFor(async () => (await page.locator('#readyCamera').getAttribute('class') || '').includes('done'));
    check((await page.locator('#sourceUri').inputValue()).startsWith('dir:'), 'Source field shows the running source');
    let actions = 0;
    await page.locator('#testSource').click(); actions++;
    await waitFor(async () => (await page.locator('#sourceStatus').textContent()).includes('Connection OK'));
    await page.locator('#calibrate').click(); actions++;
    await waitFor(async () => (await title()).includes('0/4'));
    const box = await page.locator('#board').boundingBox();
    const toCanvas = ([x, y]) => ({x: x / 1280 * box.width, y: y / 720 * box.height});
    await page.locator('#board').hover({position: toCanvas(truth.points[0])});
    check(await page.locator('#loupe').isVisible(), 'Magnifier loupe shows at the cursor while selecting');
    for (const point of truth.points) { await page.locator('#board').click({position: toCanvas(point)}); actions++; }
    await waitFor(async () => await title() === 'Check the live markers');
    await waitFor(async () => !(await page.locator('#verify').isDisabled()));
    const overlay = (await api('state')).vision.overlay;
    const drawn = await page.evaluate(o => window.setupOverlay.ringPoints(o, 170, 72), overlay);
    const ringError = Math.max(...drawn.map(([u, v], i) => Math.hypot(u - truth.ring170[i][0], v - truth.ring170[i][1])));
    check(ringError <= 3, 'Overlay r=170 ring is ' + ringError.toFixed(2) + ' px from the sim ring');
    await page.screenshot({path: path.join(artifacts, 'M1-13-setup-overlay-review.png'), fullPage: true});
    await page.locator('#verify').click(); actions++;
    await waitFor(async () => await title() === 'Ready to play');
    const state = await api('state');
    check(state.vision.phase === 'ready', 'Server phase is ready');
    check(actions <= 7, 'Took ' + actions + ' actions');
    for (const id of ['readyCamera', 'readyCalibrated', 'readyAligned', 'readyVerified']) {
      check((await page.locator('#' + id).getAttribute('class') || '').includes('done'), id + ' is ticked');
    }
    check(/cm/.test(await page.locator('#footText').textContent()), 'Camera position is described');
    await page.screenshot({path: path.join(artifacts, 'M1-13-setup-ready.png'), fullPage: true});
    return {actions, ringErrorPx: +ringError.toFixed(2), foot: state.vision.foot, pose: state.vision.pose?.source};
  });

  await run('mount side override is shown and sent to the server', async () => {
    await page.locator('#mountSide').selectOption('left');
    await waitFor(async () => (await api('state')).vision.mount_side === 'left');
    await page.locator('#mountSide').selectOption('');
    await waitFor(async () => (await api('state')).vision.mount_side === null);
    return {ok: true};
  });

  await run('B: typing the phone IP builds the IP Webcam address; test, connect, realign, verify', async () => {
    await start(['-B', 'tests/fake_ipwebcam.py', '--port', String(fakePort), '--mount', 'left',
      '--width', '1280', '--height', '720'], 'Fake IP Webcam');
    await page.locator('#phoneIp').fill('127.0.0.1:' + fakePort);
    check(await page.locator('#sourceUri').inputValue() === 'http://127.0.0.1:' + fakePort + '/video',
      'IP Webcam preset builds http://IP:PORT/video');
    await page.locator('#sourcePreset').selectOption('snapshot');
    check(await page.locator('#sourceUri').inputValue() === 'snapshot:http://127.0.0.1:' + fakePort + '/shot.jpg',
      'Snapshot preset builds snapshot:http://IP:PORT/shot.jpg');
    await page.locator('#sourcePreset').selectOption('ipwebcam');
    await page.locator('#testSource').click();
    await waitFor(async () => (await page.locator('#sourceStatus').textContent()).includes('Connection OK · 1280×720'));
    await page.locator('#connectSource').click();
    await waitFor(async () => {
      const source = (await api('state')).vision.source;
      return source && source.kind === 'mjpeg' && source.connected;
    });
    await waitFor(async () => (await page.locator('#sourceStatus').textContent()).includes('connected ·'));
    await waitFor(async () => await title() === 'Check alignment');
    await page.locator('#align').click();
    await waitFor(async () => await title() === 'Check the live markers');
    await waitFor(async () => !(await page.locator('#verify').isDisabled()));
    await page.locator('#verify').click();
    await waitFor(async () => await title() === 'Ready to play');
    const source = (await api('state')).vision.source;
    check(source.fps >= 12, 'Stream runs at >= 12 fps (got ' + source.fps + ')');
    await page.screenshot({path: path.join(artifacts, 'M1-13-setup-ipwebcam.png'), fullPage: true});
    return {fps: source.fps, processed_fps: source.processed_fps, last_frame_age: source.last_frame_age};
  });

  await run('a wrong address gives a clear error and changes nothing', async () => {
    const before = (await api('state')).vision.source.url_redacted;
    await page.locator('#sourceUri').fill('http://127.0.0.1:9/video');
    await page.locator('#testSource').click();
    await waitFor(async () => /Connection test failed/.test(await page.locator('#error').textContent()));
    check((await api('state')).vision.source.url_redacted === before, 'Testing did not switch the source');
    return {message: await page.locator('#error').textContent()};
  });

  await run('disconnect stops pulling frames', async () => {
    await page.locator('#disconnectSource').click();
    await waitFor(async () => (await api('state')).vision.source === null);
    await waitFor(async () => (await page.locator('#sourceStatus').textContent()).includes('No camera connected'));
    return {ok: true};
  });

  await run('setup page fits a phone-width screen', async () => {
    const small = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    small.on('pageerror', error => errors.push(error.message));
    await small.goto(origin + '/?t=' + token);
    await small.waitForSelector('#sourceUri');
    const sizing = await small.evaluate(() => ({width: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth}));
    check(sizing.content <= sizing.width, 'Horizontal overflow ' + JSON.stringify(sizing));
    await small.screenshot({path: path.join(artifacts, 'M1-13-setup-390.png'), fullPage: true});
    await small.close();
    return sizing;
  });
})().catch(error => { results.push({name: 'camera setup harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    for (const child of children) {
      child.kill('SIGTERM');
      await new Promise(resolve => { if (child.exitCode !== null) return resolve(); child.once('exit', resolve); setTimeout(resolve, 2000); });
    }
    fs.mkdirSync(artifacts, {recursive: true});
    const evidence = {testOnly: true, media: 'sim/ renders served by dir: and by tests/fake_ipwebcam.py; no phone, no webcam',
      network: 'own ephemeral localhost servers over plain HTTP', results, errors};
    fs.writeFileSync(path.join(artifacts, 'M1-13-camera-setup-results.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
