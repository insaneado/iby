"""Emit every Japanese term the analysis relies on, for human verification.

The terms are extracted from the data, so their existence and frequency are
facts. The English glosses are mine and are the single largest unverified
surface in the project - if a gloss is wrong, a process gets mis-named and the
Step 2 priority ordering can be wrong with it.

This writes docs/glossary.md so a Japanese reader can check the glosses without
reading any code, and so the report can state which readings were confirmed.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collections
import re

import pandas as pd

from common import load_index, BUILD, ROOT

# My proposed glosses. Everything here is UNVERIFIED until a human confirms it.
GLOSS = {
    # portal systems
    "HR人事給与システム": "HR payroll system",
    "財務会計システム": "Financial accounting system",
    "受発注在庫管理システム": "Order & inventory management system",
    # dataset A process families (from gt_manifest family_name)
    "住民税通知確認": "Resident tax notification check",
    "給与備考・控除整備": "Payroll remarks & deduction maintenance",
    "育児・産休申請確認": "Childcare / maternity leave application check",
    "社保・年金補正対応": "Social insurance & pension correction",
    "入社照合・手当確認": "Onboarding reconciliation & allowance check",
    "請求書承認": "Invoice approval",
    "経費精算承認": "Expense settlement approval",
    "銀行勘定照合": "Bank account reconciliation",
    "予算差異分析": "Budget variance analysis",
    "支払処理": "Payment processing",
    "受注処理": "Order processing",
    "在庫調整": "Inventory adjustment",
    "仕入先連絡": "Supplier contact",
    "出荷追跡": "Shipment tracking",
    "返品処理": "Returns processing",
    # dataset B roles
    "人事マネージャー": "HR manager",
    "経理マネージャー": "Accounting manager",
    "物流マネージャー": "Logistics manager",
    # dataset B word documents (romaji filenames -> my reading)
    "keiyaku_kaijo_tetsuzuki": "Contract termination procedure",
    "nyusha_checklist_shinsotsu_batch": "New-graduate onboarding checklist (batch)",
    "gyomu_itaku_kyuuyo_kitei": "Outsourcing / contractor payment rules",
    "settai_keihi_kitei": "Entertainment expense rules",
    "shinkui_keiyaku_tetsuzuki": "New contract procedure",
    "shinkuitorihikisaki_touroku_tetsuzuki": "New supplier registration procedure",
    "getsujitsu_teigaku_torihikisaki_ichiran": "Monthly fixed-amount supplier list",
    "gyomu_itaku_ukeire_tetsuzuki": "Outsourcing acceptance procedure",
    "gyomu_itaku_keihi_kitei": "Outsourcing expense rules",
    "kanrisya_kengen_shinsei_tetsuzuki": "Administrator privilege request procedure",
    "ikuji_kyuugyou_kitei": "Childcare leave rules",
    "kazoku_teate_kitei": "Family allowance rules",
    "kaigo_kyuugyou_kitei": "Nursing-care leave rules",
}

JP = re.compile(r"[぀-ヿ㐀-鿿]")

A, B = load_index("dataset_a"), load_index("dataset_b")
txt = pd.read_parquet(BUILD / "extracted_text.parquet")
tb = txt[txt.event_id.isin(set(B.event_id))]

# frequency evidence, straight from the data
freq = collections.Counter()
for d in (A, B):
    for col in ("title", "tab_title", "el_name", "new_title"):
        for v in d[col].dropna():
            s = str(v)
            for term in GLOSS:
                if term in s:
                    freq[term] += 1
for s in txt.text:
    for term in GLOSS:
        if term in s:
            freq[term] += 1

# Japanese UI strings we rely on but have NOT glossed - the unknown unknowns
ungl = collections.Counter()
for v in B.el_name.dropna():
    s = str(v).strip()
    if JP.search(s) and not any(t in s for t in GLOSS):
        ungl[s[:40]] += 1

out = ROOT / "docs" / "glossary.md"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("# Japanese glossary — for verification\n\n")
    f.write("Terms are extracted from the data, so their presence and counts are\n"
            "facts. **The English glosses are mine and are unverified.** They are the\n"
            "largest unchecked surface in the project: a wrong gloss mis-names a\n"
            "process and can distort the Step 2 priority ordering.\n\n")
    f.write("Please mark each row OK, or write the correct reading.\n\n")
    f.write("| Japanese / filename | my gloss | occurrences | correct? |\n")
    f.write("|---|---|---:|---|\n")
    for term, gloss in sorted(GLOSS.items(), key=lambda kv: -freq[kv[0]]):
        f.write(f"| `{term}` | {gloss} | {freq[term]} | |\n")
    f.write(f"\n## Unglossed Japanese UI strings in dataset B "
            f"({len(ungl)} distinct)\n\n")
    f.write("These appear as clicked UI elements. I have not translated them; several\n"
            "look like the *subject* of a work item rather than a process name.\n\n")
    f.write("| string | clicks |\n|---|---:|\n")
    for s, n in ungl.most_common(40):
        f.write(f"| `{s}` | {n} |\n")

print(f"wrote {out}")
print(f"glossed terms: {len(GLOSS)}  |  unglossed JP UI strings in B: {len(ungl)}")
print(f"terms with zero occurrences (suspicious - possibly invented): "
      f"{[t for t in GLOSS if freq[t] == 0]}")
