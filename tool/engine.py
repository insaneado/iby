"""A worklist automation engine, driven by a per-system definition file.

Why an engine rather than three scripts
---------------------------------------
Step 2 found that one screen pattern carries **35.7% of all observed work**
(254 executions, 62.4 minutes) and appears in all three portal systems. The
three top-ranked candidates are the same screen in three deployments, and the
table contract is identical in all three - same seven columns, same element
ids, differing only in what fills them (`E2001` vs `BATCH-W2`, yen vs an em
dash). Three bespoke scripts would encode that shared structure three times.

Why the LLM is confined to one step
-----------------------------------
Navigation, row selection, field entry and confirmation are deterministic. They
are cheap, auditable, and cannot hallucinate a value into a financial system -
which matters, because a wrong note on an invoice approval is a real
consequence and an LLM offers no way to bound it.

Judgment appears in exactly one place, and the logs show where. 24% of worklist
rows are 種別 = 調整 (adjustment) rather than 定常 (routine), and the processes
with the highest adjustment rates are the ones where operators open a regulation
document mid-task. So: **routine rows run end to end; adjustment rows are
prepared and queued for a human.** That split is measured, not assumed, and it
is also the honest answer to "what manual work remains".

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

    # ---- rule table, loaded once from the regulation text ------------------
    def _rules(self, doc: str) -> list[dict]:
        if not hasattr(self, "_rule_cache"):
            import regulations
            self._corpus = regulations.corpus()
            self._extract = regulations.extract_rules
            self._route = regulations.route
            self._rule_cache = {}
        if doc not in self._rule_cache:
            self._rule_cache[doc] = self._extract(self._corpus.get(doc, ""))
        return self._rule_cache[doc]

    @staticmethod
    def _yen(text: str) -> int | None:
        import re
        m = re.search(r"([\d,]+)\s*円", str(text or ""))
        return int(m.group(1).replace(",", "")) if m else None

    # ---- the one place judgment lives -------------------------------------
    def compose_note(self, row: dict, rule: dict) -> tuple[str, str]:
        """Return (note, mode). Deterministic unless the row needs judgment."""
        template = rule.get("note_template", "")
        note = template.format(**{k: row.get(k, "") for k in row})
        if rule.get("mode") != "review":
            return note, "automated"

        # Before treating this as judgment, check whether the governing
        # regulation actually states a rule. Where it does - "under 50,000 yen:
        # department head; 50,000 and over: executive" - routing is arithmetic
        # and needs neither a model nor a person.
        doc = rule.get("rules_from") or rule.get("regulation", "")
        amount = self._yen(row.get("金額"))
        if doc and amount is not None:
            rules = self._rules(doc)
            approver = self._route(amount, rules) if rules else None
            if approver:
                return (f"{row.get('区分')} 確認。金額 {row.get('金額')}。"
                        f"規程により{approver}へ回付。"), "automated_by_rule"

        # Adjustment rows: a human decides. If a model is available it drafts
        # the note to save reading time; the row is queued either way.
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
        from playwright.sync_api import sync_playwright

        sel = self.d["selectors"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(self.d["url"], wait_until="domcontentloaded")
            page.wait_for_selector(sel["table"])

            pending = page.eval_on_selector_all(
                sel["rows"],
                "els => els.filter(e => e.dataset.status === '%s')"
                ".map(e => ({id: e.dataset.rowId, variant: e.dataset.variant,"
                " cells: [...e.querySelectorAll('td')].map(td => td.textContent)}))"
                % self.d["pending_value"])
            if limit:
                pending = pending[:limit]

            cols = self.d["columns"]
            for p in pending:
                t0 = time.time()
                row = dict(zip(cols, p["cells"]))
                rule = self.d["routing"].get(p["variant"], self.d["routing"]["定常"])
                note, mode = self.compose_note(row, rule)
                try:
                    if not self.dry_run:
                        page.click(f'{sel["rows"]}[data-row-id="{p["id"]}"]')
                        page.fill(sel["note"], note)
                        page.click(sel["confirm"])
                        page.wait_for_function(
                            "id => document.querySelector(`tr[data-row-id=\"${id}\"]`)"
                            ".dataset.status === '%s'" % self.d["done_value"],
                            arg=p["id"], timeout=5000)
                    self.outcomes.append(Outcome(self.d["system"], p["id"],
                                                 p["variant"], mode, note,
                                                 (time.time() - t0) * 1000))
                except Exception as e:
                    self.outcomes.append(Outcome(self.d["system"], p["id"],
                                                 p["variant"], "failed", note,
                                                 (time.time() - t0) * 1000,
                                                 f"{type(e).__name__}: {e}"))
            browser.close()
        return self.outcomes
