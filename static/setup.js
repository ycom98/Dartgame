'use strict';
// Camera setup page (M1-13, redesigned as three steps in UI-06). The Mac pulls frames from the phone's IP Webcam
// stream; this page picks the stream, shows it live, takes the four calibration clicks, draws the full board
// overlay for checking, shows readiness, and finally shows the Controller and TV links as QR codes.
// Step 1 Connect phone -> 2 Calibrate -> 3 Ready follows the camera phase reported by the server (currentStep).
// The older game controls (start a game, play) are unchanged, in a collapsible section.

const $ = id => document.getElementById(id);
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const token = new URLSearchParams(location.search).get('t') || '';

// Board geometry in mm (core.py): +x right, +y down, 20 at the top.
const TARGET_MM = [[0, -170], [170, 0], [0, 170], [-170, 0]];  // calibration points 20, 6, 3, 11
const RING_RADII = [6.35, 15.9, 99, 107, 162, 170];
const SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];
const CLICK_STEPS = ['TOP centre of 20', 'RIGHT centre of 6', 'BOTTOM centre of 3', 'LEFT centre of 11'];
const PRESETS = {
  ipwebcam: host => 'http://' + withPort(host, 8080) + '/video',
  snapshot: host => 'snapshot:http://' + withPort(host, 8080) + '/shot.jpg',
  droidcam: host => 'http://' + withPort(host, 4747) + '/video',
};
const STORAGE_KEY = 'dartroom.cameraUri';
const OPEN_KEY = 'dartroom.setupOpen.';  // + details id: remembered open/closed sections

let state = null, points = [], selecting = false, calibrationBusy = false, snapshotId = null, frozenImage = null;
let lastImage = null, pollBusy = false, actionBusy = false, stateEpoch = 0, scoreLockUntil = 0;
let serverConnected = false, displayedVersion = null, errorSource = null, sourceFieldTouched = false;
let shownStep = null, links = null;

// ---- server calls ----
const error = (message, source = 'action') => {
  errorSource = message ? source : null;
  $('error').textContent = message;
  $('error').style.display = message ? 'block' : 'none';
};

async function requestJson(url, options = {}, signal) {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener('abort', cancel, {once: true});
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 12000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Request failed (' + response.status + ')');
    return data;
  } catch (e) {
    if (timedOut) throw Error('The Mac did not respond within 12 seconds. Check that Dart Room is running, then retry.');
    throw e;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}

async function api(path, body, signal) {
  const options = {headers: {Authorization: 'Bearer ' + token}};
  if (body !== undefined) {
    stateEpoch++;
    // M1-10: every write names the revision it is based on; a 409 means another device changed the match.
    if (body.expected_revision === undefined) body = {...body, expected_revision: state?.revision ?? 0};
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const data = await requestJson('/api/' + path, options, signal);
  if (body !== undefined && data.vision) { state = data; serverConnected = true; }
  return data;
}

async function loadImage(path) {
  const res = await fetch('/api/' + path, {headers: {Authorization: 'Bearer ' + token}});
  if (!res.ok) {
    const result = await res.json();
    throw Error(result.error || 'Could not load camera image');
  }
  const url = URL.createObjectURL(await res.blob()), img = new Image();
  try {
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(Error('Could not display camera image'));
      img.src = url;
    });
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ---- button state ----
function controls() {
  const v = state?.vision || {}, g = state?.game;
  const finished = !g || g.winner !== null || g.bust || g.darts.length >= 3;
  const blocked = actionBusy || calibrationBusy || !serverConnected;
  const scoreBlocked = blocked || performance.now() < scoreLockUntil;
  const unavailable = v.phase === 'unavailable';
  $('testSource').disabled = blocked || unavailable || !$('sourceUri').value.trim();
  $('connectSource').disabled = blocked || unavailable || selecting || !$('sourceUri').value.trim();
  $('disconnectSource').disabled = blocked || selecting || !v.source;
  $('calibrate').disabled = blocked || !v.fresh;
  $('align').disabled = blocked || selecting || !v.fresh || ['waiting_camera', 'ready_to_calibrate'].includes(v.phase);
  $('baseline').disabled = blocked || selecting || !v.aligned;
  $('verify').hidden = v.phase !== 'review_overlay' || selecting;
  $('verify').disabled = blocked || !v.fresh || displayedVersion !== v.version;
  $('cancelCalibration').hidden = !selecting;
  document.body.classList.toggle('selecting', selecting);
  $('cancelCalibration').disabled = blocked;
  $('mountSide').disabled = blocked || unavailable;
  $('recordToggle').disabled = blocked || unavailable;
  $('saveNotes').disabled = blocked || !state?.recording?.active;
  $('newGame').disabled = blocked || selecting || ($('cameraGame').checked && !v.verified);
  $('confirm').disabled = scoreBlocked || selecting || !state?.camera?.pending || !v.aligned || finished ||
    (state?.camera_game && !v.verified);
  $('manual').disabled = scoreBlocked || selecting || finished;
  $('undo').disabled = scoreBlocked || selecting || !g;
  $('next').disabled = scoreBlocked || selecting || !g || g.winner !== null || (!g.bust && g.darts.length < 3) ||
    (state?.camera_game && !v.verified);
}

function act(id, fn) {
  $(id).onclick = async event => {
    const scoring = ['confirm', 'manual', 'undo', 'next'].includes(id);
    if (actionBusy || calibrationBusy || (scoring && !serverConnected) ||
        (scoring && (performance.now() < scoreLockUntil || event.detail > 1))) return;
    if (scoring) { scoreLockUntil = performance.now() + 600; setTimeout(controls, 610); }
    actionBusy = true;
    controls();
    try { error(''); await fn(); } catch (e) { error(e.message); }
    finally { actionBusy = false; await refresh(); controls(); }
  };
}

// ---- camera source ----
function withPort(host, port) {
  host = host.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  return /:\d+$/.test(host) ? host : host + ':' + port;
}

function sourceFromPreset() {
  const preset = $('sourcePreset').value, host = $('phoneIp').value.trim();
  if (preset === 'custom' || !host) return;
  $('sourceUri').value = PRESETS[preset](host);
  controls();
}

function hostFromUri(uri) {
  const match = /^(?:snapshot:)?https?:\/\/(?:[^@/]*@)?([^/]+)/.exec(uri || '');
  return match ? match[1].replace(/:(8080|4747)$/, '') : '';
}

function presetFromUri(uri) {
  if (/^snapshot:/.test(uri)) return 'snapshot';
  if (/:4747\//.test(uri)) return 'droidcam';
  if (/^https?:\/\/[^/]+:8080\/video$/.test(uri)) return 'ipwebcam';
  return 'custom';
}

function fillSourceField(uri) {
  // A redacted login (user:***@) cannot be sent again; keep what the user typed or remembered instead.
  if (!uri || sourceFieldTouched || uri.includes(':***@')) return;
  $('sourceUri').value = uri;
  $('sourcePreset').value = presetFromUri(uri);
  $('phoneIp').value = hostFromUri(uri);
}

function rememberSource(uri) {
  if (/\/\/[^/]*@/.test(uri)) return;  // never keep a login in browser storage
  try { localStorage.setItem(STORAGE_KEY, uri); } catch (e) { /* storage unavailable: nothing to remember */ }
}

function rememberedSource() {
  try { return localStorage.getItem(STORAGE_KEY) || ''; } catch (e) { return ''; }
}

function describeSource(source) {
  if (!source) return ['No camera connected. Enter the phone address above and press Connect.', ''];
  const where = source.url_redacted;
  if (!source.connected) {
    const reason = plainError(source.error) || (source.ended ? 'The recording finished.' : 'Waiting for the first image…');
    return [where + ' · not connected · ' + reason + (source.reconnects ? ' · retries: ' + source.reconnects : ''),
      'problem'];
  }
  const size = source.width ? source.width + '×' + source.height : '';
  return [where + ' · connected · ' + size + ' · ' + source.fps + ' fps received, ' + source.processed_fps +
    ' fps checked · newest image ' + Math.round((source.last_frame_age || 0) * 1000) + ' ms old', 'ok'];
}

// The server's camera error without Python exception names ("gaierror: ...", "ConnectionError: ..."), for the
// owner; /api/state keeps the raw text.
function plainError(message) {
  return String(message || '')
    .replace(/^(?:[A-Za-z_]\w*\.)*(?:\w*(?:Error|Exception)|gaierror|herror|timeout):\s*/, '')
    .replace(/\[Errno -?\d+\]\s*/g, '');
}

// A plain-English next step for a camera error (the server's message is shown as well).
function friendlyHint(message) {
  const text = String(message || '').toLowerCase();
  if (!text) return '';
  if (text.includes('no image parts') || text.includes('no content-length') || text.includes('could not be decoded') ||
      text.includes('closed the stream') || /answered http (4|5)\d\d/.test(text)) {
    return "That address answered but isn't sending camera video. Check the app on the phone is IP Webcam and its " +
      'server is started, and that a typed address ends in /video.';
  }
  if (text.includes('refused')) {
    return 'The address was reached, but nothing is listening there. On the phone, open IP Webcam and tap Start server, then try again.';
  }
  if (text.includes('timed out') || text.includes('no image within') || text.includes('no images arrived')) {
    return 'No picture came back. Check the phone screen is on, IP Webcam is running, and the phone and Mac are on the same Wi-Fi.';
  }
  if (text.includes('no route') || text.includes('unreachable') || text.includes('name or service') ||
      text.includes('nodename') || text.includes('getaddrinfo')) {
    return 'This Mac cannot find that address. Check the numbers on the phone screen, and that both are on the same Wi-Fi (not a guest network).';
  }
  if (text.includes('login')) return 'IP Webcam has a password set. Type the address as http://USER:PASSWORD@PHONE:8080/video.';
  if (text.includes('single images')) return 'That address sends single photos: choose "IP Webcam · single photos" as the App.';
  if (text.includes('must start with') || text.includes('camera address')) {
    return 'Type only the numbers from the phone screen, for example 192.168.1.23.';
  }
  return 'Check that IP Webcam is running on the phone and that the phone and Mac are on the same Wi-Fi.';
}

function showHint(text) {
  $('sourceHint').textContent = text;
  $('sourceHint').hidden = !text;
}

act('testSource', async () => {
  const uri = $('sourceUri').value.trim();
  $('sourceStatus').textContent = 'Testing ' + uri + ' …';
  $('sourceStatus').className = 'muted';
  showHint('');
  const result = (await api('camera/test', {uri})).test;
  if (!result.ok) {
    showHint(friendlyHint(result.error));
    throw Error('Connection test failed: ' + plainError(result.error));
  }
  $('sourceStatus').textContent = 'Connection OK · ' + result.width + '×' + result.height + ' · first image in ' +
    result.first_frame_ms + ' ms. Press Connect to use it.';
  $('sourceStatus').className = 'ok';
  $('sourceStatus').dataset.tested = '1';
});

act('connectSource', async () => {
  const uri = $('sourceUri').value.trim();
  await api('camera/source', {uri, expected_revision: state?.revision ?? 0});
  rememberSource(uri);
  sourceFieldTouched = false;
  delete $('sourceStatus').dataset.tested;
});

// Zoom the phone's camera (IP Webcam). Sent when the slider is released, not on every step.
let zoomDragging = false;
function zoomLabel(level) { return level > 0 ? level + ' %' : 'off'; }
$('zoom').addEventListener('input', () => { zoomDragging = true; $('zoomValue').textContent = zoomLabel(+$('zoom').value); });
$('zoom').addEventListener('change', async () => {
  const level = +$('zoom').value;
  try {
    error('');
    await api('camera/zoom', {zoom: level});
    $('sourceStatus').textContent = 'Zoom set to ' + zoomLabel(level) + '. Set the four points again when the board fills the picture.';
    $('sourceStatus').className = 'ok';
  } catch (e) { error(e.message); }
  finally { zoomDragging = false; await refresh(); }
});
function renderZoom(s) {
  if (zoomDragging || typeof s?.camera_zoom !== 'number') return;
  $('zoom').value = s.camera_zoom;
  $('zoomValue').textContent = zoomLabel(s.camera_zoom);
}

act('disconnectSource', async () => {
  await api('camera/source', {uri: null, expected_revision: state?.revision ?? 0});
});

// ---- steps (UI-06) ----
// Which step the owner is on, from the real camera phase.
function currentStep(v) {
  if (!serverConnected || ['unavailable', 'waiting_camera', 'camera_disconnected'].includes(v.phase) || !v.phase) return 1;
  if (v.phase === 'ready' && !selecting && !calibrationBusy) return 3;
  return 2;
}

function renderSteps(v) {
  const step = currentStep(v);
  const done = {1: step > 1, 2: !!v.verified && step === 3, 3: false};
  const labels = {
    1: {current: 'Do this now', done: 'Done · phone connected', todo: ''},
    2: {current: 'Do this now', done: 'Done · board checked', todo: 'After the phone is connected'},
    3: {current: 'Ready to play', done: '', todo: 'After calibration'},
  };
  for (const n of [1, 2, 3]) {
    const kind = n === step ? 'current' : done[n] ? 'done' : 'todo';
    $('step' + n).classList.toggle('current', kind === 'current');
    $('step' + n).classList.toggle('done', kind === 'done');
    $('stepNav' + n).classList.toggle('current', kind === 'current');
    $('stepNav' + n).classList.toggle('done', kind === 'done');
    $('stepNav' + n).querySelector('a').toggleAttribute('aria-current', kind === 'current');
    $('step' + n + 'State').textContent = labels[n][kind];
  }
  $('desktop').classList.toggle('at-step-3', step === 3);
  // When the step changes (or the page opens past step 1), bring the new step into view if it is off screen.
  if (step !== shownStep && !(shownStep === null && step === 1)) {
    const top = $('step' + step).getBoundingClientRect().top;
    if (top < 0 || top > innerHeight * 0.45) {
      const smooth = shownStep === 2 && step === 3 && !matchMedia('(prefers-reduced-motion: reduce)').matches;
      $('step' + step).scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'start'});
    }
  }
  shownStep = step;
}

// ---- links and QR codes (UI-06b) ----
async function loadLinks() {
  if (links) return;
  try {
    const data = await api('links');
    if (typeof data.controller !== 'string' || typeof data.presentation !== 'string') return;
    links = data;
  } catch (e) {
    return;  // the state poll reports connection problems; try again on the next poll
  }
  showLink('controllerLink', 'qrController', links.controller);
  showLink('presentationLink', 'qrPresentation', links.presentation);
  $('linkWarning').hidden = links.lan;
  $('linkWarning').textContent = links.lan ? '' : 'These links use ' + links.origin + ', which only works on this Mac. ' +
    'Connect the Mac to your Wi-Fi and restart Dart Room. If the address is still wrong, start it with ' +
    '--lan-ip and the Mac\'s Wi-Fi address.';
}

function showLink(linkId, canvasId, url) {
  $(linkId).href = url;
  $(linkId).textContent = url;
  drawQr($(canvasId), url);
}

// Draw `text` as a QR code (error correction M, 4-module quiet zone) with dark modules on cream.
function drawQr(canvas, text) {
  if (typeof qrcode !== 'function') return;
  const qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  const modules = qr.getModuleCount(), quiet = 4, total = modules + 2 * quiet;
  const scale = Math.max(4, Math.floor(528 / total));  // crisp on a Retina screen
  canvas.width = canvas.height = total * scale;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#f6f1e3';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#0c1716';
  for (let row = 0; row < modules; row++) {
    for (let col = 0; col < modules; col++) {
      if (qr.isDark(row, col)) ctx.fillRect((col + quiet) * scale, (row + quiet) * scale, scale, scale);
    }
  }
  canvas.dataset.text = text;
}

async function copyLink(linkId, buttonId) {
  const url = $(linkId).href, button = $(buttonId);
  if (!links) return;
  try {
    await navigator.clipboard.writeText(url);
    button.textContent = 'Copied';
  } catch (e) {
    // No clipboard access: select the link text so Cmd-C copies it.
    const range = document.createRange();
    range.selectNodeContents($(linkId));
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    button.textContent = 'Press Cmd-C';
  }
  setTimeout(() => { button.textContent = 'Copy link'; }, 2000);
}
$('copyController').onclick = () => copyLink('controllerLink', 'copyController');
$('copyPresentation').onclick = () => copyLink('presentationLink', 'copyPresentation');

// Collapsible sections remember whether they were open (this browser only).
function rememberOpenSections() {
  for (const section of document.querySelectorAll('details[data-remember]')) {
    try {
      const saved = localStorage.getItem(OPEN_KEY + section.id);
      if (saved !== null) section.open = saved === '1';
    } catch (e) { /* storage unavailable: keep the default */ }
    section.addEventListener('toggle', () => {
      try { localStorage.setItem(OPEN_KEY + section.id, section.open ? '1' : '0'); } catch (e) { /* not remembered */ }
    });
  }
}

// ---- readiness ----
function setupStatus() {
  const v = state?.vision || {}, phase = v.phase;
  const phases = {
    waiting_camera: ['Connect your phone', 'Start the IP Webcam server on the phone, enter its address below and press Connect.'],
    camera_disconnected: ['Camera disconnected', 'No new image for 5 s. Check the phone is awake, on the same Wi-Fi and IP Webcam is running. It reconnects by itself.'],
    ready_to_calibrate: ['Ready to calibrate', 'Empty the board and press Freeze and set four points.'],
    calibrating: ['Select four points', 'The image is frozen. Keep the camera streaming while you select the four markers.'],
    needs_alignment: ['Check alignment', 'Empty the board, then Check / realign board. If that fails, set four points again.'],
    review_overlay: ['Check the live markers', 'Every ring and sector line must sit on the board wires. Then press Markers correct.'],
    ready: ['Ready to play', 'Camera connected and checked. Scan a code in step 3 to open the Controller and the TV.'],
    unavailable: ['Camera setup unavailable', v.message || 'Install camera dependencies using start-mac.command.'],
  };
  let [title, detail] = phases[phase] || ['Connecting…', 'Checking the local server.'];
  if (calibrationBusy) {
    title = 'Checking calibration…';
    detail = 'Matching the frozen reference to the live image. Please wait.';
  } else if (selecting && v.fresh) {
    title = 'Calibrating · ' + points.length + '/4 points';
    detail = 'Frozen image · ' + (v.calibration_elapsed || 0) + 's elapsed. Keep the phone and board still.';
  }
  $('setupTitle').textContent = title;
  $('setupDetail').textContent = detail;
  $('setupStatus').classList.toggle('ready', phase === 'ready' && !selecting && !calibrationBusy);

  const source = v.source;
  const streaming = source ? source.connected && v.fresh : !!v.fresh;
  const calibrated = !!v.overlay;
  mark('readyCamera', streaming, source && !source.connected && source.error,
    streaming ? 'Camera stream' + (source?.width ? ' · ' + source.width + '×' + source.height + ' · ' + source.fps + ' fps' : '')
      : 'Camera stream · not connected');
  mark('readyCalibrated', calibrated, false, 'Four points set');
  mark('readyAligned', v.aligned, calibrated && !v.aligned, 'Board aligned with the live image');
  mark('readyVerified', v.verified, false, 'Overlay checked and verified');

  if (!$('sourceStatus').dataset.tested) {
    const [text, kind] = describeSource(source);
    $('sourceStatus').textContent = text;
    $('sourceStatus').className = kind || 'muted';
    // With no source, keep any hint from a failed Test connection until the address is edited.
    if (source) showHint(source.connected ? '' : friendlyHint(source.error));
  }
  renderSteps(v);
  footPoint(v);
  calibrationQuality(v.calibration);
}

// How the four points were turned into the board position (vision.state().calibration, M1-05c). Any field may be
// missing on older servers; a warning (wrong click order, rotated phone...) is shown prominently.
function calibrationQuality(report) {
  const line = $('calibrationQuality');
  if (!report || typeof report !== 'object') { line.hidden = true; return; }
  const parts = [];
  parts.push(report.method === 'refined' ? 'Calibration refined on the double ring' :
    report.method === 'clicks' ? 'Calibration from your four clicks' : 'Calibration: ' + (report.method || 'unknown'));
  if (report.confidence) parts.push('confidence ' + report.confidence);
  if (typeof report.residual_mm === 'number') parts.push('fit ' + report.residual_mm.toFixed(2) + ' mm');
  if (report.reason) parts.push(report.reason);
  const warning = typeof report.warning === 'string' && report.warning;
  line.textContent = parts.join(' · ') + (warning ? ' — ' + warning : '');
  line.className = warning || report.confidence === 'low' ? 'warning' : 'muted';
  line.hidden = false;
}

function mark(id, done, problem, text) {
  $(id).textContent = text;
  $(id).classList.toggle('done', !!done);
  $(id).classList.toggle('problem', !done && !!problem);
}

function footPoint(v) {
  const foot = v.foot, pose = v.pose;
  if (document.activeElement !== $('mountSide')) $('mountSide').value = v.mount_side || '';
  if (!foot) {
    $('footText').textContent = 'Camera position: set four points first.';
    $('footArrow').setAttribute('x2', 0); $('footArrow').setAttribute('y2', 0);
    $('footDot').hidden = true;
    return;
  }
  const [x, y] = foot, distance = Math.hypot(x, y);
  const parts = [];
  if (Math.abs(y) >= 20) parts.push(Math.round(Math.abs(y) / 10) + ' cm ' + (y < 0 ? 'above' : 'below'));
  if (Math.abs(x) >= 20) parts.push(Math.round(Math.abs(x) / 10) + ' cm ' + (x < 0 ? 'left' : 'right') + ' of');
  const from = {solved: 'from calibration', fallback: 'estimated (camera faces the board almost straight on)', manual: 'set by hand'};
  const out = pose?.C ? ' · ' + Math.round(pose.C[2] / 10) + ' cm out from the board' : '';
  $('footText').textContent = 'Camera position: ' + (parts.length ? parts.join(', ') + ' the bull' : 'straight in front of the bull') +
    out + ' (' + (from[pose?.source] || 'unknown') + ').';
  const scale = distance > 0 ? Math.min(90, 62 * Math.max(1.2, distance / 170)) / distance : 0;
  $('footArrow').setAttribute('x2', (x * scale).toFixed(1));
  $('footArrow').setAttribute('y2', (y * scale).toFixed(1));
  $('footDot').setAttribute('cx', (x * scale).toFixed(1));
  $('footDot').setAttribute('cy', (y * scale).toFixed(1));
  $('footDot').hidden = false;
}

$('mountSide').onchange = async () => {
  if (actionBusy) return;
  actionBusy = true; controls();
  try { error(''); await api('camera/mount_side', {mount_side: $('mountSide').value || null}); }
  catch (e) { error(e.message); }
  finally { actionBusy = false; await refresh(); controls(); }
};

// ---- recording (M1-14) ----
const gigabytes = bytes => bytes == null ? '?' : (bytes / 1024 ** 3).toFixed(1) + ' GB';
let idleFreeBytes = null;

async function refreshDisk() {
  try { idleFreeBytes = (await api('record/disk')).free_bytes; recordingStatus(); } catch (e) { /* shown on next poll */ }
}

function notes() {
  const fields = {mount: $('noteMount').value.trim(), lighting: $('noteLighting').value.trim(), phone: $('notePhone').value.trim()};
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value));
}

function recordingStatus() {
  const r = state?.recording;
  if (!r) return;
  $('recordToggle').textContent = r.active ? 'Stop recording' : 'Start recording';
  $('recordToggle').classList.toggle('primary', !r.active);
  const minutes = Math.floor((r.seconds || 0) / 60), seconds = Math.round((r.seconds || 0) % 60);
  let text = r.active ? '● Recording · ' + minutes + ' min ' + seconds + ' s · ' + gigabytes(r.bytes) + ' · ' +
    r.frames + ' frames' + (r.skipped_frames ? ' (' + r.skipped_frames + ' skipped)' : '') + ' · ' + gigabytes(r.free_bytes) +
    ' free · ' + r.directory : 'Not recording · ' + gigabytes(idleFreeBytes) + ' free' +
    (r.directory ? ' · last session ' + r.directory : '');
  if (r.error) text += ' · ' + r.error;
  $('recordStatus').textContent = text;
  $('recordStatus').className = r.error ? 'warning' : r.active ? 'ok' : 'muted';
}

act('recordToggle', async () => {
  await api('record', state?.recording?.active ? {enabled: false} : {enabled: true, notes: notes()});
});
act('saveNotes', async () => { await api('record/notes', {notes: notes()}); });

// ---- overlay geometry: board mm -> image pixels from the four calibration points ----
function solveHomography(src, dst) {
  const rows = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    rows.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  }
  for (let col = 0; col < 8; col++) {  // Gaussian elimination with partial pivoting
    let pivot = col;
    for (let r = col + 1; r < 8; r++) if (Math.abs(rows[r][col]) > Math.abs(rows[pivot][col])) pivot = r;
    [rows[col], rows[pivot]] = [rows[pivot], rows[col]];
    if (Math.abs(rows[col][col]) < 1e-12) return null;
    for (let r = 0; r < 8; r++) {
      if (r === col) continue;
      const factor = rows[r][col] / rows[col][col];
      for (let c = col; c < 9; c++) rows[r][c] -= factor * rows[col][c];
    }
  }
  return [...rows.map((row, i) => row[8] / row[i]), 1];
}

function project(H, x, y) {
  const w = H[6] * x + H[7] * y + H[8];
  return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
}

function boardHomography(overlay) {
  return overlay && overlay.length === 4 ? solveHomography(TARGET_MM, overlay) : null;
}

// Image points of the ring of radius r (mm), for drawing and for tests.
function ringPoints(overlay, radius, count = 120) {
  const H = boardHomography(overlay);
  if (!H) return [];
  return Array.from({length: count}, (_, i) => {
    const angle = 2 * Math.PI * i / count;
    return project(H, radius * Math.cos(angle), radius * Math.sin(angle));
  });
}
window.setupOverlay = {ringPoints, boardHomography, project};

function drawBoardOverlay(ctx, overlay, width) {
  const H = boardHomography(overlay);
  if (!H) return;
  const line = Math.max(1.5, width / 900);
  ctx.save();
  ctx.lineWidth = line;
  ctx.strokeStyle = 'rgba(206, 255, 117, 0.9)';
  for (const radius of RING_RADII) {
    const ring = ringPoints(overlay, radius, radius < 20 ? 48 : 180);
    ctx.beginPath();
    ring.forEach(([u, v], i) => (i ? ctx.lineTo(u, v) : ctx.moveTo(u, v)));
    ctx.closePath();
    ctx.stroke();
  }
  ctx.beginPath();
  for (let k = 0; k < 20; k++) {
    const angle = (-90 - 9 + 18 * k) * Math.PI / 180;
    const [u1, v1] = project(H, 15.9 * Math.cos(angle), 15.9 * Math.sin(angle));
    const [u2, v2] = project(H, 170 * Math.cos(angle), 170 * Math.sin(angle));
    ctx.moveTo(u1, v1);
    ctx.lineTo(u2, v2);
  }
  ctx.stroke();
  ctx.fillStyle = 'rgba(206, 255, 117, 0.95)';
  ctx.font = 'bold ' + Math.round(Math.max(14, width / 60)) + 'px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  SECTORS.forEach((number, k) => {
    const angle = (-90 + 18 * k) * Math.PI / 180;
    const [u, v] = project(H, 195 * Math.cos(angle), 195 * Math.sin(angle));
    ctx.fillText(String(number), u, v);
  });
  ctx.restore();
}

function drawMarkers(ctx, markers, width) {
  const size = Math.max(8, width / 120);
  markers.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p[0], p[1], size, 0, Math.PI * 2);
    ctx.strokeStyle = '#ceff75';
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.font = 'bold ' + Math.round(size * 3) + 'px system-ui';
    ctx.fillStyle = '#ceff75';
    ctx.fillText(String(i + 1), p[0] + size * 1.5, p[1] + size * 0.6);
  });
}

function draw() {
  const image = selecting ? frozenImage : lastImage;
  if (!image) return;
  const c = $('board'), ctx = c.getContext('2d');
  c.width = image.width;
  c.height = image.height;
  ctx.drawImage(image, 0, 0);
  $('stageEmpty').hidden = true;
  if (selecting) {
    drawMarkers(ctx, points, image.width);
    return;
  }
  displayedVersion = state?.vision?.version;
  const overlay = state?.vision?.overlay;
  if (overlay) {
    drawBoardOverlay(ctx, overlay, image.width);
    drawMarkers(ctx, overlay, image.width);
  }
}

// ---- loupe while selecting points ----
function canvasPoint(event) {
  const rect = $('board').getBoundingClientRect();
  return [(event.clientX - rect.left) * $('board').width / rect.width,
    (event.clientY - rect.top) * $('board').height / rect.height, rect];
}

$('board').addEventListener('mousemove', event => {
  const loupe = $('loupe');
  if (!selecting || !frozenImage) { loupe.hidden = true; return; }
  const [x, y, rect] = canvasPoint(event), zoom = 4, size = loupe.width, half = size / zoom / 2;
  const ctx = loupe.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#0b100d';
  ctx.fillRect(0, 0, size, size);
  ctx.drawImage(frozenImage, x - half, y - half, half * 2, half * 2, 0, 0, size, size);
  ctx.strokeStyle = '#ff5a4f';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(size / 2, 0); ctx.lineTo(size / 2, size);
  ctx.moveTo(0, size / 2); ctx.lineTo(size, size / 2);
  ctx.stroke();
  const offsetX = event.clientX - rect.left, offsetY = event.clientY - rect.top;
  loupe.style.left = Math.min(rect.width - size, Math.max(0, offsetX + 24)) + 'px';
  loupe.style.top = Math.max(0, offsetY - size - 24) + 'px';
  loupe.hidden = false;
});
$('board').addEventListener('mouseleave', () => { $('loupe').hidden = true; });

// ---- polling ----
// What the camera is doing right now, in numbers (for "it is not detecting" on the real board).
function diagnosticsText(v) {
  const d = v.diagnostics;
  if (!d || d.motion_pct === undefined) return '';
  const looked = d.looked_at ? Math.max(0, Math.round(Date.now() / 1000 - d.looked_at)) + ' s ago' : 'not yet';
  return 'Camera check: picture changing ' + d.motion_pct + '% (needs under ' + d.still_pct + '%) · still frames ' +
    d.stable + '/' + d.stable_needed + ' · last look ' + looked + (d.last_look ? ' → ' + d.last_look +
    ' (' + d.changed_blobs + ' change' + (d.changed_blobs === 1 ? '' : 's') + ')' : '') +
    (v.source?.processed_fps != null ? ' · ' + v.source.processed_fps + ' fps processed' : '');
}

async function refresh() {
  if (pollBusy || actionBusy || calibrationBusy) return;
  pollBusy = true;
  const epoch = stateEpoch;
  try {
    const incoming = await api('state');
    if (epoch !== stateEpoch) return;
    state = incoming;
    serverConnected = true;
    if (errorSource === 'connection') error('');
    $('connection').textContent = state.vision.fresh ? 'Camera connected' : 'Camera offline';
    $('connection').className = 'chip ' + (state.vision.fresh ? 'ok' : 'problem');
    loadLinks();
    if (selecting && !state.vision.calibration_active) {
      selecting = false; snapshotId = null; frozenImage = null; $('loupe').hidden = true;
      error('Calibration image expired or was replaced. Select Freeze and set four points again.');
    }
    fillSourceField(state.vision.source?.url_redacted);
    renderZoom(state);
    $('visionStatus').textContent = state.vision.message +
      (state.vision.board_warning && state.vision.board_warning !== state.vision.message
        ? ' · ' + state.vision.board_warning : '') +
      (state.vision.age_seconds != null ? ' · frame ' + state.vision.age_seconds + 's old' : '');
    $('visionDiagnostics').textContent = diagnosticsText(state.vision);
    renderGame(state.game);
    const p = state.camera?.pending;
    $('candidate').textContent = p ? 'Suggested ' + p.label + ' = ' + p.score +
      (p.near_wire ? ' · Near wire; check carefully' : '') +
      (p.commit_in != null ? ' · auto-accept in ' + Math.ceil(p.commit_in) + ' s' : '') +
      ' · Prototype tip guess: check the real dart.' : 'No dart proposal.';
    setupStatus();
    recordingStatus();
    controls();
  } catch (e) {
    if (epoch !== stateEpoch) return;
    serverConnected = false;
    $('connection').textContent = 'Disconnected';
    $('connection').className = 'chip problem';
    error(e.message, 'connection');
    if (state) state = {...state, vision: {...state.vision, fresh: false, aligned: false, verified: false}};
    controls();
    $('setupTitle').textContent = 'Server disconnected';
    $('setupDetail').textContent = 'Check that Dart Room is still running in Terminal.';
    renderSteps({});
  } finally {
    pollBusy = false;
  }
}

// Live preview at about 5 frames per second while the camera is fresh.
async function previewLoop() {
  for (;;) {
    const started = performance.now();
    if (state?.vision?.fresh && serverConnected && !selecting && !calibrationBusy && !document.hidden) {
      const epoch = stateEpoch;
      try {
        const image = await loadImage('image');
        if (epoch === stateEpoch && !selecting && !calibrationBusy) {
          lastImage = image;
          draw();
          controls();
        }
      } catch (e) { /* the state poll reports camera problems */ }
    }
    await pause(Math.max(50, 200 - (performance.now() - started)));
  }
}

function renderGame(g) {
  $('players').replaceChildren();
  if (!g) return;
  g.names.forEach((name, i) => {
    const card = document.createElement('div');
    card.className = 'player' + (g.player === i ? ' active' : '');
    const n = document.createElement('div');
    n.textContent = name;
    const s = document.createElement('div');
    s.className = 'score';
    s.textContent = g.scores[i];
    card.append(n, s);
    $('players').append(card);
  });
  $('turnStatus').textContent = g.winner !== null ? g.names[g.winner] + ' wins!' :
    g.names[g.player] + "'s turn · " + g.darts.length + '/3 darts' + (g.bust ? ' · BUST — score restored' : '') +
    ' · Throws: ' + (g.darts.map(d => d.score).join(', ') || 'none');
}

// ---- calibration ----
act('calibrate', async () => {
  const result = await api('calibration/start', {});
  state = result;
  snapshotId = result.snapshot.snapshot_id;
  frozenImage = await loadImage('calibration/image?id=' + encodeURIComponent(snapshotId));
  points = [];
  selecting = true;
  $('guide').textContent = 'Frozen image: click 1 · ' + CLICK_STEPS[0];
  draw();
  $('board').scrollIntoView({block: 'center'});  // the frozen image is where the next four clicks go
  setupStatus();
});

act('cancelCalibration', async () => {
  await api('calibration/cancel', {});
  selecting = false; snapshotId = null; frozenImage = null; points = []; $('loupe').hidden = true;
  $('guide').textContent = 'Calibration cancelled. Empty the board and try again.';
});

$('board').onclick = async e => {
  if (!selecting || !frozenImage || actionBusy || calibrationBusy || !state?.vision?.fresh) return;
  const [x, y] = canvasPoint(e);
  points.push([x, y]);
  draw();
  setupStatus();
  if (points.length < 4) {
    $('guide').textContent = 'Frozen image: click ' + (points.length + 1) + ' · ' + CLICK_STEPS[points.length];
    return;
  }
  calibrationBusy = true;
  $('loupe').hidden = true;
  controls();
  setupStatus();
  try {
    await api('calibrate', {points, snapshot_id: snapshotId});
    $('guide').textContent = 'Check every ring and sector line on the live image. If they sit on the wires, press Markers correct · Ready to play.';
  } catch (e) {
    error(e.message);
    $('guide').textContent = 'Calibration needs attention. Check alignment or select Freeze and set four points again.';
  } finally {
    selecting = false; snapshotId = null; frozenImage = null; calibrationBusy = false;
    await refresh();
    controls();
  }
};

act('align', async () => {
  await api('align', {});
  $('guide').textContent = 'Check the overlay on the live image, then press Markers correct · Ready to play.';
});
act('verify', async () => {
  await api('verify', {version: state.vision.version});
  $('guide').textContent = 'Calibration verified. Start a game from the Controller (scan the code in step 3), or press ' +
    'Start game in the older controls. After phone or board movement, check alignment and verify again.';
});
act('baseline', async () => {
  const result = await api('baseline', {});
  if (result.baseline && !result.baseline.board_empty) error(result.vision.board_warning);  // QA M4 M4
});

// ---- game (unchanged behaviour) ----
function names() {
  const count = +$('count').value;
  $('names').replaceChildren();
  for (let i = 0; i < count; i++) {
    const input = document.createElement('input');
    input.id = 'name' + i;
    input.value = 'Player ' + (i + 1);
    input.maxLength = 30;
    input.setAttribute('aria-label', 'Player ' + (i + 1) + ' name');
    $('names').append(input);
  }
}

function manualRingChoices() {
  const value = +$('value').value, ring = $('multiplier'), prior = +ring.value;
  for (const option of ring.options) {
    option.disabled = (value === 0 && option.value !== '1') || (value === 25 && option.value === '3');
  }
  const corrected = value === 0 || ring.selectedOptions[0]?.disabled;
  if (corrected) ring.value = '1';
  ring.disabled = value === 0;
  $('manualScoreHelp').textContent = value === 0 ? 'Miss records 0 points and counts as one dart.' :
    value === 25 ? (prior === 3 ? 'Bull has no triple. Ring reset to Single (25); choose Double for 50.' :
      'Bull: Single = outer bull (25), Double = inner bull (50).') :
      'Choose Single, Double or Triple for the selected number.';
}

act('newGame', async () => {
  if (state?.game && state.game.winner === null && !confirm('Replace the current game?')) return;
  await api('game', {
    names: Array.from({length: +$('count').value}, (_, i) => $('name' + i).value),
    start: +$('start').value,
    double_out: $('doubleOut').checked,
    camera: $('cameraGame').checked,
  });
});
act('confirm', () => api('throw', {proposal_id: state?.camera?.pending?.id, label: state?.camera?.pending?.label}));
act('manual', () => api('throw', {value: +$('value').value, multiplier: +$('multiplier').value}));
act('undo', () => api('undo', {}));
act('next', () => api('next', {}));

// ---- start ----
$('count').onchange = names;
names();
$('cameraGame').onchange = controls;
for (let i = 1; i <= 20; i++) $('value').add(new Option(String(i), String(i)));
$('value').add(new Option('Bull (25 / 50)', 25));
$('value').onchange = manualRingChoices;
manualRingChoices();
$('phoneIp').oninput = () => {
  sourceFieldTouched = true;
  showHint('');
  delete $('sourceStatus').dataset.tested;
  if ($('sourcePreset').value === 'custom') $('sourcePreset').value = 'ipwebcam';  // an IP means a phone app
  sourceFromPreset();
};
$('sourcePreset').onchange = () => { sourceFieldTouched = true; showHint(''); delete $('sourceStatus').dataset.tested; sourceFromPreset(); };
$('sourceUri').oninput = () => {
  sourceFieldTouched = true;
  showHint('');
  delete $('sourceStatus').dataset.tested;
  $('sourcePreset').value = presetFromUri($('sourceUri').value.trim());
  controls();
};
rememberOpenSections();
const remembered = rememberedSource();
if (remembered) fillSourceField(remembered);
controls();
setInterval(refresh, 1000);
refresh();
refreshDisk();
setInterval(refreshDisk, 10000);
previewLoop();
