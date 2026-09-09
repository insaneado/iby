"""Learn the portal's vocabulary from the logs instead of hard-coding it.

Earlier versions of this pipeline contained three Japanese system names, five
Japanese placeholder strings, the word "dashboard", and the prefix "btn-",
typed in by hand. Every one had a measured justification, but they were
*written* rather than *derived* - and a process-mining tool meets a different
portal at every client. Hand-written vocabulary is not a pipeline, it is a
transcript of one dataset.

Each function here rediscovers, from the events alone, something that was
previously a constant. `python discover.py` checks the discovered values against
the hand-written ones: agreement means the constants were justified, divergence
means they were overfitted to dataset A.

None of this is machine learning, and it should not be. These are exact
structural relations - a <button> tag is a button; an element id co-occurring
with a URL route defines that screen's prefix - recoverable by counting.
Fitting a model to them would add variance, opacity and cost while removing the
audit trail an enterprise deployment needs.
"""
from __future__ import annotations
import collections
import re

import pandas as pd

from common import load_index

BROWSERS = ("Google Chrome", "Microsoft Edge")
ROUTE_RE = re.compile(r"#/([\w-]+)")
_MORE_PAGES = re.compile(r"\s+and\s+\d+\s+more\s+pages?$")


def discover_terminators(df: pd.DataFrame) -> pd.DataFrame:
    """Clicks that end a unit of work.

    Structural, not lexical: an HTML `button` is a button. Matching names
    instead ("btn-*-ok") found 629 in dataset B and **zero** in dataset A, which
    names the same controls semantically (btn-la-approve, btn-rt-query). That
    near-miss hid the strongest signal in the data for a day.
    """
    return df[df.el_tag == "button"]


def discover_systems(df: pd.DataFrame, min_events: int = 200) -> dict:
    """Portal systems, as the leading component of browser window titles.

    A window title reads "<system> - Profile 1 - Microsoft Edge". Titles that
    appear often, across multiple sessions, and alongside portal URLs are
    system names; everything else is a stray page.
    """
    def head_of(title):
        h = str(title).split(" - ")[0].strip()
        return _MORE_PAGES.sub("", h).strip()

    d = df[df.app.isin(BROWSERS) & df.title.notna()]
    seen = collections.Counter()
    sess = collections.defaultdict(set)
    for r in d.itertuples():
        h = head_of(r.title)
        if h:
            seen[h] += 1
            sess[h].add(r.session_id)

    # A business system is one where units of work are completed. Frequency
    # alone also admits the SSO login page and untitled tabs, which are passed
    # through rather than worked in - the same test that identifies non-routes.
    hosts_work = {head_of(r.title) for r in discover_terminators(df).itertuples()
                  if r.title}
    return {k: v for k, v in seen.items()
            if v >= min_events and len(sess[k]) >= 2 and k in hosts_work}


def discover_screens(df: pd.DataFrame) -> dict:
    """Map an element-id prefix to the route it belongs to.

    Where the browser extension is connected, an element id (`pi-note`) and a
    URL route (`#/payroll-items`) are observed on the same event. Counting that
    co-occurrence recovers the prefix->route table that was previously typed in.
    """
    d = df[df.el_id.notna() & df.url.notna()]
    pref_route = collections.defaultdict(collections.Counter)
    for r in d.itertuples():
        m = ROUTE_RE.search(str(r.url))
        if not m:
            continue
        eid = str(r.el_id)
        pref = eid.split("-")[1] if eid.startswith("btn-") else eid.split("-")[0]
        if pref:
            pref_route[pref][m.group(1)] += 1
    return {p: c.most_common(1)[0][0] for p, c in pref_route.items()
            if c.most_common(1)[0][1] >= 5}


def discover_placeholders(df: pd.DataFrame) -> dict:
    """Map on-screen placeholder text to a route, for use when there is no L3.

    The note box of each screen carries distinct wording. Where both layers are
    present the placeholder is visible as `el_name` on an element whose `el_id`
    identifies the screen, so the text->route table is recoverable by counting -
    which is what makes it usable in the sessions where the browser extension
    never connected and no URL exists at all.
    """
    pref_route = discover_screens(df)
    d = df[df.el_id.notna() & df.el_name.notna()]
    text_route = collections.defaultdict(collections.Counter)
    for r in d.itertuples():
        eid = str(r.el_id)
        pref = eid.split("-")[1] if eid.startswith("btn-") else eid.split("-")[0]
        route = pref_route.get(pref)
        if route:
            text_route[str(r.el_name).strip()][route] += 1
    return {t: c.most_common(1)[0][0] for t, c in text_route.items()
            if c.most_common(1)[0][1] >= 5 and len(c) == 1}


def discover_non_routes(df: pd.DataFrame, max_share: float = 0.03) -> set:
    """Routes that are passed through rather than worked in.

    A landing page is visited briefly and often; a work screen holds the
    operator. Routes that never host a terminator are not units of work.
    """
    term = discover_terminators(df)
    term_routes = collections.Counter()
    for r in term.itertuples():
        m = ROUTE_RE.search(str(r.url)) if r.url else None
        if m:
            term_routes[m.group(1)] += 1
    all_routes = collections.Counter()
    for u in df.url.dropna():
        m = ROUTE_RE.search(str(u))
        if m:
            all_routes[m.group(1)] += 1
    total = max(sum(term_routes.values()), 1)
    return {r for r in all_routes
            if term_routes[r] / total < max_share}


if __name__ == "__main__":
    import label
    import caseid

    for ds in ("dataset_a", "dataset_b"):
        df = load_index(ds)
        print(f"\n{'='*66}\n{ds}\n{'='*66}")

        term = discover_terminators(df)
        hand = df[df.el_id.notna() & df.el_id.astype(str).str.startswith("btn-")]
        print(f"terminators      discovered {len(term):5d}   hand-written rule {len(hand):5d}")

        sysd = discover_systems(df)
        print(f"systems          discovered {len(sysd)}: {list(sysd)}")
        print(f"                 hand-written: {list(label.SYSTEMS)}")
        print(f"                 MATCH: {set(sysd) == set(label.SYSTEMS)}")

        scr = discover_screens(df)
        print(f"screens          discovered {len(scr)}: {scr}")

        ph = discover_placeholders(df)
        hand_ph = label.PLACEHOLDER_ROUTE
        agree = sum(1 for t, r in ph.items()
                    if any(f in t for f in hand_ph) and
                    hand_ph[next(f for f in hand_ph if f in t)] == r)
        print(f"placeholders     discovered {len(ph)}, agreeing with hand-written: {agree}/{len(hand_ph)}")

        nr = discover_non_routes(df)
        print(f"non-routes       discovered {sorted(nr)}   hand-written {sorted(label.NON_ROUTES - {''})}")
