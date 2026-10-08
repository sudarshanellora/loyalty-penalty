"""Build the SQLite database from the CSV files and the simulated loan book."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import ASSUMPTIONS
from simulate_loan_book import simulate

ROOT = Path(__file__).resolve().parents[1]
DATA, DB = ROOT / "data", ROOT / "outputs" / "loyalty_penalty.db"

TABLES = ["sources", "rate_distribution", "new_lending_rates", "outstanding_pdh_by_lender",
          "market_size", "bpfi_drawdowns", "bank_financials", "switching_costs"]


def main():
    DB.parent.mkdir(exist_ok=True)
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.executescript((ROOT / "sql" / "01_schema.sql").read_text())

    for t in TABLES:
        df = pd.read_csv(DATA / f"{t}.csv", dtype={"reference_month": str, "month": str, "reference_period": str})
        df.to_sql(t, con, if_exists="append", index=False)
        print(f"{t:28s} {len(df):>6,} rows")

    pd.DataFrame(ASSUMPTIONS, columns=["name", "value", "unit", "basis"]).to_sql(
        "assumptions", con, if_exists="append", index=False)

    dist = pd.read_sql("SELECT * FROM rate_distribution ORDER BY rate_upper_pct", con)
    avg_bal = pd.read_sql("SELECT avg_balance_eur FROM v_lender_base WHERE lender_type='bank'", con).iloc[0, 0]
    book = simulate(dist, avg_bal)
    book.to_sql("loan_book_synthetic", con, if_exists="append", index=False)
    book.to_csv(DATA / "loan_book_synthetic.csv", index=False)
    print(f"{'loan_book_synthetic':28s} {len(book):>6,} rows (simulated; variable noise sd {book.attrs['variable_noise_sd']:.2f})")

    con.commit()
    con.close()
    print(f"\nDatabase written to {DB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
