# Questions for a Japanese reader

**Parts A–C: twelve questions, about 15 minutes, answered 2026-09-10. Part D:
about 10 minutes, pending.** No technical knowledge required.

> **VERIFIED — 2026-09-10.** A Japanese-reading reviewer confirmed all twelve
> readings as correct. The threshold direction in Part A (未満 = under,
> 以上 = and over) is therefore confirmed, and `tool/regulations.py` routes
> approvals accordingly. Claims depending on these readings are stated as
> verified in the report rather than as assumptions.
>
> **Part D is pending.** It was added on 2026-09-11 for readings the report
> uses that Parts A–C did not cover. The report states them as unverified
> until they are checked.


Everything below is Japanese text taken directly from the client's data, except
D3 and D4 in Part D, which this project wrote. Next to each is my English
reading. I do not read Japanese, so these are unverified, and
a few of them decide what an automated tool actually does.

**How to answer:** for each row write **OK**, or write the correct reading.
Reply in any form — a photo of a scribbled list is fine.

---

## Part A — the 3 that change what the software does (most important)

The automation reads these rules and routes approvals by them. If a reading is
wrong, it routes the wrong approver on real money.

**A1.** `第２条（承認権限）1回あたり5万円未満：部門長承認。5万円以上：役員承認。10万円以上：社長承認。`

> My reading: *"Article 2 (Approval authority). Per occurrence: under ¥50,000 →
> department head approval; ¥50,000 and over → executive approval; ¥100,000 and
> over → president approval."*

Specifically: does **5万円 = 50,000 yen**, and does **未満 mean "under/less than"**
while **以上 means "and over"**? — **OK / correction:**

**A2.** `契約金額100万円未満：部門長承認。100万円以上：役員承認。3000万円以上：取締役会決議。`

> My reading: *"Contract value under ¥1,000,000 → department head; ¥1,000,000 and
> over → executive; ¥30,000,000 and over → board resolution."*

— **OK / correction:**

**A3.** Row status values: `未処理` = *unprocessed*, `登録済み` = *registered / done*,
and the confirmation message `登録確定しました` = *"registration confirmed"*.

— **OK / correction:**

---

## Part B — the 6 process names used in the analysis

These name the business processes in the report's priority ranking. Each is a
Word document filename written in romaji (Japanese in Latin letters).

| # | filename | my reading |
|---|---|---|
| **B1** | `gyomu_itaku_keihi_kitei` | Outsourcing expense regulations |
| **B2** | `getsujitsu_teigaku_torihikisaki_ichiran` | Monthly fixed-amount supplier list |
| **B3** | `keiyaku_kaijo_tetsuzuki` | Contract termination procedure |
| **B4** | `nyusha_checklist_shinsotsu_batch` | New-graduate onboarding checklist |
| **B5** | `settai_keihi_kitei` | Entertainment expense regulations |
| **B6** | `shinkuitorihikisaki_touroku_tetsuzuki` | New supplier registration procedure |

— **OK for all / corrections:**

---

## Part C — the 3 systems (quick sanity check)

| # | Japanese | my reading |
|---|---|---|
| **C1** | `HR人事給与システム` | HR payroll system |
| **C2** | `財務会計システム` | Financial accounting system |
| **C3** | `受発注在庫管理システム` | Order & inventory management system |

— **OK / corrections:**

---

## Optional, if they have another 5 minutes

`種別` column values — I read **`定常` = routine/standard** and **`調整` =
adjustment**. The tool treats 定常 rows as fully automatable and 調整 rows as
needing a rule check. Is that a fair reading of the two words?

— **OK / correction:**

---

## Part D — pending: readings the report uses that Parts A–C did not cover

**D1.** The screen titles that name the processes in the Step 2 ranking.

| # | screen title | my reading | process name used |
|---|---|---|---|
| **D1a** | `経費承認（管理職）` | Expense approval by managers | manager_expense_approval |
| **D1b** | `支払処理` | Payment processing | payments |
| **D1c** | `請求書承認・経費精算` | Invoice approval and expense settlement | invoice_approval |
| **D1d** | `発注管理` | Purchase order management | purchase_orders |
| **D1e** | `予算差異分析` | Budget variance analysis | budget_variance_analysis |
| **D1f** | `勤怠・休暇申請` | Attendance and leave applications | attendance_and_leave |
| **D1g** | `入社手続き` | Onboarding procedures | onboarding_procedures |
| **D1h** | `経費精算・給与変更` | Expense settlement and pay changes | expense_and_pay_change |
| **D1i** | `福利厚生申請` | Benefits applications | benefits_applications |
| **D1j** | `契約管理` | Contract management | contract_management |
| **D1k** | `在庫管理` | Inventory management | inventory_management |
| **D1l** | `IT申請` | IT requests | it_requests |

— **OK / corrections:**

**D2.** Row types on the contract screen: `新規締結` = *a new contract being
concluded*, `解除` = *a termination*. The tool leaves both to a person.

— **OK / correction:**

**D3.** The notes the tool writes into the portal. Are they natural Japanese,
and do they say what the English says?

| note | what I intend it to say |
|---|---|
| `確認済。…定常処理として登録。` | checked; registered as routine processing |
| `…調整区分のため要確認。` | needs confirmation, because it is an adjustment |
| `規程により社長承認へ回付` | forwarded for the president's approval, under the regulation |
| `…{部署}として処理。` | processed as {department} |
| `…更新として処理。` / `…変更として処理。` | processed as a renewal / as a change |
| `…解除のため要確認。` / `…新規締結のため要確認。` | needs confirmation, because it is a termination / a new contract |

— **OK / corrections:**

**D4.** `report/SUMMARY_JA.md` was rewritten from the corrected English after
Parts A–C were checked. Does it read naturally, and does it say what
`report/REPORT.md` says?

— **OK / corrections:**

---

That is everything. Beyond Part D, the remaining ~110 terms in `glossary.md`
are screen labels and product names that do not affect any decision — no need
to look at them.
