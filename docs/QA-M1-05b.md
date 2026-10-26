# QA report: M1-05b, "M1-05 QA fixes" and "browser suites write to test-output"

Independent QA, 2026-10-26. I worked in worktree `/home/user/qa-m1b` (detached at `ae32924`) and reviewed the diff `15b8f47..ae32924`. That range covers `589e8d3` (M1-05 QA fixes), `27bffa3` (browser output directory), the 4 commits that only touch `DECISIONS.md`, and `ae32924` (M1-05b).
Nothing was committed. The worktree is clean apart from this file, `.venv/` and the gitignored `test-output/`.

Environment: Python 3.13, numpy 2.5.4, OpenCV 4.14.0, 4 CPUs. All accuracy figures are synthetic. They are not evidence of real-board accuracy.

## Verdict

| Item | Verdict | One line |
|---|---|---|
| Held-out numbers reproduce | **PASS** | 8 cells rerun: every per-trial record matches `M1-05b-detection.json` exactly, including the false-proposal and two-dart blocks. |
| No ground-truth leakage / honest tuning | **PASS** | The detector reads only the frame, the base and the foot point. The constants are round numbers. The held-out gap is about 1 point. |
| "Click noise is the main error source" ablation | **PASS** | Reproduced one cell exactly: steep-topleft s2 goes from 85.0% to 93.0%. |
| `tests/test_qa.py` dart change | **PASS** (justified) | Under M1-05b the old left dart is scored correctly by **both** rules. The new dart is a real case where the centre rule fails, and the foot-rule assertions are unchanged. |
| D1 / D2 / D4 / D7 fixes | **PASS** | Verified in code and docs. New tests cover D4 and D7. |
| D3 browser output dir | **PASS** | `qa-artifacts/` is unchanged after a full browser run. Override and `--record` paths resolve correctly. |
| Python suite | **PASS** | Ran 100, OK (47 s). |
| Browser suite | **PASS** | 14 passed, 1 failed (`qa_presentation.cjs`, the known stale "Maya" expectation). |
| Server end-to-end | **PASS** | calibrate → verify → camera dart S19 (truth S19) → commit 301→282 → undo → 301 → align → manual + undo. Server stderr was empty. |
| Performance | **PASS-WITH-NOTES** | Ingest mean is 31–34 ms per frame (p95 86–100) as claimed. The segmentation worst case is higher than stated, and grouping time grows superlinearly with the number of fragments (D-B). |
| Code review `vision_segment.py` / `vision.py` | **PASS-WITH-NOTES** | Clear, well documented code. One real correctness bug (D-A) and one robustness gap (D-C). |

**Safe to push to main (gate acknowledged as not met)? Yes.**
- The work is correct in what it measures and honestly reported, and it does not regress anything.
- The evidence reproduces trial for trial.
- D-A is a small fix and should go in before or with the push. It does not change any measured harness result.
- D-B and D-C should become follow-ups before M1-08 or real footage (M2-02).

## Evidence

### Reproduction
Command: `tools/run_detection_gate.py --empty-trials 100 --pair-trials 50`, run into the scratchpad and compared with `scratchpad/m1b/cmp.py`.

| Cell | Exact (mine = artifact) | No-proposal | False proposals | Two darts declined | Trials identical |
|---|---|---|---|---|---|
| realistic s2 steep-topleft | 85.0% | 0.5% | 0/100 | 44/50 | yes |
| realistic s3 steep-topleft | 90.0% | 0.5% | 0/100 | 46/50 | yes |
| realistic s2 left | 94.5% | 1.5% | 0/100 | 42/50 | yes |
| realistic s3 left | 94.5% | 2.5% | 0/100 | 39/50 | yes |
| realistic+shadow s2 top | 84.0% | 5.5% | 0/100 | 37/50 | yes |
| realistic+shadow s2 right | 85.5% | 3.0% | 0/100 | 44/50 | yes |
| ideal s2 top | 94.5% | 1.0% | 0/100 | 38/50 | yes |
| ideal s2 right | 98.0% | 1.0% | 0/100 | 44/50 | yes |

- **s2+3 means.** Steep-topleft realistic gives 87.5% and left realistic 94.5%. Both equal the doc table.
- **Headline ranges recomputed from the artifact.** All of these match the doc:
  - ideal 95.2–97.8%
  - realistic 87.5–94.5%
  - realistic+shadow 83.7–86.5%
  - no-proposal (ideal/realistic) 0.25–2.0%
  - false proposals 0 of 7,200
  - two-dart frames declined 82.9–84.3%
  - pooled realistic: seed 1 93.0%, seed 2 91.7%, seed 3 92.5%
- **Ablation** (`scratchpad/m1b/ablate.py`, realistic with `click_noise=0`, steep-topleft seed 2): exact 93.0%, no-proposal 0.0%, tip median 1.182 mm. This equals the artifact exactly; the same cell scores 85.0% with click noise.
- The artifact's `git_commit` field names `693cf3c`, the pre-rewrite parent, as the doc says. My exact reproduction at `ae32924` shows that the committed code is the code that produced it.

### Leakage and tuning
- `vision.py` and `vision_segment.py` do not import `sim`, and they never see a seed, a mount name or `Dart`. `segment()` takes the warped frame, the base, scale, centre, radius and the foot point (`vision.py:277-279`).
- The foot point comes from the pose solved from H (M1-04). The harness passes only encoded frames and calibration clicks (`tools/eval_detection.py:94-140`).
- The thresholds are round values: 30, 5×, 0.5, 60, 0.12, 0.25/0.8, 10%, 5/70 mm, 10°, 25°, 40 mm².
- The seed-1 vs held-out gap is plausible:
  - realistic pooled: 93.0% on seed 1 vs 91.7% and 92.5% held out
  - ideal pooled: 96.6% vs 96.9% and 96.1%
- The renderer-bias finding (−0.6 mm) was correctly **not** shipped.

### Test change (`tests/test_qa.py:178-181`)
I ran the old and new left darts at HEAD:
- **Old dart:** foot gives S19 at 0.99 mm and centre gives S19 at 1.14 mm. The centre rule is no longer wrong there, because the whole dart is now segmented.
- **New dart:** foot gives S16 at 0.45 mm. Centre gives S17, 136 mm off: it picks the flight end.

The test keeps its intent (show a dart the centre rule gets wrong) and keeps the same foot-rule assertions, including the error below 2 mm. This is not test weakening.

### Previous defects
- **D1:** `TIP_BIAS_MM = 0.0`, with its history explained (`vision.py:21-25`).
- **D2:** the M1-05 history section now says segmentation is not the only bottleneck, and calls the tip median selection-biased.
- **D4:** `invalidate()` clears `pose` and `solved_pose` (`vision.py:121-123`). That covers `reset_camera()` and the failed-`align()` path, because `align()` calls invalidate first (`vision.py:190`). `mount_side` is kept, documented and tested (`tests/test_pose.py:113`).
- **D7:** streams are keyed by the crc32 of the mount name (`tools/eval_detection.py:141`), camera settings are recorded, and `diag_segmentation` creates the out directory. Tests were added.
- **D3:**
  - `git status` is clean after `scripts/test.sh browser`, whose output went to `test-output/browser-20261026-193055/` (56 files).
  - No `tests/*.cjs` file writes to a hard-coded `qa-artifacts` path any more. All of them go through `tests/qa_output.cjs`.
  - `DART_QA_ARTIFACTS=qa-artifacts` (relative or absolute) resolves to `<root>/qa-artifacts`, and `--record` sets the absolute path (`scripts/test.sh:38-39`).
  - Nit: running a suite directly without `scripts/test.sh` writes to `test-output/browser/` (also gitignored), which is fine.

### Server end-to-end
Script: `scratchpad/m1b/server_e2e.py`. It runs the real `server.main()` with `--camera-hfov 75` and synthetic JPEG frames from the left mount.
1. Calibrate returns 200 with a 'solved' pose, foot [-450, 0] and HFOV 75.
2. Verify returns 200.
3. The camera game produces proposal S19, rule foot, confidence high (truth S19, error about 1 mm).
4. `/api/throw` with the proposal gives [282, 301]; undo gives [301, 301].
5. `/api/align` returns 200 with a solved pose.
6. A manual T20 gives 241; undo gives 301.
7. Server stderr was empty.

### Performance
Measured in a single process, unloaded (`scratchpad/m1b/perf.py`, top and steep-topleft, 60 darts, seed 1):

| | realistic | realistic+shadow |
|---|---|---|
| `Vision.ingest` mean / p95 | 31.2–31.9 / 86 ms | 32.0–34.1 / 91–100 ms |
| `segment()` median / p95 / max | 63 / 84 / 92 ms | 67 / 103 / 171 ms |

The doc's "32 ms, p95 about 90, 60–120 ms segmentation" holds, except that the shadow maximum is 171 ms. With 4 parallel workers, ingest is about 48 ms per frame.

## Defects (ranked)

**D-A — Medium (correctness). `FragmentGrouper.group` caches "apart" pairs by `id()`, and ids of freed merged blobs are reused.** `vision_segment.py:340-354`.
- When a merged Blob replaces `groups[i]`, the previous merged Blob is freed. CPython often hands its address to the next `merged()` result. A stale `(id, id)` entry in `apart` then makes the loop skip a pair that was never compared, so a merge is missed. The outcome depends on the memory allocator.
- Stress test (`scratchpad/m1b/idreuse2.py`, 400 random fragment sets):
  - 2,035 stale-id hits
  - 68 of 400 sets (17%) group differently from a version keyed by a stable serial number
  - usually more groups remain; in one case the result was 2 groups instead of 1, which would turn a dart into "multiple"
- No effect in the harness: a 60-dart realistic+shadow cell gave 0 stale hits, and the reproduced trials are identical.
- Fix: key `apart` by a per-blob serial number (or `id` plus keeping the objects alive), or drop the cache.

**D-B — Medium (performance / robustness). Grouping cost grows superlinearly with fragment count.** `vision_segment.py:337-358`, `:303-314`.
- After every merge the loop restarts the O(n²) scan. Each `belongs()` call builds a full outline-to-outline distance matrix.

  | Small specks (uniform board) | `segment()` time |
  |---|---|
  | 20 | 135 ms |
  | 50 | 170 ms |
  | 100 | 340 ms |
  | 200 | 968 ms |

- Real footage (sensor noise, flicker, partial shadows) can produce many fragments. `ingest` runs under the server's global lock (M1-06 is not done yet), so one slow frame stalls `/api/state`.
- Fix: cap the fragment count (more than N fragments means "too noisy, no proposal"), and/or keep the merge scan going after a merge instead of restarting it.

**D-C — Medium (false proposals). Grouping can chain unrelated small changes into one "dart".** `vision_segment.py:280-301` (wedge up to `AXIS_GAP_MM = 70` along the away-from-foot direction), `:392-404`.
- 30 synthetic boards, each with 20 isolated red specks. Each speck is below `MIN_DART_MM2`, and the specks are randomly placed with no dart. **9 of 30 returned `kind='dart'`**, with groups up to 170 mm long and only 123–198 px filled.
- Nothing checks that a candidate is plausible for a dart: length, fill ratio, or that a large solid core exists.
- The harness's "0 false proposals in 7,200" covers only an empty board plus exposure drift and sensor noise. That scenario never creates fragments, so the claim is true but narrow. The doc does say hands, people and pulled darts are not measured.
- Fix: require at least one fragment of real dart size in the group, or bound the group's length and fill. Add speckle and debris scenes to the false-proposal trials.

**D-D — Low. The doc understates the segmentation worst case.** `docs/M1-DETECTION-RESULTS.md` ("Not covered", Speed). It says 60–120 ms; I measured a maximum of 171 ms with shadow, and about 1 s with many fragments (see D-B).

**D-E — Low (code nits).**
- `vision.py:280`: `self.segmentation` keeps the last result, including a 700×700 float32 `difference` image and all groups. It is never cleared by `invalidate()` or `reset_base()`, so stale diagnostics persist. Nothing reads it today.
- `vision.py:29`: the change radius grew from 172 to 200 mm, which also changes the denominator of `LARGE_CHANGE_FRACTION` (`vision_segment.py:51`) and widens sensitivity into the number ring. Worth a one-line note.
- `vision.py:59`: the `end - 1.5` tolerance is in warp px, while the neighbouring constants are in mm. A short comment would help.
- `vision_segment.py:177-193`: `inside_shadow` sums all three channels of the 2-px ring. That is fine, but the docstring says "darkened like a shadow" and only the brightness ratio is tested, not chromaticity.
- `vision.py:300-337`: `locate_tip` still runs PCA on the outline (now dense via `CHAIN_APPROX_NONE`, which addresses old D5), while `refine_tip` uses all pixels. That is consistent and documented.

Not defects:
- The near-frontal mount stays at about 50%; it is not gated and is explained.
- Pair trials use the session after the single-dart trials, so they share the click RNG. That is deterministic and reproduced.

## Reproduce
```
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
scripts/test.sh py ; scripts/test.sh browser ; git status --short   # stays clean
.venv/bin/python tools/run_detection_gate.py --profiles realistic --seeds 2,3 --mounts steep-topleft,left \
    --empty-trials 100 --pair-trials 50 --out /tmp/x.json   # then compare trials with qa-artifacts/M1-05b-detection.json
```
QA scripts: `/tmp/claude-0/-home-user/39130e07-3815-5ada-9f6d-04313fc052e0/scratchpad/m1b/` (`cmp.py`, `ablate.py`, `perf.py`, `idreuse.py`, `idreuse2.py`, `server_e2e.py`).
