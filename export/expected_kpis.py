"""
Independent recomputation of headline KPIs - pandas straight from the RAW parquet
files. It deliberately shares no code, SQL or intermediate table with the dbt
project, so agreement between the two is real evidence, and the output file is
what you check your Power BI/DAX measures against.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def compute(raw="data/raw", year=2025, as_of="2025-12-31", db=None):
    raw = Path(raw)
    rd = lambda n: pd.read_parquet(raw / f"{n}.parquet")
    gl, acc, ent, fx, bfx = rd("gl_entries"), rd("accounts"), rd("entities"), rd("fx_rates"), rd("budget_fx_rates")
    bud, inv, pay = rd("budgets"), rd("invoices"), rd("payments")
    as_of = pd.Timestamp(as_of)

    # balanced journals only
    jt = gl.groupby("journal_id")[["debit_cents", "credit_cents"]].sum()
    bad = jt[jt["debit_cents"] != jt["credit_cents"]]
    ok = gl[~gl["journal_id"].isin(bad.index)].merge(acc, on="account_id").merge(ent[["entity_id", "currency"]], on="entity_id")
    ok["posting_date"] = pd.to_datetime(ok["posting_date"])
    ok["period_start"] = ok["posting_date"].dt.to_period("M").dt.to_timestamp()
    fx["period_start"] = pd.to_datetime(fx["period_start"])
    ok = ok.merge(fx, on=["currency", "period_start"])
    sign = np.where(ok["normal_balance"] == "C", 1, -1)
    ok["natural_lc"] = sign * (ok["credit_cents"] - ok["debit_cents"]) / 100.0
    ok["natural_eur"] = ok["natural_lc"] * ok["avg_rate_to_eur"]
    cy = ok[ok["posting_date"].dt.year == year]

    rows = []
    def add(kid, desc, ctx, val, tol=5.0, source="independent"):
        rows.append(dict(kpi_id=kid, description=desc, filter_context=ctx, expected_value=float(val), tolerance=tol, source=source))

    t = lambda g: cy[cy["account_type"] == g]["natural_eur"].sum()
    rev, cogs, opex = t("REVENUE"), t("COGS"), t("OPEX")
    dep = cy[cy["account_id"] == 6500]["natural_eur"].sum()
    add("rev_fy_total", "Revenue, EUR (monthly average rates)", f"FY{year}, all entities", rev)
    add("cogs_fy_total", "Cost of goods sold, EUR", f"FY{year}, all entities", cogs)
    add("gross_margin_pct_fy", "Gross margin %", f"FY{year}, all entities", (rev - cogs) / rev, 1e-5)
    add("opex_fy_total", "Operating expenses incl. depreciation, EUR", f"FY{year}, all entities", opex)
    add("operating_income_fy_total", "Operating income, EUR", f"FY{year}, all entities", rev - cogs - opex)
    add("ebitda_fy_total", "EBITDA (operating income + depreciation), EUR", f"FY{year}, all entities", rev - cogs - opex + dep)
    for e, g in cy.groupby("entity_id"):
        add(f"rev_fy_{e}", "Revenue, EUR", f"FY{year}, entity {e}", g[g["account_type"] == "REVENUE"]["natural_eur"].sum())

    # budget variance (FY), operational vs FX
    pl = cy[cy["statement"] == "PL"]
    act_lc = pl.groupby(["entity_id", "period_start", "account_id", "cost_center_id"])["natural_lc"].sum().rename("actual_lc").reset_index()
    bl = bud.copy(); bl["period_start"] = pd.to_datetime(bl["period_start"]); bl = bl[bl["period_start"].dt.year == year]
    bl["budget_lc"] = bl["budget_cents"] / 100.0
    m = bl.merge(act_lc, on=["entity_id", "period_start", "account_id", "cost_center_id"], how="outer").fillna({"actual_lc": 0.0, "budget_lc": 0.0})
    m = m.merge(acc[["account_id", "account_type"]], on="account_id").merge(ent[["entity_id", "currency"]], on="entity_id") \
         .merge(fx, on=["currency", "period_start"])
    m["fy"] = year
    m = m.merge(bfx.rename(columns={"fiscal_year": "fy"}), on=["fy", "currency"])
    m["fav"] = np.where(m["account_type"] == "REVENUE", 1, -1)
    m["var_total"] = m["actual_lc"] * m["avg_rate_to_eur"] - m["budget_lc"] * m["budget_rate_to_eur"]
    m["var_oper"] = (m["actual_lc"] - m["budget_lc"]) * m["budget_rate_to_eur"]
    m["var_fx"] = m["actual_lc"] * (m["avg_rate_to_eur"] - m["budget_rate_to_eur"])
    add("budget_eur_fy_total_revenue", "Budgeted revenue, EUR (budget rates)", f"FY{year}, all entities",
        (m[m["account_type"] == "REVENUE"]["budget_lc"] * m[m["account_type"] == "REVENUE"]["budget_rate_to_eur"]).sum())
    add("favourable_variance_fy_total", "Favourable (+) / unfavourable (-) P&L variance vs budget, EUR", f"FY{year}, all entities", (m["var_total"] * m["fav"]).sum())
    add("favourable_operational_fy_total", "Operational part of the profit variance, EUR (+ = good for profit)", f"FY{year}, all entities", (m["var_oper"] * m["fav"]).sum())
    add("favourable_fx_fy_total", "FX part of the profit variance, EUR (+ = good for profit)", f"FY{year}, all entities", (m["var_fx"] * m["fav"]).sum())

    # receivables at as_of
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"]); inv["due_date"] = pd.to_datetime(inv["due_date"])
    pay["payment_date"] = pd.to_datetime(pay["payment_date"])
    paid = pay[pay["payment_date"] <= as_of].groupby("invoice_id")["amount_cents"].sum()
    o = inv[inv["invoice_date"] <= as_of].copy()
    o["bal_lc"] = (o["gross_cents"] - o["invoice_id"].map(paid).fillna(0)) / 100.0
    o = o[o["bal_lc"] > 0.004]
    o["days_past_due"] = (as_of - o["due_date"]).dt.days
    cur = ent.set_index("entity_id")["currency"]
    close = fx[fx["period_start"] == as_of.to_period("M").to_timestamp()].set_index("currency")["close_rate_to_eur"]
    o["bal_eur"] = o["bal_lc"] * o["entity_id"].map(cur).map(close)
    add("ar_balance_eur_total", "Open receivables, EUR (month-end rate)", f"{as_of.date()}, all entities", o["bal_eur"].sum())
    add("ar_over_90_eur_total", "Receivables more than 90 days past due, EUR", f"{as_of.date()}, all entities", o[o["days_past_due"] > 90]["bal_eur"].sum())
    add("ar_over_90_pct", "Share of receivables more than 90 days past due", f"{as_of.date()}, all entities",
        o[o["days_past_due"] > 90]["bal_eur"].sum() / o["bal_eur"].sum(), 1e-5)
    for e, g in o.groupby("entity_id"):
        win = inv[(inv["entity_id"] == e) & (inv["invoice_date"] > as_of - pd.Timedelta(days=90)) & (inv["invoice_date"] <= as_of)]["gross_cents"].sum() / 100.0
        add(f"dso_{e}", "Days sales outstanding (90-day window)", f"{as_of.date()}, entity {e}", round(g["bal_lc"].sum() / win * 90, 1), 0.06)

    add("unbalanced_journals", "Journals quarantined for debits <> credits", "all periods", len(bad), 0)
    add("unbalanced_abs_difference_cents", "Total absolute out-of-balance amount, cents", "all periods", float((bad["debit_cents"] - bad["credit_cents"]).abs().sum()), 0)

    # ---- second section: results of the platform's own engines. These are NOT independent
    # (they come from the same warehouse) - they let you check your DAX on recon/forecast numbers.
    if db and Path(db).exists():
        import duckdb
        con = duckdb.connect(str(db), read_only=True)
        src = "platform output (not independent)"
        r = con.execute("select sum(bank_lines), sum(bank_matched_lines), sum(gl_cash_lines), sum(gl_matched_lines) from marts.fct_bank_recon_summary").fetchone()
        add("bank_match_rate", "Share of bank lines matched to the ledger", "all periods, all entities", r[1] / r[0], 1e-6, src)
        add("ledger_match_rate", "Share of ledger cash lines matched to the bank", "all periods, all entities", r[3] / r[2], 1e-6, src)
        add("review_queue_matches", "Matches flagged for human review (tier 4c)", "all periods", con.execute("select count(*) from marts.fct_bank_recon_matches where review_required").fetchone()[0], 0, src)
        add("variance_alert_rows", "Rows flagged is_alert in the variance alert mart", "all periods", con.execute("select count(*) from marts.fct_variance_alerts where is_alert").fetchone()[0], 0, src)
        add("cash_forecast_13w_eur", "Forecast collections over the next 13 weeks, EUR", f"origin {as_of.date()}, all entities", con.execute("select sum(predicted_eur) from marts.fct_cash_forecast").fetchone()[0], 5.0, src)
        b = con.execute("select sum(abs(predicted_eur - actual_eur)), sum(abs(baseline_eur - actual_eur)), sum(actual_eur) from marts.fct_cash_forecast_backtest").fetchone()
        add("backtest_wape_model", "Weekly forecast error (WAPE), model", "all backtest origins, all entities", b[0] / b[2], 1e-6, src)
        add("backtest_wape_baseline", "Weekly forecast error (WAPE), naive baseline", "all backtest origins, all entities", b[1] / b[2], 1e-6, src)
        con.close()
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="docs/powerbi/expected_kpis.csv")
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    a = ap.parse_args()
    df = compute(a.raw, db=a.db)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(df.to_string(index=False, float_format=lambda x: f"{x:,.4f}" if abs(x) < 10 else f"{x:,.2f}"))
