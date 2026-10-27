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
    """A match of any registered game mode (modes/, M1-15).

    The mode owns the rules and its state (self.data); Game adds what every mode shares: validation of
    names and darts, undo (a snapshot stack in self.history), correcting a dart of the current turn,
    filling in missed darts, and save/restore. Game(names, start, double_out) still makes an x01 game.
    """
    def __init__(self, names, start=301, double_out=False, mode='x01', options=None):
        import modes
        self.mode = modes.get(mode)
        if options is None and self.mode.id == 'x01':
            options = {'start': start, 'double_out': double_out}
        self.options = self.mode.validate_options(options)
        if not isinstance(names, list) or not self.mode.min_players <= len(names) <= self.mode.max_players:
            raise ValueError(f'Choose {self.mode.min_players}\u2013{self.mode.max_players} players')
        if any(not isinstance(name, str) or not name.strip() or len(name.strip()) > 30 for name in names):
            raise ValueError('Player names must contain 1–30 characters')
        if len(set(n.strip().casefold() for n in names)) != len(names):
            raise ValueError('Player names must be distinct')
        self.data = self.mode.new_state([n.strip() for n in names], self.options)
        self.history = []
    def snapshot(self): return {**copy.deepcopy(self.data), 'mode': self.mode.id}
    def hints(self): return self.mode.presentation_hints(self.data)
    def turn_over(self): return self.mode.turn_over(self.data)
    def _save(self): self.history.append(copy.deepcopy(self.data))
    def throw(self, value, multiplier=1, filled=False):
        """Record one dart. filled=True marks a miss the server filled in for an undetected dart."""
        if type(value) is not int or type(multiplier) is not int or multiplier not in (1, 2, 3):
            raise ValueError('Invalid dart')
        if value not in (*range(0, 21), 25) or (value == 25 and multiplier == 3) or (value == 0 and multiplier != 1):
            raise ValueError('Invalid board score')
        if self.mode.turn_over(self.data):
            raise ValueError('Turn is finished; advance or undo')
        self._save()
        self.mode.throw(self.data, value, multiplier)
        if filled: self.data['darts'][-1]['filled'] = True
        return self.snapshot()
    def next_turn(self):
        if self.data['winner'] is not None: raise ValueError('Game is finished')
        if not self.mode.can_advance(self.data): raise ValueError('Record all three darts, including misses, first')
        self._save()
        self.mode.next_turn(self.data)
        return self.snapshot()
    def fill_misses(self):
        """End the turn with fewer darts than allowed: record the missing darts as filled-in misses."""
        if self.mode.turn_over(self.data):
            raise ValueError('Turn is finished; advance or undo')
        before = copy.deepcopy(self.data); history = list(self.history)
        count = 0
        while not self.mode.turn_over(self.data):
            self.throw(0, 1, filled=True); count += 1
        self.history = history + [before]  # one undo step
        return count
    def turn_start_state(self):
        """The state before the first dart of the current turn (from the undo history)."""
        turn = self.data['turn']
        if not self.data['darts']: return copy.deepcopy(self.data)
        for state in reversed(self.history):
            if state['turn'] == turn and not state['darts']:
                return copy.deepcopy(state)
        raise ValueError('The start of this turn is no longer available')
    def correct(self, index, value, multiplier=1):
        """Replace dart `index` of the current turn and replay the later darts (one undo step).

        Returns the number of later darts dropped because the corrected dart ended the turn (bust or win)."""
        d = self.data
        if type(index) is not int or not 0 <= index < len(d['darts']): raise ValueError('No such dart in this turn')
        before = copy.deepcopy(d); history = list(self.history)
        darts = [dict(dart) for dart in d['darts']]
        darts[index] = {'value': value, 'multiplier': multiplier}
        # Replay the turn from its start (the history may hold collapsed steps from earlier corrections).
        self.data = self.turn_start_state()
        try:
            dropped = 0
            for dart in darts:
                if self.mode.turn_over(self.data):
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
    def to_json(self):
        """Everything needed to resume this match (M1-16)."""
        return {'mode': self.mode.id, 'options': copy.deepcopy(self.options), 'state': self.mode.to_json(self.data),
                'history': [self.mode.to_json(state) for state in self.history]}
    @classmethod
    def from_json(cls, data):
        import modes
        if not isinstance(data, dict):
            raise ValueError('Saved match is not an object')
        mode = modes.get(data.get('mode'))
        game = cls.__new__(cls)
        game.mode = mode
        game.options = mode.validate_options(data.get('options'))
        game.data = mode.from_json(data.get('state'))
        if not isinstance(data.get('history'), list):
            raise ValueError('Saved match has no undo history list')
        game.history = [mode.from_json(state) for state in data['history']]
        return game
