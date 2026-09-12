"""The component nobody has challenged yet: the labeller.

The brief grades two things, and one of them is whether the same process gets the
same label. That is entirely the labeller's job, and unlike the brackets it has
never been tested against an alternative. SignatureLabeller derives a label from
the system in the window title and the route from the URL or the note-box
placeholder. Reasonable - but is it the best available?

Four approaches, on identical segments, so only the labelling varies:

    signature   the delivered labeller
    prefix      the case ID's leading token. The report rejected this early,
                reading dataset B's IDs as employee records, and it later turned
                out to carry the process code - so it deserves a fair run.
    kmeans      unsupervised clustering over each segment's activity: which apps,
                which event types, which element ids, which URL routes.
    agglom      the same features, agglomerative clustering with cosine linkage.

Scored where there is ground truth (dataset A gold) and where there is only a
proxy (dataset B's process codes). The clustering arms get the true number of
classes handed to them, which flatters them - a real deployment would have to
choose K, and this is the friendliest possible version of that.

Nothing here writes to out/segments.jsonl.
"""
from __future__ import annotations
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\LENOVO\imby")
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, v_measure_score

from caseid import anchors, case_prefix
from common import load_index
from gold import load_gold
from label import SignatureLabeller, _route_from_placeholder
from segment import event_bounds
from segment_v4 import segment_dataset_v4

ROW_ID = re.compile(r"^P\d+-\d{8}-\d{3}$")
code = lambda rid: rid.split("-")[0]

print("loading", flush=True)
gold_a = load_gold("dataset_a")
df_a = load_index("dataset_a")
bounds_a = event_bounds("dataset_a")
lab_a = SignatureLabeller("dataset_a")
df_b = load_index("dataset_b")
bounds_b = event_bounds("dataset_b")
lab_b = SignatureLabeller("dataset_b")
by = {"dataset_a": {s: g.sort_values("ts_ms") for s, g in df_a.groupby("session_id")},
      "dataset_b": {s: g.sort_values("ts_ms") for s, g in df_b.groupby("session_id")}}


def signature_text(ds, sid, lo_ms, hi_ms):
    """A bag of what happened inside the segment - no label, no case id."""
    d = by[ds].get(sid)
    if d is None:
        return ""
    w = d[(d.ts_ms >= lo_ms) & (d.ts_ms <= hi_ms)]
    if not len(w):
        return ""
    toks = []
    toks += [f"app={a}" for a in w.app.dropna().astype(str).unique()[:8]]
    toks += [f"ev={e}" for e in w.event_type.dropna().astype(str).unique()[:8]]
    toks += [f"eid={i}" for i in w.el_id.dropna().astype(str).unique()[:12]]
    toks += [f"tag={t}" for t in w.el_tag.dropna().astype(str).unique()[:6]]
    for u in w.url.dropna().astype(str).unique()[:6]:
        m = re.search(r"#/([\w-]+)", u)
        if m:
            toks.append(f"route={m.group(1)}")
    for t in w.title.dropna().astype(str).unique()[:4]:
        toks.append("title=" + re.sub(r"\s+", "_", t)[:40])
    return " ".join(toks)


def cluster_labels(texts, k, how):
    vec = TfidfVectorizer(token_pattern=r"\S+", min_df=2)
    X = vec.fit_transform(texts)
    if X.shape[1] == 0:
        return ["c0"] * len(texts)
    # A segment whose activity produced no surviving token is an empty vector.
    # KMeans tolerates those; cosine linkage cannot, and silently dropping them
    # would score the arms on different segments. They get their own label.
    dense = np.asarray(X.todense())
    nz = np.asarray(dense).any(axis=1)
    out = ["cEMPTY"] * len(texts)
    idx = np.flatnonzero(nz)
    if len(idx) < k:
        return out
    sub = dense[idx]
    if how == "kmeans":
        lab = KMeans(n_clusters=k, n_init=10, random_state=0).fit(sub).labels_
    else:
        lab = AgglomerativeClustering(n_clusters=k, metric="cosine",
                                      linkage="average").fit_predict(sub)
    for j, i in enumerate(idx):
        out[i] = f"c{int(lab[j])}"
    return out


def arms_for(ds, segs_by_sid, truth_pairs_fn, k):
    """Every arm's labels for the same segments, then scored by the caller."""
    flat = [(sid, s) for sid, segs in segs_by_sid.items() for s in segs]
    texts = [signature_text(ds, sid, s.start.timestamp() * 1000, s.end.timestamp() * 1000)
             for sid, s in flat]
    out = {}
    out["signature"] = [s.label for _, s in flat]
    out["prefix"] = [case_prefix(str(s.case_id)) if s.case_id else "?" for _, s in flat]
    out["kmeans"] = cluster_labels(texts, k, "kmeans")
    out["agglom"] = cluster_labels(texts, k, "agglom")
    return flat, out


print("\n" + "=" * 78)
print("DATASET A - against the gold labels, which are real ground truth")
print("=" * 78)
pred_a = segment_dataset_v4("dataset_a", bounds_a, labeller=lab_a, expand_gap_s=60)
gold_lab = {}
for sid, (segs, _, _) in gold_a.items():
    gold_lab[sid] = segs
# tie each predicted segment to the gold segment it overlaps most
flat_a, arms_a = arms_for("dataset_a", pred_a, None, k=len({s.label for v in gold_a.values() for s in v[0]}))
truth = []
for sid, s in flat_a:
    best, bl = 0.0, None
    for g in gold_lab.get(sid, []):
        ov = min(s.end, g.end).timestamp() - max(s.start, g.start).timestamp()
        if ov > best:
            best, bl = ov, g.label
    truth.append(bl)
keep = [i for i, t in enumerate(truth) if t is not None]
print(f"segments scored: {len(keep)} of {len(flat_a)}  "
      f"(gold classes: {len({t for t in truth if t})})")
for name in ("signature", "prefix", "kmeans", "agglom"):
    got = [arms_a[name][i] for i in keep]
    tru = [truth[i] for i in keep]
    print(f"  {name:12} V={v_measure_score(tru, got):.3f}  ARI={adjusted_rand_score(tru, got):.3f}  "
          f"distinct labels {len(set(got))}")

print("\n" + "=" * 78)
print("DATASET B - against the process code its row IDs carry (a proxy, not truth)")
print("=" * 78)
pred_b = segment_dataset_v4("dataset_b", bounds_b, labeller=lab_b, expand_gap_s=60)
fixture = json.loads((ROOT / "tool" / "mock_portal" / "fixture.json").read_text(encoding="utf-8"))
expect = collections.defaultdict(set)
for st in fixture.values():
    expect[f"{st['system']}__{_route_from_placeholder(st['placeholder'])}"] |= {
        code(r["ID"]) for r in st["rows"]}
a_b = anchors("dataset_b")
a_b = a_b[a_b.case.astype(str).str.match(ROW_ID)]
by_anchor = {s: g for s, g in a_b.groupby("session_id")}
flat_b, arms_b = arms_for("dataset_b", pred_b, None,
                          k=len({c for cs in expect.values() for c in cs}))
codes = []
for sid, s in flat_b:
    g = by_anchor.get(sid)
    c = None
    if g is not None:
        w = g[(g.ts_ms >= s.start.timestamp() * 1000) & (g.ts_ms <= s.end.timestamp() * 1000)]
        if len(w):
            c = code(collections.Counter(w.case).most_common(1)[0][0])
    codes.append(c)
keep_b = [i for i, c in enumerate(codes) if c]
print(f"segments tied to a row: {len(keep_b)} of {len(flat_b)}  "
      f"(process codes: {len({c for c in codes if c})})")
for name in ("signature", "prefix", "kmeans", "agglom"):
    got = [arms_b[name][i] for i in keep_b]
    tru = [codes[i] for i in keep_b]
    print(f"  {name:12} V={v_measure_score(tru, got):.3f}  ARI={adjusted_rand_score(tru, got):.3f}  "
          f"distinct labels {len(set(got))}")

print("\nnote: the clustering arms were handed the true number of classes.")
print("A deployment would have to choose it, so this is their friendliest case.")
