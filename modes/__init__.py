"""Registered game modes (M1-15). A new game is a GameMode subclass registered here; the server and
core.Game need no changes. See docs/GAME_MODES.md."""
from .base import GameMode
from .x01 import X01

MODES = {}


def register(mode):
    """Add a mode instance to the registry (tests register their own)."""
    if not isinstance(mode, GameMode) or not mode.id:
        raise ValueError('register a GameMode instance with an id')
    MODES[mode.id] = mode
    return mode


def unregister(mode_id):
    MODES.pop(mode_id, None)


def get(mode_id):
    try:
        return MODES[mode_id]
    except (KeyError, TypeError):
        raise ValueError('Unknown game mode: ' + str(mode_id)) from None


def catalog():
    """Metadata for a game-selection screen."""
    return [{'id': m.id, 'display_name': m.display_name, 'description': m.description,
             'min_players': m.min_players, 'max_players': m.max_players} for m in MODES.values()]


register(X01())
