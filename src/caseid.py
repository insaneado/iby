"""Recover the case identifier in play at each moment.

Process mining needs an event log of (case ID, activity, timestamp). The
provided data has timestamps only; this module recovers the case dimension.

Why screen text, and why "dominant"
-----------------------------------
Measured on dataset A (see explore/caseid_*.py):

* 97.8% of ground-truth case IDs appear in `context.extracted_text`. They are
  read off the screen, not typed - keystroke reconstruction is unnecessary.
* But "visible" is not "active". A portal list view shows many cases at once
  (mean 4.2 distinct IDs per capture, max 61), so taking every visible ID gives
  only 21.8% in-window precision.
* The discriminator is repetition *within one capture*: opening a case's detail
  view repeats its ID across header, fields and breadcrumb, while list rows
  show each ID once.

That yields a precision/coverage frontier, measured against 1,752 gt executions:

    rule                     precision   exec-coverage
    dominant, count >= 1        72.5%        71.1%
    dominant, count >= 2        75.2%        70.9%
    dominant, count >= 3        93.5%        60.3%     <- chosen
    dominant, count >= 4        98.0%        46.2%
    clicked UI element         100.0%         4.6%

`count >= 3` is the knee. Precision is what matters for an anchor - a wrong
anchor drags a boundary to the wrong place and mislabels everything between -
whereas missing coverage is recoverable downstream by interpolation. Clicked
elements are added as extra anchors: only 82 of them, but perfectly precise.
"""
from __future__ import annotations
import collections
import re
from functools import lru_cache

import pandas as pd

from common import load_index, BUILD

# Deliberately broad: dataset B carries formats dataset A does not
# (INV-2026-8002, P10-07010448-012). Constraining to A's shapes did not transfer.
ID_RE = re.compile(r"\b[A-Z]{1,6}\d*-\d{2,10}-\d{1,6}\b")

# A clicked list row often carries the process name and the case together,
# e.g. "請求書承認 INV-2026-7344" - a label and an anchor in one event.
LABELLED_ROW = re.compile(r"^\s*(?P<label>\D+?)\s+(?P<case>[A-Z]{1,6}\d*-\d{2,10}-\d{1,6})\s*$")

MIN_REPEAT = 3          # tuned on dataset A; see table above
SOLE_MAX_LEN = 400      # see "uniqueness" below


def _load_text(ds: str) -> pd.DataFrame:
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    idx = load_index(ds)[["event_id"]]
    return txt[txt.event_id.isin(set(idx.event_id))]


@lru_cache(maxsize=8)
def anchors(ds: str, min_repeat: int = MIN_REPEAT,
            sole_max_len: int = SOLE_MAX_LEN) -> pd.DataFrame:
    """High-precision (session_id, ts_ms, case, source, hint) observations.

    An ID is taken to be the active case when it is unambiguous, by either of
    two routes - which is what lets one rule serve both datasets:

      dominance   the most-repeated ID in the capture, repeated >= min_repeat.
                  This is how A's portal list views reveal the open record.
      uniqueness  the only distinct ID in a short capture. This is how B's
                  Notepad completion memos read
                  ("請求書照合完了。INV-2026-7345　金額：455,128円").

    Plus `click`, an ID inside a clicked UI element - only ~80 in A but 100%
    precise, and in B these rows often carry the process name alongside the
    case, which `hint` preserves.

    Measured on dataset A against 1,752 gt executions:
        dominance only              93.5% precision / 60.3% coverage
        + uniqueness + click        92.5% precision / 60.7% coverage

    One point of precision buys the mechanism dataset B actually needs. Tuning
    purely on A would have produced a rule that fires 72 times on B.
    """
    rows = []

    for r in _load_text(ds).itertuples():
        ids = ID_RE.findall(r.text)
        if not ids:
            continue
        c = collections.Counter(ids)
        top, n = c.most_common(1)[0]
        if n >= min_repeat:
            rows.append((r.session_id, r.ts_ms, top, "dominance", None))
        elif len(c) == 1 and len(r.text) <= sole_max_len:
            rows.append((r.session_id, r.ts_ms, top, "uniqueness", None))

    for r in load_index(ds)[lambda d: d.el_name.notna()].itertuples():
        name = str(r.el_name).strip()
        m = LABELLED_ROW.match(name)
        if m:
            rows.append((r.session_id, r.ts_ms, m.group("case"), "click",
                         m.group("label").strip()))
            continue
        for case in set(ID_RE.findall(name)):
            rows.append((r.session_id, r.ts_ms, case, "click", None))

    out = pd.DataFrame(rows, columns=["session_id", "ts_ms", "case", "source", "hint"])
    return out.sort_values(["session_id", "ts_ms"]).drop_duplicates(
        subset=["session_id", "ts_ms", "case"]).reset_index(drop=True)


def case_prefix(case: str) -> str:
    """Leading token of a case ID.

    On dataset A this maps to the process family with **100% purity** across all
    15 families (INV->invoice approval, RT->resident tax, ...), which makes
    labelling free wherever case IDs are recoverable.

    Treat that as a property of this data, not a law. Real deployments issue
    case IDs that need not encode process type at all, so `label.py` also
    provides signature-based labelling that does not depend on this holding.
    """
    return case.split("-")[0]


if __name__ == "__main__":
    for ds in ("dataset_a", "dataset_b"):
        a = anchors(ds)
        pre = collections.Counter(case_prefix(c) for c in a.case)
        print(f"\n{ds}: {len(a)} anchors, {a.case.nunique()} distinct cases, "
              f"{a.session_id.nunique()} sessions")
        print(f"  sources: {dict(collections.Counter(a.source))}")
        print(f"  prefixes ({len(pre)}): "
              + ", ".join(f"{k}={v}" for k, v in pre.most_common(20)))
