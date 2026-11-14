"""The Power BI documentation is a CONTRACT with the warehouse: every column the DAX uses must
exist in the exported tables, and every KPI to validate must map to a measure that exists."""
import json
import re

import pandas as pd
import pytest

from conftest import ROOT
from export.make_validation_doc import KPI_TO_MEASURE
from export.to_powerbi import TABLES

DAX = (ROOT / "docs" / "powerbi" / "measures.dax").read_text()


def exported_columns(wh):
    cols = {t: {r[0] for r in wh.execute(f"describe marts.{t}").fetchall()} for t in TABLES}
    cols["dim_user_entity"] = {"user_principal_name", "entity_id"}
    return cols


def test_every_table_column_reference_in_the_dax_exists(wh):
    cols = exported_columns(wh)
    refs = set(re.findall(r"\b((?:fct|dim)_[a-z_]+)\[([a-z_0-9]+)\]", DAX))
    assert refs, "no references found - regex broken?"
    missing = [(t, c) for t, c in refs if t not in cols or c not in cols[t]]
    assert not missing, missing


def measure_names():
    return set(re.findall(r"^([A-Za-z][A-Za-z0-9 %()\-,/]*?) =\s*$", DAX, flags=re.M))


def test_measure_cross_references_resolve():
    """Every bare [Measure] used inside an expression must be a measure defined in the file."""
    names = measure_names()
    code = "\n".join(l for l in DAX.splitlines() if not l.strip().startswith("//"))
    # a bare [Name] is not preceded by an identifier, a closing bracket or a quote (table-qualified refs)
    used = set(re.findall(r"(?<![A-Za-z_0-9\]'])\[([A-Za-z][A-Za-z0-9 %()\-,/]*)\]", code))
    unknown = used - names
    assert not unknown, unknown


def test_every_kpi_maps_to_a_real_measure():
    kpis = pd.read_csv(ROOT / "docs" / "powerbi" / "expected_kpis.csv")
    names = measure_names()
    assert set(kpis["kpi_id"]) <= set(KPI_TO_MEASURE), set(kpis["kpi_id"]) - set(KPI_TO_MEASURE)
    assert {KPI_TO_MEASURE[k][0] for k in kpis["kpi_id"]} <= names


def test_theme_is_valid_json_with_required_keys():
    theme = json.loads((ROOT / "docs" / "powerbi" / "theme.json").read_text())
    assert theme["name"] and len(theme["dataColors"]) >= 8
