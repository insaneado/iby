"""Generate report/step2_analysis.md from the pipeline.

Written after finding the hand-maintained version had gone stale: it still
carried figures from three pipeline revisions earlier, in a file sitting in
`report/` as a deliverable. Numbers that are typed once drift; numbers that are
generated cannot. Prose that carries no figures stays inline here - but prose
that states a comparison is generated too, because typed once, "the
second-lowest judgment load" drifted into being false.

    python src/make_step2_report.py
"""
from __future__ import annotations
import collections
import json
import re

import pandas as pd

from common import load_index, ROOT, BUILD
from analyze import load_segments, enrich, profile
from rank import build, PROCESS_NAME, DOC_RE

DS = "dataset_b"
SYSTEMS = {"HR人事給与システム": "hr", "財務会計システム": "fin",
           "受発注在庫管理システム": "ops"}
# how the portal prints who is logged in: "<family> <given> · <role>マネージャー"
LOGIN_RE = re.compile(r"([一-鿿]{2,4}\s+[一-鿿]{2,4})\s*·\s*([一-鿿ァ-ヿ]+マネージャー)")
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
ORDINAL = ["lowest", "second-lowest", "third-lowest", "fourth-lowest", "fifth-lowest"]


def scale(seg, df):
    return dict(
        n=len(seg), minutes=seg.dur.sum() / 60,
        sessions=seg.session_id.nunique(), operators=seg.machine.nunique(),
        users=df.user.nunique(), machines=df.machine.nunique(),
        days=sorted({s[:10] for s in seg.start}),
    )


def logins(df):
    """Every operator name the portal shows, and where each appears.

    A name that belonged to a person would appear on that person's machine, in
    whichever systems they used. These appear on every machine, each in one
    system - the evidence that they are shared per-system logins. The report
    once said all three appear in every session; one appears in 13 of 15.
    """
    txt = pd.read_parquet(BUILD / "extracted_text.parquet")
    txt = txt[txt.event_id.isin(set(df.event_id))].merge(
        df[["event_id", "machine"]], on="event_id")
    seen = collections.defaultdict(lambda: {"systems": collections.Counter(),
                                            "sessions": set(), "machines": set()})
    for r in txt.itertuples():
        system = next((v for k, v in SYSTEMS.items() if k in r.text), None)
        for m in LOGIN_RE.finditer(r.text):
            s = seen[m.group(1)]
            s["sessions"].add(r.session_id)
            s["machines"].add(r.machine)
            if system:
                s["systems"][system] += 1
    rows = []
    for s in seen.values():
        tot = sum(s["systems"].values())
        home, k = s["systems"].most_common(1)[0] if tot else ("?", 0)
        rows.append((home, len(s["machines"]), len(s["sessions"]),
                     100 * k / tot if tot else 0.0))
    return sorted(rows)            # (system, machines, sessions, % in that system)


def doc_evidence(seg, df):
    """Dominant regulation document per label, and the weighted purity."""
    by = {s: g.sort_values("ts_ms") for s, g in df.groupby("session_id")}
    per = collections.defaultdict(collections.Counter)
    for r in seg.itertuples():
        g = by.get(r.session_id)
        e = g[(g.ts_ms >= r.start_ms) & (g.ts_ms <= r.end_ms)]
        docs = collections.Counter()
        for t in e.title.dropna():
            m = DOC_RE.match(str(t))
            if m:
                docs[m.group(1).strip()] += 1
        if docs:
            per[r.label][docs.most_common(1)[0][0]] += 1
    tot = pure = 0
    rows = []
    for lab, c in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        top, k = c.most_common(1)[0]
        tot += n
        pure += k
        rows.append((lab, top, n, 100 * k / n))
    return rows, (100 * pure / tot if tot else 0)


def robustness(p):
    sch = {
        "total time": p["total_min"], "execution count": p["n"],
        "time x automatability": p["total_min"] * p["automatability"],
        "mechanical x count": p["mechanical"] * p["n"],
        "shipped formula": p["priority"],
        "time x mech x autom": p["total_min"] * p["mechanical"] * p["automatability"],
    }
    c = collections.Counter(x for v in sch.values()
                            for x in p["process"][v.nlargest(3).index])
    return c, len(sch)


def screen_table(p5):
    """Processes aggregated by portal screen.

    Judgment is the share of the screen's RUNS with a regulation document open,
    the same definition as per process. It used to be the plain mean of the
    per-system percentages, which weighted fin's 8 social-insurance runs like
    hr's 120 payroll runs, and showed social-insurance lowest at 22% when its
    runs consult a document 28% of the time.
    """
    x = p5.assign(screen=[i.split("__")[1] for i in p5.index],
                  doc_runs=p5["judgment_%"] * p5["n"] / 100)
    g = x.groupby("screen").agg(
        n=("n", "sum"), total_min=("total_min", "sum"), share=("share_%", "sum"),
        systems=("n", "size"), doc_runs=("doc_runs", "sum"))
    g["judgment"] = 100 * g.doc_runs / g.n
    return g.sort_values("total_min", ascending=False)


def judgment_standing(g, band=2.0):
    """The top screen's judgment rank, and the screens within `band` points of
    it - close enough that the rank on its own would overstate the difference."""
    top = g.index[0]
    j = g.judgment
    rank = int((j < j[top]).sum())
    near = sorted((s for s in g.index if s != top and abs(j[s] - j[top]) < band),
                  key=lambda s: j[s])
    word = ORDINAL[rank] if rank < len(ORDINAL) else f"{rank + 1}th-lowest"
    return word, near


def main():
    df = load_index(DS)
    seg = enrich(load_segments(), df)
    p = build()
    p5 = p[p.n >= 5]
    sc = scale(seg, df)
    docs, purity = doc_evidence(seg, df)
    rob, nsch = robustness(p5)
    lg = logins(df)

    L = []
    A = L.append
    A("# Step 2 — what the work is, and what to automate\n")
    A("*Generated by `src/make_step2_report.py` from `out/segments.jsonl`. "
      "Do not edit by hand — an earlier hand-maintained version silently went "
      "three pipeline revisions out of date.*\n")
    A("All figures are **relative**. The brief states the recordings were made "
      "in a test environment with compressed waiting times, so absolute "
      "durations are meaningless and only comparisons between processes are "
      "valid.\n")

    A("## Scale\n")
    when = (f"all on {sc['days'][0]}" if len(sc["days"]) == 1
            else f"from {sc['days'][0]} to {sc['days'][-1]}")
    A(f"**{sc['n']} executions, {sc['minutes']:.0f} minutes of observed work, "
      f"{sc['sessions']} sessions, {sc['operators']} operators**, {when}.\n")
    A("### How many people\n")
    A("| source | count |\n|---|---:|")
    A(f"| `username_hash` | {sc['users']} |")
    A(f"| `machine_id` | {sc['machines']} |")
    A(f"| operator names on the portal dashboard | {len(lg)} |\n")
    A("Where each of those names appears. The names themselves are withheld; each "
      "row is keyed by the system the name belongs to.\n")
    A("| name belongs to | machines it appears on | sessions it appears in | "
      "appearances in that system |")
    A("|---|---:|---:|---:|")
    for home, nm, ns, cons in lg:
        A(f"| {home} | {nm} of {sc['machines']} | {ns} of {sc['sessions']} | {cons:.0f}% |")
    if lg and all(nm == sc["machines"] for _, nm, _, _ in lg) and min(c for *_, c in lg) >= 90:
        A(f"\nThe {WORDS.get(len(lg), len(lg))} names are **not** operators — each "
          "appears on every machine, and each belongs to one portal system. They "
          f"are shared per-system logins. So: **{sc['operators']} people** working "
          "across three systems under shared accounts, which is a governance "
          "finding rather than a trivial one — automation would run with no "
          "per-user audit trail.\n")
    else:
        A("\n**This no longer supports reading the names as shared logins.** The "
          "headcount and the shared-account risk both need revisiting before "
          "either is quoted.\n")

    A("## The route names describe nothing\n")
    A("The portal is one SPA deployed three times, so its route names repeat. "
      "The regulation document open during the work identifies it instead:\n")
    A("| segment label | dominant document | segments | purity |")
    A("|---|---|---:|---:|")
    for lab, top, n, pur in docs[:10]:
        A(f"| `{lab}` | {top} | {n} | {pur:.0f}% |")
    A(f"\nWeighted document purity across labels: **{purity:.1f}%**. The "
      "pipeline never reads document names, so this is independent evidence "
      "that the groupings track real business processes.\n")

    A("## Ranking\n")
    A("Two measurable quantities in tension: **mechanical load** (clipboard "
      "events and application switches per run — what automation removes) "
      "against **judgment load** (share of runs with a regulation document "
      "open — what it does not). High volume with high judgment is a poor "
      "first target, because the residue is what costs the time.\n")
    A("| process | n | min | share | median | mech | judgment | people |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in p5.iterrows():
        A(f"| {r['process']} | {int(r['n'])} | {r['total_min']:.1f} | "
          f"{r['share_%']:.1f}% | {r['median_s']:.0f} s | {r['mechanical']:.1f} | "
          f"{r['judgment_%']:.0f}% | {int(r['people'])} |")

    A(f"\n### Robustness\n")
    A(f"A priority formula is easy to make say what you want, so the ranking "
      f"was scored under {nsch} different weightings. Processes with n < 5 were "
      f"excluded, since per-run rates on one or two observations are noise.\n")
    A("| process | top-3 appearances |\n|---|---|")
    for name, k in rob.most_common():
        bold = "**" if k == nsch else ""
        A(f"| {bold}{name}{bold} | {bold}{k} / {nsch}{bold} |")
    survivors = [name for name, k in rob.most_common() if k == nsch]
    if len(survivors) == 1:
        lead = f"Only **{survivors[0]}** survives every weighting."
    elif survivors:
        lead = f"{len(survivors)} processes survive every weighting: " + \
               ", ".join(f"**{s}**" for s in survivors) + "."
    else:
        name, k = rob.most_common(1)[0]
        lead = (f"No process survives every weighting; the most robust is "
                f"**{name}**, in the top three under {k} of {nsch}.")
    A(f"\n{lead} Anything appearing once is an artefact of a particular formula, "
      "not a finding.\n")

    A("## The result that sets the scope\n")
    g = screen_table(p5)
    A("Aggregating by portal **screen** rather than by system. Judgment is the "
      "share of the screen's runs with a regulation document open:\n")
    A("| screen | executions | minutes | share of all work | systems | judgment |")
    A("|---|---:|---:|---:|---:|---:|")
    for i, r in g.iterrows():
        b = "**" if i == g.index[0] else ""
        A(f"| {b}{i}{b} | {b}{int(r['n'])}{b} | {b}{r['total_min']:.1f}{b} | "
          f"{b}{r['share']:.1f}%{b} | {b}{int(r['systems'])}{b} | {r['judgment']:.0f}% |")
    top = g.index[0]
    word, near = judgment_standing(g)
    j = g.judgment
    level = (f", though only just: {j[top]:.1f}%, against "
             + " and ".join(f"{j[s]:.1f}% for {s}" for s in near)
             if near else f" ({j[top]:.0f}%)")
    para = (f"\n**One screen pattern accounts for {g.loc[top,'share']:.1f}% of all "
            f"observed work**, occurs in {int(g.loc[top,'systems'])} systems, and "
            f"carries the {word} judgment load of the {WORDS.get(len(g), len(g))} "
            f"screens{level}.")
    if all(i.split("__")[1] == top for i in p5.index[:3]):
        para += (" The three top-ranked processes are this one screen in different "
                 "deployments.")
    A(para + "\n")
    A("That reframes Step 3: the choice is not *which process to automate* but "
      "*one bespoke process, or the shared pattern behind several* — which is "
      "exactly the scope question the brief says is itself part of the ROI "
      "decision.\n")

    dest = ROOT / "report" / "step2_analysis.md"
    dest.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {dest}  ({len(L)} lines)")
    print(f"  {sc['n']} executions, {sc['minutes']:.0f} min, {sc['operators']} operators")
    print(f"  top screen: {top} at {g.loc[top,'share']:.1f}%, {word} judgment load")


if __name__ == "__main__":
    main()
