"""Extract the decision rules the operators are actually applying.

The Step 3 design originally assumed the regulation documents were a judgment
problem - read the 規程, decide the handling - and therefore a RAG case. Reading
the captured content shows otherwise. The 接待交際費規程 says:

    第２条（承認権限）1回あたり5万円未満：部門長承認。5万円以上：役員承認。
                      10万円以上：社長承認。

That is a threshold table. Approval routing by amount is arithmetic, and
arithmetic belongs in code: it is exact, instant, free, auditable line by line
against the regulation, and it cannot hallucinate an approver.

The measured alternative is worse on every axis. Running the same rows through
the model gave 23 s median latency against 170 ms for the deterministic path
(135x), a 2-in-5 timeout rate, and notes that echoed the regulation's filename
back instead of composing anything.

So the model keeps exactly one job, and it is offline: reading a regulation
document once to *propose* a rule table, which a human checks before it ships.
Runtime stays deterministic. That is the opposite of the usual arrangement and
it is the right way round - the expensive, unreliable, unauditable component
runs once under supervision rather than on every transaction.
"""
from __future__ import annotations
import collections
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from common import load_index, BUILD                                  # noqa: E402

DOC_RE = re.compile(r"^(.*?)\s+(?:-|\[)\s*Compatibility Mode")

# Amount thresholds in Japanese regulation prose. 万円 = 10,000 yen.
THRESHOLD = re.compile(
    r"(\d[\d,]*)\s*(万円|円)\s*(未満|以上|以下|超)\s*[：:]\s*([^\n。、]{2,20})")


def corpus() -> dict[str, str]:
    """Longest captured text per regulation document."""
    df = load_index("dataset_b")
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))]
    tmap = dict(zip(txt.event_id, txt.text))
    best: dict[str, str] = {}
    w = df[(df.app == "Microsoft Word") & df.event_id.isin(tmap)]
    for r in w.itertuples():
        m = DOC_RE.match(str(r.title or ""))
        t = tmap.get(r.event_id)
        if m and t and len(t) > len(best.get(m.group(1).strip(), "")):
            best[m.group(1).strip()] = t
    return best


def to_yen(value: str, unit: str) -> int:
    n = int(value.replace(",", ""))
    return n * 10_000 if unit == "万円" else n


def extract_rules(text: str) -> list[dict]:
    """Threshold rules of the form '<amount><unit><comparator>: <outcome>'."""
    out = []
    for amount, unit, cmp_, outcome in THRESHOLD.findall(text):
        out.append({"yen": to_yen(amount, unit), "cmp": cmp_,
                    "outcome": outcome.strip()})
    # deduplicate, keep ascending by threshold so routing can walk it in order
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: r["yen"]):
        k = (r["yen"], r["cmp"], r["outcome"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def route(amount_yen: int, rules: list[dict]) -> str | None:
    """Apply the extracted threshold table to an amount."""
    hit = None
    for r in rules:
        if r["cmp"] in ("以上", "超") and amount_yen >= r["yen"]:
            hit = r["outcome"]
        elif r["cmp"] in ("未満", "以下") and amount_yen < r["yen"] and hit is None:
            hit = r["outcome"]
    return hit


if __name__ == "__main__":
    c = corpus()
    print(f"regulation documents with captured content: {len(c)}\n")
    total = 0
    for name, text in sorted(c.items(), key=lambda kv: -len(kv[1])):
        rules = extract_rules(text)
        total += len(rules)
        flag = "  <- decision rules" if rules else ""
        print(f"  {name[:44]:46} {len(text):5d} chars  rules={len(rules)}{flag}")
        for r in rules:
            print(f"      {r['yen']:>9,} yen {r['cmp']:4} -> {r['outcome']}")
    print(f"\ntotal machine-readable threshold rules extracted: {total}")

    for amt in (30_000, 60_000, 150_000):
        rules = extract_rules(c.get("gyomu_itaku_keihi_kitei", ""))
        print(f"  route({amt:,} yen) -> {route(amt, rules)}")
