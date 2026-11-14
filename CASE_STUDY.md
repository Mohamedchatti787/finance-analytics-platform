# Case study: closing the books on a five-entity company

**Company:** Meridian, a fictional software-and-hardware group: 5 legal entities (France, Germany, Tunisia, two US), 3 currencies,
reporting in EUR, January 2023 to December 2025. **All data is synthetic**, generated with known problems planted in it, so each
finding below can be checked against a known answer. Read the findings as *evidence that the method works*, not as discoveries.
Numbers are for seed 2024 at full scale and reproduce exactly with `python run_pipeline.py`.

---

## 1. Where did we miss budget, and was it real performance or currency?

**Question.** FY2025 profit is behind plan. Which entities and lines are responsible, and how much is just exchange rates?

**Method.** Compare actual with budget for every P&L line (entity × account × cost centre × month), translating actuals at the month's
average rate and budget at the fixed budget rate, then split the EUR variance into an operational part, `(actual − budget) × budget rate`,
and an FX part, `actual × (actual rate − budget rate)`. The two sum exactly to the total (a dbt test enforces it on every line).
Variances are signed in profit terms (positive = good for profit).

**Finding.** FY2025 revenue was **€91.1 M** and operating income **€16.4 M (18.0 %)**, which is **€1.62 M below budget**:
**−€1.71 M operational** and **+€0.09 M from currency**. Almost nothing here is an exchange-rate story.

| Entity | Profit vs budget | Main driver |
|---|---:|---|
| Tunisia | **−€1.47 M** | subscription revenue −11.8 %, services −12.1 %, hardware −6.9 % vs budget |
| Germany | **−€0.69 M** | hardware COGS +13 % over budget (−€321 k), hardware revenue −6 % |
| US-East | ≈ €0 | salaries +8.1 % (+€469 k cost) offset by revenue above budget |
| France | +€0.37 M | |
| US-West | +€0.17 M | |

**Why a sorted variance list is not enough.** Large revenue lines always top it, because noise on a big number is a big number. The platform
instead scores each entity-account's rolling 3- and 6-month variance against how noisy *that account* normally is across the whole panel
(robust z-score using median and median absolute deviation, so the anomalies don't inflate the yardstick that detects them), and requires a material EUR
impact. Against the problems planted in the data:

| Planted | Result |
|---|---|
| Germany marketing overspend, Q4-2024 | **Detected.** €97.7 k over in the quarter, +42.9 % vs budget (planted +35 % volume, plus noise). |
| Germany hardware price +12 % from Jul-2024 | **Detected only at the 6-month horizon, and narrowly** (peak z 3.6 vs a 3.5 threshold). A 3-month-only first version missed it. |
| Tunisia lost customer, revenue −18 % | **Detected on 2 of 3 revenue lines.** Realized −14.2 %: that sample drew 4.6 % more invoices than expected (+3.1 σ). The generator is unbiased elsewhere (0.999 observed/expected), so the seed was kept rather than re-rolled. |
| US-East payroll +8 % | **Detected**, strongly (z ≈ 21), also flowing through payroll taxes. |

One false alarm in 3 years (Tunisia software, a single month). The June-2025 spike in German marketing (149 invoices vs about 119 expected) is ordinary noise and, correctly, does not alert.

**Recommendation.** Review Tunisia's revenue pipeline and German hardware supplier pricing first; together they explain more than the whole group shortfall.
Re-forecast US-East's payroll (the overrun is real but covered by revenue). Treat alerts as a *triage queue*: the z-threshold is a judgment call, and a longer-horizon method (CUSUM/EWMA) is the natural next step for slow drifts.

**Caveat.** The detector's power was demonstrated on effects I planted. Real shocks are messier.

---

## 2. Can we trust the cash number? Bank reconciliation

**Question.** Do 317 k bank lines match 321 k ledger cash postings, and what explains the rest?

**Method.** A five-tier matcher, strictest first, so each match has an auditable reason: exact amount + exact reference; exact amount + similar reference;
exact amount with a unique pairing; amount within tolerance (bank-deducted fees, keying typos), with the reference carrying the decision;
and one bank deposit equal to the sum of several ledger receipts (subset-sum search). The lowest-confidence tier is flagged for human review.
Leftovers are classified (outstanding timing vs investigate; unbooked bank charge, unbooked interest, unidentified deposit).
The engine never sees the generator's answer key; it is scored against it afterwards.

**Finding.** **99.03 %** of bank lines and **98.44 %** of ledger lines matched, with **precision 99.98 %** and **recall 99.75 %** against ground truth
(73 wrong pairs, 778 missed, out of 316,328). Recall is 100 % on clean items, 94.1 % on fee/typo differences and 90.6 % on batched deposits (batches containing a slow-clearing cheque fall outside the search window).
The one weak tier, matches with **no usable reference**, is only 81.9 % precise, which is exactly why it is queued for review rather than auto-approved.

Each entity gets a bank-to-ledger statement that **foots to 0.00 unexplained**. One entity at 31-Dec-2025 (bank €12.76 M vs ledger €12.34 M, difference €424.7 k):

| Reconciling item | € |
|---|---:|
| Unidentified deposits (cash received, not in the ledger) | +320,329 |
| Ledger items not yet at the bank (outstanding, timing) | +220,756 |
| Ledger items to investigate (no bank counterpart, > 30 days) | −96,655 |
| Matched pairs whose amounts differ (fees, typos) | −15,383 |
| Bank charges not booked | −8,795 |
| Interest not booked | +4,471 |
| **Unexplained** | **0** |

**A bug worth knowing about.** My first tolerance tier matched about 13 % of its pairs to the *wrong* ledger line. Fuzzy string similarity rated two different bill numbers
(`...0095` and `...0058`) as 97 % alike, and my scoring *rewarded closer amounts*, which is backwards when a bank fee changed the amount on purpose.
The fix (an exact reference always outranks a fuzzy one) cut false positives from 782 to 73 and is locked in by a regression test.

**Recommendation.** Book the 2,058 unrecorded bank charges (about €37.7 k, Dr 6700 / Cr 1010) and the interest; work the 831 unidentified deposits
(net €1.28 M of cash received but not applied to a customer); review ledger items older than 30 days that never reached the bank
(3,650 of the 4,341 flagged are genuinely ledger-only postings, i.e. possible duplicates or errors).

---

## 3. Who owes us money, and how late?

**Question.** How old is the receivables book, who is behind it, and is collection getting worse?

**Method.** Aging is snapshotted at **every** month-end from the AR subledger (open balance = invoice − payments received to that date), bucketed 0 / 1-30 / 31-60 / 61-90 / 90+ days past due,
and tied to the general ledger: the subledger must equal GL account 1100 for every entity and month (asserted by a dbt test and re-checked by a mutation test that removes a payment).
DSO is the open balance over the trailing 90 days of invoicing, weighted across entities in EUR.

**Finding.** At 31-Dec-2025, **€16.5 M** is open and **16.8 % is more than 90 days past due**. Group DSO is 62 days.
**Tunisia's DSO rose from 53 (Dec-2023) to 57 (Dec-2024) to 73 days (Dec-2025)**, the visible footprint of its customers slowing down in 2025.
The 53 chronically slow payers (4.3 % of customers) hold only about **5.5 %** of the over-90 balance: most of the aged book is invoices that are never paid at all.

**Recommendation.** Treat the over-90 book as a **provisioning and write-off review**, not a collections drive, since in the backtest that bucket collected 0.04 % of its balance in 13 weeks.
Chase Tunisia separately: its slowdown is behavioural and growing.

---

## 4. How much cash will arrive in the next 13 weeks?

**Question.** Forecast weekly customer collections from the open receivables.

**Method.** For each open invoice: predicted payment date = due date + the customer's typical delay **conditional on how late the invoice already is**;
predicted amount = open balance × a **recovery rate by lateness bucket** learned only from history before the forecast date (no look-ahead). Backtested from three past
origins (31-Mar, 30-Jun, 30-Sep-2025) against what was actually collected, versus a naive baseline in which everyone pays on the due date.

**Finding.** Weekly error (WAPE) **14.4 %** vs **61.7 %** for the baseline; total-volume bias **+1.3 %** vs **+19.9 %**.
Forecast collections for the 13 weeks after 31-Dec-2025: **€13.4 M**. Tunisia is hardest (20.6 %) because its behaviour shifted during 2025.

**How the forecast got here (the useful part).** The first version over-predicted by 17 %. My hypothesis (survivorship bias in the delay estimate) was *wrong*: conditioning on lateness changed nothing.
A bucket-level diagnostic showed the real cause. Invoices 90+ days late, effectively never paid, accumulate in the open book, so the open book is enriched with dead debt,
while a single entity-wide collection rate (about 98.7 %) is computed over all old invoices and cannot see it. Recovery rates by lateness bucket cut the bias to +1.3 % and the error from 29 % to 14 %.

**Recommendation.** Use the forecast for weekly cash planning with the backtest error shown next to it, and keep the recovery rates under review as behaviour changes (Tunisia).

**Caveat.** Payment behaviour here is synthetic (non-payers are a simple 1.2 % random draw); real behaviour is messier, so real error would be higher.

---

## 5. Controls that make the numbers trustworthy

* **Double-entry integrity.** 12 journals out of 652,542 were posted unbalanced (€323 in total). They are **quarantined** (excluded from every report, listed in `fct_journal_exceptions`),
  and a test proves no ledger line can vanish.
* **Subledger ties to ledger** for every entity and month; **trial balance debits = credits**; **variance parts sum exactly**; **FX rates complete**; no overpaid invoices; budgets only on P&L accounts.
* **Two implementations.** Headline KPIs are recomputed in pandas straight from the raw files and compared with the dbt marts (they share no code).
* **Mutation tests.** Five tests corrupt a copy of the data (drop a payment, unbalance a journal, delete an FX rate, overpay an invoice, budget a balance-sheet account) and assert the matching control fires.

## What is deliberately out of scope

Power BI Desktop is Windows-only and was not available where this was built, so the `.pbix` is not included; the data model, 56 DAX measures, page specification, RLS design and a 32-KPI
validation guide are. The Airflow DAG was loaded and parsed with Airflow's own DagBag but not run. The warehouse is DuckDB, not PostgreSQL. See the README for the full status table.
