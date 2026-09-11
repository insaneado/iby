"""Step 2: rank automation candidates, with the reasoning made explicit.

The ranking is not a single score. It is a tension between two measurable
quantities, and the tension is the whole point:

  MECHANICAL LOAD   how much of the work is moving values between systems by
                    hand - clipboard events, application switches, keystrokes.
                    This is the part automation removes.

  JUDGMENT LOAD     how often the operator opens a regulation document to
                    decide how the case should be handled. This is the part
                    automation does not remove, and the part that decides
                    whether a deterministic script is even possible.

A process with high volume and high judgment load is a poor first target
however expensive it looks, because the residue is what costs the time. A
process with high volume, high mechanical load and low judgment load is the
one worth building.

Process names come from evidence, not from the portal's own route names. The
portal is one SPA deployed three times, so the routes repeat and mislead:
`ops__leave-applications` is contract termination work, and
`fin__leave-applications` is entertainment expense approval. The regulation
document open during the work says what the work is. How consistently each
label's segments consult one document is measured, not quoted here:
`report/step2_analysis.md` gives it per label, generated from the pipeline, and
`explore/verify_report.py` checks that every name below still cites the document
the data shows. (The purities once typed into this table had drifted by up to
27 points from the data.)
"""
from __future__ import annotations
import collections
import re

import pandas as pd

from common import load_index, ROOT
from analyze import load_segments, enrich, profile

DS = "dataset_b"
DOC_RE = re.compile(r"^(.*?)\s+(?:-|\[)\s*Compatibility Mode")

# Evidence-based names. Each is the dominant regulation document consulted
# during that label's segments; the gloss is my reading of the filename and is
# listed in docs/glossary.md for verification.
PROCESS_NAME = {
    "ops__leave-applications": ("contract_termination", "keiyaku_kaijo_tetsuzuki"),
    "hr__onboarding":          ("new_grad_onboarding", "nyusha_checklist_shinsotsu_batch"),
    "fin__payroll-items":      ("recurring_supplier_payment", "getsujitsu_teigaku_torihikisaki_ichiran"),
    "fin__onboarding":         ("contractor_payment_setup", "gyomu_itaku_kyuuyo_kitei"),
    "fin__leave-applications": ("entertainment_expense_approval", "settai_keihi_kitei"),
    "hr__social-insurance":    ("childcare_leave_handling", "ikuji_kyuugyou_kitei"),
    "fin__resident-tax":       ("new_supplier_registration", "shinkuitorihikisaki_touroku_tetsuzuki"),
    "hr__payroll-items":       ("payroll_item_maintenance", "gyomu_itaku_keihi_kitei"),
    "ops__social-insurance":   ("admin_privilege_request", "kanrisya_kengen_shinsei_tetsuzuki"),
    "ops__payroll-items":      ("inventory_payroll_items", None),     # 2 segments open a document: too few to name it by one
    "hr__leave-applications":  ("leave_application_review", None),
    "ops__resident-tax":       ("ops_supplier_registration", "shinkuitorihikisaki_touroku_tetsuzuki"),
    "ops__onboarding":         ("ops_onboarding", "nyusha_checklist_shinsotsu_batch"),
    "fin__social-insurance":   ("fin_social_insurance", None),
}


def doc_rate(seg: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """Share of a label's segments during which a regulation document is open."""
    by = {s: g.sort_values("ts_ms") for s, g in df.groupby("session_id")}
    has = []
    for r in seg.itertuples():
        g = by.get(r.session_id)
        e = g[(g.ts_ms >= r.start_ms) & (g.ts_ms <= r.end_ms)]
        has.append(any(DOC_RE.match(str(t)) for t in e.title.dropna()))
    seg = seg.assign(_doc=has)
    return seg.groupby("label")._doc.mean() * 100


def build() -> pd.DataFrame:
    df = load_index(DS)
    seg = enrich(load_segments(), df)
    p = profile(seg)
    p["judgment_%"] = doc_rate(seg, df)
    p["mechanical"] = p.clip_per_run + p.switch_per_run      # transfers per run
    p["process"] = [PROCESS_NAME.get(i, (i, None))[0] for i in p.index]

    # Rank on the hand transfers automation would remove, discounted by the
    # share of runs that need judgment: runs x transfers per run x (1 - judgment).
    # Deliberately simple and inspectable: an opaque score would be impossible
    # for a client to argue with, which is the wrong property here.
    #
    # The first version multiplied the share of TIME by transfers PER RUN, which
    # counts run length twice: two processes with the same total time and the
    # same total transfers came out ten times apart if one's runs were ten times
    # as long. It ranked third a process this formula ranks fifth.
    p["automatability"] = (1 - p["judgment_%"].div(100)).clip(lower=0.05)
    p["priority"] = p.n * p.mechanical * p.automatability
    return p.sort_values("priority", ascending=False)


if __name__ == "__main__":
    p = build()
    pd.set_option("display.width", 220)
    cols = ["process", "n", "total_min", "share_%", "median_s", "cv", "people",
            "mechanical", "judgment_%", "priority"]
    print(p[cols].round(1).to_string())
    print(f"\ntotal observed work: {p.total_min.sum():.0f} min across "
          f"{int(p.n.sum())} executions, {p.people.max()} operators")
