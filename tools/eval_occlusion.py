#!/usr/bin/env python3
"""Multi-dart turns, throw by throw (M1-05d): how often later darts are visible and detected.

The detector proposes one new dart per stable frame against a base image. As M1-08
will do in play, the base is reset after each dart, so each dart is detected on a
board that already holds the earlier darts of the turn (and those darts are in the
base image). A turn:
  1. Re-establish the empty-board base.
  2. For dart k = 1, 2, 3: render the board with darts 1..k, ingest frames, score the
     proposal against dart k, then make the current frame the base.

Scenarios (three darts per turn; dart orientation and colours as sim.random_dart):
  t20-group       all three aimed at the T20 centre, scatter sigma 8 mm
  t20-neighbours  T20, then T5 or T1, then the other one (scatter sigma 5 mm)
  stacked-below   dart 2 lands 30-80 mm directly below dart 1, dart 3 30-80 mm below
                  dart 2 (x jitter sigma 3 mm); turns that leave the board are redrawn

Visibility is geometric, from the renderer: a dart's tip is hidden by earlier darts
when their outline covers the tip's image point, and hidden by itself when its own
barrel, shaft or flight does. The detector never sees these labels.

IMPORTANT: synthetic results only; not evidence of real-board accuracy.

Example:
    python tools/eval_occlusion.py --mounts ceiling-1.5ft --profiles ideal,realistic --seeds 2,3 \\
        --turns 100 --out qa-artifacts/M1-05d-occlusion.json
"""
import argparse
import collections
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from sim.camera import CEILING_MOUNTS, MOUNTS, camera_for_mount  # noqa: E402
from sim.scene import DEFAULT_LIGHT, PROFILES, dart_silhouette, random_dart, render_clean  # noqa: E402
from tools import eval_detection  # noqa: E402

SCENARIOS = ('t20-group', 't20-neighbours', 'stacked-below')
TREBLE_CENTRE_MM = 103.0
SCENARIO_STREAM = {name: index for index, name in enumerate(SCENARIOS)}
COVERED = 128  # silhouette value (0-255) at which a pixel counts as covered


def treble_centre(degrees):
    angle = math.radians(degrees)
    return TREBLE_CENTRE_MM * math.sin(angle), -TREBLE_CENTRE_MM * math.cos(angle)


def aimed(rng, target, sigma):
    """A random dart (orientation, colours) whose tip lands around target (mm)."""
    x, y = target
    return replace(random_dart(rng), x=float(x + rng.normal(0.0, sigma)), y=float(y + rng.normal(0.0, sigma)))


def turn_darts(scenario, rng):
    """Three darts for one turn of the scenario."""
    if scenario == 't20-group':
        return [aimed(rng, treble_centre(0.0), 8.0) for _ in range(3)]
    if scenario == 't20-neighbours':
        second, third = (18.0, -18.0) if rng.uniform() < 0.5 else (-18.0, 18.0)
        return [aimed(rng, treble_centre(angle), 5.0) for angle in (0.0, second, third)]
    if scenario == 'stacked-below':
        while True:
            first = random_dart(rng, max_radius=110.0)
            darts = [first]
            for _ in range(2):
                previous = darts[-1]
                darts.append(replace(random_dart(rng), x=float(previous.x + rng.normal(0.0, 3.0)),
                                     y=float(previous.y + rng.uniform(30.0, 80.0))))
            if all(math.hypot(d.x, d.y) <= 168.0 for d in darts):
                return darts
    raise ValueError('unknown scenario %r' % scenario)


def covered(mask, pixel):
    col, row = int(round(pixel[0])), int(round(pixel[1]))
    if not (0 <= row < mask.shape[0] and 0 <= col < mask.shape[1]):
        return False
    return bool(mask[row, col] >= COVERED)


def visibility(camera, darts, k):
    """{'hidden_by_earlier', 'hidden_by_self'} for dart k's tip (geometric, harness only)."""
    tip = camera.project_plane([[darts[k].x, darts[k].y]])[0]
    earlier = dart_silhouette(camera, darts[:k]) if k else None
    own_body = dart_silhouette(camera, [darts[k]], include_point=False)
    return {'hidden_by_earlier': bool(earlier is not None and covered(earlier, tip)),
            'hidden_by_self': covered(own_body, tip)}


def run_cell(cell):
    """One (mount, profile, seed): every scenario, `turns` turns each. Returns (key, summary, records)."""
    mount, profile, seed, turns, refine, frames_per_trial = cell
    shadow = profile.endswith('+shadow')
    degradation = PROFILES[profile.replace('+shadow', '')]
    if shadow:
        degradation = degradation.with_options(shadow=DEFAULT_LIGHT)
    key = eval_detection.mount_stream_key(mount)
    noise_rng = np.random.default_rng([seed, key, 101])
    click_rng = np.random.default_rng([seed, key, 102])
    exposure_rng = np.random.default_rng([seed, key, 103])

    camera = camera_for_mount(mount)
    vision = eval_detection.make_vision(refine=refine)
    feeder = eval_detection.FrameFeeder(vision, degradation, noise_rng)
    empty = render_clean(camera, [])
    calibrations = []
    eval_detection.calibrate(vision, camera, degradation, feeder, empty, degradation.brightness, click_rng, 3,
                             calibrations)
    session = eval_detection.TrialSession(vision, camera, degradation, feeder, empty, click_rng, 3,
                                          frames_per_trial, calibrations)
    records = []
    for scenario in SCENARIOS:
        dart_rng = np.random.default_rng([seed, key, 200 + SCENARIO_STREAM[scenario]])
        for turn in range(turns):
            darts = turn_darts(scenario, dart_rng)
            brightness = degradation.brightness
            if degradation.brightness_jitter:
                jitter = degradation.brightness_jitter
                brightness *= float(exposure_rng.uniform(1 - jitter, 1 + jitter))
            session.rebase(brightness)
            for k in range(len(darts)):
                truth = darts[k].label()
                record = {'scenario': scenario, 'turn': turn, 'dart': k + 1, 'truth': truth['label'],
                          'x': round(truth['x'], 2), 'y': round(truth['y'], 2), **visibility(camera, darts, k)}
                if not vision.aligned:
                    record['outcome'] = 'no_proposal'
                    record['message'] = 'vision not aligned after an earlier dart'
                    records.append(record)
                    continue
                scene = render_clean(camera, darts[:k + 1], degradation.shadow, degradation.shadow_strength)
                feeder.ingest(scene, brightness, frames_per_trial)
                proposal = vision.proposal
                record['outcome'] = eval_detection.classify(truth, proposal)
                if proposal is None:
                    record['message'] = vision.message
                else:
                    record.update({'proposal': proposal['label'], 'tip_error_mm': round(float(
                        math.hypot(proposal['x'] - truth['x'], proposal['y'] - truth['y'])), 2)})
                records.append(record)
                if vision.aligned:
                    vision.reset_base()  # throw by throw: this dart joins the base
    summary = summarise(records)
    summary['calibration'] = eval_detection.calibration_summary(calibrations)
    return (mount, profile, seed), summary, records


def rate(count, total):
    return round(count / total, 4) if total else None


def summarise(records):
    """Per scenario and dart number: visibility and detection rates."""
    groups = collections.defaultdict(list)
    for record in records:
        groups[(record['scenario'], record['dart'])].append(record)
        groups[('all', record['dart'])].append(record)
    summary = {}
    for (scenario, dart), rows in sorted(groups.items()):
        visible = [r for r in rows if not r['hidden_by_earlier'] and not r['hidden_by_self']]
        hidden = [r for r in rows if r['hidden_by_earlier'] or r['hidden_by_self']]
        outcomes = collections.Counter(r['outcome'] for r in rows)
        summary.setdefault(scenario, {})['dart%d' % dart] = {
            'n': len(rows),
            'tip_visible_rate': rate(len(visible), len(rows)),
            'hidden_by_earlier_rate': rate(sum(r['hidden_by_earlier'] for r in rows), len(rows)),
            'hidden_by_self_rate': rate(sum(r['hidden_by_self'] for r in rows), len(rows)),
            'exact_rate': rate(outcomes['exact'], len(rows)),
            'no_proposal_rate': rate(outcomes['no_proposal'], len(rows)),
            'wrong_rate': rate(outcomes['wrong_sector'] + outcomes['wrong_ring'], len(rows)),
            'exact_when_visible': rate(sum(r['outcome'] == 'exact' for r in visible), len(visible)),
            'exact_when_hidden': rate(sum(r['outcome'] == 'exact' for r in hidden), len(hidden)),
            'wrong_when_hidden': rate(sum(r['outcome'] in ('wrong_sector', 'wrong_ring') for r in hidden),
                                      len(hidden)),
            'messages': dict(collections.Counter(r.get('message') for r in rows if r['outcome'] == 'no_proposal')),
        }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mounts', default=','.join(CEILING_MOUNTS))
    parser.add_argument('--profiles', default='ideal,realistic')
    parser.add_argument('--seeds', default='2,3')
    parser.add_argument('--turns', type=int, default=100, help='turns per scenario per cell')
    parser.add_argument('--frames', type=int, default=4)
    parser.add_argument('--no-refine', action='store_true', help='four-click calibration only (M1-05b)')
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 1)
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    mounts = [m for m in args.mounts.split(',') if m]
    unknown = [m for m in mounts if m not in MOUNTS]
    if unknown:
        parser.error('unknown mount(s): ' + ', '.join(unknown))
    profiles = [p for p in args.profiles.split(',') if p]
    seeds = [int(s) for s in args.seeds.split(',') if s]
    refine = False if args.no_refine else None
    cells = [(m, p, s, args.turns, refine, args.frames) for p in profiles for s in seeds for m in mounts]

    started = time.perf_counter()
    results = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for (mount, profile, seed), summary, records in pool.map(run_cell, cells):
            results.setdefault(profile, {}).setdefault(str(seed), {})[mount] = {'summary': summary,
                                                                                 'trials': records}
            line = '  '.join('{} d2 vis {} exact {} | d3 vis {} exact {}'.format(
                scenario, summary[scenario]['dart2']['tip_visible_rate'], summary[scenario]['dart2']['exact_rate'],
                summary[scenario]['dart3']['tip_visible_rate'], summary[scenario]['dart3']['exact_rate'])
                for scenario in SCENARIOS)
            print('{:14} {:17} seed {}  {}'.format(mount, profile, seed, line), flush=True)
    report = {
        'tool': 'tools/eval_occlusion.py',
        'disclaimer': eval_detection.DISCLAIMER,
        'git_commit': eval_detection.git_commit(),
        'settings': {'mounts': mounts, 'profiles': profiles, 'seeds': seeds, 'turns_per_scenario': args.turns,
                     'scenarios': list(SCENARIOS), 'frames_per_dart': args.frames,
                     'calibration_refinement': refine is None,
                     'base': 'reset after every dart (throw by throw); earlier darts are in the base image',
                     'visibility': 'geometric: tip image point covered (>= 50%) by an earlier dart outline '
                                   '(hidden_by_earlier) or by the dart\'s own barrel/shaft/flight (hidden_by_self)'},
        'total_wall_seconds': round(time.perf_counter() - started, 1),
        'results': results,
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
