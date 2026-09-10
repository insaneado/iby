"""Re-derive every load-bearing figure in the report and compare.

The report was drafted before the terminator-state labeller and the 12-screen
tool. Numbers written once and not re-checked are exactly the kind of thing a
reviewer catches, so each is recomputed from the current pipeline.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import json
import re

import numpy as np
import pandas as pd

from common import load_index, BUILD
from gold import load_gold
from evaluate import evaluate
from segment import event_bounds
from segment_v4 import segment_dataset_v4
from label import SignatureLabeller

REPORT = (Path(__file__).resolve().parent.parent / "report" / "REPORT.md").read_text(encoding="utf-8")
checks: list[tuple[str, str, str]] = []


def check(name, actual, claimed):
    a, c = str(actual), str(claimed)
    checks.append((name, a, c))
    mark = "OK  " if a == c else "STALE"
    print(f"  [{mark}] {name:44} actual={a:<10} report={c}")


# ---- Step 1, dataset A ----
gold = load_gold("dataset_a")
pred = segment_dataset_v4("dataset_a", event_bounds("dataset_a"),
                          labeller=SignatureLabeller("dataset_a"), expand_gap_s=60)
r = evaluate(gold, pred)
print("Step 1 - dataset A")
check("boundary F1 @2s", f"{r.bf1[2.0][2]:.3f}", "0.700")
check("boundary F1 @5s", f"{r.bf1[5.0][2]:.3f}", "0.756")
check("boundary F1 @10s", f"{r.bf1[10.0][2]:.3f}", "0.818")
check("WindowDiff", f"{r.windowdiff:.3f}", "0.195")
check("V-measure", f"{r.v_measure:.3f}", "0.719")
check("segments produced", r.n_pred, "2,010".replace(",", ""))
check("idle claimed", f"{100*r.idle_pred:.1f}%", "6.6%")

# ---- Step 1, dataset B deliverable ----
seg = [json.loads(l) for l in open(Path(__file__).parent.parent / "out" / "segments.jsonl",
                                   encoding="utf-8") if l.strip()]
dur = sum((pd.Timestamp(s["end"]) - pd.Timestamp(s["start"])).total_seconds() for s in seg)
print("\nStep 2 - dataset B")
check("executions", len(seg), "664")
check("minutes of work", f"{dur/60:.0f}", "173")
check("sessions", len({s['session_id'] for s in seg}), "15")
check("distinct labels", len({s['label'] for s in seg}), "12")

# ---- screen shares ----
share = collections.Counter()
for s in seg:
    d = (pd.Timestamp(s["end"]) - pd.Timestamp(s["start"])).total_seconds()
    share[s["label"].split("__")[1]] += d
tot = sum(share.values())
top, tval = share.most_common(1)[0]
m = re.search(r"\| \*\*payroll-items\*\* \| \*\*(\d+)\*\* \| \*\*([\d.]+)\*\* \| \*\*([\d.]+)%\*\*", REPORT)
check("top screen", top, "payroll-items")
check("top screen share", f"{100*tval/tot:.1f}%", (m.group(3) + "%") if m else "?")

# ---- Step 3 ----
run = json.loads((Path(__file__).parent.parent / "out" / "automation_run.json").read_text(encoding="utf-8"))
modes = collections.Counter(o["mode"] for o in run)
auto = modes["automated"] + modes["automated_by_rule"]
print("\nStep 3 - automation")
check("rows handled", len(run), "984")
check("fully automated", auto, "915")
check("automation rate", f"{100*auto/len(run):.0f}%", "93%")
check("failures", modes["failed"], "0")
check("screens", len({o["system"] for o in run}), "12")

# ---- signals quoted in the report ----
df = load_index("dataset_a")
print("\nsignals quoted in the report")
check("row-selection clicks (dataset A)", len(df[df.el_tag == "td"]), "1,780".replace(",", ""))
check("confirm clicks (dataset A)", len(df[df.el_tag == "button"]), "1,752".replace(",", ""))
b = load_index("dataset_b")
check("confirm clicks (dataset B)", len(b[b.el_tag == "button"]), "629")

stale = [c for c in checks if c[1] != c[2]]
print(f"\n{len(checks) - len(stale)}/{len(checks)} figures match; {len(stale)} stale")
for n, a, c in stale:
    print(f"   STALE  {n}: report says {c}, actual {a}")
