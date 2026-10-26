# Dart Room — local feasibility prototype

A small local 301/501 game for a **Winmau Diamond Plus**, **Samsung Galaxy S22 (SM-S901U)**, and a **MacBook on the same Wi-Fi**. Supports 2–4 players, straight-out or double-out, bust rules, undo, guided initial calibration, feature-based pre-game realignment, and experimental camera score proposals.

**This is a prototype for physical testing, not production-ready automatic scoring. Every camera proposal requires human confirmation.** The archive includes prior Linux tests. This milestone is being validated locally on the Mac; the physical S22 (SM-S901U) and mounted board still need supervised live testing.

## Quickstart: Mac + Galaxy S22 with IP Webcam

The phone streams video with the free Android app **IP Webcam**; the Mac pulls the stream over plain HTTP on your home Wi-Fi and does everything else. No certificates or phone browser page are needed.

1. On the Mac, install Python 3.10+ from python.org if `python3 --version` is missing or older. Extract this folder.
2. On the S22, install **IP Webcam** (by Pavel Khlebovich) from the Play Store. Mount the phone (main 1× lens, whole board in view, 20 at the top) and plug it in.
3. In IP Webcam → **Video preferences**: resolution 1920×1080 (1280×720 if the stream is slow), quality about 80, FPS limit 15; turn video stabilisation off. Then scroll to the bottom and tap **Start server**. Note the address it shows, e.g. `http://192.168.1.23:8080`.
4. Mac and phone must be on the same, non-guest Wi-Fi. In Terminal, in this folder, run `bash start-mac.command --camera 192.168.1.23` (your phone's numbers; `http://192.168.1.23:8080/video` works too). The first run installs dependencies, which needs Internet.
5. Allow Python's incoming connections if macOS asks. Open the **Setup** link printed in Terminal on the Mac.
6. The checklist shows **Camera stream ✓** with fps. (No `--camera`? Type the phone IP under **Phone stream**, press **Test connection**, then **Connect**.) Lock focus and exposure in IP Webcam once framed.
7. Empty the board. Press **Freeze and set four points** and click the outer edge of the double ring at the centre of 20, 6, 3, 11 (a magnifier follows the cursor).
8. Check that the drawn rings and sector lines sit on the wires, then press **Markers correct · Ready to play**.
9. Open the **Controller** link on a phone/tablet and the **Presentation** link on the TV (both printed in Terminal), or start a game in section 2 of the setup page.
10. Stop with **Ctrl-C** in Terminal.

DroidCam is the fallback: use `http://PHONE:4747/video`. Other sources: `snapshot:http://PHONE:8080/shot.jpg` (single photos), `file:clip.avi` and `dir:frames/` (replay). The default port is 8000; `--port` changes it. If the printed LAN address is wrong, add `--lan-ip YOUR_MAC_WIFI_IPV4`. The stream reconnects by itself after a Wi-Fi drop; after more than 5 s without images, press **Check / realign board** and verify again. To rehearse without a phone, run `.venv/bin/python tests/fake_ipwebcam.py --port 8080` and connect to `127.0.0.1`.

Plain HTTP on the home LAN is the default (owner decision #7): the links carry the access token unencrypted, so anyone on your Wi-Fi who sees a link can control the match. Use `--https` if you want encryption (below).

## Camera darts on the controller

In a camera game, `/control` shows each detected dart as **Camera: T20 (60)** with a marker on the board and a countdown. It is accepted automatically after 3 s unless you act (owner decision #1; `--auto-commit SECONDS` changes it, 0 turns it off):

- **Wrong dart:** tap the right place on the board (one tap). Your value is recorded instead and logged as a correction.
- **Accept now** or **Pause auto-accept** (camera darts then wait for Accept).
- **Dart the camera missed:** tap where it landed.
- **Fix a dart already recorded:** tap its chip (Dart 1: …), then tap the board (two taps).
- **Darts off the board:** press **End turn · fill misses**; the missing darts are recorded as clearly marked misses, which you can still correct.

Every write carries the revision it was based on, so a second controller with an old view gets "Match changed" instead of overwriting.

## Test games without a board or camera

Open the **Setup** link on the Mac. Under **Start a game**, uncheck **Camera game**, choose 301 or 501, select 2–4 players and enter their names. Select Double out if wanted, then press **Start game**. Manual games require no calibration.

Use **Value** and **Ring**, then **Record manual score**. Miss records zero; bull Single is 25 and Double is 50. Record three darts, then press **Darts removed · Next player**. A bust also permits advancing. **Undo last action** reverses a score or turn change; record the corrected dart afterwards. Starting another game asks before replacing an unfinished game.

## Optional: HTTPS with a local certificate authority

Not needed for the IP Webcam setup. `bash start-mac.command --https` serves HTTPS on port 8443 (requires `openssl`). Browsers on other devices then need to trust the project CA, as below.


The app generates a uniquely named project CA and a 30-day server certificate for localhost, 127.0.0.1 and the selected Mac Wi-Fi IPv4 address. Leaf renewal preserves that CA. No trust is installed automatically on the Mac, phone or browser. The CA expires after one year; replacing it deliberately also requires updating device trust.

After reviewing the exact CA identity and full SHA-256 fingerprint on the Mac or in the trusted setup chat, open a second Terminal in this project and run:

```sh
.venv/bin/python local_https.py serve --lan-ip YOUR_MAC_WIFI_IPV4
```

This opens a **10-minute public-certificate-only HTTP setup page** at `http://YOUR_MAC_WIFI_IPV4:8765/`. It serves only the instruction page, public CA download and fingerprint. It exposes no pairing token, game API, camera image, directory listing or private key. Start it when ready to download; restart the helper if its window expires.

On the S22, compare the complete fingerprint with the trusted Mac/chat value, then download `DartRoom-Local-CA.crt`. Installing a CA authorizes the device to trust certificates signed by that CA's private key; install it only after explicitly accepting that trust. The private key remains in this project on the Mac.

In Android Settings, search for **Install a certificate** or **CA certificate**. Select **CA certificate**, then choose the downloaded file. Do not select a Wi-Fi certificate. Samsung menu names vary by Android/One UI version; Android 11+ requires this CA installation through Settings rather than a web page. Close and reopen Chrome and open the HTTPS link.

If the Mac browser also needs trust, that is a separate deliberate user/Keychain step. This software does not change Keychain or Android trust. To remove the phone trust later, find the uniquely named **Dart Room Local CA …** under Android's user-installed/trusted credentials and remove that specific CA.

Certificate staging can be inspected without altering a running server:

```sh
.venv/bin/python local_https.py prepare --lan-ip YOUR_MAC_WIFI_IPV4
```

Staging is in `.local/pki/`. The managed leaf is activated on the next app startup. Coordinate a restart before switching an existing self-signed installation; restarting also changes the pairing token.

References: [local HTTPS development](https://web.dev/articles/how-to-use-local-https), [Android CA installation via Settings](https://developer.android.com/reference/android/security/KeyChain#createInstallIntent()).

## Board and phone setup

Use a fixed phone mount outside the throwing path and bright, even lighting without glare. Mount the board normally with 20 at the top; ensure it cannot turn during throws. The **full scoring circle must remain visible**, with the board filling much of the image. Initially calibrate with **no darts in the board**. Do not buy additional camera hardware before testing this setup.

On the setup page, select **Freeze and set four points**. The exact image freezes while the live phone stream continues. Then click the outer edge of the double ring at the centre of:

1. 20 at the top;
2. 6 at the right;
3. 3 at the bottom;
4. 11 at the left.

These points define a perspective transform to a regulation board plane. After the fourth point, the server matches that frozen reference to the latest live frame. Every ring and sector line is then drawn on the live image: check they sit on the wires, then press **Markers correct · Ready to play**. The Start game button becomes available for camera games only after verification. If the snapshot expires after five minutes, restart point selection. The calibration target is 1–5 minutes once the camera is connected; physical timing must still be measured. The procedure assumes a regulation-sized scoring area with outer double radius 170 mm.

**Check / realign board** matches the current image to the initial reference using ORB features and a RANSAC homography. Before each camera game, the server also requires a fresh frame and automatically runs this alignment check. If the four markers move by more than two image pixels, it asks you to verify the updated overlay before starting. A new alignment, detected scene change, camera dimension change, stale/disconnected stream (more than 5 s without images), or a change of camera source clears prior verification. If matching is too weak, insufficiently distributed, or takes the board out of frame, it blocks startup and asks for manual calibration. Blank, low-detail images cannot pass. Significant stable scene changes and frame resolution changes invalidate alignment. Small movement, rotationally repetitive board features, autofocus, and lighting changes can still defeat or confuse matching: always check the overlay. Robust movement detection is an open physical-test item.

## Play

1. Choose 301 or 501 and 2–4 names. Straight in / straight out is the default; enable Double out if wanted. Camera game requires successful calibration/alignment and explicit verification of the live overlay. Uncheck Camera game to test rules manually without a phone.
2. Throw **one dart**, wait for the image to settle, and inspect the possible score. **Confirm proposed score** records it. If wrong, hidden, missing, or near a wire, select the actual value and ring and press **Record manual score**. Use Miss for a bounce-out or a dart outside the scoring area. Never record the same physical dart twice.
3. Repeat for three darts. A bust restores the score at the start of the turn. In double-out mode, leaving 1 or reaching zero without a double also busts. Inner bull counts as a double 25.
4. **Remove all darts first**, wait for the clear board to be visible, then press **Darts removed · Next player**. This advances the player and captures the new baseline. A premature click with darts still in the board contaminates the baseline; remove them and press **Board clear · reset image** to repair it.
5. To correct an entry, press **Undo last action**, then record the right score. Undo can restore the previous player's turn as well. With the physical darts unchanged, undo resets the image baseline, so re-enter a corrected score manually.

## How camera proposals work — and their limits

The server projects each frame into board coordinates, waits for a few low-motion frames, subtracts the most recent accepted baseline, and looks for a single elongated new component. It estimates one end of that component as the dart tip and maps it to a segment/ring. This endpoint selection is a **heuristic**, not a validated tip detector. The end closer to the bull is not always the actual point. Shadows, flights, wire occlusion, multiple changed regions, darts outside the crop, and hidden tips can cause missed or incorrect suggestions. Boundary-adjacent guesses are flagged. Nothing in the camera path automatically adds points without confirmation.

Single-camera accuracy must be measured with real footage before deciding whether to improve the model, use additional calibration aids, or add another camera. Do not represent the synthetic tests as proof of physical scoring accuracy. Manual scoring is always available.

## Privacy and local operation

Browser pages, game state, and frame processing run on the Mac. The Mac pulls images from the S22's IP Webcam stream over the home LAN (plain HTTP unless the phone app is set up otherwise). Images and game state are held in memory and are lost when the server stops. They are not sent to an AI service, stored on disk, or published. The pairing token authorizes all game controls: anyone with that link and LAN access can control the game. Keep it private and avoid untrusted networks. The server is a small development server, not hardened for public Internet exposure.

With `--https`, the project CA private key and server private key stay in `.local/`; never share that directory or either private key. Only the public `DartRoom-Local-CA.crt` may be shared for manual trust setup. Preserve `.local/pki/`: leaf renewal and LAN-IP changes reuse the same CA. Deleting `.local/` changes the CA identity and requires removing/replacing previously installed device trust. No cloud account is needed. Initial Python packages require downloads; runtime does not need Internet access.

## Running tests

1. One-time setup: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`.
2. `scripts/test.sh py` runs the Python unittest suite; `scripts/test.sh browser` runs every Playwright suite and lists failures per suite.
3. Browser suites need Node with `require('playwright')` resolvable and its bundled Chromium; set `DART_CHROME=/path/to/chrome` to use another browser (e.g. Chrome on the Mac).
4. `DART_PYTHON` overrides the interpreter (default `.venv/bin/python`). Browser suites write screenshots and result JSON to `test-output/browser-<timestamp>/` (gitignored), or to `$DART_QA_ARTIFACTS` when set. `scripts/test.sh browser --record` writes into the committed `qa-artifacts/` instead; use it only to refresh evidence on purpose.

## Tests and handoff

### Shared display and manual host

The server prints three new views at startup:

- **Controller** (`/control?t=…`): start a 301/501 match for 2–4 named players, choose straight or double out, and record each dart manually. Miss always scores zero; Bull offers 25 or 50. Undo corrects the last action.
- **Presentation** (`/play?t=…`): a responsive shared scoreboard with a full-screen button, active-player guidance and an approximate segment map of entered darts. Open it from the controller to use a separate view-only credential. It never advances a match or sends scores.
- **Showcase** (`/showcase`): a visibly labelled, isolated demo. Pause/Play and Restart control a scripted Alex/Maya 301 match. It uses no live API calls and changes no match state.

Auto handoff is on by default for manual matches. After three darts or a bust, the controller displays a four-second countdown. Pause handoff, uncheck auto handoff, or Undo to review. Next player also works manually. Only the controller which entered the final dart starts a countdown; other controllers cancel on a changed revision. Requests use `expected_revision` so stale controllers receive HTTP 409 and current state instead of applying a duplicate action. Legacy callers may omit it. Connection failures cancel handoff and do not blindly retry writes. Camera matches continue in the legacy setup; automatic handoff is disabled there.

Keep controller links private: they can change the match. Display credentials allow only state reads; they cannot submit scores or read camera images. All game data remains in memory, and these views do not imply physical dart detection. Sound is off; no external assets are required. Keyboard controls and reduced-motion preferences are supported.

Record briefly disables for 600 ms after each submitted dart to prevent an accidental double click. A pending or stale connection health check pauses automatic handoff; review the displayed match before choosing Next player. Opening new-match setup also pauses handoff, and Back to the match returns without resuming it.

Developer presentation smoke check (requires local HTTP binding and Chrome): `node tests/developer_presentation.cjs`.

From the project folder:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Install `requirements.txt` first for vision tests. For manual-only development without dependencies:

```sh
python3 server.py --host 127.0.0.1
```
 See `REQUIREMENTS.md` and `QA_REPORT.md` for requirements and independent QA results. The next phase is live Mac/S22 (SM-S901U) setup, overlay verification, and a known-score throwing trial. Kapil reviews and accepts the result before any production release.

## Milestone 1 readiness

The setup panel shows camera waiting/disconnected, ready to calibrate, point-selection progress with elapsed seconds, overlay review, and ready to play. Readiness means fresh camera frames plus verified calibration; it does not establish dart-detection accuracy. Keep the board empty for calibration and realignment. After reconnecting, realign and verify again. A moved phone or board can still defeat the experimental movement detector; use the alignment control after any known movement.

The agreed hardware is a Winmau Diamond Plus, MacBook, and confirmed Galaxy S22 (SM-S901U) using the rear camera. Game state is currently in memory only. Broader games, robust movement recovery, saved statistics and a dashboard are later decisions.

## Camera stream status

The setup page shows the stream address (password hidden), frames received and checked per second, the age of the newest image and the number of reconnects. A dropped stream retries after 1, 2, 4, then every 5 s. Only the newest image is processed; older ones are skipped, so a slow Mac never builds up delay. The phone-browser camera page was retired in M1-13; old `/phone` links open the setup page.
