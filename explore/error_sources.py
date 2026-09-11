"""Where do the remaining Step 1 errors come from? Dataset A, shipped configuration.

Classifies every gold execution by what it contains - a confirm press, a row
click - and reports, per class, how often it maps to exactly one predicted
segment: material overlap of at least 10%, the metric audit's own definition, so
the total of misses must equal the audit's.

The report used to put the residual error "mostly where a unit has no opening
click". That describes one execution in 2,009. This is the measurement that
replaced the guess.

    python error_sources.py
"""
import collections
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
pred = segment_dataset_v4("dataset_a", event_bounds("dataset_a"),
                          labeller=SignatureLabeller("dataset_a"), expand_gap_s=60)

clicks = {}
for sid, d in df.groupby("session_id"):
    clicks[sid] = (np.sort(d[d.el_tag == "td"].ts_ms.values.astype(np.int64)),
                   np.sort(d[d.el_tag == "button"].ts_ms.values.astype(np.int64)))
EMPTY = np.array([], dtype=np.int64)


def count_in(arr, a, b):
    return int(np.searchsorted(arr, b, side="right") - np.searchsorted(arr, a, side="left"))


table = collections.defaultdict(lambda: [0, 0])      # class -> [executions, mapped to one]
for sid, (gsegs, _, _) in gold.items():
    opens, closes = clicks.get(sid, (EMPTY, EMPTY))
    ps = pred.get(sid, [])
    for g in gsegs:
        a, b = int(g.start.timestamp() * 1000), int(g.end.timestamp() * 1000)
        cls = ("confirm press" if count_in(closes, a, b) else "NO confirm press") + ", " + \
              ("row click" if count_in(opens, a, b) else "NO row click")
        ovs = [max(0.0, (min(g.end, p.end) - max(g.start, p.start)).total_seconds()) for p in ps]
        table[cls][0] += 1
        table[cls][1] += sum(1 for o in ovs if o >= 0.10 * g.duration) == 1

total = sum(n for n, _ in table.values())
misses = sum(n - ok for n, ok in table.values())
print(f"gold executions: {total}; not mapping to exactly one segment: {misses} "
      f"({100 * misses / total:.1f}%)\n")
print(f"  {'execution contains':36}{'n':>6}{'maps to one':>13}{'share of misses':>17}")
for cls, (n, ok) in sorted(table.items(), key=lambda kv: -kv[1][0]):
    print(f"  {cls:36}{n:6d}{100 * ok / n:12.1f}%{100 * (n - ok) / misses:16.1f}%")
