"""Unit tests for the reconciliation engine on tiny hand-built cases with known answers."""
import numpy as np
import pandas as pd
import pytest

from recon.engine import reconcile, _subset_sum

AS_OF = "2025-12-31"


def G(rows):
    return pd.DataFrame(rows, columns=["gl_line_id", "entity_id", "posting_date", "amount_c", "reference"])


def B(rows):
    return pd.DataFrame(rows, columns=["bank_line_id", "entity_id", "value_date", "amount_c", "bank_reference", "description"])


def pairs(res):
    return set(zip(res.matches["bank_line_id"], res.matches["gl_line_id"]))


def test_tier1_exact_amount_and_reference():
    gl = G([(1, "E01", "2025-01-10", 10000, "INV-E01-0000001")])
    bank = B([("B1", "E01", "2025-01-11", 10000, "inv e01 0000001", "CREDIT TRANSFER")])  # case/punctuation differ
    r = reconcile(gl, bank, AS_OF)
    assert pairs(r) == {("B1", 1)} and r.matches["tier"].iloc[0] == 1


def test_tier2_truncated_reference_with_exact_amount():
    gl = G([(1, "E01", "2025-01-10", 10000, "INV-E01-0000001")])
    bank = B([("B1", "E01", "2025-01-12", 10000, "INV-E01-00000", "CREDIT TRANSFER")])
    r = reconcile(gl, bank, AS_OF)
    assert pairs(r) == {("B1", 1)} and r.matches["tier"].iloc[0] == 2


def test_regression_exact_reference_beats_fuzzy_lookalike_decoy():
    """The bug found during development: BILL-...0095 and BILL-...0058 look 97% 'similar' to a
    fuzzy metric, and the decoy's amount was numerically closer. The exact reference must win."""
    gl = G([(1, "E04", "2023-02-03", -17981, "BILL-E04-0000095"),   # the true ledger line (bank deducted a fee)
            (2, "E04", "2023-02-05", -22268, "BILL-E04-0000058")])  # decoy: similar id, amount within tolerance too
    bank = B([("B1", "E04", "2023-02-06", -20340, "BILL-E04-0000095", "DEBIT TRANSFER")])
    r = reconcile(gl, bank, AS_OF)
    assert pairs(r) == {("B1", 1)}
    assert r.matches["match_type"].iloc[0].startswith("T4a")


def test_tolerance_never_matches_opposite_signs():
    gl = G([(1, "E01", "2025-01-10", 10000, "X-1")])
    bank = B([("B1", "E01", "2025-01-10", -10000, "", "DEBIT TRANSFER")])
    r = reconcile(gl, bank, AS_OF)
    assert len(r.matches) == 0


def test_never_matches_across_entities():
    gl = G([(1, "E01", "2025-01-10", 10000, "INV-1")])
    bank = B([("B1", "E02", "2025-01-10", 10000, "INV-1", "CREDIT TRANSFER")])
    assert len(reconcile(gl, bank, AS_OF).matches) == 0


def test_one_to_one_two_identical_bank_lines_one_ledger_line():
    gl = G([(1, "E01", "2025-01-10", 10000, "INV-1")])
    bank = B([("B1", "E01", "2025-01-10", 10000, "INV-1", "CREDIT TRANSFER"),
              ("B2", "E01", "2025-01-11", 10000, "INV-1", "CREDIT TRANSFER")])
    r = reconcile(gl, bank, AS_OF)
    assert len(r.matches) == 1 and len(r.unmatched_bank) == 1


def test_tier5_batched_deposit_many_to_one():
    gl = G([(1, "E01", "2025-03-03", 10000, "INV-A"), (2, "E01", "2025-03-03", 25050, "INV-B"),
            (3, "E01", "2025-03-04", 7000, "INV-C"), (4, "E01", "2025-03-04", 999, "INV-D")])
    bank = B([("B1", "E01", "2025-03-05", 42050, "BATCH DEPOSIT", "CREDIT BATCH")])
    r = reconcile(gl, bank, AS_OF)
    assert pairs(r) == {("B1", 1), ("B1", 2), ("B1", 3)}
    assert set(r.matches["tier"]) == {5}
    assert list(r.unmatched_gl["gl_line_id"]) == [4]


def test_leftover_classification():
    gl = G([(1, "E01", "2025-12-20", 5000, "INV-NEW"),     # 11 days before as-of -> timing
            (2, "E01", "2025-06-01", 7000, "INV-OLD")])    # 7 months old -> investigate
    bank = B([("B1", "E01", "2025-05-05", -350, "FEE-1", "BANK CHARGE"),
              ("B2", "E01", "2025-05-31", 1200, "INTEREST", "INTEREST CREDIT"),
              ("B3", "E01", "2025-07-07", 88800, "", "UNIDENTIFIED CREDIT")])
    r = reconcile(gl, bank, AS_OF)
    assert dict(zip(r.unmatched_gl["gl_line_id"], r.unmatched_gl["category"])) == {
        1: "Outstanding (timing)", 2: "Unmatched - investigate"}
    assert dict(zip(r.unmatched_bank["bank_line_id"], r.unmatched_bank["category"])) == {
        "B1": "Bank charge - not booked", "B2": "Interest - not booked", "B3": "Unidentified bank item"}


def test_every_input_line_is_matched_or_left_over_exactly_once():
    rng = np.random.default_rng(0)
    n = 300
    amounts = rng.integers(1000, 500000, n)
    gl = G([(i, "E01", "2025-02-01", int(a), f"REF-{i:05d}") for i, a in enumerate(amounts)])
    bank = B([(f"B{i}", "E01", "2025-02-02", int(a) if i % 5 else int(a) - 700, f"REF-{i:05d}", "CREDIT TRANSFER")
              for i, a in enumerate(amounts) if i % 11])
    r = reconcile(gl, bank, AS_OF)
    assert set(r.matches["gl_line_id"]) | set(r.unmatched_gl["gl_line_id"]) == set(gl["gl_line_id"])
    assert not (set(r.matches["gl_line_id"]) & set(r.unmatched_gl["gl_line_id"]))
    assert r.matches["gl_line_id"].is_unique


@pytest.mark.parametrize("amounts,target,expected", [
    ([100, 250, 700, 1500], 950, [1, 2]),
    ([100, 250, 700, 1500], 1050, [0, 1, 2]),
    ([100, 250, 700, 1500], 2550, [0, 1, 2, 3]),
    ([100, 250, 700, 1500], 12345, None),
])
def test_subset_sum_known_answers(amounts, target, expected):
    got = _subset_sum(np.array(amounts), target)
    assert (sorted(got) if got is not None else None) == expected
