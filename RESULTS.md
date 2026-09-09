# Evaluation results

Every pipeline version scored against dataset A's ground truth by
`src/evaluate.py`. Appended to, never rewritten, so the progression is visible.

Metrics: **BF1@t** boundary F1 at t seconds tolerance (higher better);
**WD** WindowDiff (lower better, 0 perfect); **V** V-measure and **ARI**
Adjusted Rand for label consistency (higher better).

Gold: 63 sessions, 2,009 segments, 15 process families, 5.0% idle time.

---

## v0 — baselines (Day 1)

| approach | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI |
|---|---:|---:|---:|---:|---:|---:|---:|
| **gold vs gold** (harness check) | 2009 | **1.000** | **1.000** | **1.000** | **0.000** | **1.000** | **1.000** |
| one segment per session | 63 | 0.000 | 0.000 | 0.000 | 0.491 | 0.000 | 0.000 |
| gap > 2 s | 8290 | 0.192 | 0.201 | 0.204 | 0.899 | 0.013 | 0.005 |
| gap > 3 s | 4150 | 0.199 | 0.221 | 0.308 | 0.807 | 0.018 | 0.005 |
| gap > 5 s | 1613 | 0.137 | 0.171 | 0.261 | 0.628 | 0.034 | 0.005 |
| gap > 10 s | 1327 | 0.137 | 0.163 | 0.261 | 0.610 | 0.033 | 0.004 |
| gap > 3 s, labelled by dominant app | 4150 | 0.199 | 0.221 | 0.307 | 0.808 | 0.063 | 0.013 |
| every app switch | 2580 | 0.024 | 0.199 | 0.379 | 0.638 | 0.135 | 0.011 |

Run on the complete dataset (162,768 dataset A events). An earlier run on a
partial extraction differed only in the third decimal.

### What this establishes

**The harness is correct.** Scoring ground truth against itself returns 1.000 on
every metric and WindowDiff 0.000. Without this check the rest of the table
would be unfalsifiable.

**Idle-gap segmentation does not work on this data — measured, not assumed.**
Best gap variant reaches BF1@2s = 0.199 and V-measure = 0.018. The cause was
already visible in the gold set: the median gap between consecutive gold
segments is 0.0 s, so half of all true boundaries have no pause to detect. The
gap threshold only trades false positives for false negatives — at 2 s it emits
8,255 segments for 2,009 true ones (precision 0.107); at 10 s it misses 84% of
boundaries. There is no setting where it works.

**Over-segmentation is worse than not segmenting at all.** One segment per
session scores WindowDiff 0.491; gap > 2 s scores 0.899. A predictor that
shatters the timeline is further from the truth than one that makes no claim,
which is worth remembering when tuning for boundary recall.

**App switching carries real signal but is far too noisy alone.** Best BF1@10s
(0.378) and best label agreement (V = 0.133) of the baselines — but BF1@2s
collapses to 0.024, meaning it rarely places a boundary at the right *second*.
Workers switch applications constantly *within* one unit of work, so this
over-segments for a different reason than the gap rule does.

**Label agreement is the harder half.** Every baseline sits below V = 0.14. Both
naive labelling schemes — one label for everything, or the dominant application —
carry almost no information about which business process is running. This is
where the case-ID reconstruction has to earn its place.

Target for v1: beat BF1@5s = 0.220 and V = 0.133 simultaneously.
