import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json, os, glob, collections, sys
ROOT = r"C:\Users\LENOVO\imby\data"

def sessions(ds):
    return sorted(glob.glob(os.path.join(ROOT, ds, "ses_*")))

# ---------- A: ground truth manifests ----------
fam = collections.Counter(); durs = collections.defaultdict(list)
var = collections.Counter(); apps_by_fam = collections.defaultdict(collections.Counter)
domains = collections.Counter(); ops = collections.Counter()
import datetime as dt
def p(t): return dt.datetime.fromisoformat(t.replace('Z','+00:00'))
nsess=0
for s in sessions("dataset_a"):
    f = os.path.join(s,"gt_manifest.json")
    if not os.path.exists(f): continue
    nsess+=1
    m = json.load(open(f,encoding='utf-8'))
    for pr in m.get("processes",[]):
        key=(pr["code"],pr.get("family_name"),pr.get("domain"))
        domains[pr.get("domain")]+=1
        for e in pr.get("executions",[]):
            fam[key]+=1
            var[(pr["code"],e.get("variant"))]+=1
            if e.get("end_ts") and e.get("start_ts"):
                durs[key].append((p(e["end_ts"])-p(e["start_ts"])).total_seconds())
            for a in e.get("apps",[]): apps_by_fam[key][a]+=1
print(f"=== DATASET A: {nsess} sessions with gt_manifest ===")
print(f"{'code':5}{'domain':10}{'family':28}{'n':>5}{'med_s':>8}{'p90_s':>8}  apps")
for k,c in fam.most_common():
    d=sorted(durs[k]) or [0]; med=d[len(d)//2]; p90=d[min(int(len(d)*.9),len(d)-1)]
    print(f"{k[0]:5}{str(k[2]):10}{str(k[1])[:26]:28}{c:5d}{med:8.0f}{p90:8.0f}  {','.join(a for a,_ in apps_by_fam[k].most_common(5))}")
print("variants:", dict(collections.Counter(f"{c}:{v}" for (c,v),n in var.items() for _ in [0])) if False else
      ", ".join(f"{c}/{v}={n}" for (c,v),n in sorted(var.items())))
