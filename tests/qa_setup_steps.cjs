// UI-06 / UI-06b: the Setup page as a three-step flow, on the fake IP Webcam (no phone, no browser camera).
// Walks 1 Connect phone -> 2 Calibrate -> 3 Ready, checking that the highlighted step follows the server's camera
// phase, that the Controller and TV QR codes decode (OpenCV QRCodeDetector) back to the exact links, and that the
// collapsible advanced sections are there. Screenshots at 1440x900 and 1280x800 go to the evidence folder.
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const {spawn, execFileSync} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const artifacts = require('./qa_output.cjs').dir;
const token = 'setup-steps-qa';
const results = [], errors = [], children = [];
let browser;

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(ok, message) { if (!ok) throw Error(message); }

async function waitFor(fn, limit = 10000) {
  const end = Date.now() + limit;
  while (Date.now() < end) {
    if (await fn()) return;
    await pause(50);
  }
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
    const probe = net.createServer();
    probe.listen(0, '127.0.0.1', () => {
      const port = probe.address().port;
      probe.close(() => resolve(port));
    });
  });
}

function start(args, ready) {
  const stateFile = process.env.DART_STATE_FILE ||
    path.join(os.tmpdir(), 'dart-qa-' + process.pid + '-' + Date.now(), 'match.json');  // never the real match
  const child = spawn(python, args, {cwd: root, env: {...process.env, DART_STATE_FILE: stateFile},
    stdio: ['ignore', 'pipe', 'pipe']});
  children.push(child);
  let output = '';
  child.stdout.on('data', chunk => { output += chunk.toString(); });
  child.stderr.on('data', chunk => { errors.push('child stderr: ' + chunk.toString().trim()); });
  return waitFor(() => output.includes(ready), 15000).then(() => output);
}

// Where the fake IP Webcam's board is, so the four calibration clicks can be made exactly.
const SIM_CODE = `
import json
from sim import camera_for_mount
from sim.scene import calibration_points
print(json.dumps(calibration_points(camera_for_mount('left', 1280, 720)).tolist()))
`;

// Decode every QR code in a PNG with OpenCV; prints a JSON list of strings.
const DECODE_CODE = `
import json, sys, cv2
image = cv2.imread(sys.argv[1])
found = []
detector = cv2.QRCodeDetector()
text, _, _ = detector.detectAndDecode(image)
if text: found.append(text)
print(json.dumps(found))
`;

function decodeQr(file) {
  return JSON.parse(execFileSync(python, ['-B', '-c', DECODE_CODE, file], {cwd: root}).toString());
}

(async () => {
  fs.mkdirSync(artifacts, {recursive: true});
  const points = JSON.parse(execFileSync(python, ['-B', '-c', SIM_CODE], {cwd: root}).toString());
  const port = await freePort(), fakePort = await freePort();
  const startup = await start(['-B', '-c', 'import server; server.app = server.App("' + token + '"); server.main()',
    '--host', '127.0.0.1', '--port', String(port)], 'Camera source:');
  await start(['-B', 'tests/fake_ipwebcam.py', '--port', String(fakePort), '--mount', 'left',
    '--width', '1280', '--height', '720'], 'Fake IP Webcam');
  const origin = 'http://127.0.0.1:' + port;
  const api = async endpoint =>
    (await fetch(origin + '/api/' + endpoint, {headers: {Authorization: 'Bearer ' + token}})).json();

  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  const title = () => page.locator('#setupTitle').textContent();
  const classOf = async id => (await page.locator('#' + id).getAttribute('class')) || '';
  const currentStep = async () => {
    for (const n of [1, 2, 3]) if ((await classOf('step' + n)).split(' ').includes('current')) return n;
    return null;
  };
  const shot = name => page.screenshot({path: path.join(artifacts, name)});

  await run('step 1 is current with no camera; advanced sections start collapsed', async () => {
    await page.goto(origin + '/?t=' + token);
    await waitFor(async () => await title() === 'Connect your phone');
    check(await currentStep() === 1, 'Step 1 is the current step');
    check((await classOf('stepNav1')).includes('current'), 'Stepper shows step 1');
    for (const id of ['troubleshoot', 'phoneChecklist', 'mountDetails', 'recordNotes', 'legacyGame']) {
      check(await page.locator('#' + id).evaluate(details => details.tagName === 'DETAILS' && !details.open),
        id + ' is a collapsed section');
    }
    for (const id of ['phoneIp', 'sourcePreset', 'testSource', 'connectSource', 'calibrate', 'recordToggle', 'qrController']) {
      check(await page.locator('#' + id).isVisible(), id + ' is visible without opening anything');
    }
    await shot('UI-06-setup-step1-1440.png');
    return {step: 1};
  });

  await run('a wrong address gives a plain-English hint', async () => {
    await page.locator('#sourceUri').fill('http://127.0.0.1:9/video');
    await page.locator('#testSource').click();
    await waitFor(async () => await page.locator('#sourceHint').isVisible());
    const hint = await page.locator('#sourceHint').textContent();
    check(/Start server/.test(hint), 'Refused connection explains the fix: ' + hint);
    // QA L1: an address that answers but isn't a camera gets its own hint; Python exception names are hidden.
    const notCamera = await page.evaluate(() => ({
      hint: friendlyHint('Stream connected, but no image parts were found (unexpected format)'),
      http: friendlyHint('Camera answered HTTP 404'),
      plain: [plainError('gaierror: [Errno -2] Name or service not known'), plainError('ConnectionError: Camera closed the stream'),
        plainError('socket.timeout: timed out')],
    }));
    check(/isn't sending camera video/.test(notCamera.hint) && /isn't sending camera video/.test(notCamera.http),
      'Not-a-camera hint: ' + JSON.stringify(notCamera));
    check(JSON.stringify(notCamera.plain) === JSON.stringify(['Name or service not known', 'Camera closed the stream', 'timed out']),
      'Exception names stripped: ' + JSON.stringify(notCamera.plain));
    return {hint, notCamera};
  });

  await run('step 2 becomes current once the phone is connected', async () => {
    await page.locator('#phoneIp').fill('127.0.0.1:' + fakePort);
    await page.locator('#testSource').click();
    await waitFor(async () => (await page.locator('#sourceStatus').textContent()).includes('Connection OK'));
    check(await page.locator('#sourceHint').isHidden(), 'Hint cleared after a good test');
    await page.locator('#connectSource').click();
    await waitFor(async () => await title() === 'Ready to calibrate');
    await waitFor(async () => await currentStep() === 2);
    check((await classOf('step1')).includes('done') && (await classOf('stepNav1')).includes('done'), 'Step 1 is done');
    await waitFor(async () => await page.locator('#stageEmpty').isHidden());
    await shot('UI-06-setup-step2-1440.png');
    return {step: 2};
  });

  await run('four clicks and Markers correct reach step 3', async () => {
    await page.locator('#calibrate').click();
    await waitFor(async () => (await title()).includes('0/4'));
    check(await currentStep() === 2, 'Still step 2 while selecting points');
    const box = await page.locator('#board').boundingBox();
    for (const [x, y] of points) {
      await page.locator('#board').click({position: {x: x / 1280 * box.width, y: y / 720 * box.height}});
    }
    await waitFor(async () => await title() === 'Check the live markers');
    await waitFor(async () => !(await page.locator('#verify').isDisabled()));
    await page.waitForTimeout(400);
    await shot('UI-06-setup-step2-review-1440.png');
    await page.locator('#verify').click();
    await waitFor(async () => await title() === 'Ready to play');
    await waitFor(async () => await currentStep() === 3);
    check((await classOf('step2')).includes('done'), 'Step 2 is done');
    check((await api('state')).vision.phase === 'ready', 'Server phase is ready');
    await page.waitForTimeout(800);  // smooth scroll to step 3
    await shot('UI-06-setup-step3-1440.png');
    await page.screenshot({path: path.join(artifacts, 'UI-06-setup-step3-1440-full.png'), fullPage: true});
    return {step: 3};
  });

  await run('UI-06b: both QR codes decode to the exact Controller and TV links', async () => {
    const links = await api('links');
    check(startup.includes('Controller:   ' + links.controller), 'Controller link matches the Terminal banner');
    check(startup.includes('Presentation: ' + links.presentation), 'TV link matches the Terminal banner');
    const decoded = {};
    for (const [canvas, link, expected] of [['qrController', 'controllerLink', links.controller],
      ['qrPresentation', 'presentationLink', links.presentation]]) {
      check(await page.locator('#' + link).textContent() === expected, link + ' shows the link as text');
      check(await page.locator('#' + link).getAttribute('href') === expected, link + ' opens the link');
      // As drawn on screen ...
      const onScreen = path.join(artifacts, 'UI-06b-' + canvas + '.png');
      await page.locator('#' + canvas).screenshot({path: onScreen});
      const seen = decodeQr(onScreen);
      check(seen.length === 1 && seen[0] === expected, canvas + ' on screen decodes to ' + JSON.stringify(seen));
      // ... and the canvas pixels themselves.
      const pixels = path.join(artifacts, 'UI-06b-' + canvas + '-pixels.png');
      const dataUrl = await page.locator('#' + canvas).evaluate(element => element.toDataURL('image/png'));
      fs.writeFileSync(pixels, Buffer.from(dataUrl.split(',')[1], 'base64'));
      check(decodeQr(pixels)[0] === expected, canvas + ' pixels decode');
      decoded[canvas] = seen[0];
    }
    return decoded;
  });

  await run('everything that existed stays reachable', async () => {
    await page.locator('#legacyGame summary').click();
    for (const id of ['newGame', 'cameraGame', 'manual', 'undo', 'next', 'confirm']) {
      check(await page.locator('#' + id).isVisible(), id + ' visible in the older controls');
    }
    await page.locator('#mountDetails summary').click();
    check(await page.locator('#mountSide').isVisible(), 'Mount override visible');
    await page.locator('#recordNotes summary').click();
    check(await page.locator('#saveNotes').isVisible(), 'Recording notes visible');
    check(/GB free/.test(await page.locator('#recordStatus').textContent()), 'Disk space shown');
    check(/cm/.test(await page.locator('#footText').textContent()), 'Camera position summary shown');
    // Open sections are remembered on this browser.
    await page.reload();
    await page.waitForSelector('#legacyGame[open]');
    for (const id of ['legacyGame', 'mountDetails', 'recordNotes']) await page.locator('#' + id + ' summary').click();
    return {ok: true};
  });

  await run('1280x800 layout: no horizontal scroll, screenshots', async () => {
    const small = await browser.newPage({viewport: {width: 1280, height: 800}});
    small.on('pageerror', error => errors.push(error.message));
    await small.goto(origin + '/?t=' + token);
    await small.waitForFunction(() => document.getElementById('step3').classList.contains('current'));
    await small.waitForFunction(() => document.getElementById('qrController').dataset.text);
    const sizing = await small.evaluate(() => ({width: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth}));
    check(sizing.content <= sizing.width, 'Horizontal overflow ' + JSON.stringify(sizing));
    await small.screenshot({path: path.join(artifacts, 'UI-06-setup-step3-1280.png')});
    await small.locator('#step3').scrollIntoViewIfNeeded();
    await small.screenshot({path: path.join(artifacts, 'UI-06-setup-step3-qr-1280.png')});
    await small.close();
    return sizing;
  });

  await run('step 1 again after Disconnect; 1280x800 screenshot', async () => {
    await page.locator('#disconnectSource').click();
    await waitFor(async () => await currentStep() === 1);
    await page.setViewportSize({width: 1280, height: 800});
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('UI-06-setup-step1-1280.png');
    return {step: 1};
  });
})().catch(error => { results.push({name: 'setup steps harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    for (const child of children) {
      child.kill('SIGTERM');
      await new Promise(resolve => {
        if (child.exitCode !== null) return resolve();
        child.once('exit', resolve);
        setTimeout(resolve, 2000);
      });
    }
    fs.mkdirSync(artifacts, {recursive: true});
    fs.writeFileSync(path.join(artifacts, 'UI-06-setup-steps-results.json'),
      JSON.stringify({testOnly: true, media: 'tests/fake_ipwebcam.py sim renders', results, errors}, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
