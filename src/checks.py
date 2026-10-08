"""Checks that the numbers hang together. Run after the pipeline; exits non-zero on failure."""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
con = sqlite3.connect(OUT / "loyalty_penalty.db")
res = json.loads((OUT / "results.json").read_text())
q = lambda name: pd.read_csv(OUT / "sql_results" / f"{name}.csv")
fails = []


def check(label, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + label + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails.append(label)


# 1. Source data reconciles to published totals
rec = q("q01_data_quality_reconciliation")
check("BPFI segments sum to the published total in every quarter", (rec.volume_difference == 0).all())
check("BPFI values reconcile within rounding (EUR 1m)", (rec.value_difference_eur_m.abs() <= 1).all())
s25 = pd.read_sql("""SELECT SUM(volume) v, SUM(value_eur_m) e FROM bpfi_drawdowns
                     WHERE segment='Re-mortgage/Switching' AND quarter LIKE '2025%'""", con).iloc[0]
check("2025 switching value matches BPFI's 'almost EUR 1.7bn'", 1690 <= s25.e <= 1700, f"{s25.e:.0f}")
t25 = pd.read_sql("SELECT SUM(volume) v FROM bpfi_drawdowns WHERE segment='Total' AND quarter LIKE '2025%'", con).iloc[0, 0]
check("2025 total drawdowns match BPFI's published 46,358", t25 == 46358, str(t25))
yoy = q("q02_switching_trend").set_index("quarter").yoy_volume_pct
check("Switching growth matches BPFI (Q4 25 +33.9%, Q1 26 +3.6%, Q2 26 +13.6%)",
      [yoy["2025Q4"], yoy["2026Q1"], yoy["2026Q2"]] == [33.9, 3.6, 13.6])
nl = pd.read_sql("SELECT * FROM new_lending_rates", con).set_index("month")
check("Rate series is consistent with the stated annual change (June 2026 down 11bp)",
      round((nl.loc["2025-06", "ie_new_rate_pct"] - nl.loc["2026-06", "ie_new_rate_pct"]) * 100) == 11)
d = pd.read_sql("SELECT * FROM rate_distribution ORDER BY rate_upper_pct", con)
for c in ["bank_cum_pct", "lending_nonbank_cum_pct", "nonlending_nonbank_cum_pct"]:
    check(f"{c} is non-decreasing and ends at 100", d[c].is_monotonic_increasing and d[c].iloc[-1] == 100)

# 2. SQL and Python agree
h = q("q07_headline").set_index("lender_type").loc["ALL LENDERS"]
m = res["market"]
check("Households above 4%: SQL = Python", abs(h.households_above_4pct - m["households_above_threshold"]) <= 100,
      f"{h.households_above_4pct:.0f} vs {m['households_above_threshold']}")
check("Excess interest: SQL = Python", abs(h.excess_interest_eur_m_per_year - m["excess_interest_eur_m"]) < 1)
sw = q("q03_annual_switching_rate").iloc[-1]
check("Annual switching rate: SQL = Python", sw.switches_4q == m["switches_last_4q"]
      and sw.pct_of_pdh_accounts == m["switch_rate_pct_of_accounts"])

# 3. Simulated book reproduces its targets
cal = q("q12_calibration_check")
cal["gap"] = (cal.published - cal.simulated).abs()
check("Simulated rates and mix within 0.1 of published figures", (cal.gap[1:] <= 0.1).all(), f"max {cal.gap[1:].max():.2f}")
check("Simulated average balance matches", cal.gap[0] < 1)

# 4. Model sanity
b = res["bank"]
check("Expected switchers = market rate x book", abs(b["book"]["expected_switchers"] - 0.0088 * 50000) < 1)
o = {x["option"][0]: x for x in b["options"]}
check("Option ordering: A best, B worst", o["A"]["nii_eur_m"] > o["C"]["nii_eur_m"] > o["B"]["nii_eur_m"])
gross, fund = b["book"]["gross_interest_eur_m"], b["book"]["funding_cost_eur_m"]
check("Net interest = interest income - funding cost", abs(gross - fund - b["book"]["net_interest_eur_m"]) < 0.02)
be = pd.read_csv(OUT / "tables" / "bank_breakeven_by_rate.csv")
row = be[(be.current_rate_pct == 4.25) & (be.funding_cost_pct == 2.25)].iloc[0]
check("Break-even formula: (4.25-3.46)/(4.25-2.25) = 39.5%", row.breakeven_leave_probability_pct == 39.5)

con.close()
print(f"\n{len(fails)} failed" if fails else "\nAll checks passed")
sys.exit(1 if fails else 0)
