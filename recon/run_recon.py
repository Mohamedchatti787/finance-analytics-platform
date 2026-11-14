"""Run the reconciliation engine against the warehouse and write results back as marts."""
import argparse

import duckdb
import numpy as np
import pandas as pd

from recon.engine import reconcile


def run(db="warehouse/finance.duckdb", as_of="2025-12-31", verbose=True):
    con = duckdb.connect(db)
    gl = con.execute("""
        select gl_line_id, entity_id, posting_date, cast(round(net_lc * 100) as bigint) as amount_c, reference
        from marts.fct_gl where account_id = 1010""").df()
    bank = con.execute("""
        select bank_line_id, entity_id, value_date, cast(round(amount_lc * 100) as bigint) as amount_c,
               bank_reference, description
        from staging.stg_bank_statements""").df()
    gl_all, bank_all = gl.copy(), bank.copy()
    res = reconcile(gl, bank, as_of)

    # ---- matches with both sides' facts
    m = res.matches.merge(bank_all[["bank_line_id", "value_date", "amount_c"]].rename(columns={"amount_c": "bank_amount_c"}), on="bank_line_id") \
                   .merge(gl_all[["gl_line_id", "posting_date", "amount_c"]].rename(columns={"amount_c": "gl_amount_c"}), on="gl_line_id")
    m["bank_amount_lc"] = m["bank_amount_c"] / 100.0
    m["gl_amount_lc"] = m["gl_amount_c"] / 100.0
    matches = m.drop(columns=["bank_amount_c", "gl_amount_c"])
    # lowest-confidence tier (no usable reference): queue for human review
    matches["review_required"] = matches["match_type"].str.startswith("T4c")

    # ---- unmatched (both sides in one tidy table)
    ug = res.unmatched_gl.assign(item_side="LEDGER", line_id=lambda d: d["gl_line_id"].astype(str),
                                 item_date=lambda d: d["posting_date"], reference_text=lambda d: d["reference"],
                                 description=None)
    ub = res.unmatched_bank.assign(item_side="BANK", line_id=lambda d: d["bank_line_id"],
                                   item_date=lambda d: d["value_date"], reference_text=lambda d: d["bank_reference"])
    cols = ["item_side", "line_id", "entity_id", "item_date", "amount_c", "reference_text", "description", "category", "age_days"]
    unmatched = pd.concat([ug[cols], ub[cols]], ignore_index=True)
    unmatched["amount_lc"] = unmatched["amount_c"] / 100.0
    unmatched = unmatched.drop(columns=["amount_c"])

    # ---- monthly summary
    matched_bank = set(res.matches["bank_line_id"]); matched_gl = set(res.matches["gl_line_id"])
    g = gl_all.assign(period_end=lambda d: pd.to_datetime(d["posting_date"]) + pd.offsets.MonthEnd(0),
                      matched=lambda d: d["gl_line_id"].isin(matched_gl))
    b = bank_all.assign(period_end=lambda d: pd.to_datetime(d["value_date"]) + pd.offsets.MonthEnd(0),
                        matched=lambda d: d["bank_line_id"].isin(matched_bank))
    gs = g.groupby(["entity_id", "period_end"]).agg(gl_cash_lines=("gl_line_id", "size"), gl_matched_lines=("matched", "sum")).reset_index()
    bs = b.groupby(["entity_id", "period_end"]).agg(bank_lines=("bank_line_id", "size"), bank_matched_lines=("matched", "sum")).reset_index()
    bv = b[~b["matched"]].assign(v=lambda d: d["amount_c"].abs()).groupby(["entity_id", "period_end"])["v"].sum().rename("unmatched_bank_value_lc").reset_index()
    gv = g[~g["matched"]].assign(v=lambda d: d["amount_c"].abs()).groupby(["entity_id", "period_end"])["v"].sum().rename("unmatched_gl_value_lc").reset_index()
    summary = gs.merge(bs, on=["entity_id", "period_end"], how="outer").merge(bv, on=["entity_id", "period_end"], how="left") \
                .merge(gv, on=["entity_id", "period_end"], how="left").fillna(0)
    summary["gl_match_rate"] = summary["gl_matched_lines"] / summary["gl_cash_lines"].replace(0, np.nan)
    summary["bank_match_rate"] = summary["bank_matched_lines"] / summary["bank_lines"].replace(0, np.nan)
    for c in ["unmatched_bank_value_lc", "unmatched_gl_value_lc"]:
        summary[c] = summary[c] / 100.0
    summary["period_start"] = summary["period_end"] - pd.offsets.MonthBegin(1)
    # EUR equivalents (monthly average rate) so values can be summed across entities
    fx = con.execute("""select e.entity_id, f.period_end, f.avg_rate_to_eur from staging.stg_entities e
                        join staging.stg_fx_rates f on f.currency = e.currency""").df()
    fx["period_end"] = pd.to_datetime(fx["period_end"])
    summary = summary.merge(fx, on=["entity_id", "period_end"], how="left")
    for c in ["unmatched_bank_value", "unmatched_gl_value"]:
        summary[f"{c}_eur"] = summary[f"{c}_lc"] * summary["avg_rate_to_eur"].astype(float)
    summary = summary.drop(columns=["avg_rate_to_eur"])

    # ---- bank-to-ledger reconciliation statement per entity at as_of (must foot exactly)
    rows = []
    for ent, gg in gl_all.groupby("entity_id"):
        bb = bank_all[bank_all["entity_id"] == ent]
        mb = bb[bb["bank_line_id"].isin(matched_bank)]["amount_c"].sum()
        mg = gg[gg["gl_line_id"].isin(matched_gl)]["amount_c"].sum()
        ugl = res.unmatched_gl[res.unmatched_gl["entity_id"] == ent]
        ubk = res.unmatched_bank[res.unmatched_bank["entity_id"] == ent]
        item = lambda df, cat: int(df[df["category"] == cat]["amount_c"].sum())
        bank_total, gl_total = int(bb["amount_c"].sum()), int(gg["amount_c"].sum())
        r = dict(entity_id=ent, as_of=pd.Timestamp(as_of).date(),
                 bank_balance_c=bank_total, ledger_balance_c=gl_total,
                 difference_c=bank_total - gl_total,
                 matched_amount_differences_c=int(mb - mg),
                 bank_charges_not_booked_c=item(ubk, "Bank charge - not booked"),
                 interest_not_booked_c=item(ubk, "Interest - not booked"),
                 unidentified_bank_items_c=item(ubk, "Unidentified bank item"),
                 ledger_outstanding_timing_c=-item(ugl, "Outstanding (timing)"),
                 ledger_unmatched_investigate_c=-item(ugl, "Unmatched - investigate"))
        explained = sum(v for k, v in r.items() if k in (
            "matched_amount_differences_c", "bank_charges_not_booked_c", "interest_not_booked_c",
            "unidentified_bank_items_c", "ledger_outstanding_timing_c", "ledger_unmatched_investigate_c"))
        r["unexplained_c"] = r["difference_c"] - explained
        rows.append(r)
    statement = pd.DataFrame(rows)
    for c in [c for c in statement.columns if c.endswith("_c")]:
        statement[c[:-2] + "_lc"] = statement[c] / 100.0   # rename the SUFFIX only ("bank_charges_..." must stay intact)
    statement = statement.drop(columns=[c for c in statement.columns if c.endswith("_c")])

    for name, df in [("fct_bank_recon_matches", matches), ("fct_bank_recon_unmatched", unmatched),
                     ("fct_bank_recon_summary", summary), ("fct_bank_recon_statement", statement)]:
        con.register("tmp_df", df)
        con.execute(f"create or replace table marts.{name} as select * from tmp_df")
        con.unregister("tmp_df")
    con.close()
    if verbose:
        n_b, n_g = len(bank_all), len(gl_all)
        print(f"bank lines {n_b:,} | ledger cash lines {n_g:,}")
        print(f"bank matched {len(matched_bank):,} ({len(matched_bank)/n_b:.2%}) | ledger matched {len(matched_gl):,} ({len(matched_gl)/n_g:.2%})")
        print(res.matches.groupby("match_type").agg(pairs=("gl_line_id", "size")).to_string())
        print("unmatched ledger:", res.unmatched_gl["category"].value_counts().to_dict())
        print("unmatched bank  :", res.unmatched_bank["category"].value_counts().to_dict())
        print("max |unexplained| in statements (LC):", float(statement["unexplained_lc"].abs().max()))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    ap.add_argument("--as-of", default="2025-12-31")
    a = ap.parse_args()
    run(a.db, a.as_of)
