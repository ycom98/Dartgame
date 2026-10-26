# Dart Room: review packet for Claude

Prepared October 26, 2026. Owner/product reviewer: Kapil. Status: local prototype with tested manual gameplay and an animated presentation; physical scoring is unvalidated.

## 1. What Kapil wants from this review

Please give an independent, candid opinion before further implementation. Review the product experience, code, tests, architecture and feasibility of the eventual camera system. Challenge the assumptions and identify weaknesses; passing automated tests should not be treated as proof of production readiness.

Suggested response structure:

1. Your understanding of the intended product and whether the current build serves it.
2. The five most important findings, ordered by severity, with source-file references and concrete examples.
3. Whether the animation/interaction feels deliberately designed and easy to follow; what still feels like a quick prototype.
4. Camera feasibility and the evidence needed before promising reliable automatic scoring.
5. A short, prioritized next-milestone plan, separating work possible now from work requiring the board.
6. A clear verdict: continue with this approach, revise parts of it, or change direction—and why.

This is a read-through/review request. Do not assume permission to deploy, install certificates, access a camera, change the live match or implement more features. You can review without running anything. If you do run it, use a new isolated loopback instance.

## 2. Product vision and confirmed constraints

The intended product is a social darts experience: a phone observes a real board; a Mac runs the local game; a polished shared screen guides the players through the match. Eventually the user should calibrate in roughly a minute and no more than five minutes after initial setup, then play with minimal friction.

Confirmed equipment:

- Winmau Diamond Plus dartboard. **It has not arrived.** No live-board acceptance is possible yet.
- MacBook as local host.
- Samsung Galaxy S22, model **SM-S901U**. An earlier S23 assumption was corrected.
- Mounted phone, entire board visible, rear camera. Main rear lens at 1× is the initial setup suggestion, not a measured best-lens conclusion.

Kapil wants the software to cope with board/phone movement eventually, make calibration readiness obvious, support additional games later, and provide a polished game-selection/dashboard experience. Only 301/501 are currently implemented. “Any games across boards” is a longer-term aspiration, not a completed feature or a sufficiently defined acceptance criterion.

Workflow: developer agent implements and checks; a separate QA agent verifies; Kapil and the coordinating agent perform PM/live review. The QA agents are AI agents, not an external human audit. Kapil has authorized ordinary local implementation/testing. Following the board delay, he explicitly requested all non-camera work first and camera/hardware work last.

## 3. How the work evolved

The starting point was an uploaded `Dart_Game_MVP.zip`. We extracted and worked on the local project, reviewed the Mac setup and phone camera start path, and added clearer startup/permission/network feedback and certificate setup guidance. A disabled camera button was reported on the S22 with “Connection trusted for camera: No” and “Camera access API: Unavailable,” despite an HTTPS address. A local CA/leaf certificate workflow was prepared; trust must be deliberate. Kapil later reported Yes/Available. That report does not establish actual image capture or scoring accuracy.

Once the missing board became clear, work shifted to deterministic rules, manual gameplay, recovery and authentication checks. Several reproduced software issues were repaired: retained Triple selection with Miss/Bull, non-ASCII tokens causing dropped connections, and stale connection-error feedback after recovery.

Kapil then supplied a Flight Club video/Chicago inspiration and requested an audience screen separate from QA/setup. We built audience, host and isolated showcase views. His review of the first version was that it still felt too static and “vibe-coded.” The latest iteration adds a more deliberate sequence: named entrance, individual dart feedback, an animated remaining-score reservoir and count-down, turn total, 180 celebration, recap and next-player entrance.

The packet is a snapshot of the current files, not a Git diff against the uploaded ZIP. No trustworthy commit-by-commit history is available here. Historical docs/screenshots are retained as evidence, and some describe superseded intermediate states.

## 4. What currently works

| Area | Current implementation | Important boundary |
|---|---|---|
| Game rules | 301/501; 2–4 distinct named players; straight/double out; three darts; misses/bulls; bust; undo including turn/win | State/history are in memory only |
| Host `/control` | Manual match setup and legal dart entry; undo; next player; optional four-second handoff with cancel/pause | Scoring is entered by a person |
| Audience `/play` | Read-only shared state, large scores, dart results/map, standings, connection feedback, motion | Map is an illustrative segment position, not physical tracking |
| Demo `/showcase` | Standalone scripted match using Kapil/Aita; autoplay, Pause/Play, Restart, fullscreen | No API requests and no real-match mutation |
| Motion | Score/gauge drain, dart reveal, named turn entrance, turn recap, 180 and win scenes, bust restore | No audio; reduced-motion mode suppresses large animated scenes |
| Recovery | Revision guards for new controller writes, stale-response protection, no blind write retry, paused handoff on network uncertainty | Legacy API callers can omit revision; full production concurrency hardening is not claimed |
| Access | Separate controller and read-only display credentials; display cannot write or obtain camera images | Small local development server, not public hosting |
| Camera prototype | Browser rear-camera flow, local uploads, calibration/overlay, experimental alignment and score proposals | Physical accuracy, capture stability and movement recovery remain unvalidated |

The old root/phone setup remains available. Camera/calibration controls are kept outside the audience presentation. Controller input is not covered by full-screen animation overlays.

### The exact requested animation example

Starting at 301, Kapil hits three triple twenties:

| Moment | Dart points | Turn points | Remaining | Reservoir remaining |
|---|---:|---:|---:|---:|
| Turn entrance | — | 0 | 301 | 100% |
| Dart 1: T20 | 60 | 60 | 241 | about 80% |
| Dart 2: T20 | 60 | 120 | 181 | about 60% |
| Dart 3: T20 | 60 | 180 | 121 | about 40% |

The display counts toward the accepted score, reveals the dart, shows a large 180 scene, recaps “121 remaining,” then introduces the next player when the turn advances. Live turn advancement belongs to the host, optionally after its four-second countdown. The showcase supplies its own local scripted timing (roughly 2.7-second dart beats and 5.5-second completed-turn dwell), using the same renderer.

The reservoir divides remaining points by the original 301/501 start, not the current turn-start score. A bust restores the turn-start value and banks zero. Undo/newer state cancels stale effects. Identical poll results do not recreate the score display or replay the entrance. Batched rapid state changes resolve to the latest score rather than inventing unseen individual throws. Pause freezes the demo's score tween, stage lifetime, CSS animation and script timeline; Restart resumes from the beginning.

## 5. Visual direction and references

Kapil's reference: [Flight Club short](https://www.youtube.com/shorts/W3CFioenVDo). Additional atmosphere reference: [Flight Club Chicago](https://www.flightclubdartsusa.com/chicago/).

These informed a social-game screen with warm cream/gold/red details, dark teal surfaces, strong score hierarchy, player identities and readable turn guidance. Dart Room uses its own branding; this is not an exact recreation of Flight Club's proprietary interface. We reviewed the supplied short, but it is not a complete product specification or a frame-by-frame motion study.

Start with these latest screenshots (all included in the ZIP):

- `project/qa-artifacts/presentation-animation-kapil-entrance-1920.png`
- `project/qa-artifacts/presentation-animation-settled180-1920.png`
- `project/qa-artifacts/presentation-animation-settled180-320.png`
- `project/qa-artifacts/presentation-animation-showcase-maximum180.png`
- `project/qa-artifacts/presentation-animation-showcase-handoff.png`
- `project/qa-artifacts/presentation-animation-control-1920.png`

Screenshots demonstrate layout, not motion quality by themselves. Run `/showcase` on an isolated instance to assess timing. No animation video is included: optional recording was unavailable because the local Playwright ffmpeg binary was missing. It was not installed for this review.

![Latest 180 scene](project/qa-artifacts/presentation-animation-showcase-maximum180.png)

## 6. Architecture and source reading order

No frontend framework or cloud service is used. Python's `ThreadingHTTPServer` serves static HTML/CSS/JavaScript and a JSON API. OpenCV/NumPy support the experimental vision path. The browser polls live game state about once per second. This architecture makes local experimentation straightforward; it has not been demonstrated to meet commercial operational needs.

| Read order | File | Responsibility |
|---:|---|---|
| 1 | `project/core.py` | Deterministic game transitions and board geometry |
| 2 | `project/server.py` | Local server, authentication, API, revision/state and routes |
| 3 | `project/static/presentation.js` | Shared display renderer, motion cancellation/pause, polling and requests |
| 4 | `project/static/presentation.css` | Layout, score instrument, entrances/celebrations, responsive/reduced-motion styles |
| 5 | `project/static/control.js` | Manual host state, mutations, duplicate-click guard, handoff and connection health |
| 6 | `project/static/showcase.js` | Isolated scripted snapshots and playback timeline |
| 7 | `project/static/index.html` | Legacy host/phone, startup feedback and calibration UI |
| 8 | `project/vision.py` | Image ingestion, calibration, ORB alignment, experimental dart proposal |
| 9 | `project/local_https.py` | Local CA/leaf generation and bounded public-certificate setup helper |
| 10 | `project/start-mac.command` | Python environment/dependency setup and launch |

`SOURCE_REVIEW.md` contains the runtime source concatenated into one Markdown file for convenient model ingestion. The original file layout is in `project/`, with all test sources and historical docs. Source files are copied unchanged; copied documentation/evidence have share-only credential/path sanitization described in `PACKAGE_NOTES.md`.

### Camera approach to scrutinize

The vision prototype uses a four-point perspective mapping, a saved reference, feature-based realignment with confidence gates, stable-frame/background differencing, contour filtering and a PCA endpoint guess. The guessed endpoint nearer the board center is not a demonstrated reliable dart-tip detector. Occlusion, wire hits, shadows, lighting, overlapping darts, changing perspective and ordinary motion can defeat this method. Every proposed score requires human confirmation/correction; it is not unattended automatic scoring.

The software has explicit phases such as waiting for camera, ready to calibrate, calibrating, overlay review, needs alignment and ready. “Ready” means freshness/alignment/verification gates passed, not that an accuracy benchmark passed.

## 7. Test evidence and how much confidence to place in it

Latest independent animation report: `project/PRESENTATION_ANIMATION_QA.md`. Earlier feature report: `project/PRESENTATION_QA.md`. Earlier complete manual-game journeys: `project/QA_REPORT.md`.

- Latest Python regression suite: **48/48 pass**. Earlier stages had 43; do not add these counts together.
- Latest animation browser suite: **9 groups pass**, covering actual per-dart intermediate/final drains, 301/501 gauge denominator, unchanged-poll stability, handoff/undo, bust/win correction, rapid state updates, reduced motion, pause/restart/isolation, host repaint/input and responsive layouts.
- Earlier presentation checks: nine main browser groups, three resilience groups, four PM-focused groups and two fullscreen-denial/unsupported groups passed at that stage. These are historical stage results, not a claim that every earlier browser runner was rerun after the final CSS/JS iteration.
- Earlier five manual browser journeys exercised complete 301/two-player, 501/four-player, double-out/three-player, recovery/validation and input/authentication behavior.
- Developer separately reported 318 API/rules assertions and focused browser/recovery checks. Those are developer evidence, not 318 additional independent tests.
- Latest scope reports zero browser errors, spectator mutation requests and media access; the showcase performs zero API traffic. Layout checks cover 320/736/1280/1920 widths. Phones intentionally scroll vertically.
- Tests use fresh browser profiles, isolated temporary loopback servers and generated game state. Physical camera work is not implied by synthetic/mocked or rules/geometry tests.
- PM separately checked deployed static-file hashes over CA/hostname-verified HTTPS, visually reviewed actual showcase/screenshots, and preserved existing live state.

Current machine-readable evidence: `presentation-animation-results.json`, `presentation-animation-python-results.txt` and `presentation-animation-deployment.json` under `project/qa-artifacts/`. Other evidence is included for traceability; files marked baseline may intentionally show earlier failures. Use dated final reports to interpret them.

These tests do not establish long-duration reliability, broad device/browser compatibility, WCAG conformance, real TV viewing-distance legibility, physical camera accuracy, calibration timing or production security.

## 8. Known limits and unresolved risks

1. **Hardware evidence missing.** No board means no accepted real dart detection, calibration duration, lens choice, reconnect trial or movement recovery result.
2. **In-memory state.** Restart loses the game/history. No persistence, resume, accounts, statistics or online multiplayer.
3. **Local development architecture.** No claim of Internet-safe deployment, load testing, process supervision or operational monitoring. Shared bearer links and compatibility with legacy unversioned writes deserve review.
4. **Maintainability.** Several JavaScript/CSS files are dense and compact, and the renderer uses HTML replacement with motion state/timers. Review testability, lifecycle cancellation, performance and whether targeted refactoring would improve confidence. Do not infer code quality from appearance alone.
5. **Test portability.** Browser scripts reference this Mac's Chrome/Playwright paths and need adaptation elsewhere. Python dependency ranges are bounded but not an exact lockfile. The package does not include installed runtimes.
6. **Camera ingestion backlog.** Earlier logs showed an empty/aborted upload reaching OpenCV's empty-buffer assertion and a broken pipe on a disconnected client. This was recorded for the deferred ingestion phase; no subsequent fix or physical retest is claimed.
7. **No broad game catalog.** 301/501 only. The aspiration for “any game” needs a rules/plugin model and concrete priorities later.
8. **UX not finally accepted.** Kapil asked for richer animation after the first UI. The new sequence is implemented/tested, but his final aesthetic and real-play acceptance is still pending. No sound design or user research has been completed.
9. **Documentation chronology.** Some historical README/checkpoint sections talk about older milestones or next steps. This overview and the latest animation report describe the current status; older camera plans do not override the instruction to defer hardware work.

## 9. Safe isolated review instructions (optional)

From an extracted `project/` folder with Python 3.10+:

```sh
python3 server.py --host 127.0.0.1 --http --port 8555
```

Choose a free port if necessary. This loopback/manual path can work without the optional camera dependencies. Open the freshly printed Showcase URL for animation review, Controller URL for manual scores, and Presentation URL for the read-only screen. Keep generated controller credentials private. This creates a separate empty game; do not use an existing live host's credentials.

To run the full Python suite with camera-related dependencies in a new local environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B -m unittest discover -s tests -v
```

Installation requires package downloads. Browser test scripts additionally need Node, Playwright, Chrome and path adjustment. The archived test output describes runs already performed; no new tests were run just to package these files.

The phone camera requires trusted HTTPS and is deliberately outside this review run. The Mac launcher can create a new local CA for a separate copy, but the packet excludes the existing CA/private keys. Do not install trust or disable certificate validation just to review the UI.

## 10. Recommended decision after Claude's review

Pause further feature expansion until Kapil has reviewed Claude's findings. Fix concrete critical correctness/security/maintainability issues first, and agree whether the new game sequence meets the visual expectation. Once the board arrives, plan a measured hardware trial: framing/light, known hits/misses, overlapping darts/removal, manual corrections, disconnect/reconnect, movement/overlay verification, and timed calibration. Define acceptance thresholds before claiming automatic scoring. Additional games and the larger dashboard follow that evidence and a scoped product decision.

## 11. What is in this packet

- This standalone read-through and ready-to-copy critique request.
- Runtime source, test sources, dependencies/launcher, requirements/milestone/design documents.
- All current stored QA reports, text/JSON artifacts and PNG screenshots, including clearly historical evidence.
- A single-file runtime source appendix and a manifest with SHA-256 hashes.
- The earlier interactive design concept as historical context, when available.

Excluded: `.local/` (all certificates/private keys and local state), `.venv/`, caches/compiled files, active controller/viewer credentials, original-upload archive, process state and browser profiles. No live camera frames or live match export were collected for this packet. The package was created without stopping either existing server or changing game state.
