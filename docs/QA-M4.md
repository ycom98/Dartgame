# QA: M4 camera tracking (M4-01, M4-02, M4-03)

Independent QA, 2026-11-05. Worktree `/home/user/qa-m4`, detached at `30c6213` (branch `m4-tracking`). Scope: `caddde5` (M4-01), `2f82013` (M4-02) and `30c6213` (M4-03) on top of main `68bacaf`. The baseline worktree was `/home/user/qa-m4-main` at `68bacaf`. I reran every number myself. My scripts, logs and screenshots are in `qa-artifacts/qa-m4/`:
- `e2e.py`, `race.py`, `ui.py`, `shot.cjs`, `probe_vision.py`
- the `*.txt` and `*.log` result files
- the `m4-*.png` screenshots

Interpreter: `/home/user/dart-room/.venv/bin/python` (OpenCV 4.14, NumPy 2.5), passed in as `DART_PYTHON`. The worktree has no `.venv` of its own.

## Verdict: **FAIL** (one HIGH: H1)

The normal path works, and the detection numbers reproduce exactly. In the normal path, the darts are tracked from the moment they land until they are pulled.

The failure is in recovery. After any mid-turn realignment, the camera proposes phantom darts. That realignment happens after a phone stream drop that recovers by itself, after a server restart, or after **Check / realign**. The phantom darts appear when the earlier darts are pulled out. They are the pulled darts' own scores, they are not flagged, and auto-commit records them for the **next player**. I reproduced this through the real server for both the restart path and the stream-drop path. The board also never registers as "cleared" afterwards, so the camera stays on a stale turn reference until someone presses the baseline button.

| Ticket | Verdict |
|---|---|
| M4-01 Multi-dart turn tracking | **FAIL** (H1, M1) |
| M4-02 Low confidence / no auto-commit | **PASS** (L4) |
| M4-03 Trial report + tuning kit | **PASS-WITH-NOTES** (M2, L1–L3) |

## 1. Suites

| Suite | Result |
|---|---|
| `scripts/test.sh py` | **259 tests OK** (2 skipped), 216 s |
| `scripts/test.sh browser` | **21 of 21 suites passed**, 9 min 4 s |

No browser suite failed, so I did not need to rerun one alone.

## 2. Held-out detection (ceiling-1.5ft, realistic, seeds 2+3, 50 turns × 3 scenarios = 900 darts)

I ran two jobs:
- M4 with `tools/eval_occlusion.py --tracking rolling`;
- main with its own `eval_occlusion.py` (reset after every dart, the developer's "before").

| Measure | Developer claim | QA rerun (M4) | Main baseline |
|---|---|---|---|
| Dart 2 exact / wrong / no proposal | 89.3% / 10.7% / 0.0% | **89.3% / 10.7% / 0.0%** | 85.3% / 9.3% / 5.3% |
| Dart 3 exact / wrong / no proposal | 80.7% / 15.7% / 3.7% | **80.7% / 15.7% / 3.7%** | 79.7% / 13.0% / 7.3% |
| Silent wrong (wrong and auto-committed), dart 2 | 2.0% | **2.0%** | 9.3% (nothing flagged) |
| Silent wrong, dart 3 | 4.3% | **4.3%** | 13.0% |
| Wrong darts 2–3 caught by a flag | 60 / 79 | **60 / 79** | — |
| False flags (right darts 2–3 flagged) | 21% (106/510) | **20.8% (106/510)** | — |
| Extra false darts | 4 of 900 | **4 of 900** (2 on dart 2, 2 on dart 3) | — |
| Board cleared after pulling | 300 / 300 | **300 / 300** | — |
| Dart 1 exact (clustered turns) | 95.3% | **95.3%** | 93.7% |

**Single-dart regression check.** `tools/run_detection_gate.py --pipelines current --mounts ceiling-1.5ft --seeds 2,3 --darts 200`:

| Profile | M4 | Main | Change |
|---|---|---|---|
| ideal | 98.0 / 97.0 → **97.5%** exact | 97.0 / 96.0 → 96.5% | +1.0 |
| realistic | 96.0 / 97.5 → **96.75%** exact | 94.0 / 96.5 → 95.25% | +1.5 |

The gain comes from fewer "none" results. Tip error is unchanged (median 0.90 / 0.98 mm). **No regression.**

**Caveat on the eval.** The harness scores darts on clean, step-wise scenes with no hand in front of the board, and it only pulls darts that the camera is tracking. It cannot see H1.

## 3. End-to-end through the real server (subprocess `server.py`, fake IP Webcam, sim ceiling-1.5ft 1280×720)

The script is `qa-artifacts/qa-m4/e2e.py` and its log is `e2e.log`. 44 checks passed and 2 failed; both failures are H1.

| Scenario | Result |
|---|---|
| 3 darts, auto-commit paused | 3 pending darts, oldest first (`T1, S16, S2`); `camera.pending` is the head; later darts have `queued: true` and `commit_in: null` |
| Accept dart 2 / correct dart 3 before dart 1 | **409** "Proposal changed…"; nothing recorded |
| Accept with a stale revision | **409** "Match changed…"; stale revision on throw, undo, next and fill_misses each **409** |
| Accept the head twice | 2nd **409** |
| Unpause auto-commit | dart 2 committed at 1.53 s, dart 3 at 3.05 s (delay 1.5 s): **each dart gets its own countdown** |
| Pull the darts one by one, then Next | `pulled 3`, `board_cleared 1`, no phantom darts |
| Flagged dart (tip behind an earlier dart) | `possibly hidden tip — check`, `confidence: low`, `needs_check: true`, still pending after 4 s (2.7× the delay); not in the game |
| Undo with a dart pending | 200; the pending dart is kept and can be accepted |
| **Restart mid-turn** (1 committed, 1 pending) | match restored byte-identical; the pending dart is dropped (the host must tap it, L4); **after Next, pulling the previous darts auto-committed `T1, S16` to the next player (H1)** |
| **Stream drop 6.5 s mid-turn** | Ready returns by itself ("board has not moved"); **after Next, pulling the darts auto-committed `T1, S16` to the next player (H1)** |
| Recalibrate with a dart pending | 200; pending darts dropped; the next dart is detected normally |
| Manual game; camera off | throw, undo, fill_misses and next all work with no 500s; `camera.pending_darts` is `[]` |
| Next while an old pending dart exists (`race.py`, 12 tries) | **1 of 12** committed the previous turn's dart to the next player (M1) |

**Recorded session.** I ran `tests/synthetic_session.py` with `--turns 9 --seed 4`. That gave 27 darts, 3 pile-up turns and a 64 MB recording.

`trial_report.py` took 18 s. Its output:
- `trial_report.md`: 85.2% exact, 0 false proposals, replay identical over 689 frames, landing-to-proposal median 0.20 s;
- 4 crops, each 484×286;
- `contact_sheet.png`, which is **2654×1484 (3.9 MP, 5.2 MB)**: larger than one 1280×720 frame (M2).

No video or full frame was copied.

**Hand fixes kept.** I edited a truth value and added `stacked` / `wire` tags. A rerun kept both and used them: the Stacked row became 2 darts, and throw 1 was listed with its tags.

`tune_params.py` took 8 min 39 s for 23 settings. Hold-out was 8 of 27 darts (30%). It printed "Best: change_threshold=24, 84.2% → 89.5% tuning, 87.5% → 87.5% hold-out". That result rests on one dart (L2).

## 4. Controller (390×844) and TV (1920×1080)

Screenshots are in `qa-artifacts/qa-m4/`.

**Three pending darts** (`m4-a-three-pending-control-390.png`):
- headline **"Camera: T1 (3) · then S16, S2"**;
- the head marker is solid, and the two later markers have `stroke-dasharray: 5px, 4px`.

**Flagged head** (`m4-b-flagged-head-control-390.png`):
- headline and detail are red `rgb(255,138,112)`: "Camera: Outer bull (25) · then S16" / "possibly hidden tip — check · waiting for Accept";
- the head marker is red and the queued marker is dashed gold;
- the dart was not committed after 3 s.

**Both pages:**
- no horizontal scroll (scrollWidth 390);
- the tap board does not move between the two states (top at 410 px);
- no page errors.

**TV** (`m4-*-tv-1080.png`): never shows a pending dart, no overflow, no page errors. `qa_tv_sizes`, `qa_presentation*` and the other TV suites all pass. **No TV regression.**

## 5. Code review notes (no defect)

- Commit order is enforced server-side, in `commit_camera_dart` (`server.py:546-551`), which compares against the head only. Taps (`replaces_proposal_id`) and auto-commit go through the same check.
- `CameraFlow.due()` skips `needs_check` darts. `view()` gives later darts `commit_in: null`. `promote()` restarts the countdown when a new head arrives.
- Each new game resets the turn reference (`reset_base_if_ready`). Recalibration and `invalidate` clear `pending` and `tracked`.
- Pending and tracked darts are cleared between games and between turns.
- A large still change is handled as specified. A half-covered frame keeps calibration and the pending dart. Board shifts of 4 px and 15 px invalidate the alignment ("Board or camera moved"), and a 1 px shift does not.
- Two blobs 20 mm or more apart become 2 darts (`together: 2`). A bounce-out is retracted.

## Defects

### H1 (HIGH): untracked darts become phantom darts when pulled; auto-committed to the next player

**Cause.** `align()` calls `reset_base()` (`vision.py:281` → `vision.py:348`). That makes the *current* board, with this turn's darts in it, the turn reference, and it empties `tracked`. `align()` runs on:
- stream-drop recovery (`board_recheck_loop` → `recheck_board`);
- a restart (`restore_calibration`);
- **Check / realign**.

Since M4, `/api/next` no longer resets the reference (`server.py:520-522`), and board clearing is only checked when something is tracked (`vision.py:399`, `vision.py:402`). So the holes left by pulled, untracked darts are segmented as new darts and proposed. They are proposed at the pulled darts' own scores, they are not flagged, and they are auto-committed.

**Second trigger.** The same thing happens to a dart that was scored by hand because the camera missed it (`absorb`, `vision.py:353-356`), when it is pulled on its own (`probe_vision.py` case 3).

**Steps to reproduce:**
1. Start a camera game.
2. Two camera darts land and are committed.
3. Stop the phone stream for about 6 s and let it come back. Ready returns by itself. (Or restart the server and verify.)
4. Throw dart 3, accept it, then press Next player.
5. Pull the darts one at a time.

**Result:** the next player gets `T1, S16` (the previous player's darts) by auto-commit (`e2e.log`). The vision counters show `board_cleared 0`.

Main also proposed a dart when one was pulled after Next. But main reset the reference on every commit and Next, and its proposal was recomputed every frame. M4 keeps phantom darts pending, queues up to 3 of them, and never recovers without the baseline button.

### M1 (MED): race at Next player can commit the previous turn's pending dart to the next player

**Cause.** `end_turn()` is queued asynchronously (`server.py:522`), but `CameraFlow` keeps the old head until the worker publishes. `auto_commit_once` (`server.py:568-578`) only checks `turn_over()`, which is false for the new turn. So a head older than the delay is committed into the new turn in that window.

**Steps to reproduce:**
1. A camera dart is committed.
2. Press **End turn · misses**.
3. A dart is still seen. It stays pending because the turn is over.
4. Wait more than the delay, then press Next.

**Result:** 1 of 12 tries put that dart on the next player (`race.py`).

The same asynchronous pattern existed in main. It matters more now that M4 keeps darts pending across frames. **Fix:** in `game_write`, drop the flow's pending darts synchronously on `/api/next`, or tag each pending dart with its turn.

### M2 (MED): `contact_sheet.png` is larger than a frame and grows without bound

**Location:** `tools/trial_report.py:122-125` (`make_sheet` draws a 240 px tile pair for **every** dart, 3 per row).

27 darts give 2654×1484 px, which is 4.3× the pixels of a 1280×720 frame, at 5.2 MB. A 2-hour trial (about 300 darts) would give a sheet about 25,000 px tall and about 55 MB, inside a folder that the README says to zip and send back.

It contains only crops, but it breaks the "nothing frame-sized in `report/`" rule. The developer's test (`tests/test_recording.py`) checks only `crops/`. **Fix:** split the sheet into pages, limit it to wrong, flagged or corrected darts, or downscale it.

**Steps to reproduce:** run `tests/synthetic_session.py OUT --turns 9`, then `tools/trial_report.py OUT`, then read the size of `report/contact_sheet.png`.

### L1 (LOW): the report embeds the local session path

**Location:** `tools/trial_report.py:201`.

The report reads "tune them … with `tools/tune_params.py /Users/<name>/dart-trial/session1`". This puts the owner's username and folder layout into the file that is sent off the Mac. Use the folder name only.

### L2 (LOW): `tune_params` names a "Best" from a one-dart gain while the hold-out is unchanged

**Location:** `tools/tune_params.py:156`.

It names a winner when the tuning share is higher at all, with no minimum count, and does not use the hold-out. It does print "adopt only if hold-out improves", but the "Best:" line reads like a recommendation.

A second issue at `tools/tune_params.py:100`: darts tagged `stacked` are silently excluded from tuning, and neither the docstring nor the README says so.

### L3 (LOW): long headline and notes are cut off at phone width

**Location:** `static/presentation.css:62-63` (headline `nowrap` with ellipsis; detail limited to 2 lines). Three long notes plus "waiting for Accept" overflow, and "· then …" can be cut off. Examples:
- "Camera: Outer bull (25) · then Outer bull, Outer bull";
- `possibly hidden tip — check · seen in pieces … — check · tip direction unclear — check · near a wire …`.

**Pre-existing (not M4):** at 390 px in-game, the 118 px camera panel (`presentation.css:80`) clips the bottom of the Accept / Pause buttons (visible in both `m4-*-control-390.png`).

### L4 (LOW): the pending dart is lost on restart, and the host's tap then goes to the wrong dart

After a restart mid-turn, the pending dart is gone. Its pixels are in the new reference, so it is never proposed again.

If dart 3 is then proposed, the host's tap for the lost dart 2 replaces dart 3's proposal instead, because a tap always corrects the head. That needs two taps, though the values still come out right. This is not documented in the README "Known limits".

## Run notes

- I made no edits outside `docs/QA-M4.md` and `qa-artifacts/qa-m4/`.
- The baseline worktree `/home/user/qa-m4-main` is left in place.

---

## Re-check (2026-11-05, `27dd912`)

I re-checked the four fix commits: `f509382` (H1), `6faa5af` (M1), `ca7a6af` (M2, L1, L2) and `27dd912` (L3, L4, checklist). I used the same worktree and interpreter as before. The new scripts and logs are in `qa-artifacts/qa-m4/`: `e2e2.py`, `race2.py`, `probe2.py`, `probe3.py`, `recheck-*.log`, `recheck-*.md` and `recheck-*.png`.

### Re-check verdict: **FAIL** (H1 is still open on the restart path; one new MED)

| Item | Status |
|---|---|
| H1 stream drop | **Fixed.** The turn is kept through the drop; pulling the darts adds no darts. |
| H1 Check / realign (board not moved) | **Fixed.** Checked through the real server (`/api/align`, then Next, then pull) and in a unit probe. |
| H1 hand-scored dart pulled on its own | **Fixed.** It is not proposed ("A dart was pulled out"). |
| H1 restart mid-turn, darts pulled first to last | **Fixed.** |
| H1 restart mid-turn, **last dart pulled first** | **NOT FIXED** (H1b below) |
| H1 calibrated with darts in the board | Documented precondition. The failure mode is bad (M3 below). |
| M1 Next race | **Fixed.** 0 of 32 tries leaked, with a pending dart at every Next. |
| M2 sheet size | **Fixed.** 62-dart session: sheet 1258×461 (0.63 of a frame). The cap with 62 labels forced in is 20 panels at 1258×612 (0.84 of a frame). Crops are 484×286. The report folder is 2.5 MB, with no video or frames. |
| L1 local path | **Fixed.** The report shows `tools/tune_params.py session_long` only. |
| L2 tuning advice | **Fixed.** Same session as before: "Keep the current values: change_threshold=24 scored better on the tuning darts … but not on the hold-out darts". The `stacked` exclusion is printed and documented. |
| L3 phone text | **Fixed.** See the 390 px screenshots below. |
| L4 | **Documented** in the README and the checklist. |

### Suites

| Suite | Result |
|---|---|
| `scripts/test.sh py` | **264 tests OK** (2 skipped), 228 s |
| `scripts/test.sh browser` | **21 of 21 suites passed** |

### Detection spot-check

`eval_occlusion --tracking rolling` (ceiling-1.5ft, realistic, seeds 2+3, 900 darts) gave the same numbers as before:

| Measure | Result |
|---|---|
| Dart 1 exact | 95.3% |
| Dart 2 exact / wrong / no proposal | 89.3% / 10.7% / 0% |
| Dart 3 exact / wrong / no proposal | 80.7% / 15.7% / 3.7% |
| Silent wrong, dart 2 / dart 3 | 2.0% / 4.3% |
| False flags (right darts 2–3 flagged) | 106 / 510 |
| Extra false darts | 4 |
| Board cleared after pulling | 300 / 300 |

The only per-record difference from the first run is the reason text: `tip may be hidden` instead of `possibly hidden tip — check` (see L5).

The single-dart gate gave 96.0% and 97.5% exact, the same as before.

### End-to-end (`e2e2.py`, real server subprocess, fake IP Webcam)

47 of 48 checks passed. These now pass:
- stream drop → Next → pull;
- Check/realign → Next → pull;
- restart → pull dart 1 first.

All of the first round's checks pass again. The one failure is H1b.

### Screenshots (390×844)

**`recheck-a-three-pending-control-390.png`**
- headline "Camera: T1 (3) · +2 waiting"; detail "waiting for Accept · check: near a wire";
- 1 solid marker and 2 dashed markers.

**`recheck-b-flagged-head-control-390.png`**
- red headline "Camera: S3 (3) · +1 waiting"; detail "waiting for Accept · check: tip unclear, tip may be hidden";
- red head marker and dashed queued marker;
- the dart is still pending after 3 s.

**Both:**
- Accept and Pause are now fully inside the 128 px panel;
- no horizontal scroll and no page errors;
- the TV never shows a pending dart.

### Defects still open or new

**H1b (HIGH, still open): after a restart, pulling the last dart first poisons the "empty board" and the earlier darts come back as phantom darts**

**Cause.** After a restart (or a realign where the board moved), `reset_base()` makes the board with darts 1–2 in it the turn reference, and those darts are untracked (`vision.py:300`). Dart 3 is then tracked.

When dart 3 is pulled first, the board matches `turn_base` again. `board_cleared()` reports a clear (`vision.py:560-566`) and stores that frame, with darts 1–2 still in it, as `self.empty`. `without_holes()` then compares against this wrong empty board, so pulling darts 1 and 2 is proposed as `T1` and `S16`. They are not flagged, and auto-commit records them for the next player.

**Steps to reproduce** (`e2e2.py` section 6d; `probe3.py` reproduces it on clean and on noisy frames):
1. Start a camera game.
2. Darts 1 and 2 are auto-committed.
3. Restart the server and verify.
4. Dart 3 is committed. Press Next.
5. Pull dart 3, then dart 2, then dart 1.

**Result:** the next player gets `['T1', 'S16']`.

**Fix direction:** only refresh `empty` from a clear that was matched against the empty board, not against `turn_base`. Or treat `turn_base` as known-empty only when it came from a verified clear or from calibration.

**M3 (MED, new): calibrating with darts in the board makes the camera drop real darts and invent phantom ones, and the baseline button does not recover**

The calibration image becomes `empty` (`vision.py:243`, `vision.py:370`).

**Steps to reproduce** (`probe2.py` "C", clean and noisy):
1. Calibrate with 2 darts in the board.
2. Throw, commit and pull the darts.

**Result:**
- Pulling the calibration-time darts proposes them as `T1` and `S16`.
- After **Set baseline** on an empty board, a real dart landing where a calibration-time dart was is silently dropped as a "hole" (no proposal).
- Pulling that dart then proposes a phantom `T1`.
- Only a recalibration recovers.

The README and checklist now say to calibrate on an empty board, but nothing checks it. **Fix direction:** warn at calibration if the image differs from a board model, or let a baseline taken on a visibly empty board refresh `empty`.

**L5 (LOW, new): the reason text was renamed**

The ticket's flag text is "possibly hidden tip — check". The camera now sends `tip may be hidden`, and the controller shows it as "check: tip may be hidden". The meaning is the same, and the docs were updated, but it deviates from the ticket wording. The eval JSON committed earlier (`qa-artifacts/M4-occlusion.json`) still has the old strings.

### Diff review (`30c6213..27dd912`): other notes, no defect

- `drop_pending()` now runs under the game lock, and `is_head()` is re-checked under the lock in `commit_camera_dart`. This closes M1.
- `invalidate()` now suspends the turn and `align()` restores it when the board has not moved. A real board move, or a new calibration, still starts a new turn.
- `end_turn()` also dismisses pending darts in a suspended turn.
- `recorder.py` saves `empty.png` and the replay restores it. The replay stays identical (covered by the tests).
- In the 62-dart synthetic session, 10 "false proposals" are counted. I traced all 10: they are darts thrown after a bust and dropped at Next, which the report counts as described. They are not a defect.

---

## Re-check 2 (2026-11-05, `622ee60`)

Scope: `b4bf710` (H1b), `7086276` (M3) and `622ee60` (L5). The new scripts and logs are in `qa-artifacts/qa-m4/`: `e2e2.py` (now with sections 6e and 6f), `probe4.py`, `probe_warn.py` and `recheck2-e2e.log`.

### Re-check 2 verdict: **PASS-WITH-NOTES** (no HIGH open; fix M4 before the board-day trial)

| Item | Status |
|---|---|
| H1b: restart, then the last dart pulled first | **Fixed.** `e2e2.py` 6d passes; `probe3.py` is clean on clean and noisy frames (2 clears, no proposals). |
| Restart **twice** in one turn, darts pulled 3, 2, 1 (`probe4.py` A) | **OK.** No proposals, 2 clears, and the next turn's dart is detected. |
| All earlier H1 paths (stream drop, Check/realign, hand-scored pull, restart) | **OK.** |
| M1 Next race | **OK.** No code change since the last re-check; the e2e passes. |
| M3: warning when calibrating with darts in | **Fixed** (see the table below). |
| M3: documented recovery (pull the darts, then **Board clear · reset image**) | **Works** (`probe4.py` D). The next dart at a calibration-time dart's spot is proposed, and the pull clears the board. |
| L5 wording | **Fixed** in the docs. |

**Calibration warning** (`probe_warn.py`): 6 empty boards and 6 random single darts per cell, 1280×720, with random exposure.

| Mount | Profile | Empty board warns | Empty max marks | One dart warns | One dart min marks |
|---|---|---|---|---|---|
| ceiling-1.5ft | realistic | **0 / 6** | 0.0 mm² | **6 / 6** | 35.3 mm² |
| ceiling-1.5ft | realistic+shadow | **0 / 6** | 0.0 mm² | **6 / 6** | 59.5 mm² |
| ceiling-0.5ft | realistic, realistic+shadow | 0 / 6 | 22.5 mm² | 6 / 6 | — |
| ceiling-2ft | realistic, realistic+shadow | 0 / 6 | 0.0 mm² | 6 / 6 | — |
| ceiling-3ft | realistic, realistic+shadow | 0 / 6 | 0.0 mm² | 6 / 6 | — |
| left | realistic | 0 / 6 | — | 5 / 6 | — |

Through the server (`e2e2.py` 6f), calibrating with 2 darts in returns "The board does not look empty…", and calibrating on an empty board does not.

The margins are thin:
- ceiling-0.5ft empty boards reach 22.5 mm² against the 30 mm² limit;
- the smallest single dart at ceiling-1.5ft was 35.3 mm².

Real boards with wear or logos need checking; both values are marked REAL DATA in `vision_tuning.py`.

### Suites and numbers

| Check | Result |
|---|---|
| `scripts/test.sh py` | **267 tests OK** (2 skipped) |
| `scripts/test.sh browser`, full run | 20 of 21 passed: `qa_setup_steps.cjs` failed |
| `qa_setup_steps.cjs` alone | **passed 3 of 3** |
| `e2e2.py` | **50 of 51** checks passed |
| Detection | `eval_occlusion --tracking rolling` (ceiling-1.5ft, realistic, seeds 2+3): **0 of 900 records differ** from the re-check 1 run, so the numbers are unchanged |

The `qa_setup_steps.cjs` failure in the full run was a server-side `BrokenPipeError` on a GET, which the suite counts as a page error. It is a flake that nothing in this diff caused.

The one failing `e2e2.py` check is M4 below.

### New defects

**M4 (MED): "Board clear · reset image" pressed with darts still in the board poisons the empty board; it is saved to disk and gives phantom darts later**

**Cause.** `board_is_empty()` (`vision.py:407-411`, called from `/api/baseline` at `server.py:405`) sets `self.empty = self.base` without any check. `save_calibration()` then writes it to `empty.png`, so it survives restarts.

Pulling those darts later is not recognised as a pull. They are proposed at their own scores and auto-committed. A real dart landing at a poisoned spot is silently dropped.

**Steps to reproduce** (`e2e2.py` 6e, real server; `probe4.py` B and C, clean and noisy):
1. Two darts are auto-committed.
2. Press Board clear with them still in the board.
3. Restart the server and verify.
4. Dart 3 is committed. Press Next.
5. Pull the darts.

**Result:** the next player gets `['T1', 'S16']`.

**Why MED and not HIGH:** the button says the board is clear. But the setup-page help text tells the host to use it "if it gets confused", and a confused camera is often mid-turn with darts in the board.

**Fix:** run `board_marks_mm2()` in `board_is_empty()`. When the board does not look empty, refuse to update `empty` (still reset the turn), or warn the way calibration does.

**L6 (LOW, docs): the README "Play" steps 2–5 are stale.** They still describe one dart at a time and say "Darts removed · Next player … captures the new baseline" and "undo resets the image baseline". Since M4, Next and Undo do not touch the camera reference, and pulling the darts starts the next turn.

### Diff review (`27dd912..622ee60`): other notes, no defect

- `board_cleared()` now refreshes `empty` only when the match was against the empty board. This is the correct H1b fix: a turn reference is never promoted.
- `empty.png` is saved with the calibration on calibrate, align, verify and baseline, and loaded on restart. A missing file falls back to the calibration image.
- `board_marks_mm2()` runs only at calibrate time (one pass of about 60 cells), so it adds no per-frame cost.
- `board_is_empty` is logged as a vision action. The replay test still passes.

### Still open from earlier

- **L4** (documented only).
- The **M3 failure mode** when the warning is ignored.

## Re-check 3 (not completed)

The owner asked to publish before this re-check finished. QA had already captured screenshots of the new Board-clear warning (`qa-artifacts/qa-m4/recheck3-*.png`). It had not run the full suites, `probe4.py` or the diff review on `622ee60..a015cd2`.

At `a015cd2` the developer reports 268 Python tests passing (2 skipped) and 21 of 21 browser suites passing. QA has not independently verified that the M4 and L6 fixes work. The last completed QA verdict is Re-check 2 at `622ee60`: **PASS-WITH-NOTES**, with no High defects open.
