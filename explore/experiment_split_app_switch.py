"""Pre-registered evaluation of the first-app-switch split against the midpoint.

The bar, fixed before this ran:
  * test half (overfit audit's seed-0 split): BF1@2s and BF1@5s both higher,
    and V no more than 0.005 lower;
  * all of dataset A: WindowDiff not worse, V no more than 0.005 lower, and the
    share of executions mapping to exactly one segment not lower;
  * per machine: no machine's BF1@5s more than 0.02 lower.
Also reports how many of dataset B's segments would move. Read-only.
"""
import collections
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from common import load_index
from evaluate import evaluate
from gold import load_gold
from label import SignatureLabeller
from segment import event_bounds
from segment_v4 import segment_dataset_v4

A, RULES = "dataset_a", ("midpoint", "first_app_switch")
gold, bounds, df, lab = load_gold(A), event_bounds(A), load_index(A), SignatureLabeller(A)


def run(sids, split):
    g = {k: v for k, v in gold.items() if k in sids}
    p = segment_dataset_v4(A, {k: bounds[k] for k in sids}, labeller=lab, expand_gap_s=60, split=split)
    return evaluate(g, p), g, p


def maps_to_one(g, p):
    ok = n = 0
    for sid, (gs, _, _) in g.items():
        for x in gs:
            ovs = [max(0.0, (min(x.end, q.end) - max(x.start, q.start)).total_seconds()) for q in p.get(sid, [])]
            ok += sum(1 for o in ovs if o >= 0.10 * x.duration) == 1
            n += 1
    return 100 * ok / n


res = {}
print("all of dataset A")
for split in RULES:
    r, g, p = run(set(gold), split)
    res[("all", split)] = (r, maps_to_one(g, p))
    print(f"  {split:17} BF1@2s={r.bf1[2.0][2]:.3f} BF1@5s={r.bf1[5.0][2]:.3f} BF1@10s={r.bf1[10.0][2]:.3f} "
          f"WD={r.windowdiff:.3f} V={r.v_measure:.3f} ARI={r.ari:.3f} idle={100 * r.idle_pred:.1f}% "
          f"maps to one={res[('all', split)][1]:.1f}%")

sids = sorted(gold)
random.Random(0).shuffle(sids)
test = set(sids[32:])
print("\ntest half (never used to choose the rule)")
for split in RULES:
    r, _, _ = run(test, split)
    res[("test", split)] = r
    print(f"  {split:17} BF1@2s={r.bf1[2.0][2]:.3f} BF1@5s={r.bf1[5.0][2]:.3f} V={r.v_measure:.3f} ARI={r.ari:.3f}")

machine = {sid: df[df.session_id == sid].machine.dropna().iloc[0] for sid in gold}
by = collections.defaultdict(set)
for sid, m in machine.items():
    by[m].add(sid)
print("\nper machine, BF1@5s (midpoint -> first app switch)")
worst_drop = 0.0
for m, held in sorted(by.items()):
    if len(held) < 3:
        continue
    a, b = run(held, "midpoint")[0].bf1[5.0][2], run(held, "first_app_switch")[0].bf1[5.0][2]
    worst_drop = max(worst_drop, a - b)
    print(f"  {m:18} n={len(held):2d}  {a:.3f} -> {b:.3f}  ({b - a:+.3f})")

ra, rb = res[("all", "midpoint")], res[("all", "first_app_switch")]
ta, tb = res[("test", "midpoint")], res[("test", "first_app_switch")]
bar = {
    "test: BF1@2s higher": tb.bf1[2.0][2] > ta.bf1[2.0][2],
    "test: BF1@5s higher": tb.bf1[5.0][2] > ta.bf1[5.0][2],
    "test: V no more than 0.005 lower": tb.v_measure >= ta.v_measure - 0.005,
    "all: WindowDiff not worse": rb[0].windowdiff <= ra[0].windowdiff,
    "all: V no more than 0.005 lower": rb[0].v_measure >= ra[0].v_measure - 0.005,
    "all: maps-to-one not lower": rb[1] >= ra[1],
    "machines: no BF1@5s drop over 0.02": worst_drop <= 0.02,
}
print("\nthe pre-registered bar")
for k, ok in bar.items():
    print(f"  [{'PASS' if ok else 'FAIL'}] {k}")
print(f"\nVERDICT: {'PASSES - ship it' if all(bar.values()) else 'FAILS - record as a negative result'}")

B = "dataset_b"
lb = SignatureLabeller(B)
pb = {s: segment_dataset_v4(B, event_bounds(B), labeller=lb, expand_gap_s=60, split=s) for s in RULES}
moved = sum(1 for sid in pb["midpoint"] for x, y in zip(pb["midpoint"][sid], pb["first_app_switch"][sid])
            if (x.start, x.end) != (y.start, y.end))
total = sum(len(v) for v in pb["midpoint"].values())
print(f"\ndataset B: {total} segments either way; {moved} would change an edge")
