"""Checks that each test in test_invariants.py can actually fail.

    python tests/mutation_check.py

A passing test proves nothing until it has been seen to fail. This project
shipped a test that could not: the first version of the greedy-matching test
used a case that greedy also scored 1.0, so it passed against the very bug it
was named after. This script makes the property checkable instead of assumed.

Each mutant reintroduces a defect the project actually had, or a plausible
regression, runs the one test meant to catch it, then restores and re-runs to
confirm the restore worked. A mutant counts as killed only if its test passes
on the real code, fails on the mutant, and passes again afterwards.

Nothing is written to the repository: mutants live in memory or in a temp
directory. Mutants whose test needs the datasets report SKIP when they are
absent, rather than counting as survivors.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
_spec = importlib.util.spec_from_file_location("inv", ROOT / "tests" / "test_invariants.py")
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)
import numpy as np
import evaluate

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
TMP = Path(tempfile.mkdtemp())
PRE_FIX = "3f5ab57~1"      # the last commit before boundary matching became optimal
RESULTS, SKIPPED = [], []


def outcome(fn):
    try:
        fn()
        return "PASS"
    except inv.Skip:
        return "SKIP"
    except AssertionError:
        return "FAIL"
    except Exception as e:
        return f"ERROR:{type(e).__name__}"


def patch(obj, name, value):
    orig = getattr(obj, name)
    return (lambda: setattr(obj, name, value)), (lambda: setattr(obj, name, orig))


def check(label, test_name, mutate, restore):
    fn = getattr(inv, test_name)
    real = outcome(fn)
    if real == "SKIP":
        SKIPPED.append(label)
        print(f"  SKIP     {label:44} (its test needs the datasets)", flush=True)
        return
    mutate()
    try:
        mut = outcome(fn)
    finally:
        restore()
    after = outcome(fn)
    ok = real == "PASS" and mut == "FAIL" and after == "PASS"
    RESULTS.append(ok)
    print(f"  {'KILLED  ' if ok else 'SURVIVED'} {label:44} real={real:4} "
          f"mutant={mut:14} restored={after}", flush=True)


# --- the real pre-fix matcher, taken from git rather than reconstructed ------
old_greedy = None
_r = subprocess.run(["git", "show", f"{PRE_FIX}:src/evaluate.py"], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
_m = re.search(r"^def boundary_prf\(.*?(?=^def )", _r.stdout, re.S | re.M) if _r.returncode == 0 else None
if _m:
    _ns = {"np": np}
    exec(_m.group(0), _ns)
    old_greedy = _ns["boundary_prf"]
    assert "Greedy" in (old_greedy.__doc__ or ""), "extracted the wrong function from git"
    print("pre-fix greedy vs current optimal, tol=2:")
    for gold, pred, note in (([10, 12], [11, 14], "the test's ORIGINAL case"),
                             ([10, 11], [11, 13], "case (a)"),
                             ([10, 12], [8, 11], "case (b)")):
        gf = old_greedy(np.array(gold), np.array(pred), 2)[2]
        of = evaluate.boundary_prf(np.array(gold), np.array(pred), 2)[2]
        print(f"  gold={gold} pred={pred}  greedy F1={gf:.2f}  optimal F1={of:.2f}   {note}")
print("\nmutants:", flush=True)

# 1. matcher reverted to the real pre-fix greedy
if old_greedy is not None:
    check("matcher reverted to pre-fix greedy (git)", "test_boundary_matching_is_optimal_not_greedy",
          *patch(evaluate, "boundary_prf", old_greedy))
else:
    SKIPPED.append("pre-fix greedy")
    print(f"  SKIP     {'matcher reverted to pre-fix greedy (git)':44} (git history for {PRE_FIX} unavailable)")

# 2. boundaries derived from label changes, as before that fix
label_change = lambda segs, t0, t1, bin_s=evaluate.BIN_S: \
    evaluate.boundary_idx(evaluate.to_timeline(segs, t0, t1, bin_s))
check("boundaries taken from label changes", "test_boundaries_include_same_label_neighbours",
      *patch(evaluate, "segment_boundaries", label_change))


# 3. a broken metric must break the self-consistency check
def bad_f1(g, p, tol_bins, _real=evaluate.boundary_prf):
    pr, rc, _ = _real(g, p, tol_bins)
    return pr, rc, (pr * rc / (pr + rc) if pr + rc else 0.0)


check("F1 formula broken: PR/(P+R)", "test_harness_scores_ground_truth_against_itself_as_perfect",
      *patch(evaluate, "boundary_prf", bad_f1))

# 4. build_index's missing-data guard removed, in a private copy of src/
mut_root = TMP / "mut_root"
shutil.copytree(ROOT / "src", mut_root / "src", ignore=shutil.ignore_patterns("__pycache__"))
bi = mut_root / "src" / "build_index.py"
s = bi.read_text(encoding="utf-8")
assert "    if not rows:\n" in s, "guard not found - the mutant would be a no-op"
bi.write_text(s.replace("    if not rows:\n", "    if False:\n", 1), encoding="utf-8")
check("build_index missing-data guard removed", "test_build_index_explains_missing_data_instead_of_crashing",
      *patch(inv, "ROOT", mut_root))

# 5. deliverable mutants, each on a private copy of segments.jsonl
ROWS = inv._rows()
FMT = "%Y-%m-%dT%H:%M:%SZ"
_n = [0]


def with_rows(mutator):
    rs = json.loads(json.dumps(ROWS))
    mutator(rs)
    _n[0] += 1
    f = TMP / f"seg_{_n[0]}.jsonl"
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs), encoding="utf-8")
    return patch(inv, "SEGMENTS", f)


def extra_field(rs):
    rs[0]["confidence"] = 0.9


def offset_ts(rs):
    rs[0]["start"] = rs[0]["start"].replace("Z", "+00:00")


def drop_session(rs):
    sid = rs[0]["session_id"]
    rs[:] = [r for r in rs if r["session_id"] != sid]


def full_paths(rs):
    for r in rs:
        r["session_id"] = "data/dataset_b/" + r["session_id"]


def typo_ids(rs):
    for r in rs:
        r["session_id"] = r["session_id"].replace("ses_", "ses-")


def overlap(rs):
    rs.sort(key=lambda r: (r["session_id"], r["start"]))
    i = next(i for i in range(len(rs) - 1) if rs[i]["session_id"] == rs[i + 1]["session_id"])
    end = dt.datetime.strptime(rs[i]["end"], FMT)
    rs[i + 1]["start"] = (end - dt.timedelta(seconds=1)).strftime(FMT)


def empty(rs):
    rs[0]["end"] = rs[0]["start"]


def label_per_segment(rs):
    for i, r in enumerate(rs):
        r["label"] = f"label_{i}"


def one_label(rs):
    for r in rs:
        r["label"] = "work"


check("extra field in one line", "test_deliverable_has_exactly_the_specified_fields", *with_rows(extra_field))
check("timestamp written as +00:00, not Z", "test_deliverable_timestamps_are_iso8601_utc", *with_rows(offset_ts))
check("one session missing", "test_deliverable_covers_every_dataset_b_session", *with_rows(drop_session))
check("session_id is a path, not the dir name", "test_deliverable_session_ids_are_the_directory_names", *with_rows(full_paths))
check("session_id typo in every id", "test_deliverable_session_ids_are_the_directory_names", *with_rows(typo_ids))
check("two segments overlap by 1s", "test_deliverable_has_no_empty_or_overlapping_segments", *with_rows(overlap))
check("zero-length segment", "test_deliverable_has_no_empty_or_overlapping_segments", *with_rows(empty))
check("a unique label per segment", "test_labels_are_a_small_consistent_vocabulary", *with_rows(label_per_segment))
check("one label for everything", "test_labels_are_a_small_consistent_vocabulary", *with_rows(one_label))

# 6. approval routing: the pre-fix router, and an off-by-one at 以上
sys.path.append(str(ROOT / "tool"))
import regulations


def pre_fix_route(amount_yen, rules):
    hit = None
    for r in rules:
        if r["cmp"] in ("以上", "超") and amount_yen >= r["yen"]:
            hit = r["outcome"]
        elif r["cmp"] in ("未満", "以下") and amount_yen < r["yen"] and hit is None:
            hit = r["outcome"]
    return hit


def strict_at_least(amount_yen, rules):
    hit = None
    for r in rules:
        if r["cmp"] == "以上" and amount_yen > r["yen"]:
            hit = r["outcome"]
        elif r["cmp"] == "未満" and amount_yen < r["yen"] and hit is None:
            hit = r["outcome"]
    return hit


check("router folds 超 into 以上, 以下 into 未満", "test_strict_and_inclusive_comparators_are_distinct",
      *patch(regulations, "route", pre_fix_route))
check("以上 applied as strictly greater", "test_threshold_routing_at_the_boundaries",
      *patch(regulations, "route", strict_at_least))
check("a regulation routes rows it never names (pre-fix)", "test_a_regulation_routes_only_rows_it_names",
      *patch(regulations, "governs", lambda text, subject: True))

# 7. the model stays out unless asked for, and the guard refuses identifiers
import llm
import run as tool_run
check("model on whenever a key exists (pre-fix default)", "test_the_tool_calls_no_model_unless_asked",
      *patch(tool_run, "model_requested", lambda args: not args.no_llm))
check("guard checks JSON markers only (pre-fix)", "test_llm_guard_refuses_identifiers_and_raw_records",
      *patch(llm, "_RAW_ID_PATTERNS", ()))

# 8. the runner itself: a crashing test must be reported, counted, and not stop the run
code = ("import runpy; runpy.run_path(r'%s', run_name='__main__', "
        "init_globals={'test_aa_injected_crash': lambda: int('not a number')})"
        % (ROOT / "tests" / "test_invariants.py"))
r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", env=ENV)
out = r.stdout + r.stderr
reported = "ERROR test_aa_injected_crash" in out
kept_going = "PASS  test_deliverable_has_exactly_the_specified_fields" in out
ok = r.returncode == 1 and reported and kept_going
RESULTS.append(ok)
print(f"  {'KILLED  ' if ok else 'SURVIVED'} {'runner: a test that crashes':44} exit={r.returncode} "
      f"reported={reported} later tests still ran={kept_going}")
if not ok:
    print("    " + "\n    ".join(out.strip().splitlines()[-8:]))

# 9. a fresh clone: the mock portal imported at module level again, fixture absent
def private_copy(name):
    root = TMP / name
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tool", root / "tool",
                    ignore=shutil.ignore_patterns("__pycache__", "fixture.json"))
    return root


mut_clone = private_copy("mut_clone")
rp = mut_clone / "tool" / "run.py"
s = rp.read_text(encoding="utf-8")
anchor = "from engine import WorklistEngine, DefinitionDrift"
assert s.count(anchor) == 1, "run.py's import line not found - the mutant would be a no-op"
rp.write_text(s.replace(anchor, "import server\n" + anchor, 1), encoding="utf-8")
check("mock portal imported at module level (pre-fix)", "test_the_tool_imports_without_its_generated_fixture",
      *patch(inv, "ROOT", mut_clone))

# 10. UTF-8 output switched off, as before the fix
mut_enc = private_copy("mut_enc")
cm = mut_enc / "src" / "common.py"
s = cm.read_text(encoding="utf-8")
assert s.count("\n_utf8_output()\n") == 1, "the UTF-8 call was not found - the mutant would be a no-op"
cm.write_text(s.replace("\n_utf8_output()\n", "\n", 1), encoding="utf-8")
check("UTF-8 output switched off (pre-fix)", "test_japanese_output_survives_a_legacy_windows_code_page",
      *patch(inv, "ROOT", mut_enc))

shutil.rmtree(TMP, ignore_errors=True)
killed = sum(RESULTS)
print(f"\n{killed}/{len(RESULTS)} mutants killed" + (f", {len(SKIPPED)} skipped" if SKIPPED else ""))
sys.exit(0 if killed == len(RESULTS) else 1)
