import json, os, glob, collections, datetime as dt
A=r"C:\Users\LENOVO\imby\data\dataset_a"; B=r"C:\Users\LENOVO\imby\data\dataset_b"
def P(t): return dt.datetime.fromisoformat(t.replace('Z','+00:00'))

# ---- A: apps/titles on a sample of 8 sessions, + boundary alignment ----
ses=sorted(glob.glob(os.path.join(A,"ses_*")))[:8]
wt=collections.Counter(); app=collections.Counter()
hits=collections.Counter(); nb=0
for s in ses:
    evs=[]
    for f in sorted(glob.glob(os.path.join(s,"chunk_*","events.jsonl"))):
        for line in open(f,encoding='utf-8'):
            e=json.loads(line); evs.append(e)
            c=e.get("context") or {}; aa=c.get("active_app") or {}
            if aa.get("app_name"): app[aa["app_name"]]+=1
            if aa.get("window_title"): wt[aa["window_title"]]+=1
    evs.sort(key=lambda e:e["timestamp_ms"])
    m=json.load(open(os.path.join(s,"gt_manifest.json"),encoding='utf-8'))
    starts=[P(x["start_ts"]) for p in m["processes"] for x in p["executions"] if x.get("start_ts")]
    # for each gt start, what observable signal is within +-2s?
    for st in starts:
        nb+=1
        lo,hi=st.timestamp()*1000-2000, st.timestamp()*1000+2000
        w=[e for e in evs if lo<=e["timestamp_ms"]<=hi]
        kinds=set(e["event_type"] for e in w)
        for k in kinds: hits[k]+=1
        if any((e.get("correlation") or {}).get("ms_since_last_event",0) or 0 >2000 for e in w): hits["_gap>2s"]+=1
        if not w: hits["_NO_EVENTS"]+=1
print("=== A apps (8 sessions) ===", ", ".join(f"{k}={v}" for k,v in app.most_common(12)))
print("=== A top window titles ===")
for k,v in wt.most_common(18): print(f"{v:6d}  {k[:95]}")
print(f"\n=== A: signals within +/-2s of {nb} gt process starts ===")
for k,v in hits.most_common(): print(f"  {k:26} {v:5d}  ({100*v/nb:.0f}%)")

# ---- B: real navigation URLs + one full sample event ----
print("\n=== B browser_navigation urls ===")
nav=collections.Counter(); title=collections.Counter()
smpl={}
for f in glob.glob(os.path.join(B,"ses_*","chunk_*","events.jsonl")):
    for line in open(f,encoding='utf-8'):
        e=json.loads(line)
        if e["event_type"]=="browser_navigation":
            p=e.get("payload") or {}
            nav[str(p.get("url") or p.get("to") or p)[:100]]+=1
            if p.get("title"): title[p["title"][:60]]+=1
        smpl.setdefault(e["event_type"], e)
for k,v in nav.most_common(25): print(f"{v:5d}  {k}")
print("nav titles:", ", ".join(f"{k}={v}" for k,v in title.most_common(12)))
for t in ["browser_click","keystroke","clipboard_change","app_switch","screenshot_smart"]:
    if t in smpl: print(f"\n--- sample {t} ---\n", json.dumps(smpl[t], ensure_ascii=False)[:1300])
