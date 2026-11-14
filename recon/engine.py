"""
Bank reconciliation engine: matches bank-statement lines to general-ledger cash
postings (account 1010) in tiers, from most to least certain, so every match
carries an auditable reason.

  T1  exact amount + exact (normalised) reference
  T2  exact amount + similar reference (garbled / truncated / prefixed)
  T3  exact amount + reference unusable, but the pairing is UNIQUE both ways
  T4  amount within tolerance (bank-deducted fee, keying typo): exact reference
      first, then similar reference or unique pairing - never fuzzy-over-exact
  T5  one bank line = several ledger receipts (batched deposit)

Whatever is left is classified, not just dumped:
  ledger side: outstanding (timing) vs unmatched-investigate
  bank side:   bank charge / interest not yet booked vs unidentified item

The engine NEVER sees the generator's ground truth (it lives in a separate
`truth` schema). recon/evaluate.py scores the engine against it afterwards.
"""
from dataclasses import dataclass
import itertools

import duckdb
import numpy as np
import pandas as pd

TOL_ABS_CENTS = 2500        # 25.00 in local currency (covers typical wire/bank fees)
TOL_REL = 0.005             # or 0.5% of the amount, whichever is larger
BANK_BEFORE_GL_DAYS = 3     # bank value date may precede the ledger date slightly
BANK_AFTER_GL_DAYS = 30     # ... or trail it (cheques, slow transfers)
BATCH_WINDOW_DAYS = 5       # ledger receipts of one batch sit within this many days of the deposit
BATCH_MAX_CANDIDATES = 220
REF_SIM_ACCEPT = 0.85
TIMING_WINDOW_DAYS = 30     # unmatched ledger items younger than this are 'timing'


def norm_ref(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


@dataclass
class ReconResult:
    matches: pd.DataFrame
    unmatched_gl: pd.DataFrame
    unmatched_bank: pd.DataFrame


# --------------------------------------------------------------------------- helpers
def _greedy_one_to_one(pairs: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    """Keep the best-scoring pairs such that each bank line and each ledger line is used once."""
    if pairs.empty:
        return pairs
    chosen = []
    remaining = pairs.sort_values([score_col, "dd_abs"], ascending=[False, True], kind="stable")
    for _ in range(4):  # a few passes fill gaps left by earlier conflicts
        if remaining.empty:
            break
        step = remaining.drop_duplicates("bank_line_id").drop_duplicates("gl_line_id")
        chosen.append(step)
        remaining = remaining[~remaining["bank_line_id"].isin(step["bank_line_id"])
                              & ~remaining["gl_line_id"].isin(step["gl_line_id"])]
    return pd.concat(chosen, ignore_index=True)


def _candidates(con, bank_tbl, gl_tbl, exact_amount: bool) -> pd.DataFrame:
    if exact_amount:
        amount_cond = "b.amount_c = g.amount_c"
    else:
        amount_cond = (f"sign(b.amount_c) = sign(g.amount_c) and b.amount_c <> g.amount_c and "
                       f"abs(b.amount_c - g.amount_c) <= greatest({TOL_ABS_CENTS}, {TOL_REL} * abs(g.amount_c))")
    sql = f"""
        select b.bank_line_id, g.gl_line_id, b.entity_id,
               b.amount_c - g.amount_c as amount_diff_c,
               date_diff('day', g.posting_date, b.value_date) as dd,
               abs(date_diff('day', g.posting_date, b.value_date)) as dd_abs,
               b.ref_n as bank_ref_n, g.ref_n as gl_ref_n,
               case
                 when b.ref_n <> '' and b.ref_n = g.ref_n then 1.0
                 when length(b.ref_n) >= 4 and (contains(g.ref_n, b.ref_n) or contains(b.ref_n, g.ref_n)) then 0.95
                 when b.ref_n = '' or g.ref_n = '' then 0.0
                 else jaro_winkler_similarity(b.ref_n, g.ref_n)
               end as ref_sim
        from {bank_tbl} b
        join {gl_tbl} g
          on b.entity_id = g.entity_id
         and {amount_cond}
         and b.value_date between g.posting_date - interval {BANK_BEFORE_GL_DAYS} day
                              and g.posting_date + interval {BANK_AFTER_GL_DAYS} day
    """
    return con.execute(sql).df()


def _subset_sum(amounts: np.ndarray, target: int, max_size: int = 4):
    """Indices of the smallest subset (size 2..max_size) of `amounts` summing exactly to target."""
    n = len(amounts)
    a = amounts.astype(np.int64)
    if n < 2:
        return None
    pair = a[:, None] + a[None, :]
    iu = np.triu(np.ones((n, n), dtype=bool), k=1)
    hit = np.argwhere((pair == target) & iu)
    if len(hit):
        return list(hit[0])
    if max_size >= 3 and n >= 3:
        for k in range(n):
            mask = iu.copy()
            mask[k:, :] = False
            mask[:, k:] = False  # i<j<k
            hit = np.argwhere((pair == target - a[k]) & mask)
            if len(hit):
                return [int(hit[0][0]), int(hit[0][1]), k]
    if max_size >= 4 and n >= 4:
        idx = np.argwhere(iu)
        sums = pair[iu]
        order = np.argsort(sums, kind="stable")
        s_sorted = sums[order]
        for p in range(len(sums)):
            need = target - sums[p]
            lo = np.searchsorted(s_sorted, need, side="left")
            hi = np.searchsorted(s_sorted, need, side="right")
            for q in order[lo:hi]:
                if q <= p:
                    continue
                combo = {int(idx[p][0]), int(idx[p][1]), int(idx[q][0]), int(idx[q][1])}
                if len(combo) == 4:
                    return sorted(combo)
    return None


# --------------------------------------------------------------------------- main
def reconcile(gl: pd.DataFrame, bank: pd.DataFrame, as_of) -> ReconResult:
    """
    gl   : gl_line_id, entity_id, posting_date, amount_c (signed cents: +inflow), reference
    bank : bank_line_id, entity_id, value_date, amount_c (signed cents), bank_reference, description
    """
    gl = gl.copy()
    bank = bank.copy()
    gl["ref_n"] = norm_ref(gl["reference"])
    bank["ref_n"] = norm_ref(bank["bank_reference"])
    gl["posting_date"] = pd.to_datetime(gl["posting_date"])
    bank["value_date"] = pd.to_datetime(bank["value_date"])

    con = duckdb.connect()
    matched = []

    def run_tier(name, tier_no, exact_amount, rule):
        nonlocal gl, bank
        con.register("bank_open", bank)
        con.register("gl_open", gl)
        cand = _candidates(con, "bank_open", "gl_open", exact_amount)
        if cand.empty:
            return
        sel = rule(cand)
        if sel.empty:
            return
        sel = _greedy_one_to_one(sel)
        sel["tier"] = tier_no
        sel["match_type"] = name
        matched.append(sel)
        bank = bank[~bank["bank_line_id"].isin(sel["bank_line_id"])]
        gl = gl[~gl["gl_line_id"].isin(sel["gl_line_id"])]

    # T1: exact amount + exact reference
    run_tier("T1 exact amount + exact reference", 1, True,
             lambda c: c[c["ref_sim"] == 1.0].assign(score=lambda d: 1.0 - d["dd_abs"] / 1000))
    # T2: exact amount + similar reference
    run_tier("T2 exact amount + similar reference", 2, True,
             lambda c: c[c["ref_sim"] >= REF_SIM_ACCEPT].assign(score=lambda d: d["ref_sim"] - d["dd_abs"] / 1000))

    # T3: exact amount, reference unusable, pairing unique in both directions
    def unique_rule(c):
        c = c[c["ref_sim"] < REF_SIM_ACCEPT].copy()
        nb = c.groupby("bank_line_id")["gl_line_id"].transform("nunique")
        ng = c.groupby("gl_line_id")["bank_line_id"].transform("nunique")
        c = c[(nb == 1) & (ng == 1)]
        return c.assign(score=0.7 - c["dd_abs"] / 1000)
    run_tier("T3 exact amount + unique pairing", 3, True, unique_rule)

    # T4: amount within tolerance (bank-deducted fees, keying typos). Because the amount
    # is deliberately NOT exact here, the REFERENCE has to carry the decision, and
    # references of sequential documents (BILL-E04-0000058 vs ...0000095) look
    # "97% similar" to fuzzy string metrics - so a fuzzy score must never outrank
    # an exact one. Three sub-steps, strictest first:
    def _unique(c):
        nb = c.groupby("bank_line_id")["gl_line_id"].transform("nunique")
        ng = c.groupby("gl_line_id")["bank_line_id"].transform("nunique")
        return (nb == 1) & (ng == 1)

    # T4a: exact reference, amount within tolerance
    run_tier("T4a amount within tolerance + exact reference", 4, False,
             lambda c: c[c["ref_sim"] == 1.0].assign(score=lambda d: 1.0 - d["dd_abs"] / 1000))
    # T4b: truncated/prefixed/garbled reference, but the pairing is unique in both directions
    run_tier("T4b amount within tolerance + similar reference (unique)", 4, False,
             lambda c: (lambda d: d[_unique(d)].assign(score=lambda x: x["ref_sim"] - x["dd_abs"] / 1000))(
                 c[(c["ref_sim"] >= 0.9) & (c["ref_sim"] < 1.0)]))
    # T4c: reference unusable (missing/generic), pairing unique both ways and close in time
    run_tier("T4c amount within tolerance + unique pairing (no usable reference)", 4, False,
             lambda c: (lambda d: d[_unique(d) & (d["dd_abs"] <= 5)].assign(score=lambda x: 0.5 - x["dd_abs"] / 1000))(
                 c[c["ref_sim"] < 0.6]))

    # T5: batched deposits - one bank credit equals the sum of several ledger receipts
    batch_rows = []
    is_batch = bank["bank_reference"].fillna("").str.upper().str.contains("BATCH") | \
        bank["description"].fillna("").str.upper().str.contains("BATCH")
    cand_bank = bank[is_batch & (bank["amount_c"] > 0)].sort_values("value_date")
    gl_pool = gl[gl["amount_c"] > 0]
    used_gl = set()
    for _, b in cand_bank.iterrows():
        win = gl_pool[(gl_pool["entity_id"] == b["entity_id"])
                      & (gl_pool["posting_date"] >= b["value_date"] - pd.Timedelta(days=BATCH_WINDOW_DAYS))
                      & (gl_pool["posting_date"] <= b["value_date"])
                      & (gl_pool["amount_c"] < b["amount_c"])
                      & (~gl_pool["gl_line_id"].isin(used_gl))]
        if len(win) < 2 or len(win) > BATCH_MAX_CANDIDATES:
            continue
        win = win.sort_values("posting_date")
        sol = _subset_sum(win["amount_c"].values, int(b["amount_c"]))
        if sol is None:
            continue
        for i in sol:
            row = win.iloc[i]
            used_gl.add(row["gl_line_id"])
            batch_rows.append(dict(bank_line_id=b["bank_line_id"], gl_line_id=row["gl_line_id"], entity_id=b["entity_id"],
                                   amount_diff_c=0, dd=int((b["value_date"] - row["posting_date"]).days),
                                   dd_abs=abs(int((b["value_date"] - row["posting_date"]).days)),
                                   ref_sim=np.nan, score=0.9, tier=5, match_type="T5 batched deposit (many-to-one)",
                                   bank_ref_n="", gl_ref_n=row["ref_n"]))
    if batch_rows:
        bm = pd.DataFrame(batch_rows)
        matched.append(bm)
        bank = bank[~bank["bank_line_id"].isin(bm["bank_line_id"])]
        gl = gl[~gl["gl_line_id"].isin(bm["gl_line_id"])]

    keep = ["bank_line_id", "gl_line_id", "entity_id", "tier", "match_type", "score", "ref_sim", "amount_diff_c", "dd"]
    if matched:
        matches = pd.concat(matched, ignore_index=True)[keep]
    else:  # nothing matched: return an empty frame with the right columns, not a crash
        matches = pd.DataFrame({c: pd.Series(dtype="float64") for c in keep})
    matches = matches.rename(columns={"dd": "date_diff_days"})

    # ---- classify what is left
    as_of = pd.Timestamp(as_of)
    ug = gl.copy()
    ug["age_days"] = (as_of - ug["posting_date"]).dt.days
    ug["category"] = np.where(ug["age_days"] <= TIMING_WINDOW_DAYS, "Outstanding (timing)", "Unmatched - investigate")
    ub = bank.copy()
    desc = ub["description"].fillna("").str.upper()
    ub["age_days"] = (as_of - ub["value_date"]).dt.days
    ub["category"] = np.select(
        [desc.str.contains("BANK CHARGE"), desc.str.contains("INTEREST")],
        ["Bank charge - not booked", "Interest - not booked"],
        default="Unidentified bank item")
    return ReconResult(matches, ug, ub)
