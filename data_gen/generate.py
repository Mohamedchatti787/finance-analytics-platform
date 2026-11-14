"""
Synthetic multi-entity finance data generator.

Produces (as parquet, in data/raw/):
  entities, accounts, cost_centers, fx_rates, budget_fx_rates, customers,
  invoices (AR subledger), payments, gl_entries (double-entry general ledger),
  budgets, bank_statements
plus GROUND TRUTH files used only for validation, never by the pipeline:
  truth_bank_pairs, truth_gl_only, truth_bank_only, ground_truth.json

EVERYTHING HERE IS SYNTHETIC. Company, customers and numbers are invented, and
nothing is derived from any real employer's data or schema.

Design goals
- Real accounting structure: balanced journals, control accounts that tie to
  subledgers, VAT settlement, payroll, accruals with reversals, depreciation.
- Planted, documented issues so the platform's findings can be checked against
  a known answer (see ground_truth.json):
    S1  E02 marketing overspend, Oct-Dec 2024 (+35% volume)
    S2  E03 revenue shortfall from Mar 2025 (-18% invoice volume)
    S3  E02 hardware COGS supplier price rise from Jul 2024 (+12%)
    S4  E04 payroll above plan from Jan 2025 (+8%)
    S5  E03 customers pay ~15 days slower from 2025
    S6  ~4% of customers are chronic late payers
    Q1  a handful of manual journals posted UNBALANCED
    R1  bank statement imperfections: reference noise, bank-deducted fees,
        batched deposits, unrecorded bank charges, unidentified deposits,
        timing items, and GL-only postings with no bank line
- All amounts are integer cents so journals balance exactly.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

START = np.datetime64("2023-01-01")
END = np.datetime64("2025-12-31")
N_MONTHS = 36
BASE_INV = 600.0  # baseline sales invoices per month for an entity of size 1.0

FX_BASE = {"EUR": 1.0, "USD": 0.92, "TND": 0.30}

ENTITIES = [
    dict(entity_id="E01", entity_name="Meridian Europe SAS", country="FR", currency="EUR", size=1.00, vat=0.20, mean_net=1800.0, n_customers=260),
    dict(entity_id="E02", entity_name="Meridian GmbH", country="DE", currency="EUR", size=0.90, vat=0.19, mean_net=1700.0, n_customers=240),
    dict(entity_id="E03", entity_name="Meridian Tunisie SARL", country="TN", currency="TND", size=0.60, vat=0.19, mean_net=6000.0, n_customers=200),
    dict(entity_id="E04", entity_name="Meridian Inc East", country="US", currency="USD", size=1.20, vat=0.0, mean_net=1950.0, n_customers=300),
    dict(entity_id="E05", entity_name="Meridian Inc West", country="US", currency="USD", size=0.80, vat=0.0, mean_net=1900.0, n_customers=220),
]

# account_id, name, type, statement, normal_balance, group
ACCOUNTS = [
    (1010, "Cash at bank", "ASSET", "BS", "D", "Cash"),
    (1100, "Accounts receivable", "ASSET", "BS", "D", "Receivables"),
    (1300, "VAT receivable", "ASSET", "BS", "D", "Tax"),
    (1500, "Fixed assets", "ASSET", "BS", "D", "Fixed assets"),
    (1590, "Accumulated depreciation", "ASSET", "BS", "C", "Fixed assets"),
    (2100, "Accounts payable", "LIABILITY", "BS", "C", "Payables"),
    (2200, "VAT payable", "LIABILITY", "BS", "C", "Tax"),
    (2300, "Payroll liabilities", "LIABILITY", "BS", "C", "Payroll"),
    (3000, "Share capital", "EQUITY", "BS", "C", "Equity"),
    (4000, "Revenue - Subscriptions", "REVENUE", "PL", "C", "Revenue"),
    (4010, "Revenue - Services", "REVENUE", "PL", "C", "Revenue"),
    (4020, "Revenue - Hardware", "REVENUE", "PL", "C", "Revenue"),
    (5000, "COGS - Hosting & infrastructure", "COGS", "PL", "D", "Cost of goods sold"),
    (5010, "COGS - Hardware cost", "COGS", "PL", "D", "Cost of goods sold"),
    (5020, "COGS - Delivery subcontractors", "COGS", "PL", "D", "Cost of goods sold"),
    (6100, "Salaries & wages", "OPEX", "PL", "D", "Personnel"),
    (6110, "Payroll taxes & benefits", "OPEX", "PL", "D", "Personnel"),
    (6200, "Marketing & advertising", "OPEX", "PL", "D", "Sales & marketing"),
    (6210, "Travel & entertainment", "OPEX", "PL", "D", "Sales & marketing"),
    (6300, "Rent & utilities", "OPEX", "PL", "D", "Facilities"),
    (6400, "Software & IT", "OPEX", "PL", "D", "Technology"),
    (6500, "Depreciation", "OPEX", "PL", "D", "Depreciation"),
    (6600, "Professional fees", "OPEX", "PL", "D", "General & admin"),
    (6700, "Bank charges & interest", "OPEX", "PL", "D", "General & admin"),
    (6800, "Other operating expenses", "OPEX", "PL", "D", "General & admin"),
]

COST_CENTERS = [
    ("CC10", "Sales"), ("CC20", "Marketing"), ("CC30", "Operations"), ("CC40", "Engineering"),
    ("CC50", "Finance & Admin"), ("CC60", "Customer Success"), ("CC70", "HR"), ("CC80", "Executive"),
]
PAYROLL_CC_WEIGHTS = {"CC10": .22, "CC20": .08, "CC30": .20, "CC40": .25, "CC50": .08, "CC60": .10, "CC70": .03, "CC80": .04}

# revenue accounts: (account, probability, invoice-size multiplier)
REVENUE = [(4000, .55, 1.0), (4010, .30, 1.5), (4020, .15, 0.9)]
REV_PM = sum(p * m for _, p, m in REVENUE)

# vendor-invoiced expense accounts: account -> (share of revenue, mean invoice in EUR, cost centre)
VENDOR = {
    5000: (.12, 700, "CC30"), 5010: (.14, 1200, "CC30"), 5020: (.12, 900, "CC30"),
    6200: (.06, 800, "CC20"), 6210: (.02, 150, "CC10"), 6400: (.03, 250, "CC40"),
    6600: (.015, 400, "CC50"), 6800: (.02, 250, "CC80"),
}
RENT_SHARE = 0.03
SALARY_SHARE = 0.20
PAYROLL_TAX_RATE = 0.25
DEP_SHARE = 0.01
ACCOUNT_CC = {a: v[2] for a, v in VENDOR.items()}
ACCOUNT_CC.update({6300: "CC50", 6500: "CC50", 6700: "CC50"})

SHOCKS = [
    dict(id="S1", entity_id="E02", account_id=6200, start="2024-10-01", end="2024-12-31", effect="marketing invoice volume x1.35"),
    dict(id="S2", entity_id="E03", account_id=None, start="2025-03-01", end="2025-12-31", effect="revenue (invoice volume) x0.82"),
    dict(id="S3", entity_id="E02", account_id=5010, start="2024-07-01", end="2025-12-31", effect="hardware COGS invoice size x1.12"),
    dict(id="S4", entity_id="E04", account_id=6100, start="2025-01-01", end="2025-12-31", effect="salaries x1.08"),
    dict(id="S5", entity_id="E03", account_id=None, start="2025-01-01", end="2025-12-31", effect="customers pay +15 days later"),
]

SOURCE = {"AR_INV": "AR", "AR_RCPT": "CASH", "AP_INV": "AP", "AP_PAY": "CASH", "PAYROLL": "PAYROLL",
          "PAYROLL_TAX": "PAYROLL", "VAT": "TAX", "DEP": "FA", "OPEN": "OPEN", "ACCRUAL": "MANUAL", "REVERSAL": "MANUAL"}


def cents(x):
    return np.rint(np.asarray(x) * 100).astype(np.int64)


def lognormal_mean(rng, mean, sigma, size):
    mu = np.log(mean) - sigma ** 2 / 2
    return rng.lognormal(mu, sigma, size)


def d64(s):
    return np.datetime64(s)


def lines(txn_key, entity, date, account, cc, debit, credit, kind, ref, desc, order):
    n = len(txn_key)
    return pd.DataFrame({
        "txn_key": txn_key, "entity_id": entity, "posting_date": date, "account_id": account,
        "cost_center_id": cc, "debit_c": np.asarray(debit, dtype=np.int64), "credit_c": np.asarray(credit, dtype=np.int64),
        "txn_kind": kind, "reference": ref, "description": desc, "line_order": order,
    })


class Generator:
    def __init__(self, scale, seed):
        self.scale = scale
        self.rng = np.random.default_rng(seed)
        self.months = pd.date_range("2023-01-01", "2025-12-31", freq="MS")
        self.mstart = self.months.values.astype("datetime64[D]")
        self.dim = self.months.days_in_month.values
        self.month_no = self.months.month.values
        self.t = np.arange(N_MONTHS)
        self.fx = self._fx()

    # ------------------------------------------------------------------ fx
    def _fx(self):
        rng = self.rng
        rows, brows = [], []
        for cur, base in FX_BASE.items():
            if cur == "EUR":
                avg = np.ones(N_MONTHS)
            elif cur == "USD":
                x = np.zeros(N_MONTHS)
                for i in range(1, N_MONTHS):
                    x[i] = 0.85 * x[i - 1] + rng.normal(0, 0.012)
                avg = base * np.exp(x)
            else:  # TND: slow depreciation
                x = np.cumsum(rng.normal(-0.0018, 0.004, N_MONTHS))
                avg = base * np.exp(x)
            close = avg * (1 + rng.normal(0, 0.004, N_MONTHS)) if cur != "EUR" else avg
            for i in range(N_MONTHS):
                rows.append((self.mstart[i].astype(object), cur, round(float(avg[i]), 6), round(float(close[i]), 6)))
            # budget rate: FY2023 = initial rate; FY2024 = Dec-2023 close; FY2025 = Dec-2024 close
            brows += [(2023, cur, round(base, 6)), (2024, cur, round(float(close[11]), 6)), (2025, cur, round(float(close[23]), 6))]
        fx = pd.DataFrame(rows, columns=["period_start", "currency", "avg_rate_to_eur", "close_rate_to_eur"])
        bfx = pd.DataFrame(brows, columns=["fiscal_year", "currency", "budget_rate_to_eur"])
        return fx, bfx

    # --------------------------------------------------------------- plans
    def lam_inv_plan(self, ent):
        growth = 1.012 ** self.t
        seas = 1 + 0.08 * np.sin(2 * np.pi * (self.month_no - 3) / 12)
        return BASE_INV * ent["size"] * growth * seas * self.scale

    def rev_plan(self, ent):
        return self.lam_inv_plan(ent) * ent["mean_net"] * REV_PM

    def lc_per_eur(self, ent):
        return 1.0 / FX_BASE[ent["currency"]]

    def month_mask(self, start, end):
        return (self.mstart >= d64(start)) & (self.mstart <= d64(end))

    # ---------------------------------------------------------------- AR
    def gen_ar(self, ent):
        rng = self.rng
        eid = ent["entity_id"]
        n_c = max(30, int(ent["n_customers"] * self.scale))
        ranks = np.arange(1, n_c + 1)
        w = 1 / ranks ** 0.6
        w /= w.sum()
        chronic = rng.random(n_c) < 0.04
        mu = np.clip(rng.normal(5, 4, n_c), 0, 20)
        sd = np.full(n_c, 6.0)
        mu[chronic] = rng.uniform(40, 70, chronic.sum())
        sd[chronic] = 20.0
        terms = rng.choice([30, 45, 60], size=n_c, p=[.5, .3, .2])
        seg = np.where(ranks <= max(1, int(.05 * n_c)), "Enterprise", np.where(ranks <= int(.25 * n_c), "Mid-market", "SMB"))
        cust_ids = np.array([f"{eid}-C{i:04d}" for i in range(1, n_c + 1)])
        customers = pd.DataFrame({"customer_id": cust_ids, "entity_id": eid, "segment": seg,
                                  "payment_terms_days": terms, "country": ent["country"]})

        lam = self.lam_inv_plan(ent)
        if eid == "E03":
            lam = lam * np.where(self.month_mask("2025-03-01", "2025-12-31"), 0.82, 1.0)
        n_m = rng.poisson(lam)
        total = int(n_m.sum())
        m_idx = np.repeat(np.arange(N_MONTHS), n_m)
        day = (rng.random(total) * self.dim[m_idx]).astype(int)
        inv_date = self.mstart[m_idx] + day.astype("timedelta64[D]")
        order = np.argsort(inv_date, kind="stable")
        inv_date, m_idx = inv_date[order], m_idx[order]

        cust = rng.choice(n_c, size=total, p=w)
        acc_i = rng.choice(3, size=total, p=[p for _, p, _ in REVENUE])
        acc = np.array([a for a, _, _ in REVENUE])[acc_i]
        mult = np.array([m for _, _, m in REVENUE])[acc_i]
        net_c = cents(lognormal_mean(rng, ent["mean_net"] * mult, 0.6, total))
        net_c = np.maximum(net_c, 500)
        vat_c = np.rint(net_c * ent["vat"]).astype(np.int64)
        gross_c = net_c + vat_c
        due = inv_date + terms[cust].astype("timedelta64[D]")
        inv_id = np.array([f"INV-{eid}-{i:07d}" for i in range(1, total + 1)])

        invoices = pd.DataFrame({
            "invoice_id": inv_id, "entity_id": eid, "customer_id": cust_ids[cust],
            "invoice_date": inv_date, "due_date": due, "revenue_account_id": acc,
            "net_cents": net_c, "vat_cents": vat_c, "gross_cents": gross_c,
        })

        # ---- payments
        bad = rng.random(total) < 0.012
        delay = np.rint(rng.normal(mu[cust], sd[cust])).astype(int)
        delay = np.maximum(delay, -5)
        if eid == "E03":
            delay = delay + np.where(inv_date >= d64("2025-01-01"), 15, 0)
        pay1 = due + delay.astype("timedelta64[D]")
        inst = (rng.random(total) < 0.06) & ~bad
        frac = rng.uniform(0.4, 0.7, total)
        amt1 = np.where(inst, np.rint(gross_c * frac), gross_c).astype(np.int64)
        pay2 = pay1 + rng.integers(10, 41, total).astype("timedelta64[D]")
        amt2 = gross_c - amt1
        ok1 = ~bad & (pay1 <= END)
        ok2 = inst & (pay2 <= END)
        p1 = pd.DataFrame({"invoice_id": inv_id[ok1], "payment_date": pay1[ok1], "amount_cents": amt1[ok1]})
        p2 = pd.DataFrame({"invoice_id": inv_id[ok2], "payment_date": pay2[ok2], "amount_cents": amt2[ok2]})
        pay = pd.concat([p1, p2]).sort_values(["payment_date", "invoice_id"], kind="stable").reset_index(drop=True)
        pay["payment_id"] = [f"PAY-{eid}-{i:07d}" for i in range(1, len(pay) + 1)]
        pay["entity_id"] = eid
        payments = pay[["payment_id", "invoice_id", "entity_id", "payment_date", "amount_cents"]]
        chronic_ids = cust_ids[chronic].tolist()
        return customers, invoices, payments, chronic_ids

    # ---------------------------------------------------------------- AP
    def gen_ap(self, ent):
        rng = self.rng
        eid = ent["entity_id"]
        r_plan = self.rev_plan(ent)
        lcpe = self.lc_per_eur(ent)
        parts = []
        n_vend = 80
        v_terms = rng.choice([30, 45, 60], size=n_vend, p=[.6, .3, .1])
        for acct, (share, mean_eur, _cc) in VENDOR.items():
            mean_lc = mean_eur * lcpe
            lam = share * r_plan / mean_lc
            price = np.ones(N_MONTHS)
            for s in SHOCKS:
                if s["entity_id"] == eid and s["account_id"] == acct:
                    m = self.month_mask(s["start"], s["end"])
                    if s["id"] == "S1":
                        lam = lam * np.where(m, 1.35, 1.0)
                    if s["id"] == "S3":
                        price = price * np.where(m, 1.12, 1.0)
            n_m = rng.poisson(lam)
            total = int(n_m.sum())
            m_idx = np.repeat(np.arange(N_MONTHS), n_m)
            day = (rng.random(total) * self.dim[m_idx]).astype(int)
            date = self.mstart[m_idx] + day.astype("timedelta64[D]")
            net_c = np.maximum(cents(lognormal_mean(rng, mean_lc * price[m_idx], 0.5, total)), 200)
            parts.append(pd.DataFrame({"invoice_date": date, "account_id": acct, "net_c": net_c}))
        # rent: one invoice on the 1st of each month, near-fixed
        rent_plan = RENT_SHARE * r_plan[0] * (1 + 0.004 * self.t)
        parts.append(pd.DataFrame({"invoice_date": self.mstart, "account_id": 6300,
                                   "net_c": cents(rent_plan * (1 + rng.normal(0, 0.005, N_MONTHS)))}))
        ap = pd.concat(parts).sort_values(["invoice_date", "account_id"], kind="stable").reset_index(drop=True)
        n = len(ap)
        ap["entity_id"] = eid
        ap["ap_invoice_id"] = [f"BILL-{eid}-{i:07d}" for i in range(1, n + 1)]
        ap["vat_c"] = np.rint(ap["net_c"] * ent["vat"]).astype(np.int64)
        ap["gross_c"] = ap["net_c"] + ap["vat_c"]
        ap["cc"] = ap["account_id"].map(ACCOUNT_CC)
        vend = rng.integers(0, n_vend, n)
        due = ap["invoice_date"].values.astype("datetime64[D]") + v_terms[vend].astype("timedelta64[D]")
        delay = np.maximum(np.rint(rng.normal(3, 5, n)).astype(int), -3)
        ap["pay_date"] = due + delay.astype("timedelta64[D]")
        return ap

    # ------------------------------------------------------------- payroll
    def gen_payroll(self, ent):
        rng = self.rng
        eid = ent["entity_id"]
        r_plan = self.rev_plan(ent)
        shock = np.ones(N_MONTHS)
        if eid == "E04":
            shock = np.where(self.month_mask("2025-01-01", "2025-12-31"), 1.08, 1.0)
        rows = []
        for cc, w in PAYROLL_CC_WEIGHTS.items():
            sal = cents(r_plan * SALARY_SHARE * w * (1 + rng.normal(0, 0.01, N_MONTHS)) * shock)
            tax = np.rint(sal * PAYROLL_TAX_RATE).astype(np.int64)
            rows.append(pd.DataFrame({"t": self.t, "cc": cc, "sal": sal, "tax": tax}))
        return pd.concat(rows, ignore_index=True)

    # ------------------------------------------------------------- budgets
    def gen_budget(self, ent):
        rng = self.rng
        r_plan = self.rev_plan(ent)
        rows = []
        for acct, p, m in REVENUE:
            plan = r_plan * (p * m / REV_PM)
            rows.append(pd.DataFrame({"t": self.t, "account_id": acct, "cc": "CC10", "b": cents(plan * (1 + rng.normal(0, .02, N_MONTHS)))}))
        for acct, (share, _m, cc) in VENDOR.items():
            rows.append(pd.DataFrame({"t": self.t, "account_id": acct, "cc": cc, "b": cents(share * r_plan * (1 + rng.normal(0, .02, N_MONTHS)))}))
        rent_plan = RENT_SHARE * r_plan[0] * (1 + 0.004 * self.t)
        rows.append(pd.DataFrame({"t": self.t, "account_id": 6300, "cc": "CC50", "b": cents(rent_plan * (1 + rng.normal(0, .01, N_MONTHS)))}))
        for cc, w in PAYROLL_CC_WEIGHTS.items():
            sal = r_plan * SALARY_SHARE * w
            rows.append(pd.DataFrame({"t": self.t, "account_id": 6100, "cc": cc, "b": cents(sal * (1 + rng.normal(0, .01, N_MONTHS)))}))
            rows.append(pd.DataFrame({"t": self.t, "account_id": 6110, "cc": cc, "b": cents(sal * PAYROLL_TAX_RATE * (1 + rng.normal(0, .01, N_MONTHS)))}))
        dep = DEP_SHARE * r_plan[0]
        rows.append(pd.DataFrame({"t": self.t, "account_id": 6500, "cc": "CC50", "b": cents(np.full(N_MONTHS, dep))}))
        b = pd.concat(rows, ignore_index=True)
        b["entity_id"] = ent["entity_id"]
        b["period_start"] = self.mstart[b["t"].values]
        return b.rename(columns={"cc": "cost_center_id", "b": "budget_cents"})[["entity_id", "period_start", "account_id", "cost_center_id", "budget_cents"]]

    # ------------------------------------------------------------------ GL
    def build_gl(self, ents):
        rng = self.rng
        gl = []
        all_cust, all_inv, all_pay, chronic = [], [], [], []
        budgets = []
        for ent in ents:
            eid = ent["entity_id"]
            lcpe = self.lc_per_eur(ent)
            r_plan = self.rev_plan(ent)

            # --- AR
            cu, inv, pay, ch = self.gen_ar(ent)
            all_cust.append(cu); all_inv.append(inv); all_pay.append(pay); chronic += ch
            k = ("AR|" + inv["invoice_id"]).values
            idate = inv["invoice_date"].values.astype("datetime64[D]")
            ref, desc = inv["invoice_id"].values, ("Sales invoice " + inv["invoice_id"]).values
            z = np.zeros(len(inv), dtype=np.int64)
            gl.append(lines(k, eid, idate, 1100, None, inv["gross_cents"], z, "AR_INV", ref, desc, 0))
            gl.append(lines(k, eid, idate, inv["revenue_account_id"].values, "CC10", z, inv["net_cents"], "AR_INV", ref, desc, 1))
            has_vat = inv["vat_cents"].values > 0
            if has_vat.any():
                gl.append(lines(k[has_vat], eid, idate[has_vat], 2200, None, z[has_vat], inv["vat_cents"].values[has_vat], "AR_INV", ref[has_vat], desc[has_vat], 2))
            # receipts
            kp = ("RC|" + pay["payment_id"]).values
            pdte = pay["payment_date"].values.astype("datetime64[D]")
            zp = np.zeros(len(pay), dtype=np.int64)
            rref, rdesc = pay["invoice_id"].values, ("Customer receipt " + pay["payment_id"]).values
            gl.append(lines(kp, eid, pdte, 1010, None, pay["amount_cents"], zp, "AR_RCPT", rref, rdesc, 0))
            gl.append(lines(kp, eid, pdte, 1100, None, zp, pay["amount_cents"], "AR_RCPT", rref, rdesc, 1))

            # --- AP
            ap = self.gen_ap(ent)
            k = ("AP|" + ap["ap_invoice_id"]).values
            adate = ap["invoice_date"].values.astype("datetime64[D]")
            ref, desc = ap["ap_invoice_id"].values, ("Vendor bill " + ap["ap_invoice_id"]).values
            z = np.zeros(len(ap), dtype=np.int64)
            gl.append(lines(k, eid, adate, ap["account_id"].values, ap["cc"].values, ap["net_c"], z, "AP_INV", ref, desc, 0))
            hv = ap["vat_c"].values > 0
            if hv.any():
                gl.append(lines(k[hv], eid, adate[hv], 1300, None, ap["vat_c"].values[hv], z[hv], "AP_INV", ref[hv], desc[hv], 1))
            gl.append(lines(k, eid, adate, 2100, None, z, ap["gross_c"], "AP_INV", ref, desc, 2))
            paid = ap["pay_date"].values.astype("datetime64[D]") <= END
            apd = ap[paid]
            kp = ("AP-PAY|" + apd["ap_invoice_id"]).values
            pdte = apd["pay_date"].values.astype("datetime64[D]")
            zp = np.zeros(len(apd), dtype=np.int64)
            ref, desc = apd["ap_invoice_id"].values, ("Vendor payment " + apd["ap_invoice_id"]).values
            gl.append(lines(kp, eid, pdte, 2100, None, apd["gross_c"], zp, "AP_PAY", ref, desc, 0))
            gl.append(lines(kp, eid, pdte, 1010, None, zp, apd["gross_c"], "AP_PAY", ref, desc, 1))

            # --- payroll (month-end), tax remittance (15th of next month)
            pr = self.gen_payroll(ent)
            tot = pr.groupby("t")[["sal", "tax"]].sum()
            net = np.rint(0.75 * tot["sal"].values).astype(np.int64)
            liab = tot["sal"].values + tot["tax"].values - net
            pdate = (self.mstart + (self.dim - 1).astype("timedelta64[D]"))
            for _, grp in pr.groupby("cc"):
                tt = grp["t"].values
                kk = np.array([f"PR|{eid}|{i:02d}" for i in tt])
                ref = np.array([f"PAYROLL-{eid}-{self.months[i].strftime('%Y-%m')}" for i in tt])
                zz = np.zeros(len(tt), dtype=np.int64)
                cc = grp["cc"].iloc[0]
                gl.append(lines(kk, eid, pdate[tt], 6100, cc, grp["sal"].values, zz, "PAYROLL", ref, "Payroll", 0))
                gl.append(lines(kk, eid, pdate[tt], 6110, cc, grp["tax"].values, zz, "PAYROLL", ref, "Payroll taxes", 1))
            kk = np.array([f"PR|{eid}|{i:02d}" for i in self.t])
            ref = np.array([f"PAYROLL-{eid}-{self.months[i].strftime('%Y-%m')}" for i in self.t])
            zz = np.zeros(N_MONTHS, dtype=np.int64)
            gl.append(lines(kk, eid, pdate, 1010, None, zz, net, "PAYROLL", ref, "Net pay", 2))
            gl.append(lines(kk, eid, pdate, 2300, None, zz, liab, "PAYROLL", ref, "Payroll liabilities", 3))
            rem_date = pdate + np.timedelta64(15, "D")
            okr = rem_date <= END
            kk2 = np.array([f"PRTAX|{eid}|{i:02d}" for i in self.t])[okr]
            ref2 = np.array([f"PAYTAX-{eid}-{self.months[i].strftime('%Y-%m')}" for i in self.t])[okr]
            zz2 = np.zeros(okr.sum(), dtype=np.int64)
            gl.append(lines(kk2, eid, rem_date[okr], 2300, None, liab[okr], zz2, "PAYROLL_TAX", ref2, "Payroll tax remittance", 0))
            gl.append(lines(kk2, eid, rem_date[okr], 1010, None, zz2, liab[okr], "PAYROLL_TAX", ref2, "Payroll tax remittance", 1))

            # --- VAT settlement on the 20th of the following month
            if ent["vat"] > 0:
                inv_m = ((inv["invoice_date"].values.astype("datetime64[M]") - np.datetime64("2023-01", "M")).astype(int))
                ap_m = ((ap["invoice_date"].values.astype("datetime64[M]") - np.datetime64("2023-01", "M")).astype(int))
                vpay = np.bincount(inv_m, weights=inv["vat_cents"].values, minlength=N_MONTHS).astype(np.int64)
                vrec = np.bincount(ap_m, weights=ap["vat_c"].values, minlength=N_MONTHS).astype(np.int64)
                sdate = (self.mstart.astype("datetime64[M]") + 1).astype("datetime64[D]") + np.timedelta64(19, "D")
                oks = sdate <= END
                tt = self.t[oks]
                kk = np.array([f"VAT|{eid}|{i:02d}" for i in tt])
                ref = np.array([f"VAT-{eid}-{self.months[i].strftime('%Y-%m')}" for i in tt])
                diff = vpay[tt] - vrec[tt]
                zz = np.zeros(len(tt), dtype=np.int64)
                gl.append(lines(kk, eid, sdate[oks], 2200, None, vpay[tt], zz, "VAT", ref, "VAT settlement", 0))
                gl.append(lines(kk, eid, sdate[oks], 1300, None, zz, vrec[tt], "VAT", ref, "VAT settlement", 1))
                gl.append(lines(kk, eid, sdate[oks], 1010, None, np.where(diff < 0, -diff, 0), np.where(diff > 0, diff, 0), "VAT", ref, "VAT settlement", 2))

            # --- depreciation (constant) and opening balances
            dep = int(cents(DEP_SHARE * r_plan[0]))
            kk = np.array([f"DEP|{eid}|{i:02d}" for i in self.t])
            ref = np.array([f"DEP-{eid}-{self.months[i].strftime('%Y-%m')}" for i in self.t])
            zz = np.zeros(N_MONTHS, dtype=np.int64)
            dd = np.full(N_MONTHS, dep, dtype=np.int64)
            gl.append(lines(kk, eid, pdate, 6500, "CC50", dd, zz, "DEP", ref, "Monthly depreciation", 0))
            gl.append(lines(kk, eid, pdate, 1590, None, zz, dd, "DEP", ref, "Monthly depreciation", 1))
            cap_cash = int(cents(3.0 * r_plan[0]))
            fa = dep * 60
            kk, od = np.array([f"OPEN|{eid}"] * 3), np.array([START] * 3).astype("datetime64[D]")
            ref = np.array([f"OPEN-{eid}"] * 3)
            gl.append(lines(kk, eid, od, np.array([1010, 1500, 3000]), None,
                            np.array([cap_cash, fa, 0]), np.array([0, 0, cap_cash + fa]), "OPEN", ref, "Opening balances", np.array([0, 1, 2])))

            # --- manual accruals (+ reversals next month)
            n_acc = rng.poisson(6, N_MONTHS)
            tt = np.repeat(self.t, n_acc)
            na = len(tt)
            adate = self.mstart[tt] + rng.integers(21, 28, na).astype("timedelta64[D]")
            accts = rng.choice(list(VENDOR.keys()), size=na)
            amt = cents(lognormal_mean(rng, 2000 * lcpe, 0.6, na))
            cc = pd.Series(accts).map(ACCOUNT_CC).values
            kk = np.array([f"ACC|{eid}|{i:05d}" for i in range(na)])
            ref = np.array([f"ACCR-{eid}-{i:05d}" for i in range(na)])
            zz = np.zeros(na, dtype=np.int64)
            gl.append(lines(kk, eid, adate, accts, cc, amt, zz, "ACCRUAL", ref, "Month-end accrual", 0))
            gl.append(lines(kk, eid, adate, 2100, None, zz, amt, "ACCRUAL", ref, "Month-end accrual", 1))
            rdate = (self.mstart[tt].astype("datetime64[M]") + 1).astype("datetime64[D]")
            okr = rdate <= END
            kr = np.array([f"REV|{eid}|{i:05d}" for i in range(na)])[okr]
            rr = np.array([f"REVR-{eid}-{i:05d}" for i in range(na)])[okr]
            zr = np.zeros(okr.sum(), dtype=np.int64)
            gl.append(lines(kr, eid, rdate[okr], 2100, None, amt[okr], zr, "REVERSAL", rr, "Accrual reversal", 0))
            gl.append(lines(kr, eid, rdate[okr], accts[okr], cc[okr], zr, amt[okr], "REVERSAL", rr, "Accrual reversal", 1))

            budgets.append(self.gen_budget(ent))

        gl = pd.concat(gl, ignore_index=True)
        gl["posting_date"] = pd.to_datetime(gl["posting_date"])
        gl = gl.sort_values(["posting_date", "txn_key", "line_order"], kind="stable").reset_index(drop=True)
        jid = pd.factorize(gl["txn_key"])[0] + 1
        gl["journal_id"] = [f"J{i:08d}" for i in jid]
        gl["line_no"] = gl.groupby("journal_id").cumcount() + 1
        gl["gl_line_id"] = np.arange(1, len(gl) + 1)
        gl["source_system"] = gl["txn_kind"].map(SOURCE)

        # ---- plant unbalanced manual journals (control failures)
        n_bad = max(3, int(round(12 * self.scale)))
        acc_first = gl[(gl["txn_kind"] == "ACCRUAL") & (gl["line_order"] == 0)]
        pick = self.rng.choice(acc_first.index.values, size=n_bad, replace=False)
        delta = self.rng.integers(100, 5000, n_bad)
        gl.loc[pick, "debit_c"] = gl.loc[pick, "debit_c"].values + delta
        bad_journals = sorted(gl.loc[pick, "journal_id"].unique().tolist())
        return gl, pd.concat(all_cust, ignore_index=True), pd.concat(all_inv, ignore_index=True), \
            pd.concat(all_pay, ignore_index=True), pd.concat(budgets, ignore_index=True), chronic, bad_journals

    # ----------------------------------------------------------------- bank
    def build_bank(self, gl):
        rng = self.rng
        cash = gl[gl["account_id"] == 1010].copy()
        cash["amount_c"] = cash["debit_c"] - cash["credit_c"]
        n = len(cash)
        kind = cash["txn_kind"].values
        is_rcpt = kind == "AR_RCPT"
        amount = cash["amount_c"].values
        pdate = cash["posting_date"].values.astype("datetime64[D]")
        ent = cash["entity_id"].values

        u = rng.random(n)
        gl_only_error = u < 0.012
        amount_diff = (u >= 0.012) & (u < 0.032)
        # batched deposits: ~3.5% of receipts that are otherwise clean
        batch_cand = is_rcpt & ~gl_only_error & ~amount_diff & (rng.random(n) < 0.035)

        lag = np.where(is_rcpt, rng.choice([0, 1, 2], n, p=[.5, .35, .15]), rng.choice([0, 1, 2, 3, 4], n, p=[.3, .3, .2, .1, .1]))
        cheque = rng.random(n) < 0.015
        lag = np.where(cheque, rng.integers(7, 26, n), lag)
        bdate = pdate + lag.astype("timedelta64[D]")

        # ---- batch grouping (consecutive candidates, same entity, within 2 days)
        group = np.full(n, -1, dtype=np.int64)
        cand_idx = np.where(batch_cand)[0]
        order = cand_idx[np.lexsort((pdate[cand_idx], ent[cand_idx]))]
        g, i = 0, 0
        while i < len(order):
            size = int(rng.integers(2, 5))
            members = [order[i]]
            for j in range(i + 1, min(i + size, len(order))):
                same = ent[order[j]] == ent[members[0]]
                close = (pdate[order[j]] - pdate[members[0]]).astype(int) <= 2
                if same and close:
                    members.append(order[j])
                else:
                    break
            if len(members) >= 2:
                group[members] = g
                g += 1
            i += max(len(members), 1)
        batched = group >= 0

        # ---- references
        gl_ref = cash["reference"].values.astype(object)
        ref_u = rng.random(n)
        bank_ref = gl_ref.copy()
        garble = (ref_u >= 0.78) & (ref_u < 0.90)
        missing = ref_u >= 0.90
        for idx in np.where(garble)[0]:
            r = gl_ref[idx]
            c = int(rng.integers(0, 5))
            if c == 0:
                r = r.lower().replace("-", " ")
            elif c == 1:
                r = "".join(ch for ch in r if ch.isdigit()) or r
            elif c == 2:
                r = r[:-3]
            elif c == 3 and len(r) > 6:
                p = int(rng.integers(3, len(r) - 2)); r = r[:p] + r[p + 1] + r[p] + r[p + 2:]
            else:
                r = "REF " + r
            bank_ref[idx] = r
        for idx in np.where(missing)[0]:
            bank_ref[idx] = rng.choice(["", "WIRE TRANSFER", "SEPA PAYMENT", "PAYMENT"])
        # structural references (payroll/vat/capital) stay clean
        structural = ~np.isin(kind, ["AR_RCPT", "AP_PAY"])
        bank_ref = np.where(structural, gl_ref, bank_ref)
        ref_state = np.where(garble & ~structural, "garbled", np.where(missing & ~structural, "missing", "exact"))

        # ---- amounts
        bank_amt = amount.copy()
        fee = rng.integers(500, 2500, n)
        bank_amt = np.where(amount_diff, amount - fee, bank_amt)
        transpose = amount_diff & (rng.random(n) < 0.25)
        for idx in np.where(transpose)[0]:
            a = abs(int(amount[idx])); s = str(a)
            if len(s) >= 3 and s[-1] != s[-2]:
                a2 = int(s[:-2] + s[-1] + s[-2]); bank_amt[idx] = a2 * (1 if amount[idx] > 0 else -1)

        # ---- timing: bank line would land after the statement end
        rows_bank, pairs, gl_only = [], [], []
        gl_ids = cash["gl_line_id"].values
        beyond = bdate > END
        for i in np.where(gl_only_error)[0]:
            gl_only.append((int(gl_ids[i]), "gl_only_error"))

        singles = np.where(~gl_only_error & ~batched & ~beyond)[0]
        for i in np.where(~gl_only_error & ~batched & beyond)[0]:
            gl_only.append((int(gl_ids[i]), "timing_outstanding"))
        key = 0
        for i in singles:
            cat = "amount_diff" if amount_diff[i] else ("ref_" + ref_state[i] if ref_state[i] != "exact" else "exact")
            rows_bank.append((key, ent[i], bdate[i], int(bank_amt[i]), bank_ref[i],
                              "CREDIT TRANSFER" if amount[i] > 0 else "DEBIT TRANSFER"))
            pairs.append((key, int(gl_ids[i]), cat))
            key += 1
        for gi in range(g):
            m = np.where(group == gi)[0]
            d = bdate[m].max()
            if d > END:
                for i in m:
                    gl_only.append((int(gl_ids[i]), "timing_outstanding"))
                continue
            rows_bank.append((key, ent[m[0]], d, int(amount[m].sum()), "BATCH DEPOSIT", "CREDIT BATCH"))
            for i in m:
                pairs.append((key, int(gl_ids[i]), "batch"))
            key += 1

        # ---- bank-only items: fees, interest, unidentified deposits
        bo = []
        ent_cur = {e["entity_id"]: e for e in ENTITIES}
        for e in ENTITIES:
            lcpe = self.lc_per_eur(e)
            for t in range(N_MONTHS):
                nf = int(rng.integers(8, 16))
                days = (rng.random(nf) * self.dim[t]).astype(int)
                for d in days:
                    dt = self.mstart[t] + np.timedelta64(int(d), "D")
                    rows_bank.append((key, e["entity_id"], dt, -int(rng.integers(300, 4000) * max(1, lcpe * 0.5)), f"FEE-{key}", "BANK CHARGE"))
                    bo.append((key, "bank_charge")); key += 1
                dt = self.mstart[t] + np.timedelta64(int(self.dim[t]) - 1, "D")
                rows_bank.append((key, e["entity_id"], dt, int(rng.integers(1000, 30000) * lcpe), "INTEREST", "INTEREST CREDIT"))
                bo.append((key, "interest")); key += 1
        n_unid = int(0.003 * is_rcpt.sum())
        for _ in range(n_unid):
            e = ENTITIES[int(rng.integers(0, len(ENTITIES)))]
            dt = START + np.timedelta64(int(rng.integers(0, int((END - START).astype(int)))), "D")
            amt = int(cents(lognormal_mean(rng, 2000 * self.lc_per_eur(e), 0.7, 1))[0])
            rows_bank.append((key, e["entity_id"], dt, amt, "", "UNIDENTIFIED CREDIT"))
            bo.append((key, "unidentified_deposit")); key += 1

        bank = pd.DataFrame(rows_bank, columns=["bk_key", "entity_id", "value_date", "amount_cents", "bank_reference", "description"])
        bank = bank[bank["value_date"] <= END].sort_values(["value_date", "bk_key"], kind="stable").reset_index(drop=True)
        bank["bank_line_id"] = [f"B{i:07d}" for i in range(1, len(bank) + 1)]
        bank["bank_account"] = "MAIN"
        key_to_id = dict(zip(bank["bk_key"], bank["bank_line_id"]))
        t_pairs = pd.DataFrame(pairs, columns=["bk_key", "gl_line_id", "category"])
        t_pairs["bank_line_id"] = t_pairs["bk_key"].map(key_to_id)
        t_pairs = t_pairs.dropna(subset=["bank_line_id"])[["bank_line_id", "gl_line_id", "category"]]
        t_bo = pd.DataFrame(bo, columns=["bk_key", "category"])
        t_bo["bank_line_id"] = t_bo["bk_key"].map(key_to_id)
        t_bo = t_bo.dropna(subset=["bank_line_id"])[["bank_line_id", "category"]]
        t_gl = pd.DataFrame(gl_only, columns=["gl_line_id", "category"])
        bank_out = bank[["bank_line_id", "entity_id", "bank_account", "value_date", "amount_cents", "bank_reference", "description"]].copy()
        bank_out["currency"] = bank_out["entity_id"].map({e["entity_id"]: e["currency"] for e in ENTITIES})
        return bank_out, t_pairs, t_gl, t_bo


def to_date(df, cols):
    for c in cols:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="volume multiplier (1.0 ~ 1.1M GL lines)")
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    g = Generator(args.scale, args.seed)
    gl, customers, invoices, payments, budgets, chronic, bad_journals = g.build_gl(ENTITIES)
    bank, t_pairs, t_gl, t_bo = g.build_bank(gl)

    ents = pd.DataFrame(ENTITIES)[["entity_id", "entity_name", "country", "currency"]]
    ents["reporting_currency"] = "EUR"
    accts = pd.DataFrame(ACCOUNTS, columns=["account_id", "account_name", "account_type", "statement", "normal_balance", "account_group"])
    ccs = pd.DataFrame(COST_CENTERS, columns=["cost_center_id", "cost_center_name"])
    fx, bfx = g.fx

    gl_out = gl[["gl_line_id", "journal_id", "line_no", "entity_id", "posting_date", "account_id", "cost_center_id",
                 "debit_c", "credit_c", "source_system", "reference", "description"]].rename(
        columns={"debit_c": "debit_cents", "credit_c": "credit_cents"})
    gl_out = to_date(gl_out, ["posting_date"])
    invoices = to_date(invoices, ["invoice_date", "due_date"])
    payments = to_date(payments, ["payment_date"])
    budgets = to_date(budgets, ["period_start"])
    bank = to_date(bank, ["value_date"])
    fx = to_date(fx, ["period_start"])

    tables = dict(entities=ents, accounts=accts, cost_centers=ccs, fx_rates=fx, budget_fx_rates=bfx,
                  customers=customers, invoices=invoices, payments=payments, gl_entries=gl_out,
                  budgets=budgets, bank_statements=bank,
                  truth_bank_pairs=t_pairs, truth_gl_only=t_gl, truth_bank_only=t_bo)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)

    truth = dict(seed=args.seed, scale=args.scale, shocks=SHOCKS, chronic_late_customers=sorted(chronic),
                 unbalanced_journals=bad_journals)
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2))

    print(f"scale={args.scale} seed={args.seed}")
    for name in ["gl_entries", "invoices", "payments", "bank_statements", "budgets", "customers"]:
        print(f"  {name:16s} {len(tables[name]):>10,}")
    print(f"  journals         {gl_out['journal_id'].nunique():>10,}")
    print(f"  unbalanced journals planted: {len(bad_journals)}")
    print(f"  chronic late customers: {len(chronic)}")


if __name__ == "__main__":
    main()
