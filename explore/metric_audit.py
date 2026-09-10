"""Is the evaluator itself biased in my favour?

A fair objection: I chose the metrics, the tolerances, the binning, the IDLE
handling and the gold construction. Standard definitions (WindowDiff is Pevzner
& Hearst; V-measure and ARI are sklearn) do not protect against a *scoring
harness* that flatters the method it was built alongside.

Four tests that do not depend on my judgement.

1. CHANCE CALIBRATION. What does a random segmenter with the *same segment
   count* score? If random scores near mine, the metric is not measuring
   anything. This is the test that matters most and I had not run it.

2. LABEL PERMUTATION. Keep my boundaries, shuffle the labels. V-measure should
   collapse. If it does not, the label score is coming from the segmentation
   rather than from the labels.

3. BIJECTION. Parameter-free: does each ground-truth execution correspond to
   exactly one predicted segment, and vice versa? No tolerance, no binning, no
   choices of mine involved.

4. DURATION DISTRIBUTION. Kolmogorov-Smirnov between predicted and gold segment
   durations. Also parameter-free, and nothing in the pipeline optimises it.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import random
import collections
import datetime as dt

import numpy as np
from scipy import stats

from common import load_index
from gold import load_gold, Segment
from evaluate import evaluate
from segment import event_bounds
from segment_v4 import segment_dataset_v4
from label import SignatureLabeller

UTC = dt.timezone.utc
gold = load_gold("dataset_a")
bounds = event_bounds("dataset_a")
lab = SignatureLabeller("dataset_a")
pred = segment_dataset_v4("dataset_a", bounds, labeller=lab, expand_gap_s=60)

real = evaluate(gold, pred)
print(f"MINE            BF1@2={real.bf1[2.0][2]:.3f} BF1@5={real.bf1[5.0][2]:.3f} "
      f"WD={real.windowdiff:.3f} V={real.v_measure:.3f} ARI={real.ari:.3f}")
print()

# ---------- 1. chance calibration ----------
def random_like(pred, seed):
    """Same segment count and same label vocabulary per session, random placement."""
    rng = random.Random(seed)
    out = {}
    for sid, segs in pred.items():
        t0, t1 = bounds[sid]
        span = (t1 - t0).total_seconds()
        n = len(segs)
        labels = [s.label for s in segs]
        if n == 0:
            out[sid] = []; continue
        cuts = sorted(rng.uniform(0, span) for _ in range(2 * n))
        new = []
        for i in range(n):
            a, b = cuts[2 * i], cuts[2 * i + 1]
            if b - a < 1:
                b = a + 1
            new.append(Segment(sid, t0 + dt.timedelta(seconds=a),
                               t0 + dt.timedelta(seconds=b),
                               labels[rng.randrange(len(labels))]))
        new.sort(key=lambda s: s.start)
        # remove overlaps so it is a legal segmentation
        clean = []
        for s in new:
            if clean and s.start < clean[-1].end:
                s.start = clean[-1].end
            if (s.end - s.start).total_seconds() >= 1:
                clean.append(s)
        out[sid] = clean
    return out

rows = [evaluate(gold, random_like(pred, s)) for s in range(5)]
b2 = np.mean([r.bf1[2.0][2] for r in rows]); b5 = np.mean([r.bf1[5.0][2] for r in rows])
wd = np.mean([r.windowdiff for r in rows]); v = np.mean([r.v_measure for r in rows])
ari = np.mean([r.ari for r in rows])
print(f"1. RANDOM       BF1@2={b2:.3f} BF1@5={b5:.3f} WD={wd:.3f} V={v:.3f} ARI={ari:.3f}")
print(f"   (same segment count and label vocabulary, random placement, 5 seeds)")
print(f"   discrimination on BF1@5s: {real.bf1[5.0][2] - b5:+.3f}   "
      f"on ARI: {real.ari - ari:+.3f}")
print()

# ---------- 2. label permutation ----------
def shuffled_labels(pred, seed):
    rng = random.Random(seed)
    out = {}
    for sid, segs in pred.items():
        labels = [s.label for s in segs]
        rng.shuffle(labels)
        out[sid] = [Segment(s.session_id, s.start, s.end, l)
                    for s, l in zip(segs, labels)]
    return out

perm = [evaluate(gold, shuffled_labels(pred, s)) for s in range(5)]
print(f"2. LABELS SHUFFLED (boundaries kept)   "
      f"V={np.mean([r.v_measure for r in perm]):.3f}  "
      f"ARI={np.mean([r.ari for r in perm]):.3f}")
print(f"   mine: V={real.v_measure:.3f} ARI={real.ari:.3f}   "
      f"-> label signal = {real.v_measure - np.mean([r.v_measure for r in perm]):+.3f} V")
print()

# ---------- 3. bijection (parameter-free) ----------
per_gold, per_pred = collections.Counter(), collections.Counter()
for sid, (gsegs, _, _) in gold.items():
    psegs = pred.get(sid, [])
    for g in gsegs:
        n = sum(1 for p in psegs if p.start < g.end and p.end > g.start)
        per_gold[n] += 1
    for p in psegs:
        n = sum(1 for g in gsegs if p.start < g.end and p.end > g.start)
        per_pred[n] += 1
tot_g, tot_p = sum(per_gold.values()), sum(per_pred.values())
# Any-overlap counts a 1 ms touch the same as a full one. Under v4 each segment
# is expanded to the midpoint of the gap to its neighbour, so neighbours abut and
# almost every execution registers a spurious second overlap. Material overlap -
# at least 10% of the execution - is the figure that means anything.
mat = collections.Counter()
covs = []
for sid, (gsegs, _, _) in gold.items():
    ps = pred.get(sid, [])
    for g in gsegs:
        ovs = [max(0.0, (min(g.end, p.end) - max(g.start, p.start)).total_seconds())
               for p in ps]
        mat[sum(1 for o in ovs if o >= 0.10 * g.duration)] += 1
        covs.append(max(ovs) / g.duration if ovs else 0.0)
covs = np.array(covs)
print(f"3. BIJECTION (no tolerance, no binning)")
print(f"   ANY overlap, even 1 ms  - exactly one: "
      f"{per_gold[1]}/{tot_g} ({100*per_gold[1]/tot_g:.1f}%)   <- misleading under v4")
print(f"   MATERIAL overlap >=10%  - exactly one: "
      f"{mat[1]}/{tot_g} ({100*mat[1]/tot_g:.1f}%)   <- the meaningful figure")
print(f"   best match covers >=80% of the execution: {100*(covs>=.8).mean():.1f}%"
      f"   median coverage {100*np.median(covs):.1f}%")
print()

# ---------- 4. duration distribution ----------
gd = np.array([s.duration for v in gold.values() for s in v[0]])
pd_ = np.array([s.duration for v in pred.values() for s in v])
ks = stats.ks_2samp(gd, pd_)
print(f"4. DURATION DISTRIBUTION")
print(f"   gold   n={len(gd)} median={np.median(gd):.0f}s p90={np.percentile(gd,90):.0f}s")
print(f"   mine   n={len(pd_)} median={np.median(pd_):.0f}s p90={np.percentile(pd_,90):.0f}s")
print(f"   KS statistic={ks.statistic:.3f}  (0 = identical distributions)")
rnd = np.array([s.duration for v in random_like(pred, 0).values() for s in v])
print(f"   random n={len(rnd)} median={np.median(rnd):.0f}s  "
      f"KS={stats.ks_2samp(gd, rnd).statistic:.3f}")
