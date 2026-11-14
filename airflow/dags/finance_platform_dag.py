"""
Daily refresh of the finance analytics platform.

  [generate demo data] -> load warehouse -> dbt build (models + tests)
        -> reconciliation engine -> score vs ground truth ----+
                                 -> collections forecast -----+-> KPI cross-check -> Power BI export

dbt tests are part of the build: if a financial control fails (journal out of balance,
subledger not tying to the ledger, ...) the task fails and NOTHING downstream publishes.

The first task only runs when the DAG is triggered with {"regenerate": true}; in a real
deployment the source systems would supply the data and that step would not exist.

Set FINANCE_PROJECT_DIR to the repository root (default: two folders above this file).
Airflow does not run natively on Windows - use WSL or Docker.
"""
import os
from datetime import datetime, timedelta

try:  # Airflow 3
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:  # Airflow 2.x
    from airflow.operators.bash import BashOperator
from airflow import DAG

PROJECT_DIR = os.environ.get("FINANCE_PROJECT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
PY = os.environ.get("FINANCE_PYTHON", "python")

default_args = {
    "owner": "finance-analytics",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def sh(cmd: str) -> str:
    return f"cd {PROJECT_DIR} && {cmd}"


with DAG(
    dag_id="finance_platform_daily",
    description="Load, test, reconcile, forecast and export the finance analytics marts",
    default_args=default_args,
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    params={"regenerate": False, "scale": 1.0},
    tags=["finance", "dbt", "reconciliation"],
) as dag:

    generate = BashOperator(
        task_id="generate_demo_data",
        bash_command=sh(f'if [ "{{{{ params.regenerate }}}}" = "True" ]; then {PY} -m data_gen.generate --scale {{{{ params.scale }}}}; else echo "skipping data generation"; fi'),
    )
    load = BashOperator(task_id="load_warehouse", bash_command=sh(f"{PY} -m warehouse.load_raw"))
    dbt_build = BashOperator(task_id="dbt_build_and_test", bash_command=sh("dbt build --profiles-dir ."))
    recon = BashOperator(task_id="bank_reconciliation", bash_command=sh(f"{PY} -m recon.run_recon"))
    recon_score = BashOperator(task_id="score_reconciliation", bash_command=sh(f"{PY} -m recon.evaluate"))
    forecast = BashOperator(task_id="collections_forecast", bash_command=sh(f"{PY} -m forecast.collections"))
    kpis = BashOperator(task_id="independent_kpi_check", bash_command=sh(f"{PY} -m export.expected_kpis && {PY} -m pytest tests/test_pipeline_outputs.py -q"))
    export = BashOperator(task_id="export_for_power_bi", bash_command=sh(f"{PY} -m export.to_powerbi"))

    generate >> load >> dbt_build
    dbt_build >> [recon, forecast]
    recon >> recon_score
    [recon_score, forecast] >> kpis >> export
