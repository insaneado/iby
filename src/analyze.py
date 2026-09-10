"""Step 2: what work is being done, by whom, how often, and what it costs.

Reads `out/segments.jsonl` - the Step 1 output - and characterises each process
so that automation candidates can be ranked on evidence.

The ranking rests on a tension, not a single number. A process is worth
automating when it carries a lot of **mechanical transfer** (copying values
between systems by hand) and little **judgment** (consulting a regulation to
decide how to handle the case). High volume with high judgment is a bad first
target however expensive it looks, because the part you cannot automate is the
part that takes the time.

Every figure here is *relative*. The brief states the recordings were made in a
test environment with compressed waiting times, so absolute durations mean
nothing and only comparisons between processes are valid.

Self-checks run on every invocation; a violated invariant prints FAIL and
should stop the analysis being trusted.
"""
from __future__ import annotations
import collections
import datetime as dt
import json

import numpy as np
import pandas as pd

from common import load_index, OUT, BUILD
from segment import event_bounds

DS = "dataset_b"
UTC = dt.timezone.utc


def load_segments(path=None) -> pd.DataFrame:
    path = path or OUT / "segments.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    d = pd.DataFrame(rows)
    d["start_ms"] = pd.to_datetime(d.start).astype("int64") // 10**6
    d["end_ms"] = pd.to_datetime(d.end).astype("int64") // 10**6
    d["dur"] = (d.end_ms - d.start_ms) / 1000.0
    return d


def enrich(seg: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-segment activity counts from the event index."""
    ev = df.sort_values("ts_ms")
    out = []
    by_sess = {sid: g for sid, g in ev.groupby("session_id")}
    for r in seg.itertuples():
        g = by_sess.get(r.session_id)
        if g is None:
            out.append({}); continue
        e = g[(g.ts_ms >= r.start_ms) & (g.ts_ms <= r.end_ms)]
        apps = collections.Counter(e.app.dropna())
        out.append({
            "machine": e.machine.dropna().iloc[0] if e.machine.notna().any() else None,
            "n_events": len(e),
            "clipboard": int((e.event_type == "clipboard_change").sum()),
            "app_switch": int((e.event_type == "app_switch").sum()),
            "keystrokes": int((e.event_type == "keystroke").sum()),
            "n_apps": len(apps),
            "excel": int(apps.get("Microsoft Excel", 0) > 0),
            "word": int(apps.get("Microsoft Word", 0) > 0),
            "notepad": int(apps.get("Notepad", 0) > 0),
        })
    return pd.concat([seg.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def self_checks(seg: pd.DataFrame, df: pd.DataFrame) -> bool:
    """Invariants that must hold for the analysis to mean anything."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"    [{'OK  ' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")

    check("all segments have positive duration", (seg.dur > 0).all(),
          f"min={seg.dur.min():.0f}s")
    check("no segment extends beyond its session",
          all(seg.groupby("session_id").end_ms.max()
              <= df.groupby("session_id").ts_ms.max()))
    ov = 0
    for sid, g in seg.groupby("session_id"):
        g = g.sort_values("start_ms")
        ov += int((g.start_ms.values[1:] < g.end_ms.values[:-1]).sum())
    check("no overlapping segments", ov == 0, f"overlaps={ov}")
    check("every session represented",
          seg.session_id.nunique() == df.session_id.nunique(),
          f"{seg.session_id.nunique()}/{df.session_id.nunique()}")
    total_span = sum((b - a).total_seconds() for a, b in event_bounds(DS).values())
    check("segment time does not exceed session time",
          seg.dur.sum() <= total_span * 1.001,
          f"{seg.dur.sum()/60:.0f}min of {total_span/60:.0f}min")
    term = df[df.el_tag == "button"]
    check("segment count is close to terminator count",
          abs(len(seg) - len(term)) / max(len(term), 1) < 0.25,
          f"{len(seg)} segments vs {len(term)} terminators")
    return ok


def profile(seg: pd.DataFrame) -> pd.DataFrame:
    g = seg.groupby("label")
    p = pd.DataFrame({
        "n": g.size(),
        "total_min": g.dur.sum() / 60,
        "median_s": g.dur.median(),
        "iqr_s": g.dur.quantile(.75) - g.dur.quantile(.25),
        "people": g.machine.nunique(),
        "sessions": g.session_id.nunique(),
        "clip_per_run": g.clipboard.mean(),
        "switch_per_run": g.app_switch.mean(),
        "keys_per_run": g.keystrokes.mean(),
        "pct_word": g.word.mean() * 100,
        "pct_excel": g.excel.mean() * 100,
    })
    p["share_%"] = 100 * p.total_min / p.total_min.sum()
    # relative regularity: lower spread = more repeatable = easier to automate
    p["cv"] = (g.dur.std() / g.dur.mean()).round(2)
    return p.sort_values("total_min", ascending=False)


if __name__ == "__main__":
    df = load_index(DS)
    seg = enrich(load_segments(), df)

    print("SELF-CHECKS")
    ok = self_checks(seg, df)
    print(f"  -> {'all invariants hold' if ok else 'INVARIANT VIOLATED - do not trust what follows'}\n")

    print(f"dataset B: {len(seg)} segments, {seg.session_id.nunique()} sessions, "
          f"{seg.machine.nunique()} operators, {seg.dur.sum()/60:.0f} min of work\n")

    p = profile(seg)
    pd.set_option("display.width", 200)
    print(p[["n", "total_min", "share_%", "median_s", "cv", "people",
             "clip_per_run", "switch_per_run", "pct_word"]].round(1).to_string())

    print("\nper-operator spread (are these shared processes or one person's job?)")
    x = pd.crosstab(seg.label, seg.machine)
    print(x.to_string())
