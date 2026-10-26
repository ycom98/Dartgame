# Presentation animation — independent QA

October 26, 2026. Scope: the revised shared score renderer, reservoir, per-dart feedback, named entrance/turn recap/180/winner scenes and isolated showcase motion controls. This adds to the previous `PRESENTATION_QA.md`; historical QA evidence is preserved.

## Isolation

`tests/qa_presentation_animation.cjs` starts a separate ephemeral HTTP loopback application with fresh game state, unavailable vision and a fresh headless Chrome profile. It uses real scoring APIs for live journeys and a paused local showcase only for deliberately rapid renderer snapshots. No real camera is requested. The active HTTPS matches on 8443 and 8444 are untouched. No deployment or certificate changes were made.

## Evidence and checks

- Existing rule/API regressions: **48/48 PASS**, recorded in `qa-artifacts/presentation-animation-python-results.txt`.
- Actual visible score drain through three T20s: 301 → 241 → 181 → **121**; settled banked turn points **180**. Each dart appears once, with its segment and points.
- Reservoir final height agrees with remaining/start score for both 301 and 501: 121/301 and 321/501. Numeric percent rounds correctly; an intermediate first-dart score confirms visible motion rather than only a final snapshot.
- Repeated identical renderer inputs and unchanged live polls preserve the existing score DOM node, perform zero observed game-tree mutations and never replay the 180 scene.
- Next turn introduces the actual next player. Undo restores the previous player, three darts and remaining reservoir accurately.
- Overshoot restores the turn-start score and banks zero. Undo restores the pre-bust score; checkout reaches zero and a winner scene; undo removes the pending/current winner scene.
- Rapid snapshots interrupt an in-flight tween and settle at the latest authoritative score and turn total; an older frame never overwrites the final state.
- Reduced motion reaches exact score/gauge values on the next frame, disables computed dart animation and suppresses entrance/180 scenes.
- Showcase Pause is checked immediately during numeric drain, and again for a visible 180 scene beyond its usual duration. Restart resets to 301 and resumes from the opening entrance. The natural 180/next-player flow remains isolated from live state and performs zero API traffic.
- A host UI score tests its 610ms cooldown repaint: the score node survives while its tween runs, scoring becomes available normally and no full-screen stage covers host input.
- All three routes are checked at 320, 736, 1280 and 1920px for horizontal overflow. Phone and TV captures receive visual inspection.

Machine-readable result: `qa-artifacts/presentation-animation-results.json`; console: `qa-artifacts/presentation-animation-console.txt`.

## Visual artifacts

`qa-artifacts/presentation-animation-settled180-{320,1920}.png` shows 121 remaining, 180 banked and all three T20s. `presentation-animation-maximum180-1920.png` shows the dedicated 180 scene; `presentation-animation-kapil-entrance-1920.png` and `presentation-animation-maya-handoff-1920.png` show named entrances. Other captures show the first hit, bust restoration, victory, 501 reservoir and final route layouts.

Stage screenshots wait for computed opacity above .95, including the large stage text; settled captures wait below .01. This corrects early screenshot timing that captured fades. Optional video was omitted because the environment lacks Playwright's ffmpeg binary; no dependency was installed.

## Verdict

**PASS — no open software blocker in this animation scope.** All nine independent browser groups pass, with zero browser errors, zero spectator mutation requests and no camera access. All 48 existing Python tests pass. Final clean 320px and 1920px settled captures were visually inspected: 121 remaining, 180 banked, three T20 results and 40% left are legible; the stage fully clears. PM separately reviewed the clean maximum scene. Pause freezes the in-flight numeric drain and preserves the 180 overlay lifetime; Restart and the natural next-player flow pass. Host input remains unobscured.

Root separately verified deployed asset hashes and that the 8443 active match and empty 8444 state were unchanged; that PM evidence is `qa-artifacts/presentation-animation-deployment.json`, outside this isolated QA run. Physical-camera/hardware acceptance remains outside scope.
