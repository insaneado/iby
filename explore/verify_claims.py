"""Re-verify every load-bearing factual claim against the CURRENT index.

Many claims in NOTES.md were measured during Day 0 recon, by reading raw JSONL
from the incomplete Downloads copy, before the data root moved and the index was
rebuilt. Any of them could now be stale. Anything that feeds the report has to
be re-derived from the current source of truth, or dropped.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import re

import pandas as pd

from common import load_index, BUILD

A, B = load_index("dataset_a"), load_index("dataset_b")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")


def claim(text, actual, expected=None):
    mark = "" if expected is None else ("  OK" if actual == expected else
                                        f"  MISMATCH (claimed {expected})")
    print(f"{text:52} {actual}{mark}")


print("=== dataset sizes ===")
claim("dataset_a events", len(A), 162768)
claim("dataset_b events", len(B), 20477)
claim("dataset_a sessions", A.session_id.nunique(), 63)
claim("dataset_b sessions", B.session_id.nunique(), 15)
claim("dataset_b distinct username_hash", B.user.nunique(), 4)
claim("screen-text captures (both)", len(txt), 8239)

print("\n=== the 629 confirm-click claim ===")
ok = B[B.el_id.notna() & B.el_id.astype(str).str.match(r"btn-\w+-ok$")]
claim("dataset_b btn-*-ok clicks", len(ok), 629)
print("   by screen:", dict(collections.Counter(ok.el_id)))

print("\n=== portal systems: same in A and B? ===")
for name, d in (("A", A), ("B", B)):
    sysnames = collections.Counter()
    for t in d.tab_title.dropna():
        sysnames[str(t)] += 1
    for t in d.title.dropna():
        for s in ("HR人事給与システム", "財務会計システム", "受発注在庫管理システム"):
            if s in str(t):
                sysnames[s] += 1
    top = [k for k, _ in sysnames.most_common(6)]
    print(f"   {name}: {top}")

print("\n=== browsers ===")
for name, d in (("A", A), ("B", B)):
    print(f"   {name}: " + ", ".join(
        f"{k}={v}" for k, v in collections.Counter(d.app.dropna()).most_common(5)))

print("\n=== operator identity in dataset_b screen text ===")
tb = txt[txt.event_id.isin(set(B.event_id))]
people = collections.Counter()
for s in tb.text:
    for m in re.findall(r"([一-鿿]{1,4}\s?[一-鿿]{1,4})\s*·\s*([^|\n]{2,12})", s):
        people[f"{m[0].strip()} · {m[1].strip()}"] += 1
claim("distinct 'name · role' strings found", len(people))
for k, v in people.most_common(8):
    print(f"      {v:4d}  {k}")

print("\n=== Word documents open in dataset_b (label backbone) ===")
docs = collections.Counter()
for t in B.title.dropna():
    m = re.match(r"^(.*?)\s+(?:-|\[)\s*Compatibility Mode", str(t))
    if m:
        docs[m.group(1).strip()] += 1
claim("distinct Word procedure documents", len(docs))
for k, v in docs.most_common(15):
    print(f"      {v:5d}  {k}")
