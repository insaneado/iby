# Step 2 — what the work is, and what to automate

Derived from `out/segments.jsonl` by `src/analyze.py` and `src/rank.py`.
All figures are **relative**. The brief states the recordings were made in a test
environment with compressed waiting times, so absolute durations are meaningless
and only comparisons between processes are valid.

## Scale

**668 executions, 175 minutes of observed work, 15 sessions, 4 operators**, all
on 2026-07-01 between 16:44 and 19:36 UTC.

### How many people, resolved

Three sources disagreed and had to be reconciled:

| source | count |
|---|---|
| `username_hash` | 4 |
| `machine_id` | 4 (strictly 1:1 with the hashes) |
| operator names on the portal dashboard | 3 |

The three names are **not** operators — all three appear in every session. Each
maps to one portal system:

| name | system | consistency |
|---|---|---|
| 田中 麻里 · 人事マネージャー | HR人事給与システム | 98% |
| 佐藤 直樹 · 経理マネージャー | 財務会計システム | 100% |
| 高橋 健司 · 物流マネージャー | 受発注在庫管理システム | 97% |

So: **4 people, working across all three systems under shared per-system
logins.** That last point is a governance finding, not a trivia one — automation
would run under a shared account, leaving no per-user audit trail.

## The route names lie

The portal is one SPA deployed three times, so its route names repeat across all
three systems and describe nothing. The regulation document open during the work
says what the work actually is:

| segment label | regulation document consulted | what it really is |
|---|---|---|
| `ops__leave-applications` | keiyaku_kaijo_tetsuzuki | contract termination |
| `fin__leave-applications` | settai_keihi_kitei | entertainment expense approval |
| `fin__payroll-items` | getsujitsu_teigaku_torihikisaki_ichiran | recurring supplier payment |
| `fin__resident-tax` | shinkuitorihikisaki_touroku_tetsuzuki | new supplier registration |
| `hr__onboarding` | nyusha_checklist_shinsotsu_batch | new-graduate onboarding |
| `ops__social-insurance` | kanrisya_kengen_shinsei_tetsuzuki | admin privilege request |

This is also **independent validation of Step 1's labels**. The pipeline never
reads document names, yet segments sharing a label consult the same document at
**79% weighted purity**. That agreement is evidence the groupings track real
business processes rather than portal geography.

*Caveat: the English readings are mine and unverified — see `docs/glossary.md`.*

## Ranking

Two measurable quantities in tension:

- **Mechanical load** — clipboard events and application switches per run. The
  part automation removes.
- **Judgment load** — share of runs where a regulation document is open. The
  part automation does not remove, and what decides whether a deterministic
  script is even possible.

High volume with high judgment is a poor first target however expensive it
looks, because the residue is what costs the time.

| process | n | min | share | median s | mech | judgment | people |
|---|---:|---:|---:|---:|---:|---:|---:|
| payroll_item_maintenance | 115 | 24.5 | 14.0% | 11 | 2.3 | 11% | 4 |
| recurring_supplier_payment | 74 | 22.8 | 13.1% | 15 | 3.5 | 55% | 4 |
| contract_termination | 65 | 22.0 | 12.6% | 18 | 6.3 | 79% | 4 |
| new_grad_onboarding | 59 | 20.2 | 11.5% | 19 | 6.3 | 83% | 4 |
| inventory_payroll_items | 65 | 15.1 | 8.6% | 11 | 3.7 | 6% | 4 |
| new_supplier_registration | 67 | 13.8 | 7.9% | 11 | 1.9 | 22% | 4 |
| leave_application_review | 58 | 12.4 | 7.1% | 10 | 1.9 | 0% | 3 |
| contractor_payment_setup | 40 | 12.0 | 6.9% | 20 | 5.5 | 60% | 3 |
| admin_privilege_request | 45 | 10.3 | 5.9% | 11 | 3.1 | 18% | 4 |
| entertainment_expense_approval | 36 | 10.2 | 5.8% | 16 | 5.1 | 67% | 2 |
| childcare_leave_handling | 33 | 7.4 | 4.2% | 13 | 3.3 | 52% | 3 |

### Robustness

A priority formula is easy to make say what you want, so the ranking was scored
under six different weightings (time alone, count alone, time x automatability,
mechanical x count, and two combined forms). Processes with n < 5 were excluded,
since per-run rates on one or two observations are noise.

| process | top-3 appearances |
|---|---|
| **payroll_item_maintenance** | **6 / 6** |
| recurring_supplier_payment | 4 / 6 |
| inventory_payroll_items | 3 / 6 |
| contract_termination | 2 / 6 |
| four others | 1 / 6 each |

Only one process survives every weighting. Anything appearing once is an
artefact of a particular formula, not a finding.

## The result that changes the recommendation

Aggregating by portal **screen** rather than by system:

| screen | executions | minutes | share of all work | systems | judgment |
|---|---:|---:|---:|---:|---:|
| **payroll-items** | **254** | **62.4** | **35.7%** | **3** | **24%** |
| leave-applications | 159 | 44.6 | 25.5% | 3 | 48% |
| onboarding | 99 | 32.2 | 18.4% | 2 | 72% |
| social-insurance | 86 | 20.4 | 11.7% | 3 | 23% |
| resident-tax | 67 | 13.8 | 7.9% | 1 | 22% |

**One screen pattern accounts for 36% of all observed work, occurs in all three
systems, and carries the second-lowest judgment load.** The three top-ranked
processes are the same screen in three different deployments.

That reframes Step 3. The choice is not "which process do I automate" but
"one bespoke process, or the shared pattern behind three of them" — which is
exactly the scope question the brief says is itself part of the ROI decision.
