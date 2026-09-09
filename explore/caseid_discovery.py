"""Discovery: where do ground-truth case IDs actually appear in the event stream?

Day 0 established that case IDs are present. This measures *where*, and how
completely, so the extractor targets the right fields instead of guessing.
"""
import collections

import pandas as pd

from common import load_index, BUILD, sessions, load_gt_manifest

df = load_index("dataset_a")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")
tmap = dict(zip(txt.event_id, txt.text))

cases = collections.defaultdict(set)
for s in sessions("dataset_a"):
    m = load_gt_manifest(s)
    for p in m.get("processes", []):
        for e in p.get("executions", []):
            if e.get("case_id"):
                cases[s.name].add(e["case_id"])

allc = set().union(*cases.values())
total = sum(len(v) for v in cases.values())
print(f"gt case_ids: {total} across {len(cases)} sessions, {len(allc)} distinct")
print("samples:", sorted(allc)[:8])

FIELDS = ["char", "el_value", "el_name", "title", "new_title", "prev_title", "url", "el_id"]
found = collections.defaultdict(set)

for sid, cs in cases.items():
    d = df[df.session_id == sid]
    for f in FIELDS:
        blob = "  ".join(str(x) for x in d[f].dropna().unique())
        for c in cs:
            if c in blob:
                found[f].add((sid, c))
    blob = "  ".join(tmap.get(e, "") for e in d.event_id if e in tmap)
    for c in cs:
        if c in blob:
            found["extracted_text"].add((sid, c))

print(f"\n{'field':18}{'found':>8}  recall")
for f in sorted(found, key=lambda x: -len(found[x])):
    print(f"{f:18}{len(found[f]):8d}  {100*len(found[f])/total:5.1f}%")
union = set().union(*found.values()) if found else set()
print(f"{'UNION':18}{len(union):8d}  {100*len(union)/total:5.1f}%")

k = df[df.event_type == "keystroke"]
print(f"\nkeystroke events {len(k)}, distinct char values {k.char.nunique()}"
      "  -> IDs must be reconstructed from runs, not read off single events")
print(f"el_value populated on keystrokes: {100*k.el_value.notna().mean():.0f}%")
