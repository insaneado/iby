"""Label a segment by what the operator did, not by what the record was called.

Why this exists
---------------
On dataset A the case-ID prefix identifies the process family with 100% purity
across all 15 families. It is useless on dataset B, where the IDs are employee
records (`P4-07089771-012`). A labeller that depends on case IDs encoding their
own process type would score perfectly on the data with ground truth and fail
silently on the data that is actually graded.

What the signature is
---------------------
Measured on dataset A's 2,009 gold segments, scoring candidate signatures
against the true process family:

    dominant app                     8 clusters   V=0.121
    portal system                    6 clusters   V=0.404
    route                            6 clusters   V=0.572
    document                        19 clusters   V=0.150
    system + route                  22 clusters   V=0.797   <- chosen
    system + route + document      159 clusters   V=0.697
    system + route + element id     63 clusters   V=0.818

That search predates two changes below - reading the state in force at a
segment's end, and learning the portal vocabulary from each dataset - so its
figures describe the signature as it then was. `python label.py` prints what
the shipped labeller scores on the same gold segments, and the report quotes
that figure, checked by explore/verify_report.py.

**system + route** wins, and the reason is structural rather than empirical:
the portal is one SPA deployed three times, so its route names repeat across
all three systems. Neither half identifies a process alone - `resident-tax`
under the HR system is 住民税通知確認 while the same route under the accounting
system is 請求書承認 - but 3 systems x 5 routes is exactly the 15 process
families, and each pair maps predominantly to one of them (`python label.py`
prints the purity of each; an earlier "92-98%" here had gone stale).

Richer signatures score no better. Adding the open document shatters the space
into 159 clusters for a *lower* score; adding element ids buys 0.021 V for
three times the clusters. Both are overfitting to dataset A's particular
apps, which is the failure mode this module exists to avoid.

Two details that matter more than they look
-------------------------------------------
*Read the system from the window title, not the browser tab.* `tab_title` is
populated on only 72% of browser events; the window title carries the system
name on 96.5% (dataset A) and 98.9% (dataset B). Using the obvious field would
have discarded a quarter of the signal.

*Carry the context forward.* A worker who steps into Excel or Notepad mid-task
is still on the same process, but emits no browser context while there. The
portal context in force at the segment's start is carried into segments that
observe none of their own.
"""
from __future__ import annotations
import collections
import re

import numpy as np

from common import load_index

# The three portal deployments, and short ASCII tokens for readable labels.
SYSTEMS = {
    "HR人事給与システム": "hr",
    "財務会計システム": "fin",
    "受発注在庫管理システム": "ops",
}
ROUTE_RE = re.compile(r"#/([\w-]+)")
UNKNOWN = "unknown"

# The route normally comes from the URL, which is an L3 (browser extension)
# signal. When the extension is not connected there is no L3 layer at all: 6 of
# 63 dataset A sessions and 1 of 15 dataset B sessions have zero URL events.
#
# Each portal screen has a distinctly worded note box, and that placeholder text
# also reaches L2 through the OS accessibility layer - 2,032 occurrences in
# dataset B. Cross-checked against L3 element ids where both layers exist, the
# mapping is one-to-one with no overlap (pi 472, la 282, ob 181, si 164, rt 137
# observations, zero cross-contamination). So it recovers the route from L2
# alone.
PLACEHOLDER_ROUTE = {
    "処理内容・確認コメントを入力": "payroll-items",
    "承認コメントまたは差戻し理由": "leave-applications",
    "照合結果・特記事項を入力": "onboarding",
    "処理内容・対応状況を入力": "social-insurance",
    "処理内容を入力": "resident-tax",
}


# `dashboard` is the portal's landing page, not a unit of work - operators pass
# through it between tasks. Treating it as a route created three low-purity
# clusters (33-65%) and cost 0.022 V-measure on dataset A. Ignoring it lets the
# surrounding context carry through instead.
NON_ROUTES = {"dashboard", ""}


def _slug(name: str) -> str:
    """Stable ASCII token for a discovered system name.

    SYSTEMS supplies readable tokens for the systems seen here; anything newly
    discovered falls back to a hash. Purely cosmetic - the task states the label
    text is not evaluated, only its consistency - so no discovered system is
    ever dropped for lack of a hand-written name.
    """
    import hashlib as _h
    return "sys_" + _h.sha1(name.encode("utf-8")).hexdigest()[:4]


def _route_from_placeholder(el_name, table=None) -> str | None:
    if not el_name:
        return None
    s = str(el_name).strip()
    table = PLACEHOLDER_ROUTE if table is None else table
    if s in table:
        return table[s]
    for frag, route in table.items():
        if frag in s:
            return route
    return None


def _mode(values):
    """Most common non-null value, or None."""
    c = collections.Counter(v for v in values if v)
    return c.most_common(1)[0][0] if c else None


def _system_of(title, tab_title, systems=None) -> str | None:
    for text in (title, tab_title):
        if not text:
            continue
        for jp, short in (systems or SYSTEMS).items():
            if jp in str(text):
                return short
    return None


def context_timeline(df, session_id: str, systems=None,
                     placeholders=None, non_routes=None):
    """(timestamps, [(system, route)]), filled forward then backward.

    Forward fill covers the common case - a worker steps into Excel mid-task and
    emits no browser context while there. Backward fill covers the start of a
    session, before any navigation has happened: 204 of dataset A's 2,009 gold
    segments had no context to inherit from the past, and those clusters were
    only 21-29% pure. Taking the *next* known context for them is the same
    assumption in the other direction.
    """
    g = df[df.session_id == session_id].sort_values("ts_ms")
    ts, sys_raw, url_raw, ph_raw = [], [], [], []
    for r in g.itertuples():
        m = ROUTE_RE.search(str(r.url)) if r.url else None
        route = m.group(1) if m else None
        ts.append(r.ts_ms)
        sys_raw.append(_system_of(r.title, r.tab_title, systems))
        url_raw.append(None if route in (non_routes or NON_ROUTES) else route)
        ph_raw.append(_route_from_placeholder(r.el_name, placeholders))

    def fill(seq):
        out = [None] * len(seq)
        cur = None
        for i, v in enumerate(seq):                      # forward
            cur = v or cur
            out[i] = cur
        nxt = None
        for i in range(len(seq) - 1, -1, -1):            # backward, gaps only
            nxt = seq[i] or nxt
            out[i] = out[i] or nxt
        return out

    # The URL is authoritative. The placeholder is kept in a separate channel and
    # consulted only where the URL never supplies a route, because the note box
    # lingers in the accessibility tree after the operator navigates away -
    # letting it compete with the URL cost 0.010 V-measure on dataset A.
    sys_f, url_f, ph_f = fill(sys_raw), fill(url_raw), fill(ph_raw)
    state = [(sys_f[i], url_f[i] or ph_f[i]) for i in range(len(ts))]
    return np.array(ts, dtype=np.int64), state


class SignatureLabeller:
    """Callable labeller for `segment.segment_dataset(labeller=...)`.

    Takes the segment rather than the case id, so it works identically on a
    dataset whose case ids carry no process information.
    """

    takes_segment = True          # segment.py dispatches on this

    def __init__(self, ds: str, discovered: bool = True):
        """discovered=True learns the portal vocabulary from this dataset's own
        events rather than using the module constants.

        This matters beyond tidiness. The hand-written placeholder table was
        derived from dataset B and agrees with dataset A's actual note-box
        wording on only 2 of 5 entries - the two portals word their screens
        differently. Discovery gets 5/5 on each dataset separately, because it
        reads each one's own vocabulary instead of assuming they share one.
        """
        self.df = load_index(ds)
        self._ctx: dict = {}
        if discovered:
            import discover
            sysnames = discover.discover_systems(self.df)
            self.systems = {n: SYSTEMS.get(n, _slug(n)) for n in sysnames}
            self.placeholders = discover.discover_placeholders(self.df)
            self.non_routes = discover.discover_non_routes(self.df) | {""}
        else:
            self.systems = dict(SYSTEMS)
            self.placeholders = dict(PLACEHOLDER_ROUTE)
            self.non_routes = set(NON_ROUTES)

    def _ctx_for(self, sid):
        if sid not in self._ctx:
            self._ctx[sid] = context_timeline(
                self.df, sid, self.systems, self.placeholders, self.non_routes)
        return self._ctx[sid]

    def __call__(self, segment) -> str:
        sid = segment.session_id
        ts, state = self._ctx_for(sid)
        if len(ts) == 0:
            return UNKNOWN
        a = int(segment.start.timestamp() * 1000)
        b = int(segment.end.timestamp() * 1000)
        lo, hi = int(np.searchsorted(ts, a)), int(np.searchsorted(ts, b, side="right"))

        # A segment ENDS at the terminal click, so the state in force at that
        # instant is where the work was actually completed. Taking the modal
        # state over the whole segment instead mixes in whatever the operator
        # passed through on the way, and measurably destroys the signal: on
        # dataset B, the labeller state and the portal breadcrumb agree
        # perfectly event-by-event (system 100%, V=0.770), but only V=0.254
        # once aggregated by mode. The loss was entirely in the aggregation.
        inside = state[lo:hi]
        if inside:
            sys_ = next((s for s, _ in reversed(inside) if s), None)
            route = next((r for _, r in reversed(inside) if r), None)
        else:
            sys_ = route = None
        # fall back to the modal state only where the end carries nothing
        if sys_ is None:
            sys_ = _mode(s for s, _ in inside if s)
        if route is None:
            route = _mode(r for _, r in inside if r)

        # otherwise carry forward whatever was in force when it started
        if sys_ is None or route is None:
            i = max(0, min(lo - 1, len(state) - 1))
            cs, cr = state[i]
            sys_ = sys_ or cs
            route = route or cr

        return f"{sys_ or UNKNOWN}__{route or UNKNOWN}"


if __name__ == "__main__":
    import collections
    from sklearn.metrics import v_measure_score, adjusted_rand_score
    from gold import load_gold

    gold = load_gold("dataset_a")
    lab = SignatureLabeller("dataset_a")
    truth, pred = [], []
    for sid, (segs, _, _) in gold.items():
        for s in segs:
            truth.append(s.label)
            pred.append(lab(s))
    print(f"gold segments {len(truth)}  clusters {len(set(pred))}")
    print(f"V-measure {v_measure_score(truth, pred):.3f}   "
          f"ARI {adjusted_rand_score(truth, pred):.3f}")
    print(f"unknown labels: {sum(1 for p in pred if UNKNOWN in p)}")
    print("\nlabel -> dominant true family (purity):")
    by = collections.defaultdict(collections.Counter)
    for t, p in zip(truth, pred):
        by[p][t] += 1
    for p, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values()))[:18]:
        top, n = c.most_common(1)[0]
        print(f"   {p:34} n={sum(c.values()):4d}  -> {top}  {100*n/sum(c.values()):5.1f}%")
