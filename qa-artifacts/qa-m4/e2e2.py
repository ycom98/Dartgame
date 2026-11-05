"""QA M4 end-to-end: real server.py subprocess + fake IP Webcam (sim ceiling-1.5ft, 1280x720)."""
import http.client, json, os, re, socket, subprocess, sys, time
ROOT = sys.argv[1]
OUT = sys.argv[2]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))
import numpy as np
from fake_ipwebcam import FakeIPWebcam
from sim import camera_for_mount
from sim.scene import Dart, calibration_points, render_clean, degrade, PROFILES
from core import score_point

PY = '/home/user/dart-room/.venv/bin/python'
camera = camera_for_mount('ceiling-1.5ft', 1280, 720)
points = calibration_points(camera).tolist()
rng = np.random.default_rng(7)
def frames(ds, n=3):
    clean = render_clean(camera, ds)
    return [degrade(clean, PROFILES['realistic'], rng)[0] for _ in range(n)]

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

fake = FakeIPWebcam(frames([]), fps=15).start()
PORT = free_port()
STATE = os.path.join(OUT, 'state', 'match.json')
os.makedirs(os.path.dirname(STATE), exist_ok=True)
TOKEN = None
proc = None
results = []

def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + ('  ' + str(detail) if detail else ''), flush=True)

def start_server(extra=()):
    global proc, TOKEN
    log = open(os.path.join(OUT, 'server.log'), 'a')
    proc = subprocess.Popen([PY, '-B', os.path.join(ROOT, 'server.py'), '--host', '127.0.0.1', '--port', str(PORT),
                             '--lan-ip', '127.0.0.1', '--camera', fake.url + '/video', '--state-file', STATE,
                             '--auto-commit', '1.5', *extra], cwd=ROOT, stdout=subprocess.PIPE, stderr=log, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line: log.write(line); log.flush()
        m = re.search(r'/control\?t=([^\s]+)', line or '')
        if m:
            TOKEN = m.group(1); break
    import threading
    threading.Thread(target=lambda: [log.write(l) or log.flush() for l in proc.stdout], daemon=True).start()
    wait(lambda: state()['vision']['fresh'], 10)

def stop_server():
    proc.terminate(); proc.wait(10)

def req(path, body=None, rev=True):
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=20)
    if body is not None and rev and 'expected_revision' not in body:
        body = {**body, 'expected_revision': state()['revision']}
    c.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None,
              {'Authorization': 'Bearer ' + TOKEN})
    r = c.getresponse(); data = r.read(); c.close()
    try: data = json.loads(data)
    except ValueError: pass
    return r.status, data

def state(): return req('/api/state')[1]
def wait(pred, t, step=0.1):
    end = time.time() + t
    while time.time() < end:
        v = pred()
        if v: return v
        time.sleep(step)
    return pred()
def pend(): return state()['camera']['pending_darts']
def labels(): return [d['label'] for d in pend()]
def lab(d):
    v, m = d.get('value'), d.get('multiplier')
    if not v: return 'Miss'
    if v == 25: return 'Bull' if m == 2 else 'Outer'
    return {1: 'S', 2: 'D', 3: 'T'}[m] + str(v)
def game_darts(): return [lab(d) for d in state()['game']['darts']]
def show(ds, settle=1.2):
    fake.set_frames(frames(ds)); time.sleep(settle)

def calibrate_and_verify():
    st, s = req('/api/calibration/start', {})
    st, c = req('/api/calibrate', {'snapshot_id': s['snapshot']['snapshot_id'], 'points': points})
    st, v = req('/api/verify', {'version': c['vision']['version']})
    return st

def pause(p): req('/api/camera/auto_commit', {'paused': p})

D = [Dart(x=30.0, y=-100.0, tilt=12.0), Dart(x=-75.0, y=40.0, tilt=12.0), Dart(x=60.0, y=75.0, tilt=12.0)]
L = [score_point(d.x, d.y)['label'] for d in D]
try:
    start_server(['--fresh'])
    check('verify after calibration', calibrate_and_verify() == 200)
    st, g = req('/api/game', {'names': ['Ana', 'Ben'], 'start': 501, 'camera': True})
    check('camera game started', st == 200, g.get('error'))
    time.sleep(0.8)
    # --- 1. three darts, no commits (auto-commit paused)
    pause(True)
    for k in range(1, 4):
        show(D[:k])
        wait(lambda: len(pend()) >= k, 4)
    check('three pending darts oldest first', labels() == L, (labels(), L))
    s = state()
    check('/api/state camera.pending_darts present & head==pending', s['camera']['pending']['id'] == s['camera']['pending_darts'][0]['id'])
    check('later darts queued, no countdown', all(d['queued'] and d['commit_in'] is None for d in s['camera']['pending_darts'][1:]))
    ids = [d['id'] for d in s['camera']['pending_darts']]
    # --- 2. commit dart 2 before dart 1
    st, r = req('/api/throw', {'proposal_id': ids[1]})
    check('accept dart 2 before dart 1 -> 409', st == 409, (st, r.get('error')))
    st, r = req('/api/throw', {'replaces_proposal_id': ids[2], 'value': 20, 'multiplier': 1})
    check('correct dart 3 before dart 1 -> 409', st == 409, (st, r.get('error')))
    check('nothing recorded by the 409s', game_darts() == [], game_darts())
    # stale revision
    rev = state()['revision']
    st, r = req('/api/throw', {'proposal_id': ids[0], 'expected_revision': rev - 1})
    check('stale revision accept -> 409', st == 409, (st, r.get('error')))
    st, r = req('/api/throw', {'proposal_id': ids[0], 'label': L[0]})
    check('accept head', st == 200, r.get('error'))
    st, r = req('/api/throw', {'proposal_id': ids[0]})
    check('accept head twice -> 409', st == 409, st)
    # auto-commit each dart has own countdown: unpause, head (dart 2) commits after ~1.5 s, then dart 3 after another 1.5 s
    t0 = time.time(); pause(False)
    wait(lambda: len(game_darts()) >= 2, 5); t1 = time.time() - t0
    wait(lambda: len(game_darts()) >= 3, 5); t2 = time.time() - t0
    check('auto-commit dart2 then dart3, each with own countdown', game_darts() == L and t1 >= 1.3 and t2 - t1 >= 1.3,
          (game_darts(), round(t1, 2), round(t2, 2)))
    # pull darts one by one, then Next
    show(D[1:]); show(D[2:]); show([])
    s = state()
    check('board cleared after pulling', 'cleared' in s['vision']['message'] or s['vision']['turn']['board_cleared'] >= 1, (s['vision']['message'], s['vision'].get('turn')))
    check('no phantom pending after normal pull', pend() == [], labels())
    st, r = req('/api/next', {}); check('next player', st == 200, r.get('error'))
    # --- 3. stale revision on other writes
    rev = state()['revision']
    for path, body in (('/api/throw', {'value': 20, 'multiplier': 1}), ('/api/undo', {}), ('/api/next', {}),
                       ('/api/turn/fill_misses', {})):
        st, r = req(path, {**body, 'expected_revision': rev - 1})
        check('stale revision %s -> 409' % path, st == 409, st)
    # --- 4. flagged dart is not auto-committed (Ben's turn)
    upper = Dart(10.0, -60.0, length=125.0, tilt=10.0, azimuth=0.0)
    below = Dart(10.0, -25.0, length=125.0, tilt=10.0, azimuth=0.0)
    show([upper]); wait(lambda: len(game_darts()) >= 1, 5)
    check('upper dart auto-committed', len(game_darts()) == 1, game_darts())
    show([upper, below]); time.sleep(4.0)
    p = pend()
    check('flagged dart still pending after 2x delay', len(p) == 1 and p[0]['needs_check'] and p[0]['commit_in'] is None
          and 'tip may be hidden' in (p[0].get('check') or []), p and {k: p[0][k] for k in ('label', 'check', 'confidence', 'needs_check', 'commit_in')})
    check('flagged dart not in game', len(game_darts()) == 1, game_darts())
    # --- 5. undo with pending dart: undo the upper dart while flagged dart pending
    st, r = req('/api/undo', {}); check('undo with pending', st == 200, r.get('error'))
    check('pending kept after undo', len(pend()) == 1, labels())
    st, r = req('/api/throw', {'proposal_id': pend()[0]['id']}); check('accept flagged after undo', st == 200, r.get('error'))
    print('game darts after undo+accept (dart 2 recorded as dart 1):', game_darts())
    st, r = req('/api/throw', {'value': 0, 'multiplier': 1}); print('manual miss', st, r.get('error') if isinstance(r, dict) else r)
    # --- 6. restart mid-turn: Ana's next turn, dart 1 committed + dart 2 pending, then restart
    show([]); show([])
    st, r = req('/api/next', {}); print('next', st, r.get('error'))
    print('vision message before Ana turn:', state()['vision']['message'], 'pending', labels())
    pause(True)
    show(D[:1]); wait(lambda: len(pend()) >= 1, 4)
    st, r = req('/api/throw', {'proposal_id': pend()[0]['id']}); check('ana d1 accepted', st == 200, (r.get('error'), labels()))
    show(D[:2]); wait(lambda: len(pend()) >= 1, 4)
    check('ana d2 pending before restart', labels() == L[1:2], labels())
    before = state()['game']['darts']
    stop_server(); start_server()
    s = wait(lambda: 'matches the saved' in state()['vision']['message'] and state(), 15) or state()
    check('restart: match restored', s['game']['darts'] == before, (s['game']['darts'], before))
    print('restart vision:', s['vision']['phase'], s['vision']['message'], 'pending', labels())
    st, r = req('/api/verify', {'version': state()['vision']['version']}); check('verify after restart', st == 200, r.get('error') if isinstance(r, dict) else r)
    check('restart: the pending dart 2 is gone (must be tapped)', labels() == [], labels())
    show(D[:3]); wait(lambda: len(pend()) >= 1, 4)
    check('restart: dart 3 detected', labels() == L[2:3], labels())
    st, r = req('/api/throw', {'value': 16, 'multiplier': 1})  # host taps dart 2 by hand... (head is dart 3) -> manual throw
    print('manual tap of lost dart 2 while dart3 pending:', st, r.get('error') if isinstance(r, dict) else '', 'pending', labels())
    if pend(): req('/api/throw', {'proposal_id': pend()[0]['id']})
    print('ana darts', game_darts())
    pause(False)
    st, r = req('/api/next', {}); print('next', st, r.get('error'))
    # Ben now; Ana's darts are pulled one by one
    show(D[1:]); show(D[2:]); show([], 1.0)
    print('after pull: msg', state()['vision']['message'], 'pending', labels(), 'turn', state()['vision'].get('turn'))
    time.sleep(3.0)
    g = state()['game']
    check('restart: pulling the earlier darts adds no darts to the next player', game_darts() == [], (game_darts(), labels()))
    st, r = req('/api/baseline', {}); print('baseline', st)
    # --- 6b. stream drop mid-turn (camera source re-set), then pull after Next
    st, r = req('/api/baseline', {})
    print('6b start: turn darts', game_darts(), 'pending', labels())
    if len(game_darts()) == 3: req('/api/next', {})
    if game_darts(): req('/api/turn/fill_misses', {}); req('/api/next', {})
    pause(False)
    show([]); show(D[:1]); wait(lambda: len(game_darts()) >= 1, 5)
    show(D[:2]); wait(lambda: len(game_darts()) >= 2, 5)
    print('6b two darts auto-committed', game_darts())
    fake.stop(); time.sleep(6.5)  # the phone drops for 6 s
    fake.start(); time.sleep(0.2)
    ready = wait(lambda: state()['vision']['verified'], 20)
    print('6b after drop: verified', ready, state()['vision']['message'])
    show(D[:3]); wait(lambda: len(game_darts()) >= 3, 6)
    print('6b dart 3', game_darts())
    st, r = req('/api/next', {}); print('6b next', st, r.get('error'))
    show(D[1:]); show(D[2:]); show([], 1.0); time.sleep(2.5)
    check('stream drop: pulling the darts adds no darts to the next player', game_darts() == [], (game_darts(), labels(), state()['vision']['message']))
    # --- 6c. Check/realign mid-turn (manual /api/align), then pull after Next
    req('/api/turn/fill_misses', {}) if game_darts() else None
    if game_darts(): req('/api/next', {})
    show([]); req('/api/baseline', {}); pause(False)
    show(D[:1]); wait(lambda: len(game_darts()) >= 1, 5)
    show(D[:2]); wait(lambda: len(game_darts()) >= 2, 5)
    st, r = req('/api/align', {}); print('6c align', st, r.get('error'), state()['vision']['message'])
    if not state()['vision']['verified']: req('/api/verify', {'version': state()['vision']['version']})
    show(D[:3]); wait(lambda: len(game_darts()) >= 3, 6); print('6c turn', game_darts())
    req('/api/next', {})
    show(D[1:]); show(D[2:]); show([], 1.0); time.sleep(2.5)
    check('check/realign: pulling the darts adds no darts to the next player', game_darts() == [], (game_darts(), labels(), state()['vision']['message']))
    # --- 6d. restart mid-turn, then pull the LAST dart first
    show([]); req('/api/baseline', {}); pause(False)
    show(D[:1]); wait(lambda: len(game_darts()) >= 1, 5)
    show(D[:2]); wait(lambda: len(game_darts()) >= 2, 5)
    stop_server(); start_server()
    wait(lambda: 'matches the saved' in state()['vision']['message'], 15)
    req('/api/verify', {'version': state()['vision']['version']})
    show(D[:3]); wait(lambda: len(game_darts()) >= 3, 6); print('6d turn', game_darts())
    req('/api/next', {})
    show(D[:2]); show(D[1:2]); show([], 1.0); time.sleep(2.5)
    check('restart, last dart pulled first: no darts to the next player', game_darts() == [], (game_darts(), labels(), state()['vision']['message']))
    # --- 6e. Board clear pressed with 2 darts still in, survives a restart, then pull
    show([]); req('/api/baseline', {}); pause(False)
    if game_darts(): req('/api/turn/fill_misses', {}); req('/api/next', {})
    show(D[:1]); wait(lambda: len(game_darts()) >= 1, 5)
    show(D[:2]); wait(lambda: len(game_darts()) >= 2, 5)
    st, r = req('/api/baseline', {}); print('6e board clear with darts in', st, state()['vision']['message'])
    stop_server(); start_server()
    wait(lambda: 'matches the saved' in state()['vision']['message'], 15)
    req('/api/verify', {'version': state()['vision']['version']})
    show(D[:3]); wait(lambda: len(game_darts()) >= 3, 6); print('6e turn', game_darts())
    req('/api/next', {})
    show(D[:2]); show(D[1:2]); show([], 1.0); time.sleep(2.5)
    check('board clear with darts in (operator error): no darts to the next player', game_darts() == [], (game_darts(), labels(), state()['vision']['message']))
    # --- 6f. calibration warning through the server, darts in vs empty
    show(D[:2]); st, s1 = req('/api/calibration/start', {}); st, c1 = req('/api/calibrate', {'snapshot_id': s1['snapshot']['snapshot_id'], 'points': points})
    check('calibrate with darts in: warning', 'does not look empty' in c1['vision']['message'], c1['vision']['message'])
    show([]); st, s1 = req('/api/calibration/start', {}); st, c1 = req('/api/calibrate', {'snapshot_id': s1['snapshot']['snapshot_id'], 'points': points})
    check('calibrate on empty board: no warning', 'does not look empty' not in c1['vision']['message'], c1['vision']['message'])
    req('/api/verify', {'version': c1['vision']['version']})
    # --- 7. recalibration while darts pending
    pause(True)
    for d in game_darts(): pass
    show([D[0]]); wait(lambda: len(pend()) >= 1, 4)
    print('before recal pending', labels())
    st = calibrate_and_verify(); check('recalibrate with pending', st == 200, st)
    check('recalibration drops pending darts', labels() == [], labels())
    show([D[0], D[1]]); wait(lambda: len(pend()) >= 1, 4); print('after recal next dart', labels())
    # --- 8. manual game and camera off
    st, r = req('/api/game', {'names': ['A', 'B'], 'start': 301, 'camera': False}); check('manual game', st == 200, r.get('error'))
    for path, body in (('/api/throw', {'value': 20, 'multiplier': 3}), ('/api/undo', {}), ('/api/throw', {'value': 5, 'multiplier': 1}),
                       ('/api/turn/fill_misses', {}), ('/api/next', {})):
        st, r = req(path, body); check('manual game %s' % path, st == 200, r.get('error') if isinstance(r, dict) else r)
    st, r = req('/api/camera/source', {'uri': None}); check('camera off', st == 200)
    for path, body in (('/api/throw', {'value': 20, 'multiplier': 1}), ('/api/undo', {}), ('/api/next', {})):
        st, r = req(path, body); check('camera off %s' % path, st in (200, 400) and st != 500, (st, r.get('error') if isinstance(r, dict) else r))
    s = state(); check('state with camera off', 'pending_darts' in s['camera'], s['camera'])
finally:
    try: stop_server()
    except Exception: pass
    fake.stop()
print('\nSUMMARY: %d pass, %d fail' % (sum(r[1] for r in results), sum(not r[1] for r in results)))
json.dump(results, open(os.path.join(OUT, 'e2e_results.json'), 'w'), indent=1)
