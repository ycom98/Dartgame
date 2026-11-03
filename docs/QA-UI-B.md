# QA: Developer B UI work (ui-b @ d2cb836, diff bb0f92d..d2cb836)

Independent QA, 2026-11-03. Worktree /home/user/qa-ui-b (detached). I reran every check myself and did not rely on the developer's reported results. My scratch QA scripts are outside the repo.

## Verdicts

| Ticket | Verdict |
|---|---|
| UI-06 Setup page as three steps | **PASS-WITH-NOTES** |
| UI-06b Offline QR codes | **PASS** |
| UI-08 First-run launcher and README quick start | **PASS-WITH-NOTES** |
| UI-04 Offline WebAudio sounds | **PASS** |

**Safe to merge: yes.** I found no blocking or medium defects. The notes below are all low severity.

## Test runs (rerun)

- **Python suite** (`unittest discover -s tests`): **229 tests, OK** (221 s).
- **Browser suites** (`scripts/test.sh browser`): **18 of 19 passed**. That count includes the new `qa_setup_steps.cjs` and `qa_sound.cjs`, and both passed.
  - The only failure is `qa_presentation.cjs`, which times out waiting for "Maya" in `.hero h1`. This is the known failure. The diff touches no presentation or showcase files, so this branch cannot have caused it.
- **Changed test selectors** in five suites:
  - Four suites now open `#legacyGame`, `#mountDetails` or `#recordNotes` before using controls inside them.
  - Two suites now scan `static/` recursively (`qa_camera_startup.cjs` and `test_setup_page.py`).
  - These changes are needed because the controls now sit inside collapsed `<details>` sections, and `static/vendor/` is new.
  - No assertion was removed or loosened. The recursive scan checks more files than before, not fewer.

## UI-06: what I checked myself

I used my own Playwright script against `tests/fake_ipwebcam.py` with two scenes. The server was started normally through `main()`.

**Step flow**
- Connect leads to step 2, the four clicks plus Markers correct lead to step 3, and the server phase is `ready`.
- **Board moved** (I switched the fake camera to another scene): the page went back to step 2, with the title "Check the live markers". Check / realign plus verify returned it to step 3.
- **Stream dropped** (I killed the fake camera): the page went back to step 1 ("Camera disconnected", phase `camera_disconnected`). When the camera came back, the page left step 1 by itself.

**Error messages** (each shows a plain-English hint plus the server's raw message)

| What I entered | Hint shown |
|---|---|
| Wrong IP (10.255.255.1) | "No picture came back…" |
| Unknown host | "This Mac cannot find that address…" |
| Bad scheme | "Type only the numbers…" |
| Non-camera URL (an HTML page) | The generic fallback hint (note L1) |

**Everything from before is still reachable**
- Comparing element ids in the old and new `index.html`, the only one removed is `cameraSection`, which was a wrapper that nothing referenced.
- Every id that `setup.js` used before is still present.
- The older game controls, camera position override, recording notes and phone checklist all open and work.

**Layout and accessibility**
- No horizontal scroll at 1440×900, 1280×800 or 390×844, even with all collapsible sections open.
- Keyboard: every tab stop shows a visible outline (`setup.css:107`). Disabled buttons are skipped as expected.
- Contrast: every visible text node is at least 4.5:1. The only exceptions are the stepper digits, which are deliberately transparent and replaced by a ✓ once a step is done.
- I made no external requests during the walk, and the page logged no errors.

## UI-06b

- Both QR codes decode with OpenCV to exactly the Controller and TV links. I checked at 1440 px and at 390 px.
- On a normal start the links use the LAN IP (`192.0.2.2`, from `local_ip()`), and `lan` is true.
- With `--lan-ip 127.0.0.1`, the "only works on this Mac" warning appears.
- The vendored `static/vendor/qrcode.js` is **byte-identical** to npm `qrcode-generator@1.4.4`, fetched through the proxy (sha256 `18ae399f…1780`). The MIT licence file is present.

## Server additions (`server.py`)

- **Token check on `/api/links`:**
  - no token gives 401;
  - the display token gives 401;
  - the owner token in the Authorization header gives 200.
- **Path traversal:** `SETUP_STATIC` is a fixed lookup table. `/static/../server.py`, `/static/vendor/../../server.py`, `%2e%2e` and `/static/vendor/` all return 401 and never return file content. The licence `.txt` is not served, which is fine.
- **Display-token holders:** `/api/state` read with the display token does not contain the owner token. `share_links` only appears on the owner-only route.
- `PUBLIC_ORIGIN` is set after the bind (`server.py:645-646`). The Host header is only used when `main()` has not run, which is the test case only.

## UI-08 (run on Linux, which has no `open` command)

- Normal start: it prints "Open the Setup link above in a browser on this Mac." and keeps running. It does not fail.
- `--no-browser`: the "open the link" line is suppressed.
- **Port busy:** a friendly message, exit 1, and it suggests `--port N+1`.
- **Camera unreachable** (`--camera 10.255.255.1`): a plain-English warning, and the server still starts.
- **Old Python** (I faked 3.8.10 with `DART_PYTHON`): "This Mac has Python 3.8.10. Dart Room needs Python 3.10 or newer…", exit 1.
- **Unknown option:** argparse's error is shown, followed by the friendly footer.
- **README quick start:**
  - It has 10 steps.
  - Every bold label matches the UI exactly, for example Phone IP address, Test connection, Connect, Live view, "Can't connect? Things to check", "Freeze and set four points" and "Markers correct · Ready to play".
  - The flags it mentions (`--camera`, `--record`, `--no-browser`, `--lan-ip`, `--port`) all exist.

## UI-04

I loaded `sound.js` on a bare page in Chromium.

- It starts with `isEnabled()` false, and `play()` returns false until a click.
- After the toggle is clicked:
  - all six names play;
  - an unknown name returns false;
  - localStorage holds `on`;
  - the button shows "Sound off" with `aria-pressed=true`.
- **After a reload with sound left on:** it stays muted until the first click, then turns back on.
- **Mute is remembered:** after muting and reloading, it stays off even after a click.
- `renderOffline` returns non-silent output for every sound.
- No network requests and no page errors.

## Offline

- I searched `static/` for `http(s)://` and found only:
  - licence and comment URLs and the SVG namespace in `vendor/qrcode.js`;
  - placeholder and example text in `setup.js:18-20,204` and `index.html:51,69`.
- Nothing is fetched from outside.

## Defects (all low; none block merge)

- **L1** `static/setup.js:191-209`
  - A URL that answers but is not a camera ("ConnectionError: Camera closed the stream") only gets the generic hint.
  - The raw messages that appear in `#error` include Python exception names (`gaierror: [Errno -2]…`, `ConnectionError:`).
  - Suggestion: add a "that address isn't a camera video stream" case, and drop the exception class name on the server side.
- **L2** `start-mac.command:100-110`
  - The port check always binds `0.0.0.0`, whatever `--host` is set to.
  - On a Mac without Command Line Tools, `python3` is Apple's stub, so the "too old" message may quote xcode-select text instead of a version.
- **L3** `README.md` (an unchanged, pre-existing line): it says "after more than 5 s without images, press **Check / realign board**". In my run the page recovered to Ready by itself when the camera came back, so that line is more cautious than it needs to be.
- **Note:** at 390 px the page is about 6000 px tall, and the live view sits below all three steps. That is acceptable, because setup is done on the Mac; the phone is only used for the QR and Controller links.
