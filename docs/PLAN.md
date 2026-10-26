# Dart Room — Delivery Plan (M1 → M3)

Owner: Kapil · PM plan written Mon 26 Oct 2026 · Board (Winmau Diamond Plus) arrives Thu 29 Oct 2026.

Status of this document: approved decisions from the owner are baked in; items marked **[Owner?]** need a decision (see §5).

---

## 1. Product summary and "concept proven"

**Product.** A home darts night for 2–4 players. A Samsung Galaxy S22 (SM-S901U) is mounted off-axis near a real steel-tip board and streams video over the home LAN (IP Webcam app, MJPEG over HTTP; DroidCam as fallback). A MacBook runs everything offline: it pulls frames, detects each dart, and runs the rules engine (301/501 in V1). A host uses `/control` (phone, tablet or laptop) to confirm or correct each dart with one tap. A PC/TV opens `/play` for the Flight Club-style animated scoreboard. Later we add more games (Cricket, Killer, Shanghai, Snakes & Ladders…) and a game-selection dashboard.

**What we keep:** `core.py` rules, the `/play` presentation and animations, the `/control` host controller, and the revision-guarded API.
**What changes:** camera ingest (pull a stream instead of pushing frames from the phone browser), the dart-tip rule, multi-dart turn tracking, lock structure, persistence, a game-mode interface, tap-to-score, and readable JS/CSS.

### Definition of "concept proven" (acceptance for the Thursday/Friday hardware trial)

All of the following must hold at **one chosen mount position**, normal room lighting plus any agreed added light, on the real board, with the owner throwing:

| # | Criterion | Threshold |
|---|---|---|
| C1 | Exact-score accuracy of camera proposals (e.g. T20 ≠ S20 ≠ D20) on darts that stay in the board, excluding deliberate stacked or touching darts | **≥ 95 %** on **≥ 100** labelled throws |
| C2 | Accuracy on deliberately stacked or touching darts (reported separately) | ≥ 80 % (target only, does not decide pass/fail) |
| C3 | Missed detections: a dart in the board with no proposal | ≤ 3 % |
| C4 | False proposals: a proposal where no new dart is in the board (people in frame, pulling darts, bounce-outs, lighting change) | ≤ 2 per 100 throws |
| C5 | Correction cost | A pending wrong or missing dart is fixed with **1 tap** on the controller's board. A dart that is already committed is fixed with ≤ 2 taps |
| C6 | Calibration time, from phone on its mount with the stream running to "Ready" | **< 2 min** median over 3 attempts by the owner, with no help |
| C7 | Detection latency, from the dart landing to the proposal showing on `/control` | ≤ 1.5 s median, ≤ 2.5 s p95 |
| C8 | Turn flow | Pulling darts is detected as "board cleared" within 3 s, without losing alignment or needing recalibration |
| C9 | Resilience | A 10 s Wi-Fi drop on the phone recovers automatically in ≤ 10 s without recalibration. A phone bump is detected (never silent wrong scores) and recovered by realignment or a guided recalibration |
| C10 | Restart | Killing and restarting the server mid-match resumes the identical match state and revision |

If C1 fails but C5 passes, the product still works with "camera-assisted" scoring. In that case we decide in M2 whether to tune further, add a second camera, or ship assisted mode (see §5).

---

## 2. Milestone M1 — "Before the board" (Mon 26 – Wed 28 Oct)

### Conventions for every ticket

- One developer agent works through tickets in order. A separate QA agent verifies each ticket against its acceptance criteria.
- **Standing criterion for every ticket after M1-01:** the full Python suite and all browser suites pass with the single commands defined in M1-01. Any test whose expectation changes on purpose is updated in the same ticket and listed in the ticket's commit message.
- Evidence goes in `qa-artifacts/` with the ticket ID in the filename (for example `qa-artifacts/M1-03-detection-baseline.json`).
- No ticket changes the look of `/play` or `/showcase` unless the ticket says so.
- Board coordinates are those of `core.py`: millimetres, origin at the bull, +x right, +y down (20 at the top), +z out of the board toward the thrower.
- **Schedule:** Mon pm: M1-01 to M1-04. Tue: M1-05 to M1-10. Wed: M1-11 to M1-17. **Cut line:** M1-15 and M1-16 may slip to Thursday morning or after the trial without blocking it. M1-01 to M1-08 and M1-11 to M1-14 are required before the board arrives. M1-17 is the go/no-go for Thursday.

---

#### M1-01 — Portable test bootstrap
- **Why:** Browser tests hard-code `/Users/kapilgandhi/...` Playwright and `/Applications/Google Chrome.app`. OpenCV is not installed in the dev container. QA cannot verify anything until tests run here and on the Mac.
- **Scope:**
  - Create `.venv` and install from `requirements.txt` (pip works through the proxy).
  - Replace hard-coded `require(...)` paths with `require('playwright')`, and `chromium.launch({executablePath…})` with `chromium.launch()`. An env var `DART_CHROME` is an optional override for the Mac.
  - Spawn the Python server from `process.env.DART_PYTHON || <root>/.venv/bin/python`.
  - Add `scripts/test.sh` with two entry points: `scripts/test.sh py` runs `unittest discover`, and `scripts/test.sh browser` runs every `tests/*.cjs` that is a runnable suite (it skips `manual_qa_common.cjs`) and exits non-zero on any failure.
  - Add a README "Running tests" section of 5 lines or fewer.
- **Files:** `tests/*.cjs`, new `scripts/test.sh`, `README.md`.
- **Depends on:** —
- **Acceptance:**
  1. `grep -rn "/Users/\|/Applications/" tests/` returns nothing.
  2. On this container, `scripts/test.sh py` reports 48 tests passing (or the current count, recorded in the artifact).
  3. `scripts/test.sh browser` runs every suite, and failures are reported per suite. Any suite that fails for reasons unrelated to paths is listed in `qa-artifacts/M1-01-baseline.json` with its reason, and is not hidden.
  4. No runtime code changes (`git diff --stat` touches only tests, scripts, README).

#### M1-02 — Synthetic board and dart scene renderer
- **Why:** This is the riskiest part of the product. We need repeatable images with known truth before hardware arrives.
- **Scope:** New package `sim/`:
  - `board.py`: renders a top-down board texture at ≥ 4 px/mm using the `core.py` radii and `SECTORS`. It includes black/cream singles, red/green doubles and trebles, ~1 mm wires, the number ring to r≈225 mm and a dark surround.
  - `camera.py`: a pinhole camera from position, look-at point, roll, resolution and HFOV, with an optional radial distortion k1. It returns K, R, t and the plane homography.
  - `scene.py`: places N darts. Each dart has a tip on the board plane at (x, y, 0) and a body: point, barrel (~47×7 mm), shaft and a cross-shaped flight (~38 mm wide). Total protrusion is 110–140 mm, tilted 5–30° from the normal, mostly "tail up". Darts are drawn nearest-last. Optional degradations: Gaussian noise, blur, JPEG quality, brightness/contrast change and a hard shadow cast from a configurable light direction.
  - Output: a frame (BGR ndarray), the image points of the four calibration points (20/6/3/11 on the outer double edge, r = 170, as `vision.TARGETS` expects), and labels per dart (tip x/y, `score_point` label, `near_wire`).
  - Standard mount set `MOUNTS` (camera position in mm, looking at the bull): `top (0,-450,500)`, `bottom (0,450,500)`, `left (-450,0,500)`, `right (450,0,500)`, `steep-topleft (-300,-500,350)`, `near-frontal (150,-200,1200)`. Default 1920×1080, HFOV 70°.
- **Files:** new `sim/__init__.py`, `sim/board.py`, `sim/camera.py`, `sim/scene.py`, `tests/test_sim.py`.
- **Depends on:** M1-01.
- **Acceptance:**
  1. Unit test: projecting the board point (0, -135) (the S20 centre) with the camera and mapping it back through the inverse plane homography returns it within 0.5 mm, for every mount.
  2. Unit test: the label for each rendered dart equals `score_point(tip)`.
  3. `python -m sim.preview --mount left --darts 3 --out qa-artifacts/M1-02-left.png` writes an image. QA eyeballs it for a board with 20 at the top and three plausible darts.
  4. Rendering is deterministic for a given `--seed` (byte-identical PNG).

#### M1-03 — End-to-end detection harness and baseline
- **Why:** This measures the real `vision.py` pipeline rather than a simplified simulation. The baseline confirms or refutes the ~20 % error found for the current "nearer centre" rule.
- **Scope:** `tools/eval_detection.py`. For each mount:
  1. Render an empty board and calibrate `Vision` using the projected calibration points plus optional click noise (σ px). Verify.
  2. Ingest ≥ 3 identical empty frames to establish the base.
  3. For each trial, render one dart, ingest ≥ 4 frames (so the stability gate passes), read `vision.proposal`, compare it with the truth, then reset the base.

  Profiles: `ideal` (no degradations, no click noise) and `realistic` (noise σ=4, blur 1 px, JPEG q80, ±15 % brightness, click noise σ=2 px). Flags: `--mounts`, `--darts`, `--seed`, `--profile`, `--out`.

  The JSON report gives, per mount: exact-score accuracy, wrong-sector / wrong-ring / no-proposal rates, tip error (median/p95, mm), accuracy for near-wire darts versus the rest, and wall-clock time per frame. The harness also accepts recorded real footage via `--recording DIR` later (stubbed with "not implemented" until M1-14).
- **Files:** new `tools/eval_detection.py`, `tests/test_eval_harness.py` (a smoke test with 10 darts).
- **Depends on:** M1-02.
- **Acceptance:**
  1. `python tools/eval_detection.py --profile ideal --darts 200 --seed 1 --out qa-artifacts/M1-03-detection-baseline.json` completes in under 5 min on this container.
  2. The report contains every metric above for all 6 mounts.
  3. The baseline numbers are copied into the ticket's commit message (expected: clearly below 95 % on off-axis mounts). This ticket does not change `vision.py`.
  4. Smoke test runs in under 30 s inside the Python suite.

#### M1-04 — Camera pose and foot point from calibration
- **Why:** The correct tip rule needs the camera's foot point: the perpendicular projection of the camera centre onto the board plane.
- **Scope:** `vision_pose.py` (pure functions):
  - Build G, the board-mm → image homography (`inv(H)` composed with the mm→warp scaling).
  - Assume square pixels and a principal point at the image centre. Solve the focal length f in closed form from the r1⊥r2 and |r1|=|r2| constraints, with least squares over both.
  - If f falls outside [0.4w, 2.5w] or is ill-conditioned (near-frontal), fall back to `--camera-hfov` (default 70°).
  - Recover R and t, then C = −Rᵀt. The foot point is (C.x, C.y) in mm and C.z is the camera height off the plane.
  - Store `vision.pose = {f, C, foot, source: 'solved'|'fallback'|'manual'}`.
  - A manual override `mount_side ∈ {top, bottom, left, right}` places the foot point 2 m out on that axis (the "simple calibration step" fallback).
  - Expose `foot` and `mount_side` in `vision.state()`.
- **Files:** new `vision_pose.py`, `vision.py` (call after `calibrate()` and `align()`), `tests/test_pose.py`.
- **Depends on:** M1-02.
- **Acceptance:**
  1. On all 6 synthetic mounts with exact calibration points, the recovered foot point direction (angle from the bull) is within 2° and the distance within 10 %.
  2. With σ=2 px click noise over 50 seeds, the direction error is ≤ 10° at p95 for the 4 off-axis mounts. The `near-frontal` result is reported, not gated.
  3. A pose that cannot be solved falls back without raising, and `state()['pose']['source']` says so.

#### M1-05 — Foot-point tip rule and tip bias correction
- **Why:** This is the core accuracy fix (approved). The off-plane dart body projects away from the foot point, so the tip is the blob endpoint nearer the foot point.
- **Scope:**
  - In `vision.py`, replace `tip = min(ends, key=…CENTER)` with `tip = min(ends, key=distance to foot point in warp px)`.
  - Add a configurable `TIP_BIAS_MM`, which extends the chosen endpoint along the blob axis toward the foot point. Its default comes from the harness median signed error, and it is recorded in the code with the harness run that produced it.
  - If the blob is not elongated (ratio < 3, a dart pointing at the lens), use the blob pixel nearest the foot point instead of rejecting it, and set `confidence: 'low'`.
  - Add `confidence` and `rule` to the proposal.
  - Keep the old rule selectable for the harness (`rule='centre'`).
- **Files:** `vision.py`, `tools/eval_detection.py` (adds `--rule`), `tests/test_qa.py` (adds or adjusts tests).
- **Depends on:** M1-03, M1-04.
- **Acceptance:** with `--darts 200 --seed 1`, for each of the 4 axis mounts plus `steep-topleft`:
  1. `ideal`: ≥ 99 % exact score.
  2. `realistic`: ≥ 95 % exact score, and at least 10 points better than `--rule centre` on the same seed.
  3. Tip error median ≤ 2 mm and p95 ≤ 5 mm (`ideal`).
  4. The report is saved as `qa-artifacts/M1-05-detection.json`, and the `near-frontal` and shadow-on results are reported.
  5. Existing vision tests (stationary board never proposes, alignment and invalidation tests) still pass.

#### M1-06 — Split the global lock; a background vision worker
- **Why:** `server.py` holds one `RLock` across game writes, `/api/state`, image encoding and ORB `align()`. A slow alignment freezes `/api/state` polling and the TV. A pulled stream also needs a long-lived worker thread.
- **Scope:**
  - `App.game_lock` protects only the game and revision.
  - `Vision` owns its own lock and publishes an immutable `state_snapshot` dict, replaced atomically after each processed frame or action.
  - `/api/state` reads the game under `game_lock` (fast) plus the latest vision snapshot without taking the vision lock.
  - Frame processing (`ingest`) and `align()` run on a single vision worker thread. API vision actions (calibrate, align, verify, reset) are queued to it and wait on a future with a timeout of ≤ 10 s.
  - A camera-proposal commit reads the proposal snapshot under the vision lock, then commits under the game lock. Locks are never nested in the opposite order.
  - Image endpoints encode a copy outside both locks.
- **Files:** `server.py`, `vision.py`, `tests/test_concurrency.py`.
- **Depends on:** M1-05 (to avoid conflicting `vision.py` edits).
- **Acceptance:**
  1. A test monkeypatches `Vision.align` to sleep 2 s, starts it via `/api/align`, and meanwhile issues 20 `/api/state` requests. Each returns in < 100 ms and shows the pre-align state.
  2. A manual `/api/throw` during that sleep succeeds in < 100 ms.
  3. There is no deadlock in a 30 s stress test: 4 threads mixing state, throw, undo and align.
  4. The existing suite passes.

#### M1-07 — Pull-based frame sources (IP Webcam, DroidCam, file, folder)
- **Why:** This replaces the browser camera, which requires HTTPS and a phone-trusted CA (approved). Recorded or replayed footage uses the same path.
- **Scope:** `camera_source.py` with a `FrameSource` interface (`start()`, `stop()`, `latest() -> (frame, ts, seq)`, `status()`):
  - `MjpegSource(url)`: a stdlib `urllib` multipart/JPEG parser that keeps the **latest frame only** (no buffering lag) and reconnects with backoff 1 → 5 s. It works with IP Webcam `http://PHONE:8080/video` and DroidCam `http://PHONE:4747/video`.
  - `SnapshotSource(url, fps)`: polls IP Webcam `/shot.jpg`.
  - `VideoFileSource(path, realtime=True|False)`.
  - `ImageFolderSource(dir, fps)`.
  - A URI form for `--camera`: `http(s)://…`, `snapshot:http://…/shot.jpg`, `file:path.mp4`, `dir:path/`.
  - The vision worker (M1-06) consumes `latest()` at up to 15 fps.
  - `state()['vision']['source']` reports `{kind, url_redacted, fps, last_frame_age, reconnects, connected}`.
  - Runtime switching via `POST /api/camera/source {uri, expected_revision}` (controller auth).
  - Frames larger than 1920 px on the long side are downscaled instead of rejected.
  - `/api/frame` (the push path) stays available for tests only.
- **Files:** new `camera_source.py`, `server.py` (CLI `--camera`, endpoint), `vision.py` (accept ndarray frames), new `tests/test_camera_source.py` (includes a stdlib stub MJPEG server serving `sim` frames).
- **Depends on:** M1-06.
- **Acceptance:**
  1. Against the stub MJPEG server at 15 fps, `/api/state` shows `connected: true`, `fps ≥ 12` and `last_frame_age < 0.5 s`.
  2. Kill the stub and the state shows disconnected within 5 s. Restart it and frames resume within 6 s, with calibration kept (alignment check passes on the identical scene).
  3. Frames processed by vision lag the stub's latest frame by at most 1 frame, measured by frame sequence numbers embedded in the stub images.
  4. `dir:` and `file:` sources replay a sim sequence and produce the same proposals as feeding the frames directly.
  5. The server starts with `--camera` and no HTTPS or OpenSSL.

#### M1-08 — Turn-aware multi-dart tracking (3 darts, occlusion, pulling, bounce-outs)
- **Why:** Today the base resets only after a commit. If a player throws three darts without the host confirming in between, darts 2 and 3 show up as "Ambiguous". A person reaching in to pull darts changes >12 % of pixels, which **invalidates calibration**. That makes real play impossible.
- **Scope:** a vision state machine per turn:
  - `turn_base` is the empty-board frame at the start of the turn, and `last_base` is the frame after the latest accepted dart.
  - A stable single new blob against `last_base` becomes a pending detection `{id, seq, label, x, y, confidence, near_wire, ts}` (up to 3). `last_base` then rolls forward automatically, with no host action needed.
  - A large change becomes the `occluded` phase, which is **not** invalidation. Once the scene is stable again:
    - diff vs `last_base` is small → resume;
    - diff vs `turn_base` is small → emit a `board_cleared` event and start a new `turn_base`;
    - otherwise run the ORB alignment check: if the board moved, go to `needs_alignment`; if it did not, report "unexpected change", with no proposal.
  - Bounce-out: if the region of a pending detection reverts to `last_base` within 3 s, retract that detection (`retracted: true`).
  - Detections outside r>172 mm are ignored (misses are entered by the host).
  - Pending detections are exposed as `vision.pending[]`. The single `proposal` is kept as an alias of the oldest pending detection for backward compatibility until M1-12.
  - Extend the harness with `--sequence`. Each turn throws 3 darts, inserts 5 "hand in frame" frames (a large skin-tone polygon), then removes the darts. The report adds sequence metrics: per-dart accuracy, false proposals, board-cleared detection rate and retraction rate.
- **Files:** `vision.py`, `tools/eval_detection.py`, `sim/scene.py` (hand occluder, dart removal), `tests/test_qa.py` (the "large scene change invalidates" test changes to "large change → occluded; moved board → needs_alignment").
- **Depends on:** M1-07.
- **Acceptance** (harness `--sequence --turns 50 --profile realistic`, mounts top, left and right):
  1. Per-dart exact-score accuracy is within 2 points of M1-05 single-dart results for the same mount.
  2. 0 false proposals during hand-occlusion and removal frames.
  3. `board_cleared` is detected on ≥ 98 % of turns.
  4. Calibration is never invalidated by occlusion alone. A synthetic 15 px board shift does reach `needs_alignment`.
  5. A synthetic bounce-out (a dart present for 1 s, then removed) ends with 0 committed or pending detections.

#### M1-09 — Reformat JS/CSS/HTML into readable files (no behaviour change)
- **Why:** `control.js`, `presentation.js`, `presentation.css`, `index.html` and the HTML shells are minified-style one-liners. M1-11 to M1-13 edit them heavily.
- **Scope:**
  - Pretty-print (2-space indent, one statement per line).
  - Split `index.html`'s inline script and style into `static/setup.js` and `static/setup.css`.
  - Add short section comments.
  - No identifier renames or logic edits beyond what moving the code requires.
  - Register new static files in `server.py`'s `public` map.
- **Files:** `static/*`, `server.py` (static routes only).
- **Depends on:** M1-01 (needs the browser suites as a safety net).
- **Acceptance:**
  1. All browser suites pass unchanged.
  2. Screenshot diff at 1920 and 320 widths for `/play` (mid-match), `/control` and `/showcase` paused at a fixed step, before vs after: ≤ 0.1 % differing pixels. Images and the report go to `qa-artifacts/M1-09-*`.
  3. No line over 160 chars in `static/*.js` and `static/*.css`.
  4. `git diff -w --stat` shows the server change limited to the static route map.

#### M1-10 — Write hardening and proposal identity
- **Why:** Writes without `expected_revision` are accepted, so legacy callers can clobber state. `start=301.0` or `True` passes `start in (301, 501)`. `/api/throw {proposal:true}` commits whatever proposal exists *at that moment*, which may differ from what the host saw.
- **Scope:**
  - Every POST except `/api/frame` requires an int `expected_revision` equal to `app.revision`: 400 if missing or not an int, 409 with the current state if stale. This includes `/api/game`, the camera and calibration endpoints and `/api/camera/source`.
  - `Game` rejects a `start` that is not an int (`type(start) is not int`).
  - Camera commits use `{proposal_id}`. The server commits only if that id is still pending; otherwise it returns 409 "Proposal changed".
  - Update `control.js` and `setup.js` callers, and the tests.
- **Files:** `server.py`, `core.py`, `static/control.js`, `static/setup.js`, `tests/test_*.py`, `tests/*.cjs`.
- **Depends on:** M1-08, M1-09.
- **Acceptance:**
  1. API tests: each write endpoint without `expected_revision` → 400; with a stale value → 409 and the state is unchanged.
  2. `start` values 301.0, "301", true and 401 → 400.
  3. Committing a proposal id that was replaced or retracted → 409 and no throw is recorded.
  4. All browser suites pass.

#### M1-11 — Tap-the-board manual scoring on the controller
- **Why:** This is the fast fallback for every dart and the base for one-tap correction (approved).
- **Scope:**
  - `/control` gains a large SVG board (reusing the board drawing from `presentation.js`, extracted to a shared `static/board.js`). Each of the 82 regions is a hit target: 20×{S-inner, T, S-outer, D}, outer bull and bull. Inner and outer singles map to the same score.
  - A "Miss" button sits beside the board.
  - Tapping a region records one dart through `/api/throw` with `expected_revision`, and shows a brief highlight.
  - The existing select-based entry stays as a collapsible "Keypad entry" fallback.
  - Hit targets must be ≥ 24 px at 360 px width. The narrow treble and double rings are widened in the hit layer, not the visual layer.
  - The existing 600 ms duplicate-tap guard still applies.
- **Files:** new `static/board.js`, `static/control.js`, `static/control.html`, `static/presentation.css` (host-only rules), `static/presentation.js` (imports the shared board; no visual change).
- **Depends on:** M1-10.
- **Acceptance** (new Playwright suite `tests/qa_tap_board.cjs`):
  1. Tapping the centroid of every one of the 62 scoring regions (20×S, 20×D, 20×T, 25, 50) records the matching dart, verified via `/api/state`, across a scripted series of turns.
  2. Miss records 0.
  3. Double-tapping within 600 ms records one dart.
  4. At 360×740 every region's hit box is ≥ 24×24 px.
  5. The `/play` screenshot diff (as in M1-09) is unchanged.

#### M1-12 — Camera proposals on the controller with one-tap correction
- **Why:** Concept criterion C5. Today camera confirmation lives only on the legacy `/` page, and `/control` disables entry in camera games.
- **Scope:**
  - In a camera game, `/control` shows the pending detections (from M1-08) as numbered markers on the tap board, plus chips "Dart n: T20 ✓".
  - **Accept** commits the oldest pending detection by `proposal_id`. **Accept all** commits all pending detections in order.
  - **Correction in one tap:** while a detection is pending, tapping any board region commits that value *instead of* the oldest pending detection, using `{value, multiplier, replaces_proposal_id}` (the server drops that detection), and records the correction in the event log (used later as labels).
  - Missing dart: the host taps the region and it commits as a manual dart (one tap).
  - Committed dart: tap its chip, then tap a region. The server performs `/api/correct {dart_index, value, multiplier, expected_revision}` on the current turn, implemented as undo-to-that-dart plus replaying the remaining darts. That is 2 taps.
  - Optional **Auto-accept after N s** (default off; see §5).
  - Remove the `camera_game` disabling of manual entry.
- **Files:** `static/control.js`, `static/control.html`, `static/board.js`, `server.py` (`/api/correct`, `replaces_proposal_id`), `core.py` (or the x01 mode after M1-15: a pure replay helper), `tests/qa_camera_controller.cjs`, `tests/test_correct.py`.
- **Depends on:** M1-11.
- **Acceptance** (server driven by a `dir:` sim sequence with a known wrong detection injected):
  1. A pending detection appears on `/control` ≤ 1.5 s after the frame containing the dart is served.
  2. Accept commits exactly that detection (verified by id).
  3. One tap on a different region commits the tapped value and the detection is no longer pending.
  4. Correcting committed dart 1 of 3 changes only that dart, recomputes the score, bust and win correctly (including a correction that turns a bust into a non-bust), and increments the revision once.
  5. Every correction appears in the event log.
  6. `/play` never shows pending (unconfirmed) detections.

#### M1-13 — Mac camera setup page; HTTP-on-LAN default; retire the phone-browser and HTTPS path
- **Why:** The phone no longer runs our web page, so the local CA, trust setup and `getUserMedia` flow are dead weight and a setup hazard. Calibration must take < 2 min (C6).
- **Scope:**
  - `/` becomes a Mac **Camera setup** page with:
    - a source URI field with presets (IP Webcam `/video`, DroidCam `/video`, and a "Test connection" button);
    - a live preview from `/api/image` at ~5 fps;
    - "Freeze and set four points", where the image is clicked at 20, 6, 3 and 11 on the outer double edge, with a magnifier loupe at the cursor;
    - an overlay drawing every ring and sector line (not only 4 markers) for verification;
    - a foot-point and mount-side indicator, with a manual override (M1-04);
    - Verify;
    - a phone settings checklist (resolution 1280×720 or 1920×1080, focus locked, exposure locked, stabilisation off, keep screen awake, plugged in).
  - Delete the phone `getUserMedia` and upload UI.
  - Server: HTTP becomes the default and LAN binding is allowed without `--http`. `--https` keeps the `local_https` path as optional; its tests run only for that path.
  - `start-mac.command` drops the OpenSSL requirement and prints Controller, Presentation and Setup URLs.
  - Rewrite the README quickstart for IP Webcam.
- **Files:** `static/index.html`, `static/setup.js`, `static/setup.css`, `server.py`, `start-mac.command`, `README.md`, `tests/qa_camera_startup.cjs` (rewrite), the certificate tests (gated).
- **Depends on:** M1-12.
- **Acceptance:**
  1. `python3 server.py --camera dir:<sim seq>` starts without OpenSSL and serves on 0.0.0.0.
  2. A Playwright script completes source → freeze → 4 clicks → verify against a sim stream, and reaches phase `ready` with 7 user actions or fewer. The overlay ring at r=170 lands within 3 px of the sim's projected ring.
  3. No `getUserMedia` reference remains in `static/`.
  4. `--https` still starts with the existing certificate tests passing.
  5. The README quickstart takes ≤ 10 steps from a fresh Mac to a running match.

#### M1-14 — Recording, labelling and replay
- **Why:** The Thursday trial must produce labelled footage that the harness can replay, so that tuning (M2) is offline and repeatable.
- **Scope:**
  - `--record DIR` (also toggled in setup) writes:
    - received JPEG bytes as-is to `frames/000123.jpg`;
    - `frames.jsonl` (`seq`, `ts`);
    - `events.jsonl` (calibration points, pose, verify, align results, detections, retractions, commits, corrections, board_cleared, undo, game revisions);
    - `session.json` (mount notes, lighting, phone settings, entered on the setup page).
  - `tools/make_labels.py DIR` derives `labels.jsonl`, one line per committed dart: `{throw_id, turn, dart, truth_label, source: accepted|corrected|manual, detection_label|null, frame_seq_before, frame_seq_after, tags: []}`. Tags are added by hand afterwards (`wire`, `stacked`, `bounce`, `miss`, `occluded`, `bump`).
  - `tools/eval_detection.py --recording DIR` replays frames through `Vision` with the recorded calibration and scores against the labels, using the same report format as M1-03.
  - `tools/contact_sheet.py DIR` writes per-throw before/after crops with the detected tip marked, for human label review.
  - Disk guard: stop recording below 5 GB free and warn.
- **Files:** new `recorder.py`, `tools/make_labels.py`, `tools/contact_sheet.py`, `tools/eval_detection.py`, `server.py`, `static/setup.js`.
- **Depends on:** M1-13.
- **Acceptance:**
  1. Record a 3-turn sim session through the stub MJPEG server with one corrected dart. `make_labels` yields 9 labels with exactly one `corrected`.
  2. Replaying that recording reproduces the identical detection sequence (same labels and seq numbers).
  3. The contact sheet PNG exists with 9 panels.
  4. Recording at 1080p/15 fps for 60 s keeps p95 latency within the M1-12 limit.

#### M1-15 — Game-mode interface (x01 as the first mode)
- **Why:** New games will plug in later (approved). Do this before persistence so the saved schema includes the mode.
- **Scope:**
  - `modes/base.py` `GameMode` contract: `id`, `display_name`, `validate_options(opts)`, `new_state(names, opts)`, `throw(state, value, multiplier) -> state`, `can_advance(state)`, `next_turn(state)`, `to_json` and `from_json`, and `presentation_hints(state)` (e.g. `{kind:'x01', start}`).
  - `modes/x01.py` moves the `core.Game` logic there unchanged. `core.Game` becomes a thin generic wrapper that holds the mode, state and history (undo stays generic, a snapshot stack).
  - `MODES` registry. `/api/game` accepts `{mode:'x01', options:{start, double_out}}` and also the legacy top-level `start`/`double_out` mapped to x01.
  - The state snapshot gains `mode` and keeps every existing x01 field, so `/play` is untouched.
  - No new games.
- **Files:** new `modes/__init__.py`, `modes/base.py`, `modes/x01.py`, `core.py`, `server.py`, `tests/test_modes.py`.
- **Depends on:** M1-12 (correction replay uses the mode).
- **Acceptance:**
  1. All existing rules tests pass unchanged against `core.Game`.
  2. A test registers a trivial dummy mode (in the test only) and plays it through the API without any server edits.
  3. `/api/state` for an x01 game equals the pre-refactor snapshot plus `mode: 'x01'` (golden JSON test).
  4. All browser suites pass.

#### M1-16 — Persist match state to disk
- **Why:** A server restart (or a Mac sleep or crash) mid-match must resume (approved, criterion C10).
- **Scope:**
  - After every successful game write, atomically write (temp file, `fsync`, `os.replace`) `.local/state/match.json` containing `{schema:1, mode, state, history, revision, camera_game, saved_at}`.
  - On boot, load it if valid. If it is corrupt, rename it to `match.corrupt-<ts>.json` and start empty with a printed warning.
  - Flags: `--state-file` and `--fresh`.
  - Calibration persistence: save `calibration.json` (points, image size, pose) plus `reference.jpg`. On boot with a camera, attempt `align()` with that reference (an M1-08 alignment check). If it succeeds, verification is still required (one tap).
  - Tokens are not persisted (unchanged).
- **Files:** new `persistence.py`, `server.py`, `vision.py`, `tests/test_persistence.py`.
- **Depends on:** M1-15.
- **Acceptance:**
  1. Play to mid-turn (2 darts), kill -9 the server, restart, and `/api/state.game` plus `revision` match exactly. Undo works across the restart.
  2. A corrupt file leads to a clean start and a preserved corrupt copy.
  3. Write time is < 20 ms p95 with 200 history entries.
  4. Restart with a calibration file and the same sim stream gives the `review_overlay` phase without clicking points.

#### M1-17 — Board-day dry run and go/no-go
- **Why:** Rehearse Thursday end to end on synthetic footage so the trial measures the board, not our bugs.
- **Scope:** No new features.
  - Run the full flow on a sim MJPEG stream (mount `left`, `realistic`, 10 turns with occlusions, one bump and one 10 s stream drop): setup → calibrate → 2-player 301 → camera proposals with corrections → board cleared → restart mid-match → finish.
  - Measure C6 (scripted), C7, C8, C9 and C10 on sim.
  - Produce `docs/TRIAL_CHECKLIST.md`, a one-page printable checklist for Thursday that mirrors §3.
  - Fix-forward only for bugs found (small fixes; anything larger becomes an M2 ticket).
- **Files:** `docs/TRIAL_CHECKLIST.md`, `qa-artifacts/M1-17-dryrun.json`.
- **Depends on:** M1-14 (and M1-16 if landed).
- **Acceptance:**
  1. The dry-run report shows each of C5–C10 passing on sim, or the gap listed with an owner-visible note.
  2. Both full suites pass.
  3. The checklist exists and fits on one page.
  4. The PM signs off go/no-go in the commit message.

---

## 3. Milestone M2 — "Board day" (Thu 29 Oct onward)

### 3.1 Setup (≈30 min)
- Hang the board regulation-style (bull at 173 cm, oche at 237 cm) with 20 at the top. Note that the Diamond Plus number ring is removable, so check that 20 is at the top before calibrating.
- Phone: IP Webcam on the **main 1× lens** (avoid the 0.6× ultrawide: its distortion breaks the plane homography). Settings: 1920×1080 (fall back to 1280×720 if fps < 12 or latency fails), quality 80, fps cap 15, focus locked (or fixed focus at board distance), exposure and white balance locked after framing, stabilisation off, screen awake, charging. DroidCam is the fallback only (the free tier is 640×480).
- The Mac runs `start-mac.command --camera http://PHONE:8080/video --record ~/dart-trial/<session>`. Fill in `session.json`: mount ID, tape-measured camera offset from the bull (x, y, z cm), lighting, resolution.

### 3.2 Mount positions (try in this order, ~30 throws each, then pick one)
| ID | Position | Notes |
|---|---|---|
| A | **Top**: bracket above the board, phone ~45 cm out from the wall and ~40 cm above the board top, looking down | Out of the throw line. Flights may occlude tips in the top sectors |
| B | **Side** (left or right of the board, at bull height): ~45 cm out from the wall, ~45 cm sideways | Good foot-point separation. Watch for the thrower's arm and body |
| C | **Bottom**: below the board, looking up, ~40 cm out | Low occlusion by flights. Risk of being hit by darts, so needs a guard |
| D | (Optional) steep top-corner, ~35 cm out | Test only if A–C all fail C1 |

Selection rule: the highest C1 accuracy on the 30-throw sample. On a tie, take the lower false-proposal count, then the physically safest mount. Record each mount with a photo.

### 3.3 Lighting passes
1. Room lighting as usual.
2. Room plus a diffuse light near the board (a ring light or LED strip around the surround, if available) to cut dart shadows. Shadows are the main known risk to the tip rule: an on-plane shadow can extend toward the foot point.
3. One dim pass (lamps only) at the chosen mount, 15 throws, to see where it breaks.

Watch for LED flicker or banding in the preview. If it appears, change the IP Webcam anti-banding setting to 60 Hz.

### 3.4 Throw script (at the chosen mount; ~130 throws ≈ 60–75 min)
Each line is one block. The host scores via the controller as normal (accept or correct), and that becomes the label. Tag blocks in `session.json`/the event log via setup page buttons ("block: wire", etc.).

| Block | Throws | What | Expected system behaviour |
|---|---|---|---|
| 1 Normal play | 45 (15 turns) | 501, aiming freely across the board | Proposals for each dart; feeds C1 |
| 2 Targeted rings | 24 | 8 turns aiming T20, T19, D16, D20, bull, 25, D3, T5 | Thin ring accuracy |
| 3 Wire hits (placed) | 20 | Push darts in by hand **on or within 2 mm of wires** (ring wires and radial wires, including the bull wires). Note the true side from a close-up phone photo | Feeds near-wire accuracy and `near_wire` flags |
| 4 Stacked / overlapping | 15 | Group in T20 and the bull; deliberately land darts touching or shadowing earlier ones | C2; ambiguous cases should say "ambiguous", not guess |
| 5 Bounce-outs | 5 | Drop a dart so it hits and falls out, or seat a dart loosely so it falls out | Retracted, with no committed dart (C4) |
| 6 Misses | 6 | Off the board into the surround, and one that hits the number ring | No proposal; the host taps Miss |
| 7 People in frame | 10 turns overall | During blocks 1–2, the next player walks past, the thrower leans in, someone stands in front for 5 s | 0 false proposals (C4); occluded phase |
| 8 Pulling darts | every turn | Normal pulling, plus pulling only 1 of 3 darts mid-turn once | `board_cleared` ≤ 3 s (C8); partial pull handled without wrong proposals |
| 9 Phone bump | 3 | Tap the mount lightly; nudge it ~1 cm; rotate it slightly | Detected; realign or guided recalibration; never silent wrong scores (C9) |
| 10 Stream drop | 2 | Toggle phone Wi-Fi off for 10 s; lock the screen for 10 s | Reconnect ≤ 10 s, no recalibration (C9) |
| 11 Restart | 1 | Kill the server mid-turn and restart | Identical state resumes (C10) |
| 12 Calibration timing | 3 | Cold calibration by the owner, timed with a stopwatch | C6 |

### 3.5 Footage and labelling
- Record continuously for every block, including the mount trials (`--record`). Expect roughly 2–4 GB/hour at 1080p/15 fps. Keep ≥ 20 GB free.
- **Labels:** the controller commit is the truth (accepted, corrected or manual). After the session, run `make_labels.py` and `contact_sheet.py`, and hand-review every throw tagged `wire`, `stacked` or `corrected` against the close-up photos. Fix truth labels in `labels.jsonl`, keeping the original value in a `truth_original` field.
- **Latency:** compute it from `events.jsonl`: the first frame seq where the dart is present (from the contact-sheet review on a sample of 20) to the detection event timestamp.
- **Privacy:** footage stays on the Mac in `~/dart-trial/` and is excluded from git. The owner decides retention.

### 3.6 M2 tuning tickets (after the first trial session)
- **M2-01 Real-footage baseline:** run `eval_detection --recording` on every session and publish C1–C4 per mount and block. Acceptance: report in `qa-artifacts/M2-01-*.json`.
- **M2-02 Threshold tuning:** grid-search the diff threshold (35), morphology kernel, contour area limits (35–6000), stability frames (3), motion limits (0.004 / 0.10) and resolution, on recordings. Hold out 30 % of throws. Acceptance: improvement on the hold-out set, no regression on the sim suite.
- **M2-03 Tip bias and shadow handling:** fit `TIP_BIAS_MM` per mount from labelled tips. If shadows cause errors, add a colour/darkness split (shadow is darker but colour-preserving versus the dart) or recommend the light. Acceptance: C1 ≥ 95 % on the hold-out set.
- **M2-04 Occlusion and pull tuning:** tune the occluded→cleared logic and the bounce-out window on blocks 5, 7 and 8. Acceptance: C4 ≤ 2/100 and C8 on the hold-out set.
- **M2-05 Bump recovery:** tune ORB realignment gates using block 9. Decide on auto-realign vs ask-to-verify. Acceptance: no silent wrong score after any bump in the recordings.
- **M2-06 Latency:** profile the worker. Consider a lower processing resolution and long-poll or SSE for `/control` proposals if polling dominates. Acceptance: C7.
- **M2-07 Mount and setup guide:** a one-page physical setup guide (mount, distances, phone settings, light), with photos. Acceptance: the owner reproduces the setup from the guide alone, and C6 passes.
- **M2-08 Go/no-go review:** compare against §1. If C1 < 95 % after M2-02/03, present options: assisted mode, a second phone camera (multi-view; the most common approach in commercial auto-scorers), or different mount or lighting hardware.

---

## 4. M3 outline — Game catalog and game-selection dashboard

- **Modes on the M1-15 interface**, in suggested order:
  1. Cricket (15–20 + bull, marks, points/no-points);
  2. Around the Clock;
  3. Shanghai;
  4. Killer (2–4 players, lives, number assignment);
  5. Snakes & Ladders (a board-game overlay mapped to segments).

  Each mode ships with rules unit tests, an x01-style golden snapshot test, and its own presentation renderer.
- **Per-mode presentation:** `presentation_hints.kind` selects the renderer module, with shared turn entrance, dart reveal and celebration primitives factored out of `presentation.js`. Cricket needs a marks grid; Killer needs lives.
- **Game-selection dashboard:** a controller home screen (player picker, recent players, game cards with a short rules blurb and options) and a TV "lobby/attract" scene on `/play` while no game is running.
- **Catalog metadata:** `MODES` registry entries carry name, description, player range, option schema and a thumbnail, and the dashboard renders from them.
- **Later:** player profiles and per-player stats (averages, checkout %), match history, sound design.
- Scope M3 only after M2-08.

---

## 5. Risks and open questions

### Risks
| Risk | Impact | Mitigation |
|---|---|---|
| A single camera cannot see tips hidden by earlier darts (stacked T20 groups) | C2 low; wrong or ambiguous proposals | "Ambiguous" instead of a guess; one-tap correction; the second-camera option in M2-08 |
| Dart shadows extend the blob on the board plane, possibly toward the foot point | Tip picked at the shadow end | Diffuse light; shadow rendering in the harness (M1-02/05); M2-03 |
| The 4-click homography has no redundancy, so click error skews the pose and the scoring map | Systematic ring errors | Loupe and full-ring overlay check (M1-13); harness click noise; later option: ECC refinement against a rendered template |
| Unknown real intrinsics and lens processing on the S22 (focal estimate, distortion) | Foot-point direction error | Only the direction matters much; `mount_side` manual override; 1× lens only |
| Auto-exposure, focus hunting or LED flicker cause motion and diff noise | False "motion" or proposals | Lock exposure and focus in IP Webcam; anti-banding; the stability gate |
| Phone heat or battery over a long night; IP Webcam backgrounded by Android | Stream drops | Charging, case off, a fan if needed; exempt the app from battery optimisation; auto-reconnect (M1-07) |
| Wi-Fi jitter | Latency (C7) | Latest-frame-only reader; 720p fallback; 5 GHz band |
| HTTP on the LAN sends bearer tokens unencrypted on the home network | Someone on the Wi-Fi could control the match | Acceptable for a home LAN in our view; `--https` remains available **[Owner?]** |
| The synthetic-to-real gap | Sim passes, real fails | The trial is the real gate; M2 tuning runs on recordings only |
| Schedule: 17 tickets in about 2.5 days | Slip into Thursday | Cut line: M1-15 and M1-16 may slip; M1-17 gives the go/no-go |

### Open questions for the owner
1. **Auto-accept:** should camera darts commit automatically after N seconds unless corrected (faster play), or always need a host tap? The proposed default is a host tap during the trial and an optional auto-accept after the trial.
2. **Mount hardware:** what can physically be mounted? Wall arm above or beside the board, floor stand, shelf? Is there power near the board? This decides which positions in §3.2 are realistic.
3. **Lighting:** may we buy or use a board ring light (~$30–60)? It is the cheapest accuracy lever.
4. **Second camera:** is a second phone or webcam acceptable if one camera misses C1 or C2?
5. **Misses:** is a host tap on "Miss" acceptable for off-board darts, or should a turn end (board cleared with fewer than 3 detections) auto-fill misses?
6. **Committed-dart correction:** is 2 taps (chip, then region) acceptable for darts already committed? Pending darts are 1 tap.
7. **HTTP default on the LAN:** OK to drop HTTPS by default (the local CA stays optional)?
8. **Recording retention:** keep trial footage of players for tuning? Where, and for how long?
9. **Who throws on Thursday,** and is ~2 hours available for the full protocol (§3.4)?
10. **M3 priority:** which game comes first after x01, and must the dashboard come before a second game?
