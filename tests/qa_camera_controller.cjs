// M1-12 camera darts on /control: pending dart with countdown, auto-accept, Accept, one-tap correction of
// a (deliberately treated as) wrong detection, two-tap correction of a committed dart, filled-in misses,
// and /play never showing a pending dart. The phone is tests/fake_ipwebcam.py serving sim/ scenes.
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const {spawn, execFileSync} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const artifacts = require('./qa_output.cjs').dir;
const token = 'camera-controller-qa';
const results = [], errors = [], children = [];
let browser;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(ok, message) { if (!ok) throw Error(message); }
async function waitFor(fn, limit = 8000, step = 30) {
  const end = Date.now() + limit;
  while (Date.now() < end) { if (await fn()) return; await pause(step); }
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
function freePort() {
  return new Promise(resolve => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}
async function start(args, ready) {
  const child = spawn(python, args, {cwd: root,env:{...process.env,DART_STATE_FILE:process.env.DART_STATE_FILE||require('path').join(require('os').tmpdir(),'dart-qa-'+process.pid+'-'+Date.now(),'match.json')}/* M1-16: never the real saved match */, stdio: ['ignore', 'pipe', 'pipe']});
  children.push(child);
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => errors.push('child: ' + chunk.toString().trim()));
  await waitFor(() => output.includes(ready), 15000);
  return output;
}

const SCENES = `
import json, sys, cv2
from sim import camera_for_mount
from sim.scene import Dart, calibration_points, render_clean
folder = sys.argv[1]
camera = camera_for_mount('left', 1280, 720)
darts = [Dart(x=40.0, y=-60.0, tilt=12.0), Dart(x=-70.0, y=95.0, tilt=10.0), Dart(x=98.0, y=31.8, tilt=12.0)]
for k in range(4):
    cv2.imwrite(f'{folder}/scene-{k}.png', render_clean(camera, darts[:k]))
print(json.dumps({'points': calibration_points(camera).tolist()}))
`;

(async () => {
  fs.mkdirSync(artifacts, {recursive: true});
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'dart-scenes-'));
  const sim = JSON.parse(execFileSync(python, ['-B', '-c', SCENES, folder], {cwd: root}).toString());
  const fakePort = await freePort(), port = await freePort();
  await start(['-B', 'tests/fake_ipwebcam.py', '--port', String(fakePort), '--scenes', folder], 'Fake IP Webcam');
  const fake = 'http://127.0.0.1:' + fakePort;
  const output = await start(['-B', '-c', 'import server;server.app=server.App("' + token + '");server.main()',
    '--host', '127.0.0.1', '--port', String(port), '--camera', fake + '/video', '--auto-commit', '3'], 'Camera source:');
  const origin = 'http://127.0.0.1:' + port;
  const displayPath = output.match(/\/play\?t=\S+/)[0];
  async function api(endpoint, body) {
    const options = {headers: {Authorization: 'Bearer ' + token}};
    if (body !== undefined) {
      const state = await (await fetch(origin + '/api/state', options)).json();
      options.method = 'POST';
      options.body = JSON.stringify({expected_revision: state.revision, ...body});
    }
    const response = await fetch(origin + '/api/' + endpoint, options);
    const data = await response.json();
    if (!response.ok) throw Error(endpoint + ': ' + data.error);
    return data;
  }
  const scene = k => fetch(fake + '/scene?n=' + k);
  const game = async () => (await api('state')).game;
  const lastCommit = async () => (await api('events')).events.filter(e => e.type === 'commit').pop();

  // Calibrate and start a camera game through the API (the setup page is covered by qa_camera_startup).
  await waitFor(async () => (await api('state')).vision.fresh, 8000);
  const started = await api('calibration/start', {});
  const calibrated = await api('calibrate', {snapshot_id: started.snapshot.snapshot_id, points: sim.points});
  await api('verify', {version: calibrated.vision.version});
  await api('game', {names: ['Cam A', 'Cam B'], camera: true, start: 501});

  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  const page = await browser.newPage({viewport: {width: 1100, height: 1100}});
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin + '/control?t=' + token);
  await page.waitForSelector('#camera-panel:not([hidden])');
  await page.locator('#auto').uncheck();  // keep the turn on screen for the corrections below
  const play = await browser.newPage({viewport: {width: 1280, height: 800}});
  play.on('pageerror', error => errors.push('play: ' + error.message));
  await play.goto(origin + displayPath);
  const pendingText = () => page.locator('#pending').textContent();
  async function tap(key) {
    const point = await page.evaluate(k => {
      const hit = document.querySelector(`#tap-board .hit-region[data-key="${k}"]`);
      const [x, y] = hit.dataset.target.split(',').map(Number);
      const svg = hit.ownerSVGElement, p = svg.createSVGPoint();
      p.x = x; p.y = y;
      const s = p.matrixTransform(svg.getScreenCTM());
      return {x: s.x, y: s.y};
    }, key);
    await page.mouse.click(point.x, point.y);
  }

  await run('dart 1: pending shows within 1.5 s with a countdown, then auto-accepts', async () => {
    const served = Date.now();
    await scene(1);
    await waitFor(async () => (await pendingText()).includes('Camera: S18'), 5000, 20);
    const latency = (Date.now() - served) / 1000;
    check(/auto-accept in \d\.\d s/.test(await pendingText()), 'Countdown shown: ' + await pendingText());
    check(await page.locator('#accept').isVisible(), 'Accept visible');
    check(await play.locator('.darts .dart.filled').count() === 0, '/play shows no pending dart');
    await page.screenshot({path: path.join(artifacts, 'M1-12-control-pending.png'), fullPage: true});
    check(latency <= 1.5, 'Pending dart appeared after ' + latency + ' s');
    await waitFor(async () => (await game()).darts.length === 1, 6000);
    const commit = await lastCommit();
    check(commit.source === 'auto' && commit.dart.score === 18, 'Auto commit ' + JSON.stringify(commit));
    await waitFor(async () => (await page.locator('#turn-darts').textContent()).includes('Dart 1: Single 18'));
    return {pendingVisibleAfterSeconds: latency};
  });

  await run('dart 2: Accept commits exactly the shown detection (auto-accept paused)', async () => {
    await page.locator('#auto-pause').click();
    await waitFor(async () => (await api('state')).camera.auto_commit.paused);
    await scene(2);
    await waitFor(async () => (await pendingText()).includes('Camera: S7'));
    check((await pendingText()).includes('waiting for Accept'), 'No countdown while paused');
    const shownId = (await api('state')).camera.pending.id;
    await page.locator('#accept').click();
    await waitFor(async () => (await game()).darts.length === 2);
    const commit = await lastCommit();
    check(commit.source === 'accepted' && commit.proposal.id === shownId && commit.dart.score === 7, JSON.stringify(commit));
    return {id: shownId};
  });

  await run('dart 3: one tap on the board replaces a wrong pending detection', async () => {
    await scene(3);
    await waitFor(async () => (await pendingText()).includes('Camera: T10'));
    // Treat T10 as a wrong detection: the host taps D10 instead (1 tap). Taps within 600 ms of the
    // previous write are ignored by the duplicate guard, so wait as a person would.
    await pause(650);
    await tap('D10');
    await waitFor(async () => (await game()).darts.length === 3).catch(async error => {
      throw Error(error.message + ' · notice: ' + await page.locator('#notice').textContent() +
        ' · board: ' + await page.locator('#tap-board').getAttribute('class'));
    });
    const g = await game(), commit = await lastCommit();
    check(g.darts[2].score === 20, 'Dart 3 is D10');
    check(commit.source === 'corrected' && commit.proposal.label === 'T10', JSON.stringify(commit));
    await pause(1200);
    check((await api('state')).camera.pending === null, 'Replaced detection does not come back');
    return {ok: true};
  });

  await run('a committed dart is corrected with 2 taps (chip, then board)', async () => {
    const before = (await api('state')).revision;
    await pause(650);
    await page.locator('#turn-darts .dart-chip').first().click();
    check((await page.locator('#tap-hint').textContent()).includes('correct dart 1'), 'Hint shows correction mode');
    await tap('T18');
    await waitFor(async () => (await game()).darts[0].score === 54);
    const state = await api('state');
    check(state.revision === before + 1, 'One revision for the correction');
    check(state.game.darts.map(d => d.score).join(',') === '54,7,20', 'Only dart 1 changed');
    const events = (await api('events')).events.filter(e => e.type === 'correct');
    check(events.length === 1 && events[0].before.score === 18 && events[0].after.score === 54, 'Correction logged');
    await waitFor(async () => Number(await play.locator('.turn-points').textContent()) === 81, 5000);
    await page.screenshot({path: path.join(artifacts, 'M1-12-control-corrected.png'), fullPage: true});
    return {revision: state.revision};
  });

  await run('a turn with undetected darts ends with clearly marked filled-in misses', async () => {
    await page.locator('#next').click();
    await waitFor(async () => (await game()).player === 1);
    await waitFor(async () => await page.locator('#end-turn').isVisible());
    await page.locator('#end-turn').click();
    await waitFor(async () => (await game()).darts.length === 3);
    const g = await game();
    check(g.darts.every(d => d.value === 0 && d.filled), 'Three filled misses');
    await waitFor(async () => (await page.locator('#turn-darts').textContent()).includes('Miss · filled in'));
    await pause(650);
    await page.locator('#turn-darts .dart-chip').nth(1).click();
    await tap('Si5');
    await waitFor(async () => (await game()).darts[1].score === 5);
    check(!(await game()).darts[1].filled, 'Corrected miss is no longer marked filled');
    await page.screenshot({path: path.join(artifacts, 'M1-12-control-filled.png'), fullPage: true});
    return {darts: (await game()).darts};
  });
})().catch(error => { results.push({name: 'camera controller harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    for (const child of children) {
      child.kill('SIGTERM');
      await new Promise(resolve => { if (child.exitCode !== null) return resolve(); child.once('exit', resolve); setTimeout(resolve, 2000); });
    }
    fs.mkdirSync(artifacts, {recursive: true});
    fs.writeFileSync(path.join(artifacts, 'M1-12-camera-controller-results.json'),
      JSON.stringify({testOnly: true, media: 'sim/ scenes via tests/fake_ipwebcam.py', results, errors}, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
