#!/usr/bin/env bash
# Rebuild everything from the CSV files in data/.
set -euo pipefail
cd "$(dirname "$0")"
python3 src/build_db.py
mkdir -p outputs/sql_results
python3 src/run_queries.py > outputs/sql_results/all_results.txt
python3 src/analysis.py > outputs/analysis_log.txt
python3 src/charts.py
python3 src/build_dashboard.py
python3 src/checks.py
