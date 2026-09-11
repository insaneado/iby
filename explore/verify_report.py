"""Reconcile every load-bearing figure in the report with a fresh run.

Each check re-derives a figure from the current pipeline and compares it with
the figure *as written in the document* - parsed out of REPORT.md and
SUMMARY_JA.md, never typed into this script.

An earlier version kept the claimed values as literals here. It compared the
pipeline with its own copy of the numbers, reported 21/21, and could not see
that the report and the Japanese summary still quoted an earlier pipeline in a
dozen places. One of its 21 checks compared against a figure the report does not
contain at all. A check that cannot see the thing it checks is not a check.

Figures that come from the slower audits are taken from those audits' own
output, so each audit stays the single source of truth for its numbers. Takes a
few minutes. Exits non-zero if anything is stale.

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
