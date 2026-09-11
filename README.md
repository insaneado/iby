# From Operation Logs to an Automation Proposal

Recovering business processes from raw PC operation logs, analysing them, and
building the automation with the best return.

**Start here:** [`report/REPORT.md`](report/REPORT.md) ([PDF](report/REPORT.pdf))
· Japanese summary: [`report/SUMMARY_JA.md`](report/SUMMARY_JA.md)

---

## Results

**Step 1 — recover units of work.** The logs record keystrokes and clicks and
nothing about what work is in progress. Process mining needs
*(case ID, activity, timestamp)*; this data has only timestamps. Recovering the
rest is the known problem of *event log correlation*.

Scored against dataset A's 2,009 ground-truth executions:

| | best baseline | delivered | ground truth |
|---|---:|---:|---:|
| boundary F1 @2s | 0.275 | **0.700** | 1.000 |
| boundary F1 @5s | 0.365 | **0.756** | 1.000 |
| WindowDiff *(lower better)* | 0.682 | **0.195** | 0.000 |
| V-measure *(label consistency)* | 0.135 | **0.719** | 1.000 |
| segments produced | 5,236 | **2,010** | 2,009 |

Held out on unseen operators: **0.759 ± 0.117**. A random segmenter with the
same segment count scores 0.267, so the metric discriminates by +0.489.

**Step 2 — analyse.** 664 executions, 173 minutes, 4 operators working across
three systems under shared logins. The portal's route names describe nothing;
the regulation document open during the work identifies it.

**Step 3 — automate.** A schema-driven engine covering all **12 portal worklist
screens**: 984 rows, **86% fully automated, zero failures**, 131 ms per row.

---

## Run it

Unzip `dataset_a` and `dataset_b` into `data/` (or point `config.local.json` at
them), then run everything from the repository root, in this order:

```bash
python src/build_index.py           # 790 MB of JSONL -> an 11 MB Parquet index
python src/run_dataset_b.py         # -> out/segments.jsonl   (the graded deliverable)
python src/analyze.py               # Step 2 profile, with self-checks
python src/rank.py                  # Step 2 automation ranking
python tool/extract_fixture.py      # rebuild the portal fixture from the logs
python tool/run.py                  # Step 3: drive all 12 screens end to end, no model
```

Reproduce the evaluation and the audits (the last two need the Step 3 run above):

```bash
python src/segment_v4.py                 # segmenter, scored against ground truth
python src/label.py                      # labeller, scored against ground truth
python src/baseline.py                   # the approaches a reasonable person tries first
python explore/metric_audit.py           # is the scorer itself biased?
python explore/overfit_audit.py          # strict protocol + leave-one-machine-out
python explore/label_vs_breadcrumb.py    # dataset B labels vs a signal the labeller cannot see
python explore/ablation.py               # which component earns its place; parameter sensitivity
python explore/handling_variants.py      # Step 2: are rows the portal flags handled differently?
python explore/automation_by_judgment.py # Step 3: what "fully automated" means, screen by screen
python explore/verify_report.py          # re-derives every figure the documents rest on (~20 min)
```

Check the claims directly — and check that each check can fail:

```bash
python tests/test_invariants.py     # 17 tests; the two that need the datasets skip without them
python tests/mutation_check.py      # breaks what each test guards; every test must then fail
```

Install the exact versions this was verified with:

```bash
pip install -r requirements.txt
python -m playwright install chromium   # Step 3 and the PDF build
```

---

## Layout

| | |
|---|---|
| `src/` | the pipeline — index, gold set, evaluation, case recovery, segmenter, labeller |
| `tests/` | the project's claims as assertions, and a mutation check that each assertion can fail |
| `tool/` | **Step 3**: the automation engine, 12 screen definitions, and a portal rebuilt from the logs |
| `out/segments.jsonl` | **Step 1 deliverable** — 664 segments, 15 sessions, 12 labels |
| `report/` | final report, Japanese summary, PDFs |
| `explore/` | the measurements and audits behind every claim |
| `docs/` | the task brief, the Japanese glossary and its verification |
| `data/`, `build/` | provided data and derived indexes (gitignored, reproducible) |

### Pipeline

```
events.jsonl ──> build_index ──> events.parquet
                                      │
              caseid ──────────────────┤ which case is in play
              segment_v4 ──────────────┤ bracket each unit: row click -> confirm click
              label ───────────────────┤ system + route, vocabulary discovered not typed
                                      ▼
                              out/segments.jsonl ──> analyze / rank ──> tool/
```

---

## Documents

| | |
|---|---|
| [`report/REPORT.md`](report/REPORT.md) | the final report — analysis, the automation choice, what remains manual, risks with evidence |
| [`RESULTS.md`](RESULTS.md) | every measurement, appended to and never rewritten, so the progression and the corrections are visible |
| [`WORKLOG.md`](WORKLOG.md) | what was tried, what failed, and how AI was used |
| [`NOTES.md`](NOTES.md) | running technical state |
| [`tool/README.md`](tool/README.md) | why an engine rather than scripts, and why the LLM is not in the runtime path |
| [`docs/CHECK_THIS.md`](docs/CHECK_THIS.md) | the Japanese readings the work depends on, and their verification |

## Three things worth knowing before reading further

**The scorer was built before the segmenter, and validated against itself.**
Ground truth scored against ground truth returns 1.000 on every metric. Without
that check the rest is unfalsifiable. Two later audits found real defects in it.

**A shortcut was found and deliberately rejected.** On dataset A the case-ID
prefix predicts the process family with 100% purity across all 15 families.
Shipping it would have scored spectacularly and failed silently on dataset B,
where the IDs are worklist rows. `label.py` uses the activity signature instead.

**The LLM was built, measured, and removed from the runtime path.** 137x slower
than the deterministic path with a 2-in-5 timeout rate — and the regulation it
was meant to interpret turned out to be a threshold table, which is arithmetic.
It now runs offline only, proposing rules for a human to approve.
