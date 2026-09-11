"""Run the worklist automation across all three systems and report what happened.

    python tool/run.py                 # all 12 screens, mock portal, no model
    python tool/run.py --limit 10      # first 10 pending rows per screen
    python tool/run.py --llm-drafts    # also let a configured model draft review notes

No model is called unless --llm-drafts is given; a configured API key alone
changes nothing. The report's decision is that the model stays out of the
runtime path, so the default has to be the decision rather than the exception.
--llm-drafts reproduces the measured experiment (135x slower, 2 of 5 timed out).

The report is the point, not the run: it separates what was automated from what
still needs a person, because that difference is the honest measure of impact.
"""
from __future__ import annotations
import argparse
import collections
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "mock_portal"))
sys.path.insert(0, str(HERE.parent / "src"))

import common                     # noqa: E402,F401  UTF-8 output on Windows; see common.py
from engine import WorklistEngine, DefinitionDrift                  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--llm-drafts", action="store_true",
                    help="let a configured model draft notes for rows queued for review "
                         "(the measured experiment; off by default)")
    ap.add_argument("--no-llm", action="store_true", help=argparse.SUPPRESS)   # now the default
    ap.add_argument("--only", default=None, help="substring filter on screen key")
    return ap


def model_requested(args) -> bool:
    """A model runs only when asked for - never merely because a key exists."""
    return args.llm_drafts and not args.no_llm


def main():
    args = build_parser().parse_args()

    llm = None
    if model_requested(args):
        try:
            import llm as llm_mod
            if llm_mod.available():
                llm = llm_mod.LLM()
            else:
                # Said aloud: without it, asking for drafts and getting none
                # looked exactly like a run that had used the model.
                print("  (--llm-drafts given, but no GEMINI_API_KEY is configured; "
                      "review rows will use the deterministic note)")
        except Exception as e:
            print(f"  (no model available: {type(e).__name__}; "
                  f"review rows will use the deterministic note)")

    # Imported here, not at the top: the mock portal loads fixture.json, which
    # is rebuilt from dataset B and not committed. At module level it made
    # `import run` fail on a fresh clone, and with it the test that checks the
    # model stays off - on exactly the checkout a reviewer starts from.
    import server
    server.serve_all()
    time.sleep(0.5)

    t0 = time.time()
    all_out = []
    defs = sorted((HERE / "definitions").glob("*.yaml"))
    if args.only:
        defs = [d for d in defs if args.only in d.stem]
    drifted, warnings = [], []
    for path in defs:
        eng = WorklistEngine(path, llm=llm)
        try:
            out = eng.run(limit=args.limit)
        except DefinitionDrift as e:
            # Stop this screen, keep going with the rest, and make it impossible
            # to miss: a drifted definition is the one outcome that must never
            # be mistaken for a clean run with nothing to do.
            drifted.append((path.stem, str(e)))
            print(f"{path.stem:9} {eng.d['screen'][:16]:18}  DRIFT - screen stopped")
            continue
        all_out += out
        warnings += eng.warnings
        c = collections.Counter(o.mode for o in out)
        print(f"{path.stem:9} {eng.d['screen'][:16]:18} {len(out):4d}  "
              + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))

    wall = time.time() - t0
    modes = collections.Counter(o.mode for o in all_out)
    var = collections.Counter(o.variant for o in all_out if o.variant)
    fail = [o for o in all_out if o.mode == "failed"]

    n = max(len(all_out), 1)
    auto = modes["automated"] + modes["automated_by_rule"]
    print(f"\n{'-'*66}")
    print(f"rows handled            {len(all_out)}")
    print(f"  routine, templated    {modes['automated']} "
          f"({100*modes['automated']/n:.0f}%)")
    print(f"  adjustment, routed    {modes['automated_by_rule']} "
          f"({100*modes['automated_by_rule']/n:.0f}%)  by regulation threshold")
    print(f"  FULLY AUTOMATED       {auto} ({100*auto/n:.0f}%)")
    print(f"  left for a human      {modes['queued_for_review']} "
          f"({100*modes['queued_for_review']/n:.0f}%)")
    print(f"  failed                {modes['failed']}")
    print(f"screens                 {len(defs)}")
    print(f"row types               {dict(var.most_common(8))}")
    ms = sorted(o.ms for o in all_out)
    if ms:
        print(f"per-row latency         median {ms[len(ms)//2]:.0f} ms   "
              f"p95 {ms[int(len(ms)*.95)]:.0f} ms")
    print(f"wall clock              {wall:.1f} s")
    if llm is not None:
        print(f"model usage             {llm.stats.summary()}")
    print(f"screens stopped (drift) {len(drifted)}")
    for stem, msg in drifted:
        print(f"  DRIFT   {stem}: {msg}")
    for w in warnings:
        print(f"  WARNING {w}")
    for f in fail[:5]:
        print(f"  FAILED {f.system} {f.row_id}: {f.error}")

    dest = HERE.parent / "out" / "automation_run.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps([o.__dict__ for o in all_out],
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
