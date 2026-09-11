"""Independent validation of dataset B labels, using a signal never used to make them.

`label.py` derives a label from the URL route (an L3 signal) and the system name
in the window title (L2). The portal also prints a breadcrumb - "ダッシュボード /
契約管理" - in `context.extracted_text`, which is an L1 screen capture and is
read by nothing in the labelling path.

If the two agree, the labels track the screen the operator was actually on.
Dataset B has no ground truth, so this is the closest available substitute, and
it is only evidence because the labeller cannot see it.

Three comparisons, in increasing order of fairness:

1. Per segment, the breadcrumb most often in force inside it. That mixes in
   every screen the operator passed through, and screen text is captured only
   every ~7.7 s, so much of it is stale by the time the work is done.
2. The same pairs as a clustering score (V-measure), against a shuffled-label
   chance baseline.
3. Only breadcrumbs actually captured close to where the segment's work was
   completed - within 2, 5 and 10 s of its end, and anywhere in it. Every row
   carries its own shuffled-label chance baseline, because a V-measure over a
   few dozen pairs is inflated by the small sample alone.

An earlier, uncommitted version of comparison 3 produced the figure the report
first quoted - and it was run against the modal labeller that the comparison
itself then led to replacing. Everything here runs on the current deliverable.
"""
import collections
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import v_measure_score

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

# the breadcrumb in force at each capture, and the captures that actually show one
tl, fresh = {}, {}
for sid, g in txt.groupby("session_id"):
    g = g.sort_values("ts_ms")
    ts, cr, cur = [], [], None
    fts, fcr = [], []
    for r in g.itertuples():
        s = next((k for k in SYSTEMS if k in r.text), None)
        m = CRUMB.search(r.text)
        if s and m:
            cur = f"{SYSTEMS[s]}::{m.group(1).strip()}"
            fts.append(r.ts_ms)
            fcr.append(cur)
        ts.append(r.ts_ms)
        cr.append(cur)
    tl[sid] = (np.array(ts), cr)
    fresh[sid] = (np.array(fts), fcr)


def crumbs_in(sid, a, b):
    ts, cr = tl.get(sid, (np.array([]), []))
    if not len(ts):
        return []
    lo, hi = int(np.searchsorted(ts, a)), int(np.searchsorted(ts, b, side="right"))
    return [c for c in cr[lo:hi] if c]


def last_fresh(sid, a, b):
    """The last breadcrumb actually captured in [a, b], or None."""
    fts, fcr = fresh.get(sid, (np.array([]), []))
    if not len(fts):
        return None
    i = int(np.searchsorted(fts, b, side="right")) - 1
    return fcr[i] if i >= 0 and fts[i] >= a else None


# ---- 1. modal breadcrumb per segment -----------------------------------------
pair = collections.defaultdict(collections.Counter)
modal = []
for r in seg.itertuples():
    cs = crumbs_in(r.session_id, r.start_ms, r.end_ms)
    if not cs:
        continue
    top = collections.Counter(cs).most_common(1)[0][0]
    pair[r.label][top] += 1
    modal.append((r.label, top))

print(f"segments with an observable breadcrumb: {len(modal)} of {len(seg)}\n")
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


# ---- 2 and 3. as a clustering score, and against contemporaneous captures ----
def v(pairs):
    return v_measure_score([c for _, c in pairs], [l for l, _ in pairs])


def chance_v(pairs, seeds=20):
    g = np.random.default_rng(0)
    labs = [l for l, _ in pairs]
    out = []
    for _ in range(seeds):
        g.shuffle(labs)
        out.append(v_measure_score([c for _, c in pairs], labs))
    return float(np.mean(out))


def system(x):
    return x.split("__")[0] if "__" in x else x.split("::")[0]


print(f"\nmodal breadcrumb per segment: pairs={len(modal)}  V={v(modal):.3f}  "
      f"chance V={chance_v(modal):.3f}")
print("\nbreadcrumb actually captured close to the end of the segment's work:")
for name, t in (("2 s of segment end", 2), ("5 s of segment end", 5),
                ("10 s of segment end", 10), ("the whole segment", None)):
    pairs = []
    for r in seg.itertuples():
        a = r.start_ms if t is None else max(r.start_ms, r.end_ms - t * 1000)
        c = last_fresh(r.session_id, a, r.end_ms)
        if c:
            pairs.append((r.label, c))
    if not pairs:
        print(f"  within {name:22} pairs=0")
        continue
    agree = 100 * np.mean([system(l) == system(c) for l, c in pairs])
    print(f"  within {name:22} pairs={len(pairs):<4d} system agreement={agree:.1f}%  "
          f"V={v(pairs):.3f}  chance V={chance_v(pairs):.3f}")
