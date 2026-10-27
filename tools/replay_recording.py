"""Replay a recording through Vision and score its detections against the labels (M1-14).

The frames vision processed live are fed again, in order, with every recorded vision action (calibration,
alignment, verification, base resets...) applied after the same frame as live. The replayed detection on
each frame is compared with the recorded one (it should be identical), and each committed dart is scored:
did the camera propose the host's final value?

This is a separate tool from tools/eval_detection.py (synthetic harness, owned by another developer); its
report uses the same names where they apply (exact_score_accuracy, no_proposal_rate).

Usage: python tools/replay_recording.py RECORDING_DIR [--out report.json]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from camera_source import fit_frame  # noqa: E402
from tools.make_labels import make_labels, read_jsonl  # noqa: E402
from vision import Vision  # noqa: E402


def load_frame(directory, file):
    frame = cv2.imread(str(Path(directory) / file), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f'Cannot read {file}')
    return fit_frame(frame)


def restore_start(vision, directory, folder='start'):
    """Recording (or a resumed part, start-N/) started mid-session: begin from the state saved then."""
    start = Path(directory) / folder
    if (start / 'frame.png').exists():  # the frame vision held when recording started
        vision.frame = cv2.imread(str(start / 'frame.png'), cv2.IMREAD_COLOR)
        vision.timestamp = time.time()
    if not (start / 'vision.json').exists():
        return False
    state = json.loads((start / 'vision.json').read_text())
    vision.camera_hfov = state['camera_hfov']
    vision.reference = cv2.imread(str(start / 'reference.png'), cv2.IMREAD_COLOR)
    vision.reference_H = np.asarray(state['reference_H'], np.float64)
    vision.H = np.asarray(state['H'], np.float64)
    height, width = vision.reference.shape[:2]
    vision.reference_mask = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(vision.reference_mask, np.asarray(state['reference_points'], np.float32).astype(np.int32), 255)
    vision.ref_kp, vision.ref_desc = vision.orb.detectAndCompute(vision.reference, vision.reference_mask)
    if vision.frame is None:
        vision.frame = vision.reference.copy(); vision.timestamp = time.time()
    vision.aligned = state['aligned']
    if state['has_base']:
        vision.base = cv2.imread(str(start / 'base.png'), cv2.IMREAD_COLOR)
        vision.last_warp = vision.base.copy()
    if vision.aligned:
        vision.last_warp = vision.warp(vision.frame)
    vision.stable = state.get('stable', 0)        # frames already stable when recording started
    vision.version = state.get('version', 0)      # later verify() calls name this version
    vision.mount_side = state['mount_side']
    vision.update_pose()
    if state['verified']:
        vision.verified_version = vision.version
    return True


def apply_action(vision, event, snapshot_ids):
    name, args, kwargs = event['action'], list(event.get('args') or []), dict(event.get('kwargs') or {})
    if name == 'calibrate' and len(args) > 1 and args[1] is not None:
        args[1] = snapshot_ids.get(args[1], args[1])
    try:
        result = getattr(vision, name)(*args, **kwargs)
    except Exception as error:
        return (False, str(error))
    if name == 'begin_calibration' and isinstance(event.get('result'), dict) and isinstance(result, dict):
        snapshot_ids[event['result']['snapshot_id']] = result['snapshot_id']
    return (True, None)


def outcome(vision):
    proposal = vision.proposal
    if proposal is None:
        return None
    if 'x' not in proposal:
        return {'label': proposal.get('label')}
    return {'label': proposal.get('label'), 'x': round(float(proposal['x']), 3), 'y': round(float(proposal['y']), 3)}


def replay(directory):
    directory = Path(directory)
    files = {record['seq']: record['file'] for record in read_jsonl(directory / 'frames.jsonl')}
    processed = read_jsonl(directory / 'processed.jsonl')
    events = sorted(read_jsonl(directory / 'events.jsonl'), key=lambda e: e['order'])
    # Vision actions, and the start of each resumed part (the server restarted: vision begins again from start-N/).
    actions = [e for e in events if e['type'] == 'vision' or (e['type'] == 'recording_started' and e.get('part', 1) > 1)]
    vision = Vision()
    restored = restore_start(vision, directory)
    parts_restored = 0
    snapshot_ids = {}
    action_index = 0
    action_mismatches = []

    def run_actions_up_to(seq):
        nonlocal action_index, vision, parts_restored
        while action_index < len(actions) and (actions[action_index].get('after_seq') is None and seq is None or
                                               actions[action_index].get('after_seq') == seq):
            event = actions[action_index]
            if event['type'] == 'recording_started':
                vision = Vision()
                restore_start(vision, directory, event.get('start') or f"start-{event['part']}")
                parts_restored += 1
                action_index += 1
                continue
            ok, error = apply_action(vision, event, snapshot_ids)
            if ok != event['ok']:
                action_mismatches.append({'order': event['order'], 'action': event['action'], 'live_ok': event['ok'],
                                          'replay_ok': ok, 'replay_error': error})
            action_index += 1

    run_actions_up_to(None)
    mismatches, missing = [], []
    for record in processed:
        seq = record['seq']
        if seq not in files:
            missing.append(seq)
        else:
            vision.ingest(load_frame(directory, files[seq]))
            replayed = outcome(vision)
            if replayed != record['proposal']:
                mismatches.append({'seq': seq, 'live': record['proposal'], 'replay': replayed})
        run_actions_up_to(seq)
    return {'frames_processed': len(processed), 'frames_missing': missing, 'detection_mismatches': mismatches,
            'identical': not mismatches and not missing and not action_mismatches,
            'vision_actions': len(actions), 'action_mismatches': action_mismatches, 'started_from_saved_calibration': restored,
            'resumed_parts': parts_restored}


def score(labels):
    scored = [label for label in labels if label['source'] != 'filled' and 'stacked' not in label['tags']]
    with_detection = [label for label in scored if label['detection_label'] is not None]
    exact = [label for label in with_detection if label['detection_label'] == label['truth_label']]
    sources = {}
    for label in labels:
        sources[label['source']] = sources.get(label['source'], 0) + 1
    return {'labels': len(labels), 'scored': len(scored), 'with_detection': len(with_detection),
            'exact_score_accuracy': round(len(exact) / len(with_detection), 4) if with_detection else None,
            'no_proposal_rate': round(1 - len(with_detection) / len(scored), 4) if scored else None,
            'sources': sources,
            'wrong': [{'throw_id': l['throw_id'], 'truth': l['truth_label'], 'detected': l['detection_label']}
                      for l in with_detection if l not in exact]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory')
    parser.add_argument('--out', help='write the JSON report here')
    args = parser.parse_args(argv)
    labels_path = Path(args.directory) / 'labels.jsonl'
    labels = read_jsonl(labels_path) if labels_path.exists() else make_labels(args.directory)
    report = {'recording': str(args.directory), 'replay': replay(args.directory), 'detection': score(labels)}
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text + '\n')
    print(text)
    return report


if __name__ == '__main__':
    main()
