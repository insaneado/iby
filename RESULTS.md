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

---

## Audit round 2 — the first fix was incomplete

Re-checking the parts of the scorer the first audit did not touch.

### The boundary fix reached BF1 but not WindowDiff

`window_diff()` computed its own boundaries by calling `boundary_idx()` on the
rendered timeline — the very label-change definition round 1 replaced. So
WindowDiff was still blind to **312 of 2,142** boundaries after the "fix".

A partial fix is worse than none, because it looks finished. `window_diff()`
now takes explicit boundary arrays.

### Discretisation was inconsistent by one bin

`to_timeline` fills `[floor(start), ceil(end))`; `segment_boundaries` used
`round()` for both edges. A segment spanning 10.4–20.6 s rendered to bins 10–20
but reported boundaries at 10 and 21. Always inside the ≥2 s tolerances, so it
never changed a headline — but two functions describing the same segmentation
disagreed. Now both use `floor`/`ceil`.

### No overlapping predictions

Checked: the segmenter emits zero overlapping segments across all 63 sessions,
so `to_timeline`'s last-writer-wins rule never fires on real output.

### Final corrected scoreboard

| approach | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI | idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gold vs gold *(harness check)* | 2009 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 5.0% |
| baseline: gap > 3 s, app labels | 4150 | **0.226** | 0.314 | 0.494 | 0.656 | 0.063 | 0.013 | 41.5% |
| baseline: every app switch | 2580 | 0.021 | 0.252 | 0.471 | 0.468 | 0.135 | 0.011 | 9.2% |
| **v1** | **1974** | 0.208 | **0.450** | **0.631** | **0.348** | **0.507** | **0.435** | **5.7%** |

Held out (tuned on 32 sessions, tested on 31 unseen):

| split | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI |
|---|---:|---:|---:|---:|---:|---:|---:|
| dev | 1016 | 0.196 | 0.450 | 0.625 | 0.351 | 0.531 | 0.445 |
| **test** | 958 | 0.220 | **0.450** | 0.638 | 0.346 | 0.514 | 0.436 |

### What honest scoring cost, and one place v1 now loses

Across both audit rounds, v1's BF1@5s went 0.463 → 0.448 → 0.450 while the gap
baseline went 0.221 → 0.242 → 0.314. **The baselines gained far more from the
corrections than v1 did**, because counting every segment edge rewards emitting
many segments. The lead on BF1@5s narrowed from 2.1x to **1.43x**.

And at the tightest tolerance the over-segmenting baseline now **beats** v1:
BF1@2s 0.226 vs 0.208. That is a real result, not a rounding artefact — with
4,150 segments against 2,009 true ones, scattering boundaries catches more of
them within 2 s by brute force. It pays for that everywhere else: WindowDiff
0.656 vs 0.348, V-measure 0.063 vs 0.507, and it claims 41.5% of wall time is
idle when the truth is 5.0%.

Reported rather than buried, because "my method wins on every metric" is
usually a sign the metrics are not adversarial enough.

**v1's standing lead:** BF1@5s 1.43x, BF1@10s 1.28x, WindowDiff 1.34x better,
V-measure 3.8x, ARI 33x, and the only approach whose segment count (1,974 vs
2,009) and idle fraction (5.7% vs 5.0%) land near gold.

---

## Day 4 — signature labelling, and a failed transfer to dataset B

### The labeller (dataset A, measured)

Case-ID prefix labels dataset A with 100% purity and is useless on dataset B,
whose ids are employee records. So labels must come from what the operator did.

Signatures scored against the true family on gold segments:

| signature | clusters | V | ARI |
|---|---:|---:|---:|
| dominant app | 8 | 0.121 | 0.011 |
| portal system | 6 | 0.404 | 0.206 |
| route | 6 | 0.572 | 0.359 |
| open document | 19 | 0.150 | 0.035 |
| system + route + document | 159 | 0.697 | 0.447 |
| **system + route** | 22 | **0.797** | 0.731 |
| + drop `dashboard`, fill gaps | **15** | **0.854** | **0.805** |

The final 15 clusters are in **1:1 correspondence with the 15 true process
families**, purity 71.8–100%. The structure is not a coincidence: the portal is
one SPA deployed three times, so 3 systems x 5 routes *is* the taxonomy.

Three refinements that each paid:

- **Read the system from the window title, not `tab_title`** — the obvious field
  is populated on 72% of browser events, the window title on 96.5%.
- **Ignore `dashboard`** — a landing page, not a unit of work. Worth 0.022 V.
- **Recover the route from L2 when there is no L3.** 6 of 63 dataset A sessions
  and 1 of 15 dataset B sessions have zero URL events (extension never
  connected). Each portal screen has a distinctly worded note box whose
  placeholder reaches L2 via accessibility; cross-checked against L3 element ids
  the mapping is one-to-one with zero overlap. Eliminates all 204 unknown labels.

On the 57 dataset A sessions with complete telemetry the labeller reaches
**V=0.937, ARI=0.929**, and the L2 fallback costs nothing there (0.937 either
way). The method is strong when the data is complete; degradation is a
telemetry-availability problem, not a method problem.

End to end on predicted segments: signature labels give V=0.460 against the
case-prefix labeller's 0.507. Prefix wins on dataset A because it is a shortcut
that exists only there. **0.460 is the number expected to transfer.**

### The dataset B run fails its held-out check

`out/segments.jsonl` (341 segments, 12 labels, 99.2% coverage) is **not fit to
submit**. The check that caught it uses the 629 `btn-*-ok` confirm presses,
deliberately excluded from segmentation, so it is genuine held-out evidence.

If a segment were one unit of work, its confirm press should sit near the end.

| evidence | value |
|---|---|
| confirm clicks inside some segment | 629 / 629 (100%) |
| segments containing exactly 4 confirms | 90 (others hold 8, 10, 12) |
| position histogram across 0→1 | flat: 34, 82, 71, 85, 67, 64, 74, 55, 71, 26 |
| single-confirm segments: median position | 0.35 |
| single-confirm segments past two-thirds | 9% |

Flat is the damning one. The segments are not aligned to work units at all —
341 segments against 629 completions, where dataset A produced 1,974 against
2,009. The transfer failed, and it failed silently on every internal statistic
(coverage, label count, segment durations all looked plausible).

**Why.** Dataset A's anchors come from list-view dominance (2,830 of 3,428);
dataset B's are 759 of 818 from clicked rows, carrying employee ids that persist
across consecutive work units. Consecutive units therefore share an anchor value
and get merged.

**Next.** Use the confirm press itself as a boundary signal for dataset B — it
is the observable completion of a unit of work, and there is no principled
reason to withhold real signal from the method. That costs the held-out check,
so validation moves to the completion memos (`請求書照合完了。INV-2026-7345`),
which stay excluded, plus duration-distribution comparison against dataset A and
human review of the labels.

Recording the trade explicitly because it is easy to launder: a check is only
evidence while the thing it checks cannot see it.

---

## v3 — terminator-driven segmentation (Day 4/5)

### The signal

Every portal screen ends a unit of work with a button. Scored against dataset A's
gold segments, those 1,751 presses land **1,751/1,751 inside a gold segment,
exactly one per segment** (`{1: 1751}`, never two), at median relative position
**0.89**. It is not an inferred boundary, it is an observed statement that a
unit ended.

It was nearly missed: the first search used dataset B's naming (`btn-*-ok`) and
returned **zero** on dataset A, which names the same controls semantically
(`btn-la-approve`, `btn-rt-query`). Matching on structure — an HTML `button`
tag — finds them in both.

### Result on dataset A

| approach | segs | BF1@2s | BF1@5s | BF1@10s | WD | V | ARI | idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| best baseline (gap > 3 s) | 4150 | 0.226 | 0.314 | 0.494 | 0.656 | 0.063 | 0.013 | 41.5% |
| v1 anchor-driven | 1974 | 0.208 | 0.450 | 0.631 | 0.348 | 0.471 | 0.412 | 5.7% |
| **v3 terminator-driven** | **2016** | **0.286** | **0.722** | **0.765** | **0.294** | **0.518** | **0.490** | **5.7%** |
| *gold* | *2009* | *1.000* | *1.000* | *1.000* | *0.000* | *1.000* | *1.000* | *5.0%* |

**BF1@5s 2.3x the best baseline and 1.6x v1.** Segment count within 0.3% of gold
(2,016 vs 2,009); idle within 0.7 points. Held out: dev 0.723, test 0.722 —
the split is invisible.

`max_unit_s` was set to 200 s rather than the 90 s that maximises BF1@5s
(0.733). 90 s scores 0.011 higher but claims 11.5% of wall time is idle against
a true 5.0%; 200 s gives 5.7%. Calibration was preferred over a hundredth of
boundary F1, because Step 2 measures how long processes take and a segmenter
that discards 6% of working time answers that question wrongly.

### Dataset B, regenerated

| | v1 | **v3** |
|---|---:|---:|
| segments | 341 | **672** |
| labels | 12 | 14 |
| coverage | 99.2% | 99.4% |
| segments per session | 9–40 | 26–56 |

672 against 629 observed terminators — the 43 extra come from the fallback for
work that ends without a press.

### The held-out check, honestly re-earned

The confirm press now *defines* the segment end, so it cannot also be evidence:
scoring it returns 1.00 by construction. Validation moved to the completion memo
the operator types into Notepad (`請求書照合完了。INV-2026-7345`), which no part
of the pipeline reads.

| | v1 | v3 |
|---|---|---|
| memos inside a segment | — | 149/149 (100%) |
| median relative position | 0.35 *(confirm clicks)* | **0.78** |
| fraction in last third | 9% | **78%** |
| histogram 0→1 | flat | 2, 2, 2, 1, 1, 0, 39, 39, 50, 13 |

A check is only evidence while the thing it checks cannot see it. Swapping to a
signal the pipeline still cannot see is what keeps this a test rather than a
restatement.

---

## Hardcoding audit — `src/discover.py`

Three Japanese system names, five placeholder strings, `dashboard` and the
prefix `btn-` were typed in by hand. Each had a measured justification, but a
process-mining tool meets a different portal at every client, and hand-written
vocabulary is a transcript of one dataset rather than a pipeline.

`discover.py` re-derives each from the events alone:

| constant | how it is discovered | agrees with hand-written? |
|---|---|---|
| terminators | clicks on an HTML `button` | A 1752 vs 1751, B 629 vs 629 |
| systems | leading component of browser window titles, filtered to those that host a terminator | **exact on both** |
| screens | element-id prefix co-occurring with a URL route | 5/5 on both |
| placeholders | placeholder text co-occurring with a screen id | B **5/5**; A only **2/5** |
| non-routes | routes that never host a terminator | `dashboard`, exact on both |

The placeholder row is the one that matters. The hand-written table came from
dataset B and matches dataset A's actual note-box wording on only 2 of 5
entries — **the two portals word their screens differently**, and the constant
had been silently wrong on half its entries. Discovery gets 5/5 on each dataset
because it reads each one's own vocabulary instead of assuming they share one.

Substituting discovery for the constants moves dataset A to V=0.840 / ARI=0.817
against 0.854 / 0.805 — the same within noise, now learned rather than typed.

**None of this is machine learning, deliberately.** These are exact structural
relations recoverable by counting: a `button` tag is a button; an element id
co-occurring with a route defines that screen. Fitting a model would add
variance, opacity and inference cost while removing the audit trail that makes
the output defensible to a client.

---

## Overfitting audit

Prompted by the fair objection that the pipeline is tuned to dataset A. Three
tests, and one of them found a real methodological fault.

### 1. Parameter leakage — real, and it was costing me

Every parameter had been swept over all 63 sessions, with a dev/test split
reported *afterwards*. The test set had therefore already informed the choice.
That is leakage dressed as validation.

Redone strictly — the sweep sees dev only, test is scored once:

| protocol | chosen | test BF1@5s | test V |
|---|---|---:|---:|
| honest (tune on dev alone) | max_unit_s=60 | **0.745** | 0.522 |
| leaky (tune on all 63) | max_unit_s=200 | 0.722 | 0.516 |

**Cost of the leak: −0.023.** The honest protocol scores *higher*, because the
value shipped was not the BF1-maximising one. The leak was real and should not
have happened, but it was not inflating the reported result.

### 2. Leave-one-machine-out — the honest generalisation number

A random session split shares operators across both sides. Holding out whole
machines asks the harder question: does this survive an operator it has never
seen?

| held-out machine | sessions | BF1@5s | V | ARI |
|---|---:|---:|---:|---:|
| CHAITANYA0BCF | 12 | 0.820 | 0.662 | 0.527 |
| MSI | 8 | 0.804 | 0.623 | 0.600 |
| Marcos | 10 | 0.780 | 0.649 | 0.505 |
| yuvraj | 5 | 0.768 | 0.676 | 0.531 |
| LAPTOP-0IM1OHQH | 7 | 0.764 | 0.691 | 0.580 |
| SIDDHIGUPTAB00B | 12 | 0.717 | 0.517 | 0.248 |
| **LAPTOP-R36BQBTE** | 7 | **0.444** | **0.331** | 0.185 |

**mean BF1@5s 0.728, sd 0.120.** Six of seven machines sit in 0.72–0.82. The
seventh is not a tuning artefact:

| machine | sessions | sessions with no URL | L3 events |
|---|---:|---:|---:|
| LAPTOP-R36BQBTE | 7 | **6** | **0** |
| every other machine | 5–12 | 0 | 565–2,022 |

The browser extension never connected on that machine, so the route signal does
not exist there and the labeller falls back to the L2 placeholder path. The
variance is a **telemetry-availability** property, not an overfitting one — and
it is the single most quantified deployment risk in this project: *expect
BF1@5s ≈ 0.73 ± 0.12 on an unseen operator, falling to ≈ 0.44 wherever L3
capture is missing.*

### 3. The parameter choice, re-examined

| max_unit_s | BF1@5s | WD | V | idle (gold 5.0%) |
|---:|---:|---:|---:|---:|
| 60 | **0.741** | 0.300 | 0.529 | **19.9%** |
| 90 | 0.733 | 0.297 | 0.527 | 11.5% |
| 120 | 0.726 | 0.296 | 0.519 | 8.5% |
| **200** | 0.722 | **0.294** | 0.518 | **5.7%** |

60 s wins on boundary F1 and claims a fifth of all working time is idle. 200 s
gives up 0.019 BF1 and gets time accounting right. Step 2 exists to say how long
each process takes, so a segmenter that discards 15% of working time answers the
actual question wrongly while scoring better on the proxy. 200 s stands.

### What this does not prove

Machine-to-machine is a weaker test than dataset A to dataset B, which changes
department, process vocabulary and portal wording at once. Three transfers have
already failed or needed repair — the case-ID prefix, the anchor rule, the
button naming. **0.73 ± 0.12 is an optimistic ceiling for dataset B, not a
prediction.**

### Incidental fix

`boundary_prf` enumerated the full gold x pred cross product (~4M iterations per
tolerance) when only pairs within tolerance can match. Replaced with a binary
search over the sorted boundary arrays: `evaluate()` went from seconds to
0.25 s, with byte-identical results and gold-vs-gold still 1.000. Caching the
Parquet loads cut a pipeline run from 5.9 s to 2.3 s. Neither changes any
number; both are why this audit was affordable to run at all.
