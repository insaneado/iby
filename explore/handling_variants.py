"""Step 2's third question: are there different handling patterns within one process?

The brief asks it directly. The report used to answer with a limitation - "only
72 segments could be tied to a variant", measured on an earlier revision's
output and never re-run. On the delivered segments most can be tied, so the
question gets an answer instead.

How a segment is tied to a worklist row
    A case ID observed inside the segment (caseid.anchors: repeated on screen,
    alone in a short capture, or inside a clicked element) that names a row of
    the worklist screen the segment's label points at - same system, same
    screen. Only IDs inside the segment count: one carried forward from before
    it could belong to the previous unit of work.

Which rows are handled differently
    The Step 3 definition for each screen routes rows on one column
    (`route_on`) to a rule, and each rule has a mode: `deterministic` (done end
    to end) or `review` (flagged for judgment). A row's handling class is the
    mode its value routes to - 種別 = 調整 on the three payroll-type screens,
    新規締結 and 解除 on the contract screen. The definitions were written when
    the tool was built, before this comparison existed, so the classes cannot
    have been steered by what it shows.

    A first version counted any column with two or more routing keys as a
    variant. That took in department columns, whose keys only change the
    wording of the note, and on fin's payment screen a column that holds
    invoice references. The mode is what the definitions use to say a row is
    handled differently, so it is what is compared.

What is compared
    Per label, review rows against deterministic rows, each with at least 10
    runs: median duration, keystrokes per run, and the share of runs with a
    regulation document open. Each by a 5,000-draw permutation test (seed 0).
    A difference is reported as one only if it survives Bonferroni across every
    comparison made - a dozen tests at 0.05 would find one by chance alone.

    python explore/handling_variants.py
"""
from __future__ import annotations
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import yaml

from analyze import load_segments
from caseid import anchors
from common import load_index
from label import _route_from_placeholder
from rank import DOC_RE

DS = "dataset_b"
MIN_RUNS = 10
DRAWS = 5000
ALPHA = 0.05
CLASSES = ("deterministic", "review")
FIXTURE = ROOT / "tool" / "mock_portal" / "fixture.json"


def handling_classes() -> dict[str, tuple[str, dict]]:
    """screen key -> (the column its definition routes on, the routing), for
    screens that send some rows to review and handle the rest end to end."""
    out = {}
    for f in sorted((ROOT / "tool" / "definitions").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        routing = d.get("routing", {})
        if d.get("route_on") and {r.get("mode") for r in routing.values()} >= set(CLASSES):
            out[d["screen_key"]] = (d["route_on"], routing)
    return out


def mode_of(row: dict, col: str, routing: dict) -> str:
    """The same lookup the engine makes (engine.rule_for)."""
    rule = routing.get(str(row.get(col, "")).strip(), routing.get("default", {}))
    return rule.get("mode", "deterministic")


def tie_segments(seg, fixture, df):
    """One record per segment: its measures, and the worklist row it processed
    where one can be identified."""
    rows = {}                      # (system, route, row id) -> (screen key, row)
    for key, st in fixture.items():
        route = _route_from_placeholder(st["placeholder"])
        for r in st["rows"]:
            rows[(st["system"], route, r["ID"])] = (key, r)
    anc = {s: g for s, g in anchors(DS).groupby("session_id")}
    ev = {s: g.sort_values("ts_ms") for s, g in df.groupby("session_id")}
    out = []
    for s in seg.itertuples():
        system, route = s.label.split("__")
        a = anc.get(s.session_id)
        inside = a[(a.ts_ms >= s.start_ms) & (a.ts_ms <= s.end_ms)] if a is not None else None
        hit = None
        if inside is not None and len(inside):
            for case, _ in collections.Counter(inside.case).most_common():
                hit = rows.get((system, route, case))
                if hit:
                    break
        e = ev[s.session_id]
        e = e[(e.ts_ms >= s.start_ms) & (e.ts_ms <= s.end_ms)]
        out.append(dict(
            label=s.label, dur=s.dur, screen=hit[0] if hit else None,
            row=hit[1] if hit else None,
            keystrokes=int((e.event_type == "keystroke").sum()),
            doc=float(any(DOC_RE.match(str(t)) for t in e.title.dropna())),
        ))
    return out


def permutation_p(x, y, stat, rng):
    """Two-sided: how often a random relabelling moves the statistic as far."""
    obs = stat(y) - stat(x)
    pool = np.concatenate([x, y]).astype(float)
    hits = 0
    for _ in range(DRAWS):
        rng.shuffle(pool)
        if abs(stat(pool[len(x):]) - stat(pool[:len(x)])) >= abs(obs) - 1e-12:
            hits += 1
    return obs, (hits + 1) / (DRAWS + 1)


def main():
    if not FIXTURE.exists():
        sys.exit(f"{FIXTURE} not found: run `python tool/extract_fixture.py` first")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    df = load_index(DS)
    seg = load_segments()
    recs = tie_segments(seg, fixture, df)
    tied = [r for r in recs if r["row"] is not None]
    print(f"segments tied to the worklist row they processed: {len(tied)} of {len(recs)} "
          f"({100 * len(tied) / len(recs):.1f}%)")

    cls = handling_classes()
    print(f"screens whose definition sends some rows to review: {len(cls)}")
    for key, (col, routing) in sorted(cls.items()):
        flagged = sorted(k for k, r in routing.items() if r.get("mode") == "review")
        print(f"  {key:28} on {col}: review = {', '.join(flagged)}")

    by = collections.defaultdict(lambda: collections.defaultdict(list))
    values = collections.defaultdict(collections.Counter)
    for r in tied:
        if r["screen"] in cls:
            col, routing = cls[r["screen"]]
            m = mode_of(r["row"], col, routing)
            by[r["label"]][m].append(r)
            values[(r["label"], m)][str(r["row"].get(col, ""))] += 1

    print("\nper handling class:")
    print(f"  {'label':26} {'class':13} {'runs':>5} {'median s':>9} {'keys/run':>9} "
          f"{'doc open':>9}  values")
    pairs = []
    for lab in sorted(by):
        for m in CLASSES:
            rs = by[lab].get(m, [])
            if not rs:
                continue
            vals = ", ".join(f"{v} {k}" for v, k in values[(lab, m)].most_common())
            print(f"  {lab:26} {m:13} {len(rs):5d} {np.median([r['dur'] for r in rs]):9.1f} "
                  f"{np.mean([r['keystrokes'] for r in rs]):9.1f} "
                  f"{100 * np.mean([r['doc'] for r in rs]):8.1f}%  {vals}")
        if all(len(by[lab].get(m, [])) >= MIN_RUNS for m in CLASSES):
            pairs.append((lab, by[lab]["deterministic"], by[lab]["review"]))

    rng = np.random.default_rng(0)
    measures = (("median duration, s", "dur", np.median),
                ("keystrokes per run", "keystrokes", np.mean),
                ("regulation open, share", "doc", np.mean))
    k = len(pairs) * len(measures)
    bar = ALPHA / k if k else ALPHA
    print(f"\ncomparisons: {k} (review vs deterministic, labels with >= {MIN_RUNS} runs "
          f"of each); Bonferroni bar p < {bar:.4f}")
    survivors = []
    for lab, det, rev in pairs:
        for name, field, stat in measures:
            x = np.array([r[field] for r in det])
            y = np.array([r[field] for r in rev])
            d, p = permutation_p(x, y, stat, rng)
            if p < bar:
                survivors.append((lab, name, d))
            print(f"  {lab:26} review - deterministic  {name:24} {d:+8.2f}  p={p:.4f}"
                  f"{'  SURVIVES' if p < bar else ''}")
    print(f"differences surviving the correction: {len(survivors)} of {k}")
    for lab, name, d in survivors:
        print(f"  {lab}: {name} {d:+.2f}")


if __name__ == "__main__":
    main()
