#!/usr/bin/env python3
"""DIAGNOSTIC ONLY: how good is the tip rule when segmentation is not the bottleneck?

At M1-05, vision.py segmented a dart with a grayscale difference (> 35) and
required exactly one contour. On synthetic scenes that split most darts into
fragments ("Ambiguous change"), which hid the effect of the tip rule. M1-05b
replaced that segmentation (vision_segment.py); this tool is kept for comparison.

This tool runs the same harness with a Vision subclass that, after the normal
ingest, re-segments stable frames with a per-channel colour difference and
treats ALL changed pixels as one dart. That is only valid because every
harness trial contains exactly one new dart, so it is an optimistic upper
bound for the tip rule, not a proposal for production segmentation.

Synthetic only; not evidence of real-board accuracy.

Example:
    python tools/diag_segmentation.py --profile ideal --darts 200 --seed 1 --rule foot \\
        --out qa-artifacts/M1-05-diagnostic-union-segmentation.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core import near_wire, score_point  # noqa: E402
from sim.camera import MOUNTS  # noqa: E402
from sim.scene import PROFILES  # noqa: E402
from tools import eval_detection  # noqa: E402
from vision import CENTER, SCALE, SIZE, Vision  # noqa: E402

DIFF_THRESHOLD = 35
MIN_PIXELS = 35


class UnionSegmentationVision(Vision):
    """Vision with colour-difference, all-fragments-as-one-dart segmentation (diagnostic)."""

    def ingest(self, data):
        super().ingest(data)
        if not self.aligned or self.stable < 3 or self.base is None:
            return
        diff = cv2.absdiff(self.last_warp, self.base).max(axis=2)
        mask = (diff > DIFF_THRESHOLD).astype(np.uint8) * 255
        yy, xx = np.ogrid[:SIZE, :SIZE]
        mask[(xx - CENTER) ** 2 + (yy - CENTER) ** 2 > (172 * SCALE) ** 2] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        points = np.argwhere(mask > 0)[:, ::-1].astype(np.float32)
        if len(points) < MIN_PIXELS:
            self.proposal = None
            self.message = 'Ready'
            return
        tip, confidence, rule = self.locate_tip(points)
        if tip is None:
            self.proposal = None
            self.message = 'Change is not dart-shaped; use manual scoring'
            return
        x, y = (tip - CENTER) / SCALE
        self.proposal = {**score_point(float(x), float(y)), 'x': float(x), 'y': float(y),
                         'review_required': True, 'near_wire': near_wire(float(x), float(y)),
                         'confidence': confidence, 'rule': rule, 'note': 'diagnostic union segmentation'}
        self.message = 'Possible dart found (diagnostic segmentation)'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mounts', default=','.join(MOUNTS))
    parser.add_argument('--darts', type=int, default=200)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--profile', default='ideal', choices=sorted(PROFILES))
    parser.add_argument('--shadow', action='store_true')
    parser.add_argument('--rule', default='foot', choices=('foot', 'centre'))
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    mounts = [m for m in args.mounts.split(',') if m]
    report = eval_detection.run(
        mounts, args.darts, args.seed, args.profile, args.shadow, rule=args.rule,
        vision_factory=UnionSegmentationVision,
        progress=lambda result: print(eval_detection.summary_line(result), flush=True))
    report['tool'] = 'tools/diag_segmentation.py (DIAGNOSTIC upper bound; not the shipped pipeline)'
    report['settings']['segmentation'] = ('per-channel colour diff > 35, 3x3 open, all changed pixels in r<=172 mm '
                                          'treated as one dart (valid only because each trial has one dart)')
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
