"""Dataset B's labels against the process code its own row IDs carry.

Dataset B has no ground truth file, and the report long said its accuracy could
only be inferred. But its worklist row IDs have the form P<n>-<batch>-<row>,
and the code P<n> is the process: every code sits on exactly one portal screen,
except the HR screen 経費精算・給与変更, whose one worklist holds two (expense
claims and pay changes). The labeller never reads these IDs, so they are a
held-out check - the strongest one dataset B offers.

Two ways to tie a segment to the row it processed, each with a weakness:
    case anchors inside the segment (label-blind; caseid.anchors) - most
        segments have one, but on a screen whose list shows several rows an
        anchor can name a row other than the one processed
    the confirmation "<row id>: 登録確定しました" captured within 15 s of the
        segment's confirm press - names the processed row exactly, but only the
        payroll-type screens print it, and captures are ~7.7 s apart

    python explore/label_vs_process_code.py
"""
from __future__ import annotations
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from sklearn.metrics import completeness_score, homogeneity_score, v_measure_score

from caseid import anchors
from common import BUILD, load_index
from label import _route_from_placeholder

DS = "dataset_b"
ROW_ID = re.compile(r"^P\d+-\d{8}-\d{3}$")
CONFIRMED = re.compile(r"(P\d+-\d{8}-\d{3}): 登録確定しました")
code = lambda row_id: row_id.split("-")[0]


def report(name, pairs, n_seg, expect):
    lab = [l for l, _ in pairs]
    cod = [c for _, c in pairs]
    ok = sum(c in expect.get(l, set()) for l, c in pairs)
    print(f"\n{name}: {len(pairs)} of {n_seg} segments tied")
    print(f"  V-measure {v_measure_score(cod, lab):.3f}  (homogeneity {homogeneity_score(cod, lab):.3f}, "
          f"completeness {completeness_score(cod, lab):.3f})")
    print(f"  label names the screen that holds the code: {ok} of {len(pairs)} ({100 * ok / len(pairs):.1f}%)")
    print(pd.crosstab(pd.Series(lab, name="label"), pd.Series(cod, name="code")).to_string())


def main():
    seg = [json.loads(l) for l in (ROOT / "out" / "segments.jsonl").read_text(encoding="utf-8").splitlines()
           if l.strip()]
    fixture = json.loads((ROOT / "tool" / "mock_portal" / "fixture.json").read_text(encoding="utf-8"))
    ms = lambda s: pd.Timestamp(s).timestamp() * 1000

    expect = collections.defaultdict(set)          # our label -> the codes its screen's worklist holds
    for st in fixture.values():
        lab = f"{st['system']}__{_route_from_placeholder(st['placeholder'])}"
        expect[lab] |= {code(r["ID"]) for r in st["rows"]}
    shared = {lab: sorted(c) for lab, c in expect.items() if len(c) > 1}
    codes = sorted({c for cs in expect.values() for c in cs}, key=lambda c: int(c[1:]))
    print(f"process codes on the worklists: {len(codes)} ({', '.join(codes)}), on {len(expect)} screens")
    print(f"screens holding more than one code: {shared or 'none'}")

    a = anchors(DS)
    a = a[a.case.astype(str).str.match(ROW_ID)]
    by = {s: g for s, g in a.groupby("session_id")}
    pairs = []
    for s in seg:
        g = by.get(s["session_id"])
        if g is None:
            continue
        w = g[(g.ts_ms >= ms(s["start"])) & (g.ts_ms <= ms(s["end"]))]
        if len(w):
            pairs.append((s["label"], code(collections.Counter(w.case).most_common(1)[0][0])))
    report("case anchors inside the segment (label-blind)", pairs, len(seg), expect)

    df = load_index(DS)
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    conf = txt[txt.text.astype(str).str.contains("登録確定しました")]
    presses = df[df.el_tag == "button"]
    pairs = []
    for s in seg:
        p = presses[(presses.session_id == s["session_id"]) & (presses.ts_ms >= ms(s["start"]))
                    & (presses.ts_ms <= ms(s["end"]))].ts_ms
        if p.empty:
            continue
        c = conf[(conf.session_id == s["session_id"]) & (conf.ts_ms >= p.iloc[0])
                 & (conf.ts_ms <= p.iloc[0] + 15_000)]
        hits = [m.group(1) for m in map(CONFIRMED.search, c.text.astype(str)) if m]
        if hits:
            pairs.append((s["label"], code(hits[0])))
    report("the confirmation captured after the press", pairs, len(seg), expect)
    for lab in shared:
        split = collections.Counter(c for l, c in pairs if l == lab)
        print(f"\n{lab} holds {' and '.join(shared[lab])}; confirmed rows by code: {dict(split)}")


if __name__ == "__main__":
    main()
