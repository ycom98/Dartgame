#!/usr/bin/env python3
"""One shareable report for a recorded trial session (M4-03).

Runs make_labels (unless labels.jsonl already exists: hand-fixed truth and tags are kept), replays the recording
through Vision, draws the contact sheet, and writes into REPORT_DIR (default SESSION_DIR/report):
  trial_report.md     accuracy overall / near-wire / stacked, no-proposal and false-proposal rates, latency,
                      calibration quality, mount and lighting notes, and every wrong or corrected dart
  contact_sheet.png   before/after crops of the darts worth a look (wrong, corrected, not proposed, flagged), at half
                      size, at most SHEET_PANELS of them: never larger than one 1280x720 frame
  crops/throw_NNN.png the crop pair of each wrong or corrected dart (named in the report)

Privacy: only small crops around each dart leave the recording; no video and no full frames are written.
Send back the whole REPORT_DIR folder.

Usage: python tools/trial_report.py SESSION_DIR [--out REPORT_DIR] [--relabel]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import vision_tuning  # noqa: E402
from tools.contact_sheet import Panels  # noqa: E402
from tools.make_labels import make_labels, read_jsonl  # noqa: E402
from tools.replay_recording import replay  # noqa: E402


# The report's contact sheet: half-size panels, SHEET_COLUMNS wide, at most SHEET_PANELS (1258 x 612 px), so it is
# never frame-sized and does not grow with the session (QA M4 M2). Every listed dart also has its own crop file.
SHEET_COLUMNS = 5
SHEET_PANELS = 20


def contact_sheet(drawer, labels):
    """(sheet image or None, labels drawn) for the first SHEET_PANELS labels, at half size."""
    shown = labels[:SHEET_PANELS]
    if not shown:
        return None, []
    tiles = [cv2.resize(drawer.panel(label), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA) for label in shown]
    height, width = tiles[0].shape[:2]
    rows = (len(tiles) + SHEET_COLUMNS - 1) // SHEET_COLUMNS
    sheet = np.full((rows * (height + 8) + 8, SHEET_COLUMNS * (width + 8) + 8, 3), 24, np.uint8)
    for index, tile in enumerate(tiles):
        row, column = divmod(index, SHEET_COLUMNS)
        y, x = 8 + row * (height + 8), 8 + column * (width + 8)
        sheet[y:y + height, x:x + width] = tile
    return sheet, shown


def rate(count, total):
    return None if not total else count / total


def percent(value):
    return '—' if value is None else f'{100 * value:.1f}%'


def accuracy_row(name, labels):
    """(name, darts, camera proposed, exact share of proposed, no-proposal share)."""
    proposed = [label for label in labels if label['detection_label'] is not None]
    exact = sum(label['detection_label'] == label['truth_label'] for label in proposed)
    return (name, len(labels), len(proposed), rate(exact, len(proposed)), rate(len(labels) - len(proposed), len(labels)))


def scored(labels):
    """Darts the camera should have proposed: not misses (filled in, or tapped as Miss)."""
    return [label for label in labels if label['source'] != 'filled' and label['truth_label'] != 'Miss']


def latency(directory, labels):
    """Seconds from the dart landing (first unsteady frame) to its proposal, and from proposal to commit."""
    stamps = {record['seq']: record['ts'] for record in read_jsonl(Path(directory) / 'frames.jsonl')}
    events = {event['order']: event for event in read_jsonl(Path(directory) / 'events.jsonl')}
    detect, commit = [], []
    for label in labels:
        seen, landed = label.get('frame_seq_detected'), label.get('frame_seq_landed')
        if seen in stamps and landed in stamps:
            detect.append(stamps[seen] - stamps[landed])
        event = events.get(label['event_order'])
        if seen in stamps and event is not None:
            commit.append(event['ts'] - stamps[seen])
    return detect, commit


def spread(values):
    if not values:
        return '—'
    values = sorted(values)
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    return f'median {statistics.median(values):.2f} s · p90 {p90:.2f} s · max {values[-1]:.2f} s (n {len(values)})'


def false_proposals(directory, labels):
    """Camera darts that were pending but never committed (bounce-outs retracted, darts left at Next player,
    and false detections). None for recordings made before M4-01 (no dart ids in processed.jsonl)."""
    processed = read_jsonl(Path(directory) / 'processed.jsonl')
    if not any('pending' in record for record in processed):
        return None
    seen = {dart['id'] for record in processed for dart in record.get('pending') or [] if dart.get('id')}
    committed = {label['detection_id'] for label in labels if label.get('detection_id')}
    return len(seen - committed)


def calibrations(directory):
    rows = []
    for event in sorted(read_jsonl(Path(directory) / 'events.jsonl'), key=lambda e: e['order']):
        if event.get('type') == 'vision' and event.get('action') == 'calibrate' and event.get('ok'):
            quality = (event.get('result') or {}).get('calibration') or {}
            rows.append(quality)
    return rows


def vision_actions(directory):
    counts = {}
    for event in read_jsonl(Path(directory) / 'events.jsonl'):
        if event.get('type') == 'vision':
            key = event['action'] + ('' if event.get('ok') else ' (failed)')
            counts[key] = counts.get(key, 0) + 1
    return counts


def table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    lines += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return '\n'.join(lines)


def build_report(directory, out, relabel=False):
    directory, out = Path(directory), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    labels_path = directory / 'labels.jsonl'
    if relabel or not labels_path.exists():
        labels = make_labels(directory)
        with open(labels_path, 'w', encoding='utf-8') as handle:
            for label in labels:
                handle.write(json.dumps(label) + '\n')
    labels = read_jsonl(labels_path)
    replayed = replay(directory)

    darts = scored(labels)
    flagged = [label for label in darts if label.get('detection_check')]
    rows = [accuracy_row('All darts', darts),
            accuracy_row('Near a wire (camera flag or "wire" tag)',
                         [l for l in darts if l.get('detection_near_wire') or 'wire' in l['tags']]),
            accuracy_row('Stacked ("stacked" tag)', [l for l in darts if 'stacked' in l['tags']]),
            accuracy_row('Flagged low confidence by the camera', flagged),
            accuracy_row('Not flagged', [l for l in darts if not l.get('detection_check')]),
            accuracy_row('Dart 1 of the turn', [l for l in darts if l['dart'] == 1]),
            accuracy_row('Darts 2 and 3 of the turn', [l for l in darts if l['dart'] > 1])]
    wrong_flagged = sum(l['detection_label'] not in (None, l['truth_label']) for l in flagged)
    wrong_total = sum(l['detection_label'] not in (None, l['truth_label']) for l in darts)
    false_count = false_proposals(directory, labels)
    detect, commit = latency(directory, labels)
    session = json.loads((directory / 'session.json').read_text()) if (directory / 'session.json').exists() else {}

    lines = [f'# Trial report: {directory.name}', '',
             'Generated by `tools/trial_report.py` from this recording. '
             'No video or full frames are included: only small crops around each dart.', '',
             '## Accuracy', '',
             'Truth is the host\'s final value (accepted, corrected or tapped). "Exact" is the share of camera '
             'proposals with the right score; "no proposal" is the share of darts the camera did not propose '
             '(misses excluded).', '',
             table(['Darts', 'n', 'camera proposed', 'exact', 'no proposal'],
                   [(name, n, p, percent(e), percent(none)) for name, n, p, e, none in rows]), '',
             f'- Low-confidence flags (M4-02): {len(flagged)} darts flagged; {wrong_flagged} of the {wrong_total} '
             'wrong camera scores were flagged (flagged darts wait for Accept instead of auto-committing).',
             '- False proposals (camera darts never committed: false detections, bounce-outs, darts left at Next): '
             + ('not recorded (recording made before M4-01)' if false_count is None else
                f'{false_count} ({percent(rate(false_count, len(darts)))} of darts)'),
             f'- Replay: {"identical to live" if replayed["identical"] else "DIFFERS from live"} '
             f'({replayed["frames_processed"]} frames, {len(replayed["detection_mismatches"])} detection mismatches, '
             f'{len(replayed["frames_missing"])} missing frames).', '',
             '## Latency', '',
             f'- Dart landing to camera proposal: {spread(detect)} (landing = first frame that changed; '
             'a dart that changed too little to unsettle the image counts from the frame it was seen in)',
             f'- Camera proposal to commit: {spread(commit)}', '',
             '## Calibration', '']
    quality = calibrations(directory)
    if quality:
        lines.append(table(['#', 'method', 'confidence', 'residual mm', 'click error px', 'reason'],
                           [(i + 1, q.get('method'), q.get('confidence'), q.get('residual_mm'), q.get('click_error_px'),
                             q.get('reason') or '') for i, q in enumerate(quality)]))
    else:
        lines.append('No calibration in this recording (it started from a saved calibration).')
    actions = vision_actions(directory)
    lines += ['', 'Camera actions: ' + (', '.join(f'{k} {v}' for k, v in sorted(actions.items())) or 'none'), '',
              '## Mount, lighting and phone notes', '']
    notes = session.get('notes') or {}
    lines += [f'- **{key}**: {value}' for key, value in notes.items()] or ['- (no notes entered on the setup page)']
    source = session.get('source') or {}
    if source:
        lines.append(f"- **camera**: {source.get('kind')} {source.get('width')}x{source.get('height')}")
    lines += [f"- **frames**: {session.get('frames')} recorded, {session.get('skipped_frames')} skipped", '',
              '## Wrong or corrected darts', '']

    problems = [l for l in labels if l['source'] == 'corrected' or
                l['detection_label'] not in (None, l['truth_label']) or
                (l in darts and l['detection_label'] is None)]
    drawer = Panels(directory) if labels else None
    worth_a_look = problems + [l for l in flagged if l not in problems]
    sheet, shown = contact_sheet(drawer, worth_a_look) if drawer else (None, [])
    (out / 'contact_sheet.png').unlink(missing_ok=True)
    if sheet is not None:
        cv2.imwrite(str(out / 'contact_sheet.png'), sheet)
    panels = len(shown)
    crops = out / 'crops'
    entries = []
    for label in problems:
        crops.mkdir(exist_ok=True)
        name = f"throw_{label['throw_id']:03d}.png"
        cv2.imwrite(str(crops / name), drawer.panel(label))
        entries.append((label['throw_id'], f"G{label['game']} T{label['turn']} D{label['dart']}", label['truth_label'],
                        label['detection_label'] or 'no proposal', label['source'],
                        '; '.join(label.get('detection_check') or []) or ('near wire' if label.get('detection_near_wire') else ''),
                        ', '.join(label['tags']), f'crops/{name}'))
    lines.append(table(['throw', 'dart', 'truth', 'camera', 'recorded as', 'camera flags', 'tags', 'crop'], entries)
                 if entries else 'None.')
    lines += ['', f'`contact_sheet.png` shows {len(shown)} of the {len(worth_a_look)} wrong, corrected, unproposed or '
              'flagged darts' + (f' (the first {SHEET_PANELS}; every one listed above has its own crop)'
                                 if len(worth_a_look) > len(shown) else '') + '.']
    lines += ['', '## Thresholds in use', '',
              'Synthetic-tuned values (`vision_tuning.py`); tune them on this recording with '
              f'`tools/tune_params.py {directory.name}` (run it on the session folder on the Mac).', '',
              table(['name', 'value'], [(name, vision_tuning.current(name)) for name in vision_tuning.TUNABLE]), '']
    (out / 'trial_report.md').write_text('\n'.join(lines))
    return {'report': str(out / 'trial_report.md'), 'darts': len(darts), 'panels': panels, 'problems': len(entries),
            'replay_identical': replayed['identical']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory')
    parser.add_argument('--out', help='report folder (default: SESSION_DIR/report)')
    parser.add_argument('--relabel', action='store_true', help='rebuild labels.jsonl (discards hand fixes)')
    args = parser.parse_args(argv)
    result = build_report(args.directory, args.out or Path(args.directory) / 'report', args.relabel)
    print(f"{result['report']}: {result['darts']} darts, {result['problems']} wrong or corrected, "
          f"replay {'identical' if result['replay_identical'] else 'DIFFERS'}")
    return result


if __name__ == '__main__':
    main()
