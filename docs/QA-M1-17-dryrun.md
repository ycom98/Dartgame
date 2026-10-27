# QA: M1-05c/e + M1-16 fixes (c0095a0) and the M1-17 board-day dry run

Tree: `/home/user/qa-m1h`, detached at c0095a0. Nothing was committed.

## Job 1: verification of the fixes

**Suites**
- Python: **224/224 OK**.
- Browser: **16/17**. The only failure is the known `qa_presentation.cjs` "Maya" case.
- Held-out spot check (realistic ceiling-1.5ft, seed 2, 200 darts) is **unchanged**: 94.0% exact, 1.5% no proposal, median tip error 0.906 mm. These match `M1-05e-detection.json` exactly.

| Defect | Verdict | Evidence (old probes re-run) |
|---|---|---|
| 05cde D1: 12 px limit | **FIXED** | The limit is now max(30 px, 10% of the radius). Click noise σ 2/4/6 px: 10/10 refined. σ 8: 7/10, the rest rejected for real reasons (edges, a moved click). σ 12: 9/10. |
| 05cde D2: quality report persisted | **FIXED** | `calibration.json` has `calibration_quality`. After a restart, `vision.calibration` is the full report and the Setup page shows it. |
| 05cde D3: refine() raises | **FIXED** | Grayscale input refines. BGRA, black and tiny images return `clicks` with a reason. Nothing raises. |
| 05cde D4: many large fragments | **FIXED** | 20–40 cored strokes: `noisy` in 53–73 ms (was 156–377 ms). Residual (Low): 13 strokes, which is just over the 12-core cap with ~14 fragments, gave `dart` in 2 of 5 scenes. Contrived. |
| 05cde D5: rejected dart, silent "Ready" | **FIXED** | Code (`vision_segment.py`, "only implausible" → `noisy`) plus the new test. |
| 05cde D6: click order | **FIXED** | Rotated clicks give `confidence low` plus a warning. In the real UI (below), the warning line is highlighted. |
| 05cde D7: nits | **FIXED** | The 15 mm comment is corrected, the disabled-refinement report has the same keys, the banner says where the match is saved, and the artifact has its `git_commit`. |
| 16 D1: wrong-shape save crashes startup | **FIXED** | All 9 damaged variants start cleanly, the file is kept as `match.corrupt-*`, and a WARNING is printed. Variants: truncated, empty, binary, `[]`, `null`, schema 2, unknown mode, missing scores, player 7. |
| 16 D2: overlay 462 px off shown as Ready | **FIXED** | left→right gives `needs_alignment`: "markers moved 463 px. Set four points again". Top/bottom: needs_alignment. A 25 px shift gives `review_overlay`. The message is no longer overwritten by "Ready". |
| 16 L1–L5 | **OK** | Covered by the suite. The kill -9 hammer left 0 of 12 files unparsable and no `.tmp`. |

**Setup page with real data**
- After calibration it shows "Calibration refined on the double ring · confidence high · fit 0.41 mm" (muted).
- With clicks in the wrong order (6, 3, 11, 20) it shows the same line with "confidence low … — the 20 is not the topmost of the four points: check the click order (20, 6, 3, 11) and that the phone is upright", in the **warning** style. Screenshot: `dryrun/setup-wrong-order-warning.png`.

**No new defects in the fix commits.**

## Job 2: M1-17 dry run

**Setup**
- `tests/fake_ipwebcam.py --port 8080 --scenes …` served 8 sim scenes of the ceiling-1.5ft mount at 1920×1080. Generator: `dryrun/gen.py`.
- The server was started exactly as the owner will start it: `bash start-mac.command --camera 127.0.0.1 --record <tmp>/session1`, with `DART_STATE_FILE` pointing at a temp folder.
- Playwright drove it (`dryrun/dry.cjs`, log in `dryrun/run.log`) with three pages: Setup on a 1280 px Mac window, the Controller on a 390×844 touch phone, and the TV at 1920×1080.

**What worked**
- **Calibration** with ~6 px click error, four clicks 1.2 s apart:
  - 6.6 s from "Freeze" to the "Markers correct" button; the server answered in 0.3–0.5 s.
  - About 10 s to Ready, including looking at the overlay. Target C8 is under 2 minutes.
  - Wrong click order is flagged in the warning style.
- **Darts:**
  - Pending darts appeared 0.21–0.54 s after the scene changed, all 7 under 1.5 s (C7).
  - The camera read every dart correctly: T20, S12, S10, S16, S3, S20, T4.
  - One dart auto-accepted, one tap correction (S12 → T12), one **Accept**, and **End turn · misses** filled the third dart.
  - Auto handoff happened after the darts were pulled.
- **kill -9 mid-turn, then the same command again:**
  - The match came back identical (revision 12).
  - The re-check said "Board position matches the saved calibration…"; one **Markers correct** and it was ready in 3.7 s.
  - The next dart (T4) scored.
- **Recording and tools:** **Stop recording** worked. `make_labels.py`, `replay_recording.py` and `contact_sheet.py` all ran as the README says (0.06 s, 9 s, 0.5 s).

**Go / no-go: GO, conditional.** Scoring, calibration and recovery work. Before Thursday, fix #1 below, or change the checklist so the restart records into a new folder (it is a one-line change). #2 and #3 can be handled by checklist wording if there is no time to fix them.

### Fixes before Thursday (ranked)

1. **High: restarting with the same `--record` folder corrupts the session.**
   - Where: `recorder.py:84-97` (appends to the jsonl files; `last_written_seq` restarts from the new source's seq) and `server.py:148`.
   - What happens after a restart:
     - Frame numbers start again at 1. `frames/000001.jpg…` are **overwritten**: 134 files in this run, the start of the session including the empty board.
     - The `events.jsonl` `order` field restarts, so two events carry the same `order`.
     - `session.json` is replaced: the notes are lost (`notes: {}`) and `frames` is 134.
     - `start/` is replaced.
   - Result: `replay_recording.py` reports `identical: false`, with 207 detection mismatches and 2 failed actions (verify / reset_base "Connect the camera…"). The contact sheet puts the last dart first.
   - Block 11 tells the owner to do exactly this. After 10 min of play past the restart, about 9,000 frames from the start of the trial would be overwritten.
   - Fix: refuse a non-empty folder, or use `session1-2`; or continue the seq/order numbering and keep the first `session.json` and `start/`.
2. **Medium: every restart changes both pairing links.**
   - Where: `server.py:165-166`.
   - The phone controller and the TV both switch to "PAIRING LINK REQUIRED". The TV keeps showing the old scoreboard under that banner (`dryrun/tv-after-restart-old-link.png`).
   - The owner has to retype a 32-character link on the display PC mid-match.
   - Fix: save the tokens in the state folder (0600). At minimum, add a checklist step.
3. **Medium (UX): a phone-stream drop is not explained on the controller.**
   - During the 10 s outage the controller shows "Camera: not ready" with the detail "**Ready**" (`dryrun/controller-wifi-drop.png`). `vision.message` stays "Ready" while the phase is `camera_disconnected`.
   - After the stream returns, the camera stays `needs_alignment` until someone presses **Check / realign board** and then **Markers correct · Ready to play** on the **Mac**. The controller says nothing about this; in the sim it took 0.4 s once done.
   - Fix: a message such as "Phone camera stream lost: on the Mac press Check / realign board, then Markers correct". Or allow realign + verify from the controller.
4. **Medium (intermittent, not root-caused): auto handoff did not fire in 1 of 4 runs.**
   - No `next` event within 10 s after **End turn · misses** and pulling the darts.
   - The other three runs handed over after 4 s.
   - Workaround: tap **Next player →**. Suspect `control.js:15` (`schedule()` pauses when `Date.now()-lastHealthy>1500` or the revision moved).
5. **Low–Medium: an action in the ~0.5 s after an auto-accept can be refused while the UI claims it worked.**
   - One run: a tap at "auto-accept in 0.0 s" showed "Triple 12 (instead of camera T20)", but nothing was recorded (409 "Proposal changed"). The camera's next dart was then auto-accepted.
   - Another run: the first **Undo** click right after an auto-accept did nothing.
   - `control.js:52` writes the feedback before the request. It should clear it, or say "not recorded", on an error.

### Nice to have
- While the darts are pulled at handoff, the camera says "More than one new dart; enter scores manually". This is harmless but confusing.
- After **Undo** of a camera dart that is still in the board, the camera does not propose it again; the host must tap it. Say so in the checklist.
- `start-mac.command` always prints "Camera: add --camera PHONE_IP…", even when `--camera` was given.
- README:122 is stale: it says images and game state "are held in memory and are lost when the server stops… not … stored on disk". The match and calibration are now saved, and recordings store frames.
- The Setup page does not scroll the frozen image into view. After editing the notes (below the image), clicks fall outside the visible image. My first runs clicked nothing until I scrolled.
- Controller during an outage: the "Pause auto-accept" button overflows the panel, and the tap-feedback text is truncated ("Sin…") beside **End turn · misses**.

### Exact checklist / README corrections (`docs/BOARD_DAY_CHECKLIST.md`)
- **L33:** "**End turn · fill misses**" → "**End turn · misses**", which is the button label.
- **L35:** "(or tap **Next player**)" → "(or tap **Next player →**; tap it if the 4 s auto handoff does not happen)".
- **L52 (block 10), add:** "When the picture is back, on the Mac Setup page press **Check / realign board**, then **Markers correct · Ready to play**. The controller shows 'Camera: not ready' until then."
- **L53 (block 11):** replace with "Close Terminal mid-turn, then restart with the same command but a **new record folder** (`--record ~/dart-trial/session1b`). Then:
  - Re-open the **new Controller and Presentation links** printed in Terminal on the phone and the TV; the old ones stop working.
  - Press **Markers correct · Ready to play** on Setup.
  - The match should come back exactly."

  Once fix #1 lands, the folder note can go.
- **Section "How scoring works", add:** "Undo removes the dart from the score, but the camera won't propose that dart again; tap where it is."
- **Wrap-up, add the commands for the trial folder** (the README examples use `recordings/SESSION`):
  `.venv/bin/python tools/make_labels.py ~/dart-trial/session1`, then the same for `replay_recording.py` and `contact_sheet.py`. If you restarted into a second folder, run them on each folder.
- **README:122:** update the privacy paragraph (see Nice to have).

### Screenshots and files (`/home/user/qa-m1h/dryrun/`)
- Setup: `setup-ready.png`, `setup-wrong-order-warning.png`, `setup-after-restart.png`.
- Controller: `controller-pending.png`, `controller-late-tap.png`, `controller-wifi-drop.png`.
- TV: `tv-mid-game.png`, `tv-mid-game-2.png`, `tv-after-restart-old-link.png`.
- Recording output: `contact_sheet.png`, `replay-session1.json`.
- Run files: `dry.cjs`, `gen.py`, `run.log`.
