# Dart Room — social-play UI direction

Kapil's reference, October 25, 2026: a Flight Club short and Flight Club Chicago. This is a design direction for PM/user review; the tested live application has not been replaced by the concept.

## References reviewed

- [User's Flight Club short](https://www.youtube.com/shorts/W3CFioenVDo), titled “Flight Club #flightclub #darts #nightout.” The visible game display above the physical board combines player-score rows and a digital dartboard map in a warm orange frame.
- [Flight Club Chicago](https://www.flightclubdartsusa.com/chicago/) and its official venue photography: shared screens above the boards, warm wood, cream/gold light, red accents and fairground bulbs.
- [Chicago venue image](https://www.flightclubdartsusa.com/img/asset/YXNzZXRzL2NoaWNhZ28vY2hpY2Fnby1vY2hlcy0xLmpwZw/chicago-oches-1.jpg?fm=webp&h=960&q=70&s=a97219725311ec0af5d94d70780b5004).

## Proposed product direction

Make Dart Room a shared social-game screen. The active player, remaining score and three dart results should be readable immediately. Player standings and a digital hit map support that central game view. Use a warm clubhouse palette, strong score typography, player identities and clear turn/bust/win feedback.

Move setup and calibration behind match/setup controls. They should not occupy a large empty area above the game. Manual play remains possible without the board or phone. Camera work remains the final hardware phase.

Keep the game's controls easy to find: switch between the implemented 301/501 modes, select players/rules, enter or correct a dart, undo and advance the player. Avoid displaying unsupported party games as if they already exist.

## Two concepts for review

1. **Clubhouse scoreboard:** player scores in a side column, active player's score in the center and digital board alongside. Cream, burgundy and warm dark surfaces adapt to the host appearance.
2. **Big-screen match:** more space for the active player's score and board, with the other players in a horizontal strip below. Intended as the direction for a future shared/TV display.

Both concepts use Dart Room's own branding. The reference informs the atmosphere and game focus; it is not an instruction to reuse Flight Club's logo or exact product screens.

The interactive concept uses sample players and local example scores only. It is not connected to the running server and does not capture a camera. It includes score-entry feedback, undo, turn transitions, game choice and a winner state for reviewing hierarchy and layout.

## Validation and next step

The concept was visually inspected and exercised in the in-app browser: score entry/undo, a winning turn and both design variants. Layout checks at a 320px browser viewport and at 736px confirmed no horizontal overflow; narrow player cards were corrected. The production game/rules code is unchanged, so its previous QA evidence remains separate.

Review the two directions with Kapil, then assign the selected UI to the developer and independent QA. Preserve existing rules, error recovery and manual entry. Additional game types, persistent statistics and hardware scoring accuracy still require their own scope and acceptance.

Concept source: USER_HOME/.codex/visualizations/2026/10/25/01a174e1-da18-7b63-bcdb-3e948347f3ba/dart-room-social-play.html.

## Approved presentation implementation — October 26, 2026

Kapil requested a polished screen to present, separate from QA, with animated player turns and automated guidance. Build /play (read-only audience), /control (manual host with safe optional auto-handoff), and /showcase (isolated autoplay sample with pause/restart). Use the big-screen direction with warm clubhouse accents; keep calibration out of the main flow. Preserve existing rules and defer physical camera/board integration. This supersedes the earlier design-only status.

## Delivered presentation

Implemented the big-screen direction with dark teal, cream, gold and red accents. /play shows scores, dart results, an entered-segment map, standings and animated turn/bust/win guidance. /control supplies manual scores and optional four-second handoff. /showcase is an isolated autoplay presentation with pause, restart and fullscreen controls. Independent QA passed; see PRESENTATION_QA.md. Deployed on HTTPS 8444 while preserving the active legacy match on 8443. Joint PM/Kapil visual review is next; physical tracking remains deferred.

## Gameplay animation revision — October 26, 2026

Kapil's review: the first delivered screen is too static. Build an actual guided match sequence, with a named turn entrance, three distinct dart results, remaining-score count-down and a visible reservoir representing remaining points as a percentage of the starting score. For Kapil's 301 example, three triple twenties earn 180 and leave 121 (40.2% remaining). Reveal the turn total, celebrate a maximum 180, then introduce the next player. The same rendering system must drive real manually scored matches and the isolated showcase. Use Kapil and Aita in the example.

Quality gates: motion has a deliberate hierarchy and timing, the numbers always resolve to authoritative backend scores, bust restores the reservoir, undo cancels stale effects, unchanged polls do not restart effects, and fast scoring cannot leave an obsolete player's banner onscreen. Reduced-motion users get immediate stable outcomes. All three dart results and the turn total stay readable; animations support play rather than delaying score entry. Physical scoring, camera, other games and audio remain outside this change. Developer implementation is followed by independent QA and PM visual review before delivery.

Animation revision delivered: independent QA passed all nine motion groups and 48 Python regressions. PM reviewed the named entrance, per-hit drain, clean 180 recap and settled mobile/TV screens, and visibly verified the local showcase. Browser errors, media requests and spectator writes were zero. All three served asset hashes match the reviewed files over verified HTTPS. The existing matches were preserved; no server restart was needed. See PRESENTATION_QA.md and qa-artifacts/presentation-animation-results.json.
