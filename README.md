# From Operation Logs to an Automation Proposal

Intern selection task — recover business processes from raw PC operation logs,
analyse them, and build the automation with the best ROI.

## Layout

```
src/          pipeline code
  common.py       paths + loaders
  build_index.py  raw JSONL -> compact Parquet index
out/          deliverables (segments.jsonl)
report/       final report
explore/      throwaway recon scripts (kept for the record)
data/         provided datasets (gitignored, 3.8 GB)
build/        derived indexes (gitignored, reproducible)
```

## Setup

Unzip `dataset_a` and `dataset_b` into `data/`, then:

```bash
cd src && python build_index.py
```

Builds `build/events.parquet` (182,483 events x 35 cols, 11 MB) and
`build/extracted_text.parquet` (8,210 screen-text captures).

Requires: pandas, pyarrow, numpy, scikit-learn.

## Documents

- `NOTES.md` — running technical state and findings
- `WORKLOG.md` — daily log: what I tried, what failed, how I used AI
- `report/` — final report
