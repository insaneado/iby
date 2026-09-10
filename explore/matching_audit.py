"""Did greedy boundary matching bias the reported scores? (Yes - now fixed.)

`evaluate.boundary_prf` USED TO pair predicted boundaries to gold ones greedily,
nearest-first. Greedy is not optimal bipartite matching, so every boundary F1 in
this project could be understating or overstating the truth. Compared here
against the optimal assignment (Hungarian, via scipy).

Also checks a subtler property: matching is done on the POOLED boundary arrays
across all sessions, with a per-session offset added. If that offset were ever
too small, a boundary from one session could match one from another.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
from scipy.optimize import linear_sum_assignment

from gold import load_gold
from evaluate import evaluate, segment_boundaries, to_timeline, boundary_prf, BIN_S


from segment import event_bounds
from segment_v4 import segment_dataset_v4
from label import SignatureLabeller


def greedy_prf(gold_b, pred_b, tol_bins):
    """The superseded nearest-first matcher, kept so the comparison this
    script exists to make remains reproducible. `boundary_prf` is now
    optimal, so calling it here would compare optimal against optimal and
    report a delta of zero forever."""
    g = np.asarray(gold_b, dtype=np.int64)
    p = np.asarray(pred_b, dtype=np.int64)
    if len(g) == 0 or len(p) == 0:
        return 0.0, 0.0, 0.0
    lo = np.searchsorted(p, g - int(tol_bins), side='left')
    hi = np.searchsorted(p, g + int(tol_bins), side='right')
    pairs = sorted((abs(int(p[pi]) - int(gv)), gi, pi)
                   for gi, gv in enumerate(g) for pi in range(lo[gi], hi[gi]))
    ug, up = set(), set()
    for _, gi, pi in pairs:
        if gi not in ug and pi not in up:
            ug.add(gi); up.add(pi)
    tp = len(ug)
    prec, rec = tp / len(p), tp / len(g)
    return prec, rec, (0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))


def optimal_prf(gold_b, pred_b, tol_bins):
    """Optimal one-to-one matching within tolerance, via Hungarian assignment."""
    g = np.asarray(gold_b, dtype=np.int64)
    p = np.asarray(pred_b, dtype=np.int64)
    if len(g) == 0 or len(p) == 0:
        return 0.0, 0.0, 0.0
    # cost = distance, with anything beyond tolerance made prohibitively costly
    BIG = 10 ** 6
    d = np.abs(g[:, None] - p[None, :])
    cost = np.where(d <= tol_bins, d, BIG)
    ri, ci = linear_sum_assignment(cost)
    tp = int(((cost[ri, ci]) < BIG).sum())
    prec, rec = tp / len(p), tp / len(g)
    f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
    return prec, rec, f1


gold = load_gold("dataset_a")
lab = SignatureLabeller("dataset_a")
pred = segment_dataset_v4("dataset_a", event_bounds("dataset_a"),
                          labeller=lab, expand_gap_s=60)

# rebuild the pooled boundary arrays exactly as evaluate() does
gb, pb, offset = [], [], 0
gap_ok = True
for sid, (gsegs, t0, t1) in gold.items():
    n = len(to_timeline(gsegs, t0, t1, BIN_S))
    g = segment_boundaries(gsegs, t0, t1, BIN_S) + offset
    p = segment_boundaries(pred.get(sid, []), t0, t1, BIN_S) + offset
    if len(g) and g.max() >= offset + n:
        gap_ok = False
    gb.append(g)
    pb.append(p)
    offset += n
gb, pb = np.concatenate(gb), np.concatenate(pb)

print(f"pooled boundaries: gold {len(gb)}, predicted {len(pb)}")
print(f"session offsets keep boundaries inside their own session: {gap_ok}")
print(f"\n{'tolerance':>10}{'greedy F1':>12}{'optimal F1':>12}{'delta':>9}")
for tol in (2.0, 5.0, 10.0):
    gr = greedy_prf(gb, pb, tol / BIN_S)[2]
    op = optimal_prf(gb, pb, tol / BIN_S)[2]
    print(f"{int(tol):9}s{gr:12.4f}{op:12.4f}{op - gr:+9.4f}")

# cross-session contamination: could a boundary match one from another session?
mins = []
prev_end = 0
for sid, (gsegs, t0, t1) in gold.items():
    n = len(to_timeline(gsegs, t0, t1, BIN_S))
    mins.append(n)
    prev_end += n
print(f"\nsmallest session length in bins: {min(mins)}  "
      f"(must exceed the largest tolerance, {int(max((2,5,10)))} bins)")
