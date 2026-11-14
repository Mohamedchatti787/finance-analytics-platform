"""
13-week cash COLLECTIONS forecast from the open receivables, with a backtest.

Method (deliberately simple and explainable - a finance team can audit it):
  - for every customer, look at how many days after the due date their recent
    invoices were actually paid (median of the last 8 fully-paid invoices;
    fall back to the entity median for customers with too little history)
  - predicted payment date = due date + that typical delay (never in the past)
  - predicted amount = open balance x entity collectability (share of old
    invoice value that eventually gets collected)
Baseline to beat: "everyone pays on the due date".
Backtest: forecast from three past origins and compare with what was really collected.
"""
import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HORIZON_WEEKS = 13
HISTORY_N = 8
RECOVERY_BUCKETS = [0, 1, 31, 61, 91, 181]
MIN_HISTORY = 3


def _load(con):
    inv = con.execute("select invoice_id, entity_id, customer_id, invoice_date, due_date, gross_lc from staging.stg_invoices").df()
    pay = con.execute("select invoice_id, payment_date, amount_lc from staging.stg_payments").df()
    for c in ["invoice_date", "due_date"]:
        inv[c] = pd.to_datetime(inv[c])
    pay["payment_date"] = pd.to_datetime(pay["payment_date"])
    inv["gross_lc"] = inv["gross_lc"].astype(float)
    pay["amount_lc"] = pay["amount_lc"].astype(float)
    return inv, pay


def forecast_from(inv, pay, origin, horizon_weeks=HORIZON_WEEKS):
    """Return (per-invoice forecast frame, open-invoice frame) as of `origin`."""
    origin = pd.Timestamp(origin)
    p = pay[pay["payment_date"] <= origin]
    paid = p.groupby("invoice_id").agg(paid_lc=("amount_lc", "sum"), last_pay=("payment_date", "max")).reset_index()
    d = inv[inv["invoice_date"] <= origin].merge(paid, on="invoice_id", how="left")
    d["paid_lc"] = d["paid_lc"].fillna(0.0)
    d["balance_lc"] = d["gross_lc"] - d["paid_lc"]
    settled = d[d["balance_lc"] <= 0.004].copy()
    settled["days_late"] = (settled["last_pay"] - settled["due_date"]).dt.days
    # recent behaviour per customer
    settled = settled.sort_values("last_pay")
    recent = settled.groupby("customer_id").tail(HISTORY_N)
    cust = recent.groupby("customer_id")["days_late"].agg(["median", "count"]).reset_index()
    cust = cust[cust["count"] >= MIN_HISTORY].rename(columns={"median": "cust_delay"})[["customer_id", "cust_delay"]]
    ent_recent = settled[settled["last_pay"] > origin - pd.Timedelta(days=120)]
    ent_delay = ent_recent.groupby("entity_id")["days_late"].median().rename("entity_delay").reset_index()
    # Recovery rate by lateness bucket ("roll rates"). Of the old invoices that were STILL
    # unpaid `b` days after their due date, what share did eventually get paid? An invoice
    # that is 90 days late is a very different proposition from one not yet due, and the
    # open book is enriched with the dead ones, so one entity-wide ratio overstates cash.
    # Built only from invoices that fell due >250 days before `origin`, using payments
    # received up to `origin` (no look-ahead).
    old = d[d["due_date"] < origin - pd.Timedelta(days=250)].copy()
    old["settled_by"] = old["last_pay"].where(old["balance_lc"] <= 0.004)
    old["ever_paid"] = old["balance_lc"] <= 0.004
    rec_rows = []
    for ent, g in old.groupby("entity_id"):
        for b in RECOVERY_BUCKETS:
            at_risk = g[g["settled_by"].isna() | (g["settled_by"] > g["due_date"] + pd.Timedelta(days=b))]
            rec_rows.append(dict(entity_id=ent, bucket_from=b, recovery=float(at_risk["ever_paid"].mean()) if len(at_risk) >= 20 else np.nan))
    recovery = pd.DataFrame(rec_rows)
    # fall back to the all-entity rate where an entity has too few at-risk invoices
    pooled_rec = recovery.groupby("bucket_from")["recovery"].mean()
    recovery["recovery"] = recovery.apply(lambda r: pooled_rec[r["bucket_from"]] if pd.isna(r["recovery"]) else r["recovery"], axis=1)
    rec_lookup = {(r.entity_id, r.bucket_from): r.recovery for r in recovery.itertuples()}

    open_ = d[d["balance_lc"] > 0.004].copy()
    open_["overdue_now"] = (origin - open_["due_date"]).dt.days.clip(lower=0)

    # Delay pools. Customer pool = their recent settled invoices. Entity pool = invoices
    # that fell due long enough ago to be fully settled (an unbiased sample: it is not
    # missing the slow payers who are still open today).
    cust_pool = {k: np.sort(v.values) for k, v in recent.groupby("customer_id")["days_late"]}
    matured = settled[settled["due_date"] < origin - pd.Timedelta(days=150)]
    ent_pool = {k: np.sort(v.values) for k, v in matured.groupby("entity_id")["days_late"]}

    def expected_delay(row):
        # Condition on lateness so far: an invoice already 40 days overdue is not
        # forecast from customers who usually pay 5 days late.
        L = row["overdue_now"]
        cp = cust_pool.get(row["customer_id"])
        if cp is not None and len(cp) >= MIN_HISTORY:
            tail = cp[cp > L] if L > 0 else cp
            if len(tail) >= MIN_HISTORY:
                return float(np.median(tail))
        ep = ent_pool.get(row["entity_id"])
        if ep is not None:
            tail = ep[ep > L] if L > 0 else ep
            if len(tail) >= 5:
                return float(np.median(tail))
        return float(L + 14)

    open_["delay_used"] = open_.apply(expected_delay, axis=1)
    open_["pred_date"] = np.maximum(open_["due_date"] + pd.to_timedelta(open_["delay_used"].round(), unit="D"),
                                    origin + pd.Timedelta(days=1))
    def bucket_from(L):
        return max([b for b in RECOVERY_BUCKETS if b <= max(L, 0)] or [0]) if L >= 1 else 0
    open_["recovery"] = [rec_lookup.get((e, bucket_from(L)), 1.0) for e, L in zip(open_["entity_id"], open_["overdue_now"])]
    open_["pred_amount_lc"] = open_["balance_lc"] * open_["recovery"]
    open_["base_date"] = np.maximum(open_["due_date"], origin + pd.Timedelta(days=1))
    for col, out in [("pred_date", "pred_week"), ("base_date", "base_week")]:
        open_[out] = ((open_[col] - origin).dt.days - 1) // 7 + 1
    return open_, origin


def weekly(open_, origin, pay, horizon_weeks=HORIZON_WEEKS):
    weeks = pd.DataFrame({"week_no": range(1, horizon_weeks + 1)})
    ent = sorted(open_["entity_id"].unique())
    grid = pd.MultiIndex.from_product([ent, weeks["week_no"]], names=["entity_id", "week_no"]).to_frame(index=False)
    pr = open_[open_["pred_week"].between(1, horizon_weeks)].groupby(["entity_id", "pred_week"])["pred_amount_lc"].sum().rename("predicted_lc").reset_index().rename(columns={"pred_week": "week_no"})
    bs = open_[open_["base_week"].between(1, horizon_weeks)].groupby(["entity_id", "base_week"])["balance_lc"].sum().rename("baseline_lc").reset_index().rename(columns={"base_week": "week_no"})
    # actuals: money really received on the invoices that were open at the origin
    pp = pay.merge(open_[["invoice_id", "entity_id"]], on="invoice_id")
    pp = pp[(pp["payment_date"] > origin) & (pp["payment_date"] <= origin + pd.Timedelta(days=7 * horizon_weeks))]
    pp["week_no"] = ((pp["payment_date"] - origin).dt.days - 1) // 7 + 1
    ac = pp.groupby(["entity_id", "week_no"])["amount_lc"].sum().rename("actual_lc").reset_index()
    out = grid.merge(pr, how="left").merge(bs, how="left").merge(ac, how="left").fillna(0.0)
    out["week_start"] = origin + pd.to_timedelta((out["week_no"] - 1) * 7 + 1, unit="D")
    return out


def run(db="warehouse/finance.duckdb", origins=("2025-03-31", "2025-06-30", "2025-09-30"), final_origin="2025-12-31"):
    con = duckdb.connect(db)
    inv, pay = _load(con)
    fx = con.execute("select e.entity_id, f.period_end, f.avg_rate_to_eur from staging.stg_entities e join staging.stg_fx_rates f on f.currency = e.currency").df()
    fx["period_end"] = pd.to_datetime(fx["period_end"])

    back, metrics = [], {"origins": {}, "pooled": {}}
    for o in origins:
        open_, ts = forecast_from(inv, pay, o)
        w = weekly(open_, ts, pay)
        w["origin"] = ts
        back.append(w)
    bt = pd.concat(back, ignore_index=True)
    bt["origin_month_end"] = bt["origin"] + pd.offsets.MonthEnd(0)
    bt = bt.merge(fx.rename(columns={"period_end": "origin_month_end"}), on=["entity_id", "origin_month_end"], how="left")
    for col in ["predicted", "baseline", "actual"]:
        bt[f"{col}_eur"] = bt[f"{col}_lc"] * bt["avg_rate_to_eur"]

    def wape(df, p, a):
        return float((df[p] - df[a]).abs().sum() / df[a].sum())

    def bias(df, p, a):
        return float(df[p].sum() / df[a].sum() - 1)

    for o, g in bt.groupby("origin"):
        metrics["origins"][str(o.date())] = dict(
            wape_model=wape(g, "predicted_eur", "actual_eur"), wape_baseline=wape(g, "baseline_eur", "actual_eur"),
            volume_bias_model=bias(g, "predicted_eur", "actual_eur"), volume_bias_baseline=bias(g, "baseline_eur", "actual_eur"),
            actual_collected_eur=float(g["actual_eur"].sum()))
    metrics["pooled"] = dict(
        wape_model=wape(bt, "predicted_eur", "actual_eur"), wape_baseline=wape(bt, "baseline_eur", "actual_eur"),
        volume_bias_model=bias(bt, "predicted_eur", "actual_eur"), volume_bias_baseline=bias(bt, "baseline_eur", "actual_eur"))
    metrics["pooled"]["wape_improvement_vs_baseline"] = 1 - metrics["pooled"]["wape_model"] / metrics["pooled"]["wape_baseline"]
    metrics["by_entity_wape"] = {e: dict(model=wape(g, "predicted_lc", "actual_lc"), baseline=wape(g, "baseline_lc", "actual_lc"))
                                 for e, g in bt.groupby("entity_id")}

    # production forecast from the last available date (no actuals exist yet)
    open_, ts = forecast_from(inv, pay, final_origin)
    f = weekly(open_, ts, pay).drop(columns=["actual_lc"])
    f["origin"] = ts
    f["origin_month_end"] = ts + pd.offsets.MonthEnd(0)
    f = f.merge(fx.rename(columns={"period_end": "origin_month_end"}), on=["entity_id", "origin_month_end"], how="left")
    f["predicted_eur"] = f["predicted_lc"] * f["avg_rate_to_eur"]
    f["week_end"] = f["week_start"] + pd.Timedelta(days=6)

    out_bt = bt[["origin", "entity_id", "week_no", "week_start", "predicted_lc", "baseline_lc", "actual_lc", "predicted_eur", "baseline_eur", "actual_eur"]]
    out_f = f[["origin", "entity_id", "week_no", "week_start", "week_end", "predicted_lc", "predicted_eur"]]
    for name, df in [("fct_cash_forecast", out_f), ("fct_cash_forecast_backtest", out_bt)]:
        con.register("tmp_df", df)
        con.execute(f"create or replace table marts.{name} as select * from tmp_df")
        con.unregister("tmp_df")
    con.close()
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    ap.add_argument("--json", default="docs/results/forecast_backtest.json")
    a = ap.parse_args()
    m = run(a.db)
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(m, indent=2))
    print(json.dumps(m, indent=2))
