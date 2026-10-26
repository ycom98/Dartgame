# M1-03 to M1-05: synthetic detection results

**All numbers below come from synthetic rendered scenes (`sim/`). They measure the vision code against a model of a board and darts. They are not evidence of real-board accuracy; the Thursday trial is the real gate.**

Seed 1, 200 single-dart trials per mount, 1920×1080, HFOV 70°. Every dart stays in the board (r ≤ 170 mm). Evidence: `qa-artifacts/M1-03-detection-baseline*.json`, `qa-artifacts/M1-04-pose.json`, `qa-artifacts/M1-05-detection.json`.

## Result in one paragraph

The foot-point tip rule (M1-05) works: when the dart is segmented as one blob, it beats the old "nearer the centre" rule by 5.5–23.5 points and gives tip errors of about 1 mm. **But the M1-05 gate is not met**, because the shipped segmentation, not the tip rule, is the bottleneck. `vision.py` thresholds a *grayscale* difference at 35, then requires exactly one contour. Any dart part whose gray level is close to the board behind it drops out: a barrel over the red treble, a black shaft on a black segment, a red flight on a red ring, or the thin point after the 3×3 opening. The dart splits into fragments, and 72–81% of darts get "Ambiguous change" and no proposal.

## Exact-score accuracy, shipped pipeline (`tools/eval_detection.py`)

| Mount | ideal centre (old) | ideal foot (new) | realistic centre | realistic foot | ideal foot + shadow |
|---|---|---|---|---|---|
| top | 16.0% | 18.5% | 15.0% | 17.0% | 10.5% |
| bottom | 14.0% | 15.0% | 13.5% | 15.5% | 2.0% |
| left | 13.0% | 16.5% | 10.5% | 12.5% | 3.5% |
| right | 15.0% | 17.0% | 15.5% | 17.0% | 2.0% |
| steep-topleft | 13.0% | 13.5% | 15.0% | 15.5% | 15.0% |
| near-frontal (not gated) | 13.0% | 26.0% | 9.5% | 17.5% | 8.5% |

M1-05 gate (≥ 99% ideal, ≥ 95% realistic and +10 points over centre, tip median ≤ 2 mm and p95 ≤ 5 mm): **failed on all five gated mounts**. Only the tip median (≤ 2 mm) passes.

## Diagnostic: tip rule with segmentation taken out of the way (`tools/diag_segmentation.py`)

This diagnostic uses a per-channel colour difference and treats every changed pixel as one dart. That is valid only because each trial has exactly one dart, so it is an optimistic upper bound for the rule, **not** a production design and not a gate result.

| Mount | ideal centre | ideal foot | tip med / p95 (mm) | realistic centre | realistic foot |
|---|---|---|---|---|---|
| top | 68.5% | 92.0% | 0.8 / 1.6 | 67.0% | 90.0% |
| bottom | 80.0% | 93.0% | 1.0 / 1.6 | 78.0% | 91.0% |
| left | 76.0% | 94.5% | 0.8 / 1.6 | 73.5% | 93.0% |
| right | 73.5% | 92.0% | 0.9 / 1.9 | 72.5% | 89.5% |
| steep-topleft | 85.0% | 90.5% | 1.0 / 1.8 | 84.0% | 90.0% |

What limits it even here: darts more than 1.5 mm from a wire score 96.9–100% (ideal). Near-wire darts (about 20% of throws) score 56–73%, where sub-millimetre tip error flips the segment.

## Pose (M1-04)

Exact clicks recover the foot point exactly on all six mounts. With σ = 2 px click noise (50 seeds), direction error p95 is 2.6–3.7° on the five off-axis mounts (gate ≤ 10°). Near-frontal cannot solve the focal length and falls back to the assumed HFOV: p95 52.6°, reported only.

## Shadows

A hard shadow from the default light (`--shadow`) is badly harmful, as the plan's risk table predicted. On the side and bottom mounts the on-plane shadow becomes the blob end nearer the foot point (ideal + shadow: 2–3.5% shipped, 11–57% diagnostic). Diffuse lighting on the trial day matters.

## Recommended next step (needs a PM decision; not done in M1-05)

Add a segmentation ticket ahead of M1-08. Use a colour-aware difference and group fragments along one axis into a single dart candidate, with an explicit "two darts" ambiguity check. Then re-run the M1-05 gate. `TIP_BIAS_MM` (0.2 mm from the harness) and the thresholds must be refit on real footage (M2-02/M2-03).
