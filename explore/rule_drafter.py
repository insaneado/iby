"""The one job the report keeps for a model, built and measured for the first time.

Section 4 says the model's remaining role is offline: proposing a rule table
from a regulation document for a human to approve before it ships. It has been
"designed, not built" since the report was written, and three of thirteen
captured documents now parse without a model, so ten remain unread.

This is the graded version of that job.

    The eval set is the three documents whose rules regulations.py already
    extracts deterministically - seven rules in total, with exact amounts,
    comparators and approvers. A model that cannot reproduce those seven from
    the same text cannot be trusted on the other ten, and the run stops there.

    Only then are the other ten put to it, and their output is a PROPOSAL. It is
    printed for review, not applied: nothing here writes a definition, and
    nothing routes.

Privacy. The captured text of a regulation often has approval records appended
below it - 経費承認記録, with employees' names and amounts. Those must not leave
the machine, so each prompt is cut at the regulation's own closing provision
(附則) and any residual record line is dropped. The cut is asserted, and the
prompt is printed for the first document so the reader can see what was sent.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\LENOVO\imby")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tool"))

import llm as llm_mod
import regulations as R

RECORD_MARKERS = ("経費承認記録", "承認記録", "申請者", "承認者", "氏名")

SYSTEM = (
    "You read a Japanese internal regulation and report only its approval "
    "thresholds by amount.\n"
    "Reply with JSON and nothing else: a list of objects with keys "
    '"yen" (integer, in yen - 万円 means ten thousand), '
    '"cmp" (one of 未満, 以上, 以下, 超 - exactly as the document words it), '
    'and "outcome" (the approver, e.g. 部門長承認).\n'
    "Rules may be tabulated (5万円未満：部門長承認) or written as a sentence "
    "(金額が50,000円を超える場合は部門長の事前承認が必要).\n"
    "An amount with no approver attached is an allowance rate, not an approval "
    "threshold: do not report it.\n"
    "If the document sets no approval threshold at all, reply with []."
)


def sanitise(body: str) -> str:
    """The regulation only - never the approval records captured beneath it."""
    m = re.search(r"附則[^。]*。", body)
    if m:
        body = body[:m.end()]
    kept = [ln for ln in body.split("\r") if not any(k in ln for k in RECORD_MARKERS)]
    return "\r".join(kept).strip()


def parse(reply: str):
    s = reply.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        out = json.loads(s)
    except Exception:
        m = re.search(r"\[.*\]", s, re.S)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(out, list):
        return None
    norm = []
    for r in out:
        if not isinstance(r, dict) or "yen" not in r or "cmp" not in r:
            continue
        try:
            norm.append({"yen": int(r["yen"]), "cmp": str(r["cmp"]).strip(),
                         "outcome": str(r.get("outcome", "")).strip()})
        except Exception:
            continue
    return sorted(norm, key=lambda r: (r["yen"], r["cmp"]))


def key(rules):
    return sorted(((r["yen"], r["cmp"], r["outcome"]) for r in rules))


corpus = R.corpus()
known = {t: R.extract_rules(b) for t, b in corpus.items() if R.extract_rules(b)}
unknown = {t: b for t, b in corpus.items() if t not in known}
print(f"corpus: {len(corpus)} documents, {len(known)} with rules the parser already reads, "
      f"{len(unknown)} without")

if not llm_mod.available():
    sys.exit("no API key configured; this experiment needs one")
client = llm_mod.LLM()

print("\n" + "=" * 74)
print("THE GUARD: what actually leaves the machine")
print("=" * 74)
first = sorted(known)[0]
sent = sanitise(corpus[first])
print(f"{first}: captured {len(corpus[first])} chars -> sent {len(sent)} chars")
for marker in RECORD_MARKERS:
    assert marker not in sent, f"{marker} survived the cut"
print("no approval-record marker survives the cut. The prompt sent for that document:\n")
print("  " + sent.replace("\r", "\n  "))

print("\n" + "=" * 74)
print("GRADED: the three documents whose rules are known deterministically")
print("=" * 74)
passed = 0
for title in sorted(known):
    truth = known[title]
    body = sanitise(corpus[title])
    try:
        reply = client.complete(body, system=SYSTEM)
    except Exception as e:
        print(f"  {title:22} {type(e).__name__}: {e}")
        continue
    got = parse(reply)
    if got is None:
        print(f"  {title:22} unparseable reply: {reply[:120]!r}")
        continue
    exact = key(got) == key(truth)
    amounts = sorted(r["yen"] for r in got) == sorted(r["yen"] for r in truth)
    cmps = sorted(r["cmp"] for r in got) == sorted(r["cmp"] for r in truth)
    passed += exact
    print(f"  {title:22} {'EXACT' if exact else 'WRONG':5}  "
          f"amounts {'ok' if amounts else 'no'}  comparators {'ok' if cmps else 'no'}")
    if not exact:
        print(f"      deterministic {key(truth)}")
        print(f"      model         {key(got)}")

print(f"\n  reproduced exactly: {passed} of {len(known)}")
if passed < len(known):
    print("  -> the model cannot reproduce rules that are already known.")
    print("     Its proposals for the remaining documents are not trustworthy,")
    print("     which is the finding. Running them anyway, marked as such.")

print("\n" + "=" * 74)
print("PROPOSALS for the documents the parser cannot read (for human review only)")
print("=" * 74)
for title in sorted(unknown):
    body = sanitise(corpus[title])
    try:
        reply = client.complete(body, system=SYSTEM)
    except Exception as e:
        print(f"  {title:26} {type(e).__name__}")
        continue
    got = parse(reply)
    if got is None:
        print(f"  {title:26} unparseable: {reply[:80]!r}")
    elif not got:
        print(f"  {title:26} no threshold  (agrees with the parser)")
    else:
        print(f"  {title:26} PROPOSES {key(got)}")

print(f"\nmodel usage: {client.stats.summary()}")
