# Dart Room milestone tracker

Updated October 26, 2026. Camera and physical-board work remain the final phase.

| Stage | Work | Status |
| --- | --- | --- |
| 1. Existing manual game foundation | 301/501, two to four players, straight/double-out, undo/correction, validation/recovery | Passed developer + independent QA: 43 tests and five browser journeys |
| 2. Guided presentation experience | /play spectator, /control host, /showcase isolated demo; polished animations and turn guidance | Implemented and deployed on HTTPS 8444 |
| 3. Presentation QA and PM review | Shared displays, safe auto-handoff/recovery, visual/accessibility checks, demo isolation | Independent QA PASS; 48 Python tests plus browser checks. Ready for PM/Kapil review |
| 4. Further game/dashboard scope | Agree additional game types and any expanded features after presentation review | Pending scope |
| 5. Final camera/board phase | Live rear camera, calibration, real dart accuracy, removal, movement and timing | Deferred until Winmau board arrives |

## Current presentation acceptance

A player-facing screen can be presented independently of QA. It clearly shows whose turn it is, guides three darts, responds to scores and celebrates transitions/wins. A host enters scores now; automatic physical scoring is not claimed. Optional manual auto-handoff is visible/cancellable and only controlled by the host. Multiple audience windows are read-only.

A separate showcase runs an animated sample match without changing live game scores. The live audience view and controller share the actual backend rules/state; camera setup stays outside the main presentation flow.

See REQUIREMENTS.md and UI_DIRECTION.md for scope. Earlier manual-game evidence remains in QA_REPORT.md; the new independent feature report is PRESENTATION_QA.md.

## Hardware acceptance later

After delivery, mount the confirmed S22 SM-S901U rear camera with the entire Winmau Diamond Plus visible. Verify trusted context/permissions, calibrate an empty board, inspect overlay and measure routine calibration. Then test known hits, misses, overlap/removal, reconnect and board/phone movement.

Routine calibration target remains roughly one minute and no more than five after first installation/pairing/trust setup. No software mock or demo proves physical accuracy.

## Gameplay animation refinement

Kapil requested a stronger gameplay sequence after visual review. The new candidate adds named entrances, animated score/reservoir drain, per-dart points and turn total, 180 celebration, recap/next-player, bust restore and win scenes. Developer implementation passes its browser checks. Independent animation QA passed all nine groups, with 48 Python regressions also passing. PM reviewed clean mobile/TV images and the live showcase; ready for Kapil review. This refinement supersedes the earlier static presentation. Both existing services remain running and no live match was changed.
