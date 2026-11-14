"""Load generated parquet files into the DuckDB warehouse.

raw.*    -> source tables the dbt project reads
truth.*  -> ground-truth tables used ONLY by validation code, kept in a separate
            schema so the reconciliation engine can never touch them by accident.
"""
import argparse
from pathlib import Path

import duckdb


def load(raw_dir="data/raw", db="warehouse/finance.duckdb"):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db)
    con.execute("create schema if not exists raw")
    con.execute("create schema if not exists truth")
    loaded = {}
    for f in sorted(Path(raw_dir).glob("*.parquet")):
        if f.stem.startswith("truth_"):
            schema, name = "truth", f.stem[len("truth_"):]
        else:
            schema, name = "raw", f.stem
        con.execute(f"create or replace table {schema}.{name} as select * from read_parquet('{f.as_posix()}')")
        loaded[f"{schema}.{name}"] = con.execute(f"select count(*) from {schema}.{name}").fetchone()[0]
    con.close()
    return loaded


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--db", default="warehouse/finance.duckdb")
    a = ap.parse_args()
    for k, v in load(a.raw, a.db).items():
        print(f"  {k:28s} {v:>10,}")
