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
(137x), a 2-in-5 timeout rate, and notes that echoed the regulation's filename
back instead of composing anything.

So the model keeps at most one job, and it would be offline: reading a
regulation document once to *propose* a rule table, which a human checks before
it ships. That job is designed, not built - the pattern below reads both
threshold tables in the captured regulations without one. Runtime stays deterministic. That
is the opposite of the usual arrangement and it is the right way round - the
expensive, unreliable, unauditable component would run once under supervision
rather than on every transaction.
"""
from __future__ import annotations
import collections
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from common import load_index, BUILD                                  # noqa: E402

# Amount thresholds in Japanese regulation prose. 万円 = 10,000 yen.
THRESHOLD = re.compile(
    r"(\d[\d,]*)\s*(万円|円)\s*(未満|以上|以下|超)\s*[：:]\s*([^\n。、]{2,20})")

# The same kind of rule, written out rather than tabulated. 接待交際費規程
# tabulates ("5万円未満：部門長承認"); 業務委託経費規程 writes "金額が50,000円を
# 超える場合は部門長の事前承認が必要" - no colon, and the comparator inflected,
# so the pattern above does not see it. An amount with no approver beside it
# is a rate rather than a routing rule: 家族手当規程 lists four allowance
# amounts and names no approver, and must not become a threshold table.
SENTENCE = re.compile(
    r"(\d[\d,]*)\s*(万円|円)\s*を?\s*(超える|超え|以上|未満|以下)\s*場合[はに]?[、]?\s*([^\r\n。]{2,30})")
CMP_FORMS = {"超える": "超", "超え": "超", "以上": "以上", "未満": "未満", "以下": "以下"}
APPROVER = re.compile(r"(取締役会|部門長|役員|社長|上長)")


# A regulation or procedure opens with the title it prints - ...規程, ...手続き, a
# list or a checklist - then its first article or item. Word puts paragraph
# marks after the title.
TITLE = re.compile(r"([^\s。、：:]{2,24}(?:規程|手続き|手続|チェックリスト|一覧))\s*(?=第[１1]条|１[．.]|1[．.]|\r)")


def bodies(text: str) -> dict[str, str]:
    """The regulations in one screen capture, keyed by the title each prints.

    A capture is logged under the Word window in focus, which is often not the
    document on screen, so a regulation is known by its own title and runs to
    the next title in the capture.
    """
    text = text or ""
    heads = list(TITLE.finditer(text))
    return {m.group(1): text[m.start():(heads[i + 1].start() if i + 1 < len(heads) else len(text))]
            for i, m in enumerate(heads)}


def corpus() -> dict[str, str]:
    """Longest captured text of each regulation, keyed by its own printed title.

    Not by the window title. Keyed that way, one window's longest capture was
    another regulation's approval table, and the tool routed a screen's rows by
    rules its operators never had on screen.
    """
    df = load_index("dataset_b")
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))]
    tmap = dict(zip(txt.event_id, txt.text))
    best: dict[str, str] = {}
    w = df[(df.app == "Microsoft Word") & df.event_id.isin(tmap)]
    for t in {str(tmap[e]) for e in w.event_id}:
        for title, body in bodies(t).items():
            if (len(body), body) > (len(best.get(title, "")), best.get(title, "")):
                best[title] = body
    return best


def to_yen(value: str, unit: str) -> int:
    n = int(value.replace(",", ""))
    return n * 10_000 if unit == "万円" else n


def extract_rules(text: str) -> list[dict]:
    """Threshold rules, in either form a captured regulation writes them."""
    out = []
    for amount, unit, cmp_, outcome in THRESHOLD.findall(text):
        out.append({"yen": to_yen(amount, unit), "cmp": cmp_,
                    "outcome": outcome.strip()})
    for amount, unit, cmp_, clause in SENTENCE.findall(text):
        who = APPROVER.search(clause)
        if not who:
            continue
        out.append({"yen": to_yen(amount, unit), "cmp": CMP_FORMS[cmp_],
                    "outcome": who.group(1) + ("決議" if "決議" in clause else "承認")})
    # deduplicate, keep ascending by threshold so routing can walk it in order
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: r["yen"]):
        k = (r["yen"], r["cmp"], r["outcome"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


# Each comparator keeps its own meaning. An earlier version folded 超 into 以上
# and 以下 into 未満, which sends an amount exactly at a threshold to the wrong
# approver. 業務委託経費規程 uses 超: "50,000円を超える" excludes 50,000 itself,
# so the distinction is load-bearing on this data and not only on a revision.
AT_LEAST = {"以上": lambda a, t: a >= t, "超": lambda a, t: a > t}     # lower bounds
BELOW = {"未満": lambda a, t: a < t, "以下": lambda a, t: a <= t}      # upper bounds


def route(amount_yen: int, rules: list[dict]) -> str | None:
    """Apply the extracted threshold table to an amount."""
    hit = None
    for r in rules:
        if r["cmp"] in AT_LEAST and AT_LEAST[r["cmp"]](amount_yen, r["yen"]):
            hit = r["outcome"]
        elif r["cmp"] in BELOW and BELOW[r["cmp"]](amount_yen, r["yen"]) and hit is None:
            hit = r["outcome"]
    return hit


# A regulation's own text: its title (...規程) and articles, through its closing
# provisions (附則). Screen captures carry other text beside it - notes above,
# approval records below - and those do not make the regulation govern anything.
# Word separates the title from 第１条 with paragraph marks (\r\r).
REG_BODY = re.compile(r"[^\s。、：:]{1,20}規程\s*第[１1]条.*?(?:附則[^。]*。|$)", re.S)


def governs(text: str, subject: str) -> bool:
    """Whether the regulation in `text` names `subject`, so its thresholds apply.

    A threshold table is arithmetic only for what it covers. The HR expense
    screen once routed overtime-allowance adjustments (残業手当調整) by the
    entertainment-expense regulation, which names entertainment expenses and
    nothing about pay. Without an identifiable regulation body, nothing is
    routed and a person decides.
    """
    m = REG_BODY.search(text or "")
    return bool(m and subject and str(subject).strip() in m.group(0))


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
        rules = extract_rules(c.get("接待交際費規程", ""))
        print(f"  route({amt:,} yen) -> {route(amt, rules)}")
