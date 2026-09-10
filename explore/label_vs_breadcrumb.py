"""Independent validation of dataset B labels, using a signal never used to make them.

`label.py` derives a label from the URL route (an L3 signal) and the system name
in the window title (L2). The portal also prints a breadcrumb - "ダッシュボード /
契約管理" - in `context.extracted_text`, which is an L1 screen capture and is
read by nothing in the labelling path.

If the two agree, the labels track the screen the operator was actually on.
Dataset B has no ground truth, so this is the closest available substitute, and
it is only evidence because the labeller cannot see it.
"""
import collections
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from common import load_index, BUILD                                   # noqa: E402
from analyze import load_segments                                      # noqa: E402

SYSTEMS = {"HR人事給与システム": "hr", "財務会計システム": "fin",
           "受発注在庫管理システム": "ops"}
CRUMB = re.compile(r"ダッシュボード / ([^\n]+)")

df = load_index("dataset_b")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")
txt = txt[txt.event_id.isin(set(df.event_id))]
seg = load_segments()

# breadcrumb in force at each instant, per session
tl = {}
for sid, g in txt.groupby("session_id"):
    g = g.sort_values("ts_ms")
    ts, cr, cur = [], [], None
    for r in g.itertuples():
        s = next((k for k in SYSTEMS if k in r.text), None)
        m = CRUMB.search(r.text)
        if s and m:
            cur = f"{SYSTEMS[s]}::{m.group(1).strip()}"
        ts.append(r.ts_ms)
        cr.append(cur)
    tl[sid] = (np.array(ts), cr)


def crumbs_in(sid, a, b):
    ts, cr = tl.get(sid, (np.array([]), []))
    if not len(ts):
        return []
    lo, hi = int(np.searchsorted(ts, a)), int(np.searchsorted(ts, b, side="right"))
    return [c for c in cr[lo:hi] if c]


pair = collections.defaultdict(collections.Counter)
covered = 0
for r in seg.itertuples():
    cs = crumbs_in(r.session_id, r.start_ms, r.end_ms)
    if not cs:
        continue
    covered += 1
    pair[r.label][collections.Counter(cs).most_common(1)[0][0]] += 1

print(f"segments with an observable breadcrumb: {covered} of {len(seg)}\n")
print(f"{'my label':26}{'n':>5}  dominant breadcrumb screen              purity")
tot = pure = 0
for lab, c in sorted(pair.items(), key=lambda kv: -sum(kv[1].values())):
    n = sum(c.values())
    top, k = c.most_common(1)[0]
    tot += n
    pure += k
    print(f"{lab:26}{n:5}  {top[:38]:40}{100*k/n:5.0f}%")
print(f"\nweighted agreement between label and breadcrumb: {100*pure/tot:.1f}%  "
      f"({pure}/{tot})")

# a label should map to ONE screen, and a screen to ONE label
rev = collections.defaultdict(collections.Counter)
for lab, c in pair.items():
    for scr, n in c.items():
        rev[scr][lab] += n
one_to_one = sum(1 for c in pair.values() if len(c) == 1)
print(f"labels mapping to exactly one screen: {one_to_one}/{len(pair)}")
print(f"screens mapping to exactly one label: "
      f"{sum(1 for c in rev.values() if len(c) == 1)}/{len(rev)}")

# chance baseline: shuffle labels across segments
rng = np.random.default_rng(0)
labels = seg.label.values.copy()
scores = []
for _ in range(5):
    rng.shuffle(labels)
    p2 = collections.defaultdict(collections.Counter)
    for lab, r in zip(labels, seg.itertuples()):
        cs = crumbs_in(r.session_id, r.start_ms, r.end_ms)
        if cs:
            p2[lab][collections.Counter(cs).most_common(1)[0][0]] += 1
    t = sum(sum(c.values()) for c in p2.values())
    pu = sum(c.most_common(1)[0][1] for c in p2.values())
    scores.append(100 * pu / t)
print(f"chance baseline (labels shuffled): {np.mean(scores):.1f}%")
