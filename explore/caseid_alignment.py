"""Can case IDs seen in screen text actually drive segmentation?

Two things decide it:
  1. DENSITY  - how often is screen text captured? That bounds how precisely a
     case change can be located in time.
  2. ALIGNMENT - when case X is visible on screen at time t, is t actually
     inside the ground-truth execution of case X? If mentions leak outside
     their window, the signal is not usable as a boundary source.
"""
import collections
import datetime as dt

import numpy as np
import pandas as pd

from common import load_index, BUILD, sessions, load_gt_manifest
from gold import parse_ts

df = load_index("dataset_a")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")

# ---------- 1. density ----------
gaps = []
for sid, g in txt.groupby("session_id"):
    ts = np.sort(g.ts_ms.values)
    if len(ts) > 1:
        gaps.extend(np.diff(ts) / 1000.0)
gaps = np.sort(np.array(gaps))
q = lambda p: gaps[int(len(gaps) * p)]
print(f"screen-text captures: {len(txt)} over {txt.session_id.nunique()} sessions")
print(f"seconds between captures: p50={q(.5):.1f} p75={q(.75):.1f} "
      f"p90={q(.9):.1f} p99={q(.99):.1f}")
print(f"  gold segment median duration is 32 s, so a segment contains "
      f"~{32/max(q(.5),0.01):.1f} captures at the median")

# ---------- 2. alignment ----------
execs = collections.defaultdict(list)          # session -> [(case, start, end, code)]
for s in sessions("dataset_a"):
    m = load_gt_manifest(s)
    for p in m.get("processes", []):
        for e in p.get("executions", []):
            if e.get("case_id") and e.get("start_ts") and e.get("end_ts"):
                execs[s.name].append((e["case_id"], parse_ts(e["start_ts"]),
                                      parse_ts(e["end_ts"]), p["code"]))

inside = outside = 0
off = []
covered, uncovered = 0, 0
for sid, rows in execs.items():
    t = txt[txt.session_id == sid]
    if t.empty:
        continue
    blobs = list(zip(t.ts_ms.values, t.text.values))
    for case, a, b in ((c, a, b) for c, a, b, _ in rows):
        ams, bms = a.timestamp() * 1000, b.timestamp() * 1000
        seen_in = False
        for ms, text in blobs:
            if case in text:
                if ams <= ms <= bms:
                    inside += 1
                    seen_in = True
                else:
                    outside += 1
                    off.append(min(abs(ms - ams), abs(ms - bms)) / 1000.0)
        covered += seen_in
        uncovered += not seen_in

tot = inside + outside
print(f"\nmentions of a case in screen text: {tot}")
print(f"  inside  its gt execution window: {inside} ({100*inside/tot:.1f}%)")
print(f"  outside its gt execution window: {outside} ({100*outside/tot:.1f}%)")
if off:
    off = np.sort(np.array(off))
    print(f"  when outside, distance to window: p50={off[len(off)//2]:.1f}s "
          f"p90={off[int(len(off)*.9)]:.1f}s")
print(f"\nexecutions with >=1 in-window mention: {covered} "
      f"({100*covered/(covered+uncovered):.1f}%)  none: {uncovered}")
