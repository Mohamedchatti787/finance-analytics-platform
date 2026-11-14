"""Generate docs/powerbi/validation.md from expected_kpis.csv so numbers and measure names stay in sync."""
import re
from pathlib import Path

import pandas as pd

# kpi_id -> (DAX measure to compare, how to set the report filters)
KPI_TO_MEASURE = {
    "rev_fy_total": ("Revenue", "Year = 2025"),
    "cogs_fy_total": ("COGS", "Year = 2025"),
    "gross_margin_pct_fy": ("Gross Margin %", "Year = 2025"),
    "opex_fy_total": ("Operating Expenses", "Year = 2025"),
    "operating_income_fy_total": ("Operating Income", "Year = 2025"),
    "ebitda_fy_total": ("EBITDA", "Year = 2025"),
    "budget_eur_fy_total_revenue": ("Budget Revenue", "Year = 2025"),
    "favourable_variance_fy_total": ("Favourable Variance (Profit)", "Year = 2025 (must also equal [Operating Income Variance])"),
    "favourable_operational_fy_total": ("Operational Variance (Profit)", "Year = 2025"),
    "favourable_fx_fy_total": ("FX Impact (Profit)", "Year = 2025"),
    "ar_balance_eur_total": ("AR Balance (EUR)", "any date in Dec 2025"),
    "ar_over_90_eur_total": ("AR Over 90 (EUR)", "any date in Dec 2025"),
    "ar_over_90_pct": ("AR Over 90 %", "any date in Dec 2025"),
    "unbalanced_journals": ("Journal Exceptions", "no filters"),
    "unbalanced_abs_difference_cents": ("Journal Exceptions Abs Difference (LC cents)", "no filters"),
    "bank_match_rate": ("Bank Match Rate", "no filters"),
    "ledger_match_rate": ("Ledger Match Rate", "no filters"),
    "review_queue_matches": ("Review Queue", "no filters"),
    "variance_alert_rows": ("Variance Alerts", "no filters"),
    "cash_forecast_13w_eur": ("Forecast Collections (EUR)", "no filters"),
    "backtest_wape_model": ("Backtest WAPE (Model)", "no filters"),
    "backtest_wape_baseline": ("Backtest WAPE (Baseline)", "no filters"),
}
for e in ["E01", "E02", "E03", "E04", "E05"]:
    KPI_TO_MEASURE[f"rev_fy_{e}"] = ("Revenue", f"Year = 2025 and entity {e}")
    KPI_TO_MEASURE[f"dso_{e}"] = ("DSO (days)", f"any date in Dec 2025 and entity {e}")


def fmt(v):
    if abs(v) < 5:
        return f"{v:,.4f}"
    return f"{v:,.2f}"


def main(csv="docs/powerbi/expected_kpis.csv", out="docs/powerbi/validation.md"):
    df = pd.read_csv(csv)
    lines = ["# Validating the Power BI measures", "",
             "The DAX in `measures.dax` has **not been executed** in Power BI Desktop. Before trusting it, set the filters below",
             "and confirm each measure shows the expected value. The numbers come from `expected_kpis.csv`, which this",
             "repository regenerates on every pipeline run.", "",
             "* **Independent** rows were recomputed with pandas straight from the raw files, sharing no code or tables with dbt.",
             "  If your measure disagrees with one of these, suspect the DAX (or the relationships) first.",
             "* **Platform output** rows come from the warehouse's own engines (reconciliation, alerts, forecast). They check that",
             "  Power BI reads the marts correctly, not that the engines are right.", "",
             "Tip: put the *Measure* in a card visual, apply the filter in a slicer, and compare with *Expected*.", ""]
    for source, title in [("independent", "Independent checks"), ("platform output (not independent)", "Platform-output checks")]:
        sub = df[df["source"] == source]
        lines += [f"## {title}", "", "| KPI | Measure | Set filters to | Expected | Tolerance |", "|---|---|---|---:|---:|"]
        for r in sub.itertuples():
            m, ctx = KPI_TO_MEASURE[r.kpi_id]
            lines.append(f"| {r.description} | `[{m}]` | {ctx} | {fmt(r.expected_value)} | ±{r.tolerance:g} |")
        lines.append("")
    Path(out).write_text("\n".join(lines))
    print("wrote", out, f"({len(df)} KPIs)")


if __name__ == "__main__":
    main()
