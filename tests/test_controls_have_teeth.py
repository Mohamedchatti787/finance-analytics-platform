"""
A control that can never fail is worthless. Each test corrupts a throwaway COPY of the
warehouse in a specific, realistic way and asserts that the matching dbt control fires
(or, for the journal quarantine, that it contains the damage).
"""
import shutil
from pathlib import Path
import subprocess
from decimal import Decimal

import duckdb
import pytest

from conftest import ROOT, DB

MUT = ROOT / "warehouse" / "mutation.duckdb"


def query_mut(sql):
    """Open/close per query so a failed assertion can never leave the file locked."""
    con = duckdb.connect(str(MUT), read_only=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def mutate():
    if not DB.exists():
        pytest.skip("warehouse not built - run: python run_pipeline.py")
    shutil.copy(DB, MUT)
    con = duckdb.connect(str(MUT))
    yield con
    try:
        con.close()
    finally:
        MUT.unlink(missing_ok=True)
        Path(str(MUT) + ".wal").unlink(missing_ok=True)


def dbt(*args):
    r = subprocess.run(["dbt", *args, "--profiles-dir", ".", "--target", "mutation"],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def failed(out, test):
    return any(test in line and "FAIL" in line for line in out.splitlines())


def test_dropping_a_payment_breaks_the_ar_to_gl_tie_out(mutate):
    pid = mutate.execute("select payment_id from raw.payments order by amount_cents desc limit 1").fetchone()[0]
    mutate.execute(f"delete from raw.payments where payment_id = '{pid}'")
    mutate.close()
    code, out = dbt("build", "--select", "fct_ar_aging", "assert_ar_subledger_ties_to_gl")
    assert code != 0 and failed(out, "assert_ar_subledger_ties_to_gl"), out[-800:]


def test_unbalanced_journal_is_quarantined_not_reported(mutate):
    before = mutate.execute("select count(*) from marts.fct_journal_exceptions").fetchone()[0]
    jid = mutate.execute("select journal_id from raw.gl_entries where source_system = 'AR' limit 1").fetchone()[0]
    mutate.execute(f"update raw.gl_entries set debit_cents = debit_cents + 777 where journal_id = '{jid}' and line_no = 1")
    mutate.close()
    # the quarantine and its guard tests must all pass: the damage is CONTAINED...
    code, out = dbt("build", "--select", "int_journal_balance", "fct_gl", "fct_journal_exceptions",
                    "assert_fct_gl_journals_balanced", "assert_exceptions_are_really_unbalanced", "assert_no_ledger_lines_lost")
    assert code == 0, out[-800:]
    assert query_mut("select count(*) from marts.fct_journal_exceptions") == before + 1
    assert query_mut(f"select count(*) from marts.fct_gl where journal_id = '{jid}'") == 0
    assert query_mut(f"select abs_difference_lc from marts.fct_journal_exceptions where journal_id = '{jid}'") == Decimal("7.77")
    # ...and the downstream subledger tie-out notices that an invoice vanished from the ledger
    code, out = dbt("build", "--select", "fct_trial_balance", "assert_ar_subledger_ties_to_gl")
    assert code != 0 and failed(out, "assert_ar_subledger_ties_to_gl"), out[-800:]


def test_missing_fx_rate_is_caught(mutate):
    mutate.execute("delete from raw.fx_rates where currency = 'TND' and period_start = date '2024-06-01'")
    mutate.close()
    code, out = dbt("test", "--select", "assert_fx_rates_complete")
    assert code != 0 and failed(out, "assert_fx_rates_complete"), out[-800:]


def test_overpaid_invoice_is_caught(mutate):
    mutate.execute("""insert into raw.payments
        select 'PAY-DUP-0000001', invoice_id, entity_id, payment_date, amount_cents from raw.payments limit 1""")
    mutate.close()
    code, out = dbt("test", "--select", "assert_no_overpaid_invoices")
    assert code != 0 and failed(out, "assert_no_overpaid_invoices"), out[-800:]


def test_budget_on_a_balance_sheet_account_is_caught(mutate):
    mutate.execute("""insert into raw.budgets
        select entity_id, period_start, 1010, cost_center_id, budget_cents from raw.budgets limit 1""")
    mutate.close()
    code, out = dbt("test", "--select", "assert_budget_only_on_pl_accounts")
    assert code != 0 and failed(out, "assert_budget_only_on_pl_accounts"), out[-800:]
