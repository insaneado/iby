"""Measurement only: open units at the accessibility-layer row click where L3 is missing.

In a session with no L3 events there is no browser row click and no confirm
press, so v4 falls back to case anchors. The same row selection is still visible
at L2 as a click on a `DataItem` control. This opens a unit at each such click
and closes it at the next one - no tuned parameter, and the rest of the pipeline
untouched - then scores it against the shipped fallback on dataset A's gap
sessions and on the whole of dataset A, and sizes what it would change in
dataset B's one gap session. Nothing is written to the repository.

A negative result, kept so it can be re-run: boundary F1 at 5 s rises while
label consistency and ARI fall, and dataset B's gap session over-segments. The
bar was set before measuring, it failed, and it was not shipped. See RESULTS.md.

    python experiment_l2_opens.py
"""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from common import load_index
from evaluate import evaluate
from gold import Segment, load_gold
from label import SignatureLabeller
from segment import event_bounds
from segment_v4 import segment_dataset_v4

UTC = dt.timezone.utc


def gap_sessions(df):
    return sorted(sid for sid, x in df.groupby("session_id") if (x.layer == "L3").sum() == 0)


def l2_segments(df, sid, lab):
    x = df[df.session_id == sid]
    opens = np.sort(x[x.event_type.isin(["mouse_click", "mouse_double_click"])
                      & (x.el_type == "DataItem")].ts_ms.values.astype(np.int64))
    last = int(x.ts_ms.max())
    segs = []
    for i, o in enumerate(opens):
        end = int(opens[i + 1]) if i + 1 < len(opens) else last
        if end - o < 1000:
            continue
        s = Segment(session_id=sid, start=dt.datetime.fromtimestamp(o / 1000, tz=UTC),
                    end=dt.datetime.fromtimestamp(end / 1000, tz=UTC), label="")
        s.label = lab(s)
        segs.append(s)
    return segs


def maps_to_one(gold, pred):
    ok = n = 0
    for sid, (gsegs, _, _) in gold.items():
        ps = pred.get(sid, [])
        for g in gsegs:
            ovs = [max(0.0, (min(g.end, p.end) - max(g.start, p.start)).total_seconds()) for p in ps]
            ok += sum(1 for o in ovs if o >= 0.10 * g.duration) == 1
            n += 1
    return 100 * ok / n


A = "dataset_a"
gold, df, lab, bounds = load_gold(A), load_index(A), SignatureLabeller(A), event_bounds(A)
shipped = segment_dataset_v4(A, bounds, labeller=lab, expand_gap_s=60)
gaps = gap_sessions(df)
trial = dict(shipped)
for sid in gaps:
    trial[sid] = l2_segments(df, sid, lab)

g_gap = {k: v for k, v in gold.items() if k in gaps}
print(f"dataset A: {len(gaps)} sessions with zero L3 events, {sum(len(v[0]) for v in g_gap.values())} gold executions\n")
for name, pred in (("shipped (case-anchor fallback)", shipped), ("trial (L2 row click opens a unit)", trial)):
    p_gap = {k: v for k, v in pred.items() if k in gaps}
    r, R = evaluate(g_gap, p_gap), evaluate(gold, pred)
    print(f"  {name}")
    print(f"     gap sessions: BF1@2s={r.bf1[2.0][2]:.3f}  BF1@5s={r.bf1[5.0][2]:.3f}  BF1@10s={r.bf1[10.0][2]:.3f}  "
          f"V={r.v_measure:.3f}  ARI={r.ari:.3f}  segments={r.n_pred}  maps to one={maps_to_one(g_gap, p_gap):.1f}%")
    print(f"     all of A:     BF1@2s={R.bf1[2.0][2]:.3f}  BF1@5s={R.bf1[5.0][2]:.3f}  V={R.v_measure:.3f}  "
          f"ARI={R.ari:.3f}  segments={R.n_pred}  maps to one={maps_to_one(gold, pred):.1f}%")

B = "dataset_b"
dfb, labb = load_index(B), SignatureLabeller(B)
shipped_b = segment_dataset_v4(B, event_bounds(B), labeller=labb, expand_gap_s=60)
for sid in gap_sessions(dfb):
    t = l2_segments(dfb, sid, labb)
    print(f"\ndataset B gap session {sid}: shipped {len(shipped_b[sid])} segments -> trial {len(t)}")
    print(f"  total B segments would go from {sum(len(v) for v in shipped_b.values())} "
          f"to {sum(len(v) for v in shipped_b.values()) - len(shipped_b[sid]) + len(t)}")
