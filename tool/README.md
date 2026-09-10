# Step 3 — worklist automation engine

```bash
python tool/extract_fixture.py     # rebuild the mock portal's data from the logs
python tool/run.py --no-llm        # run against all three systems
python tool/regulations.py         # show the rules extracted from the 規程
```

## What it does

Processes the portal's pending-work list end to end: read the worklist, select
an unprocessed row, apply the governing rule, write the note, confirm, verify
the row changed state.

Measured over all **456 worklist rows** in the reconstructed portal:

| outcome | rows | share |
|---|---:|---:|
| routine (定常), templated note | 336 | 74% |
| adjustment (調整), routed by regulation threshold | 94 | 21% |
| **fully automated** | **430** | **94%** |
| left for a human | 26 | 6% |
| failed | **0** | 0% |

Median 151 ms per row, p95 224 ms, 89 s wall clock for the full set.

The 26 rows left for a person are not a residue of laziness: they are inventory
adjustments whose 金額 is an em dash. With no amount, the regulation's threshold
table says nothing, so there is nothing to apply. That is the correct place for
the boundary.

## Why an engine and three definitions, not three scripts

Step 2 found one screen pattern carrying **35.7% of all observed work** (254
executions, 62.4 min) present in all three systems — the three top-ranked
candidates were the same screen in three deployments. The table contract is
identical across them: same seven columns, same element ids, differing only in
content (`E2001` vs `BATCH-W2`, yen vs em dash). Encoding that three times
would triple the maintenance for no coverage.

`definitions/{hr,fin,ops}.yaml` hold what differs — URL, regulation, note
wording. `engine.py` holds what does not.

## Why the LLM is not in the runtime path

This was going to be a RAG feature. The evidence killed it, in two steps.

**First, the measurement.** Running the judgment step through Gemini:

| | deterministic | model |
|---|---:|---:|
| median latency per row | 170 ms | 23,310 ms (**135x**) |
| error rate | 0 / 456 | 2 / 5 (timeouts) |
| output | states the facts | echoed the regulation's *filename* back |

**Second, the reason it was never needed.** Reading the captured regulation
content shows the "judgment" is a threshold table:

> 第２条（承認権限）1回あたり5万円未満：部門長承認。5万円以上：役員承認。10万円以上：社長承認。

Approval routing by amount is arithmetic. Arithmetic belongs in code — exact,
instant, free, auditable line by line against the regulation, and incapable of
inventing an approver. `regulations.py` parses those thresholds and
`route(107158)` returns 社長承認, which the run then writes as
`規程により社長承認へ回付`.

The model keeps one job and it is **offline**: proposing a rule table from a
regulation document, for a human to check before it ships. The expensive,
unreliable, unauditable component runs once under supervision instead of on
every transaction. `run.py` works identically with no model configured.

Honest limit: **3 of 13 regulation documents contain machine-readable
thresholds.** The other 10 are procedural checklists. Extending coverage means
handling procedures, which is a different and harder problem, and is deferred.

## What the mock portal proves, and what it does not

The real portal runs on `127.0.0.1:5132-5134` on the operators' machines and is
not available here. `mock_portal/` is rebuilt from dataset B: element ids and
CSS selectors from `payload.element.css_selector`, the seven-column schema and
456 real rows from `context.extracted_text`, note placeholders from
`browser_form_input.field.label`, the ports from `active_browser_tab.url`, and
the confirmation string `"<row id>: 登録確定しました"` from the captured screens.

**Proves:** the automation drives the real DOM contract end to end, and the
rule routing produces correct approvers on real amounts.

**Does not prove:** that the production portal behaves the same. Session
handling, server-side validation, pagination, concurrent edits and real latency
are all unobserved in the logs and therefore unimplemented here. Treat the 94%
as an upper bound established under favourable conditions.

## Files

| | |
|---|---|
| `engine.py` | the shared engine; the only place automation logic lives |
| `definitions/*.yaml` | per-system configuration — what differs between deployments |
| `regulations.py` | extracts threshold rules from the captured 規程 text |
| `mock_portal/` | portal reconstruction + fixture builder |
| `run.py` | CLI and the run report |
| `../out/automation_run.json` | per-row outcome of the last run |
