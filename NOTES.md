# Technical notes

Running state. Findings that shape the approach, kept here so they do not have
to be re-derived.

## Framing: this is a process-mining problem

The recording agent in the logs is `procmine-desktop-agent.exe` / "ProcMine
Agent" — the company's product is a process mining and automation platform. That
is visible in the data itself, so the work is best expressed in process-mining
terms rather than generic ML ones.

> **Scope note.** An earlier version of this section justified several decisions
> by reference to the job description. That was a mistake: the JD is context
> about the company, not part of the task specification, and it was never
> attached to the brief. Requirements come from `docs/task/TASK_README.md` and
> `DATA_SCHEMA.md` only. Decisions that survive on the brief's own terms are
> kept; those that existed to demonstrate JD keywords are demoted — notably
> LLM-as-Judge, which the task never asks for and which is weaker evidence for
> dataset B than the deterministic proxy checks already planned.

Process mining requires an event log of **(case ID, activity, timestamp)**. The
provided data has timestamps only. Recovering the other two from an uncased
stream is the known problem of *event log correlation* / segmentation of
unlabeled event logs.

So Step 1 restated: **convert a raw UI event stream into a process-mining-ready
event log.** Step 2 then becomes standard process mining over that log —
variant analysis, frequency and performance analysis, bottleneck detection —
rather than ad-hoc counting.

This makes the case-ID finding below the *canonical* solution to the field's
central problem here, not an incidental trick.

### Consequences for the deliverable

Each of these is justified by a line in the brief, not by the job description.

1. **Measure before tuning.** "How far you push accuracy - and what you consider
   'good enough' - is left to your judgment." That judgment is not possible
   without a scorer, which is why the harness came before the segmenter.
2. **Step 3 = deterministic core, LLM only where judgment is real.** The brief
   lists an AI agent as one acceptable form among several, and says outright
   that sophistication is not rewarded. Navigation, form filling and data
   transfer should be deterministic: cheaper, auditable, and incapable of
   hallucinating on financial data. The 13 Word regulation documents workers
   consult mid-task are the one place a model earns its cost.
3. **Risks must carry evidence.** "We are looking at how well you can anticipate
   realistic risks from that limited information" and "including what evidence
   led you to anticipate each risk." So every risk in the report cites a
   measurement, not a worry.
4. **Validation of dataset B is deterministic first.** The 629 `btn-*-ok`
   confirm clicks and the completion memos are deliberately excluded from
   anchoring, so they are genuine held-out evidence. That beats a model grading
   its own labels.

Minor observation: the machine IDs in both datasets (CHAITANYA0BCF,
SIDDHIGUPTAB00B, NEELA9BAF, JAYESH, Marcos, MSI) look like the company's own
India-based team recording synthetic sessions. Consistent with the brief's
warning that in-operation waiting times are compressed — reinforces that
absolute durations are meaningless and only cross-process comparison is valid.

## Data shape

| | dataset_a | dataset_b |
|---|---|---|
| sessions | 63 | 15 |
| events | 162,006 | 20,477 |
| ground truth | yes | no |
| people (username_hash) | — | 4 |
| wall-clock | multiple days | 2026-07-01, 16:44–19:36 UTC |

**Dataset A processes:** 15 families (codes A–O), 3 domains — hr / finance / ops,
~2,009 executions. Median execution 24–74 s (test environment; compare
processes *relative to each other*, never in absolute terms).

Declared variants: `A,F,K` = std/exc; `B,G,L` = reg/adj; the other 9 have none.
This is the task's "different handling patterns within the same process",
already labelled — use it to validate variant detection.

## The applications are not as different as the README implies

The README says dataset B uses different applications. Partly true:

- **Same in both:** the three portal systems — HR人事給与システム,
  財務会計システム, 受発注在庫管理システム. Local SPAs on
  `127.0.0.1:5132/5133/5134`. Routes: `#/payroll-items`, `#/resident-tax`,
  `#/onboarding`, `#/leave-applications`, `#/social-insurance`, `#/dashboard`.
  The three "systems" share one SPA codebase — route names are identical across
  all three ports, so **(tab_title, route) together** identify a screen, not
  the route alone.
- **Different:** Chrome (A) -> Edge (B). B adds a large set of Word `.doc`
  regulation/procedure documents, Excel workbooks, Notepad memos.

Consequence: the approach transfers better than the brief suggests. Say so
honestly in the report rather than pretending otherwise.

## Key finding — case IDs are recoverable (Day 2, measured)

**Step 1 is not blind change-point detection.** It is: recover the case
identifier in play at each moment; a segment is a maximal stretch working on one
(case, process) pair. This is what separates two *consecutive executions of the
same process* — the case pure gap/app-switch heuristics always miss.

### Where the IDs actually live

Day 0 attributed them to `keystroke` payloads. **Wrong** — that probe grepped
whole JSON lines and the hits were in `context`. Measured properly over all
2,009 gt case IDs:

| source | recall |
|---|---|
| `context.extracted_text` | **97.8%** |
| `el_name` (clicked UI element) | 4.8% |
| `el_value` (focused field) | 1.7% |

They are read *off the screen*, not typed. No keystroke reconstruction needed.

### Visible is not active

Screen text is captured every ~7.7 s (p50), so a 32 s segment contains ~4
captures — enough resolution. But a portal list view shows many cases at once
(mean 4.2 distinct IDs per capture, max 61), so taking every visible ID gives
only **21.8%** in-window precision.

Discriminators, scored against 1,752 gt executions:

| rule | n | precision | exec-coverage |
|---|---:|---:|---:|
| any ID visible | 13,910 | 21.8% | — |
| first appearance in session | 1,714 | 28.2% | — |
| ID in focused field | 1,243 | 3.0% | — |
| dominant ID, repeat ≥ 2 | 2,991 | 75.2% | 70.9% |
| **dominant ID, repeat ≥ 3** | 2,075 | **93.5%** | 60.3% |
| dominant ID, repeat ≥ 4 | 1,146 | 98.0% | 46.2% |
| ID in clicked UI element | 82 | 100.0% | 4.6% |

Precision is the thing to buy: a wrong anchor drags a boundary *and* mislabels
everything between, while missing coverage is recoverable by interpolation.

### The A-tuned rule did not transfer — and the fix

`repeat >= 3` fired 72 times on all of dataset B. B's captures are half the
length (675 vs 1,382 chars) and IDs almost never repeat, because B's screen text
is mostly the worker's own Notepad completion memo
(`請求書照合完了。INV-2026-7345　金額：455,128円`), not a list view.

Generalised to **unambiguous by dominance *or* by uniqueness** — the sole
distinct ID in a capture ≤400 chars. On A that costs one point (92.5% precision,
60.7% coverage); on B it yields 818 anchors across all 15 sessions.

### Labelling: the shortcut that works on A and fails on B

On dataset A the case-ID prefix maps to the process family with **100% purity**
across all 15 families (INV→請求書承認, RT→住民税通知確認, LA→育児・産休申請確認,
SUP→仕入先連絡, BR→銀行勘定照合, EXP→経費精算承認, STK→在庫調整, SHP→出荷追跡,
ORD→受注処理, PI→給与備考・控除整備, BV→予算差異分析, SI→社保・年金補正対応,
OB→入社照合・手当確認, RET→返品処理, PM→支払処理).

**It does not transfer.** Dataset B's dominant prefixes are `P4`, `P10`, `P6`,
`P11` — employee/payroll record IDs of the form `P<n>-<8 digits>-012`, not
process-typed case IDs. Only `INV` behaves like A.

So labelling must come from the activity signature (portal system + route + open
Word document + app mix), with the prefix used only as corroboration. This was
predicted before it was measured — a case ID encoding its own process type is a
property of *this* synthetic data, not something a real deployment can assume —
and it is the clearest evidence in the project for why the pipeline needs a
mechanism that does not depend on the convenient shortcut.

### Bonus signals found in B's screen text

- Clicked list rows carry label and case together: `請求書承認 INV-2026-7344`.
- Dashboards expose operator identity and role: `佐藤 直樹 · 経理マネージャー`
  (Sato Naoki, Accounting Manager) — this answers Step 2's "how many people
  are involved" directly, rather than by inferring from machine IDs.

## Portal structure (dataset B)

Five screens, each with a note textarea and a confirm button, clean ID prefixes:

| prefix | screen | note inputs | OK clicks |
|---|---|---|---|
| `pi-` | payroll-items | 233 | 240 |
| `la-` | leave-applications | 146 | 146 |
| `ob-` | onboarding | 89 | 92 |
| `si-` | social-insurance | 82 | 82 |
| `rt-` | resident-tax | 69 | 69 |

**629 `btn-*-ok` clicks total in B** — candidate work-unit completion anchors.

## Signal inventory

Strong:

- `browser_click` -> `element.css_selector` / `xpath` 100% populated, `id` 65%
- `browser_form_input` -> `field.id/label/css_selector/xpath` 100% populated
- `keystroke` -> `target_field.name` 87%, `target_field.value` 43%,
  `character` 86%
- `mouse_click` -> `target_element.name` 98% (Japanese UI labels; the
  `DataItem: <entity>` form reveals the record being worked on)
- Word document name in `window_title` — near-perfect process label in B
- `screenshot_smart.trigger_reason`: on_browser_click / post_app_switch /
  on_scroll / on_paste / on_keystroke / on_navigation

Weak or unusable:

- **Idle gaps.** p50 = 23 ms, p95 = 2.0 s, p99 = 5.3 s; only 22 gaps over 10 s
  in all of B. Do not build boundaries on idle time alone.
- **`clipboard_change` carries no content in B** — only `content_type`,
  `formats_available`, `text_length`. Copy/paste linkage must be inferred.
- `text_input_complete` — the README warns it is unreliable; only 77 events in B.

## Ground-truth alignment caveat

For **27% of dataset A ground-truth process starts there is no event at all
within ±2 s**. GT timestamps are not tightly aligned to the event stream. Score
with a tolerance window (±2–5 s) plus a segmentation metric (WindowDiff / Pk);
exact-boundary matching would badly understate real accuracy.

## Data source and completeness

Two copies of the data existed; they are **not** equivalent. Google Drive splits
large folder downloads into numbered parts, and the first copy (from
`dataset_a-...-1-001.zip`) was missing part 002.

| | Downloads copy | Desktop copy (**in use**) |
|---|---|---|
| dataset_a `events.jsonl` | 116 chunks, 735.7 MB | **117 chunks, 738.9 MB** |
| dataset_a screenshots | 6,959 (20%) | **34,580 → 89.7% present** |
| dataset_b events | 20 chunks, 86.1 MB | identical |
| dataset_b screenshots | 4,746 (100%) | identical |

Every shared chunk is byte-identical; the Desktop copy is a strict superset.
The one extra chunk is
`dataset_a/ses_20260701-072435-CHAITANYA0BCF/chunk_20260701-0700-CHAITANYA0BCF`
(3.22 MB, 762 events).

**Lesson worth keeping:** the first extraction looked complete — 63 and 15
sessions, all 63 `gt.jsonl`, and an event count (162,006) that matched the
brief's stated "~162,000". It was still missing a chunk. Matching a rounded
figure quoted in a spec is not verification. What actually caught it was
cross-checking `payload.file_reference` against the filesystem: DATA_SCHEMA
promises at most one missing image across the whole distribution, we measured
27,433 missing, and a contradiction that large has to be a collection artefact
rather than a property of the data.

`src/common.py` resolves the data root from `config.local.json` (gitignored) so
the datasets stay where they were unpacked rather than being copied around.

Residual: ~10% of dataset A screenshots are still absent. Not pursued —
dataset B is at 100%, dataset A is used only for scoring against timestamps,
and screen text is available directly via `context.extracted_text` (8,239
captures indexed; DATA_SCHEMA confirms OCR is not required).

## Conventions

- Never read raw JSONL after indexing — always `build/events.parquet`.
- Scripts print at most ~80 lines of aggregates; detail goes to files.
- `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` required (Japanese text, cp1252 console).
- Keep paths short — the Windows 260-character limit already broke one
  extraction attempt.
