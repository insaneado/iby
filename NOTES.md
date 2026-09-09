# Technical notes

Running state. Findings that shape the approach, kept here so they do not have
to be re-derived.

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

## Key finding — case IDs are recoverable

All 32 ground-truth `case_id` values of the first A session appear **verbatim**
in the raw event stream (mostly `keystroke` payloads — the worker types them —
plus window titles and `extracted_text`).

In B, one naive regex finds 212 distinct IDs over ~920 events. Other formats
exist (e.g. `P4-07089771-012`).

Therefore **Step 1 is not blind change-point detection.** It is: recover the
case identifier in play at each moment; a segment is a maximal stretch working
on one (case, process) pair. This is what separates two *consecutive executions
of the same process* — the case that pure gap/app-switch heuristics always miss.

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

## Conventions

- Never read raw JSONL after indexing — always `build/events.parquet`.
- Scripts print at most ~80 lines of aggregates; detail goes to files.
- `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` required (Japanese text, cp1252 console).
- Keep paths short — the Windows 260-character limit already broke one
  extraction attempt.
