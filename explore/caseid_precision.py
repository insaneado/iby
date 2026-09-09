"""Which case ID on screen is the one actually being worked on?

A screen capture of a portal list view contains many case IDs at once, so
"visible" is not "active". This measures candidate discriminators by their
in-window precision, to find a high-precision anchor to pair with the
high-recall screen-text signal.
"""
import collections
import re

import numpy as np
import pandas as pd

from common import load_index, BUILD, sessions, load_gt_manifest
from gold import parse_ts

ID = re.compile(r"\b[A-Z]{2,4}-\d{4,8}-\d{2,4}\b")

df = load_index("dataset_a")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")

execs = collections.defaultdict(list)
for s in sessions("dataset_a"):
    m = load_gt_manifest(s)
    for p in m.get("processes", []):
        for e in p.get("executions", []):
            if e.get("case_id") and e.get("start_ts") and e.get("end_ts"):
                execs[s.name].append((e["case_id"],
                                      parse_ts(e["start_ts"]).timestamp() * 1000,
                                      parse_ts(e["end_ts"]).timestamp() * 1000))

win = {sid: {c: (a, b) for c, a, b in rows} for sid, rows in execs.items()}

# ---- how many distinct IDs does one capture contain? ----
counts = []
for _, r in txt.iterrows():
    counts.append(len(set(ID.findall(r.text))))
counts = np.array(counts)
print(f"distinct case IDs per screen capture: mean={counts.mean():.1f} "
      f"p50={np.percentile(counts,50):.0f} p90={np.percentile(counts,90):.0f} "
      f"max={counts.max()}  (captures with 0: {(counts==0).mean():.0%})")


def precision(pairs, name):
    """pairs: iterable of (session_id, case_id, ts_ms)."""
    ok = tot = 0
    for sid, case, ms in pairs:
        w = win.get(sid, {}).get(case)
        if not w:
            continue
        tot += 1
        ok += w[0] <= ms <= w[1]
    print(f"{name:38} n={tot:6d}  in-window precision={100*ok/max(tot,1):5.1f}%")
    return ok, tot


# ---- A: every mention in screen text (the baseline) ----
allm = []
for _, r in txt.iterrows():
    for c in set(ID.findall(r.text)):
        allm.append((r.session_id, c, r.ts_ms))
precision(allm, "A. any ID visible in screen text")

# ---- B: ID appearing in a clicked UI element ----
d = df[df.el_name.notna()]
clicked = [(r.session_id, c, r.ts_ms)
           for r in d.itertuples() for c in set(ID.findall(str(r.el_name)))]
precision(clicked, "B. ID inside a clicked UI element")

# ---- C: ID inside a focused field value ----
d = df[df.el_value.notna()]
valued = [(r.session_id, c, r.ts_ms)
          for r in d.itertuples() for c in set(ID.findall(str(r.el_value)))]
precision(valued, "C. ID inside a focused field value")

# ---- D: first appearance of an ID within the session ----
first = {}
for sid, c, ms in sorted(allm, key=lambda x: x[2]):
    first.setdefault((sid, c), ms)
precision([(s, c, ms) for (s, c), ms in first.items()],
          "D. first appearance in session")

# ---- E: newly appeared vs the previous capture in the same session ----
newly = []
for sid, g in txt.groupby("session_id"):
    g = g.sort_values("ts_ms")
    prev = set()
    for r in g.itertuples():
        cur = set(ID.findall(r.text))
        for c in cur - prev:
            newly.append((sid, c, r.ts_ms))
        prev = cur
precision(newly, "E. newly appeared since previous capture")

# ---- F: the ID that occurs most often within a single capture ----
dom = []
for r in txt.itertuples():
    ids = ID.findall(r.text)
    if ids:
        c = collections.Counter(ids).most_common(1)[0][0]
        dom.append((r.session_id, c, r.ts_ms))
precision(dom, "F. most-repeated ID within one capture")
