"""Build the mock portal's fixture data from the observed logs.

Nothing here is invented. Every worklist row, column header, screen title and
status string is lifted from `context.extracted_text` in dataset B, so the mock
the automation runs against is a reconstruction of the real screens rather than
a convenient fiction.

What that does and does not prove is stated plainly in tool/README.md: it
demonstrates the automation logic end to end against the real DOM contract, and
it does not demonstrate that the real portal behaves identically.
"""
from __future__ import annotations
import collections
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from common import load_index, BUILD                                  # noqa: E402

SYSTEMS = {"HR人事給与システム": "hr",
           "財務会計システム": "fin",
           "受発注在庫管理システム": "ops"}

# Generalised across all three deployments. The accounting system's 社員ID is
# E2001 / V3001, the logistics system's is BATCH-W2, and its 金額 is an em dash
# wherever an adjustment carries no amount. The schema is otherwise identical in
# all three - which is the structural form of the "one screen, three
# deployments" finding that makes a shared engine the right shape.
ROW = re.compile(
    r"(P\d+-\d+-\d+)\n([A-Z][A-Z0-9\-]*)\n([^\n]+)\n([^\n]+)\n([\d,]+円|[—-])\n"
    r"(定常|調整|新規|変更)\n(未処理|登録済み|完了)")
NAV = re.compile(r"ダッシュボード\n((?:[^\n]+\n\d+\n)+)")
CRUMB = re.compile(r"ダッシュボード / ([^\n]+)")

# Placeholder text per screen, from browser_form_input labels in the logs.
NOTE_PLACEHOLDER = {
    "pi": "処理内容・確認コメントを入力してください…",
    "la": "承認コメントまたは差戻し理由を入力してください…",
    "ob": "照合結果・特記事項を入力してください…",
    "si": "処理内容・対応状況を入力してください…",
    "rt": "処理内容を入力…",
}
COLUMNS = ["ID", "社員ID", "氏名", "区分", "金額", "種別", "ステータス"]


def main():
    df = load_index("dataset_b")
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))]

    per_system = collections.defaultdict(dict)      # system -> row_id -> row
    screen_title = collections.defaultdict(collections.Counter)
    nav_items = collections.defaultdict(collections.Counter)
    operator = {}

    for t in txt.text:
        sysname = next((s for s in SYSTEMS if s in t), None)
        if not sysname:
            continue
        key = SYSTEMS[sysname]
        for r in ROW.findall(t):
            # keep the first-seen state so the fixture starts with work to do
            per_system[key].setdefault(r[0], dict(zip(COLUMNS, r)))
        m = CRUMB.search(t)
        if m:
            screen_title[key][m.group(1).strip()] += 1
        m = NAV.search(t)
        if m:
            for line in m.group(1).strip().split("\n"):
                if not line.isdigit():
                    nav_items[key][line.strip()] += 1
        m = re.search(r"([一-鿿]{2,4}\s+[一-鿿]{2,4})\s*·\s*([一-鿿ァ-ヿ]+マネージャー)", t)
        if m and key not in operator:
            operator[key] = f"{m.group(1)} · {m.group(2)}"

    out = {}
    for key, rows in per_system.items():
        rows = list(rows.values())
        for r in rows:                    # every row starts unprocessed
            r["ステータス"] = "未処理"
        out[key] = {
            "system_name": next(k for k, v in SYSTEMS.items() if v == key),
            "operator": operator.get(key, ""),
            "screen_title": screen_title[key].most_common(1)[0][0] if screen_title[key] else "",
            "nav": [n for n, _ in nav_items[key].most_common(6)],
            "columns": COLUMNS,
            "rows": rows,
        }

    dest = Path(__file__).resolve().parent / "mock_portal" / "fixture.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"wrote {dest}")
    for k, v in out.items():
        variants = collections.Counter(r["種別"] for r in v["rows"])
        print(f"  {k:4} {v['system_name']:14} rows={len(v['rows']):4d} "
              f"screen={v['screen_title'][:22]:24} variants={dict(variants)}")


if __name__ == "__main__":
    main()
