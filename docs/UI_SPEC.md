# M3-UI: Polished UI and experience (production-ready by Wed Nov 4)

Owner request (Nov 3): "Start working on polished UI and experience. It needs to be production ready by Wednesday."
Scope: make the existing 301/501 game feel like a finished product, Flight Club-style, at home. New games (Cricket, party games) are out of scope for this deadline, but the lobby shows them as "coming soon" and the game-mode interface (`docs/GAME_MODES.md`) is used so they slot in later.

Constraints: fully offline (no CDNs, no Google Fonts, no network calls; any library is vendored into `static/vendor/` with its licence), plain HTML/CSS/JS as today, Python stdlib server. Must not regress camera scoring, recording, persistence or any existing test. Respect `prefers-reduced-motion`. Readable, normally formatted code for everything new or touched.

Surfaces:
- **TV / Presentation** (`/play`) — the shared screen everyone watches.
- **Controller** (`/control`) — the host's phone or tablet.
- **Setup** (`/`) — the Mac, used once per session to connect and calibrate the camera.

Priority order. P1 must ship Wednesday; P2 ships if time allows; P3 is next.

## Developer A — TV + Controller + game experience (branch `ui-a`)

| ID | P | Ticket | Acceptance |
|---|---|---|---|
| UI-01 | P1 | **Shared theme.** `static/theme.css` with design tokens (colours from the current presentation palette: dark teal surfaces, cream text, gold accent, red/green board colours; spacing scale; type scale; radii; shadows; motion durations) and a system font stack. `/play` and `/control` use it. | No visual regression on `/play` beyond intended changes; tokens documented at the top of the file. |
| UI-02 | P1 | **Lobby and game setup from the controller.** When no match is running, `/play` shows a lobby: "Dart Room" title, "Choose your game" tiles (301, 501 enabled; Cricket, Killer, Shanghai, Around the Clock as "Coming soon"), and the players joined so far with colour + initial avatars. The controller gets a setup flow: add 2–4 players (with recent names as one-tap chips, stored server-side), pick game, options (double out), and **Start**. Camera vs manual is chosen automatically from camera readiness, with a manual override. The Mac setup page's game section keeps working. | A new match can be set up and started from the controller in ≤ 6 taps for 2 recent players; the TV lobby updates live as players are added; tests cover the flow. |
| UI-03 | P1 | **x01 experience.** (a) **Checkout suggestions** when a finish is possible (≤ 170, respecting double-out vs straight-out and darts left in the turn), shown on TV and controller. Use a correct standard checkout table; tests for every score 2–170 with double-out and for straight-out. (b) **Bust** moment on TV (clear "BUST" + score restore). (c) **Game shot / winner screen** with match stats per player: 3-dart average, highest turn, darts thrown, 100+/140+/180 counts, checkout. (d) **Rematch** (same players, next player starts) and **New game** buttons on the controller. | Stats computed server-side from the turn history, unit-tested; win screen screenshot at 1920×1080. |
| UI-05 | P1 | **Controller polish.** Large touch targets (≥ 44 px for main actions), clear camera status chip (Watching / Pending / Reconnecting / Board check needed / Manual), toasts for Undo/correction results, short haptic tap (`navigator.vibrate`) where supported, Screen Wake Lock while a match runs, portrait phone and landscape tablet layouts. Tap board stays fixed (no layout shift — keep the existing tests green). | Browser tests at 360×740, 390×844, 1024×768; no horizontal scroll; layout-shift tests pass. |
| UI-07 | P2 | **TV robustness.** Scales cleanly at 1280×720, 1920×1080, 3840×2160; overscan-safe margins; fullscreen button and Wake Lock; styled reconnect banner; reduced-motion variant. Fix the stale "Maya" expectation in `tests/qa_presentation.cjs` so the browser suite is fully green. | Screenshots at the three sizes; browser suite 17/17. |

## Developer B — Setup, onboarding, sound (branch `ui-b`)

| ID | P | Ticket | Acceptance |
|---|---|---|---|
| UI-06 | P1 | **Setup page redesign as a 3-step flow** in the same visual language as the TV/controller (copy the tokens from `static/presentation.css` into the setup styles for now; they will be unified with `theme.css` at merge). Steps: **1 Connect phone** (IP field, app choice, Test / Connect, live view, plain-English troubleshooting), **2 Calibrate** (freeze, four points with magnifier, overlay check, calibration quality line + warnings, Markers correct), **3 Ready** (big QR codes for the **Controller** and **TV** links plus the links as text, camera position summary, recording toggle and disk space). Step state follows the real camera phase; advanced items (camera position override, phone settings checklist, legacy game controls) go in collapsible sections. Everything that exists today stays reachable. | All existing setup/camera browser tests pass (update selectors only where needed, listed in the commit); a new test walks the 3 steps on the fake IP Webcam; screenshots at 1440×900 and 1280×800. |
| UI-06b | P1 | **QR codes, offline.** Vendor a small MIT/BSD QR encoder into `static/vendor/` (with licence) or write one; render the Controller and Presentation links as QR on the Setup page step 3. | QR decodes back to the exact link (test with a decoder in the test, e.g. OpenCV `QRCodeDetector`). |
| UI-08 | P1 | **First-run experience.** `start-mac.command` opens the Setup page in the default browser automatically on macOS (`open`), prints a short friendly banner, and plain-English errors for: port busy, camera unreachable, Python too old. README "Quick start" rewritten for a non-technical owner (≤ 10 steps, matches the new Setup page). | Manual check of the script on Linux with `open` absent (must not fail); README matches the UI labels. |
| UI-04 | P2 | **Sound, offline.** `static/sound.js`: synthesised with WebAudio (no audio files): dart hit, turn change chime, bust, 180 fanfare, game shot. TV only, starts muted until someone clicks "Sound on" (autoplay rules); mute toggle remembered in localStorage. Expose a tiny API (`DartSound.play('bust')` etc.) and document the event names; do NOT edit `presentation.js` — the coordinator wires the calls at merge. | A test page or unit check that each sound plays without errors in headless Chromium. |

## Rules for both

- Work only in your own worktree/branch. Don't push. Commit per ticket (`UI-0X: …`) with the session trailers.
- Python suite and browser suites must stay green (known "Maya" failure only, until UI-07 fixes it).
- Screenshots of new screens go in `test-output/` (gitignored); the coordinator picks a few for `docs/`.
- If a change needs the other developer's files, stop and tell the coordinator.
