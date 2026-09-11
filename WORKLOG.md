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

**AI use in this section:** as above, and more so. Each round below was a review
pass I asked Claude (Claude Code, Opus) to make — read the repository as a
reviewer would, measure each suspicion, fix what failed — and the entries are
its drafts. Every figure in them comes from a committed script, not from the
model's recollection.

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

**The report checker could not see the report — a seventh instance.**
`explore/verify_report.py` reported "21/21 figures match". Twenty of its
twenty-one claimed values were literals typed into the script, and one was a
figure the report does not contain at all; only the top-screen share was read
from the document. It compared the pipeline with its own copy of the numbers.
Rewritten so that every claimed value is parsed out of `REPORT.md` and
`SUMMARY_JA.md`, it was run first against the unchanged documents and reported
**59 of 119 figures stale**. The report's summary, ablation and one risk still
quoted the greedy scorer (0.673, 0.752, 0.684, 0.286). §3 still said "three
~30-line definitions covers 36%" one paragraph after calling its premise false.
§5 still described 26 of 456 rows, R2 said 94%, and a limitation quoted 175
minutes and a variant count "currently" measured on an earlier revision. The
Japanese summary described the 3-screen, 456-row tool almost throughout. None of
it was visible to a check that never read the document. It now reads the README
as well — the first page a reviewer opens, and one no check had ever read.

**The rewritten checker had two defects of its own, both caught on its first
run.** It captured a sentence's closing full stop as part of the figure. And it
fed the baselines the raw index where `baseline.py` excludes screen captures, so
it flagged the report's *correct* baseline figures as stale — it would have
"corrected" 4,150 segments to 4,336. The filter is now one function that both
use. Its disagreement with `baseline.py`'s own output is what gave it away:
comparing the checker against an independent source is the only reason it did
not introduce errors while claiming to remove them.

**The ablation had never been committed.** The §7 table was produced ad hoc and
went stale when the scorer and the labeller changed underneath it.
`explore/ablation.py` now regenerates it. Its conclusions survive, with two
nuances the report now states: without case anchors BF1@2s is higher (0.723
against 0.700) but BF1@5s is lower; and the anchor threshold is not quite inert,
spanning 0.695–0.714 across 2 to 4. The shipped value was chosen for anchor
precision, and moving it to 4 because it scores higher on the evaluation set
would be tuning on the test data, so it stays.

**The README's reproduction command did not reproduce the README.**
`python segment_v4.py` ran the segmenter at the function's default
`expand_gap_s` of 30 rather than the shipped 60, and printed a WindowDiff,
V-measure and idle share that matched no table. It now runs the shipped
configuration.

**A baseline was not deterministic.** `baseline.py` broke ties for the most
common application with `max(set(xs), key=xs.count)`, and set order for strings
changes with every process's hash seed. The app-labelled gap baseline scored
V 0.0637–0.0639 under four seeds, printing as 0.063 in one run and 0.064 in the
next. The rewritten checker caught it by disagreeing with `baseline.py` by 0.001.
Ties now go to the value seen first, and V is 0.0633 under every seed. The
pattern appears nowhere else in the codebase — the labeller's own `_mode` was
already order-stable — and the deliverable regenerates byte-for-byte under three
different hash seeds.

**The Japanese summary was rewritten from the corrected English.** Its figures
are checked mechanically now, but its new sentences have not yet been read by
the Japanese-reading reviewer who checked the originals.

**An audit promised a test it never ran.** `overfit_audit.py`'s docstring
listed a third test — hold out a whole department, the closest analogue of the
dataset A → B move — but the code stopped after two. No document quoted a
result from it, so no published figure was wrong, but the script claimed more
than it did. Building it turned out to be impossible rather than merely
skipped: every one of dataset A's 63 sessions contains work from all three
departments, so none can be held out by session. The audit now prints that
evidence in place of the promise, the report says so where it describes
generalisation, and the checker verifies the count. The cross-department test
that does exist is dataset B itself, against signals the pipeline never reads.

**The Japanese summary had gaps in the middle of its sentences.** A line break
inside a Markdown paragraph renders as a space: harmless between English words,
a visible gap between Japanese characters (「を 示す」, 「は 算出しません」).
Every earlier version carried them, in the PDF and on GitHub alike. Only
rendering the PDF to an image and looking at it showed this; no text check
could have. Each paragraph is now one line, and a comparison with all whitespace
removed confirms not one character changed.

**The approval router mishandled two comparators.** `regulations.route()`
treated 超 ("more than") as 以上 ("or more") and 以下 ("or less") as 未満
("under"), so an amount exactly at a threshold went to the wrong approver. The
captured regulations use only 以上 and 未満, and old and new routing agree on all
120,027 real comparisons, so no result changes; but the parser accepts all four,
and re-extraction is the documented path when a regulation is revised. Step 3
had no tests at all. It now has two, each checked to fail on the defect it
guards.

**The report's main evidence for dataset B came from code that was never
committed.** §8 quoted breadcrumb agreement of V = 0.948 on 31 segments. The
committed `label_vs_breadcrumb.py` computed none of it — only a purity figure —
and the analysis behind 0.948 had been run against the modal labeller that it
then led to replacing. Rebuilt as committed code and run on the current
deliverable, it reproduces exactly, and now carries the chance baseline a
31-pair V-measure needs: 0.948 against 0.158 for shuffled labels. The report had
also merged two rows of the sweep: "falls to 0.254 at any point" was the modal
comparison (0.255); a breadcrumb captured anywhere in the segment gives 0.480.

**The completion-memo check had stopped testing anything.** Under v3 the memos
sat at median position 0.78, near segment ends. v4 stretches every segment to
the midpoint of the neighbouring gaps, so segments cover 97.9% of session time:
5,000 random instants land inside one 97.9% of the time, at median 0.50, against
the memos' 100% and 0.47. The report still quoted 0.78. It now reports the check
as spent. A check is evidence only while it can fail, and this one no longer
could.

**The README said the checker covered "every figure in the report".** It
covered 144 and missed the dataset B evidence, the Step 2 tables, the ablation
and the case-ID findings. It now re-derives those too, checks that the generated
Step 2 analysis is current, and fails rather than passes when a table it should
compare turns up empty. That guard fired before the first run: the process names
it looked up were tuples, so the table comparison would have checked nothing.
The first full run then failed, and the gate in front of the commit refused to
proceed: twelve ablation cells read as missing because `re.escape` escapes
spaces, which the checker's own whitespace handling then broke; a reused
variable made one README check compare a set against a number; and the README
still said 10 tests after two were added. Each was fixed and the full run
repeated before anything was committed.

**Two current-state documents still described retired evidence.** `NOTES.md`
called the confirm clicks and completion memos genuine held-out evidence — true
when it was written, false since the confirm click became the segmenter's
closing signal and v4 made the memos indistinguishable from random instants. It
also still called the regulations the one place a model earns its cost. It now
carries a marked correction rather than a rewrite, so the history stays
readable. `tool/README.md` gave the LLM comparison's deterministic error rate as
0 / 984, pairing the experiment's 170 ms latency with today's row count; like
the report, it now says 0 / 456, the rows modelled when the comparison ran.

**The model was in the Step 3 runtime path by default.** The report's most
defended Step 3 decision is that no model runs at runtime. `tool/run.py` created
one whenever an API key existed, and `engine.py` then asked it to draft notes
for the rows queued for review; only `--no-llm` prevented it, and the README's
command happened to include that flag. The model is now opt-in with
`--llm-drafts`, and a test fails if the default ever changes back. The report
also described the model's one remaining job — proposing rule tables offline —
as if it existed. No code does it: the three regulations with thresholds are
read by a regular expression. The report now says the role is designed, not
built.

**The raw-log guard let identifiers through.** R7 said only derived material
could leave the machine. The guard refused prompts containing JSON field names,
which catches a pasted event record, but not the same identifiers pasted as
screen text: a worklist row id, an invoice number and a session id all passed.
It now refuses those too, and R7 states what is enforced rather than what was
hoped.

**The report guessed the cause of its residual error.** It put the 23% of
executions that map to no single segment "mostly where a unit has no opening
click". Measured, that describes one execution in 2,009. The misses split
between units with both clicks (61.4%) and 258 units with neither (38.6%), and
those 258 are not a kind of process: most are the seven sessions of one machine
whose browser extension recorded nothing. Dataset B has one such session — 22 of
the 664 graded segments — which the report now discloses beside R1.

**Can accuracy go up without overfitting?** Not by tuning: the sensitivity sweep
shows the parameters are close to inert, and any choice would be made on the
evaluation data. The one lever left is the sessions without browser telemetry,
where the same row click is still visible through the accessibility layer: 99.0%
of those L2 clicks fall inside a gold execution, at median position 0.15 against
the browser click's 0.13, one per execution 95.1% of the time. Its ceiling on
the graded file is the 3.3% of segments in B's one gap session. Measured here,
not yet built — shipping it changes the graded file, which is the author's call.

**The accuracy experiment failed its own bar, and is not shipped.** Opening a
unit at each accessibility-layer row click, in sessions without browser
telemetry, raised boundary F1 at 5 s on those sessions from 0.471 to 0.803 — and
overall from 0.756 to 0.791 — while label consistency fell from 0.719 to 0.689,
ARI from 0.708 to 0.668, and precision at 2 s fell too. The brief scores
boundaries and label consistency; one up and one down is not an improvement, and
quoting only the 5-second figure would be choosing the metric after seeing the
result. On dataset B's gap session it would have turned 22 segments into 107,
because the same row is clicked repeatedly there. Fixing both would take two new
choices made after seeing these numbers — the definition of the overfitting this
project has avoided so far — for a ceiling of 3.3% of the graded segments.
Recorded as a negative result, with the script committed so it can be re-run.

**Two repairs to the failed experiment, diagnosed before building, and both
refuted.** The label loss looked like a timing fault: a segment running from one
row click to the next ends just before the next unit, where the labeller reads
its state. Reading the label at the opening click instead was predicted to help.
Measured against ground truth through a label-to-family map learned on the other
sessions' gold segments, it did the opposite — 23.2% correct against 32.8%.
Without the L3 route the labeller is weak at any reading point, which is what R1
already says. The over-segmentation looked like repeated clicks on one row;
merging consecutive clicks on the same row changes nothing (107 units stay 107),
because the repeats are never consecutive. Neither repair was built. Both
diagnoses ran on sessions already examined, so neither could have been a clean
test of a fix anyway.

**A parameter-free rival to the midpoint boundary, rejected.** Between a
confirm press and the next row click, v4 splits the gap at its midpoint. The
unseen head and tail of a unit scale with its length, so splitting the gap in
proportion to the two neighbouring brackets' lengths looked strictly better.
Scored against the true boundary on 1,549 adjacent pairs, it was worse where
it matters: within 2 s 71.7% against 80.2% on the dev half and 76.4% against
82.3% on the test half, gaining under two points at 5 s. The midpoint stays —
now as the better of two measured rules rather than an unexamined default. The
same measurement showed how bracketed units miss: 285 of 286 are overlapped by
two segments, so the residual error is boundary placement inside the gap, and
only an observable event inside it could do better than either rule.

**An observable boundary signal inside the gap, and the bar it had to clear.**
Rather than another rule of thumb, this asked which event actually opens a unit.
On dataset A's dev half it is an app switch 62% of the time (492 of 799
adjacent pairs), and then within 0.5 s of the true start 97.5% of the time. So
the gap between a confirm press and the next row click is divided at its first
app switch, where it has one, and at the midpoint otherwise — no new tuned
setting, and the event type was chosen on the dev half alone. On the untouched
test half it placed boundaries within 2 s 85.1% of the time against the
midpoint's 82.1%, and within 5 s 86.4% against 85.9%. That is a diagnostic, not
a result, so before the full evaluation the bar was written down: on the test
half, boundary F1 higher at 2 s and at 5 s with V no more than 0.005 lower; on
all of A, WindowDiff not worse, V no more than 0.005 lower and the one-segment
mapping not lower; on every machine, BF1@5s no more than 0.02 lower.

**It failed the bar.** Boundaries improved as the diagnostic promised — boundary
F1 at 2 s from 0.700 to 0.733, WindowDiff from 0.195 to 0.172, and more
executions mapping to one segment — but label consistency fell past the
tolerance set in advance (V 0.719 → 0.698 overall, 0.708 → 0.678 on the test
half), ARI with it, and one machine lost 0.029 at 5 s. The brief grades
boundaries and labels both, and a bar that could be renegotiated after seeing
the result would not be a bar. The rule stays in `segment_v4.py` behind
`split="first_app_switch"`, off by default, and
`explore/experiment_split_app_switch.py` re-runs the evaluation. Iterating on it
now — for instance so the cap stops leaving more time idle, the likely cause of
the label loss (idle 6.6% → 8.8%) — would mean designing against the same data a
third time, with no untouched labelled data left to check the result on.

**The claims nothing checked.** `verify_report.py` re-derives every figure the
report states, so the next place for a stale claim to hide was where it does
not look. Four places turned up. A comparison in prose: the report said the
chosen screen had the "second-lowest" judgment load, which was false — and the
screen figure was a plain mean of per-system percentages, the wrong aggregate,
which made the rank come out differently again. Weighted by runs it is the
lowest of the five, by half a point, and the report now says "though only
just" rather than claiming a margin it lacks. The login evidence: "all three
names appear in every session" — one appears in 13 of 15; the conclusion held
on better evidence (every name on every machine). Figures in code: the engine's
docstring quoted Step 2 three revisions out of date, gave the 調整 share as 24%
where it is 12%, and asserted a link between 調整 rows and regulation reading
that the data contradicts; `rank.py` carried typed-in purities up to 27 points
off. And `tool/README.md`, which carried its own copy of the Step 3 figures and
was read by nothing. All of it is now generated or checked, including the prose
comparison, since a comparison drifts as easily as a number.

**Two failures only a clean machine shows.** Running the test suite from a
fresh `git archive` of the repository — no data, no generated files — gave one
failure: `tool/run.py` loaded the mock portal's fixture at import, and the
fixture is generated and gitignored, so the test that checks the model stays
off crashed before it ran. That is the checkout a reviewer starts from, and the
README promised only skips. Separately, piping any script that prints Japanese
on Windows crashed on the ANSI code page; the tests hid it by setting
`PYTHONIOENCODING` themselves. Both are fixed, each with a test that runs in the
conditions that exposed it and a mutant proving the test fails without the fix.

**The brief's third Step 2 question had no answer.** "Are there different
handling patterns within the same process?" The report met it with a limitation
carried over from an earlier revision: 72 tied segments, not re-measured. Tying
a segment to the worklist row it processed, through a case ID seen inside it,
now works for 87% of segments, so the question could be answered rather than
deferred. Rows the portal flags for judgment were compared with routine rows on
duration, typing and regulation reading, within each process. Nothing survives
a correction for the twelve comparisons. That is reported as a null result with
its limit stated — with 19–43 flagged runs per process only a large difference
could have shown — and it sharpens one argument: the portal's flag, not a
measured difference in effort, is the evidence for leaving those rows to a
person. My first criterion for which column is a "variant" was too loose; it
counted department columns and a column of invoice references. It was tightened
to the definitions' handling mode, which the docstring had meant all along,
before any figure reached the report, and both versions are recorded.

**Step 3 was routing approvals by a regulation nobody on those screens reads.**
Every flagged rule in the tool named the same expense regulation, chosen when
the first screen was built and carried to the rest. Step 2 had already measured
which document each screen's operators consult, and on two of the three
payroll-type screens it is not that one: invoice operators check a supplier
list, inventory operators open no regulation. So 57 approvals were routed by a
threshold table no evidence connects to them — the optimistic assumption the
brief warns about, sitting inside the headline figure. They now go to a person,
the headline falls from 93% to 87%, and a check ties every routing rule to the
document its screen's operators actually consult. Following the same evidence
one step further: on five screens the operators consult a procedure in most
runs, and there the tool's 確認済 records a check it did not make. The report
now splits the automated rows on that line (277 there, 581 elsewhere) and
carries it as risk R9. Its mitigation — enable the low-judgment screens first,
and have automated notes say they are automated — is proposed rather than
built, because it changes Japanese text written into the client's records, and
that wording should come from someone who reads it.

**Configuration that was a transcript of the sample.** The tool's definitions
are meant to hold what differs between screens, and four of them held the sample
itself: every department, and on the payment screen every one of 48 invoice
references, as its own routing key with its own copy of the note. They routed
nothing — every key went the same way — but the next invoice would have fallen
through to a different note, and one file was 172 lines of data dressed as
configuration. One rule with the value filled in replaces each list, and a
comparison over all 252 rows of those screens shows every note and mode
unchanged. Smaller finds in the same pass: four recon scripts still pointed at
this machine's data directory, the README's command blocks worked only if each
was pasted into a fresh shell, and "exactly one confirm press per execution"
was true only of the executions that have one.

**The baseline was handicapped, in my favour.** The idle-gap baseline read its
pauses from the logging agent's "time since the last event", and the agent takes
a screenshot right after most operator actions. The baselines drop those
screenshot rows, but the gap field still counted them, so every pause was
measured from the last screenshot rather than the last thing the operator did.
Measured as its own definition says, the 3 s baseline scores 0.365 at 5 s, not
0.316 — and it becomes, as its label claimed, the best threshold, which under
the old field it had not been. Nothing about the delivered segmenter changed;
its lead over the baseline shrank by 0.049, and the report now says so. The
audits had checked the scorer, the random control and the delivered pipeline;
none had checked that the comparator was measuring what it said it measured.

**The random control was fair to one metric and not the other.** After the
baseline turned out to be handicapped, the other comparator got the same
question. The random segmenter behind the bias audit matched the delivered
segment count, which is what boundary F1 needs, but its segments were half as
long — and the coverage figure the report set against it rewards length.
Shuffling the delivered segments' own durations instead leaves boundary F1 where
it was (0.261 against 0.267) and raises chance coverage from 17.8% to 43.0%. The
delivered 83.0% still clears it, by a margin less than half as wide as the
report had implied. The lesson generalises past this project: a null has to be
matched on whatever the metric can reward, and that differs from metric to
metric even within one audit. The same pass found leave-one-machine-out holding out seven of dataset A's
eight machines, having skipped a 2-session one without saying so. Held out,
that machine scores 0.854, above the mean, so the exclusion had not flattered
the result; it was still a choice nobody had stated. Every machine is now held
out (0.759 ± 0.117).

**A robustness claim measured on the one metric that could not move.** The
sensitivity paragraph showed that the expansion cap leaves boundary F1 unchanged
across a fifteen-fold range, and drew from it that almost nothing is fitted. But
the cap was never meant to move boundaries; it decides how much of each gap is
claimed as work, and across the same range the idle share runs from 12.5% to
4.2%. So there is one fitted parameter, set on dataset A, and it is the one that
produces a figure the report had held up as never optimised for. Neither
sentence was false about what it measured; each was chosen by the metric that
flattered it. Both now say what the cap does, with the figures, checked.

**A robustness check that counted one formula twice.** The ranking was said to
survive six weightings. Two of them were the same formula written two ways, so
it was five — and the formula they duplicated was itself wrong, multiplying the
share of time by transfers per run and so counting how long a run takes twice.
Corrected, the conclusion holds (the chosen process is in the top three under
every distinct weighting), but a sentence the scope argument leaned on does not:
the top three processes are not all one screen, only the top two. That is the
third comparison this week that was right about its headline and wrong in a
supporting detail, and each time the detail was the part nobody had checked
because it looked like arithmetic.

**The summary still told the story of the first design.** Its first finding —
case IDs on screen make case-identity reconstruction "the only method that can
separate" two runs of the same process — was the plan on Day 2, and it was
what the first segmenter did. The delivered segmenter does not work that way:
the two clicks do the separating, and section 7 shows boundaries are no worse
without case anchors at all. The report had recorded that reversal in its own
ablation and never carried it back to the summary, which is the part a reviewer
reads first. The finding now says what the pipeline actually uses case identity
for, and how often an ID is on screen while its own execution is under way,
not merely somewhere in the session.

**A near-miss in the same pass.** The report listed 10% of dataset A's
screenshots as missing. A first check pooled every screenshot folder in the
dataset, found all 34,580 names, and was on its way to deleting the limitation
as false. Checking only the folder each event names reproduced the 10%. Neither
was right: resolved within each session, every image is on disk, and 3,567 sit
under a second name for the same chunk. Two checks, each confident, disagreed
because each asked a slightly different question — which is the case for asking
the question the claim actually makes.

**A convergence pass, and what "every figure" left out.** Asked to keep going
until a pass finds nothing, I changed the method. Rereading for problems finds
whatever the reader happens to notice, and there is always something. Instead I
listed every number in the three documents a reviewer reads and removed the
ones the checker re-derives. What remained was finite - about fifty numbers on
forty lines - and most of it was history or parameters. Seven were live figures
from the summary and the results table, and all seven held.

The two defects that pass found were in the checking, not the documents. The
checker matched timings exactly, and a second run on the same machine already
broke that (p95 149, then 153 ms). And the run file it reads is whatever ran
last: my own demonstration had left 20 timeouts in it, and an audit script
counted 838 automated rows without saying where the other 20 had gone. It is the
screenshot lesson again: a check has to say which run it is about. The same
pass found three problems in the documents themselves; they are the next commit.

**Three errors the number scan could not see.** The scan of every number finds
figures that are wrong; it cannot find sentences that are. Reading the report as
a reviewer would - the heading, then the table under it - found the one I would
least like a reviewer to find: a section headed "Ranking" whose table was not the
ranking. It was ordered by minutes and cut to eight rows, a leftover from before
the priority was fixed. The check that compared its rows with the generated
analysis passed, because it only looked at the rows that were there. The other
two were a stale story and a slip. "Out of scope entirely" was true of the
three-screen tool and false of the twelve-screen one. And 135x for 23,310 / 170
had sat in six places since the first day, because nobody divides.

The fix made a flaw of its own, which is the cascade I was asked to avoid.
Printing the formula above the table invites a reviewer to recompute it, and
from the rounded figures two neighbouring pairs swap. I found this by doing the
recomputation before committing. The order is right, and the table now says it
is computed before rounding. The cheap guard was to do, before committing, the
first thing a reader would do with the new sentence.

**A verification claim wider than the verification.** Reading the ranking table
I had just completed, I asked where its new process names came from. Three came
from document names the Japanese-reading reviewer never saw. The report said
every Japanese reading in it was verified. The reviewer had checked twelve, and
my own log said so. The claim was true of the report the reviewer read, and it
widened quietly as the report grew. It now says which twelve. The rest are
listed for the same reviewer as Part D of `docs/CHECK_THIS.md`, and they stay
marked unverified until someone who reads Japanese has seen them.

**A docstring that explained a number with the wrong set.** A scan of the
numbers in the code's docstrings turned up 12.8% twice. In gold.py it is the
share of executions whose end is inferred. In segment_v3.py it is the share of
executions with no confirm press, and the docstring called those "resumed
phases". Two sets of nearly the same size had been merged, then named after a
third. Crossing the gold set's own fields took a minute, and it showed only 25
of the 258 are resumed phases. The report had never repeated the explanation,
which is the one reason this fix was cheap.

**The pointer in the first paragraph a reviewer reads.** A fresh read of the
report, top to bottom, found the summary's cross-reference for its strongest
recommendation pointing at the wrong section: "the evidence for that is in §5",
for evidence that sits in §4. A second pointer sent the reader to §6 for an API
check that §6 never mentions. Nothing checked pointers, so nothing could have
noticed. The checker now resolves all ten.

The first version of that check was itself broken, and the gate refused it. I
generated the table of patterns into the checker as raw strings of their own
`repr`, which doubled every backslash, so no pattern could match. My dry run had
tested the table in memory, not the code it wrote, and passed. The full run
reported all ten as missing. The corrected script executes the generated table
before writing it.

**The deep check, and the first flaw in what the tool does rather than what the
report says.** Asked to look in depth for major flaws, I stopped rereading the
documents and asked the data questions the documents had never asked. The first
question was whether the 984 rows were real. They were, every one on screen. The
38 IDs on screen but not modelled turned out not to be worklist rows. Some were
memos and detail panels. The rest were a capture of the data generator's own
task plan, `proc=P12 … variant=V2_renewal`, which gave the question away:
dataset B's row IDs carry a process code.

That code showed two processes sharing one HR screen. The tool routed both by
one expense regulation, and that regulation says nothing about pay. The report
had checked that operators consult the regulation. It had never checked that the
regulation covers what it was applied to.

The fix went wrong on its first attempt. The guard matched nothing in the real
regulation text, because Word puts paragraph marks after the title. A synthetic
test passed it. Checking the guard against the real capture before running the
tool caught it, and the test now uses the real layout.

**The routing the report was proudest of rested on a mislabelled capture.**
Section 4 argues that the regulation is a threshold table and therefore
arithmetic, and the tool's 37 routed rows were the proof. Chasing the 14 pay
adjustments showed the table came from the wrong document. The screen capture
logged under the window the HR operators open was the entertainment-expense
rules, and those rules never appear on the HR screen. The argument still holds:
where a regulation is a table, routing by it is arithmetic. But on this data no
screen's operators are seen consulting one, so the tool routes nothing, and the
honest headline fell from 87% to 83% in two commits.

Two decisions here were the user's, not mine. One was whether to apply the
report's own evidence rule strictly, which costs the headline 3 points. The
other was to leave the graded segments untouched, although one label merges
two processes. Both went the conservative way.

**A correction that stopped one step short.** On Day 6 NOTES recorded that
dataset B's `P4-07089771-012` is a worklist row id, not an employee id. The
report went on saying the case-ID prefix was meaningless on B, because the
verdict had been reached under the old reading and nothing sent me back to it.
The corrected reading implied the next question - what does a worklist row's
prefix mean? - and I did not ask it for five days. Asked now, it answers the
limitation the report had called unanswerable: dataset B's labels can be
checked, and they hold up (V 0.966 on 645 segments). The lesson is plain. When
a premise changes, the conclusions built on it have to be walked forward too,
not just the sentence that stated it.

The same lesson applied to this fix within the hour. Section 8's new opening no
longer matched the text the cross-reference table anchors on, so section 1's
pointer to it could not be resolved. The checker refused the commit (411 of
412), and the table now anchors on the new opening.

**Named after the evidence, when the evidence was one kind of case.** Naming
processes by the regulation open during them was the right move against route
names that repeat across systems. It also gave the labels an independent check.
But it answered the wrong question. A document tells you which kind of case is
on the desk, not which process the desk belongs to. The contract screen became
"contract_termination" because terminations send people to the termination
procedure most often, and new contracts, renewals and NDAs were never named at
all. The screen's own title was in the fixture from Day 6. Seeing it took the
simulator's task plan listing five kinds of contract under one process.

**The tense a change leaves behind.** Removing the routing took four commits of
figures with it, and the checker held every one of them to the run. What it
cannot hold is a sentence whose numbers are right and whose tense is wrong: R9
still offering to encode a rule "as the approval thresholds were", R5 stating a
risk that now begins only when a client names a regulation. Reading the report
against what the tool does, rather than against what it reports, is the only
pass that finds these, and it is worth doing once after every change that moves
behaviour rather than numbers.
