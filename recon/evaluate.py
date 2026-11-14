"""Score the reconciliation engine against the generator's hidden ground truth."""
import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd


def evaluate(db="warehouse/finance.duckdb"):
    con = duckdb.connect(db, read_only=True)
    truth = con.execute("select bank_line_id, gl_line_id, category from truth.bank_pairs").df()
    pred = con.execute("select bank_line_id, gl_line_id, tier, match_type from marts.fct_bank_recon_matches").df()
    tk = set(zip(truth["bank_line_id"], truth["gl_line_id"]))
    pk = set(zip(pred["bank_line_id"], pred["gl_line_id"]))
    tp = len(tk & pk)
    out = dict(true_pairs=len(tk), predicted_pairs=len(pk), true_positive=tp,
               false_positive=len(pk - tk), false_negative=len(tk - pk),
               precision=tp / len(pk) if pk else 0.0, recall=tp / len(tk) if tk else 0.0)
    out["f1"] = 2 * out["precision"] * out["recall"] / (out["precision"] + out["recall"]) if tp else 0.0

    # recall by the kind of imperfection the generator injected
    t = truth.assign(hit=[(b, g) in pk for b, g in zip(truth["bank_line_id"], truth["gl_line_id"])])
    out["recall_by_category"] = {k: round(float(v), 4) for k, v in t.groupby("category")["hit"].mean().items()}
    out["pairs_by_category"] = {k: int(v) for k, v in t.groupby("category").size().items()}

    # precision by tier (which tiers can be trusted?)
    p = pred.assign(correct=[(b, g) in tk for b, g in zip(pred["bank_line_id"], pred["gl_line_id"])])
    out["precision_by_tier"] = {k: round(float(v), 4) for k, v in p.groupby("match_type")["correct"].mean().items()}
    out["pairs_by_tier"] = {k: int(v) for k, v in p.groupby("match_type").size().items()}

    # classification of the leftovers
    ug = con.execute("select line_id, category from marts.fct_bank_recon_unmatched where item_side = 'LEDGER'").df()
    ug["line_id"] = ug["line_id"].astype("int64")
    tg = con.execute("select gl_line_id, category as truth from truth.gl_only").df()
    j = ug.merge(tg, left_on="line_id", right_on="gl_line_id", how="left")
    j["truth"] = j["truth"].fillna("not_in_truth_gl_only")
    out["ledger_leftover_confusion"] = {f"{a} | truth={b}": int(n) for (a, b), n in j.groupby(["category", "truth"]).size().items()}
    ub = con.execute("select line_id, category from marts.fct_bank_recon_unmatched where item_side = 'BANK'").df()
    tb = con.execute("select bank_line_id, category as truth from truth.bank_only").df()
    k = ub.merge(tb, left_on="line_id", right_on="bank_line_id", how="left")
    k["truth"] = k["truth"].fillna("not_in_truth_bank_only")
    out["bank_leftover_confusion"] = {f"{a} | truth={b}": int(n) for (a, b), n in k.groupby(["category", "truth"]).size().items()}
    con.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    ap.add_argument("--json", default="docs/results/recon_evaluation.json")
    a = ap.parse_args()
    r = evaluate(a.db)
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(r, indent=2))
    print(json.dumps(r, indent=2))
