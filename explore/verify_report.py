"""Reconcile every load-bearing figure in the report with a fresh run.

Each check re-derives a figure from the current pipeline and compares it with
the figure *as written in the document* - parsed out of REPORT.md,
SUMMARY_JA.md, README.md and tool/README.md, never typed into this script.
Comparisons stated in prose ("the lowest judgment load of the five screens")
are checked as well as numbers: one of those had drifted into being false.

An earlier version kept the claimed values as literals here. It compared the
pipeline with its own copy of the numbers, reported 21/21, and could not see
that the report and the Japanese summary still quoted an earlier pipeline in a
dozen places. One of its 21 checks compared against a figure the report does not
contain at all. A check that cannot see the thing it checks is not a check.

Figures that come from the slower audits are taken from those audits' own
output, so each audit stays the single source of truth for its numbers. What it
does not re-derive: figures the report presents as history - the phase table,
v3's memo position, the LLM experiment - and a few descriptive statistics quoted
once (click positions, the gap median, the capture interval). Takes about ten
minutes. Exits non-zero if anything is stale.

    python verify_report.py
"""
import collections
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
from sklearn.metrics import v_measure_score

from baseline import operator_events, split_on_gap, split_on_app_switch
from common import load_index
from evaluate import evaluate
from gold import load_gold
from label import SignatureLabeller
from segment import event_bounds
from segment_v4 import segment_dataset_v4

REPORT = (ROOT / "report" / "REPORT.md").read_text(encoding="utf-8")
JA = (ROOT / "report" / "SUMMARY_JA.md").read_text(encoding="utf-8")
STEP2 = (ROOT / "report" / "step2_analysis.md").read_text(encoding="utf-8")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
checks: list[tuple[str, str, str]] = []


def grab(doc: str, pattern: str) -> str:
    """The figure as written. MISSING if the sentence it lives in is gone.

    A space in a pattern matches any run of whitespace, so re-wrapping a
    paragraph of Markdown cannot turn a correct figure into a MISSING one.
    """
    m = re.search(pattern.replace(" ", r"\s+"), doc, re.S)
    # a figure that ends a sentence must not carry the full stop with it
    return m.group(1).rstrip(".") if m else "MISSING"


def printed(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1).rstrip(".") if m else "NOT PRINTED"


def check(name, actual, written):
    a, w = str(actual), str(written)
    checks.append((name, a, w))
    print(f"  [{'OK  ' if a == w else 'STALE'}] {name:46} actual={a:<12} written={w}", flush=True)


def audit(script: str) -> str:
    r = subprocess.run([sys.executable, script], cwd=ROOT / "explore", capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=ENV)
    if r.returncode:
        sys.exit(f"{script} failed:\n{r.stdout[-1500:]}{r.stderr[-1500:]}")
    return r.stdout


f3 = lambda x: f"{x:.3f}"
ours = lambda label: rf"\| {label} \| [\d.,%]+ \| \*\*([\d.,%]+)\*\*"     # delivered column
theirs = lambda label: rf"\| {label} \| ([\d.,%]+) \|"                     # baseline column

# ---- Step 1, dataset A: the shipped configuration ----------------------------
gold = load_gold("dataset_a")
lab = SignatureLabeller("dataset_a")
r = evaluate(gold, segment_dataset_v4("dataset_a", event_bounds("dataset_a"),
                                      labeller=lab, expand_gap_s=60))
b2, b5, b10 = (f3(r.bf1[t][2]) for t in (2.0, 5.0, 10.0))
print("Step 1 - dataset A, shipped pipeline")
check("results table: BF1@2s", b2, grab(REPORT, ours("boundary F1 @2s")))
check("results table: BF1@5s", b5, grab(REPORT, ours(r"\*\*boundary F1 @5s\*\*")))
check("results table: BF1@10s", b10, grab(REPORT, ours("boundary F1 @10s")))
check("results table: WindowDiff", f3(r.windowdiff), grab(REPORT, ours(r"WindowDiff \(lower better\)")))
check("results table: V-measure", f3(r.v_measure), grab(REPORT, ours(r"V-measure \(label consistency\)")))
check("results table: segments", f"{r.n_pred:,}", grab(REPORT, ours("segments produced")))
check("results table: idle claimed", f"{100 * r.idle_pred:.1f}%", grab(REPORT, ours("idle time claimed")))
check("summary: BF1@5s", b5, grab(REPORT, r"Using both edges lifted boundary F1.*?\*\*([\d.]+)\*\*"))
check("summary: BF1@2s", b2, grab(REPORT, r"Using both edges lifted boundary F1.*?\*\*[\d.]+\*\*.*?\*\*([\d.]+)\*\*"))
check("ablation table: shipped BF1@2s", b2, grab(REPORT, r"\| shipped \| ([\d.]+) \|"))
check("ablation table: shipped V", f3(r.v_measure), grab(REPORT, r"\| shipped \| [\d.]+ \| ([\d.]+) \|"))
check("ablation table: shipped ARI", f3(r.ari), grab(REPORT, r"\| shipped \| [\d.]+ \| [\d.]+ \| ([\d.]+) \|"))
check("sensitivity: BF1@2s held at", b2, grab(REPORT, r"leave BF1@2s unchanged at ([\d.]+)"))
check("R8: BF1@2s", b2, grab(REPORT, r"\*\*R8\*\*.*?BF1@2s = ([\d.]+)"))
check("R8: BF1@10s", b10, grab(REPORT, r"\*\*R8\*\*.*?BF1@2s = [\d.]+ against ([\d.]+) at 10 s"))
check("JA: BF1@2s", b2, grab(JA, ours("境界F1（±2秒）")))
check("JA: BF1@5s", b5, grab(JA, ours("境界F1（±5秒）")))
check("JA: WindowDiff", f3(r.windowdiff), grab(JA, ours("WindowDiff（低いほど良い）")))
check("JA: V-measure", f3(r.v_measure), grab(JA, ours("ラベル一貫性（V値）")))
check("JA: segments", f"{r.n_pred:,}", grab(JA, ours("区間数（正解2,009）")))

truth, guess = [], []
for segs, _, _ in gold.values():
    for s in segs:
        truth.append(s.label)
        guess.append(lab(s))
check("labeller V on gold segments", f3(v_measure_score(truth, guess)),
      grab(REPORT, r"V = ([\d.]+) on gold segments"))

# Why no department can be held out: every session mixes all three. Each gold
# family's department is read off the labeller's system prefix on that family's
# own segments, not typed in.
dept_of = {}
for fam in set(truth):
    prefixes = collections.Counter(g.split("__")[0] for t, g in zip(truth, guess) if t == fam)
    dept_of[fam] = prefixes.most_common(1)[0][0]
mixed = sum(len({dept_of[s.label] for s in segs}) == 3 for segs, _, _ in gold.values())
check("sessions containing all three departments", mixed,
      grab(REPORT, r"every one of the (\d+) sessions contains work from all three"))

# ---- the baselines, rescored with the current matcher ------------------------
df_a = load_index("dataset_a")
# The baselines' own input, through the same function baseline.py uses. A first
# version of this check fed them the raw index, screen captures included, and
# flagged the report's correct baseline figures as stale.
ops = operator_events(df_a)
g3 = evaluate(gold, split_on_gap(ops, gold, 3))
g3_app = evaluate(gold, split_on_gap(ops, gold, 3, by_app=True))
g10 = evaluate(gold, split_on_gap(ops, gold, 10))
n_g2 = sum(len(v) for v in split_on_gap(ops, gold, 2).values())
sw = evaluate(gold, split_on_app_switch(ops, gold))
print("\nbaselines")
check("baseline column: BF1@2s", f3(g3.bf1[2.0][2]), grab(REPORT, theirs("boundary F1 @2s")))
check("baseline column: BF1@5s", f3(g3.bf1[5.0][2]), grab(REPORT, theirs(r"\*\*boundary F1 @5s\*\*")))
check("baseline column: BF1@10s", f3(g3.bf1[10.0][2]), grab(REPORT, theirs("boundary F1 @10s")))
check("baseline column: WindowDiff", f3(g3.windowdiff), grab(REPORT, theirs(r"WindowDiff \(lower better\)")))
check("baseline column: V (app switch)", f3(sw.v_measure), grab(REPORT, theirs(r"V-measure \(label consistency\)")))
check("baseline column: segments", f"{g3.n_pred:,}", grab(REPORT, theirs("segments produced")))
check("baseline column: idle claimed", f"{100 * g3.idle_pred:.1f}%", grab(REPORT, theirs("idle time claimed")))
check("gap baseline prose: BF1@5s", f3(g3.bf1[5.0][2]), grab(REPORT, r"it reached BF1@5s ([\d.]+) and V-measure"))
check("gap baseline prose: V", f3(g3_app.v_measure), grab(REPORT, r"it reached BF1@5s [\d.]+ and V-measure ([\d.]+)"))
check("gap baseline prose: segments at 2 s", f"{n_g2:,}", grab(REPORT, r"at 2 s it emits ([\d,]+) segments"))
check("gap baseline prose: recall at 10 s", f"{100 * g10.bf1[5.0][1]:.0f}%",
      grab(REPORT, r"at 10 s it finds only (\d+%) of true boundaries"))
check("best baseline, against chance", f3(g3.bf1[5.0][2]), grab(REPORT, r'the "best baseline" at ([\d.]+)'))
check("app-switch baseline prose: V", f3(sw.v_measure), grab(REPORT, r"\(V = ([\d.]+)\): operators switch"))
check("JA baseline: BF1@2s", f3(g3.bf1[2.0][2]), grab(JA, theirs("境界F1（±2秒）")))
check("JA baseline: BF1@5s", f3(g3.bf1[5.0][2]), grab(JA, theirs("境界F1（±5秒）")))
check("JA baseline: V", f3(sw.v_measure), grab(JA, theirs("ラベル一貫性（V値）")))

# ---- the two clicks ----------------------------------------------------------
print("\nsignals quoted in the report")
n_td, n_btn = f"{(df_a.el_tag == 'td').sum():,}", f"{(df_a.el_tag == 'button').sum():,}"
check("row-selection clicks (A)", n_td, grab(REPORT, r"Selecting a\s+record opens it \(([\d,]+) clicks"))
check("confirm presses (A)", n_btn, grab(REPORT, r"a confirm press closes it \(([\d,]+) presses"))
check("JA: row-selection clicks", n_td, grab(JA, r"対象行の選択クリック（([\d,]+)件"))
check("JA: confirm presses", n_btn, grab(JA, r"確定ボタン\s*（([\d,]+)件"))

# ---- Step 2, dataset B deliverable -------------------------------------------
seg = [json.loads(l) for l in (ROOT / "out" / "segments.jsonl").read_text(encoding="utf-8").splitlines()
       if l.strip()]
secs = lambda s: (pd.Timestamp(s["end"]) - pd.Timestamp(s["start"])).total_seconds()
minutes = f"{sum(secs(s) for s in seg) / 60:.0f}"
n_sess = len({s["session_id"] for s in seg})
print("\nStep 2 - dataset B")
check("executions", len(seg), grab(REPORT, r"back-office work: (\d+) executions"))
check("minutes of work", minutes, grab(REPORT, r"Dataset B contains \*\*(\d+) minutes"))
check("sessions", n_sess, grab(REPORT, r"executions across (\d+)\s+sessions"))
check("distinct labels", len({s["label"] for s in seg}), grab(REPORT, r"\d+ segments, \d+ sessions, (\d+) labels"))
check("limitations: minutes observed", minutes, grab(REPORT, r'coverage" describes (\d+) observed minutes'))
check("JA: executions", len(seg), grab(JA, r"(\d+)件の実行"))
check("JA: minutes", minutes, grab(JA, r"(\d+)分の業務"))
check("JA: sessions", n_sess, grab(JA, r"(\d+)セッション"))

# R1: the graded dataset's own telemetry gap - sessions with no L3 event at all
b_idx = load_index("dataset_b")
gap_sids = {sid for sid, x in b_idx.groupby("session_id") if (x.layer == "L3").sum() == 0}
gap_segs = [s for s in seg if s["session_id"] in gap_sids]
gap_share = f"{100 * sum(secs(s) for s in gap_segs) / sum(secs(s) for s in seg):.1f}"
check("R1: dataset B sessions with zero L3 events", len(gap_sids), grab(REPORT, r"same gap in \*\*(\d+) of its \d+ sessions\*\*"))
check("R1: dataset B sessions", n_sess, grab(REPORT, r"same gap in \*\*\d+ of its (\d+) sessions\*\*"))
check("R1: segments from the gap session", len(gap_segs), grab(REPORT, r"sessions\*\*: (\d+) of its \d+ segments"))
check("R1: dataset B segments", len(seg), grab(REPORT, r"sessions\*\*: \d+ of its (\d+) segments"))
check("R1: share of time in the gap session", gap_share, grab(REPORT, r"segments, ([\d.]+)% of the time, come from"))

share, count = collections.Counter(), collections.Counter()
for s in seg:
    screen = s["label"].split("__")[1]
    share[screen] += secs(s)
    count[screen] += 1
total = sum(share.values())
top = share.most_common(1)[0][0]
pct = lambda screen: f"{100 * share[screen] / total:.1f}%"
check("top screen", top, grab(REPORT, r"\| \*\*([a-z-]+)\*\* \| \*\*\d+\*\* \|"))
check("top screen: executions", count[top], grab(REPORT, rf"\| \*\*{top}\*\* \| \*\*(\d+)\*\*"))
check("top screen: minutes", f"{share[top] / 60:.1f}", grab(REPORT, rf"\| \*\*{top}\*\* \| \*\*\d+\*\* \| \*\*([\d.]+)\*\*"))
check("top screen: share (table)", pct(top), grab(REPORT, rf"\| \*\*{top}\*\* \| \*\*\d+\*\* \| \*\*[\d.]+\*\* \| \*\*([\d.]+%)\*\*"))
check("top screen: share (summary)", pct(top), grab(REPORT, r"One screen pattern carries ([\d.]+%)"))
check("leave-applications: share", pct("leave-applications"), grab(REPORT, r"\| leave-applications \| \d+ \| [\d.]+ \| ([\d.]+%)"))
check("JA: top screen share", pct(top), grab(JA, r"全業務時間の([\d.]+%)"))
check("JA: top screen executions", count[top], grab(JA, r"全業務時間の[\d.]+%\*\*（(\d+)件"))
check("JA: top screen minutes", f"{share[top] / 60:.1f}", grab(JA, r"全業務時間の[\d.]+%\*\*（\d+件、([\d.]+)分）"))

# step2_analysis.md is generated from the pipeline, so it is the reference here
words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}
once = len(re.findall(r"\| 1 / 6 \|", STEP2))
check("ranking: processes in the top three once", words.get(once, once), grab(REPORT, r"(\w+) processes appear exactly once"))
check("document purity", grab(STEP2, r"Weighted document purity across labels: \*\*([\d.]+%)\*\*"),
      grab(REPORT, r"\*\*([\d.]+%) weighted purity\*\*"))

# ---- Step 3 ------------------------------------------------------------------
run = json.loads((ROOT / "out" / "automation_run.json").read_text(encoding="utf-8"))
modes = collections.Counter(o["mode"] for o in run)
n = len(run)
auto = modes["automated"] + modes["automated_by_rule"]
left = modes["queued_for_review"]
share_of = lambda k: f"{100 * k / n:.0f}%"
queued = [o for o in run if o["mode"] == "queued_for_review"]
ms = sorted(o["ms"] for o in run)
screens = len({o["system"] for o in run})
print("\nStep 3 - automation")
check("rows handled", f"{n:,}", grab(REPORT, r"Measured result — all ([\d,]+) rows"))
check("screens", screens, grab(REPORT, r"Measured result — all [\d,]+ rows across (\d+) screens"))
check("routine, templated note", modes["automated"], grab(REPORT, r"\| routine, templated note \| (\d+) \|"))
check("routed by regulation threshold", modes["automated_by_rule"],
      grab(REPORT, r"\| flagged rows routed by regulation threshold \| (\d+) \|"))
check("fully automated", auto, grab(REPORT, r"\| \*\*fully automated\*\* \| \*\*(\d+)\*\*"))
check("automation rate", share_of(auto), grab(REPORT, r"\| \*\*fully automated\*\* \| \*\*\d+\*\* \| \*\*(\d+%)\*\*"))
check("left for a person", left, grab(REPORT, r"\| left for a person \| (\d+) \|"))
check("failures", modes["failed"], grab(REPORT, r"\| \*\*failed\*\* \| \*\*(\d+)\*\*"))
check("summary: screens", screens, grab(REPORT, r"covers \*\*all (\d+) portal worklist screens"))
check("summary: rows", f"{n:,}", grab(REPORT, r"portal worklist screens — ([\d,]+) rows"))
check("summary: automation rate", share_of(auto), grab(REPORT, r"portal worklist screens — [\d,]+ rows, (\d+%)"))
check("scope correction: screens", screens, grab(REPORT, r"exposed \*\*(\d+) screens"))
check("scope correction: rows", f"{n:,}", grab(REPORT, r"exposed \*\*\d+ screens, ([\d,]+) rows"))
check("definition files", len(list((ROOT / "tool" / "definitions").glob("*.yaml"))),
      grab(REPORT, r"One engine plus (\d+) definition files"))
check("median ms per row", f"{np.median(ms):.0f}", grab(REPORT, r"Median (\d+) ms per row"))
check("p95 ms per row (nearest rank)", f"{ms[math.ceil(0.95 * n) - 1]:.0f}", grab(REPORT, r"Median \d+ ms per row, p95 (\d+) ms"))
check("remaining: rows", left, grab(REPORT, r"\*\*(\d+) of [\d,]+ rows \(\d+%\)\*\*"))
check("remaining: share", share_of(left), grab(REPORT, r"\*\*\d+ of [\d,]+ rows \((\d+%)\)\*\*"))
check("remaining: contract rows", sum("契約" in o["system"] for o in queued), grab(REPORT, r"(\d+) contract rows"))
check("remaining: inventory adjustments", sum("在庫" in o["system"] for o in queued), grab(REPORT, r"and (\d+) inventory adjustments"))
check("impact: automation rate", share_of(auto), grab(REPORT, r"Across them, \*\*(\d+%) of rows\*\*"))
check("R2: upper bound", share_of(auto), grab(REPORT, r"Treat (\d+%) as an upper bound"))
check("limitations: coverage", share_of(auto), grab(REPORT, r'at (\d+%) coverage" describes'))
check("JA: rows", f"{n:,}", grab(JA, r"実測結果（全([\d,]+)行"))
check("JA: routine", modes["automated"], grab(JA, r"\| 定常処理（定型文で自動化） \| (\d+) \|"))
check("JA: routed by threshold", modes["automated_by_rule"], grab(JA, r"\| 要確認行（規程の金額基準で自動振分） \| (\d+) \|"))
check("JA: fully automated", auto, grab(JA, r"\| \*\*完全自動化\*\* \| \*\*(\d+)\*\*"))
check("JA: automation rate", share_of(auto), grab(JA, r"\| \*\*完全自動化\*\* \| \*\*\d+\*\* \| \*\*(\d+%)\*\*"))
check("JA: left for a person", left, grab(JA, r"\| 人手が必要 \| (\d+) \|"))
check("JA: remaining rows", left, grab(JA, r"\*\*[\d,]+行中(\d+)行（\d+%）\*\*"))
check("JA: impact rate", share_of(auto), grab(JA, r"その範囲内で(\d+%)を自動処理"))
check("JA: median ms per row", f"{np.median(ms):.0f}", grab(JA, r"1行あたり中央値(\d+)ミリ秒"))

# ---- validation figures, from the audits' own output -------------------------
print("\nvalidation - re-running metric_audit.py and overfit_audit.py", flush=True)
ma = audit("metric_audit.py")
rnd = printed(ma, r"1\. RANDOM .*?BF1@5=([\d.]+)")
disc = printed(ma, r"discrimination on BF1@5s: \+([\d.]+)")
shuf = printed(ma, r"LABELS SHUFFLED.*?V=([\d.]+)")
rnd_med = printed(ma, r"random control: .*?median coverage ([\d.]+)%")
check("random control: BF1@5s", rnd, grab(REPORT, r"segment count scores BF1@5s ([\d.]+)"))
check("random control: ARI", printed(ma, r"1\. RANDOM .*?ARI=([\d.]+)"), grab(REPORT, r"segment count scores BF1@5s [\d.]+ and ARI ([\d.]+)"))
check("discrimination", disc, grab(REPORT, r"discriminates by\s+\*\*\+([\d.]+)\*\*"))
check("labels shuffled: V", shuf, grab(REPORT, r"collapses V-measure to\s+([\d.]+)"))
check("best match covers >=80%", printed(ma, r"covers >=80% of the execution: ([\d.]+)%"),
      grab(REPORT, r"execution \*\*([\d.]+)%\*\* of the time"))
check("median coverage", printed(ma, r"median coverage ([\d.]+)%"), grab(REPORT, r"median coverage\s+\*\*([\d.]+)%\*\*"))
check("random: >=80% covered", printed(ma, r"random control: >=80% covered ([\d.]+)%"),
      grab(REPORT, r"against ([\d.]+)% and [\d.]+% for random"))
check("random: median coverage", rnd_med, grab(REPORT, r"against [\d.]+% and ([\d.]+)% for random"))
check("exactly one material overlap", printed(ma, r"MATERIAL overlap >=10%.*?\(([\d.]+)%\)"),
      grab(REPORT, r"\*\*The figure is now ([\d.]+)%\*\*"))
check("random control, rounded", f"{float(rnd_med):.0f}" if rnd_med[0].isdigit() else rnd_med,
      grab(REPORT, r"against a random control of ([\d.]+)%"))
check("JA: random control", rnd, grab(JA, r"ランダム分割は([\d.]+)"))
check("JA: discrimination", disc, grab(JA, r"差は\*\*\+([\d.]+)\*\*"))
check("JA: labels shuffled", shuf, grab(JA, r"V値は([\d.]+)に低下"))

oa = audit("overfit_audit.py")
mean = printed(oa, r"BF1@5s across held-out machines: mean=([\d.]+)")
sd = printed(oa, r"BF1@5s across held-out machines: mean=[\d.]+ sd=([\d.]+)")
worst = printed(oa, r"BF1@5s across held-out machines: .*?min=([\d.]+)")
held = sorted(float(x) for x in re.findall(r"hold out .*?BF1@5s=([\d.]+)", oa))
others = f"{held[1]:.2f}–{held[-1]:.2f}" if len(held) > 1 else "NOT PRINTED"
check("strict protocol: dev", printed(oa, r"dev\s+BF1@5s=([\d.]+)"), grab(REPORT, r"Held out on the final pipeline: dev ([\d.]+)"))
check("strict protocol: test", printed(oa, r"test \(honest\)\s+BF1@5s=([\d.]+)"), grab(REPORT, r"\*\*test ([\d.]+)\*\*"))
check("leave-one-machine-out: mean", mean, grab(REPORT, r"\*\*BF1@5s ([\d.]+), sd [\d.]+\*\* across"))
check("leave-one-machine-out: sd", sd, grab(REPORT, r"\*\*BF1@5s [\d.]+, sd ([\d.]+)\*\* across"))
check("worst held-out machine", worst, grab(REPORT, r"One held-out machine scores \*\*([\d.]+)\*\*"))
check("the other held-out machines", others, grab(REPORT, r"One held-out machine scores \*\*[\d.]+\*\* against ([\d.]+–[\d.]+)"))
check("R1: worst machine", worst, grab(REPORT, r"scored BF1@5s \*\*([\d.]+)\*\* vs"))
check("R1: the other machines", others, grab(REPORT, r"scored BF1@5s \*\*[\d.]+\*\* vs ([\d.]+–[\d.]+)"))
check("JA: leave-one-machine-out mean", mean, grab(JA, r"交差検証では \*\*([\d.]+)（"))
check("JA: leave-one-machine-out sd", sd, grab(JA, r"標準偏差([\d.]+)）"))
check("JA: worst machine", worst, grab(JA, r"端末では \*\*([\d.]+)\*\* に低下"))
check("JA risk table: worst machine", worst, grab(JA, r"L3イベントが0件、精度([\d.]+)"))

# ---- where the residual Step 1 error comes from (section 1) -------------------
print("\nresidual error, by what an execution contains", flush=True)
es = audit("error_sources.py")
check("misses: share of executions", printed(es, r"not mapping to exactly one segment: \d+ \(([\d.]+)%\)"),
      grab(REPORT, r"The residual limit is the ([\d.]+)% of executions"))
# Anchored to line start: the class name is also a substring of "NO confirm press,
# NO row click", and an unanchored search read that row's 258 as this row's 1.
only_open_missing = printed(es, r"(?m)^\s*confirm press, NO row click\s+(\d+)")
check("misses: executions lacking only the opening click",
      words.get(int(only_open_missing), only_open_missing).lower() if only_open_missing.isdigit() else only_open_missing,
      grab(REPORT, r"that describes (\w+) execution in"))
check("misses: share among units with both clicks", printed(es, r"(?m)^\s*confirm press, row click\s+\d+\s+[\d.]+%\s+([\d.]+)%"),
      grab(REPORT, r"units with both clicks \(([\d.]+)% of the misses\)"))
check("units with neither click", printed(es, r"NO confirm press, NO row click\s+(\d+)"),
      grab(REPORT, r"and the (\d+) units with neither"))
check("units with neither click: mapped to one segment", printed(es, r"NO confirm press, NO row click\s+\d+\s+([\d.]+)%"),
      grab(REPORT, r"single segment only ([\d.]+)% of the time"))

# ---- the case identifier - the report's first headline finding ---------------
print("\ncase identity, from the case-ID audits", flush=True)
disc_out = audit("caseid_discovery.py")
tune_out = audit("caseid_tune.py")
visible = printed(disc_out, r"UNION\s+\d+\s+([\d.]+)%")
check("case IDs visible in screen text", visible, grab(REPORT, r"recoverable from the screen\.\*\* ([\d.]+)% of ground-truth"))
check("JA: case IDs visible in screen text", visible, grab(JA, r"案件IDの([\d.]+)%が画面テキスト"))
check("dominant-ID anchor precision", printed(tune_out, r"dominant ID, count >= 3\s+n=\s*\d+\s+precision=\s*([\d.]+)%"),
      grab(REPORT, r"show each once\. ([\d.]+)% precision"))

# ---- Step 2 tables, against the analysis regenerated from the pipeline -------
import contextlib
import io
import tempfile
import make_step2_report
from rank import PROCESS_NAME

print("\nStep 2 tables, against a fresh regeneration of step2_analysis.md", flush=True)
regen_root = Path(tempfile.mkdtemp())
(regen_root / "report").mkdir()
make_step2_report.ROOT = regen_root            # write the regeneration there, not into the repo
with contextlib.redirect_stdout(io.StringIO()):
    make_step2_report.main()
fresh_step2 = (regen_root / "report" / "step2_analysis.md").read_text(encoding="utf-8")
check("step2_analysis.md matches a fresh regeneration", "yes" if fresh_step2 == STEP2 else "no", "yes")


def table_rows(doc, names, width):
    """First table row per name, cells stripped of bold, truncated to width."""
    out = {}
    for line in doc.splitlines():
        cells = [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] in names and cells[0] not in out:
            out[cells[0]] = " | ".join(cells[:width])
    return out


def section_of(doc, heading):
    """The text under one heading, up to the next. Empty if the heading is gone.

    Tables are read within their own section. Reading the first matching row
    anywhere broke as soon as a second table - the handling comparison in
    section 2 - began its rows with the same process names.
    """
    return doc.split(heading, 1)[1].split("\n#", 1)[0] if heading in doc else ""


processes = {v[0] for v in PROCESS_NAME.values()}     # label -> (process name, document)
screen_names = {"payroll-items", "leave-applications", "onboarding", "social-insurance", "resident-tax"}
for names, width, heading in ((processes, 7, "### Ranking, and why it is ranked this way"),
                              (screen_names, 6, "### The result that set the scope")):
    written = table_rows(section_of(REPORT, heading), names, width)
    actual = table_rows(fresh_step2, names, width)
    # A loop over zero rows would pass silently - the failure this script exists to prevent.
    check(f"Step 2 {'process' if width == 7 else 'screen'} table: rows found in the report",
          "some" if written else "none", "some")
    for name in sorted(written):
        check(f"Step 2 table: {name}", actual.get(name, "NOT GENERATED"), written[name])

# The prose around those tables, which this script used to take on trust. The
# report said the top screen had the "second-lowest" judgment load; it was third
# under the old unweighted mean and lowest under the run-weighted one.
from analyze import enrich, load_segments
from rank import build as rank_build

p_rank = rank_build()
p_rank = p_rank[p_rank.n >= 5]
gs = make_step2_report.screen_table(p_rank)
top_screen = gs.index[0]
j_word, j_near = make_step2_report.judgment_standing(gs)
j_level = sorted(int(f"{gs.judgment[s]:.0f}") for s in [top_screen] + j_near)
span = lambda v: f"{v[0]}%" if v[0] == v[-1] else f"{v[0]}–{v[-1]}%"
check("top screen: share, rounded", f"{gs.share[top_screen]:.0f}%", grab(REPORT, r"One pattern, (\d+%) of all work"))
check("top screen: judgment rank", j_word, grab(REPORT, r"of all work, and the ([\w-]+) judgment load"))
check("top screen: screens compared", make_step2_report.WORDS.get(len(gs), len(gs)),
      grab(REPORT, r"judgment load of the (\w+) screens"))
check("top screen: screens level with it", " and ".join(j_near) or "none",
      grab(REPORT, r"level with ([a-z-]+(?: and [a-z-]+)*) at"))
check("top screen: judgment span", span(j_level),
      grab(REPORT, r"level with [a-z-]+(?: and [a-z-]+)* at (\d+(?:–\d+)?%)"))

# Headcount: the shared-login reading. The report said all three names appear in
# every session (one appears in 13 of 15) at 97-100% consistency (it is 100%).
lg = make_step2_report.logins(b_idx)
n_machines = b_idx.machine.nunique()
consistency = span(sorted({int(f"{c:.0f}") for *_, c in lg}))
everywhere = (make_step2_report.WORDS[n_machines]
              if lg and all(m == n_machines for _, m, _, _ in lg) else "not all")
check("logins: operator names on screen", len(lg), grab(REPORT, r"but only (\d+) operator names on screen"))
check("logins: each name on every machine", everywhere, grab(REPORT, r"each appears on all (\w+) machines"))
check("logins: name-to-system consistency", consistency,
      grab(REPORT, r"one portal system at (\d+(?:–\d+)?%) consistency"))
check("R4: operators sharing each login", make_step2_report.WORDS[n_machines],
      grab(REPORT, r"shared by all (\w+) operators"))
check("R4: name-to-system consistency", consistency,
      grab(REPORT, r"\((\d+(?:–\d+)?%) name-to-system consistency\)"))

# Process names rest on the document their segments consult. rank.py once typed
# the purities in, and they had drifted by up to 27 points.
docs_b, _ = make_step2_report.doc_evidence(enrich(load_segments(), b_idx), b_idx)
dominant = {lab: (top, k) for lab, top, k, _ in docs_b}
wrong = [lab for lab in sorted({s["label"] for s in seg})
         if PROCESS_NAME.get(lab, (None, None))[1]
         != (dominant[lab][0] if dominant.get(lab, (None, 0))[1] >= 5 else None)]
check("process names cite the document the data shows", ", ".join(wrong) or "none", "none")
report_docs = re.findall(r"^\| `([a-z]+__[a-z-]+)` \| ([a-z_]+) \|", REPORT, re.M)
check("report's document table: rows found", "some" if report_docs else "none", "some")
for lab, doc in report_docs:
    check(f"document consulted: {lab}", dominant.get(lab, ("NO EVIDENCE",))[0], doc)

# ---- different handling within one process (section 2; section 8's limit) ----
print("\nhandling within a process - re-running handling_variants.py", flush=True)
hv = audit("handling_variants.py")
m = re.search(r"tied to the worklist row they processed: (\d+) of (\d+) \(([\d.]+)%\)", hv)
tied_n, seg_n, tied_pct = m.groups() if m else ("NOT PRINTED",) * 3
check("handling: segments tied to a row", tied_n, grab(REPORT, r"\*\*(\d+) of the \d+ segments \([\d.]+%\)\*\*"))
check("handling: segments", seg_n, grab(REPORT, r"\*\*\d+ of the (\d+) segments \([\d.]+%\)\*\*"))
check("handling: share tied", tied_pct, grab(REPORT, r"\*\*\d+ of the \d+ segments \(([\d.]+)%\)\*\*"))
classes = {(lab, c): (int(k), med, keys, f"{float(doc):.0f}%") for lab, c, k, med, keys, doc in re.findall(
    r"^\s+(\S+__\S+)\s+(deterministic|review)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)%", hv, re.M)}
comps = [(lab, meas.strip(), float(d), float(p)) for lab, meas, d, p in re.findall(
    r"^\s+(\S+__\S+)\s+review - deterministic\s+(.+?)\s+([+-][\d.]+)\s+p=([\d.]+)", hv, re.M)]
compared = sorted({c[0] for c in comps})
heading = "### Different handling within one process"
check("handling: section present", "yes" if heading in REPORT else "no", "yes")
section = REPORT.split(heading, 1)[-1].split("\n#", 1)[0]
names = {PROCESS_NAME.get(lab, (lab,))[0]: lab for lab in compared}
written = table_rows(section, set(names), 6)
check("handling table: rows", len(compared), len(written))
for name, lab in sorted(names.items()):
    d_, r_ = classes.get((lab, "deterministic")), classes.get((lab, "review"))
    expect = (" | ".join([name, str(d_[0]), str(r_[0]), f"{d_[1]} → {r_[1]} s",
                          f"{d_[2]} → {r_[2]}", f"{d_[3]} → {r_[3]}"]) if d_ and r_ else "NOT PRINTED")
    check(f"handling table: {name}", expect, written.get(name, "MISSING"))
lowest = min(comps, key=lambda c: c[3]) if comps else None
surv = printed(hv, r"differences surviving the correction: (\d+) of")
flagged = [classes[(lab, "review")][0] for lab in compared if (lab, "review") in classes]
runs_span = f"{min(flagged)}–{max(flagged)}" if flagged else "NOT PRINTED"
check("handling: comparisons", printed(hv, r"comparisons: (\d+)"), grab(REPORT, r"correction for the (\d+) comparisons made"))
check("handling: differences surviving", "No" if surv == "0" else surv, grab(REPORT, r"\*\*(\w+) difference survives a correction"))
check("handling: smallest p", f"{lowest[3]:.2f}" if lowest else "NONE", grab(REPORT, r"the smallest p is ([\d.]+),"))
check("handling: smallest p, process", PROCESS_NAME.get(lowest[0], (lowest[0],))[0] if lowest else "NONE",
      grab(REPORT, r"the smallest p is [\d.]+, for flagged (\w+) rows"))
check("handling: smallest p is on duration", "yes" if lowest and lowest[1].startswith("median duration") else "no", "yes")
check("handling: smallest p, difference", f"{lowest[2]:.1f}" if lowest else "NONE", grab(REPORT, r"rows taking ([\d.]+) s longer"))
check("handling: flagged runs per process", runs_span, grab(REPORT, r"With (\d+–\d+) flagged runs per"))
check("limitation: segments tied", tied_n, grab(REPORT, r"(\d+) of the \d+ segments tie to their worklist row"))
check("limitation: flagged runs per process", runs_span, grab(REPORT, r"has only (\d+–\d+) flagged runs"))
check("JA: handling, segments", seg_n, grab(JA, r"(\d+)件中\*\*\d+件（"))
check("JA: handling, segments tied", tied_n, grab(JA, r"\d+件中\*\*(\d+)件（"))
check("JA: handling, share tied", tied_pct, grab(JA, r"件中\*\*\d+件（([\d.]+)%）\*\*"))
check("JA: handling, comparisons", printed(hv, r"comparisons: (\d+)"), grab(JA, r"\*\*(\d+)の比較のいずれも"))

# ---- tool/README.md, which carried its own copy of the Step 3 figures ----------
TOOL = (ROOT / "tool" / "README.md").read_text(encoding="utf-8")
print("\ntool/README.md, and the regulation and schema counts", flush=True)
check("tool README: rows", f"{n:,}", grab(TOOL, r"Measured over all \*\*([\d,]+) worklist rows"))
check("tool README: screens", screens, grab(TOOL, r"worklist rows across (\d+) screens\*\*"))
check("tool README: screens the portal runs", screens, grab(TOOL, r"The portal runs \*\*(\d+) worklist screens\*\*"))
for label, k in (("routine, templated note", modes["automated"]),
                 ("flagged rows routed by regulation threshold", modes["automated_by_rule"]),
                 ("left for a human", left)):
    check(f"tool README: {label}", k, grab(TOOL, rf"\| {label} \| (\d+) \|"))
    check(f"tool README: {label}, share", share_of(k), grab(TOOL, rf"\| {label} \| \d+ \| (\d+%) \|"))
check("tool README: fully automated", auto, grab(TOOL, r"\| \*\*fully automated\*\* \| \*\*(\d+)\*\*"))
check("tool README: automation rate", share_of(auto),
      grab(TOOL, r"\| \*\*fully automated\*\* \| \*\*\d+\*\* \| \*\*(\d+%)\*\*"))
check("tool README: failed", modes["failed"], grab(TOOL, r"\| failed \| \*\*(\d+)\*\*"))
check("tool README: median ms per row", f"{np.median(ms):.0f}", grab(TOOL, r"Median (\d+) ms per row"))
check("tool README: p95 ms per row", f"{ms[math.ceil(0.95 * n) - 1]:.0f}", grab(TOOL, r"ms per row, p95 (\d+) ms"))
check("tool README: rows left for a person", left, grab(TOOL, r"The (\d+) rows left for a person"))
check("tool README: upper bound", share_of(auto), grab(TOOL, r"Treat the (\d+%) as an upper bound"))
fixture = json.loads((ROOT / "tool" / "mock_portal" / "fixture.json").read_text(encoding="utf-8"))
per_prefix = collections.Counter(v["prefix"] for v in fixture.values())
check("schema archetypes", len(per_prefix), grab(REPORT, r"rows and (\d+) distinct schema archetypes"))
check("tool README: schema archetypes", len(per_prefix), grab(TOOL, r"built from \*\*(\d+) schema archetypes\*\*"))
for pfx, k in sorted(per_prefix.items()):
    check(f"tool README: screens of archetype {pfx}", k, grab(TOOL, rf"\| `{pfx}` \| [^|]+ \| (\d+) \|"))
sys.path.insert(0, str(ROOT / "tool"))
import regulations
corpus = regulations.corpus()
with_rules = sum(1 for t in corpus.values() if regulations.extract_rules(t))
no_rules = f"{len(corpus) - with_rules} of {len(corpus)}"
check("tool README: regulations with thresholds", f"{with_rules} of {len(corpus)}",
      grab(TOOL, r"\*\*(\d+ of \d+) regulation documents contain"))
check("deferred: regulations without thresholds", no_rules,
      grab(REPORT, r"deferred:\*\* the (\d+ of \d+) regulation documents"))
check("risks: regulations without thresholds", no_rules, grab(REPORT, r"The other (\d+ of \d+) regulation documents"))

# ---- dataset B's held-out evidence (section 8) --------------------------------
print("\ndataset B held-out evidence", flush=True)
lvb = audit("label_vs_breadcrumb.py")
two = re.search(r"within 2 s of segment end\s+pairs=(\d+)\s+system agreement=([\d.]+)%\s+V=([\d.]+)\s+chance V=([\d.]+)", lvb)
two = two.groups() if two else ("NOT PRINTED",) * 4
check("breadcrumb within 2 s: segments", two[0], grab(REPORT, r"within 2 s of the segment's end, on (\d+) segments"))
check("breadcrumb within 2 s: system agreement", two[1], grab(REPORT, r"\*\*V = [\d.]+\*\* \(([\d.]+)% on the system\)"))
check("breadcrumb within 2 s: V", two[2], grab(REPORT, r"at \*\*V = ([\d.]+)\*\*"))
check("breadcrumb within 2 s: chance V", two[3], grab(REPORT, r"against ([\d.]+) for shuffled labels"))
check("breadcrumb anywhere in the segment: V",
      printed(lvb, r"within the whole segment\s+pairs=\d+\s+system agreement=[\d.]+%\s+V=([\d.]+)"),
      grab(REPORT, r"anywhere in the segment it falls to ([\d.]+)"))
check("modal breadcrumb per segment: V", printed(lvb, r"modal breadcrumb per segment: pairs=\d+\s+V=([\d.]+)"),
      grab(REPORT, r"most often in force to ([\d.]+)"))

# run_dataset_b.py rewrites the graded file. It must come out byte-identical;
# if it ever does not, the original is put back and the check fails loudly.
deliverable = ROOT / "out" / "segments.jsonl"
before = deliverable.read_bytes()
rb = subprocess.run([sys.executable, "run_dataset_b.py"], cwd=ROOT / "src", capture_output=True,
                    text=True, encoding="utf-8", errors="replace", env=ENV)
if deliverable.read_bytes() != before:
    deliverable.write_bytes(before)
    sys.exit("run_dataset_b.py produced a different segments.jsonl - original restored. "
             "The pipeline is not deterministic; nothing below can be trusted.")
if rb.returncode:
    sys.exit(f"run_dataset_b.py failed:\n{rb.stdout[-1500:]}{rb.stderr[-1500:]}")
rb = rb.stdout
check("memos", printed(rb, r"held-out check - (\d+) completion memos"), grab(REPORT, r"All (\d+) memos"))
check("memos: median relative position", printed(rb, r"relative position: median=([\d.]+)"),
      grab(REPORT, r"median relative position ([\d.]+) —"))
check("segments' share of session time", printed(rb, r"coverage\s+([\d.]+)%"),
      grab(REPORT, r"segments now cover ([\d.]+)% of session time"))
check("random instants: inside a segment", printed(rb, r"random instants: inside ([\d.]+)%"),
      grab(REPORT, r"random instants give ([\d.]+)%"))
check("random instants: median position", printed(rb, r"random instants: inside [\d.]+%\s+median=([\d.]+)"),
      grab(REPORT, r"random instants give [\d.]+% and ([\d.]+)"))

# ---- ablation and sensitivity (section 7) -------------------------------------
print("\nablation and sensitivity - re-running ablation.py", flush=True)
ab = audit("ablation.py")
for name in ("without case anchors entirely", "ends only, no opening click",
             "labels from case prefix", "one label for everything"):
    m = re.search(rf"{re.escape(name)}\s+BF1@2s=([\d.]+)\s+BF1@5s=([\d.]+)\s+V=([\d.]+)\s+ARI=(-?[\d.]+)", ab)
    got = m.groups() if m else ("NOT PRINTED",) * 4
    cell = rf"\| {name} \| \**([\d.]+)\**"     # not re.escape: it escapes spaces, which grab() rewrites
    check(f"ablation: {name}: BF1@2s", got[0], grab(REPORT, cell))
    check(f"ablation: {name}: V", got[2], grab(REPORT, cell[:-len(r"\**([\d.]+)\**")] + r"\**[\d.]+\** \| ([\d.]+) \|"))
    check(f"ablation: {name}: ARI", got[3],
          grab(REPORT, cell[:-len(r"\**([\d.]+)\**")] + r"\**[\d.]+\** \| [\d.]+ \| ([−\-\d.]+) \|").replace("−", "-"))
    if name == "without case anchors entirely":
        check("ablation prose: without anchors at 5 s", got[1], grab(REPORT, r"marginally worse at 5 s \(([\d.]+) against"))
        check("ablation prose: ARI without anchors", got[3], grab(REPORT, r"shows in ARI \([\d.]+ vs ([\d.]+)\)"))
check("ablation prose: shipped ARI", f3(r.ari), grab(REPORT, r"shows in ARI \(([\d.]+) vs"))
check("segments recovered by the anchor fallback", printed(ab, r"anchor-driven fallback: (\d+) of"),
      grab(REPORT, r"recovers the (\d+) segments no confirm press brackets"))
sweep = {k: [float(x) for x in re.findall(r"\d+: ([\d.]+)", v)]
         for k, v in re.findall(r"^\s*(expand_gap_s|max_unit_s|min_unit_s|min_repeat)\s+(.*)$", ab, re.M)}
if len(sweep) == 4:
    flat = sorted({f"{x:.3f}" for x in sweep["expand_gap_s"] + sweep["max_unit_s"]})
    check("sensitivity: expand_gap_s and max_unit_s", ",".join(flat), grab(REPORT, r"leave BF1@2s unchanged at ([\d.]+)"))
    check("sensitivity: min_unit_s, largest move", f"{max(abs(x - float(b2)) for x in sweep['min_unit_s']):.3f}",
          grab(REPORT, r"moves it by at most ([\d.]+)"))
    check("sensitivity: case-anchor threshold span", f"{min(sweep['min_repeat']):.3f}–{max(sweep['min_repeat']):.3f}",
          grab(REPORT, r"from 2 to 4 spans ([\d.]+–[\d.]+)"))
else:
    check("sensitivity sweep", "NOT PRINTED", "printed")

# ---- the README, which a reviewer reads first ---------------------------------
README = (ROOT / "README.md").read_text(encoding="utf-8")
n_tests = len(re.findall(r"^def test_", (ROOT / "tests" / "test_invariants.py").read_text(encoding="utf-8"), re.M))
print("\nREADME")
check("README: BF1@2s", b2, grab(README, ours("boundary F1 @2s")))
check("README: BF1@5s", b5, grab(README, ours("boundary F1 @5s")))
check("README: WindowDiff", f3(r.windowdiff), grab(README, ours(r"WindowDiff \*\(lower better\)\*")))
check("README: V-measure", f3(r.v_measure), grab(README, ours(r"V-measure \*\(label consistency\)\*")))
check("README: segments", f"{r.n_pred:,}", grab(README, ours("segments produced")))
check("README: baseline BF1@2s", f3(g3.bf1[2.0][2]), grab(README, theirs("boundary F1 @2s")))
check("README: baseline BF1@5s", f3(g3.bf1[5.0][2]), grab(README, theirs("boundary F1 @5s")))
check("README: baseline WindowDiff", f3(g3.windowdiff), grab(README, theirs(r"WindowDiff \*\(lower better\)\*")))
check("README: baseline V", f3(sw.v_measure), grab(README, theirs(r"V-measure \*\(label consistency\)\*")))
check("README: baseline segments", f"{g3.n_pred:,}", grab(README, theirs("segments produced")))
check("README: held-out mean", mean, grab(README, r"unseen operators: \*\*([\d.]+) ±"))
check("README: held-out sd", sd, grab(README, r"unseen operators: \*\*[\d.]+ ± ([\d.]+)\*\*"))
check("README: random control", rnd, grab(README, r"segment count scores ([\d.]+), so"))
check("README: discrimination", disc, grab(README, r"discriminates by \+([\d.]+)"))
check("README: executions", len(seg), grab(README, r"analyse\.\*\* (\d+) executions"))
check("README: minutes", minutes, grab(README, r"analyse\.\*\* \d+ executions, (\d+) minutes"))
check("README: screens", screens, grab(README, r"\*\*(\d+) portal worklist screens\*\*"))
check("README: rows", f"{n:,}", grab(README, r"portal worklist screens\*\*: ([\d,]+) rows"))
check("README: automation rate", share_of(auto), grab(README, r"rows, \*\*(\d+%) fully automated"))
check("README: median ms per row", f"{np.median(ms):.0f}", grab(README, r"(\d+) ms per row"))
check("README: deliverable segments", len(seg), grab(README, r"Step 1 deliverable\*\* — (\d+) segments"))
check("README: deliverable sessions", n_sess, grab(README, r"Step 1 deliverable\*\* — \d+ segments, (\d+) sessions"))
check("README: deliverable labels", len({s["label"] for s in seg}),
      grab(README, r"Step 1 deliverable\*\* — \d+ segments, \d+ sessions, (\d+) labels"))
check("README: invariant tests", n_tests, grab(README, r"# (\d+) tests;"))

# ---- the history the report describes ----------------------------------------
days = subprocess.run(["git", "log", "--format=%ad", "--date=format:%d"], cwd=ROOT,
                      capture_output=True, text=True).stdout.split()
print("\nhistory")
check("git history: first day", str(int(days[-1])) if days else "NO GIT",
      grab(REPORT, r"git history runs from (\d+) to \d+ September"))
check("git history: last day", str(int(days[0])) if days else "NO GIT",
      grab(REPORT, r"git history runs from \d+ to (\d+) September"))

stale = [c for c in checks if c[1] != c[2]]
print(f"\n{len(checks) - len(stale)}/{len(checks)} figures match; {len(stale)} stale")
for name, a, w in stale:
    print(f"   STALE  {name}: written {w}, actual {a}")
sys.exit(1 if stale else 0)
