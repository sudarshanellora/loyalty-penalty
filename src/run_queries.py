"""Run every named query in sql/02_queries.sql and export the results."""
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "sql_results"


def named_queries():
    text = (ROOT / "sql" / "02_queries.sql").read_text()
    for block in re.split(r"(?m)^-- name:\s*", text)[1:]:
        name, _, body = block.partition("\n")
        yield name.strip(), body.strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ROOT / "outputs" / "loyalty_penalty.db")
    for name, sql in named_queries():
        df = pd.read_sql(sql, con)
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"\n=== {name} ===\n{df.to_string(index=False)}")
    con.close()


if __name__ == "__main__":
    main()
