"""301 / 501, straight or double out: the original core.Game rules, unchanged (M1-15)."""
from . import checkout
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

    def checkout_hint(self, d):
        """The recommended finish with the darts left this turn, or None (M3 UI-03)."""
        if d['winner'] is not None or self.turn_over(d):
            return None
        remaining = d['scores'][d['player']]
        darts_left = 3 - len(d['darts'])
        route = checkout.suggest(remaining, darts_left, d['double_out'])
        if route is None:
            return None
        return {'player': d['player'], 'remaining': remaining, 'darts_left': darts_left, 'route': route}

    def match_stats(self, turns, d):
        """Per player: 3-dart average, highest turn, darts thrown, 100+ / 140+ / 180 counts, checkout.

        A bust turn counts its darts and scores 0. The 100+ band is 100-139 and 140+ is 140-179, as on a
        darts scoreboard; 180 is counted on its own."""
        players = []
        for _ in d['names']:
            players.append({'darts': 0, 'points': 0, 'turns': 0, 'highest': 0, 'tons': 0, 'ton_forties': 0,
                            'maximums': 0, 'busts': 0, 'checkout': None, 'checkout_darts': None})
        for turn in turns:
            stats = players[turn['player']]
            darts = len(turn['darts'])
            if darts == 0:
                continue
            scored = 0 if turn['bust'] else turn['turn_start'] - turn['scores'][turn['player']]
            stats['darts'] += darts
            stats['points'] += scored
            stats['turns'] += 1
            stats['highest'] = max(stats['highest'], scored)
            stats['busts'] += 1 if turn['bust'] else 0
            if scored == 180:
                stats['maximums'] += 1
            elif scored >= 140:
                stats['ton_forties'] += 1
            elif scored >= 100:
                stats['tons'] += 1
            if turn['winner'] == turn['player']:
                stats['checkout'] = scored
                stats['checkout_darts'] = darts
        for stats in players:
            stats['average'] = round(stats['points'] / stats['darts'] * 3, 1) if stats['darts'] else 0.0
        return {'kind': 'x01', 'players': players}
