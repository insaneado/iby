"""v3: terminator-driven segmentation.

v1 assigned every moment to its nearest case anchor and let runs of the same
case become segments. That merges consecutive units of work whenever they share
an anchor value - the dataset B failure, where the anchors are employee ids that
persist across units.

v3 inverts the design. Every portal screen ends a unit of work with a button
press, and on dataset A 1,751 of the 1,752 presses land inside a gold segment -
never two in one, though 258 segments hold none - at median relative position
0.89. So the press is an
almost exact statement of "a unit ended here" - far stronger than anything
inferred. The terminator therefore defines the segment END; anchors supply case
identity; the signature supplies the label.

Two details this has to get right:

*Where a unit starts.* Taking the previous terminator as the start makes the
timeline fully contiguous, which is wrong - roughly 5% of gold wall time belongs
to no process. Units are capped at `max_unit_s` and trimmed to the first real
event, so a long idle stretch before a press is not swallowed into it.

*Units with no terminator.* 258 of dataset A's 2,009 gold executions (12.8%)
hold no press. Most are ordinary executions with a recorded end - only 25 are
resumed phases, and 32 run past a recording boundary - so the press is simply
not there. Stretches with anchor evidence but no press still need boundaries,
so v1's anchor logic is retained as a fallback rather than replaced.
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

from common import load_index
from gold import Segment
from caseid import anchors as extract_anchors, case_prefix
from segment import event_bounds, segment_session

UTC = dt.timezone.utc

# Matched on the prefix, not the full name: dataset A names these semantically
# (btn-la-approve, btn-rt-query) and dataset B uniformly (btn-la-ok). Matching
# dataset B's exact names against dataset A found zero, and hid the signal.
TERMINATOR_PREFIX = "btn-"

MAX_UNIT_S = 200.0      # s - chosen for idle calibration, not peak BF1: see RESULTS.md
MIN_UNIT_S = 3.0


def terminators(df: pd.DataFrame, sid: str) -> pd.DataFrame:
    d = df[(df.session_id == sid) & df.el_id.notna()]
    d = d[d.el_id.astype(str).str.startswith(TERMINATOR_PREFIX)]
    return d.sort_values("ts_ms")


def segment_session_v3(sid, anc, df, t0, t1, labeller,
                       max_unit_s=MAX_UNIT_S, min_unit_s=MIN_UNIT_S,
                       fallback=True, **v1kw) -> list[Segment]:
    ev = df[df.session_id == sid].sort_values("ts_ms")
    ts = ev.ts_ms.values.astype(np.int64)
    term = terminators(df, sid)
    if term.empty:
        # A session with no L3 layer at all has no terminators. v1's min_len
        # default is 0, which emitted three zero-length segments here, so the
        # floor is applied explicitly rather than relying on the caller.
        v1 = segment_session(sid, anc, df, t0, t1, labeller=labeller, **v1kw)
        return [s for s in v1 if s.duration >= max(min_unit_s, 1.0)] if fallback else []

    a_sess = anc[anc.session_id == sid].sort_values("ts_ms")
    a_ts = a_sess.ts_ms.values.astype(np.int64)
    a_case = a_sess.case.values

    segs: list[Segment] = []
    prev_end = int(t0.timestamp() * 1000)
    for t_ms in term.ts_ms.values.astype(np.int64):
        lo = max(prev_end, int(t_ms - max_unit_s * 1000))
        # trim leading idle: start at the first real event at or after `lo`
        i = int(np.searchsorted(ts, lo))
        if i < len(ts) and ts[i] <= t_ms:
            lo = int(ts[i])
        if (t_ms - lo) / 1000.0 < min_unit_s:
            prev_end = int(t_ms)
            continue
        # case identity: the anchor closest to this unit's own span
        m = (a_ts >= lo) & (a_ts <= t_ms)
        if m.any():
            case = pd.Series(a_case[m]).mode().iloc[0]
        elif len(a_ts):
            case = a_case[int(np.clip(np.searchsorted(a_ts, t_ms) - 1, 0, len(a_ts) - 1))]
        else:
            case = "?"
        seg = Segment(session_id=sid,
                      start=dt.datetime.fromtimestamp(lo / 1000, tz=UTC),
                      end=dt.datetime.fromtimestamp(t_ms / 1000, tz=UTC),
                      label="", case_id=str(case))
        seg.label = (labeller(seg) if getattr(labeller, "takes_segment", False)
                     else labeller(str(case)))
        segs.append(seg)
        prev_end = int(t_ms)

    # tail: work after the last terminator that never got one
    if fallback and prev_end < int(t1.timestamp() * 1000):
        tail_t0 = dt.datetime.fromtimestamp(prev_end / 1000, tz=UTC)
        for s in segment_session(sid, anc, df, tail_t0, t1, labeller=labeller, **v1kw):
            # v1 snaps boundaries to structural transitions, which can pull a
            # start up to snap_window earlier than the window it was given -
            # producing a segment that overlaps the final terminator segment.
            # Clamp rather than drop: the work is real, only its edge is wrong.
            if s.start < tail_t0:
                s.start = tail_t0
            if s.end > t1:
                s.end = t1
            if s.duration >= max(min_unit_s, 1.0):
                segs.append(s)
    return segs


def segment_dataset_v3(ds: str, bounds=None, labeller=case_prefix, **kw) -> dict:
    bounds = bounds or event_bounds(ds)
    anc = extract_anchors(ds)
    df = load_index(ds)
    return {sid: segment_session_v3(sid, anc, df, t0, t1, labeller, **kw)
            for sid, (t0, t1) in bounds.items()}


if __name__ == "__main__":
    from gold import load_gold
    from evaluate import report
    from label import SignatureLabeller

    gold = load_gold("dataset_a")
    b = event_bounds("dataset_a")
    lab = SignatureLabeller("dataset_a")
    report("v3 terminator-driven, signature labels", gold,
           segment_dataset_v3("dataset_a", b, labeller=lab))
    report("v3 without the v1 fallback", gold,
           segment_dataset_v3("dataset_a", b, labeller=lab, fallback=False))
