"""301 / 501, straight or double out: the original core.Game rules, unchanged (M1-15)."""
from .base import GameMode

STARTS = (301, 501)


class X01(GameMode):
    id = 'x01'
    display_name = '301 / 501'
    description = 'Count down from 301 or 501 to exactly zero. Optional double out.'

    def validate_options(self, options):
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise ValueError('options must be an object')
        unknown = set(options) - {'start', 'double_out'}
        if unknown:
            raise ValueError('Unknown x01 option: ' + ', '.join(sorted(unknown)))
        start = options.get('start', 301)
        if type(start) is not int or start not in STARTS: raise ValueError('Choose 301 or 501')
        double_out = options.get('double_out', False)
        if not isinstance(double_out, bool): raise ValueError('double_out must be true or false')
        return {'start': start, 'double_out': double_out}

    def new_state(self, names, options):
        start = options['start']
        return {'names': names, 'scores': [start] * len(names), 'start': start,
                'double_out': options['double_out'], 'player': 0, 'turn_start': start, 'darts': [],
                'bust': False, 'winner': None, 'turn': 1}

    def throw(self, d, value, multiplier):
        remaining = d['scores'][d['player']] - value * multiplier
        d['darts'].append(self.score_dart(d, value, multiplier))
        bust = remaining < 0 or (d['double_out'] and (remaining == 1 or (remaining == 0 and multiplier != 2)))
        if bust:
            d['scores'][d['player']] = d['turn_start']; d['bust'] = True
        else:
            d['scores'][d['player']] = remaining
            if remaining == 0: d['winner'] = d['player']

    def turn_over(self, d):
        return d['winner'] is not None or d['bust'] or len(d['darts']) >= 3

    def can_advance(self, d):
        return d['winner'] is None and (d['bust'] or len(d['darts']) == 3)

    def next_turn(self, d):
        super().next_turn(d)
        d['turn_start'] = d['scores'][d['player']]
        d['bust'] = False

    def from_json(self, data):
        d = super().from_json(data)
        count = len(d['names'])
        if d.get('start') not in STARTS or type(d.get('start')) is not int:
            raise ValueError('Saved x01 game has an invalid start')
        scores = d.get('scores')
        if (not isinstance(scores, list) or len(scores) != count
                or not all(type(v) is int and 0 <= v <= d['start'] for v in scores)):
            raise ValueError('Saved x01 game has invalid scores')
        if type(d.get('turn_start')) is not int or not 0 <= d['turn_start'] <= d['start']:
            raise ValueError('Saved x01 game has an invalid turn start')
        if not isinstance(d.get('double_out'), bool) or not isinstance(d.get('bust'), bool):
            raise ValueError('Saved x01 game has invalid double_out or bust')
        return d

    def presentation_hints(self, d):
        return {'kind': 'x01', 'start': d['start'], 'double_out': d['double_out']}
