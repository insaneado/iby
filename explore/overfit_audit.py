"""Am I overfitting to dataset A?

Two tests, increasingly unkind, and a third that this data cannot support.

1. STRICT PROTOCOL. Every parameter was previously swept over all 63 sessions
   and a dev/test split reported afterwards - so the test set had already
   informed the choice. Here the sweep sees dev only, and test is scored once.
   The gap between the two protocols is the size of the self-deception.

2. LEAVE-ONE-MACHINE-OUT. A random session split is easy: the same operators
   and the same habits appear on both sides. Dataset B is a different
   department, so the relevant question is whether the method survives an
   operator it has never seen. Holding out whole machines is the closest
   available proxy.

3. LEAVE-ONE-DOMAIN-OUT - not possible on this data, and the script shows why.
   The natural version, tune on hr+finance and test on ops, would be the
   closest analogue of dataset A -> dataset B. It needs sessions that belong to
   one department, and none do: every one of dataset A's 63 sessions contains
   work from all three. The real cross-department test is the move to dataset
   B itself, checked against a signal the pipeline never reads - the portal
   breadcrumb, in label_vs_breadcrumb.py.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import random

import numpy as np

from common import load_index
from gold import load_gold
from evaluate import evaluate
from segment import event_bounds
from segment_v4 import segment_dataset_v4
from label import SignatureLabeller

GRID = [(mu, 3) for mu in (60, 90, 120, 200, 300)]

gold = load_gold("dataset_a")
bounds = event_bounds("dataset_a")
df = load_index("dataset_a")
lab = SignatureLabeller("dataset_a")

machine = {sid: df[df.session_id == sid].machine.dropna().iloc[0]
           for sid in gold if len(df[df.session_id == sid].machine.dropna())}


def score(sids, mu, mn):
    g = {k: v for k, v in gold.items() if k in sids}
    p = segment_dataset_v4("dataset_a", {k: bounds[k] for k in sids},
                           labeller=lab, max_unit_s=mu, min_unit_s=mn, expand_gap_s=60)
    return evaluate(g, p)


def best_on(sids):
    best = None
    for mu, mn in GRID:
        r = score(sids, mu, mn)
        s = r.bf1[5.0][2]
        if best is None or s > best[0]:
            best = (s, mu, mn)
    return best[1], best[2]


print("=" * 72)
print("TEST 1 - strict protocol: tune on dev only, score test once")
print("=" * 72)
sids = sorted(gold)
random.Random(0).shuffle(sids)
dev, test = set(sids[:32]), set(sids[32:])
mu, mn = best_on(dev)
print(f"  chosen on dev alone:            max_unit_s={mu} min_unit_s={mn}")
print(f"  (previously chosen on all 63:   max_unit_s=200 min_unit_s=3)")
r_dev, r_test = score(dev, mu, mn), score(test, mu, mn)
r_leak = score(test, 200, 3)
print(f"  dev                    BF1@5s={r_dev.bf1[5.0][2]:.3f} V={r_dev.v_measure:.3f}")
print(f"  test (honest)          BF1@5s={r_test.bf1[5.0][2]:.3f} V={r_test.v_measure:.3f}")
print(f"  test (leaky protocol)  BF1@5s={r_leak.bf1[5.0][2]:.3f} V={r_leak.v_measure:.3f}")
print(f"  cost of the leak:      {r_leak.bf1[5.0][2] - r_test.bf1[5.0][2]:+.3f} BF1@5s")

print()
print("=" * 72)
print("TEST 2 - leave-one-machine-out")
print("=" * 72)
by_machine = collections.defaultdict(set)
for sid, m in machine.items():
    by_machine[m].add(sid)
print(f"  {len(by_machine)} machines: "
      + ", ".join(f"{m}({len(v)})" for m, v in sorted(by_machine.items())))
rows = []
for m, held in sorted(by_machine.items()):
    if len(held) < 3:
        continue
    train = set(gold) - held
    mu_m, mn_m = best_on(train)
    r = score(held, mu_m, mn_m)
    rows.append((m, len(held), mu_m, r.bf1[5.0][2], r.v_measure, r.ari))
    print(f"  hold out {m:22} n={len(held):2d}  tuned max_unit_s={mu_m:3d}  "
          f"BF1@5s={r.bf1[5.0][2]:.3f}  V={r.v_measure:.3f}  ARI={r.ari:.3f}")
if rows:
    b = np.array([r[3] for r in rows]); v = np.array([r[4] for r in rows])
    print(f"\n  BF1@5s across held-out machines: mean={b.mean():.3f} "
          f"sd={b.std():.3f} min={b.min():.3f} max={b.max():.3f}")
    print(f"  V across held-out machines:      mean={v.mean():.3f} "
          f"sd={v.std():.3f} min={v.min():.3f} max={v.max():.3f}")


print()
print("=" * 72)
print("TEST 3 - leave-one-domain-out: can a department be held out at all?")
print("=" * 72)
# Each gold family's department, read off the labeller's system prefix on the
# family's own gold segments rather than typed in.
fam = collections.defaultdict(collections.Counter)
for segs, _, _ in gold.values():
    for s in segs:
        fam[s.label][lab(s).split("__")[0]] += 1
dept = {f: c.most_common(1)[0][0] for f, c in fam.items()}
spread = collections.Counter(len({dept[s.label] for s in segs}) for segs, _, _ in gold.values())
single = spread.get(1, 0)
print(f"  departments present per session: {dict(sorted(spread.items()))}")
print(f"  sessions belonging to a single department: {single} of {len(gold)}")
if single == 0:
    print("  -> no department can be held out by session. The cross-department test")
    print("     is dataset B itself, against the portal breadcrumb: label_vs_breadcrumb.py")
