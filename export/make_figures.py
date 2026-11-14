"""Static preview charts rendered with matplotlib from the marts.
These are PYTHON previews of what the data shows - not Power BI visuals."""
import json
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OUT = Path("docs/figures")
C = dict(actual="#1f6feb", budget="#9aa4b2", bad="#d1495b", good="#2a9d8f", warn="#f4a261")


def main(db="warehouse/finance.duckdb"):
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db, read_only=True)

    # 1. a planted shock the platform surfaces: DE marketing overspend
    d = con.execute("""select period_start, sum(actual_eur) a, sum(budget_eur) b from marts.fct_budget_variance
                       where entity_id='E02' and account_id=6200 group by 1 order by 1""").df()
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(d["period_start"], d["b"].astype(float) / 1e3, color=C["budget"], lw=2, label="Budget")
    ax.plot(d["period_start"], d["a"].astype(float) / 1e3, color=C["actual"], lw=2, label="Actual")
    ax.axvspan(pd.Timestamp("2024-10-01"), pd.Timestamp("2024-12-31"), color=C["bad"], alpha=.12, label="Q4-2024 overspend")
    ax.set_title("Meridian GmbH (E02): marketing actual vs budget, EUR thousand"); ax.legend(frameon=False); ax.set_ylabel("EUR k")
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); fig.savefig(OUT / "01_marketing_overspend.png", dpi=140); plt.close(fig)

    # 2. receivables aging trend (EUR)
    a = con.execute("""select period_end, aging_bucket, sum(balance_eur) v from marts.fct_ar_aging group by 1,2 order by 1,2""").df()
    p = a.pivot(index="period_end", columns="aging_bucket", values="v").fillna(0).astype(float) / 1e6
    fig, ax = plt.subplots(figsize=(9, 3.8))
    cols = ["#2a9d8f", "#8ab17d", "#e9c46a", "#f4a261", "#d1495b"]
    ax.stackplot(p.index, [p[c] for c in p.columns], labels=[c[2:] + (" days late" if c[0] != "0" else "") for c in p.columns], colors=cols)
    ax.set_title("Open receivables by aging bucket, all entities, EUR million"); ax.legend(frameon=False, ncol=5, loc="upper left", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); fig.savefig(OUT / "02_receivables_aging.png", dpi=140); plt.close(fig)

    # 3. reconciliation engine: volume and precision by matching tier
    ev = json.loads(Path("docs/results/recon_evaluation.json").read_text())
    short = {"T1": "T1  amount + reference exact", "T2": "T2  amount exact, reference similar",
             "T3": "T3  amount exact, unique pairing", "T4a": "T4a amount within tolerance, exact ref",
             "T4b": "T4b amount within tolerance, similar ref", "T4c": "T4c amount within tolerance, no ref (review)",
             "T5": "T5  batched deposit (many-to-one)"}
    tiers = list(ev["pairs_by_tier"].keys())
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.barh([short[t.split(" ")[0]] for t in tiers], [ev["pairs_by_tier"][t] for t in tiers], color=C["actual"])
    for i, t in enumerate(tiers):
        ax.text(ev["pairs_by_tier"][t], i, f"  precision {ev['precision_by_tier'][t]:.1%}", va="center", fontsize=8)
    ax.set_xscale("log"); ax.invert_yaxis(); ax.set_xlim(100, 2e6); ax.set_xlabel("matched pairs (log scale)")
    ax.set_title(f"Bank reconciliation by matching tier\noverall precision {ev['precision']:.2%} | recall {ev['recall']:.2%} (scored against hidden ground truth)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); fig.savefig(OUT / "03_reconciliation_tiers.png", dpi=140); plt.close(fig)

    # 4. collections forecast backtest (origin 2025-06-30, all entities in EUR)
    f = con.execute("""select week_no, sum(predicted_eur) p, sum(baseline_eur) b, sum(actual_eur) a
                       from marts.fct_cash_forecast_backtest where origin = date '2025-06-30' group by 1 order by 1""").df()
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(f["week_no"], f["a"].astype(float) / 1e6, color="black", lw=2.5, label="Actual collected")
    ax.plot(f["week_no"], f["p"].astype(float) / 1e6, color=C["good"], lw=2, label="Model forecast")
    ax.plot(f["week_no"], f["b"].astype(float) / 1e6, color=C["warn"], lw=2, ls="--", label="Baseline: everyone pays on due date")
    m = json.loads(Path("docs/results/forecast_backtest.json").read_text())["origins"]["2025-06-30"]
    ax.set_title(f"13-week collections backtest from 30-Jun-2025 (EUR million per week)\nweekly error (WAPE): model {m['wape_model']:.0%} vs baseline {m['wape_baseline']:.0%}", fontsize=10)
    ax.set_xlabel("week after forecast date"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "04_collections_backtest.png", dpi=140); plt.close(fig)
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
