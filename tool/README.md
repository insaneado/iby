# Step 3 — worklist automation engine

```bash
python tool/extract_fixture.py     # rebuild the mock portal's data from the logs
python tool/run.py                 # run against all 12 screens; no model is called
python tool/regulations.py         # show the rules extracted from the 規程
```

## What it does

Processes the portal's pending-work list end to end: read the worklist, select
an unprocessed row, apply the governing rule, write the note, confirm, verify
the row changed state.

Measured over all **984 worklist rows across 12 screens**:

| outcome | rows | share |
|---|---:|---:|
| routine, templated note | 821 | 83% |
| flagged rows routed by regulation threshold | 23 | 2% |
| **fully automated** | **844** | **86%** |
| left for a human | 140 | 14% |
| failed | **0** | 0% |

Median 131 ms per row, p95 150 ms, 144 s wall clock for the full set.

The 140 rows left for a person are rows the portal itself flags as needing
judgment that no regulation in use settles: contract actions of 新規締結 or
解除, 種別 = 調整 rows on the invoice and inventory screens, and the HR screen's
overtime-allowance adjustments. A flagged row is routed by a threshold only
where the screen's own operators consult the regulation that sets it - on this
data, the HR expense screen alone - and only if that regulation names the row's
subject: its entertainment expenses are routed, its pay adjustments are not.
Earlier versions routed the invoice and inventory rows by the same regulation,
which their operators are not seen opening, and the pay adjustments by a
regulation that never mentions pay. Where no rule in use resolves a flagged
row, a person decides; that is the correct place for the boundary until the
client names the rule.

Of the 844 automated rows, 277 are on five screens whose operators
consult a procedure or regulation in most runs; there the tool performs the
steps and writes 確認済 without the consultation. See the report's R9.

## Why an engine and twelve definitions, not twelve scripts

The portal runs **12 worklist screens** across its three systems, built from
**5 schema archetypes**:

| archetype | screen-specific columns | screens | status flow |
|---|---|---:|---|
| `pi` | 区分 · 金額 · 種別 | 3 | 未処理 → 登録済み |
| `la` | 申請種別 · 期間・詳細 · 部署 | 3 | 処理待ち / 申請中 → 承認 |
| `si` | 申請種別 · 対象年月 · 詳細 | 3 | 処理待ち → 処理完了 |
| `ob` | 入社日 · 部署 · 照合項目数 | 2 | 照合中 → 完了 |
| `rt` | 項目 · 金額 | 1 | 未確認 → 完了 |

**A correction to an earlier claim.** This README previously said the table
contract was identical across the three systems. True for one screen across
systems; false across screens. They share a *shape* — id, party id, name, three
screen-specific columns, a status — but not a schema, and not even the same word
for "done". An engine that hard-codes one table finds only the screens matching
it, which is exactly what the first version did: it modelled 3 screens and 456
rows where the logs hold 12 and 984.

So the engine reads the column list, the pending and done values and the routing
column from the definition. `definitions/*.yaml` hold what differs; `engine.py`
holds what does not. Adding a thirteenth screen is a config file.

## Why the LLM is not in the runtime path

This was going to be a RAG feature. The evidence killed it, in two steps.

**First, the measurement.** Running the judgment step through Gemini:

| | deterministic | model |
|---|---:|---:|
| median latency per row | 170 ms | 23,310 ms (**137x**) |
| error rate | 0 / 456 (the rows then modelled) | 2 / 5 (timeouts) |
| output | states the facts | echoed the regulation's *filename* back |

**Second, the reason it was never needed.** Reading the captured regulation
content shows the "judgment" is a threshold table:

> 第２条（承認権限）1回あたり5万円未満：部門長承認。5万円以上：役員承認。10万円以上：社長承認。

Approval routing by amount is arithmetic. Arithmetic belongs in code — exact,
instant, free, auditable line by line against the regulation, and incapable of
inventing an approver. `regulations.py` parses those thresholds and
`route(107158)` returns 社長承認, which the run then writes as
`規程により社長承認へ回付`.

The model's one remaining job would be **offline**: proposing a rule table from
a regulation document, for a human to check before it ships. That job is
designed, not built — the three regulations with thresholds parse without a
model. `run.py` never calls a model unless started with `--llm-drafts`, which
reproduces the measurement above; a configured key on its own changes nothing.

Honest limit: **3 of 13 regulation documents contain machine-readable
thresholds.** The other 10 are procedural checklists. Extending coverage means
handling procedures, which is a different and harder problem, and is deferred.

## Failure behaviour

A definition that no longer matches the live portal stops its screen with
`DefinitionDrift` rather than reporting success:

| drift | detected by | time to surface |
|---|---|---:|
| a control renamed (note, confirm) | preflight, before any row is touched | 1.2 s |
| the worklist table renamed | table wait, converted to drift | 11.4 s |
| an unfamiliar status word | rows present, none pending, some unrecognised | 1.2 s |

The last case previously produced *"0 rows, 0 failed"* and exited cleanly. The
portal uses at least five different words for "pending" across its screens, so
this is the likeliest production failure there is, and reporting it as success
was the worst possible behaviour.

`run.py` isolates drift per screen — one stale definition stops itself and the
other eleven continue — and prints every drifted screen and warning in the run
summary. A screen where every row is already done is still a legitimate no-op,
so re-running the tool is safe.

## What the mock portal proves, and what it does not

The real portal runs on `127.0.0.1:5132-5134` on the operators' machines and is
not available here. `mock_portal/` is rebuilt from dataset B: element ids and
CSS selectors from `payload.element.css_selector`, the 5 table schemas and
984 real rows across 12 screens from `context.extracted_text`, note placeholders from
`browser_form_input.field.label`, the ports from `active_browser_tab.url`, and
the confirmation string `"<row id>: 登録確定しました"` from the captured screens.

**Proves:** the automation drives the real DOM contract end to end, and the
rule routing produces the regulation's approver for real amounts, on the screen
whose operators are seen using that regulation.

**Does not prove:** that the production portal behaves the same. Session
handling, server-side validation, pagination, concurrent edits and real latency
are all unobserved in the logs and therefore unimplemented here. Treat the 86%
as an upper bound established under favourable conditions.

## Files

| | |
|---|---|
| `engine.py` | the shared engine; the only place automation logic lives |
| `definitions/*.yaml` | per-screen configuration — columns, status words, routing, URL |
| `regulations.py` | extracts threshold rules from the captured 規程 text |
| `mock_portal/` | portal reconstruction + fixture builder |
| `run.py` | CLI and the run report |
| `../out/automation_run.json` | per-row outcome of the last run |
