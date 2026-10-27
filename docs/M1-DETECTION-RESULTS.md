# M1-03 to M1-05e: synthetic detection results

**All numbers below come from synthetic rendered scenes (`sim/`). They measure the vision code against a model of a board and darts. They are not evidence of real-board accuracy; the Thursday trial is the real gate.**

## M1-05e: segmentation hardening (current)

This ticket fixes the three medium defects QA found in M1-05b's `vision_segment.py` (`QA-M1-05b.md`), plus the low-severity items. It was re-gated on held-out seeds 2 and 3 (realistic and realistic + shadow, all ten mounts, 200 darts per cell, plus 50 speckle trials per cell). The comparison is against M1-05c on the **same darts**: 93–100% of trials are identical per mount and profile, and the rest are the frames the fixes target.

Evidence: `qa-artifacts/M1-05e-detection.json`. It holds the gate cells, the M1-05c speckle baseline on identical trials, the unloaded timing, and the warped-board speck stress test.

### What changed (`vision_segment.py`, `vision.py`)

- **D-A, cache keys.** The "already apart" cache now uses a per-Blob serial number that is never reused. A test compares grouping on 40 random fragment sets with an uncached reference. That test fails when the key is switched back to `id()`.
- **D-B, cost.**
  - More than 40 fragments is a `noisy` scene ("Too many small changes…", no proposal); synthetic dart frames have at most 8.
  - Each Blob caches its bounding box, principal axis and per-direction extents.
  - Two fragments without a core only join when they touch, so speck pairs are rejected from bounding boxes alone.
  - The board-disc mask and gain-sample indices are cached, and the channel maximum uses OpenCV.
  - Results are unchanged by the caching.
- **D-C, plausibility.** A dart candidate must have:
  - a core fragment ≥ 50 mm² holding ≥ 15% of its pixels;
  - length ≥ 15 mm;
  - mean width (area / length) ≥ 2 mm.

  Only groups with a core join fragments across a gap, so specks are no longer chained. One plausible candidate beside two or more dart-sized implausible groups is `noisy`. On grazing views the warp stretches a 3–4 mm fleck to dart size, but such flecks rarely come alone.

  All thresholds were set on seed 1 (accepted darts: core ≥ 62 mm² and ≥ 26%, length ≥ 17 mm off near-frontal, mean width ≥ 3.3 mm). The noisy rule was added after the first held-out run showed single flecks passing on grazing views. It was chosen on seed-1 speckle and dart trials, where no dart result changed, before this final held-out run.
- **After QA (M1-05c/e QA fixes):**
  - D4: more than 12 core-sized fragments (≥ 50 mm²) is also `noisy`. 30–40 large strokes took 0.16–0.38 s and sometimes gave a false dart.
  - D5: when every dart-sized group is rejected as not dart-shaped, the result is `noisy` ("enter score manually") instead of a silent "Ready".

  Re-running three held-out cells (realistic+shadow ceiling-1.5ft s2, realistic steep-topleft s2, realistic+shadow left s3) gives 600 of 600 identical trials.
- **Low-severity items:**
  - `vision.segmentation` is cleared on `reset_base()` and `invalidate()`;
  - the 200 mm change radius is documented as also being the large-change denominator (12% ≈ 15,100 mm²; it was ≈ 11,200 mm² at 172 mm);
  - `refine_tip`'s 1.5 px tolerance has a comment;
  - `inside_shadow`'s docstring now says it tests brightness only.
- **Harness.** New `--speckle-trials`: an empty board plus 5–40 random-colour flecks of radius 0.8–2 mm, with no dart. Any proposal is false.

### Results, held-out seeds 2+3

| | M1-05c segmentation | **M1-05e** |
|---|---|---|
| Speckle false proposals (realistic, 10 mounts, 1,000 trials) | 118 (top 24, right 18, bottom 16, left 14, ceiling-1.5ft 12, …) | **7** (at most 3 per 100 on any mount) |
| QA scene: 20 isolated red specks, 30 boards | 9 of 30 "darts" (QA) | 0 of 30 (test) |
| Warped-board stress, 10 / 20 / 40 random specks (30 boards each) | 17 / 1 / 2 "darts" | 0 / 1 / 0 |
| `segment()` worst case, unloaded | 156 ms at 39 specks, 0.6 s at 100, 1.9 s at 200 | 84 ms (any count; > 40 fragments are `noisy` at about 45 ms) |
| Empty-board false proposals (exposure drift) | 0 | 0 of 3,000 (first M1-05e run) |

#### Exact score (no-proposal), M1-05c → M1-05e

| Mount | realistic | realistic + shadow |
|---|---|---|
| top | 95.8 → **95.8%** (1.0 → 1.0%) | 90.3 → **92.5%** (5.2 → 3.0%) |
| bottom | 95.5 → **95.8%** (0.8 → 0.5%) | 86.8 → **87.8%** (3.5 → 2.5%) |
| left | 96.0 → **96.5%** (2.0 → 1.5%) | 89.0 → **90.5%** (6.0 → 4.5%) |
| right | 97.5 → **97.5%** (0.8 → 0.8%) | 87.5 → **88.5%** (2.8 → 1.8%) |
| steep-topleft | 94.8 → **95.0%** (0.5 → 0.2%) | 92.8 → **93.3%** (1.5 → 1.0%) |
| near-frontal (not gated) | 49.8 → 49.3% | 38.0 → 39.8% |
| ceiling-0.5ft | 91.5 → **91.5%** | 76.0 → **79.5%** (10.8 → 5.8%) |
| **ceiling-1.5ft** | 95.0 → **95.2%** (1.2 → 1.0%) | 90.3 → **91.5%** (3.8 → 2.5%) |
| ceiling-2ft | 91.5 → **91.5%** | 88.2 → **90.0%** (4.8 → 3.0%) |
| ceiling-3ft | 82.0 → **82.2%** | 78.5 → **81.8%** (4.5 → 1.2%) |
| pooled, gated | 95.9 → **96.1%** | 89.2 → **90.5%** |

- **No regression.** Realistic is equal or better on every gated and ceiling mount. Four gated mounts are 95.8–97.5%. **Steep-topleft is about 95%, not a clear pass:** 95.0% on seeds 2+3 (380 of 400). QA's fresh seed 4 gave 93.0%, so it is 94.3% over seeds 2–4 (566 of 600). Seed 4 gave ceiling-1.5ft 96.0%.
- **Realistic + shadow improves on every mount.** Shadow speckle groups that used to make a second candidate are now implausible, which cuts no-proposal by 1–5 points. Left (4.5%) now meets the 5% no-proposal target. Near-frontal (7.3%) and ceiling-0.5ft (5.8%) do not.
- **Ideal** was not re-run after the last rule; that rule can only remove proposals. In the first M1-05e run, held-out ideal was equal to or above M1-05c on every mount but one (ceiling-2ft 94.0% vs 94.2%), with 0 of 3,000 empty-board false proposals.

### Timing (D-D correction)

M1-05b's "60–120 ms" understated the worst case. QA measured up to 171 ms with shadow and about 1 s with many fragments. M1-05e on this container, unloaded:
- `segment()` median 23–44 ms;
- worst case 84 ms at 39–41 specks;
- above 40 fragments it stops early (about 45 ms).

`Vision.ingest` p95 was 46–54 ms per frame in the M1-05e gate run (4 workers on 4 CPUs).

### Limits

- **A lone fleck can still pass.** One dart-sized fleck on a grazing view (about 4 mm across, stretched to 15–18 mm in the warp) is indistinguishable by shape from a short dart. That is about 3 in 100 speckle trials on ceiling-0.5ft. A pose-aware minimum projected length would separate them; it is not done.
- **Unchanged from M1-05c/d:** near-frontal (not gated) remains at about 50%, and hidden tips under earlier darts mostly give wrong scores (M1-05d).
- **Refit on real footage.** The plausibility thresholds come from synthetic darts and must be refit on Thursday's footage (M2-02).

## M1-05d: ceiling mounts — SYNTHETIC (the owner's planned geometry)

**Synthetic only.** These are rendered scenes of the owner's ceiling geometry (`docs/DECISIONS.md` #2). They rank the mount distances against each other under the harness's model; they do not predict Thursday's real accuracy.

### Geometry and camera assumptions

- **Room:** 7.5 ft (2286 mm) ceiling, bull at 1730 mm, phone 30 mm below the ceiling. The camera is therefore 526 mm above the bull, centred left-right, and aimed at the bull. In board mm the camera sits at (0, −526, d), where d is the distance from the wall.
- **Phone:** Samsung Galaxy S22 main camera at 1×, 1920×1080. **Assumed 78° diagonal FOV** (about 70.4° horizontal, 43° vertical): the 4:3 still is about 85° diagonal, the 16:9 video crop about 80°, and stabilisation crops a little more. No lens distortion is modelled.
- **Random streams:** keyed by mount name (D7), so the original six mounts' darts are unchanged.

| Mount | Distance from wall | View angle above the board plane | Camera to bull | Resolution at the bull, across / up-down (px per mm) |
|---|---|---|---|---|
| ceiling-0.5ft | 152 mm | 16° | 548 mm | 2.48 / **0.69** |
| **ceiling-1.5ft (planned)** | 457 mm | 41° | 697 mm | 1.95 / 1.28 |
| ceiling-2ft | 610 mm | 49° | 805 mm | 1.69 / 1.28 |
| ceiling-3ft | 914 mm | 60° | 1055 mm | 1.29 / 1.12 |
| (top, for reference) | 500 mm | 48° | 673 mm | 2.04 / 1.51 |

Evidence:
- `qa-artifacts/M1-05d-ceiling-detection.json`: M1-05b vs M1-05c, seeds 1–3, three profiles, 200 darts per cell, plus 50 empty-board trials per cell.
- `qa-artifacts/M1-05d-occlusion.json`: realistic, seeds 2 and 3, 100 turns per scenario.

### Single darts: exact score, held-out seeds 2+3 (400 darts per mount; seed 1 in brackets)

| Mount | ideal M1-05b | ideal M1-05c | realistic M1-05b | **realistic M1-05c** | realistic+shadow M1-05b | **realistic+shadow M1-05c** |
|---|---|---|---|---|---|---|
| ceiling-0.5ft | 97.2% | 97.8% (98.5) | 93.2% | **91.5%** (90.5) | 75.2% | **76.0%** (79.5) |
| **ceiling-1.5ft** | 96.2% | 96.2% (96.0) | 87.8% | **95.0%** (93.5) | 82.2% | **90.3%** (88.0) |
| ceiling-2ft | 94.2% | 94.2% (95.0) | 89.8% | **91.5%** (93.0) | 86.8% | **88.2%** (86.5) |
| ceiling-3ft | 85.5% | 85.5% (82.5) | 80.0% | **82.0%** (78.5) | 75.5% | **78.5%** (72.0) |

#### M1-05c details, held-out seeds 2+3

| Mount | realistic no-proposal | realistic tip median / p95 (mm) | realistic near-wire exact | realistic+shadow no-proposal | calibration residual (mm) | true map error, max (mm) | low-confidence proposals (ideal, 400 darts) |
|---|---|---|---|---|---|---|---|
| ceiling-0.5ft | 0.0% | 2.15 / 4.61 | 73.2% | 10.8% | 0.49 | 0.22 | 0 |
| ceiling-1.5ft | 1.2% | 0.94 / 1.79 | 82.4% | 3.8% | 0.41 | 0.26 | 3 |
| ceiling-2ft | 0.8% | 0.96 / 2.09 | 67.5% | 4.8% | 0.43 | 0.30 | 24 |
| ceiling-3ft | 1.0% | 1.39 / 27.25 | 61.9% | 4.5% | 0.48 | 0.46 | 153 |

0 false proposals in 1,800 empty-board trials across both pipelines.

What the numbers say:
- **ceiling-1.5ft (planned) is the best ceiling mount on single darts.** Realistic is 95.0% (M1-05b: 87.8%) and realistic + shadow 90.3%, with 1.2% no-proposal. Calibration refinement is worth 7–8 points here: at 41° each click pixel is about 0.8 mm of board up-down.
- **ceiling-0.5ft is resolution-limited.** At 16° the board is 257 px tall (0.69 px per mm up-down).
  - Even in ideal the tip error median is 1.44 mm, against 0.7 mm elsewhere. Realistic adds noise, and hard shadows give 10.8% no-proposal (shadows are long at a grazing angle).
  - Refinement does not help here: M1-05c 91.5% vs M1-05b 93.2%, within noise. The tip error median rose from 1.2 to 2.2 mm, so the M1-05b click errors seem partly to have cancelled the grazing-view tip bias by chance.
  - The original M1-05c acceptance rule rejected a correct refinement on this mount; see M1-05c.
- **ceiling-3ft (60°) is the worst.** Steeply tilted darts point almost at the lens, so the dart blob is not elongated and the tip rule falls back to "nearest the foot point": 153 of 400 ideal proposals are low-confidence, and most errors are among them. `docs/DECISIONS.md` #2 predicted this ("beyond ~60° … each dart starts hiding its own tip").
- **ceiling-2ft** sits between 1.5 ft and 3 ft, 2–3.5 points below 1.5 ft.

### Several darts in a turn (throw by throw), realistic, seeds 2+3, M1-05c

The detector proposes one new dart per stable frame, so each turn is simulated throw by throw: dart k is detected against a base image that already holds darts 1..k−1, as M1-08 will do.

Scenarios, 100 turns each per seed:
- **T20 group:** three darts aimed at T20, σ 8 mm.
- **T20 → neighbours:** T20, then T5 or T1, then the other one.
- **Stacked below:** dart 2 lands 30–80 mm directly below dart 1, and dart 3 30–80 mm below dart 2.

"Visible" is geometric (harness only): no earlier dart, and not the dart's own body, covers the tip's image point.

Each cell gives: tip visible / exact score.

| Mount | dart 1 (all) | dart 2 (all) | dart 3 (all) | T20 group, dart 3 | neighbours, dart 3 | stacked below, dart 2 | stacked below, dart 3 |
|---|---|---|---|---|---|---|---|
| ceiling-0.5ft | 100% / 91% | 92% / 84% | 82% / 76% | 86% / 82% | 100% / 86% | 80% / 74% | 60% / 61% |
| **ceiling-1.5ft** | 100% / 94% | 87% / 86% | 79% / 79% | 86% / 85% | 100% / 92% | 72% / 80% | 52% / 58% |
| ceiling-2ft | 99% / 90% | 85% / 80% | 79% / 78% | 84% / 78% | 96% / 86% | 67% / 74% | 56% / 70% |
| ceiling-3ft | 90% / 73% | 80% / 66% | 74% / 66% | 71% / 58% | 80% / 62% | 80% / 72% | 70% / 76% |
| top (reference) | 100% / 90% | 88% / 80% | 79% / 76% | 83% / 76% | 98% / 86% | 74% / 78% | 56% / 68% |

- **Visible tips stay accurate.** On ceiling-1.5ft, darts 2 and 3 score 91% and 89% when their tip is visible. When the tip is hidden by an earlier dart they score 50% and 39%; the rest are wrong (9% and 13% of darts 2 and 3) or have no proposal (5–8%).
- **Stacked darts are the hard case at every mount.** A dart landing directly below an earlier one has a hidden tip in 28–48% of throws on ceiling-1.5ft (that is what "below" means for a camera above the board). Neighbours (T20 → T5/T1) are almost never hidden on 0.5–2 ft.
- **Hidden tips usually give a wrong score, not "no proposal".** The detector does not know the tip is hidden. M1-08 / M1-12 should treat a new dart whose blob touches an earlier dart, on the camera side, as low confidence.
- **ceiling-0.5ft does not occlude more here than 1.5 ft.** The simulated darts are thin and the scenarios put dart 2 directly below dart 1, so the grazing view's long "hidden strip" rarely covers the next tip. This does not cover the flight-shadowed strip or the thicker real flights that `docs/DECISIONS.md` #2 worries about.
- **ceiling-3ft hides tips by the dart's own body** in 9–10% of throws.

### Recommendation for Thursday

**Keep the planned mount: 1.5 ft (about 46 cm) from the wall, centred on the board, aimed at the bull.**
- It has the best single-dart accuracy of the ceiling mounts (realistic 95.0%, with hard shadows 90.3%) and later-dart accuracy as good as any distance tested.
- Do not go closer than about 1.5 ft: 0.5 ft loses resolution up-down and is badly hurt by shadows.
- Do not go to 3 ft: darts start pointing at the lens.
- 2 ft is an acceptable fallback if 1.5 ft is physically awkward (2–3.5 points lower in the harness).
- Diffuse light near the board still matters most for the shadow case.

## M1-05c: calibration refinement

Same harness, darts and seeds as M1-05b: 200 single-dart trials per mount and seed, 1920×1080, HFOV 70°, tuned on **seed 1 only**, with seeds 2 and 3 **held out**. The segmentation is unchanged from M1-05b. The only change is that the four-click homography is refined from the image (`vision_calibrate.py`). With refinement off, the same code reproduces the M1-05b trials exactly (checked trial for trial on two cells), so the M1-05b columns below are M1-05b's own evidence.

Evidence:
- `qa-artifacts/M1-05c-detection.json`: all trials, seeds 1–3, four profiles, six mounts, with false-proposal and two-dart trials. Its `evidence_note` says which code produced it.
- `qa-artifacts/M1-05c-calibration-fresh-draws.json`: calibration only, 30 fresh click draws per mount (seeds 101–130, not the gate seeds), all ten mounts.

### Result in one paragraph

Calibration error is no longer an accuracy factor in the harness.
- **Calibration error:** with σ = 2 px click noise, the error of the board map within the double ring falls from 2.4–3.6 mm (median of the worst point) to 0.16–0.39 mm. The largest error over all 72 gate calibrations is 0.43 mm.
- **Exact score:** held-out realistic rises from 87.5–94.5% to **94.8–97.5%** on the gated mounts (pooled 95.9%; M1-05b 92.1%), which equals the M1-05b no-click-noise ablation. Realistic + shadow rises from 83.7–86.5% to 86.8–92.8%.
- **No change where clicks were exact:** ideal and ideal + shadow are unchanged (they have no click noise).
- **Targets:** the ≥ 95% realistic target is met on four of the five gated mounts. **Steep-topleft is 94.8% (379 of 400), one dart short.**
- **Cost:** refinement takes 0.13–0.40 s per calibration on this container unloaded (at most 1.3 s with the CPU 8× oversubscribed).

### Targets (held-out seeds 2+3, gated mounts)

| Target | Result | Met? |
|---|---|---|
| ≥ 95% exact, realistic, gated off-axis mounts | 95.8 / 95.5 / 96.0 / 97.5 / **94.8%** (top / bottom / left / right / steep-topleft) | 4 of 5 (steep-topleft misses by 1 dart in 400) |
| Calibration residual reported in mm | Fit residual (RMS distance of the found edges from the board model) 0.13 mm ideal (0.32 steep-topleft), 0.39–0.44 mm realistic. True map error (harness only) at most 0.13 mm ideal and 0.43 mm realistic | Yes |
| Refinement < 2 s (Mac-class CPU) | Median 0.13–0.22 s, max 0.40 s unloaded (10 draws per mount); max 1.3 s in the loaded gate run | Yes |
| Confidence/residual in `vision.state()` | `state()['calibration']` = `{method: refined\|clicks, confidence: high\|low, reason, residual_mm, click_offset_mm, click_error_px, edge_points, sampled_points, ring_sectors, spokes, seconds}` | Yes |
| Graceful fallback | Blank, random-texture and mostly covered images keep the clicks and give a reason (tests). Every gate and fresh-draw calibration was refined (372 of 372) | Yes |
| Tuned on seed 1 only | Pooled realistic: seed 1 94.5%, seeds 2/3 95.8% / 96.0% (seed 1 is the lowest; no tuning advantage) | Yes |

### Exact score, held-out seeds 2+3 (400 darts per mount; seed 1 in brackets)

| Mount | ideal M1-05b | **ideal M1-05c** | realistic M1-05b | **realistic M1-05c** | ideal+shadow M1-05c | realistic+shadow M1-05b | **realistic+shadow M1-05c** |
|---|---|---|---|---|---|---|---|
| top | 95.2% | **95.2%** (94.5) | 92.0% | **95.8%** (92.5) | 95.8% | 86.0% | **90.3%** (88.0) |
| bottom | 96.8% | **96.8%** (98.5) | 93.8% | **95.5%** (96.0) | 94.0% | 85.0% | **86.8%** (87.0) |
| left | 96.2% | **96.2%** (95.5) | 94.5% | **96.0%** (93.0) | 96.2% | 86.5% | **89.0%** (84.5) |
| right | 96.5% | **96.5%** (95.5) | 92.8% | **97.5%** (95.5) | 94.0% | 85.0% | **87.5%** (85.5) |
| steep-topleft | 97.8% | **97.8%** (99.0) | 87.5% | **94.8%** (95.5) | 97.5% | 83.7% | **92.8%** (90.5) |
| near-frontal (not gated) | 50.8% | 51.2% (49.5) | 50.7% | 49.8% (46.5) | 50.8% | 39.0% | 38.0% (38.0) |

The ideal profile has exact clicks, so the refined map moves by at most 0.13 mm there. Held-out ideal is identical to M1-05b on every gated mount. Ideal + shadow is within 0.7 points of M1-05b on every mount (M1-05b: 96.0 / 94.2 / 96.5 / 94.2 / 96.8%).

#### Realistic, M1-05c, held-out seeds 2+3: other metrics

| Mount | no proposal | tip median / p95 (mm) | near-wire exact | not-near-wire exact | calibration residual (mm) | true map error, max (mm) |
|---|---|---|---|---|---|---|
| top | 1.0% | 0.77 / 1.77 | 86.2% | 97.9% | 0.40 | 0.20 |
| bottom | 0.8% | 0.68 / 1.35 | 82.3% | 99.1% | 0.39 | 0.22 |
| left | 2.0% | 0.78 / 1.49 | 85.8% | 97.9% | 0.40 | 0.19 |
| right | 0.8% | 0.78 / 1.63 | 91.4% | 98.8% | 0.39 | 0.21 |
| steep-topleft | 0.5% | 1.22 / 2.39 | 76.7% | 99.4% | 0.44 | 0.30 |

M1-05b realistic tip median was 1.03–2.55 mm; it is now 0.68–1.22 mm. No-proposal: realistic 0.5–2.0%, realistic + shadow 1.5–6.0% (left 6.0% and top 5.2% still miss the 5% target). False proposals: 0 of 7,200 empty-board trials. Two-dart frames are declined 79–91% of the time, as in M1-05b.

### How the refinement works (`vision_calibrate.py`)

1. **Model edges.** About 2,240 sample points on the board's own edges: the outer-bull, treble and double ring circles (3 mm apart, kept ≥ 3 mm from the wires that cross them), and the 20 radial wires between r = 30 and 168 mm (2 mm apart, away from the rings). Each point carries its edge normal.
2. **Find each edge in the image.**
   - Under the current homography, sample the colour across the edge (±window, 0.1 mm steps), plus one colour well inside each neighbouring region.
   - Project the profile onto the difference of the two region colours. This gives a 0 → 1 step whatever the colours are (black/cream, red/green, ring/number ring).
   - The edge is the sub-sample peak of the step's slope. When the wire itself is visible (colour off the line between the two sides, within 1.2 mm of the step), the edge is the wire's centre instead. The step alone sits up to half a wire width (±0.5 mm) toward one side, which biased the outer double ring outward.
   - Flat, weak (< 25 colour units), reversed or out-of-frame profiles are dropped.
3. **Fit.** Gauss-Newton over the 8 homography parameters, minimising the distance of each found point (mapped to the board) from its model curve: |q| − R for a ring, the perpendicular distance for a wire. Residuals are weighted by pixels per mm, with Tukey robust weights, so darts or occlusions in the calibration image are outliers.
4. **Coarse to fine.** The search window is ±6, then ±3, then ±1.5 mm. 6 mm covers 2 px click noise even on the grazing ceiling-0.5ft view.
5. **Accept or keep the clicks.** The refined fit is used only when all of these hold:
   - ≥ 300 inliers and ≥ 40% of the sampled points;
   - inliers in ≥ 10 of 12 ring sectors and on ≥ 14 of 20 wires;
   - RMS residual ≤ 0.6 mm;
   - the fit moves no clicked point by more than max(30 px, 10% of the board's radius in the image). A fit that slipped by one sector moves a click by about 30% of the radius (70–100 px).

   Otherwise the clicks are kept and the setup message names the reason.

   The last check was first written as "≤ 10 mm change of the board map". On the grazing `ceiling-0.5ft` view, 2 px of click noise is 11 mm of board, and that rule rejected one correct refinement (held-out seed 3, M1-05d). It now uses pixels, because clicks are made in pixels. That change was prompted by a held-out observation, so it was validated on fresh draws (`M1-05c-calibration-fresh-draws.json`: 300 of 300 refined, worst map error 0.52 mm). Re-running every gate calibration with the new rule gives identical results except that one.

   After QA (D1), the 12 px limit became max(30 px, 10% of the board radius). 12 px rejected correct fits with sloppy clicks: 2 of 10 at 6 px click noise, 5 of 10 at 8 px. A test now refines 6–8 px click noise on ceiling-1.5ft and left to < 0.6 mm. All gate clicks are within 12 px, so no gate result changes.

It uses only the calibration image and the clicks; nothing from the harness. A refined calibration also becomes the alignment reference (`align()` composes onto it) and feeds the pose solver.

### QA fixes (M1-05c/e QA, `QA-M1-05cde.md`)

- **D1:** the click-error limit is now relative to the board's size in the image (above).
- **D3:** `refine()` accepts a grayscale image and never raises; any failure keeps the clicks with a reason.
- **D6:** if the 20 (first click) is not the topmost click, the report says `confidence: 'low'` with a `warning` (wrong click order, or a phone that is not upright). The board model is rotationally symmetric, so the fit itself cannot tell; the refined homography is still used. The setup UI should show `warning`.
- **D7:** with refinement off, the report now has the same keys as a refined one.

### What limits accuracy now

With calibration error at 0.1–0.4 mm, the remaining realistic errors are the detector's:
- near-wire darts with 1–1.5 mm tip error (realistic tip median 0.7–1.2 mm vs 0.6–0.9 mm ideal);
- no-proposals, mostly realistic + shadow;
- low-confidence darts nearly along the view ray.

Of the 82 held-out realistic errors on the gated mounts:
- 59 are near-wire darts (steep-topleft: 19 of 21);
- 20 have no proposal;
- 6 are low-confidence (not-elongated) proposals.

Not-near-wire darts score 97.9–99.4%. The next lever is tip localisation under noise, not calibration. The renderer bias (about +0.5 mm toward the foot point, M1-05b) is still not corrected, on purpose.

### Not covered

- **Real boards:** wires are raised 1–2 mm off the surface (parallax on steep views), worn colours, a number ring that may be rotated, and lens distortion. The S22 main lens has little distortion, but a homography cannot absorb any that is left; it would show up as a larger residual.
- **Thresholds:** the window and acceptance thresholds were set on synthetic seed 1 and must be checked on Thursday's calibration frames. The setup UI should show `residual_mm` and the reason when the clicks are kept.

## M1-05b: robust dart segmentation

200 single-dart trials per mount and seed, 1920×1080, HFOV 70°, every dart in the board (r ≤ 170 mm). Thresholds were tuned on **seed 1 only**; seeds 2 and 3 are **held out**, and the tables quote them (400 darts per mount) next to seed 1. The old rule and M1-05 columns are the M1-05 `vision.py` (commit 9af1ad3) run through today's harness on the same darts (`tools/run_detection_gate.py --pipelines m105-foot,m105-centre`). Shipped `TIP_BIAS_MM` is 0.0 (QA D1).

Evidence: `qa-artifacts/M1-05b-detection.json` (M1-05b, all trials, seeds 1–3, four profiles, with false-proposal and two-dart trials), `qa-artifacts/M1-05b-baseline-m105.json` (M1-05 on the same darts), `qa-artifacts/M1-05b-tip-bias-sensitivity.json`, `qa-artifacts/M1-05b-ablation-realistic-no-click-noise.json` (diagnostic). The evidence was produced from the working tree committed as "M1-05b: Robust dart segmentation"; its `git_commit` field names the parent commit.

### Result in one paragraph

Segmentation is no longer the bottleneck. On held-out seeds, no-proposal falls from 73–86% (M1-05, per seed and mount) to 0.2–2.0%, and exact score (mean of seeds 2 and 3) rises from 13–18% to **95.2–97.8% (ideal)** and **87.5–94.5% (realistic)** on the five gated mounts. With hard shadows, M1-05b reaches **94.2–96.8% (ideal)** and **83.7–86.5% (realistic)**; M1-05 got 0.8–16%. No empty-board trial produced a proposal (0 of 7,200, with an exposure drift of up to ±10%). **The targets are not met:** realistic is below 95% on every gated mount (pooled 92.1% held-out). Most of the remaining error is near-wire darts and a per-session calibration offset of 1–3 mm in the realistic profile (2 px click noise), not segmentation. Realistic + shadow also misses the 5% no-proposal target on two mounts (top 5.8%, left 7.5%).

### Targets (held-out seeds 2+3, gated mounts)

| Target | Result | Met? |
|---|---|---|
| ≥ 95% exact, realistic, off-axis mounts | 92.0 / 93.8 / 94.5 / 92.8 / 87.5% (top / bottom / left / right / steep-topleft) | **No** (all five) |
| No-proposal ≤ 5% | ideal 0.2–2.0%, realistic 0.5–2.0%, ideal + shadow 0.2–2.0%, realistic + shadow 2.2–7.5% | Yes, except realistic + shadow on top and left |
| False-proposal rate reported | 0 / 7,200 empty-board trials (all seeds, profiles and mounts) | Reported |
| Hard-shadow profile reported | See the shadow tables | Reported |
| Near-wire split reported | See the near-wire table | Reported |
| Tuned on seed 1, reported on 2 and 3 | Pooled realistic: seed 1 93.0%, seeds 2/3 91.7% / 92.5% (about a 1-point tuning gap) | Yes |

### Tables

"s2+3" is the mean of seeds 2 and 3 (held out). Gated mounts: top, bottom, left, right, steep-topleft.

#### Exact score, ideal (seeds 2+3 held out, 400 darts per mount; seed 1 = tuning)

| Mount | old rule (M1-05 centre) s2+3 | M1-05 foot s2+3 | **M1-05b s2+3** | M1-05b seed 1 | M1-05b no-proposal s2+3 |
|---|---|---|---|---|---|
| top | 14.0% | 16.0% | **95.2%** | 95.0% | 1.2% |
| bottom | 12.8% | 13.0% | **96.8%** | 98.5% | 0.2% |
| left | 15.0% | 18.0% | **96.2%** | 95.5% | 2.0% |
| right | 16.0% | 17.8% | **96.5%** | 95.5% | 1.0% |
| steep-topleft | 16.0% | 17.0% | **97.8%** | 98.5% | 0.8% |
| near-frontal (not gated) | 9.5% | 23.2% | **50.8%** | 49.5% | 1.2% |

#### Exact score, realistic (seeds 2+3 held out, 400 darts per mount; seed 1 = tuning)

| Mount | old rule (M1-05 centre) s2+3 | M1-05 foot s2+3 | **M1-05b s2+3** | M1-05b seed 1 | M1-05b no-proposal s2+3 |
|---|---|---|---|---|---|
| top | 15.5% | 17.8% | **92.0%** | 93.0% | 1.5% |
| bottom | 11.2% | 12.5% | **93.8%** | 97.0% | 1.0% |
| left | 13.0% | 15.5% | **94.5%** | 92.5% | 2.0% |
| right | 13.8% | 15.5% | **92.8%** | 92.0% | 1.0% |
| steep-topleft | 14.3% | 15.5% | **87.5%** | 90.5% | 0.5% |
| near-frontal (not gated) | 6.5% | 17.2% | **50.7%** | 52.0% | 1.2% |

#### Exact score, ideal + hard shadow (default light)

| Mount | M1-05 foot s2+3 | **M1-05b s2+3** | M1-05b seed 1 | M1-05b no-proposal s2+3 |
|---|---|---|---|---|
| top | 10.8% | **96.0%** | 95.0% | 1.2% |
| bottom | 1.5% | **94.2%** | 96.0% | 0.2% |
| left | 5.0% | **96.5%** | 95.0% | 2.0% |
| right | 2.5% | **94.2%** | 91.0% | 1.0% |
| steep-topleft | 16.2% | **96.8%** | 98.0% | 0.8% |
| near-frontal (not gated) | 6.2% | **50.5%** | 49.0% | 1.2% |

#### Exact score, realistic + hard shadow

| Mount | M1-05 foot s2+3 | **M1-05b s2+3** | M1-05b seed 1 | M1-05b no-proposal s2+3 |
|---|---|---|---|---|
| top | 8.2% | **86.0%** | 89.5% | 5.8% |
| bottom | 0.8% | **85.0%** | 84.5% | 3.2% |
| left | 2.8% | **86.5%** | 85.0% | 7.5% |
| right | 2.0% | **85.0%** | 82.5% | 3.2% |
| steep-topleft | 7.5% | **83.7%** | 86.0% | 2.2% |
| near-frontal (not gated) | 2.8% | **39.0%** | 42.0% | 12.0% |

#### Near-wire split, M1-05b, held-out seeds 2+3 (exact score; n darts)

| Mount | ideal near-wire | ideal not near | realistic near-wire | realistic not near | realistic+shadow near-wire | realistic+shadow not near |
|---|---|---|---|---|---|---|
| top | 86.1% (72) | 97.3% (328) | 77.8% (72) | 95.1% (328) | 75.0% (72) | 88.4% (328) |
| bottom | 85.7% (84) | 99.7% (316) | 83.3% (84) | 96.5% (316) | 70.2% (84) | 88.9% (316) |
| left | 87.3% (63) | 97.9% (337) | 77.8% (63) | 97.6% (337) | 63.5% (63) | 90.8% (337) |
| right | 86.8% (68) | 98.5% (332) | 66.2% (68) | 98.2% (332) | 51.5% (68) | 91.9% (332) |
| steep-topleft | 90.0% (80) | 99.7% (320) | 62.5% (80) | 93.8% (320) | 53.8% (80) | 91.2% (320) |
| near-frontal | 40.0% (80) | 53.4% (320) | 33.8% (80) | 55.0% (320) | 28.7% (80) | 41.6% (320) |

#### Tip error (mm), M1-05b, held-out seeds 2+3: median / p95 (mean of the two seeds)

| Mount | ideal | realistic | ideal+shadow | realistic+shadow |
|---|---|---|---|---|
| top | 0.61 / 1.36 | 1.83 / 3.49 | 0.86 / 1.80 | 2.04 / 4.20 |
| bottom | 0.56 / 1.11 | 1.58 / 2.90 | 0.69 / 2.29 | 1.87 / 5.41 |
| left | 0.63 / 1.20 | 1.03 / 2.20 | 0.91 / 1.75 | 1.21 / 2.81 |
| right | 0.64 / 1.37 | 1.69 / 2.89 | 0.86 / 2.43 | 1.97 / 5.29 |
| steep-topleft | 0.84 / 1.58 | 2.55 / 4.91 | 0.96 / 1.71 | 2.71 / 5.31 |
| near-frontal | 21.90 / 56.54 | 18.88 / 53.55 | 21.90 / 56.54 | 23.18 / 57.82 |

#### False proposals (empty board, exposure drift up to ±10%) and two-dart frames, M1-05b, all seeds

| Profile | empty trials | false proposals | two-dart frames | declined (no proposal) | one of the two | wrong |
|---|---|---|---|---|---|---|
| ideal | 1800 | 0 (0.0%) | 900 | 84.2% | 14.4% | 1.3% |
| realistic | 1800 | 0 (0.0%) | 900 | 83.9% | 14.3% | 1.8% |
| ideal+shadow | 1800 | 0 (0.0%) | 900 | 84.3% | 14.0% | 1.7% |
| realistic+shadow | 1800 | 0 (0.0%) | 900 | 82.9% | 14.3% | 2.8% |

### What changed (`vision_segment.py`, `vision.py`)

1. **Illumination normalisation.** A per-channel gain (median frame/base ratio over the board) is divided out before differencing, so exposure or white-balance drift is not a change. A gain outside 0.5–2 counts as a large scene change.
2. **Colour-aware change.** The largest per-channel difference is thresholded at max(30, 5 × the median difference), capped at 60. Hysteresis then keeps weaker change (> half the threshold) that is connected to a strong change, so a thin, blurred point survives and isolated noise does not.
3. **Shadow removal.** A cast shadow darkens every channel by about the same factor, so chromaticity is kept. A changed pixel counts as shadow when its mean frame/base ratio is 0.25–0.8 and the ratios agree within 10% on the channels the base shows well (≥ 60). Dim channels, such as the green and blue of the red ring, must not get brighter. Small fragments surrounded by darkened board (noise speckles inside a shadow) are dropped.
4. **Fragment grouping.** A fragment joins a group if it is within 5 mm of it, or if its near end lies in a narrow wedge (5 mm, widening by 10°, up to 70 mm away) along the group's principal axis or along the direction away from the foot point. Past the dart's end nearest the foot point only the tip can lie, so a fragment joined there across a gap must be point-shaped (solid, elongated, at least 4 mm long, within 25° of the dart's axis). Shadow edges and speckles beyond the tip fail that test.
5. **One dart vs two.** Groups of at least 40 mm² are candidates. Exactly one gives a proposal; two or more give "More than one new dart" and no proposal. A group above 8,000 mm² gives "too large".
6. **Tip localisation.** The tip end is still chosen by the M1-05 foot rule (axis and elongation from the outline, as M1-05 used the contour). It is then refined on the point's own local axis, using pixels within 12 mm of that end, to the centre of the far end. Finally it moves to the sub-pixel crossing where the change falls to half the point's own contrast. This replaces a fixed threshold, which put the end too far out on high-contrast backgrounds and too far in on low-contrast ones.

The detector uses no harness ground truth: only the frame, the empty-board base and the foot point from calibration (M1-04). A fix along the way: an even-sized (2×2) opening kernel shifted the mask by one pixel toward +x/+y. The shipped code uses a symmetric 3×3 cross.

### Remaining failure modes (held-out, gated mounts, 2,000 darts per profile)

- **Calibration offset (realistic).** With σ = 2 px click noise, each session's homography is off by a fixed 1–3 mm (the median detected − true offset per mount and seed ranges up to 2.7 mm). That alone moves near-wire darts across a wire. Diagnostic ablation (realistic without click noise, held-out seeds, `qa-artifacts/M1-05b-ablation-realistic-no-click-noise.json`): 95.5 / 95.2 / 96.2 / 97.0 / 95.0% (top / bottom / left / right / steep-topleft) with tip median about 0.7 mm. That is at or above the 95% target on all five mounts. **Calibration accuracy (refining the four clicks, for example by fitting the double ring) is now the biggest lever for realistic accuracy.** This is a PM input; it is not done here.
- **Near-wire precision.** Realistic: 158 errors in 2,000 darts. 93 are near-wire darts (45 with tip error ≤ 2 mm, 44 with 2–5 mm, 4 with > 5 mm), 41 are other darts with tip error over 2 mm, and 24 have no proposal. Ideal: 39 of its 70 errors are near-wire darts with tip error ≤ 2 mm.
- **Renderer bias.** In ideal the detected tip sits about 0.5 mm past the true tip toward the foot point on every mount. OpenCV's anti-aliased polygons are drawn about half a pixel oversize, so this is a property of `sim/`, not physics. With a −0.6 mm bias (the seed-1 robust median), held-out ideal is unchanged (pooled 97.0 / 96.0% vs 96.9 / 96.1%) and realistic rises 1–3 points per mount, to 93.5 / 95.2 / 95.0 / 94.2 / 90.5% (pooled 92.8 / 94.6% vs 91.7 / 92.5%). It is not shipped: it would fit the renderer, not a real camera (QA D1). Refit on real footage (M2-03).
- **Darts nearly along the view ray.** When the flight hides the point, the blob is not elongated and gets the low-confidence nearest-to-foot pixel. This is about 1.5% of proposals, and about 30% of them are wrong. When a strongly tilted dart near the camera side leans toward the camera, its tail can end nearer the foot point than its tip, and the foot rule then picks the tail.
- **Shadows under noise (realistic + shadow).** On the coloured rings and dark segments the shadow test is weakest. Leftover shadow speckles become a second candidate (no proposal, 4.0–4.8% pooled) or attach to the dart.
- **Two darts in one frame.** Over 3,600 two-dart frames, 83–84% are declined ("More than one new dart"). In 14% the two darts are merged into one group, or one is too small to count, and a single proposal names one of them. In 1.3–2.8% the proposal matches neither. In play, M1-08 should avoid this by updating the base after each dart.
- **near-frontal (not gated): about 50%.** The pose falls back to an assumed HFOV (M1-04: direction p95 52.6°), so the foot rule picks the wrong end about half the time.

### Not covered by these numbers

- Real footage: the colours, shadows, noise and JPEG here are the renderer's. Shadow, threshold and grouping constants (`vision_segment.py`) were tuned on synthetic seed 1 and must be refit on Thursday's footage (M2-02/M2-03).
- Hands, arms, people and pulled darts in frame. The harness's false-proposal trials are an empty board with an exposure drift. A large change ("too large" or "large change") gives no proposal, but this is not measured against C4.
- Darts already in the board: every trial starts from an empty base. Overlapping darts are M1-08's job.
- Speed: Vision.ingest averages 32 ms per frame (p95 about 90 ms) on this container's CPU. The stable-frame segmentation path takes 60–120 ms on frames with many fragments.

### Recommended next steps (PM decisions; not done in M1-05b)

1. **Calibration refinement.** The realistic profile's 2 px click noise now costs about 3–4 points (see the ablation). Snapping the four clicks to the double-ring edge, or fitting the whole ring, is the cheapest next gain.
2. **Ceiling mounts in the harness.** `docs/DECISIONS.md` #2 puts the trial phone on a ceiling mount about 52 cm above the bull and 1.5 ft from the wall (about 41°). The harness has no "ceiling-0.5ft/1.5ft/2ft" mounts yet, so none of these numbers are for the actual trial geometry. The `top` mount (450 mm up, 500 mm out) is the closest.
3. Refit `TIP_BIAS_MM` and the `vision_segment.py` thresholds on Thursday's footage (M2-02/M2-03). Do not use the synthetic −0.6 mm.

## M1-03 to M1-05 (history)

These sections describe M1-05 as committed (9af1ad3): seed 1, the older harness (random streams keyed by mount position) and `TIP_BIAS_MM = 0.2`. Evidence: `qa-artifacts/M1-03-detection-baseline*.json`, `qa-artifacts/M1-04-pose.json`, `qa-artifacts/M1-05-detection.json`.

### Result in one paragraph

The foot-point tip rule (M1-05) helps: when the dart is segmented as one blob, it beats the old "nearer the centre" rule by 5.5–23.5 points. **The M1-05 gate is not met.** The shipped segmentation is the first bottleneck: `vision.py` thresholds a *grayscale* difference at 35, then requires exactly one contour. Any dart part whose gray level is close to the board behind it drops out: a barrel over the red treble, a black shaft on a black segment, a red flight on a red ring, or the thin point after the 3×3 opening. The dart splits into fragments, and 72–81% of darts get "Ambiguous change" and no proposal.

Segmentation is not the only bottleneck. Even with the optimistic diagnostic segmentation below, ideal-profile accuracy is 90.5–94.5% against the 99% gate, limited by near-wire darts and about 1 mm of tip error at the 1.7 px/mm warp (0.59 mm per warp pixel). Meeting the 99% gate likely also needs finer tip localisation (sub-pixel, or at the original camera resolution). That is a PM input.

### Exact-score accuracy, shipped pipeline (`tools/eval_detection.py`)

| Mount | ideal centre (old) | ideal foot (new) | realistic centre | realistic foot | ideal foot + shadow |
|---|---|---|---|---|---|
| top | 16.0% | 18.5% | 15.0% | 17.0% | 10.5% |
| bottom | 14.0% | 15.0% | 13.5% | 15.5% | 2.0% |
| left | 13.0% | 16.5% | 10.5% | 12.5% | 3.5% |
| right | 15.0% | 17.0% | 15.5% | 17.0% | 2.0% |
| steep-topleft | 13.0% | 13.5% | 15.0% | 15.5% | 15.0% |
| near-frontal (not gated) | 13.0% | 26.0% | 9.5% | 17.5% | 8.5% |

M1-05 gate (≥ 99% ideal, ≥ 95% realistic and +10 points over centre, tip median ≤ 2 mm and p95 ≤ 5 mm): **failed on all five gated mounts**. Only the tip median (≤ 2 mm) passes, and that median covers only the 19–28% of darts that got a proposal (a selection-biased statistic).

### Diagnostic: tip rule with segmentation taken out of the way (`tools/diag_segmentation.py`)

This diagnostic uses a per-channel colour difference and treats every changed pixel as one dart. That is valid only because each trial has exactly one dart, so it is an optimistic upper bound for the rule, **not** a production design and not a gate result.

| Mount | ideal centre | ideal foot | tip med / p95 (mm) | realistic centre | realistic foot |
|---|---|---|---|---|---|
| top | 68.5% | 92.0% | 0.8 / 1.6 | 67.0% | 90.0% |
| bottom | 80.0% | 93.0% | 1.0 / 1.6 | 78.0% | 91.0% |
| left | 76.0% | 94.5% | 0.8 / 1.6 | 73.5% | 93.0% |
| right | 73.5% | 92.0% | 0.9 / 1.9 | 72.5% | 89.5% |
| steep-topleft | 85.0% | 90.5% | 1.0 / 1.8 | 84.0% | 90.0% |

What limits it even here: darts more than 1.5 mm from a wire score 96.9–100% (ideal). Near-wire darts (about 20% of throws) score 56–73%, where sub-millimetre tip error flips the segment.

### Pose (M1-04)

Exact clicks recover the foot point exactly on all six mounts. With σ = 2 px click noise (50 seeds), direction error p95 is 2.6–3.7° on the five off-axis mounts (gate ≤ 10°). Near-frontal cannot solve the focal length and falls back to the assumed HFOV: p95 52.6°, reported only.

### Shadows

A hard shadow from the default light (`--shadow`) is badly harmful, as the plan's risk table predicted. On the side and bottom mounts the on-plane shadow becomes the blob end nearer the foot point (ideal + shadow: 2–3.5% shipped, 11–57% diagnostic). Diffuse lighting on the trial day matters.

### Recommended next step (at M1-05; since done as M1-05b)

Add a segmentation ticket ahead of M1-08. Use a colour-aware difference and group fragments along one axis into a single dart candidate, with an explicit "two darts" ambiguity check. Then re-run the M1-05 gate. The thresholds must be refit on real footage (M2-02/M2-03).

### QA follow-ups (after M1-05)

- `TIP_BIAS_MM` is now 0.0. M1-05 shipped 0.2, fit on the same seed-1 darts it was scored on; QA found 0.0 gives identical exact scores and slightly lower tip error. The tables above were produced with 0.2.
- The harness now keys its random streams by mount *name* (it used the mount's position in `MOUNTS`). Same seed, different darts: the tables above came from the old keying (commit 9af1ad3) and are not reproduced trial-for-trial by later commits.
