# QA: M1-17 dry-run fixes (0bba724)

Independent check of commit 0bba724 in the detached worktree `/home/user/qa-m1i`. Real `server.py` subprocesses, fake IP Webcam (sim "left" 1280x720), Playwright. The probe scripts are in `/tmp/claude-0/-home-user/39130e07-3815-5ada-9f6d-04313fc052e0/scratchpad/m1i/` (`probe.py rec|links|drop|noauto`, `ho.cjs`, `t2d.py`).

**Verdict: all 5 dry-run defects are fixed. No new defects at MED or above. Safe to push: yes. Thursday: GO.**

## Results per claim

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Same `--record` folder appends a part | **PASS** | 3 parts in one folder: kill -9 mid-match, restart, kill -9 again, restart, stop. 0 of the part-1 frames were overwritten (md5 checked). frames.jsonl: 200 seqs, strictly increasing, 0 duplicates, 200 files on disk. processed.jsonl: 178, increasing, 0 dups. events: 24 orders, strictly increasing. `recording_started` part 1/2/3 with `start`/`start-2`/`start-3`; first `started_at` and notes kept; session.json lists 3 parts. make_labels: 4 labels. **replay: identical true, 0 detection mismatches, 0 action mismatches, 0 missing frames, resumed_parts 2.** contact_sheet: 4 panels. |
| 2 | Links persist | **PASS** | `links.json` is mode 600 (and stays 600 after a rewrite; no `.tmp` left behind). After kill -9 and restart, the controller and display tokens are the same and the old links return 200. `--new-links`: new tokens, the old controller and display links get 401, the match is kept, and the new links survive the next plain restart. `--fresh`: new tokens, old gets 401, no match. HTTP: `/links.json`, `/.local/state/links.json`, `/static/../…`, `%2e%2e` all give 404. The token is not in any recording .json/.jsonl, and `/api/state` read with the display token does not contain the controller token. (The controller's own state contains `presentation_path`; that was already so and is by design.) |
| 3 | Stream drop | **PASS** | Unchanged board: back to Ready with no tap, about 1 s after frames return. Board shifted 1 px: auto-Ready. Shifted 2 px (measured drift ≈3 px), 4, 8 and 17 px, rotated 1°, a different mount (462 px): **all stay unverified** in `review_overlay` with "Camera back, but the board moved N px … On the Mac: check the overlay, then Markers correct." A 2 s drop that comes back with the board moved by 17 px: not verified (it asks). While the phase was `camera_disconnected`, Ready was never shown (0 samples), and the message was "Camera stream lost: waiting for the phone…". `--no-auto-recheck`: an unchanged board stays at `needs_alignment` "Check / realign board, then verify". Auto-recheck can only restore readiness when the drift is ≤3.0 px from the overlay the host last verified (server.py:302-306). |
| 4 | Auto handoff | **PASS** | Camera game, polls slowed by a random 200-900 ms: **20/20 handoffs**, 3.8-5.2 s after the 3rd dart. When polls fail (aborted), the turn did **not** advance and the controller showed "Connection lost. Automatic handoff is paused." |
| 5 | Late tap/undo | **PASS** | The controller held a stale revision and another client committed a dart, then the controller tapped T20 100-200 ms later: "Not recorded: Triple 20. Check the turn and tap again." (class `refused`), dart not recorded, notice "Match changed on another controller…", state refreshed (2/2). A late Undo was not applied and showed the same 409 notice. No false success. |
| — | Python suite | **227/228 + flake** | The one failure is `test_recording …identical_detection_sequence` with `frames_processed 50 not > 50`. It is a timing flake, not a regression: on the parent commit 4f0dc16 the same test failed 3 of 5 runs (49/50), and on 0bba724 it passed 3 of 5 runs alone. |
| — | Browser | **16/17** | Only the known `qa_presentation.cjs` "Maya" demo timeout fails. |

## Defects / notes (none blocking)

1. **LOW: test flake.** tests/test_recording.py:146 `assertGreater(frames_processed, 50)` sits on the boundary in this container, and it was already flaky before this commit. Fix: lower it to `> 30`, or run the sim session for a little longer.
2. **LOW: session.json totals go stale after kill -9.** recorder.py:419 writes session.json only every 150 frames, so a crashed part keeps its last count. In the probe, session.json said `frames 67` (part 2: 0) while 200 frames were on disk. None of the tools use these totals (they read the jsonl), so the data is safe. Suggested fix: in `resume_from_disk` (recorder.py:138), set `previous_totals['frames']` from the frames.jsonl line count.
3. **LOW: up to 5 s of "watching" after a silent drop.** vision.py:391 marks the camera disconnected only after the frame is ≥5 s old (measured 5.0 s × 3). No frames means no proposals, so nothing can be scored wrongly in that window. The claim "never Ready while the stream is lost" holds once the loss is detected.
4. **Info.** The 3.0 px threshold is strict: a 2 px image shift measured as about 3 px drift and asked for a check. That errs on the safe side, so it is fine for Thursday.

Code review of 4f0dc16..0bba724 found no correctness bugs. The handoff wait is capped at 3 s and then falls back to the pause rule. `report()` ignores a stale promise when the feedback text has changed since. The source offsets in `on_ingest` and `write_new_frames` both use the same `source_offset()` under a lock. Replay re-creates `Vision` from `start-N/` at the part boundary, keyed on `after_seq`.

## Checklist (docs/BOARD_DAY_CHECKLIST.md) — suggested wording

The current wording in blocks 10 and 11 still works, but both rows can be simpler:

- **Block 10 (Wi-Fi drop):** `Phone Wi-Fi off for 10 s; lock the phone screen for 10 s. The controller shows **Camera reconnecting…**; keep tapping darts meanwhile. When the picture is back, the camera is ready again by itself within a few seconds if nothing moved. If the controller says **Board check needed** (or the Setup page asks), press **Check / realign board** on the Mac, look at the overlay, then **Markers correct · Ready to play**.`
- **Block 11 (Restart):** `Close Terminal mid-turn and start it again with the **same command** (same `--record` folder is fine: the recording continues as a new part). The match should come back exactly, and the Controller and Presentation pages keep working with the same links (reload them if they look stuck). On the Setup page press **Markers correct · Ready to play** after checking the overlay.`
- **Wrap-up:** you can drop "(one line per session folder)", because a restart no longer creates a second folder.
- **Night before (optional):** if a link was shared by mistake, start once with `--new-links`.
