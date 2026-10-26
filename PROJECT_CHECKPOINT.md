## Current animation revision — October 26, 2026

Kapil reviewed the first presentation as too static. Developer implemented a shared animated reservoir/count-down, per-dart points, turn tally, large named turn entrances, 180 recap, bust restoration and victory transitions. The isolated showcase uses Kapil/Aita. Only static/presentation.js, presentation.css and showcase.js changed in this revision; no backend/rules/process changes. Developer checks pass; independent animation QA passed all nine groups with zero browser errors; 48 Python regressions also pass. Root visibly reviewed the live showcase and TV/mobile images. Services 8443 and 8444 remain running; preserve the active match on 8443. Camera remains deferred. The served assets match reviewed disk hashes over verified HTTPS; see qa-artifacts/presentation-animation-deployment.json. Updated showcase has been visibly verified and is open for Kapil.

# Dart Game recovery checkpoint

Updated October 25, 2026 (America/Chicago).

## Presentation delivered — October 26, 2026

The polished /play audience display, /control manual host and isolated /showcase animated demo are implemented and independently QA approved. Optional four-second handoff is cancellable and revision guarded. All 48 Python tests, nine main browser groups, three resilience groups, four PM-focused groups and two fullscreen fallback groups passed. See PRESENTATION_QA.md.

Root deployed the new app on HTTPS port 8444 (terminal session 21702), using the existing certificate and current Wi-Fi IP 192.168.1.123. Showcase: https://localhost:8444/showcase. Private host/viewer links are in the conversation. Eight deployment HTTPS/auth checks passed; artifact: qa-artifacts/presentation-deployment.json. The showcase was opened and visibly verified in the in-app browser. Ready for joint PM/Kapil review.

The older app on port 8443 (session 51509) has an active match and was preserved without restart or mutation. Do not restart it without checking with Kapil. The new 8444 live game starts empty. Camera/physical board work remains deferred.

## Latest direction and status

The Winmau Diamond Plus has NOT arrived. Kapil asks to check all non-camera functionality now and leave live camera/board work until the end. The current manual-game candidate passed developer and independent QA review and is deployed for PM/Kapil review. Do not ask for board calibration or real throws now.

Phone remains confirmed Galaxy S22, model SM-S901U. Kapil previously reported Yes / Available after local certificate setup; live capture and physical accuracy remain unverified.

## Earlier manual-game evidence

- Independent Python suite: 43/43 PASS.
- Independent browser: five journeys PASS, zero actual media requests: complete 301/two-player, complete 501/four-player, complete double-out 301/three-player, recovery/validation, and manual-input/authentication.
- Covered bust/turn/win undo and correction, three-dart/player lifecycle, double-out remaining-one/non-double-zero busts, double bull, replacement acceptance/cancellation, blank/duplicate names, interrupted requests, committed-but-lost responses, pairing failures and reconnect.
- Developer additionally passed 318 API/rules assertions without vision dependencies, four manual UI checks and two recovery checks.
- Repaired three defects: Miss/Bull ring combinations, non-ASCII token exceptions, stale network-error banners after reconnection.
- PM reviewed screenshots and deployed after checking no active game. Six post-deployment HTTPS/auth checks passed without creating a game.
- See QA_REPORT.md and qa-artifacts/manual-*-results.json plus manual-deployment-smoke.json.

QA's child profile was still read-only. PM saved the QA-authored compact scripts; QA executed them independently. Use parent writes or ensure a writable profile for future test-file work instead of waiting on large write calls.

## Earlier runtime notes (superseded by delivery above)

Project: project.
Main HTTPS app: root terminal session 51509, port 8443, Mac Wi-Fi en0 IPv4 192.168.1.123. Started with bash start-mac.command --lan-ip 192.168.1.123.
At the earlier manual deployment, no game was active before restart; no real or synthetic frames were injected into this handoff process. The private pairing token changed; latest links are in the conversation. Never store it in a shared report.

Manual review: open the current Computer URL, uncheck Camera game, choose 301/501 and two to four names, then Start game. No phone, board or calibration is required. State/history are in memory and vanish on stop.

## Scope order

Kapil supplied a Flight Club video/Chicago reference for the UI. See UI_DIRECTION.md. Two interactive social-play concepts were prepared for PM/user design review; no live app or rules changes were made. The preferred direction is a game-first screen with large scores, clear players/turns, a dart map, and setup/calibration tucked away. Camera/physical-board work remains last.

1. Local/manual setup — software checked.
2. Existing 301/501 gameplay — developer and independent QA passed.
3. Validation/recovery hardening — repaired and independently passed.
4. Joint PM/Kapil review; agree any new games/dashboard scope before implementation.
5. Final hardware phase after delivery: rear-camera view, calibration/overlay, known throws/misses/overlap/removal, reconnect, movement recovery and timed calibration.

Calibration target remains roughly one minute, at most five after initial installation/pairing/trust setup. Measure it on the physical board. No physical result or unattended-scoring accuracy is claimed. Additional games, persistence/statistics and dashboard implementation remain deferred.

## Preserved camera/trust setup for the final phase

CA: Dart Room Local CA 5AC002AD (Dart Room), valid through October 25, 2027.
Public file: .local/pki/DartRoom-Local-CA.crt.
SHA-256: D4:F0:F4:AD:B9:6A:66:C6:89:A1:D6:19:49:E4:17:F1:A1:E4:34:A0:23:82:25:63:E3:E0:A6:28:43:9F:5D:D5.
Private keys stay protected in .local/ and must never be shared. Leaf renewals/IP changes reuse the same CA. No automatic system trust installation or browser-warning bypass is authorized.

The temporary public-certificate helper is not required for manual testing. If deliberately needed later, run .venv/bin/python local_https.py serve --lan-ip 192.168.1.123 for a ten-minute public-only download page. Recheck current Wi-Fi IP first. Preserve existing CA; do not delete .local/pki.

Deferred camera backlog: when stopping the old process, buffered logs showed an earlier aborted/empty frame upload reaching OpenCV's empty-buffer assertion, followed by a broken-pipe response to a disconnected client. Keep this for the final camera/ingestion phase; no camera fix or real-media test was attempted during this non-camera review.

No production publishing or recurring automation has been created.
