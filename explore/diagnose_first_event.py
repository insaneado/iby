"""Is there an observable event that marks where a unit begins, inside the gap?

For adjacent gold executions with no idle between them, each bracketed by one
row click and one confirm press, the true boundary sits somewhere between the
first unit's confirm press and the second's row click. v4 uses the midpoint.

This looks at which event actually opens each unit - the first event at or after
the true boundary - and how close its timestamp sits to the boundary. The
candidate event type is chosen on the dev half ONLY (the overfit audit's seed-0
split); the rule "boundary at the first such event after the confirm press" is
then scored against the midpoint on the test half, which played no part in the
choice. Read-only.
"""
import collections
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from common import load_index
from gold import load_gold

gold = load_gold("dataset_a")
df = load_index("dataset_a")
sids = sorted(gold)
random.Random(0).shuffle(sids)
half = {s: "dev" for s in sids[:32]} | {s: "test" for s in sids[32:]}

first = collections.defaultdict(collections.Counter)
offsets = collections.defaultdict(list)
pairs = []
for sid, (gs, _, _) in gold.items():
    d = df[df.session_id == sid].sort_values("ts_ms")
    ts = d.ts_ms.values.astype(np.int64)
    key = (d.event_type.astype(str) + ":" + d.el_tag.fillna("-").astype(str)).values
    opens, closes = ts[d.el_tag.values == "td"], ts[d.el_tag.values == "button"]
    gs = sorted(gs, key=lambda g: g.start)
    br = []
    for g in gs:
        a, b = int(g.start.timestamp() * 1000), int(g.end.timestamp() * 1000)
        o, c = opens[(opens >= a) & (opens <= b)], closes[(closes >= a) & (closes <= b)]
        br.append((int(o[0]), int(c[0])) if len(o) == 1 and len(c) == 1 and o[0] < c[0] else None)
    for i in range(len(gs) - 1):
        g1, g2, b1, b2 = gs[i], gs[i + 1], br[i], br[i + 1]
        if b1 is None or b2 is None or abs((g2.start - g1.end).total_seconds()) > 1:
            continue
        truth, c1, o2 = int(g2.start.timestamp() * 1000), b1[1], b2[0]
        if o2 <= c1:
            continue
        j = int(np.searchsorted(ts, truth))
        if j < len(ts):
            first[half[sid]][key[j]] += 1
            offsets[key[j]].append((ts[j] - truth) / 1000)
        lo, hi = int(np.searchsorted(ts, c1, side="right")), int(np.searchsorted(ts, o2))
        pairs.append((half[sid], c1, o2, truth, list(zip(ts[lo:hi], key[lo:hi]))))

print("the first event at or after each true boundary - dev half:")
for k, n in first["dev"].most_common(6):
    off = np.array(offsets[k])
    print(f"  {k:32} {n:4d}   offset from the boundary: median {np.median(off):6.2f} s, "
          f"within 0.5 s {100 * np.mean(np.abs(off) <= 0.5):5.1f}%")
T = first["dev"].most_common(1)[0][0]
print(f"\ncandidate chosen on dev: {T}")
print(f"  (the same count on test, for information: {first['test'][T]} of {sum(first['test'].values())})\n")

for h in ("dev", "test"):
    em, et, have, count = [], [], 0, []
    for hh, c1, o2, truth, gap in pairs:
        if hh != h:
            continue
        mid = (c1 + o2) / 2
        cand = [t for t, k in gap if k == T]
        count.append(len(cand))
        have += bool(cand)
        em.append(abs(mid - truth) / 1000)
        et.append(abs((cand[0] if cand else mid) - truth) / 1000)
    em, et = np.array(em), np.array(et)
    print(f"  {h:4}: {len(em)} pairs; gaps holding one: {100 * have / len(em):.0f}% "
          f"(median {np.median(count):.0f} per gap)")
    print(f"        midpoint           within 2 s {100 * np.mean(em <= 2):5.1f}%   within 5 s {100 * np.mean(em <= 5):5.1f}%")
    print(f"        first {T[:20]:20} within 2 s {100 * np.mean(et <= 2):5.1f}%   within 5 s {100 * np.mean(et <= 5):5.1f}%")
