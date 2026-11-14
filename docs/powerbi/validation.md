# Validating the Power BI measures

The DAX in `measures.dax` has **not been executed** in Power BI Desktop. Before trusting it, set the filters below
and confirm each measure shows the expected value. The numbers come from `expected_kpis.csv`, which this
repository regenerates on every pipeline run.

* **Independent** rows were recomputed with pandas straight from the raw files, sharing no code or tables with dbt.
  If your measure disagrees with one of these, suspect the DAX (or the relationships) first.
* **Platform output** rows come from the warehouse's own engines (reconciliation, alerts, forecast). They check that
  Power BI reads the marts correctly, not that the engines are right.

Tip: put the *Measure* in a card visual, apply the filter in a slicer, and compare with *Expected*.

## Independent checks

| KPI | Measure | Set filters to | Expected | Tolerance |
|---|---|---|---:|---:|
| Revenue, EUR (monthly average rates) | `[Revenue]` | Year = 2025 | 91,123,481.19 | ±5 |
| Cost of goods sold, EUR | `[COGS]` | Year = 2025 | 35,296,788.23 | ±5 |
| Gross margin % | `[Gross Margin %]` | Year = 2025 | 0.6126 | ±1e-05 |
| Operating expenses incl. depreciation, EUR | `[Operating Expenses]` | Year = 2025 | 39,455,541.21 | ±5 |
| Operating income, EUR | `[Operating Income]` | Year = 2025 | 16,371,151.75 | ±5 |
| EBITDA (operating income + depreciation), EUR | `[EBITDA]` | Year = 2025 | 16,970,884.10 | ±5 |
| Revenue, EUR | `[Revenue]` | Year = 2025 and entity E01 | 21,351,195.71 | ±5 |
| Revenue, EUR | `[Revenue]` | Year = 2025 and entity E02 | 17,553,722.83 | ±5 |
| Revenue, EUR | `[Revenue]` | Year = 2025 and entity E03 | 10,713,326.95 | ±5 |
| Revenue, EUR | `[Revenue]` | Year = 2025 and entity E04 | 25,228,655.00 | ±5 |
| Revenue, EUR | `[Revenue]` | Year = 2025 and entity E05 | 16,276,580.71 | ±5 |
| Budgeted revenue, EUR (budget rates) | `[Budget Revenue]` | Year = 2025 | 91,279,320.71 | ±5 |
| Favourable (+) / unfavourable (-) P&L variance vs budget, EUR | `[Favourable Variance (Profit)]` | Year = 2025 (must also equal [Operating Income Variance]) | -1,617,131.76 | ±5 |
| Operational part of the profit variance, EUR (+ = good for profit) | `[Operational Variance (Profit)]` | Year = 2025 | -1,710,388.21 | ±5 |
| FX part of the profit variance, EUR (+ = good for profit) | `[FX Impact (Profit)]` | Year = 2025 | 93,256.45 | ±5 |
| Open receivables, EUR (month-end rate) | `[AR Balance (EUR)]` | any date in Dec 2025 | 16,537,298.56 | ±5 |
| Receivables more than 90 days past due, EUR | `[AR Over 90 (EUR)]` | any date in Dec 2025 | 2,777,469.90 | ±5 |
| Share of receivables more than 90 days past due | `[AR Over 90 %]` | any date in Dec 2025 | 0.1680 | ±1e-05 |
| Days sales outstanding (90-day window) | `[DSO (days)]` | any date in Dec 2025 and entity E01 | 62.60 | ±0.06 |
| Days sales outstanding (90-day window) | `[DSO (days)]` | any date in Dec 2025 and entity E02 | 56.10 | ±0.06 |
| Days sales outstanding (90-day window) | `[DSO (days)]` | any date in Dec 2025 and entity E03 | 73.30 | ±0.06 |
| Days sales outstanding (90-day window) | `[DSO (days)]` | any date in Dec 2025 and entity E04 | 61.80 | ±0.06 |
| Days sales outstanding (90-day window) | `[DSO (days)]` | any date in Dec 2025 and entity E05 | 61.50 | ±0.06 |
| Journals quarantined for debits <> credits | `[Journal Exceptions]` | no filters | 12.00 | ±0 |
| Total absolute out-of-balance amount, cents | `[Journal Exceptions Abs Difference (LC cents)]` | no filters | 39,271.00 | ±0 |

## Platform-output checks

| KPI | Measure | Set filters to | Expected | Tolerance |
|---|---|---|---:|---:|
| Share of bank lines matched to the ledger | `[Bank Match Rate]` | no filters | 0.9903 | ±1e-06 |
| Share of ledger cash lines matched to the bank | `[Ledger Match Rate]` | no filters | 0.9844 | ±1e-06 |
| Matches flagged for human review (tier 4c) | `[Review Queue]` | no filters | 375.00 | ±0 |
| Rows flagged is_alert in the variance alert mart | `[Variance Alerts]` | no filters | 56.00 | ±0 |
| Forecast collections over the next 13 weeks, EUR | `[Forecast Collections (EUR)]` | no filters | 13,384,512.68 | ±5 |
| Weekly forecast error (WAPE), model | `[Backtest WAPE (Model)]` | no filters | 0.1440 | ±1e-06 |
| Weekly forecast error (WAPE), naive baseline | `[Backtest WAPE (Baseline)]` | no filters | 0.6172 | ±1e-06 |
