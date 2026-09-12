"""What "fully automated" means, screen by screen.

The tool confirms a routine row with a templated note that reads 確認済. On
most screens that is the whole of the operator's recorded work. On some, Step 2
measured the operators opening a procedure or regulation in most runs - the
judgment the ranking treats as the part automation does not remove - and there
the tool performs the mechanical steps without that consultation.

This joins the last tool run (out/automation_run.json) with Step 2's judgment
load for the process each screen belongs to, and splits the automated rows at
"most runs": a regulation or procedure open in more than half of them.

A row that failed is in neither split - it is not automated - but it is in the
row count those shares are taken of. The delivered run has none. If one ever
does, the count is printed rather than left to be inferred from a column that
has quietly stopped adding up.

    python explore/automation_by_judgment.py
"""
from __future__ import annotations
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from label import _route_from_placeholder
from rank import build, PROCESS_NAME

RUN = ROOT / "out" / "automation_run.json"
FIXTURE = ROOT / "tool" / "mock_portal" / "fixture.json"
MOST = 50.0
AUTOMATED = ("automated", "automated_by_rule")


def main():
    for f in (FIXTURE, RUN):
        if not f.exists():
            sys.exit(f"{f} not found: run `python tool/extract_fixture.py` and "
                     "`python tool/run.py` first")
    run = json.loads(RUN.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    judgment = build()["judgment_%"].to_dict()
    label_of = {k: f"{st['system']}__{_route_from_placeholder(st['placeholder'])}"
                for k, st in fixture.items()}

    per = collections.defaultdict(collections.Counter)
    for o in run:
        per[o["system"]][o["mode"]] += 1

    print(f"{'screen':26} {'process':32} {'judgment':>8} {'automated':>9} {'to a person':>11}")
    heavy, light, unmeasured = [], [], []          # (judgment, automated rows) per screen
    rows = [(judgment.get(label_of.get(s)), s, c) for s, c in per.items()]
    for j, screen, c in sorted(rows, key=lambda r: -(r[0] if r[0] is not None else -1)):
        lab = label_of.get(screen)
        auto = sum(c[m] for m in AUTOMATED)
        name = PROCESS_NAME.get(lab, (lab,))[0]
        shown = f"{j:7.0f}%" if j is not None else "    n/a"
        print(f"{screen:26} {name:32} {shown} {auto:9d} {c['queued_for_review']:11d}")
        (unmeasured if j is None else heavy if j > MOST else light).append((j, auto))

    n = len(run)
    failed = sum(c["failed"] for c in per.values())
    total = lambda group: sum(a for _, a in group)
    print(f"\nautomated rows: {total(heavy) + total(light) + total(unmeasured)} of {n}")
    if heavy:
        lo, hi = min(j for j, _ in heavy), max(j for j, _ in heavy)
        print(f"  on screens whose operators consult a document in most runs: "
              f"{total(heavy)} ({100 * total(heavy) / n:.0f}% of all rows), "
              f"{len(heavy)} screens, judgment {lo:.0f}–{hi:.0f}%")
    print(f"  on the other screens: {total(light)} ({100 * total(light) / n:.0f}% of all rows), "
          f"{len(light)} screens")
    if unmeasured:
        print(f"  on screens with no Step 2 measurement: {total(unmeasured)}")
    # engine.py raises rather than let a drifted definition report "0 rows, 0
    # failed"; a run with failures in it must not read like a clean one here
    # either. Silent on the delivered run, which has none.
    if failed:
        where = dict(sorted((s, c["failed"]) for s, c in per.items() if c["failed"]))
        print(f"  rows that failed: {failed} - inside the {n} above, inside none\n"
              f"                    of the automated totals: {where}")


if __name__ == "__main__":
    main()
