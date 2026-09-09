"""Build the gold segment set from dataset A's ground truth.

`gt_manifest.json` is the primary source: it lists one entry per *execution* of
a process, already resolved to start/end timestamps. Validation (see NOTES.md)
showed it is internally consistent - 2,009 executions, zero overlapping pairs,
and 1,819 phase-1 + 190 resumed entries reconciling exactly with the
`process_started` / `process_resumed` counts in `gt.jsonl`.

Two properties of the gold set drive the whole evaluation design:

1. Gold segments cover only ~82% of session wall time. The remaining ~18% is
   work that belongs to no business process. Any segmenter that tiles the
   entire timeline is therefore wrong on ~18% of it by construction, so the
   evaluation carries an explicit IDLE class rather than assuming full cover.

2. The median gap between consecutive gold segments is 0.0 s - half of all true
   boundaries have no pause at all. Boundary metrics must therefore be scored
   with a tolerance window, and idle-gap heuristics cannot be the basis of a
   segmenter.
"""
from __future__ import annotations
import json
import datetime as dt
from dataclasses import dataclass, asdict

from common import sessions, load_gt_manifest

IDLE = "__idle__"


def parse_ts(t: str) -> dt.datetime:
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


@dataclass
class Segment:
    session_id: str
    start: dt.datetime
    end: dt.datetime
    label: str
    case_id: str | None = None
    variant: str | None = None
    phase: int | None = None
    inferred_end: bool = False

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds()

    def to_jsonl(self) -> str:
        d = {
            "session_id": self.session_id,
            "start": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": self.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "label": self.label,
        }
        return json.dumps(d, ensure_ascii=False)


def _session_bounds(manifest) -> tuple[dt.datetime, dt.datetime]:
    s = manifest.get("session") or {}
    return parse_ts(s["start_ts"]), parse_ts(s["end_ts"])


def gold_segments(session_dir) -> tuple[list[Segment], dt.datetime, dt.datetime]:
    """Gold segments for one session, sorted by start time.

    Executions with a null `end_ts` continue past a recording boundary. Rather
    than drop 12.8% of the gold set, the end is inferred as the start of the
    next execution in the session (capped at session end) and flagged with
    `inferred_end`, so metrics can be reported with and without them.
    """
    m = load_gt_manifest(session_dir)
    if m is None:
        return [], None, None
    t0, t1 = _session_bounds(m)

    raw = []
    for proc in m.get("processes", []):
        for e in proc.get("executions", []):
            if not e.get("start_ts"):
                continue
            raw.append((parse_ts(e["start_ts"]), e, proc["code"]))
    raw.sort(key=lambda r: r[0])

    segs = []
    for i, (start, e, code) in enumerate(raw):
        if e.get("end_ts"):
            end, inferred = parse_ts(e["end_ts"]), False
        else:
            nxt = raw[i + 1][0] if i + 1 < len(raw) else t1
            end, inferred = min(nxt, t1), True
        if end <= start:
            continue
        segs.append(Segment(
            session_id=session_dir.name, start=start, end=end, label=code,
            case_id=e.get("case_id"), variant=e.get("variant"),
            phase=e.get("phase"), inferred_end=inferred,
        ))
    return segs, t0, t1


def load_gold(ds="dataset_a") -> dict:
    """{session_id: (segments, session_start, session_end)} for every session."""
    out = {}
    for s in sessions(ds):
        segs, t0, t1 = gold_segments(s)
        if segs:
            out[s.name] = (segs, t0, t1)
    return out


if __name__ == "__main__":
    g = load_gold()
    n = sum(len(v[0]) for v in g.values())
    inf = sum(1 for v in g.values() for s in v[0] if s.inferred_end)
    dur = sorted(s.duration for v in g.values() for s in v[0])
    cov = []
    for segs, t0, t1 in g.values():
        span = (t1 - t0).total_seconds()
        cov.append(sum(s.duration for s in segs) / span if span else 0)
    labels = {}
    for v in g.values():
        for s in v[0]:
            labels[s.label] = labels.get(s.label, 0) + 1
    print(f"sessions          {len(g)}")
    print(f"gold segments     {n}  ({inf} with inferred end, {100*inf/n:.1f}%)")
    print(f"distinct labels   {len(labels)}  {sorted(labels)}")
    print(f"duration (s)      p10={dur[len(dur)//10]:.0f} "
          f"p50={dur[len(dur)//2]:.0f} p90={dur[int(len(dur)*.9)]:.0f} max={dur[-1]:.0f}")
    print(f"session coverage  mean={100*sum(cov)/len(cov):.1f}%  "
          f"(so ~{100-100*sum(cov)/len(cov):.1f}% of wall time is IDLE)")
