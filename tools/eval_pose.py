#!/usr/bin/env python3
"""Measure foot-point recovery (vision_pose) on the synthetic mounts.

Reports, per mount, the exact-click result and the direction/distance error
distribution with Gaussian click noise. Synthetic only: not real-board evidence.

Example:
    python tools/eval_pose.py --seeds 50 --click-noise 2 --out qa-artifacts/M1-04-pose.json
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import vision_pose  # noqa: E402
from sim.camera import MOUNTS, camera_for_mount  # noqa: E402
from sim.scene import calibration_points  # noqa: E402
from vision import CENTER, SCALE, TARGETS  # noqa: E402

DISCLAIMER = 'Synthetic camera geometry only; not evidence of real-phone pose accuracy.'


def foot_errors(camera, points):
    H = cv2.getPerspectiveTransform(points.astype(np.float32), TARGETS)
    pose = vision_pose.estimate_pose(H, camera.width, camera.height, SCALE, CENTER)
    true_foot = camera.foot_point
    if pose['foot'] is None:
        return pose, None, None
    direction = vision_pose.angle_difference(vision_pose.direction_degrees(pose['foot']),
                                             vision_pose.direction_degrees(true_foot))
    distance = math.hypot(*pose['foot']) / math.hypot(*true_foot) - 1.0
    return pose, direction, distance


def evaluate(mount, seeds, click_noise):
    camera = camera_for_mount(mount)
    exact_points = calibration_points(camera).astype(np.float64)
    pose, direction, distance = foot_errors(camera, exact_points)
    directions, distances, sources = [], [], {}
    for seed in range(seeds):
        rng = np.random.default_rng([seed, list(MOUNTS).index(mount)])
        noisy = exact_points + rng.normal(0.0, click_noise, exact_points.shape)
        noisy_pose, noisy_direction, noisy_distance = foot_errors(camera, noisy)
        sources[noisy_pose['source']] = sources.get(noisy_pose['source'], 0) + 1
        directions.append(180.0 if noisy_direction is None else noisy_direction)
        if noisy_distance is not None:
            distances.append(abs(noisy_distance))
    return {
        'true_foot_mm': list(camera.foot_point),
        'true_f_px': round(camera.f, 2),
        'exact': {
            'source': pose['source'],
            'reason': pose['reason'],
            'f_px': pose['f'],
            'foot_mm': pose['foot'],
            'direction_error_deg': None if direction is None else round(direction, 4),
            'distance_error_ratio': None if distance is None else round(distance, 4),
        },
        'click_noise': {
            'sigma_px': click_noise,
            'seeds': seeds,
            'direction_error_deg_median': round(float(np.percentile(directions, 50)), 3),
            'direction_error_deg_p95': round(float(np.percentile(directions, 95)), 3),
            'distance_error_ratio_median': round(float(np.percentile(distances, 50)), 4) if distances else None,
            'sources': sources,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seeds', type=int, default=50)
    parser.add_argument('--click-noise', type=float, default=2.0)
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    report = {'tool': 'tools/eval_pose.py', 'disclaimer': DISCLAIMER,
              'mounts': {mount: evaluate(mount, args.seeds, args.click_noise) for mount in MOUNTS}}
    text = json.dumps(report, indent=1, allow_nan=False)
    if args.out:
        Path(args.out).write_text(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
