"""Diagnose the two faults behind the failed L2 experiment, before designing any fix.

1. Over-segmentation: are L2 DataItem click names row ids, and does "consecutive
   clicks on the same row are one unit" bring the unit count to the truth?
2. Label loss: does the label read at the opening click agree with ground truth
   more often than the label read at the segment's end?

Read-only. Labels are mapped to gold families with a mapping learned from GOLD
segments (label -> dominant family), never from the trial itself.
"""
import collections
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from caseid import ID_RE
from common import BUILD, load_index
from gold import Segment, load_gold
from label import SignatureLabeller

UTC = dt.timezone.utc
seg = lambda sid, a, b: Segment(session_id=sid, start=dt.datetime.fromtimestamp(a / 1000, tz=UTC),
                                end=dt.datetime.fromtimestamp(b / 1000, tz=UTC), label="")


def gap_sessions(df):
    return sorted(sid for sid, x in df.groupby("session_id") if (x.layer == "L3").sum() == 0)


def l2_clicks(df, sid):
    x = df[(df.session_id == sid) & df.event_type.isin(["mouse_click", "mouse_double_click"])
           & (df.el_type == "DataItem")].sort_values("ts_ms")
    return list(zip(x.ts_ms.values.astype(np.int64), x.el_name.fillna("").str.strip()))


def merge_same_row(clicks):
    out = []
    for t, n in clicks:
        if out and n and n == out[-1][1]:
            continue
        out.append((t, n))
    return out


# ---- dataset A ----
A = "dataset_a"
gold, df, lab = load_gold(A), load_index(A), SignatureLabeller(A)
gaps = gap_sessions(df)
clicks = {sid: l2_clicks(df, sid) for sid in gaps}
names = [n for c in clicks.values() for _, n in c]
print(f"A gap sessions: {len(gaps)}   DataItem clicks: {len(names)}   named like a row id: "
      f"{sum(bool(ID_RE.fullmatch(n)) for n in names)}   empty name: {sum(1 for n in names if not n)}")
print(f"  units, one per click: {sum(len(c) for c in clicks.values())}   "
      f"one per run of same-row clicks: {sum(len(merge_same_row(c)) for c in clicks.values())}   "
      f"gold executions: {sum(len(gold[s][0]) for s in gaps)}")

# label -> gold family, learned on gold segments of the NON-gap sessions only
votes = collections.defaultdict(collections.Counter)
for sid, (gs, _, _) in gold.items():
    if sid in gaps:
        continue
    for g in gs:
        votes[lab(g)][g.label] += 1
fam_of = {l: c.most_common(1)[0][0] for l, c in votes.items()}

hit_end = hit_open = n = unmapped = 0
for sid in gaps:
    gs = gold[sid][0]
    units = merge_same_row(clicks[sid])
    for i, (t, _) in enumerate(units[:-1]):
        t_next = units[i + 1][0]
        truth = next((g.label for g in gs if g.start.timestamp() * 1000 <= t <= g.end.timestamp() * 1000), None)
        if truth is None:
            continue
        at_end, at_open = lab(seg(sid, t, t_next)), lab(seg(sid, t, t + 1000))
        n += 1
        unmapped += at_open not in fam_of
        hit_end += fam_of.get(at_end) == truth
        hit_open += fam_of.get(at_open) == truth
print(f"\n  label vs ground truth over {n} units (label->family map from other sessions' gold):")
print(f"     read at the segment's end:   {100 * hit_end / n:.1f}%")
print(f"     read at the opening click:   {100 * hit_open / n:.1f}%     (labels with no mapping: {unmapped})")

# ---- dataset B's gap session ----
B = "dataset_b"
dfb = load_index(B)
SYSTEMS = ("HR人事給与システム", "財務会計システム", "受発注在庫管理システム")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")
for sid in gap_sessions(dfb):
    c = l2_clicks(dfb, sid)
    t = txt[txt.session_id == sid]
    crumbs = t.text.apply(lambda s: bool(re.search(r"ダッシュボード / ", s)) and any(k in s for k in SYSTEMS)).sum()
    print(f"\nB gap session {sid}: DataItem clicks {len(c)}, named like a row id "
          f"{sum(bool(ID_RE.fullmatch(n)) for _, n in c)}; units after same-row merge {len(merge_same_row(c))}; "
          f"screen captures showing a breadcrumb: {crumbs}")
