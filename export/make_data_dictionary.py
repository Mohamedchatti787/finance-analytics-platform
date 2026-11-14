"""Generate docs/data_dictionary.md from the live warehouse schema (types never drift) plus curated descriptions."""
from pathlib import Path

import duckdb

TABLES = {
    "raw": {
        "entities": "Legal entities (5) with functional currency.",
        "accounts": "Chart of accounts (25 accounts) with type, statement and normal balance.",
        "cost_centers": "Departments (8).",
        "fx_rates": "Monthly average and month-end rate to EUR for EUR/USD/TND.",
        "budget_fx_rates": "Fixed annual budget rate per currency (prior-December close).",
        "customers": "Customers (1,220) with segment and payment terms.",
        "invoices": "AR subledger: one row per sales invoice, integer cents.",
        "payments": "Customer payments applied to invoices (partial payments allowed), integer cents.",
        "gl_entries": "Double-entry general ledger lines, integer cents. Includes a handful of deliberately unbalanced journals.",
        "budgets": "Monthly budget by entity, P&L account and cost centre, integer cents (local currency).",
        "bank_statements": "Bank statement lines (signed cents) with free-text reference and description.",
    },
    "marts": {
        "dim_date": "Calendar, one row per day; month-end rows are the keys for monthly facts.",
        "dim_entity": "Entities with currency and country.",
        "dim_account": "Accounts with statement line grouping and P&L flag.",
        "dim_cost_center": "Cost centres.",
        "dim_customer": "Customers with lifetime invoicing.",
        "fct_gl": "Ledger lines from BALANCED journals only, natural-sign amounts in local currency and EUR.",
        "fct_journal_exceptions": "Quarantined journals whose debits differ from credits; excluded from all reports.",
        "fct_trial_balance": "Entity x account x month, dense grid, with activity, cumulative balance and EUR translation.",
        "fct_budget_variance": "Budget vs actual by entity/account/cost centre/month, with operational and FX variance that sum exactly to the total.",
        "fct_variance_alerts": "3- and 6-month rolling variance with a robust (median/MAD) z-score and alert flag.",
        "fct_ar_aging": "Receivables aging snapshot at every month-end by entity, customer and bucket.",
        "fct_dso": "Days sales outstanding per entity-month, with EUR columns for weighted group DSO.",
        "fct_bank_recon_matches": "Matched bank-ledger pairs with tier, score and a review flag (Python-built).",
        "fct_bank_recon_unmatched": "Unmatched ledger and bank items with a reason category (Python-built).",
        "fct_bank_recon_summary": "Entity x month match rates and unmatched value (Python-built).",
        "fct_bank_recon_statement": "Bank-to-ledger reconciliation statement per entity; unexplained_lc must be 0 (Python-built).",
        "fct_cash_forecast": "13-week collections forecast from the latest date (Python-built).",
        "fct_cash_forecast_backtest": "Forecast vs baseline vs actual from three past origins (Python-built).",
    },
}
UNITS = ("Amount columns: `*_cents` = integer cents; `*_lc` = local currency (decimal); `*_eur` = EUR. "
         "'Natural sign' = revenue, liabilities and equity credit-minus-debit; assets and expenses debit-minus-credit.")


def main(db="warehouse/finance.duckdb", out="docs/data_dictionary.md"):
    con = duckdb.connect(db, read_only=True)
    lines = ["# Data dictionary", "", "Generated from the live warehouse schema by `export/make_data_dictionary.py`.", "", UNITS, ""]
    for schema, tables in TABLES.items():
        lines += [f"## `{schema}` schema", ""]
        for t, desc in tables.items():
            n = con.execute(f"select count(*) from {schema}.{t}").fetchone()[0]
            cols = con.execute(f"describe {schema}.{t}").fetchall()
            lines += [f"### `{schema}.{t}`", "", f"{desc}  Rows: {n:,}.", "", "| Column | Type |", "|---|---|"]
            lines += [f"| `{c[0]}` | {c[1]} |" for c in cols] + [""]
    Path(out).write_text("\n".join(lines))
    print("wrote", out)


if __name__ == "__main__":
    main()
