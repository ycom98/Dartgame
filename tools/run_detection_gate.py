#!/usr/bin/env python3
"""Run the detection gate matrix (pipelines x profiles x seeds x mounts) in parallel.

Each cell is one tools/eval_detection.py run. Pipelines:
  current          vision.py in this working tree (default rule and tip bias; M1-05c calibration refinement)
  m105b            the same vision.py with calibration refinement off: the M1-05b pipeline (four clicks only)
  m105-foot        vision.py from --baseline-commit (default 9af1ad3, M1-05), rule 'foot', its own tip bias
  m105-centre      the same file with the old 'centre' rule

The baseline file is read with `git show`, written to a temporary directory and
imported as a separate module, so it runs through the same harness and darts.

Profiles: 'ideal', 'realistic', and either with '+shadow' (hard shadow, default light).

IMPORTANT: synthetic results only; not evidence of real-board accuracy.

Example (M1-05b: tune seed 1, held-out seeds 2 and 3):
    python tools/run_detection_gate.py --pipelines current,m105-foot,m105-centre \\
        --profiles ideal,realistic,ideal+shadow,realistic+shadow --seeds 1,2,3 \\
        --empty-trials 100 --pair-trials 50 --out qa-artifacts/M1-05b-detection.json
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.camera import CEILING_MOUNTS, MOUNTS  # noqa: E402
from tools import eval_detection  # noqa: E402

PIPELINES = ('current', 'm105b', 'm105-foot', 'm105-centre')
GATED_MOUNTS = ('top', 'bottom', 'left', 'right', 'steep-topleft')
# Reported as a group of their own (M1-05d), not gated.
POOLED_GROUPS = {'gated_pooled': GATED_MOUNTS, 'ceiling_pooled': CEILING_MOUNTS}
BASELINE_MODULE = 'vision_baseline'
SUMMARY_KEYS = ('exact_accuracy', 'wrong_sector_rate', 'wrong_ring_rate', 'no_proposal_rate', 'exact_given_proposal',
                'tip_error_mm', 'tip_signed_error_toward_foot_mm', 'near_wire', 'not_near_wire',
                'no_proposal_reasons', 'false_proposals', 'two_darts', 'calibration_invalidations',
                'time_per_frame_ms', 'calibration', 'speckle_false_proposals')


def load_baseline(path):
    spec = importlib.util.spec_from_file_location(BASELINE_MODULE, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cell(cell):
    (pipeline, profile, seed, mount, darts, empty_trials, pair_trials, speckle_trials, baseline_path,
     current_tip_bias) = cell
    shadow = profile.endswith('+shadow')
    base_profile = profile.replace('+shadow', '')
    factory, rule, tip_bias, refine = None, None, current_tip_bias, None
    if pipeline == 'm105b':
        refine = False
    elif pipeline != 'current':
        baseline = load_baseline(baseline_path)
        factory = baseline.Vision
        rule = 'foot' if pipeline == 'm105-foot' else 'centre'
        tip_bias = baseline.TIP_BIAS_MM
    report = eval_detection.run([mount], darts, seed, base_profile, shadow, rule=rule, tip_bias=tip_bias,
                                vision_factory=factory, empty_trials=empty_trials, pair_trials=pair_trials,
                                refine=refine, speckle_trials=speckle_trials)
    result = report['mounts'][mount]
    summary = {key: result[key] for key in SUMMARY_KEYS if key in result}
    summary['tip_bias_mm'] = tip_bias if tip_bias is not None else report['settings']['tip_bias_mm']
    summary['rule'] = rule or report['settings']['rule']
    return pipeline, profile, seed, mount, summary, result['trials'], result['wall_seconds']


def pooled(rows, key):
    """Pooled rate over gated mounts (each mount has the same number of darts)."""
    values = [row[key] for row in rows if row.get(key) is not None]
    return round(sum(values) / len(values), 4) if values else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pipelines', default='current')
    parser.add_argument('--profiles', default='ideal,realistic')
    parser.add_argument('--seeds', default='1')
    parser.add_argument('--mounts', default=','.join(MOUNTS))
    parser.add_argument('--darts', type=int, default=200)
    parser.add_argument('--empty-trials', type=int, default=0,
                        help='false-proposal trials per cell (current and m105b only)')
    parser.add_argument('--pair-trials', type=int, default=0, help='two-dart trials per cell (current and m105b only)')
    parser.add_argument('--speckle-trials', type=int, default=0,
                        help='speckle (debris, no dart) false-proposal trials per cell (current and m105b only)')
    parser.add_argument('--tip-bias', type=float, help="override the 'current' pipeline's tip bias (mm)")
    parser.add_argument('--baseline-commit', default='9af1ad3')
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 1)
    parser.add_argument('--keep-trials', default='current', help="pipelines whose per-trial records are kept")
    parser.add_argument('--out')
    args = parser.parse_args(argv)

    pipelines = [p for p in args.pipelines.split(',') if p]
    unknown = [p for p in pipelines if p not in PIPELINES]
    if unknown:
        parser.error('unknown pipeline(s): ' + ', '.join(unknown))
    profiles = [p for p in args.profiles.split(',') if p]
    seeds = [int(s) for s in args.seeds.split(',') if s]
    mounts = [m for m in args.mounts.split(',') if m]
    keep_trials = set(args.keep_trials.split(','))

    with tempfile.TemporaryDirectory() as directory:
        baseline_path = None
        if any(p.startswith('m105-') for p in pipelines):
            baseline_path = os.path.join(directory, BASELINE_MODULE + '.py')
            source = subprocess.run(['git', 'show', args.baseline_commit + ':vision.py'], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout
            Path(baseline_path).write_text(source)
        cells = []
        for pipeline in pipelines:
            extra = ((args.empty_trials, args.pair_trials, args.speckle_trials) if pipeline in ('current', 'm105b')
                     else (0, 0, 0))
            for profile in profiles:
                for seed in seeds:
                    for mount in mounts:
                        cells.append((pipeline, profile, seed, mount, args.darts, *extra, baseline_path,
                                      args.tip_bias))
        started = time.perf_counter()
        results = {}
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for pipeline, profile, seed, mount, summary, trials, seconds in pool.map(run_cell, cells):
                if pipeline in keep_trials:
                    summary['trials'] = trials
                results.setdefault(pipeline, {}).setdefault(profile, {}).setdefault(str(seed), {})[mount] = summary
                print('{:12} {:18} seed {} {}'.format(pipeline, profile, seed,
                                                     eval_detection.summary_line({'mount': mount, **summary})),
                      flush=True)

    for pipeline in results.values():
        for profile in pipeline.values():
            for seed_results in profile.values():
                for group, group_mounts in POOLED_GROUPS.items():
                    rows = [seed_results[m] for m in group_mounts if m in seed_results]
                    if not rows:
                        continue
                    seed_results[group] = {
                        'mounts': [m for m in group_mounts if m in seed_results],
                        'exact_accuracy': pooled(rows, 'exact_accuracy'),
                        'no_proposal_rate': pooled(rows, 'no_proposal_rate'),
                        'near_wire_exact': pooled([r['near_wire'] for r in rows], 'exact_accuracy'),
                        'not_near_wire_exact': pooled([r['not_near_wire'] for r in rows], 'exact_accuracy'),
                    }
    report = {
        'tool': 'tools/run_detection_gate.py',
        'disclaimer': eval_detection.DISCLAIMER,
        'git_commit': eval_detection.git_commit(),
        'baseline_commit': args.baseline_commit if baseline_path else None,
        'settings': {'pipelines': pipelines, 'profiles': profiles, 'seeds': seeds, 'mounts': mounts,
                     'darts_per_cell': args.darts, 'empty_trials_per_cell': args.empty_trials,
                     'pair_trials_per_cell': args.pair_trials, 'speckle_trials_per_cell': args.speckle_trials,
                     'gated_mounts': list(GATED_MOUNTS),
                     'ceiling_mounts': list(CEILING_MOUNTS),
                     'current_tip_bias_override_mm': args.tip_bias,
                     'note': 'gated_pooled (ceiling_pooled) averages the per-mount rates over the gated (ceiling) '
                             'mounts present; '
                             'near-wire = tip within 1.5 mm of a wire (core.near_wire).'},
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
