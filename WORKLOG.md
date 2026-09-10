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

---

## Day 4 — 2026-09-10 — Labelling, and a transfer that failed

**Built:** `src/label.py` (signature labelling), `src/discover.py` (learn the
portal vocabulary instead of hard-coding it).

**Result:** labels from (system + route) reach V=0.854 on gold segments in
exactly 15 clusters, in 1:1 correspondence with the 15 true process families.
The structure is not luck — the portal is one SPA deployed three times, so
3 systems x 5 routes *is* the taxonomy.

**The important failure.** Applying the pipeline to dataset B produced 341
segments that looked entirely plausible: 99.2% coverage, 12 sensible labels,
believable durations. Every internal statistic was fine. The held-out check —
629 confirm presses deliberately excluded from segmentation — showed they landed
*uniformly* across my segments (median relative position 0.35, 9% in the last
third) and that 90 segments swallowed four completions each.

The transfer had failed silently, and only a signal the method could not see
exposed it. That is the most useful hour of the project.

**Corrections:** two metric audits. Boundaries were derived from label changes,
so the boundary between two consecutive executions of the same process
disappeared — the metric was scoring 94% of boundaries and discarding exactly
the hardest 6%. The fix then turned out to have reached boundary F1 but not
WindowDiff. A partial fix is worse than none because it looks finished.

**AI use:** Claude (Opus) for implementation and for the audit scripts.

---

## Day 5 — 2026-09-10 — v3, the overfitting audit, Step 2

**Built:** `src/segment_v3.py`, `src/analyze.py`, `src/rank.py`.

**The fix.** Every portal screen ends a unit of work with a button press. I had
searched dataset A for dataset B's naming (`btn-*-ok`), found **zero**, and
concluded the signal did not exist there. It did — dataset A names its buttons
semantically. Matching on structure (an HTML `button` tag) rather than on name
finds 1,751 of them, and they land inside a gold segment 1,751 times out of
1,751, one per segment, at median position 0.89.

Inverting the design around that took **BF1@5s from 0.450 to 0.722**.

**The overfitting audit**, prompted by a fair challenge that the pipeline was
tuned to dataset A. It found a real fault — parameters swept over all 63
sessions with a dev/test split reported afterwards — but the honest protocol
scored *higher* (0.745 vs 0.722), because the value I shipped was chosen for
idle calibration rather than peak boundary F1. Leave-one-machine-out gave
0.728 ± 0.120, with one machine at 0.444 explained entirely by having zero L3
events.

**A trap avoided by luck, then by argument.** Tuning `max_unit_s` for the metric
picks 60 s (BF1@5s 0.741) — which then claims 19.9% of wall time is idle against
a true 5.0%, understating every process duration by about 15%. Step 2 exists to
say how long processes take. Scoring better on the proxy while answering the
real question wrongly is the actual overfitting trap.

---

## Day 6 — 2026-09-10 — The tool, and abandoning the RAG plan

**Built:** `tool/` — shared engine, three definitions, regulation rule
extraction, and a portal reconstructed from the logged DOM evidence.

**Result:** 456 rows, 94% fully automated, zero failures, 151 ms median per row.

**The design I abandoned.** This was going to be a RAG feature: read the 規程,
decide the handling. Two pieces of evidence killed it. Measured, the model was
135x slower (23,310 ms vs 170 ms), timed out on 2 of 5 calls, and returned the
regulation's *filename* instead of composing a note. Then reading the captured
regulation text showed there was never a judgment problem — approval routing is
a threshold table, and thresholds are arithmetic.

The model now has one job and it runs offline: proposing a rule table for a
human to check. The runtime is fully deterministic and works with no model
configured. That is the opposite of the fashionable arrangement and I believe it
is the correct one.

**Corrections:** `P4-07089771-012` is a worklist *row* id, not an employee id —
I had flagged it for human verification and the data answered it. And dataset B
*does* carry variants (種別: 定常/調整), contradicting my earlier note that they
were unreadable; the variant is in the row, not the button.

---

## Day 7 — 2026-09-10 — Report

Wrote `report/REPORT.md`, the Japanese summary, and rendered both to PDF via
headless Chromium (chosen over a Python PDF library because it already has the
font fallback to typeset Japanese).

A Japanese-reading reviewer verified the twelve decision-bearing readings,
including the approval-threshold direction the tool routes on. Those claims are
now stated as verified rather than assumed.

---

## What I would do differently

**Day 3's LLM layer was built three days before anything needed it**, because it
seemed like something the task wanted, and the eventual conclusion was that it
should not be in the runtime path at all. That time belonged in Step 2.

**I asserted from greps three times and was wrong each time**: case IDs "in
keystroke payloads" (they are in screen text), "zero confirm presses in dataset
A" (wrong regex), and the API key being invalid (the model had been retired).
Each was caught by measuring, but each cost time that measuring first would have
saved.

**How AI was used, overall:** Claude (Opus) wrote essentially all the code and
the drafts of these documents. Every quantitative claim here was produced by a
script whose output I read, not by asking a model what it thought. The recurring
failure mode was the model — and I — being confident about something that had
not been measured; the audits exist because of that.

---

## Later — corrections found by continued defect hunting

Recorded as a forward entry rather than by editing the earlier days. A work log
that is rewritten when the numbers change is not a log.

**Boundary matching was greedy, and greedy is not optimal.** `boundary_prf`
paired boundaries nearest-first, which can spend a predicted boundary on a gold
boundary that had another candidate and strand one that had only that. Replaced
with exact rectangular assignment. Everything was rescored the same way,
including the baselines and the random control — a change that only rescores the
winner is not a fix. The baselines gained more than the shipped pipeline did
(app-switch +0.055 at 5 s), so the error had not been in anyone's favour.

Every figure in the earlier entries that quotes a boundary F1 predates this and
is superseded by `RESULTS.md`. The Day 5 entry's leave-one-machine-out figure of
0.728 ± 0.120 was correct for what was measured that day; the shipped pipeline
now gives 0.745 ± 0.119.

**The audit scripts were auditing the wrong version.** `metric_audit.py` and
`overfit_audit.py` both imported `segment_v3` while `v4` was what shipped, so
their chance-calibration and cross-operator figures described a superseded
segmenter. Repointed. This is the third instance of the same failure in this
project: a check that runs, produces plausible output, and measures the wrong
thing.

**`matching_audit.py` became a test that could not fail.** It compared
`boundary_prf` against an optimal reference — and once `boundary_prf` itself
became optimal, it was comparing optimal to optimal, guaranteed to report a
delta of zero. It now carries its own copy of the superseded greedy matcher so
the comparison stays real.

**Two components tested for the first time, both correct.** `gold.py`'s
end-time inference, applied to the 1,752 executions that have a real end,
lands within ±2 s **97.1%** of the time and never undershoots — the 257 inferred
ends are not propping up the gold set. And the Step 3 tool is idempotent: a
second pass over the same portal processes 0 rows rather than reprocessing 288.

**A cold-start reviewer pass found three first-run defects.** There was no
`requirements.txt`, so anyone reproducing the work had to guess nine package
versions; it now pins the exact versions everything was verified with. With no
data unpacked, `build_index.py` died with `KeyError: 'ds'` — accurate, and
useless to a new user; it now exits naming the folder to unzip into and the
config file that can point elsewhere. And two figures in `NOTES.md` had gone
stale. A fresh clone of the fix, with the committed deliverable deleted first,
regenerates `segments.jsonl` byte-for-byte.

**The recurring failure has one root.** Five times in this project a check ran,
produced plausible output, and measured nothing — among them an audit comparing
optimal matching with itself, and a fresh-clone test that compared a file with
itself. None of them had ever been seen to fail. The audits in `explore/` also
only print, so nothing enforces them. `tests/test_invariants.py` now asserts the
claims the project rests on: the deliverable's format as the brief specifies it,
the scorer rating ground truth as perfect, the two metric fixes, and the
first-run behaviour.

**The first version of one of those tests could not fail either — a sixth
instance, caught before commit.** The greedy-matching test used gold `[10,12]`,
pred `[11,14]`. Traced through the actual pre-fix matcher from git history,
greedy scores that case 1.0 too, so the test would have passed against the very
bug it was named after. It now uses cases greedy demonstrably gets wrong
(F1 0.5), and `tests/mutation_check.py` makes the property checkable rather than
assumed: it reintroduces each defect — the real greedy matcher from git,
label-change boundaries, a broken F1 formula, the removed `build_index` guard,
nine corruptions of the deliverable, a test that crashes — and requires the
matching test to fail. 14 of 14 do. Building it surfaced two more gaps. The
runner caught only `AssertionError`, so one crashing test would silently hide
every test after it. And the session check counted fifteen ids without checking
they were the directory names the brief specifies — it passed on fifteen full
paths.
