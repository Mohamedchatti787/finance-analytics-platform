# Report specification: 7 pages

Each page answers one question a finance leader actually asks. Build in this order; all fields and measures
exist (see `measures.dax`, `data_model.md`). Canvas 16:9, theme `theme.json`.

**Global slicers (synced across pages):** Year (`dim_date[year]`), Entity (`dim_entity[entity_name]`).
Keep slicers in a left rail, 160 px wide. Use **Sync slicers** so a choice carries to every page.

---

## 1. Executive overview - "How are we doing, and what needs attention?"

| Visual | Fields | Notes |
|---|---|---|
| 5 KPI cards | `[Revenue]`, `[Gross Margin %]`, `[Operating Income]`, `[EBITDA]`, `[Operating Income Variance]` | Variance card: conditional font colour, green if >= 0 else red; also show the sign with `+`/`-` (do not rely on colour alone). |
| Line + column | X `dim_date[year_month]`, columns `[Revenue]`, line `[Budget Revenue]` | Shows the gap to plan at a glance. |
| Card row "Needs attention" | `[Unfavourable Alerts]`, `[Items Needing Investigation]`, `[AR Over 90 %]`, `[Journal Exceptions]` | Each card has a drill-through button to its detail page. |
| Table | `dim_entity[entity_name]`, `[Revenue]`, `[Operating Margin %]`, `[Operating Income Variance]` | Data bars on the variance column. |

## 2. P&L vs budget - "Where are we off plan?"

| Visual | Fields |
|---|---|
| Matrix | Rows `dim_account[statement_line]` > `dim_account[account_name]`; columns Actual `[Revenue]`... use per-line measures `SUM(fct_budget_variance[actual_eur])`, `SUM(fct_budget_variance[budget_eur])`, `[Favourable Variance (Profit)]`, `[Revenue Variance %]` |
| Clustered bars | Entity vs `[Favourable Variance (Profit)]`, sorted ascending |
| Decomposition tree | Analyse `[Favourable Variance (Profit)]`; explain by Entity, Account group, Cost centre |

Use `fct_budget_variance` here (it carries budget); P&L totals on other pages use `fct_trial_balance`. They agree (tested).

## 3. Variance drivers - "Is the miss operational or just currency?"

| Visual | Fields | Notes |
|---|---|---|
| **Waterfall** | Category `'Variance Bridge'[Step]`, Y `[Bridge Value]` | Budget operating income > operational variance > FX impact > actual operating income. This is the page's headline visual. |
| Clustered column | Entity vs `[Operational Variance (Profit)]` and `[FX Impact (Profit)]` | Shows Tunisia/US currency effects separately from real performance. |
| Table "Alerts" | `fct_variance_alerts`: entity, account, `period_end`, `rolling_variance_pct`, `robust_z`, `direction`, filtered `is_alert = TRUE` | Sort by `robust_z`. Add a note: rolling windows overlap, so rows are not additive. |

## 4. Balance sheet & cash - "Where is our cash and what does it consist of?"

| Visual | Fields |
|---|---|
| KPI card | `[Cash Balance (EUR)]` (closing position of the selected period) |
| Area chart | `dim_date[year_month]`, `[Cash Balance (EUR)]`, legend Entity |
| Matrix | Rows `dim_account[account_name]` for balance-sheet accounts (filter `dim_account[statement] = "BS"`), values `SUM(fct_trial_balance[closing_balance_eur])` at the selected month-end |

Note on the page: "EUR balance sheet is a presentation translation; no CTA is booked."

## 5. Receivables & DSO - "Who owes us money and how late are they?"

| Visual | Fields | Notes |
|---|---|---|
| Stacked area | `dim_date[year_month]`, `fct_ar_aging[aging_bucket]`, `SUM(balance_eur)` | Use the bucket sort order (the leading digit is deliberate). |
| Cards | `[AR Balance (EUR)]`, `[Overdue AR (EUR)]`, `[AR Over 90 %]`, `[DSO (days)]` | |
| Line | `dim_date[year_month]`, `[DSO (days)]`, legend Entity | Tunisia's DSO rising through 2025 is the intended story. |
| Table "Top overdue customers" | `dim_customer[customer_id]`, `[Overdue AR (EUR)]`, segment | Top N = 15 by `[Overdue AR (EUR)]`. |

## 6. Bank reconciliation control - "Can we trust the cash number?"

| Visual | Fields |
|---|---|
| Cards | `[Bank Match Rate]`, `[Ledger Match Rate]`, `[Review Queue]`, `[Items Needing Investigation]`, `[Recon Unexplained (max abs, LC)]` (must show 0) |
| Column | `fct_bank_recon_matches[match_type]`, count of rows | Shows how each match was justified. |
| Donut | `fct_bank_recon_unmatched[category]`, `[Unmatched Items]` | |
| Line | `dim_date[year_month]`, `[Bank Match Rate]` by entity | |
| Table | `fct_bank_recon_statement`: bank balance, ledger balance, each reconciling item, `unexplained_lc` | The reconciliation statement a controller signs. |
| Table | `fct_bank_recon_unmatched` filtered to investigate categories | Add `age_days`, `amount_lc`, `reference_text`. Drill-through target. |

## 7. Cash forecast - "How much cash will customers pay us in the next 13 weeks?"

| Visual | Fields | Notes |
|---|---|---|
| Column | `fct_cash_forecast[week_start]`, `[Forecast Collections (EUR)]`, legend Entity | |
| Card | `[Forecast Collections (EUR)]` | 13-week total. |
| Line (backtest) | `week_no`, predicted/baseline/actual from `fct_cash_forecast_backtest` | Slice by `origin`. Shows the forecast tracking reality and the baseline failing. |
| Cards | `[Backtest WAPE (Model)]`, `[Backtest WAPE (Baseline)]` | Honest accuracy disclosure on the page itself. |

---

## Design rules

* One message per page; title states the question, not the topic.
* Never encode meaning in red/green alone: keep `+`/`-` signs and arrows. The palette is colour-blind safe enough for the data colours.
* Every number that is a snapshot (cash, AR, DSO) is labelled "as at <date>" via a subtitle measure.
* Drill-through: from any `Entity` bar to page 2 filtered; from "Items Needing Investigation" to the unmatched table.
* Tooltips: add a report-page tooltip showing the entity's revenue sparkline.
