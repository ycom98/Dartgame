"""The game-mode contract (M1-15). See docs/GAME_MODES.md.

A mode is the rules of one game. It owns a JSON-ready state dict and changes it only through these
methods; core.Game wraps any mode with the generic parts: undo (a snapshot stack), correcting a dart of
the current turn (replaying the turn), filling in missed darts, and the event-friendly snapshot.

Every state must contain these common fields (the server, controller and recorder read them):
  names    list of player names
  player   index of the player whose turn it is
  turn     turn counter, starting at 1, +1 on every next_turn
  darts    the current turn's darts, oldest first: {'value', 'multiplier', 'score', ...}; throw() appends one
  winner   None, or the index of the winning player (a team or ranking mode can add more fields)
Everything else is the mode's own (x01: scores, start, double_out, turn_start, bust).
"""
import copy


class GameMode:
    id = ''                 # registry key, e.g. 'x01', 'cricket'
    display_name = ''
    description = ''
    min_players = 2
    max_players = 4
    darts_per_turn = 3

    # ---- setup ---------------------------------------------------------------------------
    def validate_options(self, options):
        """Return the normalised options, or raise ValueError. options is a dict from the API."""
        if options not in (None, {}):
            raise ValueError(f'{self.display_name} has no options')
        return {}

    def new_state(self, names, options):
        """The state at the start of the game (names already validated by core.Game)."""
        raise NotImplementedError

    # ---- play ----------------------------------------------------------------------------
    def score_dart(self, state, value, multiplier):
        """The dart record to append for a board hit (value 0 = miss, 25 = bull). Modes may add fields
        (Cricket: marks; Killer: lives taken). The default scores value x multiplier."""
        return {'value': value, 'multiplier': multiplier, 'score': value * multiplier}

    def throw(self, state, value, multiplier):
        """Apply one dart (already validated as a board position) to state, in place: append the dart
        record to state['darts'] and update the mode's own fields (scores, marks, lives, winner...)."""
        raise NotImplementedError

    def turn_over(self, state):
        """True when no more darts may be thrown this turn (all darts thrown, bust, win, elimination...)."""
        return state['winner'] is not None or len(state['darts']) >= self.darts_per_turn

    def can_advance(self, state):
        """True when next_turn() is allowed (x01 also needs a bust or all three darts)."""
        return state['winner'] is None and self.turn_over(state)

    def next_turn(self, state):
        """Move to the next player in place (turn + 1, empty darts, mode's per-turn reset)."""
        state['player'] = (state['player'] + 1) % len(state['names'])
        state['darts'] = []
        state['turn'] += 1

    # ---- display -------------------------------------------------------------------------
    def presentation_hints(self, state):
        """Small dict the /play and /control renderers pick their layout from, e.g. {'kind': 'x01', 'start': 501}.
        It may carry per-mode display data (Cricket: marks per number; Killer: lives)."""
        return {'kind': self.id}

    # ---- persistence ---------------------------------------------------------------------
    def to_json(self, state):
        return copy.deepcopy(state)

    def from_json(self, data):
        for field in ('names', 'player', 'turn', 'darts', 'winner'):
            if field not in data:
                raise ValueError(f'Saved {self.id} game is missing {field}')
        return copy.deepcopy(data)
