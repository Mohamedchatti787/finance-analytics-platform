"""Integration tests against the BUILT warehouse: reconciliation quality, anomaly detection of the
planted problems, forecast accuracy, and agreement between the dbt marts and an independent
pandas recomputation of the headline KPIs."""
import json

import pandas as pd
import pytest

from conftest import ROOT
from export.expected_kpis import compute


# ------------------------------------------------------------------ reconciliation
def test_reconciliation_quality_against_ground_truth(full_scale):
    from recon.evaluate import evaluate
    ev = evaluate(str(ROOT / "warehouse" / "finance.duckdb"))
    assert ev["precision"] >= (0.995 if full_scale else 0.98)
    assert ev["recall"] >= (0.99 if full_scale else 0.95)
    assert ev["recall_by_category"]["exact"] == 1.0
    # every tier except the explicitly low-confidence 4c must be (near) perfectly precise
    for tier, prec in ev["precision_by_tier"].items():
        if not tier.startswith("T4c"):
            assert prec >= 0.995, (tier, prec)


def test_reconciliation_statements_foot_exactly(wh):
    worst = wh.execute("select max(abs(unexplained_lc)) from marts.fct_bank_recon_statement").fetchone()[0]
    assert worst < 1e-6


def test_each_ledger_line_is_matched_at_most_once(wh):
    assert wh.execute("select count(*) from (select gl_line_id from marts.fct_bank_recon_matches group by 1 having count(*) > 1)").fetchone()[0] == 0
    # a bank line may repeat only for many-to-one (tier 5) matches
    assert wh.execute("""select count(*) from (select bank_line_id from marts.fct_bank_recon_matches group by 1
                         having count(*) > 1 and min(tier) <> 5)""").fetchone()[0] == 0


def test_low_confidence_tier_is_flagged_for_review(wh):
    assert wh.execute("""select count(*) from marts.fct_bank_recon_matches
                         where (match_type like 'T4c%') <> review_required""").fetchone()[0] == 0


# ------------------------------------------------------------------ anomaly detection
def alerts(wh, entity, account, horizon=None, after=None):
    q = f"select period_end from marts.fct_variance_alerts where is_alert and entity_id='{entity}' and account_id={account}"
    if horizon:
        q += f" and horizon_months={horizon}"
    if after:
        q += f" and period_end >= date '{after}'"
    return wh.execute(q).fetchall()


def test_planted_shocks_are_detected(wh, full_scale):
    if not full_scale:
        pytest.skip("detection power is only meaningful at full data volume")
    assert alerts(wh, "E02", 6200, after="2024-11-30"), "S1 marketing overspend not detected"
    assert alerts(wh, "E02", 5010, horizon=6, after="2024-12-31"), "S3 hardware price rise not detected"
    assert alerts(wh, "E04", 6100, after="2025-02-28"), "S4 payroll overrun not detected"
    rev = [a for a in (4000, 4010, 4020) if alerts(wh, "E03", a, after="2025-04-30")]
    assert len(rev) >= 2, "S2 revenue shortfall detected on fewer than 2 of 3 revenue lines"


def test_alert_false_alarms_are_few(wh, full_scale):
    if not full_scale:
        pytest.skip("only meaningful at full data volume")
    related = {("E02", 6200), ("E02", 5010), ("E04", 6100), ("E04", 6110), ("E03", 4000), ("E03", 4010), ("E03", 4020)}
    flagged = {(e, a) for e, a in wh.execute("select distinct entity_id, account_id from marts.fct_variance_alerts where is_alert").fetchall()}
    assert len(flagged - related) <= 2, flagged - related


# ------------------------------------------------------------------ forecast
def test_forecast_beats_baseline_and_is_unbiased(full_scale):
    m = json.loads((ROOT / "docs" / "results" / "forecast_backtest.json").read_text())["pooled"]
    assert m["wape_model"] < m["wape_baseline"]
    if full_scale:
        assert m["wape_model"] < 0.20 and abs(m["volume_bias_model"]) < 0.05
        assert m["wape_improvement_vs_baseline"] > 0.5


# ------------------------------------------------------------------ independent KPI cross-check
def mart_values(wh):
    q = lambda s: float(wh.execute(s).fetchone()[0])
    tb = lambda where: q(f"""select coalesce(sum(t.activity_natural_eur),0) from marts.fct_trial_balance t
                             join marts.dim_account a using (account_id) where year(t.period_end) = 2025 and {where}""")
    v = {}
    rev, cogs, opex = tb("a.account_type='REVENUE'"), tb("a.account_type='COGS'"), tb("a.account_type='OPEX'")
    dep = tb("t.account_id = 6500")
    v.update(rev_fy_total=rev, cogs_fy_total=cogs, gross_margin_pct_fy=(rev - cogs) / rev, opex_fy_total=opex,
             operating_income_fy_total=rev - cogs - opex, ebitda_fy_total=rev - cogs - opex + dep)
    for e in ["E01", "E02", "E03", "E04", "E05"]:
        v[f"rev_fy_{e}"] = tb(f"a.account_type='REVENUE' and t.entity_id='{e}'")
    v["budget_eur_fy_total_revenue"] = q("""select sum(b.budget_eur) from marts.fct_budget_variance b join marts.dim_account a using (account_id)
                                            where a.account_type='REVENUE' and year(b.period_start)=2025""")
    v["favourable_variance_fy_total"] = q("select sum(favourable_variance_eur) from marts.fct_budget_variance where fiscal_year=2025")
    v["favourable_operational_fy_total"] = q("select sum(favourable_operational_eur) from marts.fct_budget_variance where fiscal_year=2025")
    v["favourable_fx_fy_total"] = q("select sum(favourable_fx_eur) from marts.fct_budget_variance where fiscal_year=2025")
    v["ar_balance_eur_total"] = q("select sum(balance_eur) from marts.fct_ar_aging where period_end = date '2025-12-31'")
    v["ar_over_90_eur_total"] = q("select sum(balance_eur) from marts.fct_ar_aging where period_end = date '2025-12-31' and aging_bucket = '4 90+'")
    v["ar_over_90_pct"] = v["ar_over_90_eur_total"] / v["ar_balance_eur_total"]
    for e in ["E01", "E02", "E03", "E04", "E05"]:
        v[f"dso_{e}"] = q(f"select dso_days from marts.fct_dso where entity_id='{e}' and period_end = date '2025-12-31'")
    v["unbalanced_journals"] = q("select count(*) from marts.fct_journal_exceptions")
    v["unbalanced_abs_difference_cents"] = round(q("select sum(abs_difference_lc) from marts.fct_journal_exceptions") * 100)
    return v


def test_dbt_marts_agree_with_independent_pandas_kpis(wh):
    expected = compute(str(ROOT / "data" / "raw"))      # no db => independent rows only
    got = mart_values(wh)
    assert set(expected["kpi_id"]) == set(got), set(expected["kpi_id"]) ^ set(got)
    bad = []
    for r in expected.itertuples():
        if abs(got[r.kpi_id] - r.expected_value) > max(r.tolerance, 1e-9):
            bad.append((r.kpi_id, got[r.kpi_id], r.expected_value))
    assert not bad, bad
