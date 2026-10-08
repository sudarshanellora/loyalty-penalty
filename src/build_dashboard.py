"""Inject the analysis results into the dashboard template -> dashboard/index.html"""
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

USED_SOURCES = ["CBI_FRONTIER_2026Q2", "CBI_RIR_2026M06", "CBI_RIR_2025M06", "CBI_ARREARS_2026Q2",
                "BPFI_DD_2026Q2", "BPFI_DD_2026Q1", "BPFI_DD_2025Q4", "BPFI_STOCK_2024",
                "AIB_FY2025", "BOI_FY2025", "PTSB_FY2025", "BONKERS_FEES", "CPC_2026"]


def main():
    res = json.loads((OUT / "results.json").read_text())
    con = sqlite3.connect(OUT / "loyalty_penalty.db")
    buckets = pd.read_csv(OUT / "tables" / "market_rate_buckets.csv")[
        ["lender_type", "rate_lower", "rate_upper", "rate_mid", "share", "accounts"]]
    switching = pd.read_sql("""SELECT quarter, volume, value_eur_m FROM bpfi_drawdowns
                               WHERE segment='Re-mortgage/Switching' ORDER BY quarter""", con)
    cdf = pd.read_sql("SELECT rate_upper_pct, bank_cum_pct FROM rate_distribution ORDER BY rate_upper_pct", con)
    src = pd.read_sql("SELECT source_id, publisher, title, url FROM sources", con).set_index("source_id")
    stress = pd.read_csv(OUT / "tables" / "bank_stress.csv")
    con.close()

    data = {
        "market": res["market"], "bank": res["bank"],
        "buckets": buckets.round(5).to_dict("records"),
        "switching": switching.to_dict("records"),
        "bank_cdf": cdf.values.tolist(),
        "stress": stress.to_dict("records"),
        "sources": [src.loc[s].to_dict() for s in USED_SOURCES],
    }
    html = (ROOT / "src" / "dashboard_template.html").read_text().replace("__DATA__", json.dumps(data))
    (ROOT / "dashboard" / "index.html").write_text(html)
    print("dashboard/index.html", f"{len(html) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
