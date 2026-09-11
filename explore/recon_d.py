import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json, os, glob, collections, re
from common import DATA
A = str(DATA / "dataset_a"); B = str(DATA / "dataset_b")    # config.local.json overrides ./data
s=sorted(glob.glob(os.path.join(A,"ses_*")))[0]
m=json.load(open(os.path.join(s,"gt_manifest.json"),encoding='utf-8'))
cases=[e["case_id"] for p in m["processes"] for e in p["executions"] if e.get("case_id")]
print("session:",os.path.basename(s)," gt case_ids:",len(cases),"unique:",len(set(cases)),"sample:",cases[:6])
blob=[]; 
for f in sorted(glob.glob(os.path.join(s,"chunk_*","events.jsonl"))):
    blob.append(open(f,encoding='utf-8').read())
blob="".join(blob)
found=[c for c in set(cases) if c in blob]
print(f"case_ids literally present in raw events text: {len(found)}/{len(set(cases))}  e.g. {found[:5]}")
# where do they appear?
where=collections.Counter()
for f in sorted(glob.glob(os.path.join(s,"chunk_*","events.jsonl"))):
    for line in open(f,encoding='utf-8'):
        for c in found[:40]:
            if c in line:
                e=json.loads(line); where[e["event_type"]]+=1
                for k in ("payload","context"):
                    if c in json.dumps(e.get(k),ensure_ascii=False): where[f"  in.{k}"]+=1
                break
print("case_id appears in:", dict(where))
print("\n=== B clipboard samples ===")
cb=collections.Counter(); n=0
for f in glob.glob(os.path.join(B,"ses_*","chunk_*","events.jsonl")):
    for line in open(f,encoding='utf-8'):
        if '"clipboard_change"' in line:
            e=json.loads(line); p=e.get("payload") or {}
            cb[json.dumps(p,ensure_ascii=False)[:150]]+=1
for k,v in cb.most_common(12): print(f"{v:4d} {k}")
print("\n=== B: ID-like tokens in extracted_text / form input ===")
pat=re.compile(r'\b[A-Z]{2,4}-\d{4,7}-\d{2,4}\b')
ids=collections.Counter(); ftext=collections.Counter()
for f in glob.glob(os.path.join(B,"ses_*","chunk_*","events.jsonl")):
    for line in open(f,encoding='utf-8'):
        for t in pat.findall(line): ids[t]+=1
        if '"browser_form_input"' in line:
            e=json.loads(line); p=e.get("payload") or {}
            el=(p.get("element") or {}).get("attributes") or {}
            ftext[f"{el.get('id') or el.get('name') or el.get('placeholder')}"]+=1
print("id-like tokens:",len(ids),"total hits:",sum(ids.values()),"top:",ids.most_common(8))
print("form fields:", ", ".join(f"{k}={v}" for k,v in ftext.most_common(25)))
