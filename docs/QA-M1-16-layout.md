# QA: f142120 "Controller layout fixes" + 7d05376 "M1-16: Save the match to disk"

Worktree `/home/user/qa-m1f` at 7d05376. All results rerun here (2026-10-27). Probe scripts: scratchpad `m1f/persist.py`, `m1f/ov.py`, `m1f/lat.py`, `m1f/layout.cjs`.

## Verdicts

| Item | Verdict |
|---|---|
| Python suite | **PASS** 180/180 (`scripts/test.sh py`). One run made at the same time as my kill-9 probe failed the 20 ms p95 test (162 ms under heavy fsync load), so the test depends on load. |
| Browser suite | **PASS** 16/17. The only failure is the known `qa_presentation.cjs` "Maya" failure. |
| R1/R2: tap board does not move (360 and 390 px, camera and manual) | **PASS.** The board's top and height stayed the same for the proposal, "near a wire", "value changed", "waiting for Accept", commit, turn end, "turn over" with a 4th pending dart, chip selection, handoff, and the next player's dart. No horizontal scroll. |
| R3: message prefix | **PASS.** `fail()` adds "Recording stopped: " once (recorder.py:133), and no caller passes it in. |
| R4: a hanging drive cannot stall the API | **PASS.** With recorder writes and flushes that hang for 30 s, `/api/throw` took ≤0.61 ms and `game_state` ≤0.08 ms. `stop()` blocks only its own caller, for 5 s. |
| Labels | **PASS.** `/control` shows "CAMERA SCORING · TAP TO CORRECT" in camera games and "MANUAL SCORE ENTRY" in manual ones. The `/play` footer and connection text follow `camera_game`. |
| 3 correction chips at turn end | **PASS.** All 3 chips are fully inside the viewport at 360 and 390 px. Tapping chip 3 and then Miss corrected dart 3 to 0. |
| M1-16 kill -9 mid-turn (manual, 2 darts) | **PASS.** Game and revision are identical after restart. Undo works across the restart, and undoing past the start gives a clean 400. |
| M1-16 kill -9 right after a camera auto-commit | **PASS.** The state is identical. After the restart the same dart is not committed a second time. |
| Atomic save | **PASS.** I killed the server with kill -9 at 12 different moments during a stream of throws and undos: the file was readable 12/12 times, no `.tmp` file was left, and the match resumed each time. The save writes a temp file, fsyncs it and calls `os.replace`. |
| Corrupt or truncated file | **PARTIAL** (D1). Truncated, empty, binary, schema 2 and unknown mode all give a clean start, the file kept as `match.corrupt-*.json`, and a clear WARNING. A file that is valid JSON with the wrong shape crashes startup. |
| `--fresh`, `--state-file`, `DART_STATE_FILE` | **PASS.** `--fresh` starts empty and keeps the old file as `match.previous-*`. Tests never create `.local/state`: I ran `unittest discover` with `DART_STATE_FILE` unset and the browser suite, and `.local` does not exist afterwards. |
| Calibration restore needs a re-check and one Verify | **PASS, with D2.** Same scene → `review_overlay`, `verified=false`. Camera commits and Next stay blocked until Verify. Top/bottom mount or a different resolution → `needs_alignment` with a clear message. The overlay is never trusted without a tap, but see D2. |
| Save latency p95 ≤20 ms | **PASS.** 266 history entries (67 KB): p50 7.8 ms, p95 14.7 ms, max 36 ms. |
| Secrets | **PASS.** The state folder (`match.json`, `calibration.json`, `reference.png`) contains no token and no camera password. Path-traversal GETs for `.local/state` return 401. The file is mode 0644 in the repo folder, which is acceptable for a home LAN app. |

## Defects

**D1 (Medium): some corrupt save files stop the server from starting.**
- **Where:** persistence.py:52, :58, :69.
- **What happens:** `load()` catches only `OSError`, `ValueError`, `KeyError` and `TypeError`.
  - A file containing `[]` or `null` raises `AttributeError` at `payload.get`.
  - A game with `player` out of range raises `IndexError` at line 69.
  - In both cases the server exits with a traceback, and it stays down until the user finds and deletes the file. That breaks "corrupt file → clean start".
  - A state missing `scores` loads without complaint, so it may fail later.
- **Fix:** check `isinstance(payload, dict)`, catch `Exception` around the whole load and the message, and ideally replay or validate the state.
- **Likelihood:** a truncation or a partial disk write already falls back cleanly; this needs a file that is valid JSON with the wrong shape.

**D2 (Medium, existing align() weakness now on the automatic boot path): a restart can show a wrong overlay as ready to verify.**
- **Where:** server.py:98-118; vision.py:294.
- **What happens:**
  - I restarted with the same board seen from a mirrored mount (`right` instead of `left`). `align()` succeeded with a wrong homography: the overlay was off by up to 462 px, and the phase was `review_overlay`.
  - On the next processed frame the vision message changes to "Ready" (`SEGMENTATION_MESSAGES['none']`), overwriting "check the overlay, then verify".
  - The Verify gate still holds. But a host who taps "Markers correct" without looking will score on a wrong board.
- **Fix:**
  - Don't overwrite the message while unverified.
  - Consider rejecting a restore whose overlay differs from the saved one by more than N px, which would force the four points again.

**L1 (Low): the save is synchronous under `game_lock`, with no directory fsync.**
- **Where:** server.py:158-166; persistence.py:27.
- **What happens:**
  - A slow or hung state disk stalls every game write and `/api/state`. That is fine for the internal SSD, but not for a `--state-file` on a USB drive.
  - The directory is not fsynced after `os.replace`, so a power loss could lose the last rename. The previous file would survive.

**L2 (Low): `bump()` catches only `OSError`.**
- **Where:** server.py:158.
- **What happens:** a `ValueError` from `json.dumps(allow_nan=False)` would escape after `g.throw` and the revision bump. In `commit_camera_dart` that happens before `flow.close`.
- **Likelihood:** unlikely with today's data.

**L3 (Low): calibration save misses `cv2.error`.**
- **Where:** server.py:86.
- **What happens:** `save_calibration()` does not catch `cv2.error`. A failure there would turn a successful calibrate into a 500.

**L4 (Low, UX): the tap board starts below the first screen in camera games on a small phone.**
- **What happens:** at 360×740 the tap board's top is at y=721 in camera games (545 in manual games), because of the fixed 154 px camera panel (presentation.css:57). The host has to scroll once. It is stable after that.
- **Also:** at 360 px the "End turn · fill misses" button wraps to 3 lines.

**L5 (Low, test flakiness): the 20 ms p95 test fails under parallel disk load.**
- **Where:** `test_save_with_200_history_entries_is_under_20_ms_p95`.

## Code review (685179f..7d05376)
- The persistence design is sound and matches the plan: temp file + fsync + replace, tokens never saved, and the calibration is held as an untrusted reference until `align()` and a human Verify.
- The test isolation via `DART_STATE_FILE` covers every server-spawning suite.
- The recorder rewrite to a single writer thread with a queue cleanly fixes R4.
- The layout CSS uses fixed heights plus `visibility` instead of `hidden`, which removes the shifts.
- No regressions found.

## Safe to push?
**Yes.** D1 and D2 are Mediums with workarounds (delete the file; look at the overlay before tapping Verify). Fix D1 (a few lines) and the D2 message clobbering before the M1-17 dry run.
