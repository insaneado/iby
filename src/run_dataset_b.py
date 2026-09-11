"""Produce the graded deliverable: out/segments.jsonl for dataset B.

Runs the pipeline that was developed and measured on dataset A, with the
signature labeller rather than the case-prefix one - dataset B's case ids are
employee records and carry no process information.

Also prints the held-out check that once stood in for the ground truth dataset
B does not have: completion memos, Notepad text of the form
請求書照合完了。INV-2026-7345, which nothing in the pipeline reads. It was
evidence under v3, where the memos clustered near segment ends. Under v4 it is
printed beside the same measurements for random instants and no longer
discriminates - see the comment at the check. The labels' held-out evidence is
explore/label_vs_breadcrumb.py.
"""
from __future__ import annotations
import collections
import json

import numpy as np

from common import load_index, OUT
from segment import event_bounds
from segment_v4 import segment_dataset_v4
from label import SignatureLabeller

DS = "dataset_b"


def where_in_segment(ts_list, segs):
    """Relative position (0=start, 1=end) of each timestamp within its segment."""
    pos, outside = [], 0
    by_sess = collections.defaultdict(list)
    for s in segs:
        by_sess[s.session_id].append(s)
    for sid, ms in ts_list:
        hit = None
        for s in by_sess.get(sid, []):
            a, b = s.start.timestamp() * 1000, s.end.timestamp() * 1000
            if a <= ms <= b:
                hit = (ms - a) / max(b - a, 1)
                break
        if hit is None:
            outside += 1
        else:
            pos.append(hit)
    return np.array(pos), outside


def main():
    df = load_index(DS)
    segs_by_sess = segment_dataset_v4(DS, event_bounds(DS),
                                      labeller=SignatureLabeller(DS),
                                      expand_gap_s=60)
    segs = [s for v in segs_by_sess.values() for s in v]
    segs.sort(key=lambda s: (s.session_id, s.start))

    out = OUT / "segments.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(s.to_jsonl() + "\n")

    dur = sorted(s.duration for s in segs)
    q = lambda p: dur[int(len(dur) * p)]
    span = sum((b - a).total_seconds() for a, b in event_bounds(DS).values())
    labels = collections.Counter(s.label for s in segs)

    print(f"wrote {out}")
    print(f"  segments   {len(segs)} over {len(segs_by_sess)} sessions")
    print(f"  duration s p10={q(.1):.0f} p50={q(.5):.0f} p90={q(.9):.0f} max={dur[-1]:.0f}")
    print(f"  coverage   {100*sum(dur)/span:.1f}%   (dataset A gold was 94.7%)")
    print(f"  labels     {len(labels)}")
    for k, v in labels.most_common():
        d = sorted(s.duration for s in segs if s.label == k)
        print(f"     {k:34} n={v:4d}  median={d[len(d)//2]:5.0f}s  total={sum(d)/60:6.1f}min")

    # ---- held-out check ----
    # The confirm press now DEFINES the segment end, so it can no longer serve
    # as evidence: scoring it would return 1.00 by construction. Validation
    # moves to the completion memo the operator types into Notepad
    # ("請求書照合完了。INV-2026-7345"), which nothing in the pipeline reads.
    # A check is only evidence while the thing it checks cannot see it - and
    # while it can still fail. Under v3 the memos sat at median position 0.78,
    # near the segment end. v4 extends every segment to the midpoint of the gap
    # on either side, so segments cover nearly the whole session and position
    # no longer marks where one ends. The memos are therefore compared with
    # uniformly random instants: where the two look alike, this check no longer
    # discriminates and is not evidence.
    import re
    import pandas as pd
    from common import BUILD

    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))]
    done = txt[txt.text.str.len().lt(200)
               & txt.text.str.contains("完了|承認済|確定|登録済", regex=True, na=False)]
    pos, outside = where_in_segment(list(zip(done.session_id, done.ts_ms)), segs)
    print(f"\n  held-out check - {len(done)} completion memos, never read by the pipeline")
    if len(pos):
        print(f"     inside a segment: {len(pos)} ({100*len(pos)/len(done):.1f}%), "
              f"outside: {outside}")
        print(f"     relative position: median={np.median(pos):.2f} "
              f"(1.0 = segment end)  frac in last third={np.mean(pos > 2/3):.2f}")
        h, _ = np.histogram(pos, bins=10, range=(0, 1))
        print(f"     histogram 0->1: {[int(x) for x in h]}")

    # the same measurements for uniformly random instants in the same sessions
    rng = np.random.default_rng(0)
    bounds = event_bounds(DS)
    sids = sorted(bounds)
    spans = np.array([(bounds[s][1] - bounds[s][0]).total_seconds() for s in sids])
    picks = rng.choice(len(sids), size=5000, p=spans / spans.sum())
    rand = [(sids[i], bounds[sids[i]][0].timestamp() * 1000 + rng.uniform(0, spans[i]) * 1000)
            for i in picks]
    rpos, _ = where_in_segment(rand, segs)
    print(f"     chance, 5,000 random instants: inside {100*len(rpos)/len(rand):.1f}%  "
          f"median={np.median(rpos):.2f}  frac in last third={np.mean(rpos > 2/3):.2f}")

    print(f"\n  sanity: segments per session "
          f"{min(len(v) for v in segs_by_sess.values())}-"
          f"{max(len(v) for v in segs_by_sess.values())}")


if __name__ == "__main__":
    main()
