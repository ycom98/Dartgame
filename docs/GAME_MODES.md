# Game modes

M1-15 interface. A game is a `GameMode` subclass in `modes/`, registered in `modes/__init__.py`. Nothing else changes for a new game:
- **Server:** `/api/game {mode, options}` creates the game; throw, next, undo, correct, fill misses, camera commits and the event log all work unchanged.
- **Persistence (M1-16):** `Game.to_json()` / `Game.from_json()` save and restore the match.
- **Labels and recording:** `tools/make_labels.py` and the recorder read only the common fields.

x01 (301/501) is the first mode. Its rules moved unchanged from `core.Game` to `modes/x01.py`, and `tests/golden/x01_states.json` checks this: a pre-refactor recording of every snapshot and undo-history length.

## Who does what

| | `core.Game` (generic, every mode) | `GameMode` (rules of one game) |
|---|---|---|
| Setup | Validates player names; looks up the mode | `validate_options(options)` returns normalised options; `new_state(names, options)` |
| A dart | Checks it is a board position (0–20 or 25; ×1/×2/×3; no T25); refuses it if `turn_over()`; saves an undo snapshot; marks filled misses | `throw(state, value, multiplier)` appends the dart record (`score_dart()`) to `state['darts']` and applies the rules |
| End of turn | Refuses `next` after a win, or unless `can_advance()`; undo snapshot | `turn_over(state)`: no more darts this turn (3 thrown, bust, win, elimination…). `can_advance(state)`. `next_turn(state)`: next player and per-turn reset (skipping eliminated players, for example) |
| Win | — | Sets `state['winner']` |
| Undo | Snapshot stack (`history`) | — |
| Correct dart *i* of this turn | Replays the turn from its start state with dart *i* replaced (one undo step; drops later darts if the turn now ends earlier) | Nothing extra: replay just calls `throw()` |
| Missed darts | `fill_misses()` throws misses until `turn_over()` | Nothing extra |
| Display | `/api/state` carries `game` (the snapshot plus `mode`) and `display` | `presentation_hints(state)`: `{kind, …}` plus any per-mode data the renderers need |
| Save | `to_json()` / `from_json()` with mode, options, state and history | `to_json(state)` / `from_json(data)`: default deep copy; override for a schema change |

**Common state fields.** Every mode's state has `names`, `player`, `turn` (+1 per `next_turn`), `darts` (this turn's darts, each `{value, multiplier, score, …}`) and `winner`. The controller, the camera flow, the recorder and the label tools read only these. Everything else belongs to the mode; for x01 that is `scores`, `start`, `double_out`, `turn_start` and `bust`.

**Per-dart input is always (value, multiplier).** The tap board, keypad and camera all produce it, so no input path changes per game. A mode decides what a hit means: x01 subtracts points, Cricket adds marks, Killer takes lives.

## How Cricket maps onto it (sketch; not implemented)

- **Options:** `{"cut_throat": false}`, plus perhaps `{"points": true}` for no-points Cricket.
- **State:** the common fields, plus `marks: [{15: 0, …, 20: 0, 25: 0} per player]`, `points: [0, …]` and `round`.
- **`score_dart`:** `{value, multiplier, marks: multiplier if value in 15–20 or 25 else 0, score: points scored}`. Bull: 25 counts 1 mark and 50 counts 2.
- **`throw`:** add marks up to 3 on that number. Marks past 3 score `value × extra` while any opponent has the number open (cut-throat: add the points to the opponents instead). The player wins when all seven numbers are closed and they lead on points (cut-throat: fewest points). A miss or a 1–14 adds a dart with 0 marks.
- **`turn_over`:** win or 3 darts (the base default). `next_turn`: base default.
- **`presentation_hints`:** `{"kind": "cricket", "numbers": [20, 19, 18, 17, 16, 15, 25], "marks": …, "points": …, "closed_by_all": [...]}`. `/play` and `/control` pick a marks-grid renderer by `kind` (M3).
- **Corrections, undo, filled misses, camera commits, saving:** inherited unchanged.

## The party games

| Game | State beyond the common fields | Fits through |
|---|---|---|
| Around the Clock | `target: [1 per player]` (1→20→bull) | `throw`: a hit on the player's target advances it (option: doubles/trebles skip ahead) |
| Shanghai | `round`, `points` | Target = round number (1–7 or 1–20); `throw` scores only that number; `turn_over` = 3 darts; single + double + treble of the target in one turn wins at once ("Shanghai") |
| Killer | `number: [...]`, `lives: [...]`, `killer: [bool]`, `eliminated` | Numbers are chosen in a first round or passed as `options`. Hitting your own double makes you a killer; a killer's hits on others' doubles take lives. `next_turn` skips eliminated players. Last player standing wins. Display: lives |
| Snakes & Ladders | `position: [...]`, the board map in `options` | `score_dart` maps the hit to steps; `throw` moves and applies snakes and ladders; win at the last square. Display: positions for an overlay renderer |

## Known limits of the interface

- One player at a time, turns in seat order. A mode can skip players in `next_turn` but cannot run simultaneous turns. Teams would need a `teams` option with the turn order kept in state.
- Correction is limited to the current turn, the same as for x01 (owner decision #6).
- The `/play` and `/control` renderers are still x01-only (M3: per-mode renderers chosen by `display.kind`). The controller's turn logic still reads x01's `bust`. A new mode works through the API now, and on screen once its renderer exists.
