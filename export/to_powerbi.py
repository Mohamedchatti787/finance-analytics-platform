"""Export the marts to files Power BI Desktop can load directly (no ODBC driver needed)."""
import argparse
import json
from pathlib import Path

import duckdb

TABLES = [
    "dim_date", "dim_entity", "dim_account", "dim_cost_center", "dim_customer",
    "fct_gl", "fct_trial_balance", "fct_budget_variance", "fct_variance_alerts",
    "fct_ar_aging", "fct_dso", "fct_journal_exceptions",
    "fct_bank_recon_matches", "fct_bank_recon_unmatched", "fct_bank_recon_summary", "fct_bank_recon_statement",
    "fct_cash_forecast", "fct_cash_forecast_backtest",
]

# Sample mapping for row-level security: replace the e-mails with real user principal names.
RLS_ROWS = [
    ("group.finance@example.com", "ALL"), ("controller.fr@example.com", "E01"), ("controller.de@example.com", "E02"),
    ("controller.tn@example.com", "E03"), ("controller.us@example.com", "E04"), ("controller.us@example.com", "E05"),
]


def export(db="warehouse/finance.duckdb", out="export/powerbi_export", fmt="parquet"):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db, read_only=True)
    manifest = {}
    for t in TABLES:
        path = out / f"{t}.{fmt}"
        opts = "(FORMAT parquet, COMPRESSION zstd)" if fmt == "parquet" else "(FORMAT csv, HEADER)"
        con.execute(f"copy (select * from marts.{t}) to '{path.as_posix()}' {opts}")
        manifest[t] = dict(rows=con.execute(f"select count(*) from marts.{t}").fetchone()[0],
                           columns=[r[0] for r in con.execute(f"describe marts.{t}").fetchall()],
                           mb=round(path.stat().st_size / 1e6, 2))
    # RLS mapping table
    import pandas as pd
    rls = pd.DataFrame(RLS_ROWS, columns=["user_principal_name", "entity_id"])
    rls.to_parquet(out / "dim_user_entity.parquet", index=False) if fmt == "parquet" else rls.to_csv(out / "dim_user_entity.csv", index=False)
    manifest["dim_user_entity"] = dict(rows=len(rls), columns=list(rls.columns), mb=0.0)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    con.close()
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    ap.add_argument("--out", default="export/powerbi_export")
    ap.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    a = ap.parse_args()
    m = export(a.db, a.out, a.format)
    for k, v in m.items():
        print(f"  {k:28s} {v['rows']:>10,} rows  {v['mb']:>7.2f} MB")
