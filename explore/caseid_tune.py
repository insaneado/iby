"""Tune the active-case signal: precision AND execution coverage.

Precision alone is not enough - a rule that fires rarely but perfectly cannot
drive segmentation. What matters is the joint: how often the observation is
right, and how many of the 1,752 gt executions get at least one right
observation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import re

import pandas as pd

from common import load_index, BUILD, sessions, load_gt_manifest
from gold import parse_ts

ID = re.compile(r"\b[A-Z]{2,4}-\d{4,8}-\d{2,4}\b")

df = load_index("dataset_a")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")

execs = collections.defaultdict(dict)
n_exec = 0
for s in sessions("dataset_a"):
    m = load_gt_manifest(s)
    for p in m.get("processes", []):
        for e in p.get("executions", []):
            if e.get("case_id") and e.get("start_ts") and e.get("end_ts"):
                execs[s.name][e["case_id"]] = (
                    parse_ts(e["start_ts"]).timestamp() * 1000,
                    parse_ts(e["end_ts"]).timestamp() * 1000)
                n_exec += 1

# clicked IDs: 100% precision, use as anchors
clicked = collections.defaultdict(list)
for r in df[df.el_name.notna()].itertuples():
    for c in set(ID.findall(str(r.el_name))):
        clicked[r.session_id].append((r.ts_ms, c))


def score(obs, name):
    ok = tot = 0
    hit = set()
    for sid, case, ms in obs:
        w = execs.get(sid, {}).get(case)
        if not w:
            continue
        tot += 1
        if w[0] <= ms <= w[1]:
            ok += 1
            hit.add((sid, case))
    print(f"{name:44} n={tot:6d}  precision={100*ok/max(tot,1):5.1f}%  "
          f"exec-coverage={100*len(hit)/n_exec:5.1f}%")


def dominant(min_count=1, ratio=1.0):
    out = []
    for r in txt.itertuples():
        ids = ID.findall(r.text)
        if not ids:
            continue
        c = collections.Counter(ids)
        (top, n), = c.most_common(1)
        second = c.most_common(2)[1][1] if len(c) > 1 else 0
        if n >= min_count and n >= ratio * max(second, 1):
            out.append((r.session_id, top, r.ts_ms))
    return out


print(f"gt executions with a case id and window: {n_exec}\n")
score(dominant(1), "dominant ID (no threshold)")
score(dominant(2), "dominant ID, count >= 2")
score(dominant(3), "dominant ID, count >= 3")
score(dominant(4), "dominant ID, count >= 4")
score(dominant(2, 2.0), "dominant ID, count >= 2 and 2x runner-up")
score(dominant(3, 2.0), "dominant ID, count >= 3 and 2x runner-up")

anchors = [(s, c, ms) for s, v in clicked.items() for ms, c in v]
score(anchors, "clicked UI element only")
score(dominant(2) + anchors, "dominant(>=2) + clicked anchors")
