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
        d = re.search(r'/play\?t=([^\s]+)', line or '')
        if d: globals()['DISPLAY'] = d.group(1); break
        if m:
            TOKEN = m.group(1)
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

