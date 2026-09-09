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

---

## v1 — case anchors + boundary snapping (Day 3)

`src/caseid.py` recovers the active case; `src/segment.py` turns anchors into
segments by nearest-anchor assignment, snaps each boundary to the nearest
structural transition, and labels by case prefix.

| approach | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI | idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| best baseline (gap > 3 s) | 4150 | 0.199 | 0.221 | 0.308 | 0.807 | 0.018 | 0.005 | 41.7% |
| best baseline (app switch) | 2580 | 0.024 | 0.199 | 0.379 | 0.638 | 0.135 | 0.011 | 9.5% |
| **v1** | **1974** | 0.170 | **0.463** | **0.609** | **0.382** | **0.507** | **0.435** | **5.7%** |
| *gold* | *2009* | *1.000* | *1.000* | *1.000* | *0.000* | *1.000* | *1.000* | *5.0%* |

Both targets cleared at once: **BF1@5s 2.1x** the best baseline, **V-measure
3.8x**. Segment count lands within 2% of gold (1,974 vs 2,009) and predicted
idle time within 0.7 points (5.7% vs 5.0%), neither of which was fitted.

### Held-out verification

Parameters were tuned on 32 sessions and verified on the 31 held out (seed 0):

| config | split | BF1@5s | BF1@10s | WD | V | ARI |
|---|---|---:|---:|---:|---:|---:|
| max_dist=90 | dev | 0.461 | 0.596 | 0.387 | 0.531 | 0.445 |
| max_dist=90 | **test** | **0.465** | **0.623** | **0.375** | **0.513** | **0.435** |

Test matches or slightly exceeds dev, and the optimum is flat from max_dist
60–120 s. This is a plateau, not a tuned point — so the numbers should survive
contact with dataset B.

### Ablations — what is actually earning its place

| change | BF1@5s | WD | V |
|---|---:|---:|---:|
| v1 | 0.463 | 0.382 | 0.507 |
| without boundary snapping | 0.461 | 0.387 | 0.504 |
| with min-length filter (8 s) | 0.455 | 0.390 | 0.506 |
| max_dist = 25 s | 0.420 | 0.455 | 0.484 |

**`max_dist` is the only parameter that matters.** Snapping contributes about
0.002–0.005 — real but marginal, and much smaller than expected given that
structural transitions looked like the obvious boundary signal. The min-length
filter actively *hurts*, so it was disabled rather than kept for tidiness: the
short runs it removed were mostly landing on real boundaries.

### The honest weakness (superseded — see the audit below)

**BF1@2s is 0.170** — barely above the baselines. v1 finds the right *stretches*
of work but cannot place a boundary to the second. That is expected and
structural: screen text is captured only every ~7.7 s (p50), so an anchor
physically cannot localise a change more finely, and for 27% of gt process
starts there is no event at all within ±2 s. Pushing 2-second precision would
mean predicting boundaries in the gaps between observations. Not worth the
budget — the client cares which work happened and for how long, not
sub-5-second edges.

---

## Audit (Day 4, before extending to dataset B)

A deliberate re-check of the work so far, before building anything on top of it.
Three suspicions; two were harmless, one was a real defect in the metric.

### 1. Ground-truth metadata on the inference path — real, but harmless

`segment_dataset` was receiving session windows from `gt_manifest.json`. Dataset
B has no manifest, so dataset A was being scored with information the real run
would not have. The two sources genuinely disagree — mean 10 s at the start,
91 s at the end, max 962 s.

Measured impact: **none** (BF1@5s 0.463 vs 0.464). The anchors do the work; the
window only pads the edges with idle. Switched to `event_bounds()` anyway —
"it happened not to matter" is not a reason to keep ground truth on the
inference path.

### 2. Dependence on my own end-time inference — modest and real

257 of 2,009 gold segments (12.8%) have an end time I inferred rather than read.
Excluding them:

| gold variant | gold segs | BF1@5s | WD | V |
|---|---:|---:|---:|---:|
| all, including inferred ends | 2009 | 0.463 | 0.382 | 0.507 |
| real `end_ts` only | 1752 | 0.442 | 0.407 | 0.497 |

So roughly 0.02 BF1 and 0.01 V of the headline came from my own assumption. The
strict figure is itself a pessimistic bound — excluding those segments turns
real work into idle, so predictions there are counted as false positives. The
true value sits between the two rows; both are reported rather than the
flattering one.

### 3. A defect in the metric itself — found and fixed

Boundaries were derived from **label changes** on the rendered timeline. When
two consecutive executions share a label — two invoice approvals back to back —
the boundary between them produces no label change and disappeared.

Measured on the gold set: the metric saw **1,830 of 1,946 real internal
boundaries — 94%**. It was discarding 6% of the problem, and precisely the 6%
this task exists to solve ("the same process appears many times a day").

Fixed by deriving boundaries from segment **edges** (`segment_boundaries`).
Back-to-back same-label executions now dedup to one shared boundary, while a
segment followed by idle then another segment correctly yields two. The
gold-vs-gold sanity check still returns 1.000 everywhere.

### Corrected scoreboard

All figures below use the corrected boundary definition and event-derived
session windows. Earlier tables in this file used the superseded definition and
are left in place rather than rewritten.

| approach | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI | idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gold vs gold *(harness check)* | 2009 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 5.0% |
| baseline: gap > 3 s, app labels | 4150 | 0.203 | 0.242 | 0.378 | 0.808 | 0.063 | 0.013 | 41.5% |
| baseline: every app switch | 2580 | 0.033 | 0.237 | 0.382 | 0.638 | 0.135 | 0.011 | 9.2% |
| **v1** | **1974** | **0.182** | **0.448** | **0.618** | **0.381** | **0.507** | **0.435** | **5.7%** |

Held out (tuned on 32 sessions, tested on 31 unseen):

| split | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI |
|---|---:|---:|---:|---:|---:|---:|---:|
| dev | 1016 | 0.172 | 0.447 | 0.610 | 0.387 | 0.531 | 0.445 |
| **test** | 958 | 0.193 | **0.450** | 0.626 | 0.375 | 0.514 | 0.436 |

The correction narrowed the margin — the baselines gained more from it than v1
did, because counting edge boundaries rewards over-segmentation slightly. v1
still leads by **1.85x on BF1@5s** and **3.8x on V-measure**, and remains the
only approach whose segment count and idle fraction land near gold.

**The weakness is unchanged and structural:** BF1@2s = 0.182. Screen text is
captured only every ~7.7 s, so no anchor can localise a boundary more finely.
Improving it would mean inventing boundaries between observations.
