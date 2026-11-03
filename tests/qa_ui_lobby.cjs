// M3 UI-02 / UI-03 / UI-05: lobby and game setup from the controller, checkout suggestions, the game-shot
// screen with statistics, Rematch / New game, toasts, and controller layouts. Own ephemeral server, no camera.
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const {spawn} = require('child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.DART_PYTHON || path.join(root, '.venv/bin/python');
const output = require('./qa_output.cjs');
const token = 'ui-lobby-qa';
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

(async () => {
  // Two recent players, as a previous evening would have left them (saved next to the match file).
  const stateFile = process.env.DART_STATE_FILE || path.join(os.tmpdir(), 'dart-qa-' + process.pid + '-' + Date.now(), 'match.json');
  fs.mkdirSync(path.dirname(stateFile), {recursive: true});
  fs.writeFileSync(path.join(path.dirname(stateFile), 'recent_players.json'), JSON.stringify({schema: 1, names: ['Ana', 'Ben', 'Cy']}));
  const port = await new Promise(resolve => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
  let started = '';
  server = spawn(python, ['-B', '-c', 'import server;server.app=server.App("' + token + '");server.vision=None;' +
    'server.vision_error="QA no camera";server.main()', '--host', '127.0.0.1', '--port', String(port)],
  {cwd: root, env: {...process.env, DART_STATE_FILE: stateFile}, stdio: ['ignore', 'pipe', 'pipe']});
  server.stdout.on('data', chunk => { started += chunk; });
  server.stderr.on('data', chunk => errors.push('server: ' + chunk.toString().trim()));
  await waitFor(() => started.includes('Computer:'), 10000);
  const origin = 'http://127.0.0.1:' + port;
  async function api(endpoint, body) {
    const options = {headers: {Authorization: 'Bearer ' + token}};
    if (body !== undefined) {
      const state = await (await fetch(origin + '/api/state', {headers: options.headers})).json();
      options.method = 'POST';
      options.body = JSON.stringify({expected_revision: state.revision, ...body});
    }
    return (await fetch(origin + '/api/' + endpoint, options)).json();
  }
  async function throws(...darts) {
    for (const [value, multiplier] of darts) await api('throw', {value, multiplier});
  }
  browser = await chromium.launch(process.env.DART_CHROME ? {executablePath: process.env.DART_CHROME} : undefined);
  const display = (await api('state')).presentation_path;

  const tv = await browser.newPage({viewport: {width: 1920, height: 1080}});
  tv.on('pageerror', error => errors.push('tv: ' + error.message));
  const phoneContext = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
  const phone = await phoneContext.newPage();
  phone.on('pageerror', error => errors.push('phone: ' + error.message));
  let taps = 0;
  const tap = async selector => { taps++; await phone.locator(selector).tap(); };

  await run('the TV shows a lobby with game tiles while no match runs', async () => {
    await tv.goto(origin + display);
    await tv.waitForSelector('.lobby-live');
    const tiles = await tv.locator('.game-tile').allTextContents();
    check(tiles.length === 6, 'six game tiles: ' + tiles);
    check(tiles[0].includes('301') && tiles[1].includes('501'), '301 and 501 first');
    check(await tv.locator('.game-tile.soon').count() === 4, 'four coming-soon tiles');
    check(await tv.locator('.game-tile.chosen').textContent().then(t => t.includes('301')), '301 chosen by default');
    check(await tv.locator('button').count() === 2 && await tv.locator('#fullscreen').count() === 1
      && await tv.locator('#sound').count() === 1, 'only the full-screen and sound buttons on the TV');
    await tv.screenshot({path: output.file('ui-lobby-tv-empty-1920.png')});
    return {tiles};
  });

  await run('2 recent players + Start is 3 taps on the controller, and the TV lobby follows live', async () => {
    await phone.goto(origin + '/control?t=' + token);
    await phone.waitForSelector('.recent-chip');
    const chips = await phone.locator('.recent-chip').allTextContents();
    check(chips.join() === 'Ana,Ben,Cy', 'recent names as chips: ' + chips);
    await tap('.recent-chip >> nth=0');
    await waitFor(async () => (await tv.locator('.lobby-player.joined').allTextContents()).join().includes('Ana'));
    await tap('.recent-chip >> nth=1');
    await waitFor(async () => (await tv.locator('.lobby-player.joined').count()) === 2);
    const joined = await tv.locator('.lobby-player.joined').allTextContents();
    check(joined[0].includes('Ana') && joined[1].includes('Ben'), 'TV lobby players ' + joined);
    check(await tv.locator('.lobby-player.joined .avatar[data-seat="1"]').count() === 1, 'seat-coloured avatars');
    await tv.screenshot({path: output.file('ui-lobby-tv-players-1920.png')});
    await phone.screenshot({path: output.file('ui-lobby-control-390.png'), fullPage: true});
    await tap('#setup button[type=submit]');
    await waitFor(async () => !!(await api('state')).game);
    const state = await api('state');
    check(taps <= 6, taps + ' taps');
    check(JSON.stringify(state.game.names) === '["Ana","Ben"]' && state.game.start === 301, 'game ' + JSON.stringify(state.game));
    check(state.camera_game === false, 'camera not ready, so a manual game');
    check(state.lobby.open === false, 'lobby closed');
    await waitFor(async () => (await tv.locator('.hero .score').count()) === 1);
    await waitFor(async () => (await phone.locator('.toast').count()) > 0);
    return {taps};
  });

  await run('choosing 501 and double out on the controller reaches the TV and the game', async () => {
    await phone.locator('#new-game').tap();
    await waitFor(async () => (await tv.locator('.lobby-live').count()) === 1);
    check(await phone.locator('#names input').nth(0).inputValue() === 'Ana', 'New game keeps the players');
    await phone.locator('.game-option[data-start="501"]').tap();
    await phone.locator('#double-out').tap();
    await waitFor(async () => (await tv.locator('.game-tile.chosen').textContent()).includes('501'));
    check((await tv.locator('.lobby-label em').first().textContent()).includes('DOUBLE OUT'), 'double out on TV');
    check(await phone.locator('[data-scoring="camera"]').isDisabled(), 'camera choice disabled while the camera is not ready');
    await phone.locator('#setup button[type=submit]').tap();
    await waitFor(async () => (await api('state')).game.start === 501);
    check((await api('state')).game.double_out === true, 'double out game');
    // Opening the setup and going back changes nothing and closes the TV lobby.
    const revision = (await api('state')).revision;
    await phone.locator('#new-game').tap();
    await waitFor(async () => (await tv.locator('.lobby-live').count()) === 1);
    await phone.locator('#back-to-match').tap();
    await waitFor(async () => (await tv.locator('.hero .score').count()) === 1);
    check((await api('state')).revision === revision, 'Back to the match changes nothing');
    return {ok: true};
  });

  await run('checkout suggestions on the TV and the controller; bust is shown', async () => {
    await api('game', {names: ['Ana', 'Ben'], camera: false, start: 301, double_out: true});
    await throws([20, 3], [20, 3], [20, 3]);
    await api('next', {});
    await throws([0, 1], [0, 1], [0, 1]);
    await api('next', {});
    await waitFor(async () => (await tv.locator('.checkout-line.has-route').count()) === 1, 8000).catch(async e => {
      throw Error(e.message + JSON.stringify((await api('state')).game) + (await tv.locator('#match').innerHTML()).slice(0, 600));
    });
    const route = (await tv.locator('.checkout-line').textContent()).replace(/\s+/g, ' ');
    check(route.includes('T20') && route.includes('T11') && route.includes('D14'), 'TV checkout ' + route);
    await waitFor(async () => (await phone.locator('.compact-checkout').textContent()).includes('T20 · T11 · D14'));
    await tv.screenshot({path: output.file('ui-checkout-tv-1920.png')});
    await phone.screenshot({path: output.file('ui-checkout-control-390.png')});
    await throws([20, 3], [20, 3]);  // 1 left in double out: bust
    await waitFor(async () => (await tv.locator('.bust-badge').count()) === 1);
    await waitFor(async () => (await tv.locator('.hero .score').textContent()) === '121');
    check(await tv.locator('.checkout-line.has-route').count() === 0, 'no checkout after a bust');
    await pause(1300);
    await tv.screenshot({path: output.file('ui-bust-tv-1920.png')});
    return {route};
  });

  await run('game shot: stats on the TV at 1920x1080, Rematch on the controller', async () => {
    await api('next', {});
    await throws([0, 1], [0, 1], [0, 1]);
    await api('next', {});
    await throws([20, 3], [11, 3], [14, 2]);
    await waitFor(async () => (await tv.locator('.match-stats').count()) === 1, 8000);
    const table = await tv.locator('.stats-table').innerText();
    check(/3-dart avg/i.test(table) && /180s/i.test(table) && /checkout/i.test(table), 'stats rows ' + table);
    const stats = (await api('state')).stats.players[0];
    check(stats.checkout === 121 && stats.maximums === 1 && stats.busts === 1 && stats.darts === 8, 'stats ' + JSON.stringify(stats));
    check(table.includes(stats.average.toFixed(1)), 'TV shows the average');
    await pause(4200);  // after the victory stage
    await tv.screenshot({path: output.file('ui-win-tv-1920.png')});
    await waitFor(async () => await phone.locator('#win-panel').isVisible());
    check(await phone.locator('#tap-board').isHidden(), 'tap board steps aside after a win');
    await phone.screenshot({path: output.file('ui-win-control-390.png')});
    await phone.locator('#rematch').tap();
    await waitFor(async () => (await api('state')).game.winner === null);
    const game = (await api('state')).game;
    check(JSON.stringify(game.names) === '["Ben","Ana"]', 'Rematch: the next player starts ' + game.names);
    check(game.start === 301 && game.double_out === true, 'Rematch keeps the options');
    return {stats};
  });

  await run('Undo shows a toast; the controller fits 360x740, 390x844 and 1024x768 with 44 px targets', async () => {
    await throws([20, 1]);
    await waitFor(async () => (await phone.locator('#turn-darts .dart-chip').count()) === 1);
    await phone.locator('#undo').tap();
    await waitFor(async () => (await phone.locator('.toast').allTextContents()).some(t => t.includes('Undone')));
    const sizes = {};
    for (const [width, height] of [[360, 740], [390, 844], [1024, 768]]) {
      for (const mode of ['game', 'setup']) {
        const context = await browser.newContext({viewport: {width, height}, isMobile: width < 700, hasTouch: true});
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(width + ': ' + error.message));
        await page.goto(origin + '/control?t=' + token);
        await page.waitForSelector('#tap-board .hit-region');
        if (mode === 'setup') await page.locator('#new-game').click();
        await pause(400);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        check(overflow <= 0, `${width}x${height} ${mode}: horizontal overflow ${overflow}px`);
        const selectors = mode === 'game' ? ['#miss', '#undo', '#next', '#record', '#new-game'] :
          ['.recent-chip', '.game-option[data-start]', '#double-out', '[data-scoring]', '#add-player', '#setup button[type=submit]', '.remove-player'];
        for (const selector of selectors) {
          const boxes = await page.locator(selector).evaluateAll(nodes => nodes.filter(n => n.offsetParent).map(n => n.getBoundingClientRect().height));
          check(boxes.every(h => h >= 44), `${width} ${selector} below 44 px: ${boxes}`);
        }
        sizes[`${width}x${height}-${mode}`] = 'ok';
        await page.screenshot({path: output.file(`ui-control-${mode}-${width}x${height}.png`)});
        if (mode === 'setup') await page.locator('#back-to-match').click();
        await pause(300);
        await context.close();
      }
    }
    check((await api('state')).lobby.open === false, 'Back to the match closes the TV lobby');
    return sizes;
  });
})().catch(error => { results.push({name: 'ui lobby harness completion', pass: false, error: error.stack}); })
  .finally(async () => {
    if (browser) await browser.close();
    if (server) {
      server.kill('SIGTERM');
      await new Promise(resolve => { if (server.exitCode !== null) return resolve(); server.once('exit', resolve); setTimeout(resolve, 2000); });
    }
    fs.writeFileSync(output.file('ui-lobby-results.json'), JSON.stringify({results, errors}, null, 2) + '\n');
    console.log(JSON.stringify({results, errors}, null, 2));
    process.exitCode = results.some(result => !result.pass) || errors.length ? 1 : 0;
  });
