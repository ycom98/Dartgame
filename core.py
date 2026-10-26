"""Deterministic 301/501 rules and regulation board geometry (millimetres)."""
import copy
import math

SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

def score_point(x, y):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
        raise ValueError('Coordinates must be finite numbers')
    radius = math.hypot(x, y)
    angle = math.atan2(x, -y)
    sector = SECTORS[int(math.floor((math.degrees(angle) + 9) / 18)) % 20]
    if radius > 170: return {'value': 0, 'multiplier': 1, 'label': 'Miss', 'score': 0}
    if radius <= 6.35: return {'value': 25, 'multiplier': 2, 'label': 'Bull', 'score': 50}
    if radius <= 15.9: return {'value': 25, 'multiplier': 1, 'label': 'Outer bull', 'score': 25}
    multiplier = 3 if 99 <= radius <= 107 else 2 if radius >= 162 else 1
    return {'value': sector, 'multiplier': multiplier, 'label': ('T' if multiplier == 3 else 'D' if multiplier == 2 else 'S') + str(sector), 'score': sector * multiplier}

def near_wire(x, y, tolerance=1.5):
    r = math.hypot(x, y)
    if any(abs(r - edge) < tolerance for edge in (6.35, 15.9, 99, 107, 162, 170)):
        return True
    if 15.9 < r <= 170:
        degrees = math.degrees(math.atan2(x, -y))
        distance_degrees = abs(((degrees + 9) % 18) - 0)
        distance_degrees = min(distance_degrees, 18 - distance_degrees)
        return r * math.sin(math.radians(distance_degrees)) < tolerance
    return False

class Game:
    def __init__(self, names, start=301, double_out=False):
        if type(start) is not int or start not in (301, 501): raise ValueError('Choose 301 or 501')
        if not isinstance(names, list) or not 2 <= len(names) <= 4:
            raise ValueError('Choose 2–4 players')
        if any(not isinstance(name, str) or not name.strip() or len(name.strip()) > 30 for name in names):
            raise ValueError('Player names must contain 1–30 characters')
        if len(set(n.strip().casefold() for n in names)) != len(names):
            raise ValueError('Player names must be distinct')
        if not isinstance(double_out, bool): raise ValueError('double_out must be true or false')
        self.data = {'names': [n.strip() for n in names], 'scores': [start] * len(names), 'start': start,
                     'double_out': double_out, 'player': 0, 'turn_start': start, 'darts': [],
                     'bust': False, 'winner': None, 'turn': 1}
        self.history = []
    def snapshot(self): return copy.deepcopy(self.data)
    def _save(self): self.history.append(self.snapshot())
    def throw(self, value, multiplier=1, filled=False):
        """Record one dart. filled=True marks a miss the server filled in for an undetected dart."""
        d = self.data
        if type(value) is not int or type(multiplier) is not int or multiplier not in (1, 2, 3):
            raise ValueError('Invalid dart')
        if value not in (*range(0, 21), 25) or (value == 25 and multiplier == 3) or (value == 0 and multiplier != 1):
            raise ValueError('Invalid board score')
        if d['winner'] is not None or d['bust'] or len(d['darts']) >= 3:
            raise ValueError('Turn is finished; advance or undo')
        self._save()
        remaining = d['scores'][d['player']] - value * multiplier
        dart = {'value': value, 'multiplier': multiplier, 'score': value * multiplier}
        if filled: dart['filled'] = True
        d['darts'].append(dart)
        bust = remaining < 0 or (d['double_out'] and (remaining == 1 or (remaining == 0 and multiplier != 2)))
        if bust:
            d['scores'][d['player']] = d['turn_start']; d['bust'] = True
        else:
            d['scores'][d['player']] = remaining
            if remaining == 0: d['winner'] = d['player']
        return self.snapshot()
    def next_turn(self):
        d = self.data
        if d['winner'] is not None: raise ValueError('Game is finished')
        if not d['bust'] and len(d['darts']) != 3: raise ValueError('Record all three darts, including misses, first')
        self._save()
        d['player'] = (d['player'] + 1) % len(d['names'])
        d['turn_start'] = d['scores'][d['player']]
        d['darts'] = []; d['bust'] = False; d['turn'] += 1
        return self.snapshot()
    def fill_misses(self):
        """End the turn with fewer than 3 darts: record the missing darts as filled-in misses."""
        d = self.data
        if d['winner'] is not None or d['bust'] or len(d['darts']) >= 3:
            raise ValueError('Turn is finished; advance or undo')
        count = 3 - len(d['darts'])
        before = self.snapshot(); history = list(self.history)
        for _ in range(count): self.throw(0, 1, filled=True)
        self.history = history + [before]  # one undo step
        return count
    def correct(self, index, value, multiplier=1):
        """Replace dart `index` of the current turn and replay the later darts (one undo step).

        Returns the number of later darts dropped because the corrected dart ended the turn (bust or win)."""
        d = self.data
        if type(index) is not int or not 0 <= index < len(d['darts']): raise ValueError('No such dart in this turn')
        before = self.snapshot(); history = list(self.history)
        darts = [dict(dart) for dart in d['darts']]
        darts[index] = {'value': value, 'multiplier': multiplier}
        # Replay the turn from its start (the history may hold collapsed steps from earlier corrections).
        start = self.snapshot()
        start.update(darts=[], bust=False, winner=None)
        start['scores'][start['player']] = start['turn_start']
        self.data = start
        try:
            dropped = 0
            for dart in darts:
                if self.data['winner'] is not None or self.data['bust']:
                    dropped += 1; continue
                self.throw(dart['value'], dart['multiplier'], filled=dart.get('filled', False) and dart['value'] == 0)
        except ValueError:
            self.data, self.history = before, history
            raise
        self.history = history + [before]
        return dropped
    def undo(self):
        if not self.history: raise ValueError('Nothing to undo')
        self.data = self.history.pop()
        return self.snapshot()
