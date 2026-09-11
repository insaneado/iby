"""Ablation and sensitivity for the shipped Step 1 pipeline (report section 7).

Removes one component at a time and re-scores against dataset A's ground truth,
then sweeps each parameter across a wide range with the rest held as shipped.
Everything uses the configuration run_dataset_b.py writes the deliverable with,
and the current scorer, so these are the figures the report quotes.

An earlier version of this table was produced ad hoc, never committed, and went
stale when the scorer and the labeller changed underneath it. It lives here now
so it can be re-run rather than remembered.

    python ablation.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import segment_v4
from caseid import anchors as extract_anchors, case_prefix
from common import load_index
from evaluate import evaluate
from gold import load_gold
from label import SignatureLabeller
from segment import event_bounds

DS = "dataset_a"
SHIPPED = dict(expand_gap_s=60)          # as in run_dataset_b.py

gold = load_gold(DS)
bounds = event_bounds(DS)
df = load_index(DS)
sig = SignatureLabeller(DS)


def run(labeller=sig, anc=None, **kw):
    anc = extract_anchors(DS) if anc is None else anc
    cfg = {**SHIPPED, **kw}
    return {sid: segment_v4.segment_session_v4(sid, anc, df, t0, t1, labeller, **cfg)
            for sid, (t0, t1) in bounds.items()}


def row(name, pred):
    r = evaluate(gold, pred)
    n = sum(len(v) for v in pred.values())
    print(f"  {name:32} BF1@2s={r.bf1[2.0][2]:.3f}  BF1@5s={r.bf1[5.0][2]:.3f}  "
          f"V={r.v_measure:.3f}  ARI={r.ari:.3f}  segments={n}", flush=True)
    return r


print("ABLATION - remove one component, re-score (dataset A)")
shipped = run()
row("shipped", shipped)
row("without case anchors entirely", run(anc=extract_anchors(DS).iloc[0:0]))
_open = segment_v4.OPEN_TAG
segment_v4.OPEN_TAG = "__no_such_tag__"      # no row click can ever open a unit
try:
    row("ends only, no opening click", run())
finally:
    segment_v4.OPEN_TAG = _open
row("labels from case prefix", run(labeller=case_prefix))
row("one label for everything", run(labeller=lambda case: "work"))

n_all = sum(len(v) for v in shipped.values())
n_bracketed = sum(len(v) for v in run(fallback=False).values())
print(f"\n  segments that exist only because of the anchor-driven fallback: "
      f"{n_all - n_bracketed} of {n_all}")

print("\nSENSITIVITY - one parameter at a time, the rest as shipped (BF1@2s)")
for name, values in (("expand_gap_s", (20, 30, 60, 120, 300)),
                     ("max_unit_s", (100, 200, 300, 600)),
                     ("min_unit_s", (1, 3, 5, 10))):
    results = {v: evaluate(gold, run(**{name: v})) for v in values}
    print(f"  {name:12}  " + "   ".join(f"{v}: {r.bf1[2.0][2]:.3f}" for v, r in results.items()),
          flush=True)
    if name == "expand_gap_s":
        # The cap barely moves a boundary; it sets how much gap time is claimed as
        # work rather than left idle. Reported on BF1@2s alone it looked inert, and
        # the report called it so. These two lines are what it actually changes.
        print("  idle share by expand_gap_s  "
              + "   ".join(f"{v}: {100 * r.idle_pred:.1f}%" for v, r in results.items()), flush=True)
        print("  ARI by expand_gap_s         "
              + "   ".join(f"{v}: {r.ari:.3f}" for v, r in results.items()), flush=True)
cells = [f"{k}: {evaluate(gold, run(anc=extract_anchors(DS, min_repeat=k))).bf1[2.0][2]:.3f}"
         for k in (2, 3, 4)]
print(f"  {'min_repeat':12}  " + "   ".join(cells) + "   (case-anchor threshold)")
