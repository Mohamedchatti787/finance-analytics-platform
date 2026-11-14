"""
One command to rebuild everything:  python run_pipeline.py [--scale 1.0] [--fresh]

  1 generate synthetic source data      4 reconciliation engine + scoring vs truth
  2 load the DuckDB warehouse           5 cash-collections forecast + backtest
  3 dbt build (models + all tests)      6 independent KPIs, Power BI export, figures
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


def step(title, cmd):
    print(f"\n=== {title}\n$ {' '.join(cmd)}", flush=True)
    t = time.time()
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"step failed: {title}")
    print(f"--- done in {time.time() - t:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="data volume multiplier (1.0 = ~1.5M ledger lines)")
    ap.add_argument("--fresh", action="store_true", help="delete the existing warehouse first")
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--skip-export", action="store_true", help="skip Power BI export and figures")
    a = ap.parse_args()
    py = sys.executable

    if a.fresh and Path("warehouse/finance.duckdb").exists():
        Path("warehouse/finance.duckdb").unlink()
    if not a.skip_generate:
        shutil.rmtree("data/raw", ignore_errors=True)
        step("1/6 generate synthetic data", [py, "-m", "data_gen.generate", "--scale", str(a.scale)])
    step("2/6 load warehouse", [py, "-m", "warehouse.load_raw"])
    step("3/6 dbt build (models + tests)", ["dbt", "build", "--profiles-dir", "."])
    step("4/6 reconciliation engine", [py, "-m", "recon.run_recon"])
    step("4/6 score engine against ground truth", [py, "-m", "recon.evaluate"])
    step("5/6 cash collections forecast + backtest", [py, "-m", "forecast.collections"])
    step("6/6 independent KPI recomputation", [py, "-m", "export.expected_kpis"])
    step("6/6 Power BI validation guide", [py, "-m", "export.make_validation_doc"])
    step("6/6 data dictionary", [py, "-m", "export.make_data_dictionary"])
    if not a.skip_export:
        step("6/6 Power BI export", [py, "-m", "export.to_powerbi"])
        step("6/6 preview figures", [py, "-m", "export.make_figures"])
    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
