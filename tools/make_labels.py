"""Derive labels.jsonl from a recording's events.jsonl (M1-14).

One line per committed dart, in throw order:
  {throw_id, game, turn, player, dart, truth_label, source, detection_label, detection_xy,
   frame_seq_before, frame_seq_after, event_order, tags: []}

source: accepted (camera dart accepted by tap), auto (accepted by the 3 s timer), corrected (the host's
value replaced the camera's, at once or later), manual (no camera dart: host tapped), filled (miss filled
in at the end of a turn). The host's final value is the truth. frame_seq_before is the empty-board base
frame the dart was detected against; frame_seq_after is the newest processed frame at commit. event_order points into events.jsonl.
Tags (wire, stacked, bounce, miss, occluded, bump) are added by hand afterwards.

Usage: python tools/make_labels.py RECORDING_DIR
"""
import argparse
import json
from pathlib import Path


def dart_label(dart):
    value, multiplier = dart['value'], dart['multiplier']
    if value == 0:
        return 'Miss'
    if value == 25:
        return 'Bull' if multiplier == 2 else 'Outer bull'
    return {1: 'S', 2: 'D', 3: 'T'}[multiplier] + str(value)


def read_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def make_labels(directory):
    events = sorted(read_jsonl(Path(directory) / 'events.jsonl'), key=lambda e: e['order'])
    turns = {}          # (game, turn) -> [record]
    order = []          # every record ever made, in throw order
    game = 0
    base_seq = None
    for event in events:
        kind = event['type']
        if kind == 'vision' and event.get('ok') and event['action'] in ('reset_base', 'calibrate', 'align'):
            base_seq = event.get('after_seq')
        elif kind == 'game':
            game += 1
        elif kind == 'commit':
            proposal = event.get('proposal')
            record = {'game': game, 'turn': event['turn'], 'player': event['player'], 'dart': event['dart_index'] + 1,
                      'truth_label': dart_label(event['dart']), 'source': event['source'],
                      'detection_label': proposal.get('label') if proposal else None,
                      'detection_xy': [proposal.get('x'), proposal.get('y')] if proposal else None,
                      'frame_seq_before': base_seq, 'frame_seq_after': event.get('after_seq'),
                      'event_order': event['order'], 'tags': []}
            darts = turns.setdefault((game, event['turn']), [])
            del darts[event['dart_index']:]
            darts.append(record)
            order.append(record)
        elif kind == 'correct':
            darts = turns.get((game, event['turn']), [])
            index = event['dart_index']
            if index < len(darts):
                darts[index]['truth_label'] = dart_label(event['after'])
                darts[index]['source'] = 'corrected'
            dropped = event.get('dropped_later_darts', 0)
            if dropped:
                del darts[len(darts) - dropped:]
        elif kind == 'fill_misses':
            darts = turns.setdefault((game, event['turn']), [])
            for _ in range(event['count']):
                record = {'game': game, 'turn': event['turn'], 'player': event['player'], 'dart': len(darts) + 1,
                          'truth_label': 'Miss', 'source': 'filled', 'detection_label': None, 'detection_xy': None,
                          'frame_seq_before': base_seq, 'frame_seq_after': event.get('after_seq'),
                          'event_order': event['order'], 'tags': []}
                darts.append(record)
                order.append(record)
        elif kind == 'undo':
            after = event['after']
            darts = turns.setdefault((game, after['turn']), [])
            del darts[len(after['darts']):]
            for record, dart in zip(darts, after['darts']):
                truth = dart_label(dart)
                if truth != record['truth_label']:  # an undone correction
                    record['truth_label'] = truth
                    record['source'] = 'filled' if dart.get('filled') else (
                        'corrected' if record['detection_label'] not in (None, truth) else
                        record['source'] if record['source'] != 'corrected' else 'accepted')
            for key in [k for k in turns if k[0] == game and k[1] > after['turn']]:
                turns[key] = []  # an undone Next: later turns had no darts yet
    alive = {id(record) for darts in turns.values() for record in darts}
    labels = [record for record in order if id(record) in alive]
    for throw_id, record in enumerate(labels, 1):
        record['throw_id'] = throw_id
    return [{'throw_id': r['throw_id'], **{k: v for k, v in r.items() if k != 'throw_id'}} for r in labels]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory')
    args = parser.parse_args(argv)
    labels = make_labels(args.directory)
    path = Path(args.directory) / 'labels.jsonl'
    with open(path, 'w', encoding='utf-8') as handle:
        for label in labels:
            handle.write(json.dumps(label) + '\n')
    sources = {}
    for label in labels:
        sources[label['source']] = sources.get(label['source'], 0) + 1
    print(f'{len(labels)} labels written to {path}: ' + ', '.join(f'{k} {v}' for k, v in sorted(sources.items())))
    return labels


if __name__ == '__main__':
    main()
