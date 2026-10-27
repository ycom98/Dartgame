"""Writes tests/golden/x01_states.json: x01 game snapshots and history lengths after every step of two scripts.

Generated from core.Game *before* the M1-15 game-mode refactor (commit 9649684); tests/test_modes.py checks
the refactored game reproduces it exactly (plus the new 'mode' field). Do not regenerate after the refactor.
  .venv/bin/python -B tests/golden/make_x01_golden.py > tests/golden/x01_states.json
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import Game
SCRIPT = [('game', ['Kapil', 'Aita', 'Sam'], 301, True), ('throw', 20, 3), ('throw', 19, 3), ('throw', 25, 2),
          ('next',), ('throw', 0, 1), ('throw', 5, 1), ('undo',), ('throw', 20, 1), ('throw', 20, 2), ('next',),
          ('throw', 20, 3), ('fill',), ('correct', 1, 1, 3), ('next',), ('throw', 20, 3), ('throw', 20, 3),
          ('throw', 19, 3), ('next',), ('throw', 18, 3), ('throw', 19, 1), ('throw', 1, 2), ('next',),
          ('throw', 0, 1), ('throw', 0, 1), ('throw', 0, 1), ('next',), ('throw', 20, 1), ('throw', 1, 1), ('throw', 0, 1),
          ('next',), ('throw', 17, 1), ('throw', 2, 2)]
SCRIPT2 = [('game', ['A', 'B'], 301, False),
           ('throw', 20, 3), ('throw', 20, 3), ('throw', 20, 3), ('next',),
           ('throw', 1, 1), ('throw', 1, 1), ('throw', 1, 1), ('next',),
           ('throw', 20, 3), ('throw', 20, 3), ('throw', 5, 1), ('next',),
           ('throw', 5, 1), ('fill',), ('next',),
           ('throw', 20, 3), ('undo',), ('throw', 19, 1), ('throw', 1, 1), ('throw', 0, 1), ('next',),
           ('fill',), ('next',),
           ('throw', 20, 3), ('throw', 20, 2), ('throw', 1, 1), ('correct', 2, 2, 1), ('correct', 2, 1, 1), ('undo',), ('undo',)]
def play(script):
    out = []
    for step in script:
        if step[0] == 'game': g = Game(step[1], step[2], step[3])
        elif step[0] == 'throw': g.throw(step[1], step[2])
        elif step[0] == 'next': g.next_turn()
        elif step[0] == 'undo': g.undo()
        elif step[0] == 'fill': g.fill_misses()
        elif step[0] == 'correct': g.correct(*step[1:])
        out.append({'step': list(step), 'snapshot': g.snapshot(), 'history': len(g.history)})
    return out
if __name__ == '__main__':
    print(json.dumps({'runs': [play(SCRIPT), play(SCRIPT2)]}, indent=1))
