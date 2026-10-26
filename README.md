# Dart Room — local feasibility prototype

A small local 301/501 game for a **Winmau Diamond Plus**, **Samsung Galaxy S22 (SM-S901U)**, and a **MacBook on the same Wi-Fi**. Supports 2–4 players, straight-out or double-out, bust rules, undo, guided initial calibration, feature-based pre-game realignment, and experimental camera score proposals.

**This is a prototype for physical testing, not production-ready automatic scoring. Every camera proposal requires human confirmation.** The archive includes prior Linux tests. This milestone is being validated locally on the Mac; the physical S22 (SM-S901U) and mounted board still need supervised live testing.

## Start on the Mac

1. Extract the project folder to your Mac. Install Python 3.10 or newer from python.org if `python3 --version` is unavailable or reports a version below 3.10. The Mac needs Internet access for initial dependency installation.
2. Open Terminal in the project folder and run:

   ```sh
   bash start-mac.command
   ```

   You can also try double-clicking `start-mac.command`; macOS permissions may require the Terminal method. The script checks Python 3.10+, creates `.venv`, installs dependencies on first use, and starts the local HTTPS server. Later launches reuse compatible installed dependencies and can run offline. An existing project `.venv` is preferred. To choose a specific interpreter on first setup, run `DART_PYTHON=/absolute/path/to/python3 bash start-mac.command`.
3. Open the **Computer** URL printed in Terminal on the Mac. Open the **Phone** URL on the S22 (SM-S901U) in Chrome. Keep the complete pairing URLs, including `?t=...`, private. Restarting the server generates a new token.
4. On the Mac, allow Python's incoming local-network connection if prompted. Both devices must be on the same non-guest Wi-Fi with client isolation disabled. No router port forwarding is needed.
5. Phone camera access requires browser-trusted HTTPS. A certificate warning or Connection trusted for camera: No / Camera access API: Unavailable blocks camera access even when the page loads. Complete the local CA setup below; accepting a privacy warning alone is insufficient. Do not disable browser protections.
6. On the phone, press **Start rear camera** and allow camera access. Start with the main rear lens at 1× zoom. The page shows the selected camera and offers a camera picker after permission when the browser exposes multiple cameras; inspect the preview rather than assuming a specific S22 (SM-S901U) lens was selected. Keep the page visible, screen awake, and orientation fixed. Frames are sent about every 700 ms. No microphone is requested.
7. Stop with **Ctrl-C** in the Mac Terminal.

The default port is 8443. If the printed LAN address is wrong, run `bash start-mac.command --lan-ip 192.168.1.123` using the Mac's Wi-Fi IPv4 address from System Settings → Wi-Fi → Details → TCP/IP. The certificate is regenerated when the selected IP changes. macOS's included `openssl` is used with a config file rather than requiring `-addext`.

## Test games without a board or camera

Open the **Computer** pairing URL on the Mac. Under **Start a game**, uncheck **Camera game**, choose 301 or 501, select 2–4 players and enter their names. Select Double out if wanted, then press **Start game**. Manual games require no calibration.

Use **Value** and **Ring**, then **Record manual score**. Miss records zero; bull Single is 25 and Double is 50. Record three darts, then press **Darts removed · Next player**. A bust also permits advancing. **Undo last action** reverses a score or turn change; record the corrected dart afterwards. Starting another game asks before replacing an unfinished game.

## Trust local HTTPS on the Galaxy S22 (SM-S901U)

The app generates a uniquely named project CA and a 30-day server certificate for localhost, 127.0.0.1 and the selected Mac Wi-Fi IPv4 address. Leaf renewal preserves that CA. No trust is installed automatically on the Mac, phone or browser. The CA expires after one year; replacing it deliberately also requires updating device trust.

After reviewing the exact CA identity and full SHA-256 fingerprint on the Mac or in the trusted setup chat, open a second Terminal in this project and run:

```sh
.venv/bin/python local_https.py serve --lan-ip YOUR_MAC_WIFI_IPV4
```

This opens a **10-minute public-certificate-only HTTP setup page** at `http://YOUR_MAC_WIFI_IPV4:8765/`. It serves only the instruction page, public CA download and fingerprint. It exposes no pairing token, game API, camera image, directory listing or private key. Start it when ready to download; restart the helper if its window expires.

On the S22, compare the complete fingerprint with the trusted Mac/chat value, then download `DartRoom-Local-CA.crt`. Installing a CA authorizes the device to trust certificates signed by that CA's private key; install it only after explicitly accepting that trust. The private key remains in this project on the Mac.

In Android Settings, search for **Install a certificate** or **CA certificate**. Select **CA certificate**, then choose the downloaded file. Do not select a Wi-Fi certificate. Samsung menu names vary by Android/One UI version; Android 11+ requires this CA installation through Settings rather than a web page. Close and reopen Chrome, open the complete current HTTPS Phone link, and verify **Connection trusted for camera: Yes** and **Camera access API: Available** before pressing Start rear camera and allowing Camera.

If the Mac browser also needs trust, that is a separate deliberate user/Keychain step. This software does not change Keychain or Android trust. To remove the phone trust later, find the uniquely named **Dart Room Local CA …** under Android's user-installed/trusted credentials and remove that specific CA.

Certificate staging can be inspected without altering a running server:

```sh
.venv/bin/python local_https.py prepare --lan-ip YOUR_MAC_WIFI_IPV4
```

Staging is in `.local/pki/`. The managed leaf is activated on the next app startup. Coordinate a restart before switching an existing self-signed installation; restarting also changes the pairing token.

References: [local HTTPS development](https://web.dev/articles/how-to-use-local-https), [Android CA installation via Settings](https://developer.android.com/reference/android/security/KeyChain#createInstallIntent()).

## Board and phone setup

Use a fixed phone mount outside the throwing path and bright, even lighting without glare. Mount the board normally with 20 at the top; ensure it cannot turn during throws. The **full scoring circle must remain visible**, with the board filling much of the image. Initially calibrate with **no darts in the board**. Do not buy additional camera hardware before testing this setup.

On the computer, select **Set four points**. The exact image freezes while the live phone stream continues. Then click the outer edge of the double ring at the centre of:

1. 20 at the top;
2. 6 at the right;
3. 3 at the bottom;
4. 11 at the left.

These points define a perspective transform to a regulation board plane. After the fourth point, the server matches that frozen reference to the latest live frame. Check all four overlay markers on the live image, then press **Markers correct · Ready to play**. The Start game button becomes available for camera games only after verification. If the snapshot expires after five minutes, restart point selection. The calibration target is 1–5 minutes once the camera is connected; physical timing must still be measured. The procedure assumes a regulation-sized scoring area with outer double radius 170 mm.

**Check / realign board** matches the current image to the initial reference using ORB features and a RANSAC homography. Before each camera game, the server also requires a fresh frame and automatically runs this alignment check. If the four markers move by more than two image pixels, it asks you to verify the updated overlay before starting. A new alignment, detected scene change, camera dimension change, stale/disconnected stream, or phone camera start/stop/lens switch clears prior verification. If matching is too weak, insufficiently distributed, or takes the board out of frame, it blocks startup and asks for manual calibration. Blank, low-detail images cannot pass. Significant stable scene changes and frame resolution changes invalidate alignment. Small movement, rotationally repetitive board features, autofocus, and lighting changes can still defeat or confuse matching: always check the overlay. Robust movement detection is an open physical-test item.

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

Browser pages, game state, and frame processing run on the Mac. The S22 (SM-S901U) uploads images over the LAN's HTTPS connection. Images and game state are held in memory and are lost when the server stops. They are not sent to an AI service, stored on disk, or published. The pairing token authorizes all game controls: anyone with that link and LAN access can control the game. Keep it private and avoid untrusted networks. The server is a small development server, not hardened for public Internet exposure.

The project CA private key and server private key stay in `.local/`; never share that directory or either private key. Only the public `DartRoom-Local-CA.crt` may be shared for manual trust setup. Preserve `.local/pki/`: leaf renewal and LAN-IP changes reuse the same CA. Deleting `.local/` changes the CA identity and requires removing/replacing previously installed device trust. No cloud account is needed. Initial Python packages require downloads; runtime does not need Internet access.

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
python3 server.py --host 127.0.0.1 --http --port 8443
```

HTTP mode is deliberately restricted to loopback; it is unsuitable for the phone camera. See `REQUIREMENTS.md` and `QA_REPORT.md` for requirements and independent QA results. The next phase is live Mac/S22 (SM-S901U) setup, overlay verification, and a known-score throwing trial. Kapil reviews and accepts the result before any production release.

## Milestone 1 readiness

The setup panel shows camera waiting/disconnected, ready to calibrate, point-selection progress with elapsed seconds, overlay review, and ready to play. Readiness means fresh camera frames plus verified calibration; it does not establish dart-detection accuracy. Keep the board empty for calibration and realignment. After reconnecting, realign and verify again. A moved phone or board can still defeat the experimental movement detector; use the alignment control after any known movement.

The agreed hardware is a Winmau Diamond Plus, MacBook, and confirmed Galaxy S22 (SM-S901U) using the rear camera. Game state is currently in memory only. Broader games, robust movement recovery, saved statistics and a dashboard are later decisions.

## Camera start feedback and retry

The phone page shows connection checks, camera permission waiting, preview startup and frame upload separately. Start remains available to explain a pairing, network or trust problem. Network requests time out after 8 seconds; camera permission waits at most 30 seconds and preview startup 10 seconds. **Cancel camera start** stays available while waiting. A browser permission prompt may outlive cancellation; any stream it later grants is stopped unless it belongs to the current attempt. Permission denial, unavailable/busy camera, insecure connection and upload failures appear beside the camera controls. These paths are tested with mocked media; the actual S22 trust/permission flow still needs user validation.
