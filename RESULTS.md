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

---

## Evaluator audit — is the scorer flattering the method?

A fair objection: standard metric *definitions* (WindowDiff is Pevzner & Hearst;
V-measure and ARI are sklearn) do not protect against a scoring harness built
alongside the method it scores. I chose the tolerances, the binning, the IDLE
handling and the gold construction. Four tests that do not depend on my
judgement.

### 1. Chance calibration — what does random score?

A segmenter with the **same segment count and label vocabulary** but random
placement, averaged over 5 seeds:

| | mine | random | separation |
|---|---:|---:|---:|
| BF1@2s | 0.286 | 0.131 | +0.155 |
| BF1@5s | **0.723** | 0.259 | **+0.464** |
| WindowDiff | 0.293 | 0.523 | 0.230 better |
| V-measure | 0.518 | 0.017 | +0.501 |
| ARI | 0.490 | 0.002 | +0.488 |

The metric discriminates. Two things worth noting: BF1@5s has a **floor of
~0.26**, not 0, so raw values overstate performance — and the best baseline
(gap > 3 s, 0.314) is barely above that floor, which makes it a much weaker
comparator than it looked.

### 2. Label permutation

Keep my boundaries, shuffle the labels across segments:

| | V-measure | ARI |
|---|---:|---:|
| mine | 0.518 | 0.490 |
| labels shuffled | **0.029** | 0.011 |

The label score is not leaking from the segmentation.

### 3. Dominant overlap — parameter-free

No tolerance, no binning: for each ground-truth execution, what fraction does
its best-matching predicted segment cover?

| | mine | random |
|---|---:|---:|
| best match covers >=80% | **75.8%** | 16.9% |
| covers >=60% | 89.7% | — |
| covers >=50% | 97.1% | — |
| median coverage | **88.2%** | 38.2% |

Independent agreement with BF1, reached by a completely different route.

### 4. Duration distribution

Kolmogorov-Smirnov against the gold durations — nothing in the pipeline
optimises this:

| | n | median | KS vs gold |
|---|---:|---:|---:|
| gold | 2,009 | 32 s | — |
| mine | 2,015 | 33 s | **0.042** |
| random | 2,015 | 16 s | 0.570 |

### What the audit found that BF1 was under-stating

**Only 35.6% of gold executions overlap exactly one predicted segment.** 1,216
of 2,009 overlap two — typically one holding ~88% of the execution and a sliver
in the neighbour.

BF1@5s = 0.723 already implied this (28% of boundaries are more than 5 s out),
but *"most work units are split across two segments, 88/12"* is the more honest
phrasing and sounds considerably more serious.

Consequence: harmless for Step 2, where durations aggregate correctly (KS
0.042) and the segment count is within 0.3%. Disqualifying for any use needing
exact per-execution boundaries.

**Verdict: the evaluator is not biased in the method's favour, and the audit
surfaced a real weakness the headline metric was under-emphasising.** Both
results are worth more than the score itself.

---

## v4 — bracket each unit between its opening and closing click

The evaluator audit found the remaining defect: only 35.6% of gold executions
overlapped exactly one predicted segment, most being split ~88/12 across two.
v3 fixed the END of a unit with the confirm press and inferred the start by
walking back a fixed window. Ends were right; starts were approximate.

**Both edges are observable.** Selecting a record from the worklist is a click on
a table cell. On dataset A those 1,780 clicks land inside a gold execution
**99.9%** of the time, at median relative position **0.13**, 98% in the first
third, exactly one in 1,722 of 1,750 executions. The confirm press sits at 0.89.

    row click  ──────── work ────────▶  confirm press
      p50 = 0.13                          p50 = 0.89

### Results

| | best baseline | v3 | **v4** | gold |
|---|---:|---:|---:|---:|
| BF1@2s | 0.226 | 0.286 | **0.673** | 1.000 |
| BF1@5s | 0.314 | 0.723 | **0.752** | 1.000 |
| BF1@10s | 0.494 | 0.765 | **0.812** | 1.000 |
| WindowDiff | 0.656 | 0.293 | **0.195** | 0.000 |
| V-measure | 0.135 | 0.518 | **0.684** | 1.000 |
| ARI | 0.013 | 0.490 | **0.667** | 1.000 |
| segments | 4,150 | 2,015 | **2,010** | 2,009 |
| idle | 41.5% | 5.7% | 6.6% | 5.0% |

**BF1@2s more than doubled** and WindowDiff improved by a third. Segment count is
now within 0.05% of ground truth.

### The defect, re-measured

| | v3 | **v4** | random |
|---|---:|---:|---:|
| gold executions mapping to exactly one segment | 35.6% | **76.8%** | ~38% |
| best match covers >=80% | 75.8% | **83.0%** | 16.9% |
| median coverage | 88.2% | **97.5%** | 38.2% |

### Validation

| check | result |
|---|---|
| held out (32 dev / 31 unseen) | dev BF1@5s 0.744, **test 0.760** |
| leave-one-machine-out | **0.739 ± 0.127** (v3: 0.728 ± 0.120) |
| chance calibration | random 0.258 → separation **+0.494** |
| dataset B, case-linked memo check | **24/26 (92%)** land in the segment for their own case (v3: 23/26) |

### Two bugs found on the way, both by invariants rather than inspection

**Taking the bracket literally dropped 30% of working time.** The row click is at
0.13 and the confirm at 0.89, so ~13% of a unit precedes the click and ~11%
follows the press. Using the bracket edges directly gave **36.7% idle against a
true 5.0%**, which would have understated every process duration by a third.
Each pair is now expanded to the midpoint of the gap on either side.

**The expansion loop mutated in place while iterating**, reading neighbours that
had already moved, and produced 14 overlapping segments on dataset B. Caught by
the Step 2 invariants. Computing all expansions from the original edges before
applying them fixed the overlaps *and* the calibration — idle fell from 11.9% to
6.6% and BF1@2s rose from 0.503 to 0.673. A correctness bug was also an accuracy
bug.

### Effect on Step 2

The conclusion strengthens rather than shifts: the payroll-items screen pattern
is **38.7%** of observed work (was 35.7%), still across all three systems, still
the top-ranked candidate. `out/segments.jsonl` is now 664 segments and all Step 2
invariants hold.

---

## Label validation on dataset B (no ground truth)

The portal prints a breadcrumb — `ダッシュボード / 契約管理` — in
`context.extracted_text`. That is an L1 screen capture, and `label.py` reads
only the URL route (L3) and the window title (L2), so the breadcrumb is a signal
the labeller cannot see. It is therefore usable as evidence.

### The measurement that looked bad

Comparing each segment's label to the modal breadcrumb inside it:

| | value |
|---|---:|
| agreement | 41.5% |
| V-measure | 0.254 |
| chance (labels shuffled) | 0.064 |
| dataset A, against real ground truth | 0.684 |

Better than chance, far worse than dataset A. Two hypotheses: the labels are
wrong on dataset B, or the comparison is.

### It was the comparison

Per **event**, where no aggregation is involved, the labeller state and the
breadcrumb agree almost perfectly:

| | V-measure | system agreement |
|---|---:|---:|
| per event | **0.770** | **100.0%** |
| per segment | 0.254 | 48% |

And restricting the comparison to breadcrumbs captured close in time to the
segment's end:

| breadcrumb within | pairs | system agreement | V-measure |
|---|---:|---:|---:|
| **2 s of segment end** | 31 | **96.8%** | **0.948** |
| 5 s | 46 | 95.7% | 0.931 |
| 10 s | 96 | 62.5% | 0.537 |
| anywhere in the segment | 191 | 62.8% | 0.480 |

A breadcrumb captured ten seconds before a segment ends describes a screen the
operator has since left. Screen text is captured every ~7.7 s, so most
comparisons were against a stale reference.

**A retraction.** An intermediate step of this analysis reported that the window
title and the breadcrumb "disagree at source 36% of the time", and concluded the
breadcrumb was not a clean reference. That was wrong: per event they agree
**100%** on the system. The 36% was my own aggregation error measuring itself.

### What it changed

The investigation exposed a real defect. `label.py` took the **modal** state
across a segment, mixing in whatever the operator passed through on the way. A
segment ends at its terminal click, so the state at that instant is where the
work was completed. Switching to the terminal state, scored against dataset A's
real ground truth:

| | modal state | **terminal state** |
|---|---:|---:|
| V-measure | 0.684 | **0.719** |
| ARI | 0.667 | **0.708** |

So the best available evidence for dataset B labels is **V = 0.948 against a
contemporaneous reference**, on 31 segments where such a reference exists. Small
sample, and the effect is large and monotonic across the tolerance sweep.


---

## Matching correction — greedy was understating every score

`boundary_prf` paired predicted boundaries to gold ones greedily, nearest-first.
Greedy is not optimal bipartite matching: it can spend a predicted boundary on a
gold boundary that had another candidate, stranding one that had only that.

Replaced with exact rectangular assignment (Hungarian). Everything was rescored
the same way — a change that only rescores the winner is not a fix:

| approach | BF1@2s greedy | optimal | BF1@5s greedy | optimal |
|---|---:|---:|---:|---:|
| gold vs gold *(sanity)* | 1.000 | **1.000** | 1.000 | **1.000** |
| baseline gap > 3 s | 0.226 | 0.240 | 0.314 | 0.316 |
| baseline app switch | 0.021 | 0.023 | 0.252 | 0.307 |
| v3 | 0.286 | 0.314 | 0.723 | 0.726 |
| **v4 (shipped)** | 0.673 | **0.700** | 0.752 | **0.756** |

The baselines gained too — app-switch by +0.055 at 5 s, the largest single
gain — so the error was not in anyone's favour, merely wrong. The ranking is
unchanged and the sanity check still returns exactly 1.000.

### Everything re-verified under optimal matching

| check | result |
|---|---|
| full dataset A | BF1@2s **0.700**, BF1@5s **0.756**, BF1@10s **0.818**, WD 0.195, V 0.719, ARI 0.708 |
| held out | dev 0.748, **test 0.765** |
| leave-one-machine-out | **0.745 ± 0.119** (min 0.471, max 0.863) |
| chance control | 0.267 → discrimination **+0.489** |

## Two components tested for the first time

**`gold.py`'s end-time inference is correct.** 257 of 2,009 gold executions have
a null `end_ts` and the end is inferred as the next execution's start. Its
*impact* was measured before; its *accuracy* never was. Applying the same rule
to the 1,752 executions that do have a real end:

| | |
|---|---|
| median error | **0.0 s** |
| within ±2 s | **97.1%** |
| within ±5 s | 97.4% |
| undershoots | **0.0%** |
| worst case | +121 s |

So the inferred ends are not propping up the gold set.

**The Step 3 tool is idempotent.** Running it twice over the same portal: the
first pass handles 288 rows, the second handles **0** — the portal reports them
already done. No double-processing, no error.

---

## v4 re-audit — the audits had been measuring v3

`metric_audit.py` and `overfit_audit.py` both imported `segment_v3` while `v4`
was what shipped. Every chance-calibration and cross-operator figure above them
in this file therefore describes a **superseded segmenter**. Repointed and
re-run. The figures below supersede the corresponding rows in the two audit
sections above; those are left in place because this file is a log.

### Chance calibration, against the shipped pipeline

| | v4 (shipped) | random control | separation |
|---|---:|---:|---:|
| BF1@2s | **0.700** | 0.134 | +0.566 |
| BF1@5s | **0.756** | 0.267 | **+0.489** |
| WindowDiff | **0.195** | 0.523 | 0.328 better |
| V-measure | **0.719** | 0.017 | +0.702 |
| ARI | **0.708** | 0.002 | **+0.707** |

Labels shuffled while boundaries are kept: V collapses to **0.030**, so the
label score carries **+0.689 V** of its own signal.

### Strict protocol, re-run

| protocol | chosen | test BF1@5s | test V |
|---|---|---:|---:|
| honest (tune on dev alone) | max_unit_s=90 | **0.765** | 0.708 |
| leaky (tune on all 63) | max_unit_s=200 | 0.765 | 0.708 |

**Cost of the leak is now exactly 0.000.** Under v4 the score is flat across
`max_unit_s` from 60 to 600, so the parameter the leak could have influenced no
longer influences anything. The leak was real and is now provably inert.

### Leave-one-machine-out, re-run

| held-out machine | n | BF1@5s | V | ARI |
|---|---:|---:|---:|---:|
| MSI | 8 | 0.863 | 0.832 | 0.836 |
| LAPTOP-0IM1OHQH | 7 | 0.819 | 0.865 | 0.841 |
| CHAITANYA0BCF | 12 | 0.802 | 0.823 | 0.792 |
| Marcos | 10 | 0.769 | 0.850 | 0.835 |
| yuvraj | 5 | 0.765 | 0.855 | 0.817 |
| SIDDHIGUPTAB00B | 12 | 0.725 | 0.680 | 0.501 |
| **LAPTOP-R36BQBTE** | 7 | **0.471** | 0.482 | 0.361 |

**mean 0.745, sd 0.119.** The outlier rose from 0.444 to 0.471 but remains the
machine with zero L3 events across all seven of its sessions.

### One correction to a correction

The earlier audit section reports one-to-one mapping at 76.8%; `metric_audit`
reported 23.2%. **Both are the same pipeline, measured two ways.**

| overlap definition | exactly one |
|---|---:|
| any overlap, including 1 ms | 23.2% |
| **material overlap, ≥10% of the execution** | **76.8%** |
| best match covers ≥80% | **83.0%** |
| median coverage | **97.5%** |

v4 expands each segment to the midpoint of the gap to its neighbour, so
neighbours abut and nearly every execution registers a spurious second overlap
of a few milliseconds. Material overlap is the figure that means anything, and
it is unchanged. `metric_audit.py` now prints both, labelled.

### Duration distribution under v4

| | n | median | KS vs gold |
|---|---:|---:|---:|
| gold | 2,009 | 32 s | — |
| v4 | 2,010 | 36 s | **0.103** |
| random | 2,010 | 16 s | 0.569 |

KS rose from v3's 0.042 to 0.103 — v4's segments run slightly long, a direct
consequence of the gap expansion that fixed the calibration. Still six times
closer to gold than the random control.

---

## Step 3 robustness — the tool did not fail loudly where it mattered most

The report states the tool has "no designed behaviour [for exceptions] beyond
failing loudly". Tested by breaking one part of a definition at a time:

| break | before | after |
|---|---|---|
| confirm button renamed | loud, **93 s** | loud, **1.2 s** |
| note field renamed | loud, **93 s** | loud, **1.2 s** |
| table renamed | Playwright `TimeoutError` — **would abort all 12 screens** | isolated `DefinitionDrift`, 11.4 s |
| **status vocabulary changed** | **silent no-op — reported success, did nothing** | loud, **1.2 s** |

The last row is the one that matters. The portal uses at least five words for
"pending" across its screens (未処理, 処理待ち, 申請中, 照合中, 未確認). A word the
definition never saw produced *"0 rows, 0 failed"* — indistinguishable from a
clean run with nothing to do. For the likeliest production failure there is, the
claim of failing loudly was false.

Three changes:

- **Preflight.** Every selector the loop depends on is resolved before any row
  is touched. A renamed control used to fail per row on Playwright's 30 s
  timeout — 93 s on 3 rows, roughly two hours on a 240-row screen.
- **Drift is distinguished from done.** Rows exist but none are pending, *and*
  some carry an unrecognised status → `DefinitionDrift`. Every row already in
  the done state → a legitimate idempotent re-run, still a no-op.
- **Isolation.** `run.py` catches `DefinitionDrift` per screen, so one drifted
  screen stops itself and the other eleven continue. The table timeout is
  converted into `DefinitionDrift` because Playwright's own exception would have
  escaped that handler and aborted the run — which the first version of this fix
  missed.

Regression holds exactly: 984 rows, 915 automated, 69 to review, 0 failed. The
idempotent second pass still processes 0 rows and raises no drift, so the new
check does not false-positive on a legitimate re-run.

## Automated invariants — and whether each can fail

`tests/test_invariants.py`: 10 tests. With the datasets, **10 passed**. In a
copy with no data, no index and no config, **8 passed, 2 skipped** — the two
that need the datasets. Identical under pytest 9.1.1.

A test is evidence only once it has been seen to fail. `tests/mutation_check.py`
breaks what each test guards, requires the test to fail, restores, and requires
it to pass again:

| mutant | test that must catch it | result |
|---|---|---|
| boundary matcher reverted to the pre-fix greedy, taken from git | optimal matching | killed |
| boundaries taken from label changes | same-label neighbours | killed |
| F1 computed as PR/(P+R) | ground truth scores as perfect | killed |
| `build_index` missing-data guard removed | first-run message | killed |
| an extra field on one line | exact fields | killed |
| a timestamp written `+00:00` instead of `Z` | ISO 8601 UTC | killed |
| one session's segments missing | all 15 sessions covered | killed |
| `session_id` written as a path | ids are the directory names | killed |
| a typo in every `session_id` | ids are the directory names | killed |
| two segments overlapping by 1 s | no empty or overlapping segments | killed |
| a zero-length segment | no empty or overlapping segments | killed |
| a unique label per segment | small consistent vocabulary | killed |
| one label for everything | small consistent vocabulary | killed |
| a test that raises instead of asserting | the runner | killed |

**14 / 14 killed.** Building this exposed defects in the tests themselves:

| case (tolerance 2 bins) | pre-fix greedy F1 | optimal F1 |
|---|---:|---:|
| gold `[10,12]`, pred `[11,14]` — the matching test as first written | **1.00** | 1.00 |
| gold `[10,11]`, pred `[11,13]` | 0.50 | 1.00 |
| gold `[10,12]`, pred `[8,11]` | 0.50 | 1.00 |

The matching test as first written could not tell the bug from the fix. The
count-only session test **passes** the path mutant — fifteen distinct strings,
none of them a directory name — which is why the directory-name test exists.
And the runner originally caught only `AssertionError`, so a test that crashed
would have hidden every test after it.

Re-checked alongside: a fresh clone regenerates `segments.jsonl` byte-for-byte
(sha256 `1b1397404bc22480…`), and `explore/verify_report.py` reconciles 21 / 21
figures in the report against a fresh run.

## The report, reconciled by a checker that reads it

`explore/verify_report.py` now re-derives each figure and compares it with the
figure *as written* in `REPORT.md` or `SUMMARY_JA.md`. It exits non-zero on any
mismatch.

| run | figures | match | stale |
|---|---:|---:|---:|
| previous checker — claimed values typed into the script | 21 | 21 | 0 |
| rewritten checker, documents unchanged | 119 | 60 | **59** |
| rewritten checker, documents corrected | 119 | 119 | 0 |
| the same, with the README's figures added | 143 | 143 | 0 |

The previous checker could not fail on a stale document, because it never
opened one. Of the 59, the largest groups were the greedy-era Step 1 figures
(summary, ablation, R8), the 3-screen Step 3 figures (§3, §5, R2, limitations)
and nearly every figure in the Japanese summary.

### Ablation — `explore/ablation.py`, shipped configuration, dataset A

| configuration | BF1@2s | BF1@5s | V | ARI | segments |
|---|---:|---:|---:|---:|---:|
| shipped | 0.700 | 0.756 | 0.719 | 0.708 | 2,010 |
| without case anchors entirely | 0.723 | 0.750 | 0.694 | 0.585 | 1,750 |
| ends only, no opening click | 0.316 | 0.732 | 0.562 | 0.540 | 2,012 |
| labels from case prefix | 0.700 | 0.756 | 0.471 | 0.385 | 2,010 |
| one label for everything | 0.700 | 0.756 | 0.011 | −0.001 | 2,010 |

Segments that exist only because of the anchor-driven fallback: **260 of
2,010** — the units no confirm press brackets.

Sensitivity, one parameter at a time, BF1@2s:

| parameter | range | BF1@2s |
|---|---|---|
| `expand_gap_s` | 20 – 300 | 0.700 throughout |
| `max_unit_s` | 100 – 600 | 0.700 throughout |
| `min_unit_s` | 1 – 10 | 0.700 – 0.703 |
| case-anchor `min_repeat` | 2 / 3 / 4 | 0.695 / **0.700** / 0.714 |

The shipped threshold is 3, chosen for anchor precision (93.5%) before this
score existed. It is not moved to 4.

### Random control for coverage — `explore/metric_audit.py`, 5 seeds

Best-matching segment covers ≥80% of an execution: **17.8%** of the time;
median coverage **38.1%**. The report had quoted 16.9% and 38.2% with no
committed code behind either.

### Determinism under hash randomisation

| what | `PYTHONHASHSEED` | result |
|---|---|---|
| the deliverable, `run_dataset_b.py` | 0, 1, 2 | byte-identical to the committed file (sha256 `1b1397404bc22480…`) |
| gap > 3 s baseline labelled by app, before the fix | 0, 1, 2, 3 | V = 0.0638, 0.0637, 0.0639, 0.0638 |
| the same, ties broken by first occurrence | 0, 1, 2, 3 | V = 0.0633 under every seed |

## Can a whole department be held out?

`explore/overfit_audit.py` described a leave-one-domain-out test and never ran
one. It now prints why it cannot:

| departments present in a session | sessions |
|---|---:|
| all three | 63 |
| one | 0 |

Each gold family's department is read off the labeller's system prefix on that
family's own segments, not typed in. With every session mixing all three, a
department cannot be held out by session; the cross-department evidence is
dataset B's breadcrumb agreement (V = 0.948) and the held-out memo check.
`verify_report.py` now checks the report's statement of this — 144 / 144
figures match.

## Dataset B evidence, rebuilt as committed code

`explore/label_vs_breadcrumb.py` on the shipped deliverable. Every row carries a
shuffled-label chance baseline (20 shuffles).

| breadcrumb actually captured within | pairs | system agreement | V | chance V |
|---|---:|---:|---:|---:|
| 2 s of segment end | 31 | 96.8% | **0.948** | 0.158 |
| 5 s | 46 | 95.7% | 0.931 | 0.230 |
| 10 s | 96 | 62.5% | 0.537 | 0.222 |
| the whole segment | 191 | 62.8% | 0.480 | 0.147 |
| breadcrumb most often in force, per segment | 439 | — | 0.255 | 0.064 |

The sweep matches the uncommitted analysis recorded earlier in this file, which
ran against the modal labeller; the terminal-state labeller left it unchanged.

### The memo check against chance — `src/run_dataset_b.py`

| | inside a segment | median position | in last third |
|---|---:|---:|---:|
| 149 completion memos, v4 | 100% | 0.47 | 0.15 |
| 5,000 random instants, v4 | 97.9% | 0.50 | 0.33 |
| 149 completion memos, v3 (recorded earlier) | 100% | 0.78 | 0.78 |

Under v4 segments cover 97.9% of session time, and the check no longer
discriminates.

### Approval routing — `tool/regulations.py`

| comparator | before | after |
|---|---|---|
| 以上 — or more | ≥ | ≥ |
| 超 — more than | ≥ | **>** |
| 未満 — under | < | < |
| 以下 — or less | < | **≤** |

Old and new agree on 120,027 comparisons across the three captured rule tables
(every ¥1,000 to ¥40M, and each threshold ±1): the captured regulations use only
以上 and 未満. Tests: 12, mutation check 16 / 16.

### Checker coverage

`verify_report.py` now also re-derives the dataset B evidence, the Step 2 tables
against a fresh regeneration, every ablation row and sensitivity claim, and the
case-ID findings: 193 / 193 figures match.

## Where the residual Step 1 error comes from — `explore/error_sources.py`

466 of 2,009 executions (23.2%) map to no single segment — the metric audit's
figure, reproduced by class:

| execution contains | executions | maps to one segment | share of misses |
|---|---:|---:|---:|
| a confirm press and a row click | 1,750 | 83.7% | 61.4% |
| neither | 258 | 30.2% | 38.6% |
| a confirm press, no row click | 1 | 100% | 0% |

The 258 units with neither click are spread across all 15 process families
(5–18% of each). 204 sit in sessions with no confirm press at all, and no browser
element is clicked inside any of them.

### Telemetry gaps

| dataset | sessions | with zero L3 events |
|---|---:|---|
| A | 63 | 7 — every session of LAPTOP-R36BQBTE |
| B | 15 | 1 — `ses_20260701-192455-NEELA9BAF`: 22 of 664 segments, 10.9 of 173 minutes |

### The row click through the accessibility layer

| | L2 `DataItem` click, A's 7 gap sessions | L3 `td` click, other machines |
|---|---:|---:|
| inside a gold execution | 99.0% (206/208) | 99.9% |
| median relative position | 0.15 | 0.13 |
| exactly one per execution | 95.1% (194/204) | 98.4% (1,722/1,750) |

B's gap session carries 107 such clicks, named by the row id. No L2 click in it
corresponds to the confirm press. Measured, not built.

### Step 3 model default and guard

The model runs only with `--llm-drafts` (it ran whenever a key existed). The
guard also refuses session ids and case and row ids. Tests: 14, mutation check
18 / 18. `verify_report.py`: 203 / 203 figures match.

## Accuracy experiment: the row click through the accessibility layer — a negative result

`explore/experiment_l2_opens.py`, measurement only. In sessions with zero L3
events, each L2 `DataItem` click opens a unit and the next one closes it; nothing
is tuned and nothing else in the pipeline changes. The bar, set before
measuring: better on both of the brief's criteria — boundaries and label
consistency — with no new tuned choice.

| dataset A | BF1@2s | BF1@5s | BF1@10s | V | ARI | maps to one |
|---|---:|---:|---:|---:|---:|---:|
| gap sessions, shipped fallback | 0.174 | 0.471 | 0.640 | 0.482 | 0.361 | 37.3% |
| gap sessions, L2 row click | 0.104 | **0.803** | 0.907 | 0.433 | 0.245 | 31.9% |
| all of A, shipped | 0.700 | 0.756 | — | 0.719 | 0.708 | 76.8% |
| all of A, with the L2 row click | 0.693 | **0.791** | — | 0.689 | 0.668 | 76.3% |

Boundary F1 at 5 s rises by 0.035 overall; label consistency, ARI, precision at
2 s and the one-segment mapping all fall. The boundary sits at the click, about
0.15 of a unit after the true start, so each segment overhangs the next unit —
which is also where the labeller reads its terminal state. On dataset B's gap
session it would turn 22 segments into 107 (664 → 749 overall): the row ids show
the same row clicked repeatedly, so a click is not one unit there.

Not shipped. It fails the bar, and passing it would take two more choices —
where before the click the boundary goes, and whether repeated clicks on one row
are one unit — each made after seeing these numbers.

## Three more attempts to raise accuracy — none clears its bar

### Repairs to the L2 experiment, each diagnosed before building — `explore/diagnose_l2.py`

| hypothesis | prediction | measured |
|---|---|---|
| read the label at the opening click | more correct than at the segment's end | 23.2% against 32.8% |
| merge consecutive clicks on the same row | fewer units in B's gap session | 107 → 107 |

Correctness is against ground truth, through a label-to-family map learned on
the other sessions' gold segments.

### A length-proportional gap split — `explore/diagnose_boundaries.py`

Boundary placement on adjacent bracketed executions with no idle between them:

| half | pairs | midpoint within 2 s | proportional within 2 s | midpoint within 5 s | proportional within 5 s |
|---|---:|---:|---:|---:|---:|
| dev | 799 | 80.2% | 71.7% | 83.5% | 85.1% |
| test | 750 | 82.3% | 76.4% | 85.9% | 86.4% |

Rejected. Of the 286 bracketed executions that map to no single segment, 285 are
overlapped by two segments: the residual error is placement inside the gap.

### The first app switch in the gap — `explore/diagnose_first_event.py`, `explore/experiment_split_app_switch.py`

The first event of a unit, dev half: an app switch in 492 of 799 pairs (62%),
within 0.5 s of the true start 97.5% of those times. As a placement rule, chosen
on dev, scored on test: within 2 s 85.1% against the midpoint's 82.1% (82.3% in
the table above: this script takes the true boundary as the second unit's start,
that one as the first unit's end, and the two differ by up to 1 s).

The pre-registered full evaluation:

| | BF1@2s | BF1@5s | BF1@10s | WindowDiff | V | ARI | idle | maps to one |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all of A, midpoint | 0.700 | 0.756 | 0.818 | 0.195 | 0.719 | 0.708 | 6.6% | 76.8% |
| all of A, first app switch | 0.733 | 0.773 | 0.814 | 0.172 | 0.698 | 0.668 | 8.8% | 78.5% |
| test half, midpoint | 0.701 | 0.765 | | | 0.708 | 0.688 | | |
| test half, first app switch | 0.722 | 0.770 | | | 0.678 | 0.635 | | |

Per machine, BF1@5s: five machines up (+0.012 to +0.048), LAPTOP-R36BQBTE
unchanged, MSI −0.029.

| bar, set before running | result |
|---|---|
| test: BF1@2s higher | pass |
| test: BF1@5s higher | pass |
| test: V no more than 0.005 lower | **fail** (−0.030) |
| all: WindowDiff not worse | pass |
| all: V no more than 0.005 lower | **fail** (−0.021) |
| all: maps-to-one not lower | pass |
| machines: no BF1@5s drop over 0.02 | **fail** (MSI −0.029) |

Not shipped. The default path stays the midpoint and regenerates the deliverable
byte-for-byte; the rule remains behind `split="first_app_switch"`. On dataset B
it would have moved an edge of 413 of the 664 segments.

## Claims nothing checked — Step 2 prose, the tool's own figures, a fresh clone

### A comparison stated in prose was false

The report said the top screen, payroll-items, carries the **second-lowest**
judgment load. The screen table averaged the per-system percentages, which puts
it third (resident-tax 27%, social-insurance 22%). Averaging percentages is also
the wrong aggregate: it weights fin's 8 social-insurance runs like hr's 120
payroll runs. Judgment is now the share of the screen's runs with a regulation
document open, the definition used per process:

| screen | runs | unweighted mean (was) | share of runs (now) |
|---|---:|---:|---:|
| payroll-items | 260 | 27.7% | 26.9% |
| resident-tax | 73 | 27.4% | 27.4% |
| social-insurance | 85 | 21.8% | 28.2% |
| leave-applications | 151 | 57.0% | 53.6% |
| onboarding | 95 | 84.5% | 85.3% |

payroll-items is lowest, but only just, and the report now says so. The
sentence is generated from the data in `make_step2_report.py` and checked by
`verify_report.py`.

### The shared-login evidence was overstated

"All three appear in every session ... at 97–100% consistency." One of the three
names appears in 13 of 15 sessions. All three appear on all four machines, each
in one system 100% of the time, so the conclusion stands; the evidence is now a
generated table, and the report quotes it.

### Figures in code that no check read

| where | claimed | measured |
|---|---|---|
| `tool/engine.py` docstring | shared screen 35.7%, 254 runs, 62.4 min | 38.3%, 260, 66.1 |
| `tool/engine.py` docstring | 24% of worklist rows are 調整 | 120 of 984 (12.2%); 26.3% of the 3 screens with 種別 |
| `tool/engine.py` docstring | screens with most 調整 rows are those where a regulation is opened | inventory: highest 調整 rate (40%), lowest document rate (3%) |
| `src/rank.py` | purities 61, 100, 71, 69, 88 … ; 79% weighted | 65, 94, 85, 56, 100 … ; 80.4% |
| `src/rank.py` | ops__payroll-items named by getsujitsu_teigaku_torihikisaki_ichiran | 2 segments open any document |

The docstring figures are removed in favour of the generated analysis; the
false causal claim is corrected in place. `verify_report.py` now checks that
every process name cites the document its segments consult (at least 5), and
the report's document table against the data.

### tool/README.md was not checked at all

It carries its own copy of the Step 3 table, the latency, the archetype counts
and "3 of 13 regulation documents". All matched; 23 checks now keep it so.

### A fresh clone failed the test suite

`fixture.json` is generated from dataset B and gitignored, and `tool/run.py`
imported the mock portal - which loads it - at module level. On a clean checkout
the README's one-command check printed **11 passed, 1 failed, 2 skipped**. The
import is now inside `main()`, and a missing fixture says which script builds
it. Same checkout now: 14 passed, 0 failed, 2 skipped.

### Japanese output crashed when piped on Windows

`python tool/regulations.py | …` died with UnicodeEncodeError on its fourth
line: redirected output uses the ANSI code page. The tests never saw it because
they set `PYTHONIOENCODING`. `common.py` now sets UTF-8 output once.

Two tests guard these (16 in all) and two mutants confirm each can fail.
`verify_report.py` now checks 247 figures, all matching (203 before this round).

## Step 2's third question, answered — different handling within one process

The brief asks whether the same process is handled in different ways. The report
answered with a limitation — "only 72 segments could be tied to a variant",
measured on an earlier revision's output and never re-run.
`explore/handling_variants.py` re-measures on the delivered segments.

Tied to the worklist row they processed, through a case ID seen inside the
segment: **578 of 664 (87.0%)**. Each row is classed by the handling mode its
screen's Step 3 definition routes it to — `review` (種別 = 調整; 新規締結, 解除)
or `deterministic` — which was fixed when the tool was built, before this
comparison existed.

| label | routine runs | flagged runs | median s | keystrokes | regulation open |
|---|---:|---:|---|---|---|
| hr__payroll-items | 93 | 20 | 11.0 → 11.5 | 4.3 → 5.3 | 12.9% → 25.0% |
| ops__payroll-items | 18 | 43 | 11.0 → 11.0 | 4.1 → 10.3 | 0.0% → 4.7% |
| fin__payroll-items | 50 | 19 | 17.0 → 16.0 | 11.7 → 11.8 | 72.0% → 63.2% |
| ops__leave-applications | 12 | 30 | 16.0 → 20.0 | 5.5 → 9.7 | 91.7% → 86.7% |

12 comparisons by 5,000-draw permutation test, Bonferroni bar p < 0.0042:
**none survives**. Smallest p = 0.082, the contract screen's flagged rows at
+4.0 s median.

A first version of the script counted any routed column with two or more keys as
a variant. That took in department columns and, on fin's payment screen, a
column holding invoice references: 21 comparisons, none surviving either. The
criterion was tightened to the definitions' handling mode — what the docstring
already said it meant — before any figure reached the report.

The report's section 8 limitation now says what the null result can and cannot
show: with 19–43 flagged runs per process, only a large difference was
detectable. 22 checks in `verify_report.py` tie the section, the limitation and
the Japanese summary to the script's output.

Adding the section exposed a defect in the checker itself. Its Step 2 table
check read the *first* row in the report beginning with each process name, and
the new table - placed above the ranking table - begins its rows with the same
four names: 4 of 269 checks went stale against a correct report. Each table is
now read within its own section.

## Step 3 routed approvals by a regulation its operators never open

Every flagged rule in the tool's definitions named the same regulation,
`gyomu_itaku_keihi_kitei`, and routed rows carrying an amount by its thresholds.
Step 2 records which document each screen's operators consult, and it is that
regulation on one screen of the three (`explore/handling_variants.py`, documents
open while flagged rows are handled):

| screen | flagged runs | that regulation open | what the operators consult |
|---|---:|---:|---|
| hr 経費精算・給与変更 | 20 | 5 | it — the label's dominant document |
| fin 請求書承認・経費精算 | 19 | 2 | the monthly supplier list, in 11 |
| ops 在庫管理 | 43 | 0 | a document of any kind in 2, an onboarding checklist |

The first draft of this entry said 1 for that last cell, from a scratch
computation on in-memory segments whose edges carry milliseconds. The committed
script reads the deliverable, whose edges are whole seconds, and counts 2. The
commit gate compares the counts cited here with the script's output, and
refused to commit until they agreed.

57 approvals on the fin and ops screens (40 and 17) were routed by a threshold
table nothing connects to them. They now go to a person; hr keeps its routing.
The contract screen named the same regulation too, with no effect: its rows
carry no amount. `verify_report.py` now checks every `rules_from` against the
dominant document of its screen's label (at least 5 segments, and the document
must carry thresholds).

| | before | after |
|---|---:|---:|
| routine, templated note | 821 | 821 |
| routed by regulation threshold | 94 | 37 |
| **fully automated** | **915 (93%)** | **858 (87%)** |
| left for a person | 69 | 126 |

### What "fully automated" means, screen by screen

`explore/automation_by_judgment.py` joins the run with Step 2's judgment load.
277 of the 858 automated rows are on five screens whose operators open a
procedure or regulation in most runs (65–88%); there the tool writes 確認済
without the consultation. The other 581 rows (59% of all) are on seven screens
where the recorded work is the steps themselves. The report now says so, and
risk R9 names it: a templated 確認済 is not the check it names. One screen sits
just under the line — hr 福利厚生申請, at 49%.

### Also

`src/gold.py`'s docstring said gold segments cover ~82% of session time; they
cover 94.7% (`python gold.py`).

This run: median 132 ms per row, p95 149 ms, 145 s wall clock.

## Config that transcribed the sample, machine paths, and "exactly one per execution"

### Four definitions listed sample values as routing keys

`tool/definitions/fin_ob.yaml` listed all 48 invoice references seen in the
logs as routing keys, each with its own copy of the note; `hr_ob`, `hr_la` and
`fin_la` did the same with departments. Every key routed the same way — only
the note's wording differed — and a value missing from the list fell through to
a different note. Each is now a single rule that fills the value in
(`{部署}として処理`).

Checked on every fixture row of the four screens, old definition against new:

| definition | rows | notes or modes that differ | lines |
|---|---:|---:|---|
| hr_la | 72 | 0 | 46 → 31 |
| fin_la | 24 | 0 | 46 → 31 |
| hr_ob | 108 | 0 | 52 → 31 |
| fin_ob | 48 | 0 | 172 → 33 |

The report said the definitions were "all but one under 55 lines"; it now gives
the longest, 44 lines, checked by `verify_report.py`.

### Absolute paths in the recon scripts

`explore/recon.py`, `recon_b.py`, `recon_c.py` and `recon_d.py` pointed at
`C:\Users\LENOVO\imby\data`, so they failed on any other machine and ignored
`config.local.json`. They now take the data root from `common.DATA`.

### README commands depended on the shell's directory

The first block ended inside `src/` and the second began `cd tool`, so pasting
them in order failed. Every command now runs from the repository root; each
script resolves its paths from its own location, and four of the listed scripts
were run that way as a check.

### "Exactly one confirm press per execution"

Of dataset A's 2,009 gold executions, 1,751 hold one press and 258 hold none;
none holds two. The report now says "never two in one", checked against a count
per execution.

## The gap baseline measured pauses from the agent's screenshots

`split_on_gap` read the idle gap from the agent's `ms_since_last_event`, which
counts every event. The baselines drop the agent's `screenshot_smart` rows
first, but the gap field still ran from them — and the agent takes a screenshot
just after most operator actions (after 15,426 app switches, 9,999 keystrokes,
3,589 clicks, 2,390 pastes, 1,486 navigations). So a pause was measured from the
last screenshot rather than the last action: 5,570 pauses were cut short by more
than a second, 498 by more than five. The gap is now measured between
consecutive operator actions, as the baseline's definition says.

| gap threshold | segments | BF1@2s | BF1@5s | WindowDiff |
|---|---:|---:|---:|---:|
| 2 s, agent's gap field | 8,290 | 0.285 | 0.360 | 0.736 |
| 3 s, agent's gap field (the report's "best baseline") | 4,150 | 0.240 | 0.316 | 0.656 |
| 2 s, between actions | 10,928 | 0.265 | 0.303 | 0.779 |
| **3 s, between actions** | **5,236** | **0.275** | **0.365** | 0.682 |
| 5 s, between actions | 2,047 | 0.188 | 0.268 | 0.536 |
| 10 s, between actions | 1,428 | 0.099 | 0.127 | 0.507 |

Two corrections in one. The baseline was weaker than its own definition, by
0.049 at 5 s — in the delivered segmenter's favour. And under the old field the
2 s threshold beat 3 s on both BF1 measures, so the label "best baseline" was
wrong; measured correctly, 3 s is the best threshold from 1 to 10 s, and
`verify_report.py` now checks that it stays so. The delivered segmenter's lead
at 5 s narrows from 0.440 to 0.391; the report, README and Japanese summary
carry the corrected column, and the "best baseline" now sits 0.10 above the
random control rather than 0.05.

Also: `segment_v3.py`'s docstring repeated "exactly one per segment"; `segment.py`'s
demo scored v1 with the manifest's session bounds, which its own `event_bounds`
docstring says were removed from the inference path, and its "without
min-length filter" line matched the default it was meant to contrast with.
`tool/run.py --llm-drafts` with no key configured ran without the model and
said nothing; it now says so.

## The coverage comparison used a random control with half-length segments

`explore/metric_audit.py`'s random control matches the delivered segmentation's
segment count and nothing else: it draws 2n cut points per session and pairs
them, so its segments average half the delivered length and leave about half of
each session idle. For boundary F1 that is harmless — if anything it has twice
the boundaries to land near a true one. For coverage — how much of a gold
execution its best-matching segment covers — it is not: shorter segments cannot
cover as much, by construction.

A fairer null keeps each session's own segment durations, idle gaps and labels
and shuffles their order, so only placement is random:

| control, 5 seeds | BF1@5s | ARI | executions ≥80% covered | median coverage |
|---|---:|---:|---:|---:|
| delivered | 0.756 | 0.708 | 83.0% | 97.5% |
| count-matched random (as quoted before) | 0.267 | 0.002 | 17.8% | 38.1% |
| own durations, placed at random | 0.261 | 0.009 | 43.0% | 73.6% |

The boundary claim stands: both nulls score about 0.26, and "discriminates by
+0.489" is unchanged. The coverage claim was overstated: chance reaches 43.0%
and 73.6% given the delivered segments' lengths, not 17.8% and 38.1%. The report
now compares against the placement control and says why it changed;
`metric_audit.py` prints both.

### Also: leave-one-machine-out skipped a machine

`explore/overfit_audit.py` held out only machines with at least 3 sessions,
which silently left out one of dataset A's eight: JAYESH, with 2. The
fold's size has no bearing on the tuning, which happens on the other sessions,
so there was no reason to drop it. Held out, it scores BF1@5s 0.854 (tuned
max_unit_s=90).

| | machines | mean BF1@5s | sd | worst |
|---|---:|---:|---:|---:|
| as reported | 7 | 0.745 | 0.119 | 0.471 |
| every machine | 8 | 0.759 | 0.117 | 0.471 |

The exclusion had not flattered the result — the missing fold is one of the
stronger ones — but it was a selection the report did not state. The report now
also says what the protocol does not test: only the tuned parameter is refitted
without the machine being scored; the bracketing design was developed with
every machine in view, and dataset B is its real test.

## One parameter is fitted, and it is the one that sets idle

The report's sensitivity paragraph said `expand_gap_s` from 20 to 300 leaves
BF1@2s unchanged at 0.700, and concluded that almost nothing in the pipeline is
fitted. Both halves were measured on BF1@2s alone. `expand_gap_s` barely moves a
boundary by design: what it controls is how much of the gap between two units is
claimed as work rather than left idle.

| `expand_gap_s` | BF1@2s | BF1@5s | WindowDiff | V | ARI | idle (true 5.0%) |
|---:|---:|---:|---:|---:|---:|---:|
| 20 | 0.700 | 0.756 | 0.207 | 0.709 | 0.658 | 12.5% |
| 30 | 0.700 | 0.756 | 0.203 | 0.711 | 0.681 | 9.8% |
| **60 (shipped)** | 0.700 | 0.756 | 0.195 | 0.719 | 0.708 | 6.6% |
| 120 | 0.700 | 0.756 | 0.194 | 0.720 | 0.713 | 5.7% |
| 300 | 0.700 | 0.756 | 0.194 | 0.722 | 0.720 | 4.2% |

`max_unit_s` is inert on every column (100 to 600: V 0.718–0.719, ARI
0.708–0.709, idle 6.6–6.7%), as claimed.

The same finding undid a sentence in section 1: "two figures were never
optimised for — the segment count, and claimed idle time within 1.6 points".
The expansion was introduced to correct idle (36.7% without it), and its cap
sets it, so idle is not independent evidence. The segment count is: the confirm
presses fix it. `explore/ablation.py` now prints the idle and ARI sweeps, and
`verify_report.py` checks the report's figures against them.

The new check on the idle gap failed on its first run. The report had always said
claimed idle is "within 1.6 points" of the truth — 6.6% less 5.0%, a difference
of two figures already rounded. Unrounded, the gap is 1.5 points; the report now
says so.

## The priority formula counted run length twice, and the robustness check counted it twice

`src/rank.py` ranked on share of time × transfers per run × automatability.
Transfers per run already grow with run length, so the product counts it twice:
two processes with the same total time and the same total transfers came out ten
times apart if one's runs were ten times as long. The shipped formula is now the
hand transfers automation would remove, discounted for judgment — executions ×
transfers per run × (1 − judgment share).

The robustness check had a matching flaw. Of its "six different weightings", two
— "shipped formula" and "time x mech x autom" — are the same formula, since share
of time is time over a constant; they rank every process identically. So the
table counted one formula twice.

| | top three under the shipped formula |
|---|---|
| before | payroll_item_maintenance, inventory_payroll_items, recurring_supplier_payment |
| after | payroll_item_maintenance, inventory_payroll_items, new_supplier_registration |

| process | top-3 appearances, 6 listed (one twice) | top-3 appearances, 5 distinct |
|---|---:|---:|
| **payroll_item_maintenance** | **6 / 6** | **5 / 5** |
| recurring_supplier_payment | 4 / 6 | 2 / 5 |
| inventory_payroll_items | 3 / 6 | 2 / 5 |
| new_grad_onboarding | 2 / 6 | 2 / 5 |
| new_supplier_registration | 1 / 6 | 2 / 5 |
| leave_application_review | 1 / 6 | 1 / 5 |
| contract_termination | 1 / 6 | 1 / 5 |

The Step 3 choice stands: payroll_item_maintenance is in the top three under
every distinct weighting, and its screen carries 38.3% of observed work. One
claim does not: "the three top-ranked processes are the same screen in
different deployments" held only under the old formula. The two top-ranked
processes are; the third is supplier registration, on another screen. The
report, the Japanese summary and the engine's docstring say two now, and
`verify_report.py` checks the weighting count and that sentence rather than
hard-coding six.

Also: `src/label.py`'s docstring still presented a signature search from before
end-state labelling and vocabulary discovery (system + route, 22 clusters,
V = 0.797) as the chosen signature's score, and gave its purity as 92–98%. The
shipped labeller scores V = 0.931 with 15 clusters and purities of 87.9–100%;
the docstring now dates the search and points to `python label.py` for the
current figures.

## The first headline finding credited case IDs with what the clicks do

The report's summary listed, as the first of three findings that drove the
work: case IDs are recoverable from the screen, which "turns Step 1 … into
case-identity reconstruction — the only method that can separate two consecutive
executions of the *same* process". Section 7's ablation says otherwise: with
case anchors removed entirely, boundary F1 at 2 s is 0.723 against the shipped
0.700. The delivered segmenter separates consecutive executions with the row
click and the confirm press; case identity drives the fallback and helps ARI.

The figure itself holds, and gains a companion. `explore/caseid_discovery.py`
counted an ID as found if it appeared anywhere in the session — a list view
shows many IDs at once, long before or after their own execution. It now also
counts the ID in screen text captured during its own execution, with the gold
set's execution windows.

The summary and the Japanese summary now say the case identifier is visible on
screen, give both figures, and say what the delivered pipeline uses it for.

### The "missing" screenshots were misfiled, not missing

Section 8 said "10% of dataset A screenshots are missing from the distribution
provided", and NOTES said the same. Resolved within each event's own session,
every one of the 34,580 referenced screenshots is on disk:

| where the file is | references |
|---|---:|
| the chunk folder the event names | 31,013 |
| another chunk folder of the same session (e.g. `chunk_1200` for `chunk_20260630-1200-…`) | 3,567 (10.3%) |
| nowhere in the session | 0 |

Filenames carry the capture timestamp and are unique, so these are the right
images under a second folder name. The first check made in this round pooled
every folder in the dataset, found all 34,580 names, and would have called the
limitation simply false; a check against the named folder alone reproduces the
10%. Only resolving within the session tells the two apart. The report and
NOTES now say the images are present and misfiled, and `verify_report.py`
counts all three rows.

## Timings checked within a factor of two, and headline figures nothing checked

A fresh `python tool/run.py` gave median 132 ms per row, p95 153 ms and 147.2 s
wall clock; the documents quote the earlier run's 132 ms, p95 149 ms and 145 s.
`verify_report.py` matched timings exactly, so this rerun alone would have
reported the documents stale, and so would any reviewer's. Latency belongs to
the machine as much as to the code. The checker now passes a timing within a
factor of two of the last run and prints it as `OK~`.

The file it reads timings from, `out/automation_run.json`, is gitignored and
holds whatever ran last. A demonstration run earlier today, against a portal in
which some rows had already been processed by hand, had left 20 timeouts in it,
all on one screen; `explore/automation_by_judgment.py` then reported 838
automated rows of 984 and did not say why 20 were missing. The checker's own
failure count would have refused that run. A fresh run restored 858 automated
and 0 failed.

Every number in REPORT, README and SUMMARY_JA was then set against the
checker's log. The live figures no check re-derived were confirmed by hand
before any check was written for them:

| figure | as written | recomputed |
|---|---|---|
| row clicks inside a gold execution | 99.9% | 1,778 of 1,780 (99.89%) |
| row click, median relative position | 0.13 | 0.1348 |
| confirm presses inside a gold execution | 1,751 (99.9%) | 1,751 of 1,752 (99.94%) |
| confirm press, median relative position | 0.89 | 0.8853 |
| median gap between consecutive gold executions | 0.0 s | 1.3 ms; 19.1% exactly 0, 91.1% under 10 ms |
| ground truth's idle share | 5.0% | 5.027% |
| ground-truth executions | 2,009 | 2,009 |

Each click is placed in at most one execution, since a fifth of gold
boundaries have no gap and a click on one would otherwise count twice. All
matched, and no document changed. The rest of what no check covers is history
(the phase table, the first build's 456 rows, v3's figures) or a parameter.

## The ranking section did not show the ranking; procedural screens; 137x

### The table headed "Ranking" was not the ranking

Section 2's table showed eight of the twelve processes, ordered by minutes. The
priority order - executions × transfers per run × (1 − judgment share), every
process - existed only in `report/step2_analysis.md`. Four processes were
missing, and contractor_payment_setup (11.0 min) had been cut while
admin_privilege_request (8.5 min) was shown. The row check compared only the
rows the report showed with a fresh regeneration, so it passed. The table is now
the generated ranking, with no figure changed:

payroll_item_maintenance > inventory_payroll_items > new_supplier_registration >
leave_application_review > recurring_supplier_payment > admin_privilege_request >
childcare_leave_handling > new_grad_onboarding > contract_termination >
contractor_payment_setup > entertainment_expense_approval > fin_social_insurance

`verify_report.py` now also checks the report's row order against the
regeneration.

Printing the formula above an ordered table invites recomputing it, and from
the rounded figures two pairs of neighbours swap:

| rows | processes | priority, unrounded | from the rounded figures |
|---|---|---|---|
| 3-4 | new_supplier_registration, leave_application_review | 112.53, 111.03 | 111.9, 112.5 |
| 8-9 | new_grad_onboarding, contract_termination | 43.69, 43.66 | 43.2, 43.9 |

The order is right. The report and the generator of `step2_analysis.md`, which
states the same formula, now say it is computed before rounding.

### What the tool does where operators follow a procedure

Section 3 said rows governed by the ten procedural documents "still reach a
person", section 5 that those processes are "out of scope entirely", and the
Japanese summary 対象外. Neither has been true since the tool covered all 12
screens. `explore/automation_by_judgment.py` shows the onboarding screen, whose
operators have a new-graduate checklist open in 88% of runs, with 108 rows
automated and none left for a person. Only the flagged rows reach a person.
Both sections and the summary now say that the tool does not read those
documents, that it automates the routine rows without the consultation, and
that whether a person must still make it is the open question in R9.

### 135x was 137x

The LLM comparison has said 135x since the first commit. The run output from
that day, kept in the session transcript, prints the model's
`latency_p50=23310ms` over five calls. The deterministic run beside it printed a
median of 170 ms, rounded to the millisecond. 23,310 / 170 = 137.1, and anything
from 169.5 to 170.5 ms still gives 137. Corrected in the report, the Japanese
summary, both READMEs and two docstrings. WORKLOG's Day 6 entry keeps what was
written then. The checker now recomputes the ratio from the two figures printed
beside it, in every document that quotes it.
