# Work log

Daily record: what I was thinking, what I tried, what did not work.

Generative AI use is recorded inline — the task explicitly permits it and asks
for it to be logged.

---

## Day 0 — 2026-09-09 — Recon and scaffolding

**Goal:** understand the data well enough to commit to an approach, before
writing any segmentation code.

**Done**

- Profiled both datasets without ever loading raw logs into an LLM context:
  scripts that print aggregates only (`explore/recon*.py`).
- Established dataset A's 15 process families, 3 domains, ~2,009 executions,
  median duration 24–74 s, and which families carry variants.
- Established dataset B's shape: 15 sessions, 4 people, a single 3-hour window
  on 2026-07-01; Edge, Word, Excel, Notepad, PowerShell.
- Mapped the payload schema per event type with fill rates, so I know which
  fields are actually usable rather than merely documented.
- Built `src/build_index.py`: 790 MB of JSONL -> an 11 MB Parquet index
  (182,483 x 35) plus a 2.8 MB screen-text side table.

**Findings that changed the plan**

1. *Case IDs are recoverable from the log.* All 32 ground-truth case IDs of the
   first dataset A session appear verbatim in the events. This reframes Step 1
   from blind change-point detection to case-identity reconstruction — a
   stronger and far more explainable basis, and the only thing that can split
   two consecutive executions of the same process.
2. *Idle gaps are a weak signal here* (p95 = 2.0 s). The obvious first
   approach — segment on pauses — would have been a dead end. Checking the gap
   distribution before building on it saved a day.
3. *The two datasets share their portal systems*, contrary to my first reading
   of the brief. Chrome to Edge, plus a new set of Word procedure documents,
   are the real differences.
4. *27% of ground-truth process starts have no event within ±2 s.* Scoring must
   use a tolerance window, or I would have spent the week tuning against a
   metric that was mostly measuring ground-truth jitter rather than my errors.

**Dead ends and corrections**

- The first extraction attempt failed on the Windows 260-character path limit —
  the working path was already ~200 characters. Moved to a short root.
- I initially concluded `browser_form_input` carried no DOM attributes, because
  I read `payload.element.attributes`. The real path is `payload.field`, which
  is 100% populated with `id`, `label`, `css_selector` and `xpath`. The
  correction matters well beyond tidiness: it is direct evidence that
  DOM-level automation of the portal is feasible, which is a load-bearing
  assumption for Step 3.

**AI use:** Claude (Opus) wrote the recon scripts, the schema profiler and the
index builder. Every finding above was verified against printed aggregates
rather than accepted on assertion.

**Next:** build the evaluation harness *before* the segmenter, so that every
later change is measured rather than guessed at.

---

## Day 1 — 2026-09-09 — Evaluation framework and baselines

**Goal:** define what "good" means, and prove the definition is trustworthy,
before writing a single line of segmentation logic.

**Reframing (from the role description)**

The recording agent in the logs is ProcMine — the company's own process mining
platform. So this is not a generic segmentation exercise; it is the canonical
problem of that field. Process mining needs an event log of
*(case ID, activity, timestamp)*, and the provided data has only timestamps.
Recovering the rest from an uncased stream is *event log correlation*. Framing
Step 1 that way also reframes Day 0's case-ID finding: it stops being a trick
and becomes the standard solution to the field's central problem. Full
consequences recorded in NOTES.md.

**Built**

- `src/gold.py` — gold segments from `gt_manifest.json`. Validated first:
  2,009 executions, zero overlaps, 1,819 phase-1 + 190 resumed reconciling
  exactly with the `process_started` / `process_resumed` counts in `gt.jsonl`.
- `src/evaluate.py` — boundary F1 at 2/5/10 s tolerance, WindowDiff, and
  V-measure / ARI for label consistency, all derived from a shared 1-second
  binned timeline with an explicit IDLE class.
- `src/baseline.py` — the approaches a reasonable person tries first.
- `RESULTS.md` — the scoreboard, appended to rather than rewritten.

**Results**

The harness validates: ground truth scored against itself returns 1.000 on
every metric, WindowDiff 0.000. Without that check the rest of the table would
be unfalsifiable.

Best baselines: gap > 3 s reaches BF1@5s = 0.221 with V-measure 0.018; app
switching reaches V-measure 0.135 but BF1@2s = 0.024. Nothing clears 0.14 on
label agreement.

**What this settles**

Idle-gap segmentation is dead, and now measurably so rather than by argument.
At a 2 s threshold it emits 8,290 segments for 2,009 true ones; at 10 s it
misses 84% of boundaries. There is no threshold that works, because the median
gap between consecutive gold segments is 0.0 s — half of all true boundaries
have no pause to detect.

A second result I did not expect: **over-segmentation is worse than not
segmenting at all.** One segment per session scores WindowDiff 0.491; gap > 2 s
scores 0.899. Useful discipline for later, when the temptation will be to tune
for boundary recall.

**Dead ends and corrections**

- I reported ~18% of wall time as idle. Wrong — my ad-hoc check silently
  dropped the 257 executions with a null `end_ts`. With the full gold set,
  coverage is 94.7% and idle is 5.3%. Caught it by cross-checking against
  `gold.py`, which is exactly the kind of thing a scorer exists to prevent.
- Mid-day, a second copy of the data surfaced that was a strict superset of the
  one I had been using: one extra dataset A chunk (762 events) and 27,600 more
  screenshots. Rebuilt the index and re-ran everything. Baselines moved only in
  the third decimal, but the earlier numbers were computed on incomplete input.
  The uncomfortable part is that the first copy looked complete and its event
  count matched the figure quoted in the brief. Matching a rounded number in a
  spec is not verification.

**AI use:** Claude (Opus) for the metric implementations and baselines. The
gold-vs-gold sanity check exists specifically because generated metric code is
easy to get subtly wrong and impossible to eyeball.

**Next:** case-ID and activity recovery — turning the stream into a real event
log. Target: beat BF1@5s = 0.221 and V = 0.135 simultaneously.

---

## Day 2–3 — 2026-09-09/10 — Case recovery, v1 segmenter, LLM layer

**Built**

- `src/caseid.py` — recovers the active case from screen text.
- `src/segment.py` — anchors to segments: nearest-anchor assignment on a 1 s
  grid, boundaries snapped to structural transitions.
- `src/llm.py` — provider-agnostic, cached, instrumented, payload-guarded.

**Result: v1 clears both targets at once.**

| | best baseline | v1 | gold |
|---|---:|---:|---:|
| BF1@5s | 0.221 | **0.463** | 1.000 |
| V-measure | 0.135 | **0.507** | 1.000 |
| WindowDiff | 0.638 | **0.382** | 0.000 |
| segments | 2580 | **1974** | 2009 |

Tuned on 32 sessions, verified on 31 held out. Test slightly *exceeds* dev and
the optimum is flat over max_dist 60–120 s, so this is a plateau rather than a
fitted point.

**What I got wrong, and how it was caught**

1. *Case IDs are in keystrokes.* They are not — 97.8% are in
   `context.extracted_text`. Day 0's probe grepped whole JSON lines and I
   attributed hits to `payload` without checking. Measuring per-field fixed it.
2. *The A-tuned rule will transfer.* It fired **72 times in all of dataset B**.
   B's captures are half as long and its IDs do not repeat, because B's screen
   text is the worker's own completion memo rather than a portal list view.
   Generalising to "unambiguous by dominance *or* uniqueness" cost one point of
   precision on A and unlocked B.
3. *Boundary snapping is the clever part.* Ablation says it contributes
   0.002–0.005. Nearly all the signal is one parameter, `max_dist`.
4. *The min-length filter is obviously right.* It measurably hurt, so it is
   disabled. The short runs it removed were landing on real boundaries.
5. *The user's API key is the wrong type* — I asserted this from an `AIza`
   prefix heuristic. Wrong: Google issues several key formats and an `AQ.` key
   authenticates fine. The real fault was mine — `gemini-2.5-flash` had been
   retired for new keys. Replaced the heuristic with a live `ListModels` check,
   because guessing credential validity from a prefix is exactly the kind of
   assumption this task is testing.

**The most valuable finding is a negative one.** On dataset A the case-ID prefix
predicts the process family with **100% purity across all 15 families**. It
would have been easy to ship that and report a spectacular score. It does not
transfer: dataset B's IDs are employee records, not process-typed cases. I had
flagged it as an optimistic assumption before measuring, and it was.

**Unplanned but kept:** the model fallback chain in `src/llm.py`. Written
because `gemini-2.5-flash` was retired mid-project; within a minute of being
written, a live call fell through two 503s before succeeding. Provider
availability is an operational risk, not a hypothetical one.

**AI use:** Claude (Opus) for all implementation. Gemini (3.8/3.6/3.5-flash) is
wired in for label judging on dataset B, which has no ground truth — with a
payload guard so only derived material leaves the machine, since free-tier data
is used to improve the provider's models.

**Next:** signature-based labelling for dataset B, then ship `segments.jsonl`.
