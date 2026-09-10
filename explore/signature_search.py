"""Which activity signature identifies a process, without using the case ID?

The case-ID prefix labels dataset A with 100% purity but is meaningless on
dataset B, where the IDs are employee records. So the labeller has to work from
what the operator *did*, not what the record was called.

This measures candidate signatures on dataset A's gold segments, scoring each
against the true process family. Anything that scores well here is a candidate
for B; anything that does not is discarded before it can mislead.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import re

import pandas as pd
from sklearn.metrics import v_measure_score, adjusted_rand_score

from common import load_index, BUILD
from gold import load_gold

ROUTE = re.compile(r"#/([\w-]+)")

gold = load_gold("dataset_a")
df = load_index("dataset_a")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")
tmap = dict(zip(txt.event_id, txt.text))

by_sess = {sid: g for sid, g in df.groupby("session_id")}


def features(sid, seg):
    """Discrete tokens describing what happened inside one segment."""
    g = by_sess.get(sid)
    if g is None:
        return {}
    a, b = seg.start.timestamp() * 1000, seg.end.timestamp() * 1000
    e = g[(g.ts_ms >= a) & (g.ts_ms <= b)]
    f = collections.defaultdict(collections.Counter)
    for r in e.itertuples():
        if r.app:
            f["app"][str(r.app)] += 1
        if r.tab_title:
            f["sys"][str(r.tab_title)] += 1
        if r.url:
            m = ROUTE.search(str(r.url))
            if m:
                f["route"][m.group(1)] += 1
        if r.el_id:
            f["elid"][str(r.el_id)] += 1
        t = str(r.title or "")
        m = re.match(r"^(.*?)\s+(?:-|\[)\s*Compatibility Mode", t)
        if m:
            f["doc"][m.group(1).strip()] += 1
        elif " - Notepad" in t or " - Excel" in t or " - PowerPoint" in t:
            f["doc"][t.split(" - ")[0].lstrip("*")] += 1
    return f


def top(f, kind):
    c = f.get(kind)
    return c.most_common(1)[0][0] if c else "-"


rows = []
for sid, (segs, _, _) in gold.items():
    for s in segs:
        f = features(sid, s)
        rows.append({
            "truth": s.label,
            "app": top(f, "app"),
            "sys": top(f, "sys"),
            "route": top(f, "route"),
            "elid": top(f, "elid"),
            "doc": top(f, "doc"),
            "apps_set": "+".join(sorted(f.get("app", {}))),
            "routes_set": "+".join(sorted(f.get("route", {}))),
        })
d = pd.DataFrame(rows)
print(f"segments with features: {len(d)}\n")

CANDIDATES = {
    "dominant app": ["app"],
    "app set": ["apps_set"],
    "portal system": ["sys"],
    "route": ["route"],
    "route set": ["routes_set"],
    "system + route": ["sys", "route"],
    "document": ["doc"],
    "system + route + doc": ["sys", "route", "doc"],
    "app set + route set": ["apps_set", "routes_set"],
    "system + route + doc + appset": ["sys", "route", "doc", "apps_set"],
}
print(f"{'signature':34}{'clusters':>10}{'V':>8}{'ARI':>8}")
for name, cols in CANDIDATES.items():
    lab = d[cols].astype(str).agg("|".join, axis=1)
    print(f"{name:34}{lab.nunique():10d}{v_measure_score(d.truth, lab):8.3f}"
          f"{adjusted_rand_score(d.truth, lab):8.3f}")

print("\n(reference) case-ID prefix on dataset A = 1.000 / 1.000 by construction")
print("\nroute values seen:", dict(collections.Counter(d.route).most_common(10)))
print("doc values seen:", dict(collections.Counter(d.doc).most_common(8)))
