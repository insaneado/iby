"""A worklist automation engine, driven by a per-system definition file.

Why an engine rather than three scripts
---------------------------------------
Step 2 found that one screen pattern carries the largest share of observed work
and appears in all three portal systems; `report/step2_analysis.md` has the
figures, generated from the pipeline. (This docstring once quoted them, and
they went three revisions stale here while the report stayed current.) The
two top-ranked candidates are that screen in two of its deployments, and the
table contract is identical in all three - same seven columns, same element
ids, differing only in what fills them (`E2001` vs `BATCH-W2`, yen vs an em
dash). Three bespoke scripts would encode that shared structure three times.

Why the LLM is confined to one step
-----------------------------------
Navigation, row selection, field entry and confirmation are deterministic. They
are cheap, auditable, and cannot hallucinate a value into a financial system -
which matters, because a wrong note on an invoice approval is a real
consequence and an LLM offers no way to bound it.

Judgment appears in one place, and the portal itself marks it: rows of
種別 = 調整 (adjustment) rather than 定常 (routine), and contract actions of
新規締結 or 解除. So: **routine rows run end to end; flagged rows are routed
by a regulation threshold where one applies, and otherwise queued for a
human.** The split is the portal's own rather than an assumption, and it is also
the honest answer to "what manual work remains". (An earlier version of this
docstring said the screens with the most 調整 rows are the ones where operators
open a regulation document. The data says otherwise: the inventory screen has
the highest 調整 rate of the three and the lowest document rate.)

The engine runs unchanged with no LLM configured - `review` rows are queued with
a deterministic note instead of a drafted one. Nothing in the critical path
depends on a model being reachable.
"""
from __future__ import annotations
import dataclasses
import json
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))


class DefinitionDrift(RuntimeError):
    """The live screen no longer matches its definition.

    Raised rather than tolerated because the alternative is worse: a renamed
    control or an unfamiliar status word used to produce "0 rows, 0 failed",
    which reads exactly like a clean run with nothing to do. A definition that
    has drifted from the portal must stop the screen loudly, not report success.
    """


@dataclasses.dataclass
class Outcome:
    system: str
    row_id: str
    variant: str
    mode: str                 # automated | queued_for_review | failed
    note: str
    ms: float
    error: str | None = None


class WorklistEngine:
    def __init__(self, definition: Path, llm=None, dry_run: bool = False):
        self.d = yaml.safe_load(Path(definition).read_text(encoding="utf-8"))
        self.llm = llm
        self.dry_run = dry_run
        self.outcomes: list[Outcome] = []
        self.warnings: list[str] = []      # non-fatal drift, surfaced by run.py

    # ---- rule table, loaded once from the regulation text ------------------
    def _rules(self, doc: str) -> list[dict]:
        if not hasattr(self, "_rule_cache"):
            import regulations
            self._corpus = regulations.corpus()
            self._extract = regulations.extract_rules
            self._route = regulations.route
            self._governs = regulations.governs
            self._rule_cache = {}
        if doc not in self._rule_cache:
            self._rule_cache[doc] = self._extract(self._corpus.get(doc, ""))
        return self._rule_cache[doc]

    @staticmethod
    def _yen(text: str) -> int | None:
        import re
        m = re.search(r"([\d,]+)\s*円", str(text or ""))
        return int(m.group(1).replace(",", "")) if m else None

    def rule_for(self, row: dict) -> dict:
        """Select the routing rule for a row.

        Screens do not share a schema - the payroll worklist switches on 種別
        (定常/調整) while the contract worklist switches on 部署
        (新規締結/更新/解除) - so the column to switch on is named in the
        definition rather than assumed.
        """
        routing = self.d.get("routing", {})
        col = self.d.get("route_on")
        if col:
            v = str(row.get(col, "")).strip()
            if v in routing:
                return routing[v]
        return routing.get("default", {"mode": "deterministic",
                                       "note_template": "{ID} 確認済。"})

    # ---- the one place judgment lives -------------------------------------
    def compose_note(self, row: dict, rule: dict) -> tuple[str, str]:
        """Return (note, mode). Deterministic unless the row needs judgment."""
        template = rule.get("note_template", "")
        try:
            note = template.format(**{k: row.get(k, "") for k in row})
        except KeyError:
            note = f"{row.get('ID','')} 確認済。"
        if rule.get("mode") != "review":
            return note, "automated"

        # Before treating this as judgment, check whether the governing
        # regulation actually states a rule. Where it does - "under 50,000 yen:
        # department head; 50,000 and over: executive" - routing is arithmetic
        # and needs neither a model nor a person.
        doc = rule.get("rules_from") or rule.get("regulation", "")
        amt_col = rule.get("amount_column") or self.d.get("amount_column")
        amount = self._yen(row.get(amt_col)) if amt_col else None
        if doc and amount is not None:
            rules = self._rules(doc)
            subject = row.get(self.d.get("subject_column", "ID"), row.get("ID"))
            # The table applies only to what its regulation names: one screen
            # carries expense claims and pay changes, and an overtime adjustment
            # is not an entertainment expense because it shares the screen.
            named = self._governs(self._corpus.get(doc, ""), str(subject))
            approver = self._route(amount, rules) if rules and named else None
            if approver:
                return (f"{subject} 確認。金額 {row.get(amt_col)}。"
                        f"規程により{approver}へ回付。"), "automated_by_rule"

        # Adjustment rows: a human decides. Only when run.py was started with
        # --llm-drafts does a model draft the note - the experiment the report
        # measured and rejected for production. The row is queued either way,
        # and the prompt carries the row's type, amount and classification,
        # never its id or names.
        if self.llm is not None:
            try:
                reg = rule.get("regulation", "")
                drafted = self.llm.complete(
                    "You are drafting a one-line Japanese processing note for a "
                    "back-office worklist row that needs human review.\n"
                    f"Governing regulation: {reg}\n"
                    f"Row type: {row.get('区分')}\nAmount: {row.get('金額')}\n"
                    f"Classification: {row.get('種別')}\n"
                    "Reply with the note only, under 60 characters.",
                    temperature=0.0, max_tokens=200).strip()
                if drafted:
                    note = drafted
            except Exception as e:                      # model down, quota, refusal
                note = f"{note}  [draft unavailable: {type(e).__name__}]"
        return note, "queued_for_review"

    # ---- deterministic mechanics ------------------------------------------
    def run(self, limit: int | None = None) -> list[Outcome]:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        sel = self.d["selectors"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(self.d["url"], wait_until="domcontentloaded")
            try:
                page.wait_for_selector(sel["table"], timeout=10_000)
            except PWTimeout:
                # Surfaced as drift, not as Playwright's own timeout: run.py
                # isolates DefinitionDrift per screen, and anything else would
                # propagate and abort the remaining screens.
                raise DefinitionDrift(
                    f"{self.d['screen_key']}: table selector ({sel['table']}) "
                    f"did not appear within 10 s")

            # Preflight: every selector the loop depends on must resolve before
            # a single row is touched. Without this, a renamed control failed
            # per row on Playwright's 30 s timeout - 93 s to surface on 3 rows,
            # which on a 240-row screen is two hours before anyone notices.
            for role in ("note", "confirm"):
                if page.query_selector(sel[role]) is None:
                    raise DefinitionDrift(
                        f"{self.d['screen_key']}: selector for '{role}' "
                        f"({sel[role]}) matches nothing on the page")

            rows = page.eval_on_selector_all(
                sel["rows"],
                "els => els.map(e => ({id: e.dataset.rowId, status: e.dataset.status,"
                " cells: [...e.querySelectorAll('td')].map(td => td.textContent)}))")
            pv, dv = self.d["pending_value"], self.d["done_value"]
            pending = [r for r in rows if r["status"] == pv]
            unknown = sorted({r["status"] for r in rows} - {pv, dv})

            # Two situations that previously looked identical - "0 rows, 0
            # failed" - and must not:
            #   every row already done  -> a legitimate idempotent re-run
            #   rows in an unknown state -> the portal's vocabulary has drifted
            # The portal uses at least five words for "pending" across screens
            # (未処理 / 処理待ち / 申請中 / 照合中 / 未確認), so a word the
            # definition never saw is the likeliest production failure there is.
            # Silently reporting success on it was the worst possible outcome.
            if rows and not pending and unknown:
                raise DefinitionDrift(
                    f"{self.d['screen_key']}: {len(rows)} rows on screen, none in "
                    f"the expected pending state '{pv}'. Unrecognised statuses: "
                    f"{unknown}. The definition's status vocabulary is stale.")
            if unknown:
                self.warnings.append(
                    f"{self.d['screen_key']}: skipped rows in unrecognised "
                    f"states {unknown}")
            if limit:
                pending = pending[:limit]

            cols = self.d["columns"]
            for p in pending:
                t0 = time.time()
                row = dict(zip(cols, p["cells"]))
                note, mode = self.compose_note(row, self.rule_for(row))
                try:
                    if not self.dry_run:
                        page.click(f'{sel["rows"]}[data-row-id="{p["id"]}"]')
                        page.fill(sel["note"], note)
                        page.click(sel["confirm"])
                        page.wait_for_function(
                            "id => document.querySelector(`tr[data-row-id=\"${id}\"]`)"
                            ".dataset.status === '%s'" % self.d["done_value"],
                            arg=p["id"], timeout=5000)
                    self.outcomes.append(Outcome(self.d["screen_key"], p["id"],
                                                 str(row.get(self.d.get("route_on", "ID"), "")),
                                                 mode, note, (time.time() - t0) * 1000))
                except Exception as e:
                    self.outcomes.append(Outcome(self.d["screen_key"], p["id"],
                                                 str(row.get(self.d.get("route_on", "ID"), "")),
                                                 "failed", note,
                                                 (time.time() - t0) * 1000,
                                                 f"{type(e).__name__}: {e}"))
            browser.close()
        return self.outcomes
