# From Operation Logs to an Automation Proposal

**Final report** · Repository: <https://github.com/insaneado/iby>

---

## Summary

Dataset B contains **173 minutes of back-office work: 664 executions across 15
sessions and 4 operators**, all on 2026-07-01. Recovering that required solving
the problem the raw logs pose — they record keystrokes and clicks, but nothing
that says which unit of work is in progress.

The three findings that drove everything else:

1. **The case identifier is recoverable from the screen.** 97.8% of ground-truth
   case IDs appear in captured screen text. This turns Step 1 from blind
   change-point detection into case-identity reconstruction — the only method
   that can separate two consecutive executions of the *same* process.
2. **Each unit of work is bracketed by two observable clicks.** Selecting a
   record opens it (1,780 clicks, 99.9% inside a gold execution, median relative
   position 0.13) and a confirm press closes it (1,751/1,751, position 0.89).
   Using both edges lifted boundary F1 from 0.450 to **0.752**, and at 2-second
   tolerance from 0.208 to **0.673**.
3. **One screen pattern carries 38.7% of all observed work**, in all three
   portal systems, with an identical table contract. That is what the automation
   targets, and why it is one engine with three definitions rather than three
   scripts.

The delivered tool covers **all 12 portal worklist screens — 984 rows, 93%
fully automated, zero failures**. The 7% left for a person are precisely the
rows the portal itself flags as needing judgment and for which no regulation
rule resolves.

The recommendation I would defend hardest is a negative one: **the LLM does not
belong in the runtime path**, and the evidence for that is in §5.

---

## 1. Step 1 — recovering units of work

### What the logs do and do not contain

Process mining needs an event log of *(case ID, activity, timestamp)*. The
provided data has timestamps only. Recovering the other two from an uncased
stream is the known problem of *event log correlation*.

### What did not work, and why I checked first

The obvious approach is to segment on pauses. I measured the gap distribution
before building it: **the median gap between consecutive ground-truth segments
is 0.0 seconds** — half of all true boundaries have no pause at all. Built
anyway as a baseline, it reached BF1@5s 0.314 and V-measure 0.063. There is no
threshold at which it works: at 2 s it emits 8,290 segments for 2,009 real ones;
at 10 s it misses 84% of boundaries.

A second baseline, splitting on every application switch, was also poor
(V = 0.135): operators switch applications constantly *within* one unit of work.

### The approach that did work

| stage | signal | why |
|---|---|---|
| **case identity** | most-repeated ID in a screen capture | opening a record repeats its ID across header, fields and breadcrumb; list rows show each once. 93.5% precision |
| **unit start** | click on a table cell (`td`) | selecting the record; 1,780 clicks, 99.9% inside a gold execution, median position 0.13 |
| **unit end** | click on an HTML `button` | the terminal action; 1,751/1,751 inside a gold segment, exactly one per segment, position 0.89 |
| **label** | portal system + route | 3 systems x 5 routes is exactly the 15 process families; V = 0.854 on gold segments |

### Results

Scored against dataset A's 2,009 ground-truth executions:

| | best baseline | **delivered (v4)** | ground truth |
|---|---:|---:|---:|
| boundary F1 @2s | 0.226 | **0.673** | 1.000 |
| **boundary F1 @5s** | 0.314 | **0.752** | 1.000 |
| boundary F1 @10s | 0.494 | **0.812** | 1.000 |
| WindowDiff (lower better) | 0.656 | **0.195** | 0.000 |
| V-measure (label consistency) | 0.135 | **0.719** | 1.000 |
| segments produced | 4,150 | **2,010** | 2,009 |
| idle time claimed | 41.5% | **6.6%** | 5.0% |

Two figures were never optimised for and are the ones I trust most: the segment
count lands within **0.05%** of ground truth (2,010 against 2,009), and claimed
idle time within 1.6 points.

### How honest this number is

- **The scorer was validated first.** Scoring ground truth against itself
  returns 1.000 on every metric. Without that check the rest is unfalsifiable.
- **Two audits found real defects.** The boundary metric originally derived
  boundaries from label changes, which made the boundary between two
  consecutive executions of the *same* process invisible — it was scoring 94% of
  boundaries and silently discarding exactly the hardest 6%. A second pass found
  the fix had reached boundary F1 but not WindowDiff.
- **Parameter tuning leaked.** Parameters were swept over all 63 sessions with a
  dev/test split reported afterwards. Redone strictly, the honest protocol
  scored *higher* on test — the leak was real and was not inflating the result.
  Held out on the final pipeline: dev 0.744, **test 0.760**.
- **Generalisation was tested by holding out whole operators**, not random
  sessions: **BF1@5s 0.739, sd 0.127** across seven held-out machines.
- **The evaluator was itself audited for bias**, since I chose the tolerances,
  the binning and the gold construction. A random segmenter with the same
  segment count scores BF1@5s 0.258 and ARI 0.001 — the metric discriminates by
  **+0.494**. Shuffling labels while keeping boundaries collapses V-measure to
  0.029, so the label score is not leaking from the segmentation. And a
  parameter-free check agrees independently: the best-matching predicted segment
  covers ≥80% of a ground-truth execution **83.0%** of the time, median coverage
  **97.5%**, against 16.9% and 38.2% for random.

Two things that audit changed. **BF1@5s has a floor near 0.26, not 0** — so the
"best baseline" at 0.314 was barely above chance and is a weaker comparator than
it appeared. And it surfaced a weakness the headline was under-stating: only
35.6% of ground-truth executions overlapped exactly one predicted segment. That
was a real defect, and fixing it is what produced v4: the audit showed the ends
were right and the starts approximate, so the opening click was brought in as
the other bracket. **The figure is now 76.8%**, with median coverage 97.5%
against a random control of 38%.

### Where it fails, precisely

One held-out machine scores **0.444** against 0.72–0.82 for the other six. It is
not a tuning artefact: **LAPTOP-R36BQBTE has zero L3 events across all seven of
its sessions** — the browser extension never connected, so the route signal does
not exist there. A fallback that recovers the route from the L2 accessibility
layer limits the damage but does not remove it.

That gives the single most useful number in this report for planning purposes:
**expect BF1@5s ≈ 0.74 ± 0.13 on an unseen operator, falling to ≈ 0.44 wherever
L3 capture is missing.**

The residual limit is the ~23% of executions that still do not map cleanly to a
single segment, mostly where a unit has no opening click and the start must be
inferred. Screen text is captured only every ~7.7 s, so case identity between
observations is interpolated rather than seen.

**Deliverable:** `out/segments.jsonl` — 664 segments, 15 sessions, 12 labels.

---

## 2. Step 2 — what the work is

### Scale and people

**664 executions, 173 minutes, 15 sessions, 4 operators.**

Three sources disagreed on headcount and had to be reconciled: 4 `username_hash`
values, 4 machine IDs (strictly 1:1), but only 3 operator names on screen. The
names are **not** operators — all three appear in every session, and each maps to
one portal system at 97–100% consistency. They are **shared per-system logins**.
So: 4 people, working across three systems under shared accounts. That last part
is a governance finding, not trivia (§6).

### The route names are misleading

The portal is one SPA deployed three times, so route names repeat and describe
nothing. The regulation document open during the work identifies it:

| segment label | document consulted | what the work is |
|---|---|---|
| `ops__leave-applications` | keiyaku_kaijo_tetsuzuki | contract termination |
| `fin__leave-applications` | settai_keihi_kitei | entertainment expense approval |
| `fin__payroll-items` | getsujitsu_teigaku_torihikisaki_ichiran | recurring supplier payment |
| `fin__resident-tax` | shinkuitorihikisaki_touroku_tetsuzuki | new supplier registration |
| `hr__onboarding` | nyusha_checklist_shinsotsu_batch | new-graduate onboarding |
| `ops__social-insurance` | kanrisya_kengen_shinsei_tetsuzuki | admin privilege request |

This doubles as **independent validation of Step 1's labels**: the pipeline never
reads document names, yet segments sharing a label consult the same document at
**79% weighted purity**.

*(All Japanese readings in this report were verified by a Japanese-reading
reviewer on 2026-09-10 — see `docs/CHECK_THIS.md`.)*

### Ranking, and why it is ranked this way

Two measurable quantities in tension:

- **Mechanical load** — clipboard events and application switches per run. What
  automation removes.
- **Judgment load** — share of runs with a regulation document open. What it
  does not.

High volume with high judgment is a poor first target however expensive it
looks, because the residue is what costs the time.

| process | n | min | share | median | mech | judgment |
|---|---:|---:|---:|---:|---:|---:|
| payroll_item_maintenance | 115 | 24.5 | 14.0% | 11 s | 2.3 | 11% |
| recurring_supplier_payment | 74 | 22.8 | 13.1% | 15 s | 3.5 | 55% |
| contract_termination | 65 | 22.0 | 12.6% | 18 s | 6.3 | 79% |
| new_grad_onboarding | 59 | 20.2 | 11.5% | 19 s | 6.3 | 83% |
| inventory_payroll_items | 65 | 15.1 | 8.6% | 11 s | 3.7 | 6% |
| new_supplier_registration | 67 | 13.8 | 7.9% | 11 s | 1.9 | 22% |

A priority formula is easy to make say what you want, so the ranking was scored
under **six different weightings**. Only **payroll_item_maintenance** appears in
the top three under all six. Four processes appear exactly once, which makes
them artefacts of a particular formula rather than findings.

### The result that set the scope

Aggregating by portal **screen** instead of by system:

| screen | executions | minutes | share | systems | judgment |
|---|---:|---:|---:|---:|---:|
| **payroll-items** | **263** | **58.9** | **38.7%** | **3** | **24%** |
| leave-applications | 151 | 36.6 | 24.0% | 3 | 48% |
| onboarding | 95 | 26.0 | 17.0% | 2 | 72% |
| social-insurance | 85 | 16.8 | 11.0% | 3 | 23% |
| resident-tax | 73 | 14.1 | 9.2% | 1 | 22% |

**The three top-ranked processes are the same screen in three deployments.** One
pattern, 36% of all work, second-lowest judgment load. That is the target.

---

## 3. Step 3 — what I built

A **shared worklist automation engine** driven by a per-system definition file,
implemented for all three systems.

```
tool/engine.py              the automation logic - one copy
tool/definitions/*.yaml     what differs per system: URL, regulation, wording
tool/regulations.py         extracts decision rules from the 規程 text
tool/mock_portal/           the portal, reconstructed from the logs
```

### Measured result — all 984 rows across 12 screens

| outcome | rows | share |
|---|---:|---:|
| routine, templated note | 821 | 83% |
| flagged rows routed by regulation threshold | 94 | 10% |
| **fully automated** | **915** | **93%** |
| left for a person | 69 | 7% |
| **failed** | **0** | **0%** |

Median 133 ms per row, p95 186 ms, 166 s for the full set.

**The scope grew after a defect was found.** The first build modelled 3 screens
and 456 rows, because the fixture extractor kept only the first breadcrumb per
system and hard-coded the payroll column list — so it silently found only the
screens whose table matched. Reading the printed header instead of assuming it
exposed **12 screens, 984 rows and 5 distinct schema archetypes**. The earlier
claim that the three systems share an identical table contract was true across
systems for one screen, and false across screens.

### Why this process and this scope

**Why this process:** it is the only candidate that survived all six ranking
weightings, and its screen pattern accounts for 38.7% of observed work.

**Why this scope:** the brief notes that breadth-versus-depth is itself the ROI
question. The deciding evidence is that all three systems share an *identical
table contract* — same seven columns, same element ids, differing only in
content (`E2001` vs `BATCH-W2`, yen vs an em dash). Three bespoke scripts would
encode that structure three times and triple the maintenance for no extra
coverage. One engine plus three ~30-line definitions covers 36% of the work.

**What I deferred:** the 10 of 13 regulation documents that carry no
machine-readable thresholds. They are procedural checklists, and handling them
means solving procedure-following rather than rule lookup — a different and
harder problem. Rows governed by those still reach a person.

---

## 4. Why this implementation form, and what I rejected

| option | why not |
|---|---|
| **RPA tool** (UiPath, Power Automate) | Would work. Rejected on operational grounds: the client already captures DOM selectors, so a code path is more testable, diffable and reviewable than a recorded flow — and the per-system difference is data, which suits a config file rather than three recorded macros. |
| **An LLM agent driving the UI** | Measured and rejected. See below. |
| **API integration** | Preferable if it exists, but nothing in the logs evidences an API. Proposing one would be an assumption, and the brief warns against exactly that. Flagged as the first thing to check in a real engagement (§6). |
| **Three separate scripts** | Rejected on the identical-table-contract evidence above. |
| **Deterministic engine + config** | **Chosen.** |

### The LLM decision, in detail

This was designed as a RAG feature: read the 規程, decide the handling. Two pieces
of evidence removed it.

**Measured performance.** Running the judgment step through Gemini:

| | deterministic | model |
|---|---:|---:|
| median latency per row | 170 ms | 23,310 ms (**135x**) |
| errors | 0 / 456 | 2 / 5 (timeouts) |
| output quality | states the facts | echoed the regulation's *filename* back |

**And then the reason it was never needed.** The captured regulation text is a
threshold table, not a judgment:

> 第２条（承認権限）1回あたり5万円未満：部門長承認。5万円以上：役員承認。10万円以上：社長承認。
>
> *Article 2 (Approval authority). Under ¥50,000 → department head; ¥50,000 and
> over → executive; ¥100,000 and over → president.*

Approval routing by amount is **arithmetic**. Arithmetic belongs in code: exact,
instant, free, auditable line by line against the regulation, and incapable of
inventing an approver. `regulations.py` parses those thresholds;
`route(107158)` returns 社長承認; the tool writes
`規程により社長承認へ回付`.

**The model keeps exactly one job, and it runs offline:** proposing a rule table
from a regulation document for a human to check before it ships. The expensive,
unreliable, unauditable component runs *once under supervision* rather than on
every transaction. The tool runs identically with no model configured.

I would defend this as the correct answer rather than a compromise. An LLM in
this path would have been slower, less reliable, more expensive, unauditable
against the regulation it is supposed to implement — and would have looked more
impressive.

---

## 5. What manual work remains, and realistic impact

### Remains, by construction

- **26 of 456 rows (6%)** — inventory adjustments whose 金額 is an em dash. With
  no amount, the threshold table says nothing. Correct boundary, not a gap.
- **The other 10 of 13 regulation documents** carry no machine-readable
  thresholds; they are procedural checklists. Processes governed by those are
  out of scope entirely.
- **Exception handling.** Nothing in the logs shows what operators do when a
  record is malformed or a system rejects a submission, so the tool has no
  designed behaviour for it beyond failing loudly.
- **Review of the automated output.** At least during rollout, a person should
  sample what the tool wrote.

### Impact, stated carefully

The brief states the recordings were made in a test environment with compressed
waiting times, so **absolute durations here cannot be converted into hours
saved, and I will not do so.** What the evidence supports is relative:

- Every segment in `segments.jsonl` is portal work, and the tool now covers
  **all 12 portal worklist screens**.
- Across them, **93% of rows** were handled end to end without a person.
- So the defensible claim is that the tool addresses **the portal component of
  the observed workload, at 93% coverage within it** — under favourable
  conditions (§6).

What it does *not* support: any statement of hours or money saved. Producing one
would require production timings the client has and I do not.

---

## 6. Risks, and the evidence for each

Every risk below is anchored to a measurement rather than to a worry.

| # | risk | evidence | mitigation |
|---|---|---|---|
| **R1** | **Telemetry gaps silently degrade accuracy.** | One of seven held-out machines scored BF1@5s **0.444** vs 0.72–0.86. Cause: **zero L3 events across all 7 of its sessions** — the extension never connected. | Monitor L3 coverage per machine as a first-class health metric; refuse to report process figures for a machine below a coverage floor. The L2 accessibility fallback limits but does not remove the damage. |
| **R2** | **The mock portal is not the real portal.** | Session handling, server-side validation, pagination, concurrency and real latency are **unobserved in the logs** and therefore unimplemented. | Treat 94% as an upper bound under favourable conditions. First engagement task: run against a staging instance before any efficiency claim is repeated. |
| **R3** | **An approach validated on one department can fail silently on another.** | Three transfers failed during this project: the case-ID prefix (100% pure on A, meaningless on B), the anchor rule (fired 72 times in all of B), and the button naming (`btn-*-ok` matched **zero** rows in A). Each looked fine on internal statistics. | Never accept a transfer on internal statistics alone. Hold back one observable signal from the method and check against it — that is exactly what caught the first dataset B failure. |
| **R4** | **Automation runs under a shared account.** | Each portal system has one login shared by all four operators (97–100% name-to-system consistency). | No per-user audit trail exists today, so automated and human actions will be indistinguishable in the client's own logs. Needs a service account with a distinct identity before rollout, which is an access-control change, not a code change. |
| **R5** | **The regulation is the specification, and it changes.** | Thresholds are hard rules parsed from document text (`5万円未満：部門長承認`). A revised 規程 silently invalidates them. | Rules are extracted from the document rather than typed into code, so re-extraction is the update path. Version the rule table against the document; alert on drift; require human sign-off on each extraction. |
| **R6** | **Provider availability, if a model is ever added.** | The first live API call fell through **two 503s** before succeeding, and the default model had been retired for new keys mid-project. | Already mitigated by design: the model is off the runtime path, and the tool works with none configured. |
| **R7** | **Free-tier LLM data is used for provider training.** | Vendor terms. | `src/llm.py` refuses any prompt containing raw-log markers, so only derived material can leave the machine. Enforced in code, not promised in a document. |
| **R8** | **Boundary precision is structurally limited.** | BF1@2s = 0.286; screen text is captured every ~7.7 s. | Do not build anything requiring sub-5-second boundary accuracy. If needed, raise capture frequency — a collection change, not an algorithm change. |

---

## 7. How the time was spent

**A disclosure first: this was not seven calendar days.** The git history shows
**28 commits across two intensive days**, not a week. The brief asks how the
seven days were allocated, and the honest answer is that the work was compressed.
What follows is how the *effort* divided, which is the part that carries a
lesson.

| phase | work | why |
|---|---|---|
| **1** | Data profiling; 790 MB of JSONL → an 11 MB index | Nothing else was affordable to iterate on until this existed |
| **2** | **Evaluation harness before the segmenter**; baselines | The brief leaves "good enough" to my judgment, and that judgment is impossible without a scorer. It also killed the gap-based approach in an hour rather than a day |
| **3** | Case-ID recovery | Reframed the problem, though the final architecture barely uses it (see below) |
| **4** | v1 segmenter; LLM layer | BF1@5s 0.450. The LLM layer was premature |
| **5** | Signature labelling; **dataset B transfer failed**; two metric audits | The failure was the most valuable hour of the project |
| **6** | Terminator-driven segmenter; overfitting audit; Step 2 | BF1@5s 0.450 → 0.722 |
| **7** | Step 3 engine, three definitions, mock portal | 94% automated, zero failures |
| **8** | Report; **evaluator bias audit**, which exposed a defect and produced v4 | BF1@2s 0.286 → **0.673** |

**The allocation I would defend:** roughly a third of the effort went to
measurement rather than building — the harness, four audits, the held-out
protocol, the transfer checks. That is a high proportion and it paid for itself
repeatedly. The metric defect would have invalidated every subsequent number.
The dataset B transfer failure was invisible on every internal statistic. The
evaluator audit, run only because the approach was challenged, produced the
single largest accuracy gain in the project.

### What the final ablation says about that allocation

Removing each component and re-scoring:

| configuration | BF1@2s | V | ARI |
|---|---:|---:|---:|
| shipped | 0.673 | 0.684 | 0.667 |
| without case anchors entirely | **0.696** | 0.693 | 0.584 |
| ends only, no opening click | 0.286 | 0.518 | 0.490 |
| labels from case prefix | 0.673 | 0.471 | 0.385 |
| one label for everything | 0.673 | 0.011 | −0.001 |

Two uncomfortable readings, both worth stating.

**Case-ID recovery contributes nothing to boundary accuracy.** Boundaries are
marginally *better* without it. It earns its place only by enabling the fallback
that recovers 260 segments without an opening click — which shows in ARI
(0.667 vs 0.584) — and by supplying the case field used to validate dataset B.
A day of work that the final architecture largely routed around.

**The whole boundary gain is two clicks.** Everything else — the anchors, the
snapping, the tuned windows — is close to inert. That is the honest description
of where the accuracy comes from, and it is also why the result is robust:
`expand_gap_s` from 20 to 300, `max_unit_s` from 100 to 600, `min_unit_s` from 1
to 10 and the anchor threshold from 2 to 4 all leave BF1@2s unchanged at 0.673.
**There is almost nothing here that could be overfitted, because almost nothing
is fitted.**

**The phase I would remove:** the LLM layer, built well before anything needed
it, on an assumption that the task wanted one. The eventual conclusion was that
it should not be in the runtime path at all. That effort belonged in Step 2.

## 8. Honest limitations

- **Dataset B has no ground truth**, so its accuracy is not measured, only
  inferred from dataset A performance and held-out proxy checks. Two such
  checks: 149 completion memos never read by the pipeline land at median
  relative position **0.78** within predicted segments (0.35 for the version
  that was wrong); and labels agree with the portal breadcrumb — an L1 signal
  the labeller cannot see — at **V = 0.948** where a contemporaneous breadcrumb
  exists, on 31 segments. Measured against breadcrumbs captured at any point in
  the segment the figure falls to 0.254, because screen text is captured only
  every ~7.7 s and most references are stale by the time a segment ends.
- **Variant detection is weak on dataset B.** The 種別 column carries
  定常/調整, but only 72 of 668 segments can currently be tied to one, and their
  durations barely differ. Reported as weakly evidenced rather than as a finding.
- **10% of dataset A screenshots are missing** from the distribution provided.
  Not pursued: dataset B is complete and screen text is available as text.
- **"36% of work at 94% coverage" describes 175 observed minutes on one day
  with four operators.** It is a measurement of this sample, not an estimate of
  the client's operation.

## What I would do next, in order

1. Run the engine against a staging instance of the real portal (R2).
2. Check whether an API exists behind the portal. If it does, most of this tool
   becomes unnecessary, and that is a good outcome.
3. Instrument L3 coverage per machine as a health metric (R1).
4. Extend to `leave-applications` — 25.5% of work, but needs the
   procedure-following problem solved first.
