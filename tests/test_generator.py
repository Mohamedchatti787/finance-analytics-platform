"""The synthetic data must be internally consistent, deterministic, and its ground truth airtight."""
import hashlib
import json
import subprocess
import sys

import duckdb
import pytest

from conftest import ROOT


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    out = tmp_path_factory.mktemp("raw")
    subprocess.run([sys.executable, "-m", "data_gen.generate", "--scale", "0.05", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    con = duckdb.connect()
    for f in out.glob("*.parquet"):
        con.execute(f"create view {f.stem} as select * from read_parquet('{f.as_posix()}')")
    return out, con


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generation_is_deterministic(small, tmp_path):
    out, _ = small
    subprocess.run([sys.executable, "-m", "data_gen.generate", "--scale", "0.05", "--out", str(tmp_path)],
                   cwd=ROOT, check=True, capture_output=True)
    for name in ["gl_entries", "bank_statements", "invoices"]:
        a = duckdb.connect().execute(f"select * from read_parquet('{(out / (name + '.parquet')).as_posix()}')").df()
        b = duckdb.connect().execute(f"select * from read_parquet('{(tmp_path / (name + '.parquet')).as_posix()}')").df()
        assert a.equals(b), f"{name} differs between runs with the same seed"


def test_only_the_planted_journals_are_unbalanced(small):
    out, con = small
    bad = {r[0] for r in con.execute("select journal_id from gl_entries group by 1 having sum(debit_cents) <> sum(credit_cents)").fetchall()}
    planted = set(json.loads((out / "ground_truth.json").read_text())["unbalanced_journals"])
    assert bad == planted and len(bad) >= 3


def test_ar_subledger_ties_to_control_account(small):
    _, con = small
    diff = con.execute("""select (select sum(debit_cents - credit_cents) from gl_entries where account_id = 1100)
                              - ((select sum(gross_cents) from invoices) - (select sum(amount_cents) from payments))""").fetchone()[0]
    assert diff == 0


def test_cash_never_goes_negative(small):
    _, con = small
    worst = con.execute("""with m as (select entity_id, date_trunc('month', posting_date) mth, sum(debit_cents - credit_cents) n
                                      from gl_entries where account_id = 1010 group by 1, 2),
                                c as (select sum(n) over (partition by entity_id order by mth) as running from m)
                           select min(running) from c""").fetchone()[0]
    assert worst > 0


def test_ground_truth_partitions_every_cash_and_bank_line_exactly_once(small):
    _, con = small
    # every ledger cash line is either paired with a bank line or declared GL-only - never both, never neither
    n_cash = con.execute("select count(*) from gl_entries where account_id = 1010").fetchone()[0]
    paired = con.execute("select count(distinct gl_line_id) from truth_bank_pairs").fetchone()[0]
    gl_only = con.execute("select count(*) from truth_gl_only").fetchone()[0]
    overlap = con.execute("select count(*) from truth_bank_pairs p join truth_gl_only g using (gl_line_id)").fetchone()[0]
    assert overlap == 0 and paired + gl_only == n_cash
    n_bank = con.execute("select count(*) from bank_statements").fetchone()[0]
    b_paired = con.execute("select count(distinct bank_line_id) from truth_bank_pairs").fetchone()[0]
    b_only = con.execute("select count(*) from truth_bank_only").fetchone()[0]
    assert b_paired + b_only == n_bank


def test_every_entity_has_an_fx_rate_for_every_month(small):
    _, con = small
    assert con.execute("select count(*) from fx_rates").fetchone()[0] == 3 * 36
