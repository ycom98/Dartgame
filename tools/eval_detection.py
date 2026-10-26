#!/usr/bin/env python3
"""End-to-end detection harness: synthetic frames through the real vision.Vision.

For each mount:
  1. Render the empty board, ingest it, calibrate Vision with the projected
     calibration points (plus optional click noise) and verify.
  2. Ingest empty frames to establish the base.
  3. For each trial: ingest empty frames at the trial's exposure and reset the
     base, render one dart, ingest N frames (so the stability gate passes),
     read vision.proposal and compare it with the truth.

Profiles come from sim.PROFILES ('ideal', 'realistic').

IMPORTANT: synthetic results measure the pipeline against a rendered model of
a board and darts. They are not evidence of real-board accuracy.

Example:
    python tools/eval_detection.py --profile ideal --darts 200 --seed 1 \\
        --out qa-artifacts/M1-03-detection-baseline.json
"""
import argparse
import collections
import json
import platform
import statistics
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import vision as vision_module  # noqa: E402
from sim.camera import MOUNTS, camera_for_mount  # noqa: E402
from sim.scene import (  # noqa: E402
    DEFAULT_LIGHT,
    PROFILES,
    calibration_points,
    photometric,
    random_dart,
    render_clean,
    sensor,
)

DISCLAIMER = ('Synthetic rendered scenes only (sim/). These numbers measure the vision pipeline against a '
              'model of the board and darts; they are not evidence of real-board accuracy.')
RING_NAMES = {'Bull': 'bull', 'Outer bull': 'outer_bull'}


def ring_of(label):
    if label in RING_NAMES:
        return RING_NAMES[label]
    if label == 'Miss':
        return 'miss'
    return {'S': 'single', 'D': 'double', 'T': 'treble'}[label[0]]


def classify(truth, proposal):
    """'exact', 'wrong_ring', 'wrong_sector' or 'no_proposal'."""
    if proposal is None:
        return 'no_proposal'
    if proposal['label'] == truth['label']:
        return 'exact'
    if proposal['value'] == truth['value']:
        return 'wrong_ring'
    return 'wrong_sector'


def percentile(values, q):
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def rounded(value, digits=3):
    return None if value is None else round(float(value), digits)


def encode_lossless(frame):
    ok, data = cv2.imencode('.bmp', frame)
    if not ok:
        raise RuntimeError('BMP encoding failed')
    return data.tobytes()


class FrameFeeder:
    """Turns clean renders into encoded frames for Vision.ingest, timing each ingest."""

    def __init__(self, vision, degradation, rng):
        self.vision = vision
        self.degradation = degradation
        self.rng = rng
        self.ingest_seconds = []

    def frames(self, clean, brightness, count):
        prepared = photometric(clean, self.degradation, brightness)
        for _ in range(count):
            frame, encoded = sensor(prepared, self.degradation, self.rng)
            yield encoded if encoded is not None else encode_lossless(frame)

    def ingest(self, clean, brightness, count, timed=True):
        for data in self.frames(clean, brightness, count):
            started = time.perf_counter()
            self.vision.ingest(data)
            if timed:
                self.ingest_seconds.append(time.perf_counter() - started)


def make_vision(rule=None, tip_bias=None, factory=None):
    vision = (factory or vision_module.Vision)()
    if rule is not None:
        if not hasattr(vision, 'rule'):
            raise SystemExit('This vision.py has no selectable tip rule; omit --rule')
        vision.rule = rule
    if tip_bias is not None:
        vision.tip_bias_mm = tip_bias
    return vision


def calibrate(vision, camera, degradation, feeder, empty, brightness, click_rng, empty_frames):
    feeder.ingest(empty, brightness, 1, timed=False)
    points = calibration_points(camera).astype(np.float64)
    if degradation.click_noise:
        points = points + click_rng.normal(0.0, degradation.click_noise, points.shape)
    vision.calibrate(points.tolist())
    vision.verify(vision.version)
    feeder.ingest(empty, brightness, empty_frames, timed=False)
    vision.reset_base()
    return points


def mount_stream_key(mount):
    """Stable integer for a mount name (CRC-32), used to seed its random streams."""
    return zlib.crc32(mount.encode('utf-8'))


def camera_settings(camera):
    return {'width': camera.width, 'height': camera.height, 'hfov_deg': camera.hfov,
            'look_at': [float(v) for v in camera.look_at], 'k1': camera.k1}


def evaluate_mount(mount, darts, seed, degradation, frames_per_trial=4, empty_frames=3, rule=None,
                   tip_bias=None, vision_factory=None):
    # Random streams are keyed by the mount's name, so adding or reordering mounts leaves the others' darts unchanged.
    mount_key = mount_stream_key(mount)
    dart_rng = np.random.default_rng([seed, mount_key, 0])
    noise_rng = np.random.default_rng([seed, mount_key, 1])
    click_rng = np.random.default_rng([seed, mount_key, 2])
    exposure_rng = np.random.default_rng([seed, mount_key, 3])

    camera = camera_for_mount(mount)
    vision = make_vision(rule, tip_bias, vision_factory)
    feeder = FrameFeeder(vision, degradation, noise_rng)
    empty = render_clean(camera, [])
    session_brightness = degradation.brightness
    calibrate(vision, camera, degradation, feeder, empty, session_brightness, click_rng, empty_frames)
    foot = np.asarray(camera.foot_point)

    outcomes = collections.Counter()
    reasons = collections.Counter()
    by_ring = collections.defaultdict(collections.Counter)
    by_wire = {True: collections.Counter(), False: collections.Counter()}
    tip_errors = []
    signed_errors = []
    invalidations = 0
    trials = []

    for index in range(darts):
        dart = random_dart(dart_rng)
        truth = dart.label()
        brightness = session_brightness
        if degradation.brightness_jitter:
            jitter = degradation.brightness_jitter
            brightness *= float(exposure_rng.uniform(1 - jitter, 1 + jitter))

        if not vision.aligned:
            invalidations += 1
            calibrate(vision, camera, degradation, feeder, empty, brightness, click_rng, empty_frames)
        # Re-establish the empty base at this trial's exposure (exposure is locked within a trial).
        feeder.ingest(empty, brightness, 2, timed=False)
        vision.reset_base()

        scene = render_clean(camera, [dart], degradation.shadow, degradation.shadow_strength)
        feeder.ingest(scene, brightness, frames_per_trial)
        proposal = vision.proposal
        outcome = classify(truth, proposal)
        outcomes[outcome] += 1
        by_ring[ring_of(truth['label'])][outcome] += 1
        by_wire[truth['near_wire']][outcome] += 1
        record = {'i': index, 'truth': truth['label'], 'x': round(truth['x'], 2), 'y': round(truth['y'], 2),
                  'near_wire': truth['near_wire'], 'outcome': outcome}
        if proposal is None:
            reasons[vision.message] += 1
        else:
            detected = np.array([proposal['x'], proposal['y']])
            true_tip = np.array([truth['x'], truth['y']])
            error = float(np.linalg.norm(detected - true_tip))
            tip_errors.append(error)
            toward_foot = foot - detected
            norm = float(np.linalg.norm(toward_foot))
            if norm > 1e-9:
                signed_errors.append(float((true_tip - detected) @ (toward_foot / norm)))
            record.update({'proposal': proposal['label'], 'px': round(proposal['x'], 2),
                           'py': round(proposal['y'], 2), 'tip_error_mm': round(error, 2)})
            for key in ('confidence', 'rule'):
                if key in proposal:
                    record[key] = proposal[key]
        trials.append(record)

    def accuracy(counter):
        total = sum(counter.values())
        return {'n': total, 'exact_accuracy': rounded(counter['exact'] / total, 4) if total else None}

    frame_ms = [s * 1000 for s in feeder.ingest_seconds]
    result = {
        'mount': mount,
        'camera_position_mm': list(MOUNTS[mount]),
        'camera': camera_settings(camera),
        'foot_point_mm': [float(v) for v in foot],
        'darts': darts,
        'exact_accuracy': rounded(outcomes['exact'] / darts, 4),
        'wrong_sector_rate': rounded(outcomes['wrong_sector'] / darts, 4),
        'wrong_ring_rate': rounded(outcomes['wrong_ring'] / darts, 4),
        'no_proposal_rate': rounded(outcomes['no_proposal'] / darts, 4),
        'exact_given_proposal': (rounded(outcomes['exact'] / (darts - outcomes['no_proposal']), 4)
                                 if darts > outcomes['no_proposal'] else None),
        'counts': dict(outcomes),
        'tip_error_mm': {
            'median': rounded(percentile(tip_errors, 50)),
            'p95': rounded(percentile(tip_errors, 95)),
            'mean': rounded(statistics.fmean(tip_errors)) if tip_errors else None,
            'n': len(tip_errors),
        },
        'tip_signed_error_toward_foot_mm': {
            'median': rounded(percentile(signed_errors, 50)),
            'note': 'Projection of (true tip - detected tip) onto the unit vector from the detected tip '
                    'toward the true camera foot point. Positive = the true tip lies further toward the foot.',
        },
        'near_wire': accuracy(by_wire[True]),
        'not_near_wire': accuracy(by_wire[False]),
        'by_ring': {ring: accuracy(counter) for ring, counter in sorted(by_ring.items())},
        'no_proposal_reasons': dict(reasons),
        'calibration_invalidations': invalidations,
        'time_per_frame_ms': {
            'mean': rounded(statistics.fmean(frame_ms)) if frame_ms else None,
            'p95': rounded(percentile(frame_ms, 95)),
            'frames': len(frame_ms),
            'measures': 'wall-clock Vision.ingest() per frame (decode + warp + detection)',
        },
        'trials': trials,
    }
    return result


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(mounts, darts, seed, profile, shadow=False, frames_per_trial=4, rule=None, progress=None,
        tip_bias=None, vision_factory=None):
    degradation = PROFILES[profile]
    if shadow:
        degradation = degradation.with_options(shadow=DEFAULT_LIGHT)
    started = time.perf_counter()
    results = {}
    for mount in mounts:
        mount_started = time.perf_counter()
        results[mount] = evaluate_mount(mount, darts, seed, degradation, frames_per_trial, rule=rule,
                                        tip_bias=tip_bias, vision_factory=vision_factory)
        results[mount]['wall_seconds'] = round(time.perf_counter() - mount_started, 2)
        if progress:
            progress(results[mount])
    report = {
        'tool': 'tools/eval_detection.py',
        'disclaimer': DISCLAIMER,
        'git_commit': git_commit(),
        'settings': {
            'profile': profile,
            'degradation': {k: v for k, v in vars(degradation).items()},
            'shadow': shadow,
            'darts_per_mount': darts,
            'seed': seed,
            'frames_per_trial': frames_per_trial,
            'rule': rule or getattr(vision_module, 'DEFAULT_RULE', 'centre (only rule in this vision.py)'),
            'tip_bias_mm': tip_bias if tip_bias is not None else getattr(vision_module, 'TIP_BIAS_MM', None),
            'camera': camera_settings(camera_for_mount(mounts[0])) if mounts else None,
            'random_streams': 'numpy default_rng([seed, crc32(mount name), stream])',
            'dart_tips': 'uniform by area within r <= 170 mm (all darts stay in the board)',
            'exposure': 'brightness drawn once per trial (base and dart frames share it); '
                        'noise is independent per frame',
        },
        'environment': {
            'python': platform.python_version(),
            'numpy': np.__version__,
            'opencv': cv2.__version__,
            'machine': platform.machine(),
        },
        'total_wall_seconds': round(time.perf_counter() - started, 2),
        'mounts': results,
    }
    return report


def summary_line(result):
    return ('{mount:>14}  exact {exact:6.1%}  wrong-sector {ws:5.1%}  wrong-ring {wr:5.1%}  none {np:5.1%}  '
            'exact|proposed {given}  tip med {med} p95 {p95} mm  wire {wire}  {ms} ms/frame').format(
        mount=result['mount'], exact=result['exact_accuracy'], ws=result['wrong_sector_rate'],
        given=result['exact_given_proposal'],
        wr=result['wrong_ring_rate'], np=result['no_proposal_rate'],
        med=result['tip_error_mm']['median'], p95=result['tip_error_mm']['p95'],
        wire=result['near_wire']['exact_accuracy'], ms=result['time_per_frame_ms']['mean'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mounts', default=','.join(MOUNTS),
                        help='comma-separated mounts (default: all): ' + ', '.join(MOUNTS))
    parser.add_argument('--darts', type=int, default=200, help='single-dart trials per mount')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--profile', default='ideal', choices=sorted(PROFILES))
    parser.add_argument('--shadow', action='store_true', help='render hard dart shadows (default light)')
    parser.add_argument('--frames', type=int, default=4, help='frames ingested per dart (>= 4)')
    parser.add_argument('--rule', choices=getattr(vision_module, 'TIP_RULES', None),
                        help='tip rule (default: vision.DEFAULT_RULE)')
    parser.add_argument('--tip-bias', type=float, help='override vision.TIP_BIAS_MM (mm)')
    parser.add_argument('--recording', metavar='DIR', help='replay recorded real footage (M1-14)')
    parser.add_argument('--out', help='write the JSON report here')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    if args.recording:
        print('--recording is not implemented yet (planned for M1-14).', file=sys.stderr)
        return 2
    mounts = [m.strip() for m in args.mounts.split(',') if m.strip()]
    unknown = [m for m in mounts if m not in MOUNTS]
    if unknown:
        parser.error('unknown mount(s): ' + ', '.join(unknown))
    if args.darts < 1:
        parser.error('--darts must be >= 1')
    if args.frames < 4:
        parser.error('--frames must be >= 4 so the stability gate can pass')

    progress = None if args.quiet else (lambda result: print(summary_line(result), flush=True))
    report = run(mounts, args.darts, args.seed, args.profile, args.shadow, args.frames, rule=args.rule,
                 progress=progress, tip_bias=args.tip_bias)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, allow_nan=False) + '\n')
    if not args.quiet:
        print('total {:.1f} s'.format(report['total_wall_seconds']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
