# QA — M1-05c / M1-05d / M1-05e and merge 86a3b6b

Worktree `/home/user/qa-m1g`, detached at `86a3b6b` (merge of m1-05c into main@7d05376). These are synthetic results only, not evidence about a real board. Probe scripts are in the QA scratchpad (`m1g/`).

## Verdicts

| Item | Verdict | Notes |
|---|---|---|
| M1-05c calibration refinement | **PASS-WITH-NOTES** | The claims reproduce trial for trial. The 12 px click-error acceptance rule throws away good fits when the clicks are sloppy (D1). |
| M1-05d ceiling mounts + occlusion | **PASS** | The ceiling numbers reproduce. The occlusion conclusions match the artifact. |
| M1-05e segmentation hardening | **PASS-WITH-NOTES** | D-A, D-B and D-C are fixed for the QA scenarios. The worst case on dense *large* fragments is still about 0.3–0.4 s (D4). |
| Merge 86a3b6b | **PASS** | 213/213 tests OK. The real server works end to end with refinement, including a save/restart restore. |

**Safe to push: YES.** There are no High defects. D1 should be fixed before real-footage trials (M2).

## Reproduced numbers
Gate commands use `run_detection_gate.py --pipelines current`, 200 darts per cell.

| Cell | Claimed | Reproduced |
|---|---|---|
| realistic steep-topleft, seed 2 / 3 | 93.5 / 96.5% (pooled 95.0%) | **93.5 / 96.5%**, 200/200 trials identical each |
| realistic ceiling-1.5ft, seed 2 / 3 | 94.0 / 96.5% (pooled 95.2%) | **94.0 / 96.5%**, identical |
| realistic+shadow ceiling-1.5ft, seed 2 / 3 | 91.0 / 92.0% (91.5%) | **91.0 / 92.0%**, identical |
| Speckle false proposals in those cells | 0, 0, 0, 1 of 50 | identical |
| Empty-board false proposals (realistic+shadow, ceiling-1.5ft) | 0 | **0 / 600** |
| Calibration true map error (gate cells) | 0.16–0.39 mm | max 0.20–0.26 mm, mean 0.07–0.10 mm |
| Refinement time | 0.13–0.40 s unloaded | 0.52–0.85 s on a loaded CPU (server e2e). Under 2 s. |

**Fresh holdout, seed 4 (never seen by the developer), realistic:**
- ceiling-1.5ft: **96.0%** (1.0% no proposal); speckle false proposals 0/50.
- steep-topleft: **93.0%** (0.0% no proposal); speckle false proposals 2/50.
- steep-topleft over seeds 2–4 is 94.3% (566/600).
- So "all five gated mounts ≥ 95%" is a knife-edge result. Steep-topleft sits at about 94–95% ± 1.5. Report it as "about 95%", not "met".

## Held-out discipline
The two rules changed after looking at held-out results do **not** materially contaminate the headline exact-score numbers.

- **12 px click-error rule.**
  - In the M1-05c, M1-05d and M1-05e artifacts, every calibration's `click_offset_mm` is ≤ 8 mm except ceiling-0.5ft seed 3 (10.75 mm).
  - So the old 10 mm rule and the new rule accept exactly the same calibrations on all gated mounts and on ceiling-1.5/2/3ft.
  - Only the ceiling-0.5ft seed-3 cells are contaminated. That mount is ungated and not recommended.
- **"Noisy" rule** (`MAX_IMPLAUSIBLE_BESIDE_DART`).
  - It can only turn a single-dart result into no proposal, so it cannot raise exact score. The held-out exact numbers are conservative with respect to it.
  - What *is* optimistic is the held-out speckle false-proposal figure (118 → 7). The rule was designed in response to held-out speckle failures. Seed 4 (2/50 and 0/50) is consistent with the claimed "≤ 3 per 100".

## D-A / D-B / D-C re-run (old QA probes)

| Probe | M1-05b | Now |
|---|---|---|
| D-A: 400 random fragment sets, cached `group()` vs uncached reference | 17% differ | **0 / 400** |
| D-B: `segment()` with N specks, unloaded | ~1 s at 200 | 39 specks 61 ms, 200 specks 73 ms, 400 specks 91 ms, 1000 specks 130 ms (> 40 fragments → `noisy`) |
| D-C: 20 isolated red specks, 30 boards | 9/30 "darts" | **0/30** (also 0/30 at 5/10/20/30/40 random-colour specks) |

## Occlusion (M1-05d)
I recomputed from `M1-05d-occlusion.json`, ceiling-1.5ft, seeds 2+3, darts 2–3.
- Darts whose tip is hidden by an earlier dart (n = 201): 43% exact, **43% wrong score**, 13% no proposal.
- Visible tips (n = 999): 90% exact.
- The claim holds: a hidden tip gives a wrong score about 3 times as often as it gives no proposal.
- For M1-08, the detector cannot tell that a tip is hidden. It needs an explicit "touches an earlier dart on the camera side → low confidence" rule.
- The "dart 2 visible 87%, dart 3 79%" figures match the doc table.

## Merge / server end-to-end
Script: `scratchpad/m1g/server_e2e.py`. It runs the real `server.main()` with `--state-file` and synthetic ceiling-1.5ft frames (noise σ 4, blur 1, JPEG 80).

1. **Calibrate.**
   - The clicks had 2 px σ noise (max 5.1 px off). The result was `method refined, confidence high`, residual 0.41 mm.
   - The overlay is within 0.20 px of the true double-ring points.
   - `vision.state()['calibration']` is exposed.
2. **Verify, then start a camera game.**
3. **Dart 1:** proposal S12 (truth S12). It auto-committed after 1.5 s; score 289.
4. **Dart 2:** proposal T10 (truth T10). Accepted by `proposal_id`; score 259.
5. **Undo:** score back to 289.
6. **Restart with the same state file.**
   - The match resumed, the saved calibration loaded, and the re-check reported "Board position matches".
   - The overlay moved 0.01 px from before the restart, so the **refined** homography survives.
   - After Verify, the next camera dart was proposed correctly (T10).
   - However, `vision.state()['calibration']` is **None** after the restart (D2).

The full Python suite ran 213 tests, all OK (236 s).

## Defects

**D1 — Medium (robustness): the 12 px click-error rule rejects correct refinements when the clicks are sloppy.**
- Where: `vision_calibrate.py:80` and `:395`.
- I tested with the rule disabled and found these rejection rates; the rejected fits were correct (0.1–0.3 mm):

  | Mount | Click noise σ | Correct fits rejected | Click map error → refined error |
  |---|---|---|---|
  | ceiling-1.5ft | 6 px | 2 of 10 | 10.6–12.4 mm → 0.21–0.29 mm |
  | ceiling-1.5ft | 8 px | 5 of 10 | 10–16 mm → about 0.2 mm |
  | left | 6 px | 2 of 10 | → about 0.1 mm |
  | left | 8 px | 5 of 10 | → about 0.1 mm |

- These are the sessions where refinement helps most.
- The rule is meant to catch a fit that has slipped onto the wrong sector. A one-sector slip moves a click by roughly 70–100 px, so a limit of about 30 px, or a limit relative to the board radius in pixels, would still catch it.
- Real touch taps may well exceed the harness's 2 px σ, even with the 4× loupe.

**D2 — Low: the calibration quality report is not persisted.**
- Where: `persistence.py:86-91` (save) and `:96-118` (load).
- After an M1-16 restart, `vision.state()['calibration']` is None, although the refined H is restored and the re-check passes. The setup UI loses the confidence and residual.
- Fix: save `calibration_quality` in `calibration.json` and restore it.

**D3 — Low: `refine()` can raise despite its docstring.**
- Where: `vision_calibrate.py:336`, `:345`, `:158`, `:381`.
- The docstring says "Never raises on a bad image". A 2-D (grayscale) image raises `IndexError` at `sample()` (`image.shape[2]`), and the `except` at `:381` does not catch it.
- The server path cannot reach this today, because frames are decoded as colour.
- Fix: catch `Exception`, or check that the image is 3-channel.

**D4 — Low (performance): worst case with many large fragments.**
- Where: `vision_segment.py:91` (`MAX_FRAGMENTS = 40`) and the grouping code.
- With 30–40 "cored" fragments (25×3 mm strokes), `segment()` takes 156 / 226–319 / 290–377 ms unloaded (median / max). The 150 ms target is met only for specks.
- The same scenes return `none` (silent "Ready"), `multiple`, and once a `dart`.
- It is contrived, but a hand or arm shadow breaking into large fragments is the realistic analogue. Consider a lower cap for cored fragments, or a time budget.

**D5 — Low (UX): a rejected dart gives a silent "Ready".**
- Where: `vision_segment.py:509-511`.
- When every dart-sized group is implausible, the result is `kind 'none'` and the message is "Ready". A real dart rejected by the plausibility rules would therefore give a silent no-proposal instead of "enter score manually".
- Suggest `noisy` (or a new kind) when `implausible > 0`.

**D6 — Low (UX): wrong click order is reported as high confidence.**
- Where: `vision_calibrate.py:375-378`.
- Clicks in the wrong order (rotated 90°) refine to `method refined, confidence high` with a click error of 0.24 px. The board model is rotationally symmetric, so this cannot be detected.
- It is no worse than clicks alone, but "high confidence" should not be presented to the user as "orientation correct".

**D7 — Nits.**
- `vision_segment.py:83` vs `:88`: the comment says near-frontal darts were as short as 12 mm, but `MIN_DART_LENGTH_MM = 15`, which can reject short near-frontal darts. That mount is ungated, and its score moved 49.8 → 49.3%.
- `vision.py:207`: the disabled-refinement report lacks `residual_mm` and the other keys that the refined report has.
- `server.py:576` (pre-existing, M1-16): the banner still says "game state stay[s] in memory", although the match is now saved to disk.
- `M1-05e-detection.json` has `git_commit: null`. It was produced from the working tree, as its `evidence_note` states.
