# Board day checklist (first hardware trial)

Purpose: find out whether one ceiling-mounted phone can score real darts well enough, and record labelled footage so detection can be tuned on the real board afterwards. Plan for about 2 hours: 30 min setup, 75 min throwing, 15 min wrap-up.

The full protocol and pass criteria are in `docs/PLAN.md` §3 (M2) and the "concept proven" table (C1–C10). This page is the practical version.

## The night before

- [ ] Mac has **Python 3.10 or newer**: run `python3 --version` in Terminal (install from python.org if missing or older).
- [ ] **First run needs internet:** the first `bash start-mac.command` downloads the camera libraries (numpy, OpenCV) — a few minutes. After that it works offline.
- [ ] Mac has **at least 20 GB free** (recording uses about 100 MB per minute, ~6 GB per hour).
- [ ] Latest code on the Mac: `git pull` in the `Dartgame` folder (or `git clone https://github.com/ycom98/Dartgame.git`).
- [ ] S22: **IP Webcam** (Pavel Khlebovich) installed. Video preferences: 1920×1080, quality 80, FPS limit 15, stabilisation off, keep screen awake, exempt from battery optimisation.
- [ ] Quick rehearsal: phone and Mac on the same Wi-Fi (not a guest network), start the IP Webcam server, run `bash start-mac.command --camera <phone IP>`, open the **Setup** link, confirm "Camera stream ✓" and a live picture.
- [ ] Phone charger and a cable long enough to reach the ceiling mount.
- [ ] Optional: a diffuse light near the board (ring light or LED strip) to cut shadows.
- [ ] If a Controller or Presentation link was ever shared by mistake, start once with `--new-links` to make new ones.

## Setup (≈30 min)

1. **Board:** bull at 173 cm (5 ft 8 in), **20 at the top** (the Winmau number ring is removable, so check). Oche at 237 cm (7 ft 9¼ in).
2. **Phone:** ceiling mount **1.5 ft (≈46 cm) from the wall**, centred left–right, rear **main 1× lens** (not the 0.6× ultrawide), aimed at the bull, whole board including the number ring in frame with a little margin. Plug it in.
3. **IP Webcam:** start the server, then lock focus, exposure and white balance once the board is framed. If you see flicker or bands, set anti-banding to 60 Hz.
4. **Mac:** `bash start-mac.command --camera <phone IP> --record ~/dart-trial/session1`
5. Open the printed links:
   - **Setup** on the Mac: check the live view, fill in the notes (mount "ceiling 1.5 ft", lighting, phone settings), press **Save notes**.
   - **Controller** on your phone or a tablet (this is where you accept or correct darts).
   - **Presentation** on the display PC or TV.
6. **Calibrate (time it, target under 2 minutes):** empty board → **Freeze and set four points** → click the **outer edge of the double ring** at the centre of 20 (top), 6 (right), 3 (bottom), 11 (left) → check every ring and sector line sits on the wires → **Markers correct · Ready to play**. The app snaps the clicks to the board's ring edges automatically, so small click errors are fine.
7. Start a **camera game** (301 or 501) with your name and a second player.

## How scoring works during the trial

- After each dart the controller shows **"Camera: T20 (60) · auto-accept in 3 s"**. If it's right, do nothing (or tap **Accept**). If it's wrong, **tap where the dart really is** on the controller board. That one tap is the correction, and it becomes the "truth" label for tuning.
- A dart already recorded: tap its chip, then tap the board (2 taps).
- Missed the board: tap **Miss**. If the camera saw fewer than 3 darts, **End turn · misses** records the rest as misses.
- **Current limit:** the camera handles **one new dart at a time**. Let each dart get accepted (3 s) before throwing the next, or tap Accept. Multi-dart tracking (M1-08) is next on the list after Thursday's data.
- Pull the darts, then let the turn hand over automatically after about 4 s. If it doesn't, tap **Next player →**.
- **Undo** removes the last dart; the camera won't propose it again, so tap where it really is.

## Throw script (≈130 throws, ≈75 min)

Record continuously. Do these in order and note the time each block starts (or say it out loud on a voice memo) so the footage can be tagged later.

| # | Block | Throws | What to do |
|---|---|---|---|
| 1 | Normal play | 45 (15 turns) | Play 501 normally, aim anywhere |
| 2 | Target rings | 24 | Aim T20, T19, D16, D20, bull, 25, D3, T5 (3 darts each) |
| 3 | Wire hits | 20 | Push darts in **by hand** on or within 2 mm of wires (ring wires, radial wires, bull wires). Take a **close-up phone photo** of each so we know the true side |
| 4 | Stacked darts | 15 | Group in T20 and the bull; land darts touching or just below earlier ones |
| 5 | Bounce-outs | 5 | Darts that hit and fall out, or seat one loosely so it drops |
| 6 | Misses | 6 | Off the board into the surround; one into the number ring |
| 7 | People in frame | during 1–2 | Second person walks past, thrower leans in, someone stands in front for 5 s |
| 8 | Pulling darts | every turn | Normal pull; once, pull only 1 of 3 darts mid-turn |
| 9 | Phone bump | 3 | Tap the mount lightly; nudge ~1 cm; rotate slightly. The app should ask to re-check or recalibrate, never score silently on a moved board |
| 10 | Wi-Fi drop | 2 | Phone Wi-Fi off for 10 s; lock the phone screen for 10 s. The controller shows **Camera reconnecting…**; keep tapping darts meanwhile. When the picture is back, the camera is ready again by itself within a few seconds if nothing moved. If the controller says **Board check needed** (or the Setup page asks), press **Check / realign board** on the Mac, look at the overlay, then **Markers correct · Ready to play** |
| 11 | Restart | 1 | Close Terminal mid-turn and start it again with the **same command** (the same `--record` folder is fine: the recording continues as a new part). The match should come back exactly, and the Controller and Presentation pages keep working with the same links (reload them if they look stuck). On the Setup page press **Markers correct · Ready to play** after checking the overlay |
| 12 | Calibration timing | 3 | Three cold calibrations with a stopwatch |

If time is short, do blocks **1, 2, 3, 4, 9, 11** — they matter most.

Optional if the mount allows: 15 normal throws at **2 ft from the wall** to compare.

## Wrap-up (≈15 min)

- [ ] Stop recording on the Setup page.
- [ ] Optional, in Terminal in the `Dartgame` folder:
  ```sh
  .venv/bin/python tools/make_labels.py ~/dart-trial/session1
  .venv/bin/python tools/replay_recording.py ~/dart-trial/session1
  .venv/bin/python tools/contact_sheet.py ~/dart-trial/session1
  ```
  This makes the labels, replays the footage through the detector with an accuracy summary, and a contact sheet image of every dart.
- [ ] Note anything odd (messages that confused you, darts it missed, how calibration felt).
- [ ] Tell Claude the session is done. The footage stays on your Mac (`~/dart-trial/`); we'll decide together what, if anything, to share for tuning (for example running the replay tools locally and sharing only the numbers or a few frames).

## What "pass" means (from docs/PLAN.md)

- ≥ 95 % of camera darts exactly right on ≥ 100 normal throws (C1); stacked darts reported separately.
- ≤ 3 % darts with no proposal; ≤ 2 false darts per 100 throws.
- Wrong dart fixed in 1 tap; calibration under 2 minutes; dart shows on the controller within ~1.5 s.
- If accuracy falls short but corrections are quick, the game still works as "camera-assisted" scoring while we tune on the recorded footage.
