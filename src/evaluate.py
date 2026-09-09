"""Evaluation framework for Step 1.

Built before the segmenter, deliberately: without a scorer, every subsequent
change is a guess. This module defines what "good" means and is the reference
the whole pipeline is tuned against.

Design decisions, and why
-------------------------

*Everything derives from a binned timeline.* Gold and prediction are both
rendered onto a common 1-second grid, with uncovered time labelled IDLE. That
makes boundary metrics, segmentation metrics and label metrics mutually
consistent, and it handles the ~5% of wall time that belongs to no business
process without special-casing.

*Boundaries are scored with a tolerance.* Two independent reasons. Ground-truth
timestamps are not tightly aligned to the event stream - for 27% of gt process
starts there is no event at all within +/-2 s. And the median gap between
consecutive gold segments is 0.0 s, so boundaries are genuinely hard to place to
the second. Exact-match scoring would mostly measure ground-truth jitter.
Tolerance is reported at 2 s / 5 s / 10 s so the reader can see the curve rather
than trust one tuned number.

*Label quality is measured by agreement, not accuracy.* The task says the label
text is not evaluated - only that the same process consistently gets the same
label. That is a clustering-agreement question, so V-measure and Adjusted Rand
are the right instruments; accuracy against our arbitrary names would be
meaningless.
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass

import numpy as np
from sklearn.metrics import (adjusted_rand_score, v_measure_score,
                             homogeneity_score, completeness_score)

from gold import IDLE, Segment

BIN_S = 1.0
TOLERANCES = (2.0, 5.0, 10.0)


# --------------------------------------------------------------------------
# timeline rendering
# --------------------------------------------------------------------------

def to_timeline(segs: list[Segment], t0: dt.datetime, t1: dt.datetime,
                bin_s: float = BIN_S) -> np.ndarray:
    """Render segments onto a fixed grid. Uncovered bins are IDLE.

    Later segments win on overlap; gold has none, and a predictor that emits
    overlaps is making a claim it should be penalised for elsewhere, not here.
    """
    n = max(1, int(np.ceil((t1 - t0).total_seconds() / bin_s)))
    out = np.full(n, IDLE, dtype=object)
    for s in segs:
        a = int((s.start - t0).total_seconds() // bin_s)
        b = int(np.ceil((s.end - t0).total_seconds() / bin_s))
        a, b = max(0, a), min(n, b)
        if b > a:
            out[a:b] = s.label
    return out


def boundary_idx(tl: np.ndarray) -> np.ndarray:
    """Bin indices where the label changes.

    Kept only for WindowDiff's internal use on a rendered timeline. Do NOT use
    it to enumerate a segmentation's boundaries - see `segment_boundaries`.
    """
    if len(tl) < 2:
        return np.array([], dtype=int)
    return np.flatnonzero(tl[1:] != tl[:-1]) + 1


def segment_boundaries(segs: list[Segment], t0: dt.datetime, t1: dt.datetime,
                       bin_s: float = BIN_S) -> np.ndarray:
    """Bin indices of every segment edge, deduplicated.

    Deriving boundaries from *label changes* on a timeline loses the boundary
    between two consecutive executions that share a label - which is precisely
    the case this task exists to solve ("the same process appears many times a
    day"). Measured on dataset A's gold set, that approach saw 1,830 of the
    1,946 real internal boundaries: it silently discarded 6% of the problem,
    and specifically the hardest 6%.

    Taking the edges themselves counts back-to-back same-label executions
    correctly: the shared instant dedups to one boundary, while a segment
    followed by idle then another segment yields two.
    """
    n = max(1, int(np.ceil((t1 - t0).total_seconds() / bin_s)))
    out = set()
    for s in segs:
        for t in (s.start, s.end):
            i = int(round((t - t0).total_seconds() / bin_s))
            if 0 < i < n:          # session edges are not boundaries
                out.add(i)
    return np.array(sorted(out), dtype=int)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def boundary_prf(gold_b: np.ndarray, pred_b: np.ndarray, tol_bins: float):
    """Greedy one-to-one nearest matching within tolerance -> (P, R, F1).

    One-to-one matters: without it, a predictor that emits a dense burst of
    boundaries near every true one would score perfect recall.
    """
    if len(gold_b) == 0 and len(pred_b) == 0:
        return 1.0, 1.0, 1.0
    if len(gold_b) == 0 or len(pred_b) == 0:
        return 0.0, 0.0, 0.0
    pairs = sorted(((abs(int(p) - int(g)), gi, pi)
                    for gi, g in enumerate(gold_b)
                    for pi, p in enumerate(pred_b)
                    if abs(int(p) - int(g)) <= tol_bins))
    ug, up = set(), set()
    for _, gi, pi in pairs:
        if gi not in ug and pi not in up:
            ug.add(gi)
            up.add(pi)
    tp = len(ug)
    prec = tp / len(pred_b)
    rec = tp / len(gold_b)
    f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
    return prec, rec, f1


def window_diff(gold_tl: np.ndarray, pred_tl: np.ndarray, k: int | None = None) -> float:
    """WindowDiff (Pevzner & Hearst). Lower is better; 0 is perfect.

    Preferred over raw boundary counts because it charges a near-miss far less
    than a boundary invented in empty space.
    """
    gb = np.zeros(len(gold_tl), dtype=int)
    pb = np.zeros(len(pred_tl), dtype=int)
    gb[boundary_idx(gold_tl)] = 1
    pb[boundary_idx(pred_tl)] = 1
    n = len(gb)
    if k is None:
        nseg = max(1, gb.sum())
        k = max(2, int(round(n / (2 * nseg))))
    if n <= k:
        return float(gb.sum() != pb.sum())
    gc = np.concatenate([[0], np.cumsum(gb)])
    pc = np.concatenate([[0], np.cumsum(pb)])
    diff = np.abs((gc[k:] - gc[:-k]) - (pc[k:] - pc[:-k]))
    return float((diff > 0).mean())


@dataclass
class Result:
    n_gold: int
    n_pred: int
    bf1: dict          # tolerance -> (P, R, F1)
    windowdiff: float
    v_measure: float
    ari: float
    homogeneity: float
    completeness: float
    idle_gold: float
    idle_pred: float

    def line(self, name: str) -> str:
        b = self.bf1
        return (f"{name:24} segs={self.n_pred:5d}/{self.n_gold:<5d} "
                f"BF1@2s={b[2.0][2]:.3f} @5s={b[5.0][2]:.3f} @10s={b[10.0][2]:.3f} "
                f"WD={self.windowdiff:.3f} V={self.v_measure:.3f} ARI={self.ari:.3f}")


def evaluate(gold: dict, pred: dict, bin_s: float = BIN_S) -> Result:
    """Score predicted segments against gold, pooled across all sessions.

    `gold` is {session_id: (segments, t0, t1)}; `pred` is {session_id: segments}.
    Pooling (rather than averaging per-session) weights every second of work
    equally, which is what the client cares about.
    """
    gt_all, pr_all = [], []
    bounds_g, bounds_p, offset = [], [], 0
    n_gold = n_pred = 0
    for sid, (gsegs, t0, t1) in gold.items():
        psegs = pred.get(sid, [])
        g_tl = to_timeline(gsegs, t0, t1, bin_s)
        p_tl = to_timeline(psegs, t0, t1, bin_s)
        gt_all.append(g_tl)
        pr_all.append(p_tl)
        # boundaries come from segment edges, not label changes - see
        # segment_boundaries() for why that distinction matters here
        bounds_g.append(segment_boundaries(gsegs, t0, t1, bin_s) + offset)
        bounds_p.append(segment_boundaries(psegs, t0, t1, bin_s) + offset)
        offset += len(g_tl)
        n_gold += len(gsegs)
        n_pred += len(psegs)

    g_tl = np.concatenate(gt_all)
    p_tl = np.concatenate(pr_all)
    gb = np.concatenate(bounds_g) if bounds_g else np.array([], dtype=int)
    pb = np.concatenate(bounds_p) if bounds_p else np.array([], dtype=int)

    # label metrics run on non-idle gold bins: we are asking whether real work
    # was labelled consistently, not whether idle time was identified
    mask = g_tl != IDLE
    gi = _codes(g_tl[mask])
    pi = _codes(p_tl[mask])

    return Result(
        n_gold=n_gold, n_pred=n_pred,
        bf1={t: boundary_prf(gb, pb, t / bin_s) for t in TOLERANCES},
        windowdiff=float(np.mean([window_diff(a, b) for a, b in zip(gt_all, pr_all)])),
        v_measure=v_measure_score(gi, pi),
        ari=adjusted_rand_score(gi, pi),
        homogeneity=homogeneity_score(gi, pi),
        completeness=completeness_score(gi, pi),
        idle_gold=float((g_tl == IDLE).mean()),
        idle_pred=float((p_tl == IDLE).mean()),
    )


def _codes(arr: np.ndarray) -> np.ndarray:
    u = {v: i for i, v in enumerate(sorted(set(arr.tolist())))}
    return np.array([u[v] for v in arr.tolist()])


def report(name: str, gold: dict, pred: dict) -> Result:
    r = evaluate(gold, pred)
    print(f"\n=== {name} ===")
    print(f"  segments        pred={r.n_pred}  gold={r.n_gold}")
    for t in TOLERANCES:
        p, rc, f = r.bf1[t]
        print(f"  boundary @{int(t):>2}s   P={p:.3f} R={rc:.3f} F1={f:.3f}")
    print(f"  WindowDiff      {r.windowdiff:.3f}   (0 = perfect)")
    print(f"  V-measure       {r.v_measure:.3f}   "
          f"(homogeneity {r.homogeneity:.3f} / completeness {r.completeness:.3f})")
    print(f"  Adjusted Rand   {r.ari:.3f}")
    print(f"  idle fraction   pred={r.idle_pred:.1%}  gold={r.idle_gold:.1%}")
    return r
