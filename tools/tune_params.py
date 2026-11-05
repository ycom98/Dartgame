#!/usr/bin/env python3
"""Tune the camera thresholds on recorded sessions (M4-03).

Replays every recording (frames and camera actions, as tools/replay_recording.py does) once per setting of the
thresholds in vision_tuning.TUNABLE, and scores each setting against the labels (labels.jsonl, the host's final
values). Each live commit is replayed as a commit of the replay's own oldest pending dart, so a setting that
finds different darts is still scored dart by dart.

Settings: the current values, then each parameter moved to each of its grid values with the others at their
current values (one at a time; --full tries every combination of the chosen --params).

Scored darts: every camera-scored dart except misses and darts tagged 'stacked' in labels.jsonl (a stacked dart
can hide its tip from any single camera; the trial report shows them separately).

Darts are split by throw into a tuning part and a hold-out part (--holdout, default 30%). The candidate is the
setting with the highest exact-score share on the tuning darts whose false proposals (camera darts never
committed) are no higher than the current values'. It is recommended only if it is also better on the hold-out
darts; otherwise the advice is to keep the current values. The flag
thresholds (occlusion_*) do not change scores: compare their "silent wrong" (wrong and not flagged, so it
auto-commits) against "flagged right" (an extra tap) instead.

Usage:
  python tools/tune_params.py SESSION_DIR [SESSION_DIR ...] [--params change_threshold,stable_frames] [--full]
"""
import argparse
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import vision_tuning  # noqa: E402
from tools.make_labels import make_labels, read_jsonl  # noqa: E402
from tools.replay_recording import apply_action, load_frame, restore_start  # noqa: E402
from vision import Vision  # noqa: E402


def in_holdout(label, share):
    return (label['throw_id'] * 2654435761) % 1000 < share * 1000


def replay_scored(directory):
    """Replay one recording with the current thresholds.

    Returns ({event order of each commit: (label the replay proposed or None, flagged low confidence)},
    false proposals).
    """
    directory = Path(directory)
    files = {record['seq']: record['file'] for record in read_jsonl(directory / 'frames.jsonl')}
    processed = read_jsonl(directory / 'processed.jsonl')
    events = sorted(read_jsonl(directory / 'events.jsonl'), key=lambda e: e['order'])
    events = [e for e in events if e['type'] in ('vision', 'commit') or
              (e['type'] == 'recording_started' and e.get('part', 1) > 1)]
    vision = Vision()
    restore_start(vision, directory)
    snapshot_ids, detected, seen, committed = {}, {}, set(), set()
    index = 0

    def run_events(seq):
        nonlocal index, vision
        while index < len(events) and events[index].get('after_seq') == seq:
            event = events[index]
            index += 1
            if event['type'] == 'recording_started':
                vision = Vision()
                restore_start(vision, directory, event.get('start') or f"start-{event['part']}")
            elif event['type'] == 'commit':
                head = vision.proposal
                detected[event['order']] = (head['label'], bool(head.get('check'))) if head else (None, False)
                if head is not None and head.get('id'):
                    committed.add(head['id'])
                    vision.commit_dart(head['id'])  # the replay's own dart takes the live dart's place
                elif vision.aligned and vision.fresh():
                    vision.absorb()  # scored by hand: the dart joins the reference, as live
            elif event['action'] not in ('commit_dart', 'absorb'):  # replaced by the commit above
                apply_action(vision, event, snapshot_ids)

    run_events(None)
    for record in processed:
        if record['seq'] in files:
            vision.ingest(load_frame(directory, files[record['seq']]))
            seen.update(p['id'] for p in vision.pending if p.get('id'))
        run_events(record['seq'])
    return detected, len(seen - committed)


def labels_of(directory):
    path = Path(directory) / 'labels.jsonl'
    return read_jsonl(path) if path.exists() else make_labels(directory)


def evaluate(sessions, setting, holdout):
    """Scores of one setting over all sessions: tuning and hold-out parts."""
    totals = {part: {'darts': 0, 'proposed': 0, 'exact': 0, 'silent_wrong': 0, 'flagged_right': 0}
              for part in ('tune', 'holdout')}
    false = 0
    with vision_tuning.overridden(setting):
        for directory, labels in sessions:
            detected, extra = replay_scored(directory)
            false += extra
            for label in labels:
                if label['source'] == 'filled' or label['truth_label'] == 'Miss' or 'stacked' in label['tags']:
                    continue
                part = totals['holdout' if in_holdout(label, holdout) else 'tune']
                guess, flagged = detected.get(label['event_order'], (None, False))
                part['darts'] += 1
                part['proposed'] += guess is not None
                part['exact'] += guess == label['truth_label']
                part['silent_wrong'] += guess not in (None, label['truth_label']) and not flagged
                part['flagged_right'] += guess == label['truth_label'] and flagged
    return totals, false


def settings(names, full):
    grids = {name: vision_tuning.TUNABLE[name][2] for name in names}
    if full:
        for values in itertools.product(*grids.values()):
            yield dict(zip(grids, values))
        return
    yield {}
    for name, grid in grids.items():
        for value in grid:
            if value != vision_tuning.current(name):
                yield {name: value}


def share(part):
    return part['exact'] / part['darts'] if part['darts'] else 0.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sessions', nargs='+')
    parser.add_argument('--params', default=','.join(vision_tuning.TUNABLE),
                        help='comma-separated names from vision_tuning.TUNABLE (default: all)')
    parser.add_argument('--full', action='store_true', help='every combination of the grids (slow)')
    parser.add_argument('--holdout', type=float, default=0.3, help='share of throws held out (default 0.3)')
    args = parser.parse_args(argv)
    names = [name for name in args.params.split(',') if name]
    unknown = [name for name in names if name not in vision_tuning.TUNABLE]
    if unknown:
        parser.error('unknown parameter(s): ' + ', '.join(unknown) + '. Known: ' + ', '.join(vision_tuning.TUNABLE))
    sessions = [(directory, labels_of(directory)) for directory in args.sessions]
    stacked = sum('stacked' in label['tags'] for _, labels in sessions for label in labels)
    if stacked:
        print(f'{stacked} darts tagged "stacked" are left out of the scores.')
    rows = []
    print(f"{'setting':42} {'exact (tune)':>13} {'proposed':>9} {'false':>6} {'silent wrong':>13} "
          f"{'flagged right':>14} {'exact (hold-out)':>17}")
    for setting in settings(names, args.full):
        totals, false = evaluate(sessions, setting, args.holdout)
        name = ', '.join(f'{k}={v}' for k, v in setting.items()) or 'current values'
        rows.append((setting, totals, false))
        tune = totals['tune']
        print(f"{name:42} {share(tune):13.1%} {tune['proposed']:>4}/{tune['darts']:<4} {false:6d} "
              f"{tune['silent_wrong']:13d} {tune['flagged_right']:14d} {share(totals['holdout']):17.1%}", flush=True)
    baseline = rows[0]
    allowed = [row for row in rows if row[2] <= baseline[2]]
    best = max(allowed, key=lambda row: (share(row[1]['tune']), -row[2]))
    print()
    if best is baseline or share(best[1]['tune']) <= share(baseline[1]['tune']):
        print('Keep the current values: nothing beat them without more false proposals.')
    elif share(best[1]['holdout']) <= share(baseline[1]['holdout']):
        change = ', '.join(f'{k}={v}' for k, v in best[0].items())
        print(f"Keep the current values: {change} scored better on the tuning darts "
              f"({share(baseline[1]['tune']):.1%} -> {share(best[1]['tune']):.1%}) but not on the hold-out darts "
              f"({share(baseline[1]['holdout']):.1%} -> {share(best[1]['holdout']):.1%}).")
    else:
        change = ', '.join(f'{k}={v}' for k, v in best[0].items())
        print(f"Best: {change}: exact {share(baseline[1]['tune']):.1%} -> {share(best[1]['tune']):.1%} on the tuning "
              f"darts, {share(baseline[1]['holdout']):.1%} -> {share(best[1]['holdout']):.1%} on the hold-out darts; "
              f"false proposals {baseline[2]} -> {best[2]}.")
        print('Check it on the next session before relying on it. Set it in vision_tuning.py (or the module named '
              'in vision_tuning.TUNABLE).')
    return rows, best


if __name__ == '__main__':
    main()
