import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json, os, glob, collections, datetime as dt
from common import DATA
ROOT = str(DATA / "dataset_b")     # config.local.json overrides ./data, as everywhere else
et=collections.Counter(); app=collections.Counter(); wt=collections.Counter()
url=collections.Counter(); gaps=[]; users=collections.Counter(); mach=collections.Counter()
extc=0; tot=0; sess_rows=[]
for s in sorted(glob.glob(os.path.join(ROOT,"ses_*"))):
    files=sorted(glob.glob(os.path.join(s,"chunk_*","events.jsonl")))
    n=0; t0=t1=None; m=set()
    for f in files:
        for line in open(f,encoding='utf-8'):
            e=json.loads(line); n+=1; tot+=1
            et[e["event_type"]]+=1
            ts=e["timestamp_iso"]
            t0=ts if t0 is None or ts<t0 else t0; t1=ts if t1 is None or ts>t1 else t1
            src=e.get("source") or {}; users[src.get("username_hash")]+=1; m.add(src.get("machine_id"))
            c=e.get("context") or {}
            aa=c.get("active_app") or {}
            if aa.get("app_name"): app[aa["app_name"]]+=1
            if aa.get("window_title"): wt[aa["window_title"]]+=1
            tab=c.get("active_browser_tab") or {}
            if tab.get("url"): url[tab["url"]]+=1
            if c.get("extracted_text"): extc+=1
            g=(e.get("correlation") or {}).get("ms_since_last_event")
            if isinstance(g,(int,float)): gaps.append(g)
    sess_rows.append((os.path.basename(s), len(files), n, t0[11:19] if t0 else '', t1[11:19] if t1 else '', ",".join(sorted(x or '' for x in m))))
print(f"=== DATASET B: {len(sess_rows)} sessions, {tot} events, extracted_text on {extc} ({100*extc/tot:.1f}%) ===")
print(f"{'session':42}{'chk':>4}{'events':>8}  {'start':8} {'end':8} machine")
for r in sess_rows: print(f"{r[0]:42}{r[1]:4d}{r[2]:8d}  {r[3]:8} {r[4]:8} {r[5]}")
print("\nusers(username_hash):", len(users), list(users)[:20])
print("\nevent_types:", ", ".join(f"{k}={v}" for k,v in et.most_common()))
print("\napps:", ", ".join(f"{k}={v}" for k,v in app.most_common(20)))
gaps.sort()
import statistics
q=lambda p: gaps[int(len(gaps)*p)]
print(f"\ngaps ms: p50={q(.5)} p75={q(.75)} p90={q(.9)} p95={q(.95)} p99={q(.99)} max={gaps[-1]}")
print(f"gaps>3s: {sum(1 for g in gaps if g>3000)}  >10s: {sum(1 for g in gaps if g>10000)}  >30s: {sum(1 for g in gaps if g>30000)}")
print("\n--- top 45 window titles ---")
for k,v in wt.most_common(45): print(f"{v:6d}  {k[:110]}")
print("\n--- top 30 urls ---")
for k,v in url.most_common(30): print(f"{v:6d}  {k[:110]}")
