"""v4: bracket each unit of work between its opening and closing click.

v3 used the confirm button to fix the END of a unit and inferred the start by
walking back a fixed window. The evaluator audit showed that was the remaining
defect: only 35.6% of gold executions overlapped exactly one predicted segment,
with 1,216 of 2,009 split roughly 88/12 across two. Ends were right; starts were
approximate.

Both edges are observable. Selecting a record from the worklist is a click on a
table cell, and on dataset A those 1,780 clicks land inside a gold execution
99.9% of the time, at median relative position **0.13**, with 98% in the first
third and exactly one in 1,722 of 1,750 executions. The confirm press sits at
0.89. A unit of work is the interval between them.

    row click  ──────── work ────────▶  confirm press
      p50 = 0.13                          p50 = 0.89

So v4 pairs each confirm with the most recent unclaimed row click before it, and
falls back to v3's window only where no such click exists.
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

from common import load_index
from gold import Segment
from caseid import anchors as extract_anchors, case_prefix
from segment import event_bounds, segment_session
from segment_v3 import MAX_UNIT_S, MIN_UNIT_S

UTC = dt.timezone.utc

# Structural, not lexical - a clicked table cell is a record selection, and a
# button is a terminal action. Matching on element names instead cost a day:
# dataset B's `btn-*-ok` matched zero rows in dataset A.
OPEN_TAG = "td"
CLOSE_TAG = "button"


def brackets(df: pd.DataFrame, sid: str):
    d = df[df.session_id == sid]
    opens = np.sort(d[d.el_tag == OPEN_TAG].ts_ms.values.astype(np.int64))
    closes = np.sort(d[d.el_tag == CLOSE_TAG].ts_ms.values.astype(np.int64))
    return opens, closes


def segment_session_v4(sid, anc, df, t0, t1, labeller,
                       max_unit_s=MAX_UNIT_S, min_unit_s=MIN_UNIT_S,
                       expand_gap_s=30.0, fallback=True, **v1kw) -> list[Segment]:
    ev = df[df.session_id == sid].sort_values("ts_ms")
    ts = ev.ts_ms.values.astype(np.int64)
    opens, closes = brackets(df, sid)
    if len(closes) == 0:
        v1 = segment_session(sid, anc, df, t0, t1, labeller=labeller, **v1kw)
        return [s for s in v1 if s.duration >= max(min_unit_s, 1.0)] if fallback else []

    a_sess = anc[anc.session_id == sid].sort_values("ts_ms")
    a_ts = a_sess.ts_ms.values.astype(np.int64)
    a_case = a_sess.case.values

    segs: list[Segment] = []
    prev_end = int(t0.timestamp() * 1000)
    used = 0                                   # opens consumed so far
    for close in closes:
        window_start = max(prev_end, int(close - max_unit_s * 1000))
        # the most recent row click after the previous unit and before this close
        cand = opens[(opens >= window_start) & (opens < close)]
        cand = cand[cand >= prev_end]
        if len(cand):
            lo = int(cand[-1])                 # latest such click opens this unit
            used += 1
        else:
            lo = window_start
            i = int(np.searchsorted(ts, lo))   # trim leading idle
            if i < len(ts) and ts[i] <= close:
                lo = int(ts[i])
        if (close - lo) / 1000.0 < min_unit_s:
            prev_end = int(close)
            continue

        m = (a_ts >= lo) & (a_ts <= close)
        if m.any():
            case = pd.Series(a_case[m]).mode().iloc[0]
        elif len(a_ts):
            case = a_case[int(np.clip(np.searchsorted(a_ts, close) - 1, 0, len(a_ts) - 1))]
        else:
            case = "?"

        seg = Segment(session_id=sid,
                      start=dt.datetime.fromtimestamp(lo / 1000, tz=UTC),
                      end=dt.datetime.fromtimestamp(close / 1000, tz=UTC),
                      label="", case_id=str(case))
        seg.label = (labeller(seg) if getattr(labeller, "takes_segment", False)
                     else labeller(str(case)))
        segs.append(seg)
        prev_end = int(close)

    # The bracket sits strictly INSIDE the true unit: the row click is at
    # relative position 0.13 and the confirm at 0.89, so ~13% of the work
    # precedes the click and ~11% follows the press. Taking the bracket
    # literally drops that time out as idle - measured at 36.7% against a true
    # 5.0%, which would understate every process duration by a third.
    #
    # Each pair is therefore expanded to the midpoint of the gap on either
    # side, capped so a genuine pause is not swallowed. Boundaries stay near
    # the observed clicks; the time in between is attributed rather than lost.
    # Expansions are computed from the ORIGINAL edges and applied afterwards.
    # Mutating in place while iterating reads neighbours that have already
    # moved, which produced 14 overlapping segments on dataset B - caught by the
    # Step 2 invariants rather than by inspection.
    if segs and expand_gap_s > 0:
        orig = [(s.start, s.end) for s in segs]
        for i, s in enumerate(segs):
            prev_e = orig[i - 1][1] if i else t0
            next_s = orig[i + 1][0] if i + 1 < len(orig) else t1
            back = min((orig[i][0] - prev_e).total_seconds() / 2, expand_gap_s)
            fwd = min((next_s - orig[i][1]).total_seconds() / 2, expand_gap_s)
            if back > 0:
                s.start = orig[i][0] - dt.timedelta(seconds=back)
            if fwd > 0:
                s.end = orig[i][1] + dt.timedelta(seconds=fwd)

    if fallback and prev_end < int(t1.timestamp() * 1000):
        tail_t0 = dt.datetime.fromtimestamp(prev_end / 1000, tz=UTC)
        # The tail is appended after expansion, so it must clear the last
        # expanded segment, not the last unexpanded one.
        floor = max([s.end for s in segs], default=tail_t0)
        for s in segment_session(sid, anc, df, tail_t0, t1, labeller=labeller, **v1kw):
            if s.start < floor:
                s.start = floor
            if s.end > t1:
                s.end = t1
            if s.duration >= max(min_unit_s, 1.0):
                segs.append(s)
                floor = s.end
    return sorted(segs, key=lambda s: s.start)


def segment_dataset_v4(ds: str, bounds=None, labeller=case_prefix, **kw) -> dict:
    bounds = bounds or event_bounds(ds)
    anc = extract_anchors(ds)
    df = load_index(ds)
    return {sid: segment_session_v4(sid, anc, df, t0, t1, labeller, **kw)
            for sid, (t0, t1) in bounds.items()}


if __name__ == "__main__":
    from gold import load_gold
    from evaluate import report
    from label import SignatureLabeller
    from segment_v3 import segment_dataset_v3

    gold = load_gold("dataset_a")
    b = event_bounds("dataset_a")
    lab = SignatureLabeller("dataset_a")
    report("v3  confirm-click ends only", gold,
           segment_dataset_v3("dataset_a", b, labeller=lab))
    # The shipped configuration, as run_dataset_b.py writes the deliverable.
    # Leaving expand_gap_s at the function default (30) printed a WindowDiff,
    # V-measure and idle share that disagreed with every table quoting this run.
    report("v4  bracketed by open and close", gold,
           segment_dataset_v4("dataset_a", b, labeller=lab, expand_gap_s=60))
