"""Per-throw before/after crops for reviewing labels (M1-14).

For each label: the empty-board base frame and the frame at commit, cropped around the detected tip
(marked) or, for a dart the camera did not propose, around the bull. Captions give the throw, the host's
value (truth), how it was recorded and what the camera proposed.

Usage: python tools/contact_sheet.py RECORDING_DIR [--out contact_sheet.png] [--columns 3]
"""
import argparse
import bisect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from tools.make_labels import make_labels, read_jsonl  # noqa: E402

TARGET_MM = np.float32([[0, -170], [170, 0], [0, 170], [-170, 0]])
CROP = 120      # half-size of the crop in image pixels
PANEL = 240     # each crop is shown at PANEL x PANEL
CAPTION = 46


def nearest_frame(seqs, files, seq):
    """The recorded frame with the largest seq <= seq (or the first one)."""
    if seq is None or not seqs:
        return None
    index = bisect.bisect_right(seqs, seq) - 1
    return files[seqs[max(index, 0)]]


def overlay_before(events, order):
    """Image positions of the four calibration points in force at event `order`."""
    overlay = None
    for event in events:
        if event['order'] > order:
            break
        if event['type'] == 'vision' and event.get('overlay'):
            overlay = event['overlay']
    return overlay


def crop(image, centre, mark):
    if image is None:
        return np.zeros((PANEL, PANEL, 3), np.uint8)
    x, y = int(round(centre[0])), int(round(centre[1]))
    padded = cv2.copyMakeBorder(image, CROP, CROP, CROP, CROP, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    piece = padded[y:y + 2 * CROP, x:x + 2 * CROP].copy()
    if mark:
        cv2.circle(piece, (CROP, CROP), 9, (0, 230, 255), 2)
        cv2.drawMarker(piece, (CROP, CROP), (0, 230, 255), cv2.MARKER_CROSS, 8, 1)
    return cv2.resize(piece, (PANEL, PANEL), interpolation=cv2.INTER_AREA)


def make_sheet(directory, columns=3):
    directory = Path(directory)
    labels_path = directory / 'labels.jsonl'
    labels = read_jsonl(labels_path) if labels_path.exists() else make_labels(directory)
    frames = {r['seq']: r['file'] for r in read_jsonl(directory / 'frames.jsonl')}
    seqs = sorted(frames)
    events = sorted(read_jsonl(directory / 'events.jsonl'), key=lambda e: e['order'])
    panels = []
    for label in labels:
        before_file = nearest_frame(seqs, frames, label['frame_seq_before'])
        after_file = nearest_frame(seqs, frames, label['frame_seq_after'])
        before = cv2.imread(str(directory / before_file)) if before_file else None
        after = cv2.imread(str(directory / after_file)) if after_file else None
        overlay = overlay_before(events, label['event_order'])
        centre, mark = None, False
        if overlay is not None:
            to_image = cv2.getPerspectiveTransform(TARGET_MM, np.float32(overlay))
            point = label['detection_xy'] or [0.0, 0.0]
            centre = cv2.perspectiveTransform(np.float32([[point]]), to_image)[0][0]
            mark = label['detection_xy'] is not None
        elif after is not None:
            centre = (after.shape[1] / 2, after.shape[0] / 2)
        tile = np.zeros((PANEL + CAPTION, 2 * PANEL + 4, 3), np.uint8)
        tile[CAPTION:, :PANEL] = crop(before, centre, False) if centre is not None else 0
        tile[CAPTION:, PANEL + 4:] = crop(after, centre, mark) if centre is not None else 0
        first = f"#{label['throw_id']} T{label['turn']} D{label['dart']}  truth {label['truth_label']}"
        second = f"{label['source']} · camera {label['detection_label'] or '-'}"
        colour = (120, 230, 140) if label['detection_label'] == label['truth_label'] else (90, 170, 255)
        cv2.putText(tile, first, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(tile, second.replace('·', '-'), (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
        panels.append(tile)
    if not panels:
        raise ValueError('No labels to draw')
    rows = (len(panels) + columns - 1) // columns
    height, width = panels[0].shape[:2]
    sheet = np.full((rows * (height + 8) + 8, columns * (width + 8) + 8, 3), 24, np.uint8)
    for index, tile in enumerate(panels):
        row, column = divmod(index, columns)
        y, x = 8 + row * (height + 8), 8 + column * (width + 8)
        sheet[y:y + height, x:x + width] = tile
    return sheet, len(panels)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory')
    parser.add_argument('--out', help='default: RECORDING_DIR/contact_sheet.png')
    parser.add_argument('--columns', type=int, default=3)
    args = parser.parse_args(argv)
    sheet, count = make_sheet(args.directory, args.columns)
    out = args.out or str(Path(args.directory) / 'contact_sheet.png')
    cv2.imwrite(out, sheet)
    print(f'{count} panels written to {out}')
    return count


if __name__ == '__main__':
    main()
