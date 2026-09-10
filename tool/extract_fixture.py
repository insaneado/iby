"""Build the mock portal's fixture from the observed logs, per SYSTEM and SCREEN.

An earlier version kept only the first breadcrumb seen per system, which pooled
rows from several screens under one title and modelled 3 screens where the logs
contain **12**. Every system runs several worklist screens off the same table
contract:

    hr   入社手続き / 経費精算・給与変更 / 勤怠・休暇申請 / 福利厚生申請
    fin  請求書承認・経費精算 / 発注管理 / 支払処理 / 予算差異分析 / 経費承認（管理職）
    ops  在庫管理 / 契約管理 / IT申請

Nothing here is invented. Worklist rows, column headers, screen titles, note
placeholders and status strings all come from `context.extracted_text` and
`payload.element` in dataset B.

The screen-to-element-prefix mapping is derived, not assumed: each portal screen
is matched to the element id prefix clicked while that breadcrumb was showing.
Purity runs 45-76%, limited by screen text being captured only every ~7.7 s, so
the breadcrumb lags actual navigation.
"""
from __future__ import annotations
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from common import load_index, BUILD                                  # noqa: E402

SYSTEMS = {"HR人事給与システム": "hr",
           "財務会計システム": "fin",
           "受発注在庫管理システム": "ops"}

CRUMB = re.compile(r"ダッシュボード / ([^\n]+)")
ROW_ID = re.compile(r"^P\d+-\d+-\d+$")

# The worklist header differs BY SCREEN. An earlier version hard-coded the
# payroll columns and so silently found only the 3 screens that matched them:
#   経費精算・給与変更   ID 社員ID 氏名 区分     金額       種別 ステータス
#   契約管理            ID 社員ID 氏名 申請種別 期間・詳細 部署 ステータス
# The header is printed in the capture, so read it rather than assume it.
TABLE_HEAD = re.compile(
    r"(?:処理待ち一覧|申請一覧|一覧)\n((?:[^\n]+\n){3,10}?)(?=P\d+-\d+-\d+\n)")


def parse_table(text):
    """(columns, rows) for the worklist in one capture, or (None, [])."""
    m = TABLE_HEAD.search(text)
    if not m:
        return None, []
    cols = [c.strip() for c in m.group(1).strip().split("\n") if c.strip()]
    if not (3 <= len(cols) <= 10) or cols[0] != "ID":
        return None, []
    lines = text[m.end():].split("\n")
    rows, i = [], 0
    while i + len(cols) <= len(lines):
        if ROW_ID.match(lines[i].strip()):
            rows.append(dict(zip(cols, [x.strip() for x in lines[i:i + len(cols)]])))
            i += len(cols)
        else:
            i += 1
    return cols, rows

# Note placeholder per element prefix, from browser_form_input field labels.
PLACEHOLDER = {
    "pi": "処理内容・確認コメントを入力してください…",
    "la": "承認コメントまたは差戻し理由を入力してください…",
    "ob": "照合結果・特記事項を入力してください…",
    "si": "処理内容・対応状況を入力してください…",
    "rt": "処理内容を入力…",
}


def screen_prefix_map(df, txt) -> dict:
    """Which element-id prefix belongs to which (system, screen)."""
    tl = {}
    for sid, g in txt.groupby("session_id"):
        g = g.sort_values("ts_ms")
        ts, cr, cur = [], [], None
        for r in g.itertuples():
            s = next((k for k in SYSTEMS if k in r.text), None)
            m = CRUMB.search(r.text)
            if s and m:
                cur = (SYSTEMS[s], m.group(1).strip())
            ts.append(r.ts_ms)
            cr.append(cur)
        tl[sid] = (np.array(ts), cr)

    link = collections.defaultdict(collections.Counter)
    for r in df[df.el_id.notna()].itertuples():
        eid = str(r.el_id)
        p = eid.split("-")[1] if eid.startswith("btn-") else eid.split("-")[0]
        if p not in PLACEHOLDER:
            continue
        ts, cr = tl.get(r.session_id, (np.array([]), []))
        if not len(ts):
            continue
        i = min(int(np.searchsorted(ts, r.ts_ms)), len(cr) - 1)
        if cr[i]:
            link[cr[i]][p] += 1
    return {k: c.most_common(1)[0][0] for k, c in link.items()}


def main():
    df = load_index("dataset_b")
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))]

    prefix_of = screen_prefix_map(df, txt)
    per = collections.defaultdict(dict)          # (system, screen) -> row_id -> row
    schema = {}                                  # (system, screen) -> column list
    operator = {}
    nav = collections.defaultdict(collections.Counter)

    for t in txt.text:
        s = next((k for k in SYSTEMS if k in t), None)
        m = CRUMB.search(t)
        if not (s and m):
            continue
        key = (SYSTEMS[s], m.group(1).strip())
        cols, rows = parse_table(t)
        if cols:
            schema.setdefault(key, cols)
            for r in rows:
                per[key].setdefault(r["ID"], r)
        nav[SYSTEMS[s]][m.group(1).strip()] += 1
        om = re.search(r"([一-鿿]{2,4}\s+[一-鿿]{2,4})\s*·\s*([一-鿿ァ-ヿ]+マネージャー)", t)
        if om and SYSTEMS[s] not in operator:
            operator[SYSTEMS[s]] = f"{om.group(1)} · {om.group(2)}"

    out = {}
    for (sysk, screen), rows in per.items():
        pref = prefix_of.get((sysk, screen))
        if not pref or len(rows) < 5:            # too few rows to be a real screen
            continue
        cols = schema[(sysk, screen)]
        rows = list(rows.values())
        # every row starts unprocessed, in this screen's own vocabulary
        statuses = collections.Counter(r[cols[-1]] for r in rows)
        PENDING_WORDS = ("未処理", "処理待ち", "申請中", "未確認")
        pending = next((v for v in statuses if v in PENDING_WORDS),
                       statuses.most_common(1)[0][0])
        done = next((v for v in statuses if v != pending), "登録済み")
        for r in rows:
            r[cols[-1]] = pending
        out[f"{sysk}::{screen}"] = {
            "system": sysk,
            "system_name": next(k for k, v in SYSTEMS.items() if v == sysk),
            "screen": screen,
            "prefix": pref,
            "operator": operator.get(sysk, ""),
            "placeholder": PLACEHOLDER[pref],
            "nav": [n for n, _ in nav[sysk].most_common(6)],
            "columns": cols,
            "pending_value": pending,
            "done_value": done,
            "rows": rows,
        }

    dest = Path(__file__).resolve().parent / "mock_portal" / "fixture.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(len(v["rows"]) for v in out.values())
    print(f"wrote {dest}\n{len(out)} screens, {total} worklist rows\n")
    print(f"{'key':32}{'pfx':>5}{'rows':>6}  columns")
    for k, v in sorted(out.items(), key=lambda kv: -len(kv[1]["rows"])):
        print(f"{k[:30]:32}{v['prefix']:>5}{len(v['rows']):6}  "
              f"{' | '.join(v['columns'][3:-1])}  [{v['pending_value']}->{v['done_value']}]")


if __name__ == "__main__":
    main()
