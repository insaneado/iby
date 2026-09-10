# 12 questions for a Japanese reader

**Time needed: about 15 minutes. No technical knowledge required.**

Everything below is Japanese text taken directly from the client's data. Next to
each is my English reading. I do not read Japanese, so these are unverified, and
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

That is everything. The remaining ~110 terms in `glossary.md` are screen labels
and product names that do not affect any decision — no need to look at them.
