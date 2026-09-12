"""Would a learned model find the work-unit brackets better than the rule?

v4's only hardcoded structural claim is two constants in `brackets()`:

    opens  = events whose el_tag == 'td'        selecting a row opens a record
    closes = events whose el_tag == 'button'    the confirm press closes it

Everything downstream - case assignment, labelling, gap expansion - is identical
whichever way the brackets arrive, so replacing brackets() and changing nothing
else isolates exactly the part that is hardcoded. Every arm below runs the
shipped configuration (expand_gap_s=60) and differs only in that function.

Three tests, each answering an objection the previous one leaves open.

1. RANDOM SPLIT. Fit on 32 sessions, score the other 31 once. The split is the
   one explore/overfit_audit.py uses, so the protocol is the project's own.

2. LEAVE-ONE-MACHINE-OUT, and a fairness arm. Test 1 is not a fair contest: the
   two constants were chosen by a person who had seen all 63 sessions, while the
   model sees only its fold. So a third arm DISCOVERS the open and close tags
   from the training fold alone, ranking tags by how often their events sit on a
   gold edge. If that keeps rediscovering td and button, the rule is recoverable
   structure rather than human hindsight, and the contest is fair after all.

3. CROSS-PORTAL. Neither of the above leaves the portal. Dataset B is a
   different department on a different system that nothing here was tuned on,
   and it is the only genuinely unseen data available. It has no boundary
   ground truth, so BF1 cannot be computed; what it has is the held-out proxy
   the rest of the project uses - worklist row IDs whose P<n> prefix is the
   process, which no labeller and no bracket rule reads. Bad brackets give bad
   case assignment and therefore bad labels, so scoring those labels against the
   code measures, indirectly but really, whether a bracket transfers.

Run time is a few minutes per test. Nothing here writes to out/segments.jsonl.

    python explore/learned_brackets.py
"""
from __future__ import annotations
import collections
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import v_measure_score

from caseid import anchors
from common import load_index
from evaluate import evaluate
from gold import load_gold
from label import SignatureLabeller, _route_from_placeholder
from segment import event_bounds
import segment_v4

TOL_MS = 5_000          # an event this close to a gold edge is taken to be that edge
MIN_GAP_MS = 3_000      # non-maximum suppression between two predicted brackets
THRESHOLDS = (0.2, 0.3, 0.4)
TUNE_N = 12             # sessions sampled from the train fold to set the threshold
HAND = segment_v4.brackets

print("loading", flush=True)
gold_a = load_gold("dataset_a")
df_a = load_index("dataset_a")
bounds_a = event_bounds("dataset_a")
lab_a = SignatureLabeller("dataset_a")

# The feature layout is fixed by dataset A, because the models are fitted there
# and test 3 applies them unchanged to dataset B.
EVENT_TYPES = [t for t, _ in df_a.event_type.value_counts().head(12).items()]
EL_TAGS = ["td", "button", "input", "a", "div", "select", "textarea"]
by_a = {s: g.sort_values("ts_ms") for s, g in df_a.groupby("session_id")}


def features(d: pd.DataFrame, blind: bool) -> np.ndarray:
    """Per-event features. `blind` withholds every DOM-identity signal."""
    n = len(d)
    ts = d.ts_ms.values.astype(np.int64)
    cols = []

    def add(v):
        cols.append(np.asarray(v, dtype=np.float64))

    gap_prev = np.diff(ts, prepend=ts[0])
    gap_next = np.diff(ts, append=ts[-1])
    add(np.log1p(np.maximum(gap_prev, 0)))
    add(np.log1p(np.maximum(gap_next, 0)))
    add(np.log1p(np.maximum(gap_next, 0)) - np.log1p(np.maximum(gap_prev, 0)))
    add((ts - ts[0]) / max(ts[-1] - ts[0], 1))
    for w in (5_000, 30_000):
        left = np.searchsorted(ts, ts - w, side="left")
        right = np.searchsorted(ts, ts + w, side="right")
        add(np.arange(n) - left)
        add(right - np.arange(n) - 1)
    for t in EVENT_TYPES:
        add((d.event_type.values == t).astype(float))
    add(pd.to_numeric(d.layer, errors="coerce").fillna(-1).values)
    app = d.app.astype(str).values
    title = d.title.astype(str).values
    url = d.url.astype(str).values
    add(np.r_[0, (app[1:] != app[:-1]).astype(float)])
    add(np.r_[0, (title[1:] != title[:-1]).astype(float)])
    add(np.r_[0, (url[1:] != url[:-1]).astype(float)])
    add(pd.to_numeric(d.has_text, errors="coerce").fillna(0).values)
    add(d.key.notna().values.astype(float))
    add(d.char.notna().values.astype(float))
    add(pd.to_numeric(d.clip_len, errors="coerce").fillna(0).values)
    add(d.url.notna().values.astype(float))
    if not blind:
        for t in EL_TAGS:
            add((d.el_tag.astype(str).values == t).astype(float))
        add(d.el_id.notna().values.astype(float))
        add(d.el_name.notna().values.astype(float))
        eid = d.el_id.astype(str).values
        add(pd.Series(eid).str.startswith("btn").fillna(False).values.astype(float))
    return np.column_stack(cols)


def edge_labels(d: pd.DataFrame, sid: str) -> np.ndarray:
    """0 none, 1 opens a unit, 2 closes one - the nearest event to each gold edge."""
    ts = d.ts_ms.values.astype(np.int64)
    y = np.zeros(len(ts), dtype=int)
    for seg in gold_a[sid][0]:
        for when, cls in ((seg.start, 1), (seg.end, 2)):
            t = int(when.timestamp() * 1000)
            i = int(np.clip(np.searchsorted(ts, t), 0, len(ts) - 1))
            for j in (i - 1, i):
                if 0 <= j < len(ts) and abs(ts[j] - t) <= TOL_MS and y[j] == 0:
                    y[j] = cls
                    break
    return y


def fit(sids, blind):
    X, Y = [], []
    for sid in sids:
        d = by_a.get(sid)
        if d is None or len(d) < 3 or sid not in gold_a:
            continue
        X.append(features(d, blind))
        Y.append(edge_labels(d, sid))
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                       max_depth=6, random_state=0)
    m.fit(np.vstack(X), np.concatenate(Y))
    return m


def model_brackets(model, blind, thr, table):
    """brackets() backed by a model, reading events from `table`."""
    def fn(_df, sid):
        d = table.get(sid)
        if d is None or len(d) < 3:
            return np.array([], np.int64), np.array([], np.int64)
        p = model.predict_proba(features(d, blind))
        ts = d.ts_ms.values.astype(np.int64)
        out = []
        for cls in (1, 2):
            if cls not in model.classes_:
                out.append(np.array([], np.int64))
                continue
            score = p[:, list(model.classes_).index(cls)]
            keep = []
            for i in np.argsort(-score):
                if score[i] < thr:
                    break
                t = int(ts[i])
                if all(abs(t - k) >= MIN_GAP_MS for k in keep):
                    keep.append(t)
            out.append(np.sort(np.array(keep, dtype=np.int64)))
        return out[0], out[1]
    return fn


def discover_rule(train_sids):
    """Pick the open and close el_tag from the training fold alone.

    No human choice enters: tags are ranked by how often their events sit on a
    gold edge, weighted by how many such events there are. The criterion does
    not forbid picking the same tag for both ends, and on one fold it does -
    which is itself the finding, and is left in rather than patched away.
    """
    stats = collections.defaultdict(lambda: [0, 0, 0])
    for sid in train_sids:
        d = by_a.get(sid)
        if d is None or sid not in gold_a:
            continue
        for tag, e in zip(d.el_tag.astype(str).values, edge_labels(d, sid)):
            st = stats[tag]
            st[0] += 1
            if e == 1:
                st[1] += 1
            elif e == 2:
                st[2] += 1

    def best(idx):
        cand = [(t, st[idx] / st[0], st[idx]) for t, st in stats.items()
                if st[0] >= 20 and t not in ("nan", "None", "")]
        cand.sort(key=lambda c: c[1] * np.sqrt(c[2]), reverse=True)
        return cand[0][0] if cand else None

    return best(1), best(2)


def tag_brackets(open_tag, close_tag, table):
    def fn(_df, sid):
        d = table.get(sid)
        if d is None:
            return np.array([], np.int64), np.array([], np.int64)
        tags = d.el_tag.astype(str).values
        ts = d.ts_ms.values.astype(np.int64)
        o = np.sort(ts[tags == open_tag]) if open_tag else np.array([], np.int64)
        c = np.sort(ts[tags == close_tag]) if close_tag else np.array([], np.int64)
        return o, c
    return fn


def segment_with(bracket_fn, ds, bounds, labeller):
    original = segment_v4.brackets
    segment_v4.brackets = bracket_fn
    try:
        return segment_v4.segment_dataset_v4(ds, bounds, labeller=labeller, expand_gap_s=60)
    finally:
        segment_v4.brackets = original


def score_a(bracket_fn, sids):
    pred = segment_with(bracket_fn, "dataset_a", {k: bounds_a[k] for k in sids}, lab_a)
    return evaluate({k: v for k, v in gold_a.items() if k in sids}, pred)


def line(name, r):
    print(f"  {name:30} BF1@2s={r.bf1[2.0][2]:.3f} BF1@5s={r.bf1[5.0][2]:.3f} "
          f"BF1@10s={r.bf1[10.0][2]:.3f} WD={r.windowdiff:.3f} V={r.v_measure:.3f}", flush=True)


# =============================================================================
print("\n" + "=" * 76)
print("TEST 1 - random split: fit on 32 sessions, score the other 31 once")
print("=" * 76)
sids = sorted(gold_a)
random.Random(0).shuffle(sids)
DEV, TEST = set(sids[:32]), set(sids[32:])
line("hand rule (dev)", score_a(HAND, DEV))
line("hand rule (TEST)", score_a(HAND, TEST))
for blind, name in ((False, "model A sees DOM"), (True, "model B blind")):
    m = fit(sorted(DEV), blind)
    best, best_thr = None, THRESHOLDS[0]
    for thr in THRESHOLDS:
        s = score_a(model_brackets(m, blind, thr, by_a), DEV).bf1[5.0][2]
        if best is None or s > best:
            best, best_thr = s, thr
    line(f"{name} (dev)", score_a(model_brackets(m, blind, best_thr, by_a), DEV))
    line(f"{name} (TEST)", score_a(model_brackets(m, blind, best_thr, by_a), TEST))

# =============================================================================
print("\n" + "=" * 76)
print("TEST 2 - leave-one-machine-out, with the rule itself discovered per fold")
print("=" * 76)
machine = {sid: df_a[df_a.session_id == sid].machine.dropna().iloc[0]
           for sid in gold_a if len(df_a[df_a.session_id == sid].machine.dropna())}
by_machine = collections.defaultdict(set)
for sid, m_ in machine.items():
    by_machine[m_].add(sid)
rows = collections.defaultdict(list)
for m_, held in sorted(by_machine.items()):
    train, held = sorted(set(gold_a) - held), sorted(held)
    print(f"\nhold out {m_:22} n={len(held):2d}")
    r = score_a(HAND, held)
    rows["hand"].append(r)
    line("hand rule", r)
    ot, ct = discover_rule(train)
    r = score_a(tag_brackets(ot, ct, by_a), held)
    rows["C"].append(r)
    line(f"discovered open={ot!r} close={ct!r}", r)
    tune = random.Random(0).sample(train, min(TUNE_N, len(train)))
    for blind, name in ((False, "model A"), (True, "model B")):
        mod = fit(train, blind)
        best, best_thr = None, THRESHOLDS[0]
        for thr in THRESHOLDS:
            s = score_a(model_brackets(mod, blind, thr, by_a), tune).bf1[5.0][2]
            if best is None or s > best:
                best, best_thr = s, thr
        r = score_a(model_brackets(mod, blind, best_thr, by_a), held)
        rows[name].append(r)
        line(f"{name} thr={best_thr}", r)

print("\nacross held-out machines")
for key, label in (("hand", "hand rule (human-chosen)"), ("C", "rule discovered per fold"),
                   ("model A", "model A (sees DOM)"), ("model B", "model B (blind)")):
    b2 = np.array([r.bf1[2.0][2] for r in rows[key]])
    b5 = np.array([r.bf1[5.0][2] for r in rows[key]])
    v = np.array([r.v_measure for r in rows[key]])
    print(f"  {label:26} BF1@2s {b2.mean():.3f}+-{b2.std():.3f}   "
          f"BF1@5s {b5.mean():.3f}+-{b5.std():.3f}   V {v.mean():.3f}")

# =============================================================================
print("\n" + "=" * 76)
print("TEST 3 - cross-portal: fit on all of dataset A, run on dataset B")
print("=" * 76)
df_b = load_index("dataset_b")
by_b = {s: g.sort_values("ts_ms") for s, g in df_b.groupby("session_id")}
bounds_b = event_bounds("dataset_b")
lab_b = SignatureLabeller("dataset_b")

ROW_ID = re.compile(r"^P\d+-\d{8}-\d{3}$")
code = lambda row_id: row_id.split("-")[0]
fixture = json.loads((ROOT / "tool" / "mock_portal" / "fixture.json").read_text(encoding="utf-8"))
expect = collections.defaultdict(set)
for st in fixture.values():
    expect[f"{st['system']}__{_route_from_placeholder(st['placeholder'])}"] |= {
        code(r["ID"]) for r in st["rows"]}
a_b = anchors("dataset_b")
a_b = a_b[a_b.case.astype(str).str.match(ROW_ID)]
by_anchor = {s: g for s, g in a_b.groupby("session_id")}


def score_b(bracket_fn, name):
    pred = segment_with(bracket_fn, "dataset_b", bounds_b, lab_b)
    pairs, n_seg = [], 0
    for sid, segs in pred.items():
        n_seg += len(segs)
        g = by_anchor.get(sid)
        if g is None:
            continue
        for s in segs:
            w = g[(g.ts_ms >= s.start.timestamp() * 1000) & (g.ts_ms <= s.end.timestamp() * 1000)]
            if len(w):
                pairs.append((s.label, code(collections.Counter(w.case).most_common(1)[0][0])))
    if not pairs:
        print(f"  {name:30} segments {n_seg:4d}   nothing tied")
        return
    ok = sum(c in expect.get(l, set()) for l, c in pairs)
    v = v_measure_score([c for _, c in pairs], [l for l, _ in pairs])
    print(f"  {name:30} segments {n_seg:4d}   tied {len(pairs):4d}   "
          f"V vs process code {v:.3f}   names the right screen {100 * ok / len(pairs):.1f}%",
          flush=True)


print("the hand-rule row also checks this harness against the delivered run")
score_b(HAND, "hand rule")
for blind, name in ((False, "model A sees DOM"), (True, "model B blind")):
    mod = fit(sorted(gold_a), blind)
    for thr in THRESHOLDS:
        score_b(model_brackets(mod, blind, thr, by_b), f"{name} thr={thr}")
