# M1-03 to M1-05b: synthetic detection results

**All numbers below come from synthetic rendered scenes (`sim/`). They measure the vision code against a model of a board and darts. They are not evidence of real-board accuracy; the Thursday trial is the real gate.**

## M1-05b: robust dart segmentation (current)

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
