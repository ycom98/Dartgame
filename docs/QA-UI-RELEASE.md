# QA: UI release check ("polished UI and experience", due Wed Nov 4)

Independent QA, 2026-11-03. Worktree `/home/user/qa-ui-final`, detached at `eacd54f` (ui-a + ui-b + sound wiring). Scope: Developer A's `df4b745` (UI-01/02/03/05) and `e72524b` (UI-07), the sound wiring in `e433ff7`, and the test edits in `eacd54f`. Developer B's work was QA'd before (docs/QA-UI-B.md). I reran everything myself. My scratch scripts and screenshots are outside the repo, in the session scratchpad (`e2e.cjs`, `rematch.cjs`, `e2e/*.png`).

## Release recommendation: **SHIP AFTER ONE FIX (M1)**

There are no HIGH defects. The checkout table and the stats are correct. One MEDIUM defect is a real living-room failure: the TV can get stuck on the lobby while a match is running. The fix is small, a few lines in `server.py` (see M1). Everything else is LOW polish and can follow after release.

## Verdicts

| Ticket | Verdict |
|---|---|
| UI-01 Shared theme | **PASS** |
| UI-02 Lobby + controller setup + `POST /api/lobby` | **PASS-WITH-NOTES** (M1, L1) |
| UI-03 Checkout / bust / game shot + stats / rematch | **PASS** (L2–L5) |
| UI-05 Controller polish | **PASS-WITH-NOTES** (L6) |
| UI-07 TV robustness (720p / 1080p / 4K, reconnect, reduced motion) | **PASS** |
| Sound wiring (`presentation.html`) | **PASS** (L7) |
| Test edits in `eacd54f` | **OK**: two selector allowances for the new Sound button. No assertion was loosened. |

## 1. Suites (run twice)

- **Python, run 1:** 244 tests OK (217 s).
- **Browser, run 1:** 21 of 21 suites passed. This includes `qa_ui_lobby`, `qa_tv_sizes`, `qa_sound`, `qa_setup_steps`, the camera suites, and the layout-shift and tap-board suites.
- **Run 2:** see the last section.

## 2. Checkout table (`modes/checkout.py`): correct

**Brute-force check.** I wrote an independent brute force over every board segment and compared it with `suggest()`. It covered every score from −2 to 184, with 1, 2 and 3 darts left, for both double out and straight out. I found **0 mismatches** on any of these:
- every route adds up exactly to the score;
- under double out, the last dart is a double or the bull;
- the route uses the fewest possible darts;
- `None` is returned exactly when no finish exists.

**Expected boundary cases all hold:**
- The scores with no 3-dart finish are exactly 159, 162, 163, 165, 166, 168 and 169.
- 1-dart finishes are exactly the even numbers 2–40 and 50.
- 2-dart finishes are 61–98, 100, 101, 104, 107 and 110. There is no 2-dart finish for 99, 102, 103, 105, 106, 108 or 109.

**Against the published chart.** I read every 3-dart and 2-dart double-out route and they match the standard chart. Examples: 170 T20-T20-Bull, 167 T20-T19-Bull, 121 T20-T11-D14, 100 T20-D20, 99 T19-S10-D16, 76 T20-D8, 61 T15-D8. The live hint also updates with darts left: Ben on 121 got T20-T11-D14, and after one T20 he got T15-D8 for 61.

**Straight out** is legal and minimal everywhere. One cosmetic order issue is noted as L5.

## 3. Stats: correct

I checked the stats in `core.Game.turns/stats` and `X01.match_stats` two ways: in `core` directly, and live through the end-to-end walk. The scenario covered:
- a 180;
- undo of a dart and re-throw;
- a correction that turns the visit into a bust;
- a turn closed with filled-in misses;
- undo of an advance;
- a 2-dart checkout.

Every figure matched my hand calculation:
- 3-dart average: Ana 301 points in 11 darts gives 82.1. Bust darts and filled misses count as darts.
- Highest turn.
- Darts thrown.
- 100+ / 140+ / 180 bands (100–139, 140–179, and 180 on its own).
- Checkout and checkout darts.

**After a restart.** Stats are byte-identical after a `to_json` / `from_json` round trip and after a real server restart. The undo history is never trimmed, so stats cover the whole match.

**End-to-end figures:**
- Ana: 112.9 average, 8 darts, one 180, 76 checkout in 2 darts.
- Ben: 108.0 average, 5 darts (including the 2 bust darts), one 180.

## 4. Lobby and API

**`POST /api/lobby` rejects bad requests**, as it should:

| Request | Result |
|---|---|
| Display token | 401 |
| No token | 401 |
| 5 players | 400 |
| A 31-character name | 400 |
| A name that is not text | 400 |
| `players` as an object | 400 |
| `start` of 300, `"301"`, `301.0` or `true` | 400 |
| `open: "yes"` | 400 |

**Other lobby behaviour:**
- A lobby write never changes the match revision.
- The draft accepts duplicate names (L1). `POST /api/game` still enforces 2–4 distinct names of 1–30 characters.

**`recent_players.json`:**
- It is written only when a game starts, which needs the owner token.
- It is capped at 12 names (I started 20 games), each 1–30 characters, with no case-insensitive duplicates.
- A damaged file (numbers, blanks, a 40-character name) loads as just the valid names. It cannot grow without limit and cannot be filled with junk.

**Starting a game from the controller:**
- With the camera verified, Camera is chosen automatically and the game starts with `camera_game: true`.
- With the camera not verified (after a restart, phase `needs_alignment`), the Camera button is disabled and the note explains why.
- With 2 recent players it takes 2 taps from the win screen (New game, then Start, with names already filled in) or 3 from empty (two name chips, then Start). The spec allows 6.

**M1 (MEDIUM): the lobby can hide a running match on the TV indefinitely.**
- **Cause:** "Set up a new match" or "New game" sends `lobby.open = true`. While that flag is set, the TV shows the lobby even when a match is running (`static/presentation.js:389`).
- **The flag stays set until one of three things happens:**
  - someone taps "Back to the match" on that same page (`static/control.js:45-49`);
  - a new game starts (`server.py:462`);
  - the server restarts.
- **What I reproduced:**
  1. Opened setup mid-match.
  2. Closed the controller tab, as happens when a phone locks or the tab is swiped away.
  3. Opened a fresh controller. It shows the match screen with no hint, because `showSetup` is false.
  4. The TV stayed on the lobby. Darts keep scoring (`/api/throw` does not clear the flag) while the TV shows "Choose your game".
- **Suggested fix (server, smallest):** in `game_write` (`server.py:446`), clear `app.lobby['open']` on every match write (throw, next, undo, correct, fill, camera commit). Doing this under `game_lock` in `bump()` covers all of them.
- **Also suggested (client):**
  - In `control.js`, when a page loads or the state polls with `lobby.open` set, a match running and `!showSetup`, send `{open:false}`.
  - Send `{open:false}` on `pagehide`.

## 5. End-to-end walk on the fake phone (TV at 1920×1080 throughout)

**Steps I took:**
1. Setup page to step 3. Calibration and verify were done through the API, since Developer B's QA covered the clicks.
2. Took the Controller link from `/api/links` (what the QR code encodes) and opened it on a 390×844 touch phone.
3. Typed Ana and Ben, switched Double out on, and Start. Camera was chosen automatically.
4. Camera darts: S18 and S7 were auto-committed with proposal ids. The pending T10 was replaced by one tap on D10, and the event log shows it as a manual commit. Takeout, then the turn passed to Ben.
5. Ben threw a 180.
6. Ben busted on 121: T20, T20, leaving 1. The BUST badge appeared, the score went back to 121 and play passed to Ana.
7. Ana checked out with T20, D8.
8. Win screen, then a server restart (match, stats and recent names all came back), then Rematch: Ben throws first, same options.
9. Sound on, a 180 visit, then "Set up a new match": the recent chips showed, and the names were filled in.

**Result:** no page errors. The only console errors were expected: connection refused during the restart, and 401s only in a harness variant that changed tokens.

## 6. Visual issues the coordinator spotted

**(a) Ghost "GAME SHOT" on the win screen: RULED OUT** as a persistent defect.
- The victory stage (`presentation.js:284`) shows from +1.0 s to +4.0 s after the winning dart, then fades over 0.35 s.
- The developer's screenshot caught that fade. At +8 s the stage has opacity 0 and visibility hidden, and the screen is clean (my screenshot `15-tv-win-8200ms.png`).
- No fix needed. Optionally, take test screenshots after `.match-stage` is hidden.

**(b) Lobby player cards look faded: RULED OUT.**
- Once the animations finish, every joined card has opacity 1 and its animation reports `finished`. My lobby screenshot shows them at full strength.
- The developer's screenshot was taken mid-entrance.

**(c) Bar overlapping the tap board on a 390 px phone: CONFIRMED, LOW (L6).**
- The bar is the start toast ("501 · Ana vs Ben · manual scoring").
- `.toast-stack` is `position:fixed; top` (`static/theme.css:139-150`) with an opaque background, shown for 2.2 s (`control.js:24`).
- When the page is scrolled, it covers the 20 / 5 / 1 area of the board. It is `pointer-events:none`, so taps still go through, but undo and correction toasts appear just when the host is looking at that spot.
- **Fix:** anchor the toasts to the bottom on narrow screens (`bottom: calc(env(safe-area-inset-bottom) + 12px)`), or make them semi-transparent.

**(d) Winner shown twice on the win screen: CONFIRMED, LOW (L2).**
- The left side shows "THE WINNER · Ana", a big "0", an empty gauge and "DART 3 — READY".
- The right side shows "GAME SHOT · Ana" plus the stats.
- **Fix:** on a win, collapse the left hero to the winning visit, meaning the darts plus a "76 checkout" line. Drop the "0" and gauge, and replace the empty dart slot's "READY" with "—" (`presentation.js:235`).

## 7. Sound: PASS

- The TV starts muted: the button reads "Sound on" and `play()` returns false for every moment.
- One click turns it on: the button reads "Sound off" and `isEnabled()` is true.
- While muted, the dart, turn, bust and game-shot moments all reach `DartSound.play`, with no errors.
- With sound on, a 180 visit played `dart`, `dart`, `180` and `turn`, each returning true.
- **L7:** the TV polls once a second, so two darts entered within one poll produce one `dart` sound.
- **L7:** the `ton` sound exists in `sound.js` but is not wired to anything.

## 8. Regressions: none found

- **Camera path:** proposal ids, auto-commit, the one-tap replacement and filled misses all work. The `qa_camera_controller` suite passes, and so does my walk.
- **Recording:** `qa_camera_startup` and the Python recorder tests pass.
- **Persistence restart:** the match, stats, recent names and the TV and controller links all survive a restart.
- **Layout shift:** the tap-board and layout tests pass. No horizontal scroll at 390 px.

## 9. Offline: PASS

- The browser context blocked and logged every request that was not to 127.0.0.1. There were zero such requests across the setup page, TV and controller.
- The only `http://` strings in `static/` are placeholder text for the phone address.

## Defects

| # | Sev | Where | Defect | Fix |
|---|---|---|---|---|
| M1 | MEDIUM | `server.py:414-436`, `446`; `static/presentation.js:389`; `static/control.js:45`, `309` | `lobby.open` stays true when setup is abandoned, so the TV hides a running match | Clear `lobby.open` on every match write (in `bump()` or `game_write`); controller sends `{open:false}` on load or poll when not in setup, and on `pagehide` |
| L1 | LOW | `server.py:422-428` | The lobby draft accepts `Ana` and `ana`, so the TV lobby shows both | Drop case-insensitive duplicates in `update_lobby` |
| L2 | LOW | `static/presentation.js:187-235` | Win screen repeats the winner left and right; leftover "0", gauge and "DART 3 READY" | Make the left side a winning-visit summary and show "—" instead of READY |
| L3 | LOW | `static/control.js:367-375` | After a restart (camera needs a board check), Rematch quietly starts with manual scoring; the toast only says "Ben throws first" | Add "· manual scoring (camera needs a board check)" to the toast when `state.camera_game && !cameraReady()` |
| L4 | LOW | `static/control.html:66`, `106` | On the win screen, "New game" and "Set up a new match" do the same thing; the camera chip still says WATCHING after the match | Hide `#new-game` while `#win-panel` is shown |
| L5 | LOW | `modes/checkout.py:85` (`_route_cost`) | Straight out on 159/162/165/168 suggests T20-T13-T20 instead of the natural T20-T20-T13 (legal, just odd) | For straight out, sort set-up darts by points, or prefer the bigger treble first |
| L6 | LOW | `static/theme.css:139-150` | Toast covers the top of the tap board on a scrolled phone for 2.2 s | Bottom-anchored toasts on narrow screens |
| L7 | LOW | `static/presentation.js:218`, `static/presentation.html` | Two darts inside one 1 s poll give one dart sound; the `ton` sound is unused | Play one `dart` per added dart, with a stagger; map a 100–179 visit to `ton` |
| L8 | LOW | `static/presentation.js:385` | The TV header says "LIVE · MANUAL SCORING" in the lobby even when Camera is selected | Show "LOBBY" while in the lobby |

## Run 2 (rerun)

Run 2: Python 244 tests OK (211 s); browser 21 of 21 passed. Both runs green, no flakes.
