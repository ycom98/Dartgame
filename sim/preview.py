"""Render a synthetic frame to a PNG for eyeballing.

Example:
    python -m sim.preview --mount left --darts 3 --out qa-artifacts/M1-02-left.png

Synthetic images are a measurement aid, not evidence of real-board accuracy.
"""
import argparse
import json
import sys

import cv2
import numpy as np

from sim.camera import DEFAULT_HEIGHT, DEFAULT_HFOV, DEFAULT_WIDTH, MOUNTS, camera_for_mount
from sim.scene import DEFAULT_LIGHT, PROFILES, random_dart, render_scene


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mount', default='left', choices=sorted(MOUNTS))
    parser.add_argument('--darts', type=int, default=3)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--profile', default='ideal', choices=sorted(PROFILES))
    parser.add_argument('--shadow', action='store_true', help='add a hard shadow from the default light')
    parser.add_argument('--width', type=int, default=DEFAULT_WIDTH)
    parser.add_argument('--height', type=int, default=DEFAULT_HEIGHT)
    parser.add_argument('--hfov', type=float, default=DEFAULT_HFOV)
    parser.add_argument('--k1', type=float, default=0.0, help='radial distortion coefficient')
    parser.add_argument('--annotate', action='store_true', help='mark calibration points and true tips')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.darts < 0:
        parser.error('--darts must be >= 0')

    rng = np.random.default_rng(args.seed)
    camera = camera_for_mount(args.mount, args.width, args.height, args.hfov, k1=args.k1)
    darts = [random_dart(rng) for _ in range(args.darts)]
    degradation = PROFILES[args.profile]
    if args.shadow:
        degradation = degradation.with_options(shadow=DEFAULT_LIGHT)
    result = render_scene(camera, darts, degradation, seed=args.seed)
    frame = result.frame.copy()
    if args.annotate:
        for point in result.calibration_points:
            cv2.circle(frame, (int(round(point[0])), int(round(point[1]))), 8, (0, 255, 255), 2, cv2.LINE_AA)
        for label in result.labels:
            tip = camera.project_plane([[label['x'], label['y']]])[0]
            cv2.drawMarker(frame, (int(round(tip[0])), int(round(tip[1]))), (255, 0, 255),
                           cv2.MARKER_CROSS, 14, 2)
    if not cv2.imwrite(args.out, frame):
        print('Could not write ' + args.out, file=sys.stderr)
        return 1
    summary = {
        'out': args.out,
        'mount': args.mount,
        'seed': args.seed,
        'profile': args.profile,
        'calibration_points': result.calibration_points.round(2).tolist(),
        'labels': result.labels,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
