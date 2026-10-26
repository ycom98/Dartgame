# Dart Room — guided presentation feature

Updated October 26, 2026 from Kapil's presentation-screen request.

## Current approved work

Build a polished, presentable and interactive game experience with animations and automated guidance. The audience screen must feel like the real product, separate from QA tools. Keep all physical camera/board work last: the Winmau Diamond Plus has not arrived. The phone remains Galaxy S22 SM-S901U; this feature needs neither the phone nor camera.

## Views

- **/play — audience display:** full-screen-ready social-darts presentation, read-only shared live game, large active player/remaining score, three dart results, digital scoring map, standings, round/next-player cues, score animation, turn handoff, bust and winner scenes. No QA tools, calibration form or camera preview.
- **/control — host controller:** manual-first 301/501 setup, two to four named players, straight/double-out, legal dart entry, undo/correction, manual next player and optional guided auto-handoff. Opens/copies the audience link.
- **/showcase — isolated presentation demo:** polished automated sample game with visible Showcase/demo identity, play/pause/restart, turn and win sequence. No live match mutations, actual camera access or reliance on QA fixtures. It is presentable before the board arrives.
- Existing root/phone/camera setup remains compatible. No new games or production hosting are part of this feature.

## Guided flow and automation

1. Start a match and introduce the active player.
2. Prompt for each of three darts; animate accepted scores and entered-hit feedback.
3. Announce turn total, bust or win. Make the next action obvious.
4. In manual mode, optional automatic handoff shows a visible roughly four-second countdown and can be cancelled/paused or undone. Camera mode retains explicit clear-board/verification requirements and is deferred.
5. Only the controller can initiate a score or next-turn request. Spectator tabs never own a mutation timer or submit game actions.
6. Guard controller writes with expected game revision. Undo, new game, another controller or network loss invalidates stale pending handoffs; never blindly retry a mutation.
7. Preserve existing game rules/history and correct invalid-input behavior.

## Presentation and access

Use the Flight Club-inspired direction in UI_DIRECTION.md: warm clubhouse details, dark teal/charcoal, cream/gold/red, large scores, recognizable players and restrained celebratory motion. Keep Dart Room branding.

Use a separate read-only display credential where practical: it can read game state but cannot mutate scores or obtain the host token. Keep existing control/pairing credentials compatible. Show normal connection recovery and an empty-match lobby.

Animations must honor reduced-motion settings. Fullscreen requires a normal user gesture and must fail gracefully. Keep text legible, buttons keyboard/touch accessible, long names safe and layout useful on Mac/TV; controller also works on narrow mobile screens. Audio is optional and off unless explicitly enabled.

## Acceptance and QA

- Developer implements and tests candidate; independent QA checks it before PM/Kapil review.
- Legacy 43-test rules/API suite remains passing.
- Controller score changes appear consistently on two independent audience pages, with no display mutation requests.
- Auto-handoff, cancel, undo, bust, winner, replacement, multiple controllers and failed/disconnected requests preserve one correct game state.
- Showcase advances between players and celebrates a win; pause/restart work without touching a real game.
- Check representative 320/736/1280/1920 widths, reduced motion, fullscreen fallback and absence of QA/calibration clutter.
- Use isolated QA processes and generated sample players; preserve the actual live game/session until coordinated deployment.

## Deferred and intentional limits

Real camera scoring, physical calibration, dart accuracy, board/phone movement and calibration timing wait until board delivery. Existing state/history remain in memory and vanish on server restart. Persistence/statistics, extra games, accounts, online multiplayer and public publishing require later scope decisions.

No OS trust changes, browser-warning bypass, actual camera capture or recurring automation is authorized by this presentation work.

## October 26 PM revision: gameplay motion

The initial presentation needs a richer guided sequence: named player entrance, individual dart points, animated remaining-score count-down, a reservoir proportional to the selected301/501 starting score, readable turn recap and distinct maximum180/win/bust moments. Kapil's example is301 →241 →181 →121 after three T20s, with180 earned in the turn. Next-player introduction follows the recap. Use the same rendering system in live manually scored games and the isolated Kapil/Aita showcase. Deduplicate identical state, cancel stale effects after correction or fast updates, and honor reduced motion. Score entry must stay usable during motion.
