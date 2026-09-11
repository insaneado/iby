"""Invariants a reviewer can check in one command.

    python tests/test_invariants.py        # standalone, no extra dependencies
    pytest tests/                          # or with pytest, if installed

Each test asserts a claim the project makes, so the claim can be checked rather
than taken on trust. Several exist because the corresponding claim was once
false, and the audit scripts in explore/ that caught it only *printed* their
findings. A check that prints can report success while measuring nothing - this
project hit that five times. A check that asserts cannot - provided the
assertion can fail. tests/mutation_check.py breaks the behaviour each test
guards and confirms the test then fails; the first version of the
greedy-matching test below did not.

Tests that need the provided datasets skip cleanly when they are absent, so the
checks on the committed deliverable still run anywhere.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
SEGMENTS = ROOT / "out" / "segments.jsonl"
FIELDS = {"session_id", "start", "end", "label"}
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"          # the brief's example: 2026-07-01T18:32:32Z


class Skip(Exception):
    pass


def skip(msg: str):
    # PYTEST_CURRENT_TEST is set only while pytest is running a test. Testing
    # whether pytest has merely been imported would misfire if a dependency
    # pulled it in - and pytest's skip is not an Exception the runner catches.
    if "PYTEST_CURRENT_TEST" in os.environ:
        import pytest
        pytest.skip(msg)
    raise Skip(msg)


def _rows():
    return [json.loads(line) for line in
            SEGMENTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _when(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _need_data(ds: str = "dataset_a"):
    from common import DATA
    if not (DATA / ds).exists():
        skip(f"{ds} not present under {DATA}")


# ---- the graded deliverable ------------------------------------------------

def test_deliverable_has_exactly_the_specified_fields():
    """The brief specifies session_id, start, end, label - nothing more."""
    rows = _rows()
    assert rows, "segments.jsonl is empty"
    bad = [i for i, r in enumerate(rows, 1) if set(r) != FIELDS]
    assert not bad, f"{len(bad)} lines with extra or missing fields, first at line {bad[0]}"


def test_deliverable_timestamps_are_iso8601_utc():
    """ISO 8601 in UTC, in the exact form of the brief's example."""
    for i, r in enumerate(_rows(), 1):
        for k in ("start", "end"):
            try:
                dt.datetime.strptime(r[k], TS_FORMAT)
            except (ValueError, TypeError):
                raise AssertionError(f"line {i}: {k}={r[k]!r} is not of the form "
                                     "2026-07-01T18:32:32Z") from None


def test_deliverable_covers_every_dataset_b_session():
    """The brief: dataset B has 15 sessions."""
    ids = {r["session_id"] for r in _rows()}
    assert len(ids) == 15, f"{len(ids)} sessions; dataset B has 15"


def test_deliverable_session_ids_are_the_directory_names():
    """The brief: session_id is the session directory name. A count alone would
    accept fifteen full paths, or fifteen ids with a typo in each."""
    _need_data("dataset_b")
    from common import sessions
    ids = {r["session_id"] for r in _rows()}
    dirs = {p.name for p in sessions("dataset_b")}
    assert ids == dirs, (f"{len(ids - dirs)} ids name no directory; "
                         f"{len(dirs - ids)} directories have no segments")


def test_deliverable_has_no_empty_or_overlapping_segments():
    by = {}
    for r in _rows():
        by.setdefault(r["session_id"], []).append(r)
    for sid, rs in by.items():
        rs.sort(key=lambda r: _when(r["start"]))
        for r in rs:
            assert _when(r["end"]) > _when(r["start"]), f"empty segment in {sid} at {r['start']}"
        for a, b in zip(rs, rs[1:]):
            assert _when(b["start"]) >= _when(a["end"]), \
                f"overlap in {sid}: {a['end']} > {b['start']}"


def test_labels_are_a_small_consistent_vocabulary():
    """The brief scores whether the same process gets the same label. A label
    per segment would mean the labeller had degenerated into noise."""
    labels = {r["label"] for r in _rows()}
    assert 1 < len(labels) <= 20, f"{len(labels)} distinct labels"


# ---- the evaluation harness ------------------------------------------------

def test_harness_scores_ground_truth_against_itself_as_perfect():
    """If this fails, every other number in the project is unfalsifiable."""
    _need_data()
    from gold import load_gold
    from evaluate import evaluate
    g = load_gold("dataset_a")
    r = evaluate(g, {k: v[0] for k, v in g.items()})
    for t in (2.0, 5.0, 10.0):
        assert abs(r.bf1[t][2] - 1.0) < 1e-9, f"BF1@{t}s = {r.bf1[t][2]}"
    assert r.windowdiff == 0.0
    assert abs(r.v_measure - 1.0) < 1e-9


def test_boundary_matching_is_optimal_not_greedy():
    """Greedy nearest-first matching understated every score.

    Each case has to be one greedy actually gets wrong. As first written this
    test used gold=[10,12], pred=[11,14], which greedy also scores 1.0 - so it
    passed against the very bug it was named after.

    (a) Nearest-first over all pairs - the matcher this project actually had -
        takes the exact match (11,11) first. That strands gold 10, whose only
        candidate within tolerance was pred 11: F1 0.5. No distances tie, so
        tie-breaking cannot rescue it. Optimal pairs (10,11), (11,13): F1 1.0.
    (b) A matcher that walks gold in order gives gold 10 its nearest, pred 11 -
        gold 12's only candidate - and strands gold 12. Optimal pairs (10,8),
        (12,11). Covers the other greedy a rewrite is likely to reach for.
    """
    from evaluate import boundary_prf
    import numpy as np
    for gold, pred in (([10, 11], [11, 13]), ([10, 12], [8, 11])):
        _, _, f1 = boundary_prf(np.array(gold), np.array(pred), tol_bins=2)
        assert f1 == 1.0, f"gold={gold} pred={pred}: F1={f1}; optimal matching gives 1.0"


def test_boundaries_include_same_label_neighbours():
    """Deriving boundaries from label changes hid the edge between two
    consecutive executions of the same process - the case the task is about."""
    from gold import Segment
    from evaluate import segment_boundaries
    t0 = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    s = lambda a, b: Segment("s", t0 + dt.timedelta(seconds=a),
                             t0 + dt.timedelta(seconds=b), "same_process")
    bounds = segment_boundaries([s(0, 30), s(30, 60)], t0, t0 + dt.timedelta(seconds=90))
    assert 30 in bounds, "the boundary between two same-label segments was lost"


# ---- Step 3: approval routing ----------------------------------------------

REGULATION = ("第２条（承認権限）1回あたり5万円未満：部門長承認。"
              "5万円以上：役員承認。10万円以上：社長承認。")


def _regulations():
    sys.path.append(str(ROOT / "tool"))
    import regulations
    return regulations


def test_threshold_routing_at_the_boundaries():
    """The regulation text the tool routes by, at and either side of each
    threshold - exactly where an off-by-one sends a row to the wrong approver."""
    reg = _regulations()
    rules = reg.extract_rules(REGULATION)
    for amount, approver in ((49_999, "部門長承認"), (50_000, "役員承認"), (99_999, "役員承認"),
                             (100_000, "社長承認"), (107_158, "社長承認")):
        got = reg.route(amount, rules)
        assert got == approver, f"route({amount:,}) gave {got}; the regulation says {approver}"


def test_strict_and_inclusive_comparators_are_distinct():
    """以下 is 'or less' and 超 is 'more than'. They were once handled as 未満 and
    以上, which puts an amount exactly at the threshold on the wrong side. No
    captured regulation uses them yet; a revised one could."""
    reg = _regulations()
    rules = reg.extract_rules("5万円以下：部門長承認。5万円超：役員承認。")
    assert reg.route(50_000, rules) == "部門長承認", "5万円以下 must include exactly 50,000"
    assert reg.route(50_001, rules) == "役員承認", "5万円超 must start just above 50,000"
    assert reg.route(49_999, rules) == "部門長承認"


# ---- first-run behaviour ---------------------------------------------------

def test_build_index_explains_missing_data_instead_of_crashing():
    """It used to fail with "KeyError: 'ds'", which tells a new user nothing."""
    root = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(ROOT / "src", root / "src")
        empty = root / "empty"
        empty.mkdir()
        (root / "config.local.json").write_text(
            json.dumps({"data_root": str(empty)}), encoding="utf-8")
        r = subprocess.run([sys.executable, "build_index.py"], cwd=root / "src",
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                "PYTHONUTF8": "1"})
        out = r.stdout + r.stderr
        assert r.returncode != 0, "should exit non-zero with no data"
        assert "No events found" in out, "should say what is wrong"
        assert "KeyError" not in out, "should not leak the internal KeyError"
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Skip as e:
            print(f"  SKIP  {name}  ({e})")
            skipped += 1
        except AssertionError as e:
            print(f"  FAIL  {name}  {e}")
            failed += 1
        except Exception as e:
            # A test that crashes has not passed. Report it and carry on, so one
            # traceback cannot hide every test that would have run after it.
            print(f"  ERROR {name}  {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(1 if failed else 0)
