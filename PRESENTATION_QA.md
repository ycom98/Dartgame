# Dart Room presentation — independent QA

Date: October 26, 2026. QA is independent from the developer implementation. This report covers `/play`, `/control`, `/showcase`, the shared presentation assets and the revision/read-only API changes. Historical `QA_REPORT.md` and its manual-camera evidence are preserved.

## Environment and isolation

Each browser script starts a separate ephemeral **HTTP loopback server** with its own in-memory App and QA token, launches a fresh headless Google Chrome profile via bundled Playwright, then closes both. Vision is explicitly unavailable. `getUserMedia` is instrumented to fail if called. The actual HTTPS service on port 8443, real match, certificates and physical camera were not accessed or restarted. Sandbox loopback/Chrome execution required approved escalation; filesystem writes worked normally.

## Automated evidence

- `tests/test_presentation_qa.py`: five independent API checks; real simultaneous controller requests accept exactly one stale-revision score; stale next/undo/throw cannot touch a replacement game; malformed revisions return controlled errors; legacy payloads still work; public routes/assets do not mutate; spectator credential reads state but cannot access image routes or any tested mutation.
- Full Python discovery: **48 PASS**, comprising the 43 existing tests plus five independent presentation tests. Output: `qa-artifacts/presentation-python-results.txt`.
- `tests/qa_presentation.cjs`: host UI and two independently polling spectators; scores, active player, three-dart guide, exactly one dart per click and fourth-dart gate; double-out bust restores score, undo restores play, bull checkout wins, winner blocks further entry/next; actual four-second automatic handoff and pause/undo/new-match cancellation; offline pause/reconnection and simulated server failure recovery; two-controller next/score conflicts; read-only credential enforcement and zero spectator POSTs; local showcase natural turn handoff and win, Pause/Restart, zero API traffic and unchanged live revision; responsive layouts and fullscreen-denied fallback.
- `tests/qa_presentation_resilience.cjs`: delayed old GET response cannot roll back a successful local score; lost POST acknowledgement reconciles without retrying or doubling the dart; 501 with four long player names at 320/390/736/1280/1920; reduced-motion setting produces computed `animation-name: none`.
- `tests/qa_presentation_visual.cjs`: screenshots and document-width checks for all three routes at 320/736/1280/1920.
- `tests/qa_presentation_focus.cjs`: PM follow-up checks for valid spectator link in empty lobby, rapid real double click, return from new-match setup without mutation, and a hung health GET cancelling automatic handoff.

Machine-readable results: `qa-artifacts/presentation-results.json`, `presentation-resilience-results.json`, `presentation-visual-results.json`, and `presentation-focus-results.json`.

## Visual review

Inspected the 1920px audience display, 320px audience display and controller, and 736px controller. Active name/remaining score dominate, three darts and the next player are visible, and the board is labelled as an entered-segment map. Cream/gold on dark green is readable; warm red feedback differentiates bust. Presenter has only its fullscreen control and no scoring, QA-status or debug controls. Camera remains a secondary legacy-controller link. Phone layouts stack vertically and intentionally require scrolling; no horizontal overflow was detected.

Screenshots: `qa-artifacts/presentation-{play,control,showcase}-{320,736,1280,1920}.png` and `presentation-showcase-win.png`. The main journey recaptures narrow/TV screenshots with a live scored match; the final visual run captures an opening match and the visible fullscreen fallback.

## Findings and repair verification

1. **Repaired blocker:** audience page called `DartRoom.live()` while the shared module omitted its export. Actual browser failures on both spectators established the issue. Developer exported the function; subsequent browser journeys rendered and synchronized correctly.
2. Developer strengthened monotonic polling after QA review: only a newer revision replaces controller state. Targeted delayed-response verification passes.
3. PM follow-up safeguards cover empty-lobby spectator links, a 600ms accidental-repeat guard, short health-read timeouts before automatic handoff, setup return, and winner standings. Focused verification is recorded separately.
4. Two early harness failures were corrected test fixtures: a double-out score of one busts immediately, and direct API fixture changes require waiting for the controller's next poll before a local click. They did not establish product defects. A 31-character test name was shortened to the documented 30-character limit.

## Scope limits

QA verifies manual software scoring, server synchronization and the isolated scripted demonstration. Physical board accuracy, real camera permission/capture, calibration, LAN TV/browser pairing, real fullscreen permission and television viewing distance remain hardware acceptance work. These were deliberately outside this run because the board has not arrived.

## Verdict

**PASS — ready for PM/user presentation review.** Final browser regression: all nine main journey groups pass after the controller safeguards. All three resilience groups, all four PM-focused groups, and both final fullscreen denial/unsupported groups pass; responsive checks pass for every route at 320/736/1280/1920, plus four long-name 501 players at 390. Browser errors: zero. Manual-mode media calls: zero. Spectator mutation requests: zero. Showcase API traffic: zero. Full Python suite: 48/48 pass. No open software blocker remains in this scope.

After the last presentation polish, only the affected layouts and fullscreen paths were retested: both `/play` and `/showcase` visibly offer “Use browser full screen” when permission is denied or the API is unavailable, and enlarged SVG sector labels preserve the no-overflow result. Final 320px showcase image was visually inspected. Real fullscreen authorization and hardware remain acceptance items above.

## PM deployment addendum

Root deployed the reviewed app on HTTPS port 8444 using the existing project CA, with certificate chain and hostname validation enabled. Eight post-deployment route/authentication checks passed, including viewer read-only restrictions. See qa-artifacts/presentation-deployment.json. The actual showcase was opened in the in-app browser and visibly verified. The pre-existing active match on port 8443 was preserved without restart or mutation. This deployment smoke check is additional PM evidence, separate from the independent QA above.
