"""Where inside the gap does a real boundary fall? Midpoint vs length-proportional.

v4 places the boundary between a confirm press and the next row click at the
gap's midpoint. The unobserved head (before the row click) and tail (after the
confirm) of a unit scale with its length, so the parameter-free alternative
splits the gap in proportion to the two neighbouring brackets' lengths.

Only adjacent gold executions with no idle between them, each containing exactly
one row click and one confirm press, are used - there the true boundary is one
instant. Reported separately on the overfit audit's dev and test halves (same
seed), so a win has to hold on both. Read-only.
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
from label import SignatureLabeller
from segment import event_bounds
from segment_v4 import segment_dataset_v4

gold = load_gold("dataset_a")
df = load_index("dataset_a")

sids = sorted(gold)
random.Random(0).shuffle(sids)
half = {s: "dev" for s in sids[:32]} | {s: "test" for s in sids[32:]}

err = collections.defaultdict(lambda: {"mid": [], "prop": []})
for sid, (gs, _, _) in gold.items():
    d = df[df.session_id == sid]
    opens = np.sort(d[d.el_tag == "td"].ts_ms.values.astype(np.int64))
    closes = np.sort(d[d.el_tag == "button"].ts_ms.values.astype(np.int64))
    gs = sorted(gs, key=lambda g: g.start)
    brackets = []
    for g in gs:
        a, b = int(g.start.timestamp() * 1000), int(g.end.timestamp() * 1000)
        o = opens[(opens >= a) & (opens <= b)]
        c = closes[(closes >= a) & (closes <= b)]
        brackets.append((int(o[0]), int(c[0])) if len(o) == 1 and len(c) == 1 and o[0] < c[0] else None)
    for i in range(len(gs) - 1):
        g1, g2, b1, b2 = gs[i], gs[i + 1], brackets[i], brackets[i + 1]
        if b1 is None or b2 is None:
            continue
        if abs((g2.start - g1.end).total_seconds()) > 1:          # idle between: no single true boundary
            continue
        truth = g1.end.timestamp() * 1000
        c1, o2 = b1[1], b2[0]
        if o2 <= c1:
            continue
        l1, l2 = b1[1] - b1[0], b2[1] - b2[0]
        mid = (c1 + o2) / 2
        prop = c1 + (o2 - c1) * l1 / (l1 + l2)
        for k in (half[sid], "all"):
            err[k]["mid"].append(abs(mid - truth) / 1000)
            err[k]["prop"].append(abs(prop - truth) / 1000)

print("boundary placement error against the true boundary (seconds)\n")
print(f"  {'half':5} {'pairs':>6}   {'rule':12} {'median':>7} {'within 2 s':>11} {'within 5 s':>11}")
for k in ("dev", "test", "all"):
    for rule, name in (("mid", "midpoint"), ("prop", "proportional")):
        e = np.array(err[k][rule])
        print(f"  {k:5} {len(e):6d}   {name:12} {np.median(e):7.2f} {100 * np.mean(e <= 2):10.1f}% {100 * np.mean(e <= 5):10.1f}%")

# how do bracketed executions miss: no material overlap, or two or more?
pred = segment_dataset_v4("dataset_a", event_bounds("dataset_a"),
                          labeller=SignatureLabeller("dataset_a"), expand_gap_s=60)
kinds = collections.Counter()
for sid, (gs, _, _) in gold.items():
    d = df[df.session_id == sid]
    opens = d[d.el_tag == "td"].ts_ms.values
    closes = d[d.el_tag == "button"].ts_ms.values
    for g in gs:
        a, b = g.start.timestamp() * 1000, g.end.timestamp() * 1000
        if not (((opens >= a) & (opens <= b)).any() and ((closes >= a) & (closes <= b)).any()):
            continue
        ovs = [max(0.0, (min(g.end, p.end) - max(g.start, p.start)).total_seconds()) for p in pred.get(sid, [])]
        k = sum(1 for o in ovs if o >= 0.10 * g.duration)
        kinds["maps to one" if k == 1 else "no material overlap" if k == 0 else "two or more"] += 1
print(f"\nbracketed executions: {dict(kinds)}")
