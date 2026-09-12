"""The model class the last experiment did not try: a sequence model.

explore/learned_brackets.py fitted a gradient-boosted classifier to per-event
features and concluded that the written rule transfers better. That conclusion
has an obvious hole, and it is the one I wrote down myself: boundary detection
is a sequence-labelling problem, and a recurrent model is the natural class for
it. Trees see each event alone; a BiLSTM sees the run of events around it, which
is where the structure of "a unit of work" actually lives.

So the same two tests that decided the last one, with the same downstream
pipeline and the same metrics. Only brackets() changes.

    TEST 1  random split, 32 dev / 31 test - is it better in-distribution?
    TEST 3  cross-portal, fitted on all of dataset A and run on dataset B,
            scored against the process code its row IDs carry - does it transfer?

Leave-one-machine-out is skipped: eight folds of neural training buys little
when test 3 is the question that decided the last experiment.

The model is given the DOM features, which is the best case for it. If the best
case still collapses on dataset B, the finding holds a fortiori.

Nothing here writes to out/segments.jsonl.
"""
from __future__ import annotations
import collections
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\LENOVO\imby")
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import v_measure_score

from caseid import anchors
from common import load_index
from evaluate import evaluate
from gold import load_gold
from label import SignatureLabeller, _route_from_placeholder
from segment import event_bounds
import segment_v4

TOL_MS = 5_000
MIN_GAP_MS = 3_000
WINDOW = 512            # events per training window
EPOCHS = 12
HAND = segment_v4.brackets
torch.manual_seed(0)
random.seed(0)
np.random.seed(0)

print("loading", flush=True)
gold_a = load_gold("dataset_a")
df_a = load_index("dataset_a")
bounds_a = event_bounds("dataset_a")
lab_a = SignatureLabeller("dataset_a")
EVENT_TYPES = [t for t, _ in df_a.event_type.value_counts().head(12).items()]
EL_TAGS = ["td", "button", "input", "a", "div", "select", "textarea"]
by_a = {s: g.sort_values("ts_ms") for s, g in df_a.groupby("session_id")}


def features(d: pd.DataFrame) -> np.ndarray:
    n = len(d)
    ts = d.ts_ms.values.astype(np.int64)
    cols = []

    def add(v):
        cols.append(np.asarray(v, dtype=np.float32))

    gap_prev = np.diff(ts, prepend=ts[0])
    gap_next = np.diff(ts, append=ts[-1])
    add(np.log1p(np.maximum(gap_prev, 0)) / 10.0)
    add(np.log1p(np.maximum(gap_next, 0)) / 10.0)
    add((np.log1p(np.maximum(gap_next, 0)) - np.log1p(np.maximum(gap_prev, 0))) / 10.0)
    add((ts - ts[0]) / max(ts[-1] - ts[0], 1))
    for w in (5_000, 30_000):
        left = np.searchsorted(ts, ts - w, side="left")
        right = np.searchsorted(ts, ts + w, side="right")
        add((np.arange(n) - left) / 50.0)
        add((right - np.arange(n) - 1) / 50.0)
    for t in EVENT_TYPES:
        add((d.event_type.values == t).astype(np.float32))
    add(pd.to_numeric(d.layer, errors="coerce").fillna(-1).values / 3.0)
    app = d.app.astype(str).values
    title = d.title.astype(str).values
    url = d.url.astype(str).values
    add(np.r_[0, (app[1:] != app[:-1]).astype(np.float32)])
    add(np.r_[0, (title[1:] != title[:-1]).astype(np.float32)])
    add(np.r_[0, (url[1:] != url[:-1]).astype(np.float32)])
    add(pd.to_numeric(d.has_text, errors="coerce").fillna(0).values)
    add(d.key.notna().values.astype(np.float32))
    add(d.char.notna().values.astype(np.float32))
    add(np.minimum(pd.to_numeric(d.clip_len, errors="coerce").fillna(0).values, 500) / 500.0)
    add(d.url.notna().values.astype(np.float32))
    for t in EL_TAGS:
        add((d.el_tag.astype(str).values == t).astype(np.float32))
    add(d.el_id.notna().values.astype(np.float32))
    add(d.el_name.notna().values.astype(np.float32))
    eid = d.el_id.astype(str).values
    add(pd.Series(eid).str.startswith("btn").fillna(False).values.astype(np.float32))
    return np.column_stack(cols).astype(np.float32)


def edge_labels(d: pd.DataFrame, sid: str) -> np.ndarray:
    ts = d.ts_ms.values.astype(np.int64)
    y = np.zeros(len(ts), dtype=np.int64)
    for seg in gold_a[sid][0]:
        for when, cls in ((seg.start, 1), (seg.end, 2)):
            t = int(when.timestamp() * 1000)
            i = int(np.clip(np.searchsorted(ts, t), 0, len(ts) - 1))
            for j in (i - 1, i):
                if 0 <= j < len(ts) and abs(ts[j] - t) <= TOL_MS and y[j] == 0:
                    y[j] = cls
                    break
    return y


N_FEAT = features(by_a[sorted(gold_a)[0]]).shape[1]
print(f"{N_FEAT} features per event")


class BiLSTMTagger(nn.Module):
    def __init__(self, n_feat, hidden=64):
        super().__init__()
        self.norm = nn.LayerNorm(n_feat)
        self.lstm = nn.LSTM(n_feat, hidden, num_layers=2, batch_first=True,
                            bidirectional=True, dropout=0.1)
        self.head = nn.Linear(hidden * 2, 3)

    def forward(self, x):
        h, _ = self.lstm(self.norm(x))
        return self.head(h)


def windows(sids):
    out = []
    for sid in sids:
        d = by_a.get(sid)
        if d is None or len(d) < 3 or sid not in gold_a:
            continue
        X, Y = features(d), edge_labels(d, sid)
        for i in range(0, len(X), WINDOW):
            xs, ys = X[i:i + WINDOW], Y[i:i + WINDOW]
            if len(xs) >= 32:
                out.append((torch.from_numpy(xs), torch.from_numpy(ys)))
    return out


def train(sids):
    data = windows(sids)
    counts = np.bincount(np.concatenate([y.numpy() for _, y in data]), minlength=3)
    w = torch.tensor((counts.sum() / np.maximum(counts, 1)) ** 0.5, dtype=torch.float32)
    w = w / w.mean()
    model = BiLSTMTagger(N_FEAT)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    lossf = nn.CrossEntropyLoss(weight=w)
    print(f"  {len(data)} windows, class counts {counts.tolist()}", flush=True)
    for ep in range(EPOCHS):
        random.shuffle(data)
        model.train()
        tot = 0.0
        for xs, ys in data:
            opt.zero_grad()
            out = model(xs.unsqueeze(0)).squeeze(0)
            loss = lossf(out, ys)
            loss.backward()
            opt.step()
            tot += float(loss)
        if ep % 3 == 2 or ep == EPOCHS - 1:
            print(f"    epoch {ep + 1:2d}  mean loss {tot / len(data):.4f}", flush=True)
    model.eval()
    return model


@torch.no_grad()
def seq_brackets(model, thr, table):
    def fn(_df, sid):
        d = table.get(sid)
        if d is None or len(d) < 3:
            return np.array([], np.int64), np.array([], np.int64)
        X = torch.from_numpy(features(d))
        parts = []
        with torch.no_grad():
            for i in range(0, len(X), WINDOW):
                parts.append(torch.softmax(model(X[i:i + WINDOW].unsqueeze(0)).squeeze(0), dim=-1))
        p = torch.cat(parts).detach().numpy()
        ts = d.ts_ms.values.astype(np.int64)
        out = []
        for cls in (1, 2):
            score = p[:, cls]
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


def segment_with(fn, ds, bounds, labeller):
    original = segment_v4.brackets
    segment_v4.brackets = fn
    try:
        return segment_v4.segment_dataset_v4(ds, bounds, labeller=labeller, expand_gap_s=60)
    finally:
        segment_v4.brackets = original


def score_a(fn, sids):
    pred = segment_with(fn, "dataset_a", {k: bounds_a[k] for k in sids}, lab_a)
    return evaluate({k: v for k, v in gold_a.items() if k in sids}, pred)


def line(name, r):
    print(f"  {name:28} BF1@2s={r.bf1[2.0][2]:.3f} BF1@5s={r.bf1[5.0][2]:.3f} "
          f"BF1@10s={r.bf1[10.0][2]:.3f} WD={r.windowdiff:.3f} V={r.v_measure:.3f}", flush=True)


print("\n" + "=" * 74)
print("TEST 1 - random split, 32 dev / 31 test")
print("=" * 74)
sids = sorted(gold_a)
random.Random(0).shuffle(sids)
DEV, TEST = set(sids[:32]), set(sids[32:])
line("hand rule (TEST)", score_a(HAND, TEST))
model = train(sorted(DEV))
best, best_thr = None, 0.3
for thr in (0.2, 0.3, 0.4, 0.5):
    s = score_a(seq_brackets(model, thr, by_a), DEV).bf1[5.0][2]
    print(f"  dev thr={thr}  BF1@5s={s:.3f}", flush=True)
    if best is None or s > best:
        best, best_thr = s, thr
print(f"  threshold chosen on dev: {best_thr}")
line("BiLSTM (dev)", score_a(seq_brackets(model, best_thr, by_a), DEV))
line("BiLSTM (TEST)", score_a(seq_brackets(model, best_thr, by_a), TEST))

print("\n" + "=" * 74)
print("TEST 3 - cross-portal: fitted on all of dataset A, run on dataset B")
print("=" * 74)
df_b = load_index("dataset_b")
by_b = {s: g.sort_values("ts_ms") for s, g in df_b.groupby("session_id")}
bounds_b = event_bounds("dataset_b")
lab_b = SignatureLabeller("dataset_b")
ROW_ID = re.compile(r"^P\d+-\d{8}-\d{3}$")
code = lambda rid: rid.split("-")[0]
fixture = json.loads((ROOT / "tool" / "mock_portal" / "fixture.json").read_text(encoding="utf-8"))
expect = collections.defaultdict(set)
for st in fixture.values():
    expect[f"{st['system']}__{_route_from_placeholder(st['placeholder'])}"] |= {
        code(r["ID"]) for r in st["rows"]}
a_b = anchors("dataset_b")
a_b = a_b[a_b.case.astype(str).str.match(ROW_ID)]
by_anchor = {s: g for s, g in a_b.groupby("session_id")}


def score_b(fn, name):
    pred = segment_with(fn, "dataset_b", bounds_b, lab_b)
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
        print(f"  {name:28} segments {n_seg:4d}   nothing tied")
        return
    ok = sum(c in expect.get(l, set()) for l, c in pairs)
    v = v_measure_score([c for _, c in pairs], [l for l, _ in pairs])
    print(f"  {name:28} segments {n_seg:4d}   tied {len(pairs):4d}   "
          f"V vs process code {v:.3f}   names the right screen {100 * ok / len(pairs):.1f}%", flush=True)


score_b(HAND, "hand rule")
full = train(sorted(gold_a))
for thr in (0.2, 0.3, 0.4):
    score_b(seq_brackets(full, thr, by_b), f"BiLSTM thr={thr}")
