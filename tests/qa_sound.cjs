// UI-04: static/sound.js in headless Chromium. Every sound plays without errors, renders as real (non-silent,
// unclipped) audio, sound starts muted until a click, and the on/off choice is remembered.
// The page and script are served from a mocked origin; no Dart Room server is needed.
const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const artifacts = require('./qa_output.cjs').dir;
const origin = 'http://sound.test';
const results = [], errors = [];
const PAGE = `<!doctype html><meta charset="utf-8"><title>Sound check</title>
<body style="background:#101e1d;color:#eee9d9;font:16px system-ui;padding:40px">
<button id="sound">Sound on</button> <span id="state"></span>
<script src="/static/sound.js"></script>
<script>DartSound.attachToggle(document.getElementById('sound'));
DartSound.onchange = on => { document.getElementById('state').textContent = on ? 'on' : 'off'; };</script>`;

function check(ok, message) { if (!ok) throw Error(message); }

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

(async () => {
  const browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push('console: ' + message.text()); });
    await page.route(origin + '/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/static/sound.js') {
        return route.fulfill({contentType: 'text/javascript', body: fs.readFileSync(path.join(root, 'static/sound.js'))});
      }
      return route.fulfill({contentType: 'text/html', body: PAGE});
    });
    await page.goto(origin + '/');

    await run('sound starts muted; play does nothing until enabled', async () => {
      const muted = await page.evaluate(() => ({
        enabled: DartSound.isEnabled(), played: DartSound.play('dart'), names: DartSound.names,
        label: document.getElementById('sound').textContent, pressed: document.getElementById('sound').getAttribute('aria-pressed'),
      }));
      check(!muted.enabled && !muted.played, 'Muted at start: ' + JSON.stringify(muted));
      check(muted.label === 'Sound on' && muted.pressed === 'false', 'Toggle offers Sound on');
      check(JSON.stringify(muted.names) === JSON.stringify(['dart', 'turn', 'bust', 'ton', '180', 'gameshot']),
        'Documented names: ' + muted.names);
      return muted;
    });

    await run('clicking Sound on enables audio and remembers it', async () => {
      await page.locator('#sound').click();
      await page.waitForFunction(() => DartSound.isEnabled());
      const on = await page.evaluate(() => ({stored: localStorage.getItem('dartroom.sound'),
        label: document.getElementById('sound').textContent, pressed: document.getElementById('sound').getAttribute('aria-pressed')}));
      check(on.stored === 'on' && on.label === 'Sound off' && on.pressed === 'true', JSON.stringify(on));
      return on;
    });

    await run('every sound plays without errors', async () => {
      const played = {};
      for (const name of ['dart', 'turn', 'bust', 'ton', '180', 'gameshot']) {
        played[name] = await page.evaluate(name => DartSound.play(name), name);
        check(played[name] === true, name + ' was not played');
        await page.waitForTimeout(150);
      }
      await page.waitForTimeout(2300);  // let the longest one finish
      return played;
    });

    await run('every sound renders real audio (offline render: audible, not clipped)', async () => {
      const levels = {};
      for (const name of ['dart', 'turn', 'bust', 'ton', '180', 'gameshot']) {
        const level = await page.evaluate(name => DartSound.renderOffline(name), name);
        check(level.peak > 0.02 && level.peak <= 1 && level.rms > 0.001, name + ' level ' + JSON.stringify(level));
        levels[name] = {peak: +level.peak.toFixed(3), rms: +level.rms.toFixed(4), seconds: level.duration};
      }
      return levels;
    });

    await run('unknown sound names are ignored with a warning', async () => {
      check(await page.evaluate(() => DartSound.play('nope')) === false, 'unknown name returned true');
      return {ok: true};
    });

    await run('mute is remembered; sound that was on comes back on the first click after a reload', async () => {
      await page.locator('#sound').click();
      await page.waitForFunction(() => !DartSound.isEnabled());
      check(await page.evaluate(() => localStorage.getItem('dartroom.sound')) === 'off', 'Mute stored');
      check(await page.evaluate(() => DartSound.play('dart')) === false, 'Muted play returns false');
      await page.reload();
      check(!(await page.evaluate(() => DartSound.isEnabled())), 'Still muted after reload');
      await page.locator('#sound').click();
      await page.waitForFunction(() => DartSound.isEnabled());
      await page.reload();
      check(!(await page.evaluate(() => DartSound.isEnabled())), 'Needs a gesture after reload (autoplay rules)');
      await page.mouse.click(300, 300);  // anywhere on the page
      await page.waitForFunction(() => DartSound.isEnabled());
      check(await page.evaluate(() => DartSound.play('turn')), 'Plays after the first click');
      return {ok: true};
    });
  } catch (error) {
    results.push({name: 'sound harness completion', pass: false, error: error.stack});
  } finally {
    await browser.close();
  }
  fs.mkdirSync(artifacts, {recursive: true});
  fs.writeFileSync(path.join(artifacts, 'UI-04-sound-results.json'), JSON.stringify({results, errors}, null, 2) + '\n');
  console.log(JSON.stringify({results, errors}, null, 2));
  process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
})();
