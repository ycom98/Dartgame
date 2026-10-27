# QA recheck: the fixes for QA-M1-10-11-12-14, and M1-15

Tester: independent QA agent. Worktree `/home/user/qa-m1e`, detached at `fd363fd`. Commits reviewed: `44e21ec` (M1-15) and `fd363fd` (QA fixes). Diff reviewed: `9649684..fd363fd`.

The probes are in the scratchpad under `qa2/` (`tap2.cjs`, `shift.cjs`, `cam.cjs`, `rec.py`, `q4.py`, `fuzz.py`). None of them are committed.

## Verdicts

| Item | Verdict |
|---|---|
| Suites | **PASS.** Python 173/173. Browser 16/17; the only failure is the known `qa_presentation.cjs` "Maya" timeout. |
| Q1: tap board shows one score, records another | **PASS.** One residual layout shift in camera games (R1). |
| Q2: recorder write failure counts darts twice | **PASS** |
| Q3: frame writer dies silently | **PASS** |
| Q4: flickering label never auto-commits | **PASS** |
| Lows (Q5) | **PASS.** Two leftovers, both Low (R2, R3). |
| M1-15: game-mode interface | **PASS** |
| New regression tests fail on the old code | **PASS** |
| Code review of `9649684..fd363fd` | 1 Medium, 3 Low. No High. |

## Evidence

### Q1: tap board

**Geometry probe (`tap2.cjs`).** It compares the drawn region with the element under each point, on a 0.5-unit grid of about 496k points, for the new radii.
- 360×740 (touch) and 1280×800: **0.003 % mismatch** in both.
- All 16 mismatched points lie on the outer-bull edge (r ≈ 40.5). There, the 0.8-unit wire stroke is drawn over the next region, which is under 0.4 px. In effect, 0 %.
- No point on the visible board records nothing.

**Real taps.** 15 per viewport: touch at 360 px, mouse on desktop. Each point was 1 unit inside each side of every ring wire (r = 15, 17, 39, 41, 99, 101, 131, 133, 169, 171, 203) and 1° from the radial wires. **0 wrong.**

**Within a manual turn, the board does not move** (`shift.cjs`): 0, 1, 2 and 3 darts, bust, and a remote update.
- The "Match updated" notice is now fixed at the bottom of the screen, so it no longer pushes the board down.
- The board moves 32 px only when the turn passes to the next player: the `#prompt` height changes from 63 to 31 px. Low.

**`/play` and `/control`:**
- `/play` shows "LIVE · CAMERA SCORING" in camera games. Confirmed in the diff (`presentation.js`).
- The compact phone status is covered by `qa_tap_board`: the scoreboard is hidden and the page is under 2,400 px tall.

### Q2 and Q3: recorder failures (`rec.py`, a real `Recorder` wired like `start_recording`)

**Disk full (ENOSPC) and unplugged drive (EIO) on `events.jsonl`, manual throw:**
- The dart is recorded once and the reply succeeds.
- The revision goes 0 → 1, once.
- The recorder becomes inactive, and `error` reads "could not write events.jsonl ([Errno 28]…)".
- The listener is unhooked.
- The host's retry with the old revision gets 409, so there is still 1 dart.
- The game continues (throw, then undo).
- `stop()` twice after the failure: no exception.

**Other recorder cases:**
- **Failing write inside `stop()`:** the recorder still stops and unhooks, and `stopped_at` is written to `session.json`.
- **Auto-commit with a failing recorder** (the old `autoloop` case): darts **[60]**, revision 1. Before the fix this gave [60, 60, 60].
- **Frame writer raises EIO (Q3):** `status()` reports `active: False` with error "frame writer failed…", and the writer thread has exited.

### Q4: flickering label (`q4.py`)

**Auto-commit:**
- The label flips S20 ↔ S1 every 0.3 s, and the tip moves 1 mm. The auto-commit delay is 0.5 s.
- Result: **1 commit after 0.91 s** (the countdown restarted once), with `label_changes` 2. No second commit in the next 1.5 s.

**Proposal id and Accept:**
- **Proposal id:** the id stays the same when the label flips. A dart 23 mm away gets a new id.
- **Accept with a stale value:** Accept carrying `label: "S20"` while the camera reads S1 → 409 "The camera now reads S1, not S20. Check the dart." No dart is recorded and the revision does not change.
- **Bad `label` type:** 5, a list or an object → 400.
- `control.js:60` and `setup.js` both send the label.

### Lows (Q5)

All fixed:
- **Undo while a camera dart is pending:** the dart is kept, because the base is not reset (`server.py:341`).
- **After a bust, win or third dart:** the pending chip shows "turn over" instead of the stuck countdown (`view(turn_over)`).
- **Free-disk check:** it now measures the recording folder (`free_disk_bytes` uses `recorder.free_bytes()`).
- **Disk-guard stop:** the listener is unhooked (`on_stop`).
- **`CameraFlow.closed`:** cleared when the base changes.
- **`eval_detection.py`:** the stub message is updated.
- **`make_labels.py`:** the docstring explains `detection_label`.

### M1-15: game-mode interface

**Golden file.** I ran `make_x01_golden.py` against `core.py` from `9649684` (before the refactor). Its output is **byte-identical** to the committed `tests/golden/x01_states.json`.

**Differential fuzz (`fuzz.py`).** It compares the old `core.Game` with the new one:
- 3,000 random games, 186k actions: throw, next, undo, fill misses, correct with invalid indexes, bust, and double out.
- **0 mismatches** in snapshots (ignoring the new `mode` field), full undo history and error messages.

**Interface (`docs/GAME_MODES.md`, `modes/base.py`).** The interface is sound for Cricket and the party games:
- Each mode keeps its own state, and every mode shares the same common fields.
- Correct and fill misses are generic: they replay the turn and stop when the mode's `turn_over()` says so.
- Killer can skip eliminated players in `next_turn`.
- The doc lists its known limits honestly: the renderers and `control.js` turn logic are still x01-only.

**No regressions in camera, undo, bust or win.** `qa_camera_controller`, the `qa_manual_*` suites and `test_correct` all pass, and so do the fuzz results above.

### The new regression tests fail on the old code

I ran them in a throwaway worktree, `/home/user/qa-old` at `2dbee46`, and removed it afterwards.
- `tests/test_qa_m1d_fixes.py`: **all 8 tests fail** (7 failures, 3 errors).
- `tests/qa_tap_board.cjs`: the new "visible board = recorded score" check fails (1873/1873 points), and so does the compact-status check.

## Defects

### R1 — Medium. In camera games, the tap board moves when the pending-dart text changes.

- **Where:** `static/presentation.css:27-29` (`.camera-panel`, `.pending-row` with `flex-wrap`, and no fixed height), filled in by `static/control.js:107-119`.
- **Measured at 360 px** with the real CSS (`cam.cjs`). The board top is:

  | State | Board top |
  |---|---|
  | "waiting for a dart" | 648 px |
  | A proposal, with the Accept button shown | 732 px (**+84 px**) |
  | "near a wire, check it · value changed, check it" added | 750 px (+18 px more) |

- **Why it matters:** the +18 px shift happens mid-countdown on exactly the near-wire darts that Q4 targets, while the host is reaching to tap a correction. The fix comment "nothing above the tap board changes height during a turn" is true only for manual games.
- **Fix:** give the camera panel a fixed height, with the pending text on one line and ellipsis. Or reserve the Accept button's space so it is always laid out, and put the "near wire / value changed" note in a fixed-height line.

### R2 — Low. The board moves 32 px when the turn passes to the next player.

- **Where:** the `#prompt` height changes from 63 to 31 px between the turn-over prompt and the new-turn prompt (`shift.cjs`), at 360 px and at 1280 px.
- **Fix:** give `#prompt` a `min-height`.

### R3 — Low. The recorder error log says "Recording stopped: Recording stopped: …".

- **Where:** `recorder.py:134` adds the prefix to a reason that already starts with it (`recorder.py:197`, `recorder.py:299`). Cosmetic, console only.

### R4 — Low. A recorder failure inside a game write can hold `game_lock` for up to 5 s.

- **Where:** `recorder.fail()` → `finish()` joins the writer thread for up to 5 s, then writes `session.json`. When that happens from `EventLog.add`, the caller is inside `app.game_lock` (`server.py:337`, `recorder.py:144-155`).
- **When it hurts:** on a drive that hangs instead of returning an error, game writes and `/api/state` stall for up to 5 s.
- This was already the case before these commits; it is not a regression.
- **Fix:** run `fail()` on a separate thread, as the disk guard already does.

### Note — `/api/throw {proposal_id}` with no `label` still commits whatever the camera reads now.

Both UIs send the label, so this only affects API callers. Acceptable.

## Safe to push

**Yes.** All High and Medium defects from the last report are fixed and checked with fresh probes. M1-15 behaves exactly like the old x01 code. R1 is a Medium UX issue limited to camera games: it records the score where the host taps, it just moves the target. It should be fixed next, but it does not block the push.
