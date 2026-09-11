"""Turn case anchors into segments.

Anchors are sparse and precise: roughly one every few seconds, ~92% of them
inside the right execution, covering ~61% of executions. Segments need to be
dense and to have boundaries in the right *place*. Three stages get from one to
the other.

1. ASSIGN     every second of the session takes the case of the nearest anchor,
              within `max_dist`. Beyond that, no claim is made and the time is
              left IDLE - a segmenter that tiles the whole timeline is wrong by
              construction, since ~5% of gold wall time belongs to no process.

2. SNAP       a boundary implied by "nearest anchor" falls at the midpoint
              between two anchors, which is not where work actually changed.
              Each boundary is moved to the nearest structural transition -
              an app switch, a browser navigation, a window title change -
              within `snap_window`. This is where the accuracy is: those
              transitions are the observable trace of the worker turning to a
              new task.

3. FILTER     runs shorter than `min_len` are dropped. Gold executions have a
              p10 duration of 23 s, so a 4-second segment ought to be noise.

              Measured, this stage does not earn its place: min_len=8 s costs
              ~0.008 BF1@5s and ~0.008 WindowDiff against min_len=0, because
              the runs it removes were mostly landing on real boundaries. The
              default is therefore 0 - the parameter is kept so the ablation
              stays reproducible, not because it helps.

Parameters were tuned on a 32-session dev split and verified on the 31 held-out
sessions; test scores match or slightly exceed dev, and the optimum is flat
between max_dist 60-120 s, so this is a plateau rather than a tuned point.
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

from common import load_index
from gold import IDLE, Segment
from caseid import anchors as extract_anchors, case_prefix

UTC = dt.timezone.utc

# Events that mark a genuine change of context, used for boundary snapping.
STRUCTURAL = ("app_switch", "browser_navigation", "window_title_change")

MAX_DIST = 90.0        # s - furthest an anchor may speak for a moment in time
SNAP_WINDOW = 6.0      # s - how far a boundary may move to reach a transition
MIN_LEN = 0.0          # s - measured: filtering does not help (see above)


def _structural_times(df: pd.DataFrame, sid: str) -> np.ndarray:
    d = df[(df.session_id == sid) & (df.event_type.isin(STRUCTURAL))]
    return np.sort(d.ts_ms.values.astype(np.int64))


def segment_session(sid: str, anc: pd.DataFrame, df: pd.DataFrame,
                    t0: dt.datetime, t1: dt.datetime,
                    max_dist: float = MAX_DIST, snap_window: float = SNAP_WINDOW,
                    min_len: float = MIN_LEN, labeller=case_prefix) -> list[Segment]:
    a = anc[anc.session_id == sid].sort_values("ts_ms")
    if a.empty:
        return []
    ats = a.ts_ms.values.astype(np.int64)
    acase = a.case.values

    start_ms = int(t0.timestamp() * 1000)
    end_ms = int(t1.timestamp() * 1000)
    grid = np.arange(start_ms, end_ms + 1000, 1000, dtype=np.int64)

    # 1. assign - nearest anchor within max_dist
    idx = np.searchsorted(ats, grid)
    idx = np.clip(idx, 0, len(ats) - 1)
    left = np.clip(idx - 1, 0, len(ats) - 1)
    d_r = np.abs(ats[idx] - grid)
    d_l = np.abs(ats[left] - grid)
    pick = np.where(d_l <= d_r, left, idx)
    dist = np.minimum(d_l, d_r) / 1000.0
    lab = np.where(dist <= max_dist, acase[pick], IDLE)

    # 2. runs -> spans
    change = np.flatnonzero(lab[1:] != lab[:-1]) + 1
    bounds = np.concatenate([[0], change, [len(lab)]])
    struct = _structural_times(df, sid)

    def snap(ms: int) -> int:
        if len(struct) == 0:
            return ms
        j = int(np.searchsorted(struct, ms))
        cand = [struct[k] for k in (j - 1, j) if 0 <= k < len(struct)]
        if not cand:
            return ms
        best = min(cand, key=lambda x: abs(int(x) - ms))
        return int(best) if abs(int(best) - ms) <= snap_window * 1000 else ms

    segs = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        case = lab[lo]
        if case == IDLE:
            continue
        s_ms, e_ms = snap(int(grid[lo])), snap(int(grid[min(hi, len(grid) - 1)]))
        if (e_ms - s_ms) / 1000.0 < min_len:
            continue
        seg = Segment(
            session_id=sid,
            start=dt.datetime.fromtimestamp(s_ms / 1000, tz=UTC),
            end=dt.datetime.fromtimestamp(e_ms / 1000, tz=UTC),
            label="", case_id=case)
        # A labeller may work from the case id (cheap, but assumes the id
        # encodes its process) or from the segment's activity (transferable).
        # Both are supported so the two can be compared on equal terms.
        seg.label = (labeller(seg) if getattr(labeller, "takes_segment", False)
                     else labeller(case))
        segs.append(seg)
    return segs


def event_bounds(ds: str) -> dict:
    """Session windows derived from the event stream alone.

    Dataset A's `gt_manifest.json` also carries session start/end, and using it
    was tempting - but dataset B has no manifest, so that would score A with
    information the real run does not have. The two disagree by a mean of 10 s
    at the start and 91 s at the end (max 962 s), so it is a genuine difference,
    not a rounding one.

    Measured, it changes nothing (BF1@5s 0.463 vs 0.464): the anchors do the
    work and the bounds only pad the edges with idle. Switched anyway, because
    "it happened not to matter this time" is not a reason to keep ground truth
    on the inference path.
    """
    df = load_index(ds)
    return {sid: (dt.datetime.fromtimestamp(g.ts_ms.min() / 1000, tz=UTC),
                  dt.datetime.fromtimestamp(g.ts_ms.max() / 1000, tz=UTC))
            for sid, g in df.groupby("session_id")}


def segment_dataset(ds: str, bounds: dict | None = None, labeller=case_prefix,
                    **kw) -> dict:
    """bounds: {session_id: (t0, t1)}, defaulting to event-derived windows."""
    if bounds is None:
        bounds = event_bounds(ds)
    anc = extract_anchors(ds)
    df = load_index(ds)
    return {sid: segment_session(sid, anc, df, t0, t1, labeller=labeller, **kw)
            for sid, (t0, t1) in bounds.items()}


if __name__ == "__main__":
    from gold import load_gold
    from evaluate import report

    gold = load_gold("dataset_a")
    # Event-derived windows, as the pipeline uses - not the manifest's session
    # bounds, which this demo once passed in, contradicting event_bounds above.
    bounds = event_bounds("dataset_a")

    report("v1 anchors + snap", gold, segment_dataset("dataset_a", bounds))

    # ablations - which stage is actually earning its place?
    report("v1 without snapping", gold,
           segment_dataset("dataset_a", bounds, snap_window=0.0))
    # MIN_LEN is 0, so the filter is off by default; this shows what it cost.
    report("v1 with an 8 s minimum length", gold,
           segment_dataset("dataset_a", bounds, min_len=8.0))
    for md in (15.0, 40.0):
        report(f"v1 max_dist={md}s", gold,
               segment_dataset("dataset_a", bounds, max_dist=md))
