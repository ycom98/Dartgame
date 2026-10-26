# Independent QA — current manual-game candidate

Updated October 25, 2026.

**Latest priority: the board has not arrived. Independent QA reviewed the existing non-camera product now. Physical camera, calibration, dart detection and movement testing are deferred until the final hardware phase.**

**Verdict: PASS for the tested manual 301/501 software scope; ready for Kapil/PM review.** No physical-board or phone-camera acceptance is claimed.

## Independent evidence

The stable candidate passed **43/43 Python tests** using `.venv/bin/python -B -m unittest discover -s tests -v`.

Five independent browser journeys passed in isolated headless Chrome, each using its own temporary localhost application. Actual media calls were blocked; every journey recorded zero media requests. QA did not mutate the real port-8443 game or restart that process.

1. **Complete 301, two players:** three-dart turn gating, player transition and undo, overshoot with full-turn score restoration, bust undo, exact-zero win, win undo and corrected winning dart. Final scores 0/301. [Results](qa-artifacts/manual-301-results.json).
2. **Complete 501, four players:** two full rounds of rotation and a ninth-turn finish; all four scoreboard entries retained. Final scores 0/501/501/501. Permanent winner gates checked after the debounce interval. [Results](qa-artifacts/manual-501-four-results.json).
3. **Complete double-out 301, three players:** reaching zero without a double and leaving one both bust; undo/correction restores the appropriate scores; double bull finishes from 50. Final scores 0/301/301. [Results](qa-artifacts/manual-doubleout-three-results.json).
4. **Recovery/validation:** disconnect disables mutation controls; reconnect preserves the game and clears its stale network banner. Successful polling retains actual validation errors long enough to read. Blank/duplicate names and cancelled replacement preserve scores/history; accepted replacement creates the selected 501/three-player game. A rejected score request leaves state unchanged and retry records once. A response lost after backend commitment refreshes the one committed dart without automatic duplication, and that dart remains undoable. [Results](qa-artifacts/manual-recovery-validation-results.json).
5. **Manual entry/authentication:** Miss chosen after Triple becomes Single/zero and records once; Bull chosen after Triple resets to Single, disables Triple and records 25. Six independent HTTP requests—GET and POST with missing, wrong ASCII and Latin-1 non-ASCII Bearer tokens—each return controlled 401. Wrong/missing browser pairing links disable mutation controls; the correct link restores the same game. [Results](qa-artifacts/manual-inputs-auth-results.json).

Complete UI games are distinct from the Python/API regression count. The developer additionally reports its own 318-assertion API/rules audit, four focused manual UI checks and two recovery checks; those are developer evidence, not additional independent complete-game runs.

## Test sources and screenshots

Runners: `tests/qa_manual_301.cjs`, `tests/qa_manual_501.cjs`, `tests/qa_manual_doubleout.cjs`, `tests/qa_manual_recovery.cjs`, `tests/qa_manual_inputs_auth.cjs`; shared isolated startup in `tests/manual_qa_common.cjs`. The QA agent authored/executed these tests; PM saved their exact source files because the child agent retained a read-only filesystem profile.

PM visually reviewed the test-player screenshots:

- [301 bust](qa-artifacts/manual301-bust.png) and [301 win](qa-artifacts/manual301-win.png).
- [501 four-player win](qa-artifacts/manual501-four-win.png).
- [Double-out bust](qa-artifacts/manual-doubleout-bust.png) and [double-bull win](qa-artifacts/manual-doubleout-bull-win.png).

## Repairs validated this cycle

PM/developer findings were repaired and independently verified: retained Triple after Miss/Bull selection; non-ASCII Bearer tokens causing an uncontrolled authentication exception; and a stale red connection error remaining after recovery. Recovered connection errors clear while action/validation errors remain readable.

No unresolved software defect was observed within the exercised manual scope.

## Intentional limits and deferred work

- Implemented games remain 301/501 with two to four players and optional double-out. Additional games and the dashboard are outside this review.
- Scores and history remain in memory and are lost when the server stops. Persistence/statistics are not implemented.
- Manual scoring requires explicit user entry; there is no automatic physical-scoring acceptance.
- Actual Galaxy S22 (SM-S901U) camera permission/lens choice, live frame capture, board geometry, calibration duration, dart accuracy and board/phone movement remain unvalidated. Board-dependent work is last, after delivery. Kapil's earlier Yes / Available report is user-reported secure-context availability, not independent physical-camera evidence.
- Earlier calibration/browser, mocked-camera startup and staged-CA checks remain historical software evidence only. Existing artifacts include `browser-results.json`, `camera-startup-results.json`, `certificate-chain-results.json` and `ca-bootstrap-results.json`; QA installed no device/system trust.

## PM deployment addendum

After the independent verdict, PM confirmed the actual app had no active game and no fresh camera feed, then restarted it to activate the Python authentication fix. The new app remains empty; six read-only/unauthorized-request smoke checks passed with normal project-CA and hostname verification, including malformed-token GET/POST rejection. See [deployment evidence](qa-artifacts/manual-deployment-smoke.json). These are PM operational checks, not independent QA-agent actions. Restart rotated the private pairing token; use the latest conversation link.
