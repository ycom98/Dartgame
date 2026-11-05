import sys; sys.path.insert(0, sys.argv[1])
import numpy as np
from sim import camera_for_mount
from sim.camera import CEILING_MOUNTS
from sim.scene import calibration_points, render_clean, degrade, PROFILES, DEFAULT_LIGHT, random_dart
import vision as V
def cal(camera, img):
    v = V.Vision(); v.ingest(img); r = v.calibrate(calibration_points(camera).tolist())
    return r['calibration']['board_marks_mm2'], 'does not look empty' in r['message']
for mount in list(CEILING_MOUNTS) + ['left']:
    camera = camera_for_mount(mount, 1280, 720)
    for prof in ('realistic', 'realistic+shadow'):
        deg = PROFILES['realistic']
        if prof.endswith('shadow'): deg = deg.with_options(shadow=DEFAULT_LIGHT)
        empty_marks, empty_warn, dart_warn, dart_marks = [], 0, 0, []
        for seed in range(6):
            rng = np.random.default_rng(seed)
            img = degrade(render_clean(camera, [], deg.shadow, deg.shadow_strength), deg, rng, brightness=deg.brightness * rng.uniform(0.85, 1.15))[0]
            m, w = cal(camera, img); empty_marks.append(m); empty_warn += w
            d = random_dart(rng)
            img = degrade(render_clean(camera, [d], deg.shadow, deg.shadow_strength), deg, rng)[0]
            m, w = cal(camera, img); dart_marks.append(m); dart_warn += w
        print(f'{mount:14} {prof:17} empty: warn {empty_warn}/6 max {max(empty_marks):.1f} mm2 | one dart: warn {dart_warn}/6 min {min(dart_marks):.1f} mm2', flush=True)
