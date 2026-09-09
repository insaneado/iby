"""Naive baselines, to establish a floor and to validate the scorer.

The gold-vs-gold run is the important one: if scoring the ground truth against
itself does not come out perfect, the harness is broken and every number after
it is fiction.

The rest are the approaches a reasonable person would try first. Their job is to
be beaten - but knowing *by how much* is what makes the real segmenter's score
meaningful rather than a number floating in space.
"""
from __future__ import annotations
import datetime as dt

import pandas as pd

from common import load_index
from gold import Segment, load_gold
from evaluate import report

UTC = dt.timezone.utc


def _ts(ms) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000, tz=UTC)


def _emit(sid, rows, t0, t1, label_fn) -> list[Segment]:
    """Turn groups of consecutive event rows into segments."""
    segs = []
    for grp in rows:
        if not grp:
            continue
        a, b = _ts(grp[0][0]), _ts(grp[-1][0])
        if b <= a:
            b = a + dt.timedelta(seconds=1)
        segs.append(Segment(session_id=sid, start=max(a, t0),
                            end=min(b, t1), label=label_fn(grp)))
    return [s for s in segs if s.end > s.start]


def split_on_gap(df: pd.DataFrame, gold: dict, gap_s: float, by_app=False) -> dict:
    """Start a new segment whenever the idle gap exceeds `gap_s`."""
    out = {}
    for sid, (_, t0, t1) in gold.items():
        d = df[df.session_id == sid]
        if d.empty:
            out[sid] = []
            continue
        groups, cur = [], []
        for ts, gap, app in zip(d.ts_ms.values, d.gap_ms.values, d.app.values):
            if cur and (gap or 0) > gap_s * 1000:
                groups.append(cur)
                cur = []
            cur.append((ts, app))
        groups.append(cur)
        label = ((lambda g: f"app_{_mode([x[1] for x in g])}") if by_app
                 else (lambda g: "work"))
        out[sid] = _emit(sid, groups, t0, t1, label)
    return out


def split_on_app_switch(df: pd.DataFrame, gold: dict) -> dict:
    """Start a new segment on every change of foreground application."""
    out = {}
    for sid, (_, t0, t1) in gold.items():
        d = df[df.session_id == sid]
        if d.empty:
            out[sid] = []
            continue
        groups, cur, prev = [], [], None
        for ts, app in zip(d.ts_ms.values, d.app.values):
            if cur and app != prev and app is not None:
                groups.append(cur)
                cur = []
            cur.append((ts, app))
            prev = app if app is not None else prev
        groups.append(cur)
        out[sid] = _emit(sid, groups, t0, t1,
                         lambda g: f"app_{_mode([x[1] for x in g])}")
    return out


def one_per_session(gold: dict) -> dict:
    return {sid: [Segment(session_id=sid, start=t0, end=t1, label="work")]
            for sid, (_, t0, t1) in gold.items()}


def _mode(xs):
    xs = [x for x in xs if x is not None]
    return max(set(xs), key=xs.count) if xs else "none"


if __name__ == "__main__":
    gold = load_gold("dataset_a")
    df = load_index("dataset_a")
    df = df[df.event_type != "screenshot_smart"]      # L1 captures are not operator actions

    # 1. harness validation - must be perfect
    report("SANITY gold vs gold", gold, {k: v[0] for k, v in gold.items()})

    # 2. floors
    report("one segment per session", gold, one_per_session(gold))
    for g in (2, 3, 5, 10):
        report(f"gap > {g}s", gold, split_on_gap(df, gold, g))
    report("gap > 3s, label by app", gold, split_on_gap(df, gold, 3, by_app=True))
    report("every app switch", gold, split_on_app_switch(df, gold))
