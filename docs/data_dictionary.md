# Data dictionary

Generated from the live warehouse schema by `export/make_data_dictionary.py`.

Amount columns: `*_cents` = integer cents; `*_lc` = local currency (decimal); `*_eur` = EUR. 'Natural sign' = revenue, liabilities and equity credit-minus-debit; assets and expenses debit-minus-credit.

## `raw` schema

### `raw.entities`

Legal entities (5) with functional currency.  Rows: 5.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `entity_name` | VARCHAR |
| `country` | VARCHAR |
| `currency` | VARCHAR |
| `reporting_currency` | VARCHAR |

### `raw.accounts`

Chart of accounts (25 accounts) with type, statement and normal balance.  Rows: 25.

| Column | Type |
|---|---|
| `account_id` | BIGINT |
| `account_name` | VARCHAR |
| `account_type` | VARCHAR |
| `statement` | VARCHAR |
| `normal_balance` | VARCHAR |
| `account_group` | VARCHAR |

### `raw.cost_centers`

Departments (8).  Rows: 8.

| Column | Type |
|---|---|
| `cost_center_id` | VARCHAR |
| `cost_center_name` | VARCHAR |

### `raw.fx_rates`

Monthly average and month-end rate to EUR for EUR/USD/TND.  Rows: 108.

| Column | Type |
|---|---|
| `period_start` | DATE |
| `currency` | VARCHAR |
| `avg_rate_to_eur` | DOUBLE |
| `close_rate_to_eur` | DOUBLE |

### `raw.budget_fx_rates`

Fixed annual budget rate per currency (prior-December close).  Rows: 9.

| Column | Type |
|---|---|
| `fiscal_year` | BIGINT |
| `currency` | VARCHAR |
| `budget_rate_to_eur` | DOUBLE |

### `raw.customers`

Customers (1,220) with segment and payment terms.  Rows: 1,220.

| Column | Type |
|---|---|
| `customer_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `segment` | VARCHAR |
| `payment_terms_days` | BIGINT |
| `country` | VARCHAR |

### `raw.invoices`

AR subledger: one row per sales invoice, integer cents.  Rows: 119,720.

| Column | Type |
|---|---|
| `invoice_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `customer_id` | VARCHAR |
| `invoice_date` | DATE |
| `due_date` | DATE |
| `revenue_account_id` | BIGINT |
| `net_cents` | BIGINT |
| `vat_cents` | BIGINT |
| `gross_cents` | BIGINT |

### `raw.payments`

Customer payments applied to invoices (partial payments allowed), integer cents.  Rows: 118,841.

| Column | Type |
|---|---|
| `payment_id` | VARCHAR |
| `invoice_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `payment_date` | DATE |
| `amount_cents` | BIGINT |

### `raw.gl_entries`

Double-entry general ledger lines, integer cents. Includes a handful of deliberately unbalanced journals.  Rows: 1,490,303.

| Column | Type |
|---|---|
| `gl_line_id` | BIGINT |
| `journal_id` | VARCHAR |
| `line_no` | BIGINT |
| `entity_id` | VARCHAR |
| `posting_date` | DATE |
| `account_id` | BIGINT |
| `cost_center_id` | VARCHAR |
| `debit_cents` | BIGINT |
| `credit_cents` | BIGINT |
| `source_system` | VARCHAR |
| `reference` | VARCHAR |
| `description` | VARCHAR |

### `raw.budgets`

Monthly budget by entity, P&L account and cost centre, integer cents (local currency).  Rows: 5,220.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `period_start` | DATE |
| `account_id` | BIGINT |
| `cost_center_id` | VARCHAR |
| `budget_cents` | BIGINT |

### `raw.bank_statements`

Bank statement lines (signed cents) with free-text reference and description.  Rows: 316,511.

| Column | Type |
|---|---|
| `bank_line_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `bank_account` | VARCHAR |
| `value_date` | DATE |
| `amount_cents` | BIGINT |
| `bank_reference` | VARCHAR |
| `description` | VARCHAR |
| `currency` | VARCHAR |

## `marts` schema

### `marts.dim_date`

Calendar, one row per day; month-end rows are the keys for monthly facts.  Rows: 1,096.

| Column | Type |
|---|---|
| `date_key` | DATE |
| `year` | BIGINT |
| `quarter` | BIGINT |
| `month` | BIGINT |
| `month_short` | VARCHAR |
| `year_month` | VARCHAR |
| `period_start` | DATE |
| `period_end` | DATE |
| `is_month_end` | BOOLEAN |
| `fiscal_year` | BIGINT |
| `iso_weekday` | BIGINT |

### `marts.dim_entity`

Entities with currency and country.  Rows: 5.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `entity_name` | VARCHAR |
| `country` | VARCHAR |
| `currency` | VARCHAR |
| `reporting_currency` | VARCHAR |

### `marts.dim_account`

Accounts with statement line grouping and P&L flag.  Rows: 25.

| Column | Type |
|---|---|
| `account_id` | BIGINT |
| `account_name` | VARCHAR |
| `account_type` | VARCHAR |
| `statement` | VARCHAR |
| `normal_balance` | VARCHAR |
| `account_group` | VARCHAR |
| `statement_line` | VARCHAR |
| `is_pl` | BOOLEAN |

### `marts.dim_cost_center`

Cost centres.  Rows: 8.

| Column | Type |
|---|---|
| `cost_center_id` | VARCHAR |
| `cost_center_name` | VARCHAR |

### `marts.dim_customer`

Customers with lifetime invoicing.  Rows: 1,220.

| Column | Type |
|---|---|
| `customer_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `segment` | VARCHAR |
| `payment_terms_days` | BIGINT |
| `country` | VARCHAR |
| `first_invoice_date` | DATE |
| `lifetime_invoices` | BIGINT |
| `lifetime_invoiced_lc` | DECIMAL(38,2) |

### `marts.fct_gl`

Ledger lines from BALANCED journals only, natural-sign amounts in local currency and EUR.  Rows: 1,490,279.

| Column | Type |
|---|---|
| `gl_line_id` | BIGINT |
| `journal_id` | VARCHAR |
| `line_no` | BIGINT |
| `entity_id` | VARCHAR |
| `posting_date` | DATE |
| `period_start` | DATE |
| `period_end` | DATE |
| `account_id` | BIGINT |
| `cost_center_id` | VARCHAR |
| `debit_lc` | DECIMAL(18,2) |
| `credit_lc` | DECIMAL(18,2) |
| `net_lc` | DECIMAL(19,2) |
| `natural_lc` | DECIMAL(19,2) |
| `currency` | VARCHAR |
| `avg_rate_to_eur` | DECIMAL(12,6) |
| `natural_eur` | DECIMAL(18,4) |
| `source_system` | VARCHAR |
| `reference` | VARCHAR |
| `description` | VARCHAR |

### `marts.fct_journal_exceptions`

Quarantined journals whose debits differ from credits; excluded from all reports.  Rows: 12.

| Column | Type |
|---|---|
| `journal_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `posting_date` | DATE |
| `source_system` | VARCHAR |
| `reference` | VARCHAR |
| `line_count` | BIGINT |
| `total_debit_lc` | DECIMAL(38,2) |
| `total_credit_lc` | DECIMAL(38,2) |
| `difference_lc` | DECIMAL(38,2) |
| `abs_difference_lc` | DECIMAL(38,2) |
| `abs_difference_eur` | DECIMAL(18,2) |

### `marts.fct_trial_balance`

Entity x account x month, dense grid, with activity, cumulative balance and EUR translation.  Rows: 4,320.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `account_id` | BIGINT |
| `period_start` | DATE |
| `period_end` | DATE |
| `currency` | VARCHAR |
| `activity_debit_lc` | DECIMAL(38,2) |
| `activity_credit_lc` | DECIMAL(38,2) |
| `activity_natural_lc` | DECIMAL(38,2) |
| `cumulative_natural_lc` | DECIMAL(38,2) |
| `ytd_natural_lc` | DECIMAL(38,2) |
| `avg_rate_to_eur` | DECIMAL(12,6) |
| `close_rate_to_eur` | DECIMAL(12,6) |
| `activity_natural_eur` | DECIMAL(18,2) |
| `closing_balance_eur` | DECIMAL(18,2) |

### `marts.fct_budget_variance`

Budget vs actual by entity/account/cost centre/month, with operational and FX variance that sum exactly to the total.  Rows: 5,220.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `period_start` | DATE |
| `period_end` | DATE |
| `fiscal_year` | BIGINT |
| `account_id` | BIGINT |
| `cost_center_id` | VARCHAR |
| `currency` | VARCHAR |
| `actual_lc` | DECIMAL(38,2) |
| `budget_lc` | DECIMAL(38,2) |
| `actual_rate` | DECIMAL(12,6) |
| `budget_rate` | DECIMAL(12,6) |
| `actual_eur` | DECIMAL(18,2) |
| `budget_eur` | DECIMAL(18,2) |
| `variance_total_eur` | DECIMAL(18,2) |
| `variance_operational_eur` | DECIMAL(18,2) |
| `variance_fx_eur` | DECIMAL(18,2) |
| `variance_pct` | DOUBLE |
| `favourable_variance_eur` | DECIMAL(18,2) |
| `favourable_operational_eur` | DECIMAL(18,2) |
| `favourable_fx_eur` | DECIMAL(18,2) |

### `marts.fct_variance_alerts`

3- and 6-month rolling variance with a robust (median/MAD) z-score and alert flag.  Rows: 4,875.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `account_id` | BIGINT |
| `horizon_months` | INTEGER |
| `period_start` | DATE |
| `period_end` | DATE |
| `rolling_variance_pct` | DECIMAL(12,4) |
| `robust_z` | DECIMAL(12,2) |
| `rolling_favourable_variance_eur` | DECIMAL(18,2) |
| `is_alert` | BOOLEAN |
| `direction` | VARCHAR |

### `marts.fct_ar_aging`

Receivables aging snapshot at every month-end by entity, customer and bucket.  Rows: 74,523.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `customer_id` | VARCHAR |
| `period_start` | DATE |
| `period_end` | DATE |
| `aging_bucket` | VARCHAR |
| `open_invoices` | BIGINT |
| `balance_lc` | DECIMAL(38,2) |
| `balance_eur` | DECIMAL(18,2) |

### `marts.fct_dso`

Days sales outstanding per entity-month, with EUR columns for weighted group DSO.  Rows: 180.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `period_end` | DATE |
| `period_start` | DATE |
| `ar_balance_lc` | DECIMAL(38,2) |
| `invoiced_window_lc` | DECIMAL(38,2) |
| `ar_balance_eur` | DECIMAL(18,2) |
| `invoiced_window_eur` | DECIMAL(18,2) |
| `window_days` | BIGINT |
| `dso_days` | DOUBLE |

### `marts.fct_bank_recon_matches`

Matched bank-ledger pairs with tier, score and a review flag (Python-built).  Rows: 315,623.

| Column | Type |
|---|---|
| `bank_line_id` | VARCHAR |
| `gl_line_id` | BIGINT |
| `entity_id` | VARCHAR |
| `tier` | BIGINT |
| `match_type` | VARCHAR |
| `score` | DOUBLE |
| `ref_sim` | DOUBLE |
| `amount_diff_c` | BIGINT |
| `date_diff_days` | BIGINT |
| `value_date` | TIMESTAMP |
| `posting_date` | TIMESTAMP |
| `bank_amount_lc` | DOUBLE |
| `gl_amount_lc` | DOUBLE |
| `review_required` | BOOLEAN |

### `marts.fct_bank_recon_unmatched`

Unmatched ledger and bank items with a reason category (Python-built).  Rows: 8,074.

| Column | Type |
|---|---|
| `item_side` | VARCHAR |
| `line_id` | VARCHAR |
| `entity_id` | VARCHAR |
| `item_date` | TIMESTAMP |
| `reference_text` | VARCHAR |
| `description` | VARCHAR |
| `category` | VARCHAR |
| `age_days` | BIGINT |
| `amount_lc` | DOUBLE |

### `marts.fct_bank_recon_summary`

Entity x month match rates and unmatched value (Python-built).  Rows: 180.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `period_end` | TIMESTAMP |
| `gl_cash_lines` | BIGINT |
| `gl_matched_lines` | BIGINT |
| `bank_lines` | BIGINT |
| `bank_matched_lines` | BIGINT |
| `unmatched_bank_value_lc` | DOUBLE |
| `unmatched_gl_value_lc` | DOUBLE |
| `gl_match_rate` | DOUBLE |
| `bank_match_rate` | DOUBLE |
| `period_start` | TIMESTAMP |
| `unmatched_bank_value_eur` | DOUBLE |
| `unmatched_gl_value_eur` | DOUBLE |

### `marts.fct_bank_recon_statement`

Bank-to-ledger reconciliation statement per entity; unexplained_lc must be 0 (Python-built).  Rows: 5.

| Column | Type |
|---|---|
| `entity_id` | VARCHAR |
| `as_of` | DATE |
| `bank_balance_lc` | DOUBLE |
| `ledger_balance_lc` | DOUBLE |
| `difference_lc` | DOUBLE |
| `matched_amount_differences_lc` | DOUBLE |
| `bank_charges_not_booked_lc` | DOUBLE |
| `interest_not_booked_lc` | DOUBLE |
| `unidentified_bank_items_lc` | DOUBLE |
| `ledger_outstanding_timing_lc` | DOUBLE |
| `ledger_unmatched_investigate_lc` | DOUBLE |
| `unexplained_lc` | DOUBLE |

### `marts.fct_cash_forecast`

13-week collections forecast from the latest date (Python-built).  Rows: 65.

| Column | Type |
|---|---|
| `origin` | TIMESTAMP |
| `entity_id` | VARCHAR |
| `week_no` | BIGINT |
| `week_start` | TIMESTAMP |
| `week_end` | TIMESTAMP |
| `predicted_lc` | DOUBLE |
| `predicted_eur` | DOUBLE |

### `marts.fct_cash_forecast_backtest`

Forecast vs baseline vs actual from three past origins (Python-built).  Rows: 195.

| Column | Type |
|---|---|
| `origin` | TIMESTAMP |
| `entity_id` | VARCHAR |
| `week_no` | BIGINT |
| `week_start` | TIMESTAMP |
| `predicted_lc` | DOUBLE |
| `baseline_lc` | DOUBLE |
| `actual_lc` | DOUBLE |
| `predicted_eur` | DOUBLE |
| `baseline_eur` | DOUBLE |
| `actual_eur` | DOUBLE |
