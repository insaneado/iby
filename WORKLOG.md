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
