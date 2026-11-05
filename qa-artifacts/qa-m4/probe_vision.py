"""QA probes of Vision turn tracking edge cases (run with cwd = repo root on sys.path)."""
import sys, os
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
import cv2, numpy as np
from sim import camera_for_mount
from sim.scene import Dart, calibration_points, render_clean, degrade, PROFILES
from core import score_point
import vision as V

camera = camera_for_mount('ceiling-1.5ft')
points = calibration_points(camera).tolist()
SPOTS = [(30.0, -100.0), (-75.0, 40.0), (60.0, 75.0)]
darts = [Dart(x=x, y=y, tilt=12.0) for x, y in SPOTS]
labels = [score_point(x, y)['label'] for x, y in SPOTS]
rng = np.random.default_rng(5)
NOISY = '--noisy' in sys.argv

def frame(ds):
    img = render_clean(camera, ds)
    if NOISY:
        img = degrade(img, PROFILES['realistic'], rng)[0]
    return img

def show(v, ds, n=4):
    f = frame(ds)
    for _ in range(n):
        v.ingest(f if not NOISY else frame(ds))

def calibrated():
    v = V.Vision(); v.ingest(frame([])); v.calibrate(points); show(v, [], 3); v.reset_base(); return v

def P(v): return [p['label'] + ('!' if p.get('check') else '') for p in v.pending]

print('truth labels', labels)
# 1. Manual-scored (untracked) dart then pulled alone
v = calibrated()
show(v, darts[:1]); v.absorb()   # dart 1 scored by hand (camera's proposal cleared? absorb keeps tracked ones)
print('1a after absorb pending', P(v))
v.pending = []  # host typed it manually instead -> simulate: proposal was untracked? use real flow below
v = calibrated()
# camera misses dart 1 -> simulate by putting dart 1 in base via absorb with no proposal
v.base = v.warp(cv2.imdecode(cv2.imencode('.png', frame(darts[:1]))[1], 1)) if False else v.base
show(v, darts[:1]); d1 = v.pending[0]['id']; v.commit_dart(d1)
show(v, darts[:2]); v.commit_dart(v.pending[0]['id'])
show(v, darts[:3]); v.commit_dart(v.pending[0]['id'])
v.end_turn()
show(v, darts[1:3])  # pull dart 1
show(v, darts[2:3])
show(v, [])
print('1b normal pull after Next:', P(v), v.counters, v.message)

# 2. After an align (reconnect / recheck) mid-turn, darts become untracked; pull them
v = calibrated()
show(v, darts[:1]); v.commit_dart(v.pending[0]['id'])
show(v, darts[:2]); v.commit_dart(v.pending[0]['id'])
v.align(); print('2 after align tracked', len(v.tracked), 'pending', P(v))
show(v, darts[:3]); print('2 dart3 pending', P(v))
for p in list(v.pending): v.commit_dart(p['id'])
v.end_turn()
show(v, darts[1:3]); print('2 pulled dart1 (untracked) ->', P(v), v.message)
show(v, darts[2:3]); print('2 pulled dart2 (untracked) ->', P(v), v.message)
show(v, []); print('2 pulled all ->', P(v), v.counters, v.message)
show(v, darts[:1]); print('2 next turn dart ->', P(v), v.message)

# 3. Hand-scored dart (camera did not see it): absorb, then pull it alone mid-turn
v = calibrated()
show(v, darts[:1]); v.pending = []; v.tracked = []; v.absorb()  # untracked dart 1 in base
show(v, darts[:2]); print('3 dart2', P(v))
v.commit_dart(v.pending[0]['id'])
show(v, darts[1:2]); print('3 pulled the hand-scored dart1 ->', P(v), v.message)

# 4. Restart: fresh Vision, calibrated with darts already on board (turn_base has darts)
v = V.Vision(); v.ingest(frame(darts[:2])); v.calibrate(points); show(v, darts[:2], 3); v.reset_base()
show(v, darts[:3]); print('4 after restart dart3', P(v))
show(v, darts[1:3]); print('4 restart, pull dart 1 ->', P(v), v.message)

# 5. recalibration while pending
v = calibrated()
show(v, darts[:2]); print('5 pending', P(v)); v.calibrate(points); print('5 after calibrate', P(v), len(v.tracked), v.turn_base is v.base)

# 6. Undo of committed dart then the dart is pulled & re-thrown at same spot
v = calibrated()
show(v, darts[:1]); v.commit_dart(v.pending[0]['id'])
show(v, []); print('6 pulled the only dart ->', P(v), v.counters, v.message)

# 7. 4 darts (no Next pressed; or turn with all 3 pending then a 4th lands)
v = calibrated()
extra = Dart(x=-20.0, y=120.0, tilt=12.0)
for k in range(1, 4): show(v, darts[:k])
show(v, darts + [extra]); print('7 four darts', P(v), v.message)

# 8. two darts in one frame
v = calibrated()
show(v, darts[:2]); print('8 two at once', P(v), [p.get('together') for p in v.pending])

# 9. large occlusion: black-ish block covering half the board then removed
v = calibrated()
show(v, darts[:1])
f = frame(darts[:1]).copy(); h, w = f.shape[:2]; f[:, : w // 2] = 40
for _ in range(5): v.ingest(f)
print('9 occluded', v.aligned, P(v), v.message)
show(v, darts[:1]); print('9 after', v.aligned, P(v), v.message)
show(v, darts[:2]); print('9 next dart', P(v))
