import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "warehouse" / "finance.duckdb"


@pytest.fixture(scope="session")
def wh():
    """Read-only connection to the built warehouse (run `python run_pipeline.py` first)."""
    if not DB.exists():
        pytest.skip("warehouse not built - run: python run_pipeline.py")
    con = duckdb.connect(str(DB), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def truth():
    p = ROOT / "data" / "raw" / "ground_truth.json"
    if not p.exists():
        pytest.skip("ground truth not found - run: python run_pipeline.py")
    return json.loads(p.read_text())


@pytest.fixture(scope="session")
def full_scale(truth):
    return truth["scale"] >= 0.8
