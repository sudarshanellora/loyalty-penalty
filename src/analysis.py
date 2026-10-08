"""Loyalty Penalty: market analysis, bank decision model and profit-and-loss impact.

Run after build_db.py. Writes outputs/results.json and CSV tables in outputs/tables/.
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import as_dict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
TABLES = OUT / "tables"
A = as_dict()


# ---------------------------------------------------------------- market side
def bucket_table(con):
    """Accounts per lender type and half-point rate bucket (independent of the SQL view)."""
    d = pd.read_sql("SELECT * FROM rate_distribution ORDER BY rate_upper_pct", con)
    base = pd.read_sql("SELECT * FROM v_lender_base", con).set_index("lender_type")
    cols = {"bank": "bank_cum_pct", "lending_non_bank": "lending_nonbank_cum_pct",
            "nonlending_non_bank": "nonlending_nonbank_cum_pct"}
    rows = []
    for lender, col in cols.items():
        share = d[col].diff().fillna(d[col]) / 100
        for up, s in zip(d["rate_upper_pct"], share):
            rows.append({"lender_type": lender, "rate_lower": up - 0.5, "rate_upper": up,
                         "rate_mid": up - 0.25, "share": s,
                         "accounts": s * base.loc[lender, "accounts"],
                         "avg_balance": base.loc[lender, "avg_balance_eur"]})
    return pd.DataFrame(rows), base


def penalty(b, benchmark, threshold, balance_factor=1.0, position=0.5):
    """Households above the threshold and the interest they pay above the benchmark.

    position: where loans sit inside each half-point bucket (0 = bottom, 0.5 = midpoint, 1 = top).
    """
    x = b[b["rate_lower"] >= threshold].copy()
    rate = x["rate_lower"] + 0.5 * position
    x["excess"] = x["accounts"] * x["avg_balance"] * balance_factor * (rate - benchmark) / 100
    return x["accounts"].sum(), x["excess"].sum(), x


def market_analysis(con):
    b, base = bucket_table(con)
    hh, eur, x = penalty(b, A["benchmark_rate_pct"], A["material_gap_threshold_pct"])
    by_lender = (x.groupby("lender_type").agg(households=("accounts", "sum"), excess_eur=("excess", "sum"))
                 .assign(avg_per_household=lambda t: t.excess_eur / t.households).reset_index())

    ms = pd.read_sql("SELECT metric, value FROM market_size", con).set_index("metric")["value"]
    arrears = ms["pdh_arrears_over_90d"] + ms["pdh_arrears_under_90d"]

    # Sensitivity of the headline to the three judgement calls behind it
    sens = []
    for label, bench in [("Renegotiation rate, 3.23%", A["reneg_rate_pct"]),
                         ("New fixed rate, 3.46% (base)", A["benchmark_rate_pct"]),
                         ("New variable rate, 3.96%", A["rollover_rate_pct"])]:
        for bal_label, f in [("Average balance", 1.0), ("Balances 25% smaller", 0.75)]:
            for pos_label, pos in [("bottom of bucket", 0.0), ("midpoint", 0.5), ("top of bucket", 1.0)]:
                h, e, _ = penalty(b, bench, A["material_gap_threshold_pct"], f, pos)
                sens.append({"benchmark": label, "balance": bal_label, "rate_position": pos_label,
                             "households": round(h), "excess_eur_m": round(e / 1e6, 1),
                             "per_household_eur": round(e / h)})
    sens = pd.DataFrame(sens)

    thresholds = []
    for t in [3.5, 4.0, 4.5, 5.0, 6.0]:
        h, e, _ = penalty(b, A["benchmark_rate_pct"], t)
        thresholds.append({"paying_more_than_pct": t, "households": round(h),
                           "share_of_all_pdh_pct": round(100 * h / ms["pdh_accounts_total"], 1),
                           "excess_eur_m": round(e / 1e6, 1), "per_household_eur": round(e / h)})
    thresholds = pd.DataFrame(thresholds)

    sw = pd.read_sql("""SELECT quarter, volume, value_eur_m FROM bpfi_drawdowns
                        WHERE segment='Re-mortgage/Switching' ORDER BY quarter""", con)
    last4 = sw.tail(4)
    nl = pd.read_sql("SELECT * FROM new_lending_rates ORDER BY month", con).set_index("month")
    reneg_month = nl.loc["2026-06", "reneg_volume_eur_m"]

    nii_2025 = pd.read_sql("SELECT SUM(net_interest_income_eur_m) v FROM bank_financials WHERE fiscal_year=2025",
                           con).iloc[0, 0]
    bank_excess = by_lender.set_index("lender_type").loc["bank", "excess_eur"]

    res = {
        "benchmark_rate_pct": A["benchmark_rate_pct"],
        "threshold_pct": A["material_gap_threshold_pct"],
        "households_above_threshold": round(hh),
        "share_of_pdh_accounts_pct": round(100 * hh / ms["pdh_accounts_total"], 1),
        "excess_interest_eur_m": round(eur / 1e6, 1),
        "avg_per_household_eur": round(eur / hh),
        "households_floor_excluding_all_arrears": round(hh - arrears),
        "by_lender": by_lender.round(0).to_dict("records"),
        "switches_last_4q": int(last4["volume"].sum()),
        "switch_value_last_4q_eur_m": float(last4["value_eur_m"].sum()),
        "switch_rate_pct_of_accounts": round(100 * last4["volume"].sum() / ms["pdh_accounts_total"], 2),
        "switch_rate_pct_of_above_threshold": round(100 * last4["volume"].sum() / hh, 1),
        "avg_switch_loan_eur_latest": round(sw.iloc[-1]["value_eur_m"] * 1e6 / sw.iloc[-1]["volume"], -2),
        "reneg_june_2026_eur_m": float(reneg_month),
        "switch_monthly_avg_q2_2026_eur_m": round(sw.iloc[-1]["value_eur_m"] / 3, 1),
        "reneg_to_switch_ratio": round(reneg_month / (sw.iloc[-1]["value_eur_m"] / 3), 1),
        "three_banks_nii_2025_eur_m": float(nii_2025),
        "bank_excess_as_pct_of_three_banks_nii": round(100 * bank_excess / 1e6 / nii_2025, 1),
        "sensitivity_range_eur_m": [float(sens["excess_eur_m"].min()), float(sens["excess_eur_m"].max())],
    }
    b.round(4).to_csv(TABLES / "market_rate_buckets.csv", index=False)
    sens.to_csv(TABLES / "headline_sensitivity.csv", index=False)
    thresholds.to_csv(TABLES / "headline_by_threshold.csv", index=False)
    by_lender.round(0).to_csv(TABLES / "headline_by_lender.csv", index=False)
    return res, b, sens, thresholds


# ------------------------------------------------------------------ bank side
def prepare_book(con):
    lb = pd.read_sql("SELECT * FROM loan_book_synthetic", con)
    eligible = ((lb.arrears_flag == 0) & (lb.balance_eur >= A["min_switch_balance_eur"])
                & (lb.current_ltv_pct <= A["max_switch_ltv_pct"]))
    rolling = (lb.product_type == "fixed") & (lb.months_to_rolloff <= A["rolloff_window_months"])
    in_play = eligible & ((lb.product_type == "variable") | rolling)
    # rate paid if the customer does nothing: fixed loans roll onto the variable rate
    lb["do_nothing_rate"] = np.where(rolling, A["rollover_rate_pct"], lb.current_rate_pct)
    lb["in_play"] = in_play
    lb["gap"] = np.where(in_play, np.maximum(lb.do_nothing_rate - A["benchmark_rate_pct"], 0), 0.0)
    lb["annual_saving"] = lb.balance_eur * lb.gap / 100
    return lb


def switch_probabilities(lb, book_switch_rate, shape="proportional"):
    """Annual probability that each in-play loan switches lender.

    Calibrated so expected switches across the whole book equal the market-wide rate.
    'proportional': probability rises in line with the saving on offer.
    'flat': every in-play loan with a saving has the same probability.
    """
    w = lb["annual_saving"].values if shape == "proportional" else (lb["annual_saving"].values > 0).astype(float)
    target = book_switch_rate * len(lb)
    k = target / w.sum()
    p = np.minimum(k * w, 1.0)
    for _ in range(20):                       # re-scale if the cap at 1 binds
        free = p < 1
        if abs(p.sum() - target) < 1e-6 or not free.any():
            break
        k *= (target - (~free).sum()) / (k * w[free]).sum()
        p = np.minimum(k * w, 1.0)
    return p


def options(lb, p, funding=None, precision=None, acceptance=None, recall=None):
    f = A["funding_cost_pct"] if funding is None else funding
    P = A["trigger_precision"] if precision is None else precision
    a = A["offer_acceptance"] if acceptance is None else acceptance
    R = A["trigger_recall"] if recall is None else recall
    bench = A["benchmark_rate_pct"]
    bal, r, gap = lb.balance_eur.values, lb.do_nothing_rate.values, lb.gap.values

    base_nii = (bal * (r - f) / 100).sum()                       # nobody leaves, nobody reprices
    lost_a = (p * bal * (r - f) / 100).sum()                     # A: margin lost to switching
    nii_a = base_nii - lost_a

    target = gap >= 0.5                                          # B: reprice everyone 0.5+ points above market
    giveaway_b = (bal * gap / 100)[target].sum()
    still_lost_b = (p * bal * (r - f) / 100)[~target].sum()
    nii_b = base_nii - giveaway_b - still_lost_b

    # C: offer only when an intent signal fires
    saved_c = R * a * (p * bal * (bench - f) / 100).sum()        # switchers kept at the market margin
    lost_c = lost_a                                              # the margin they were paying is gone either way
    false_pos = R * (1 - P) / P                                  # flagged non-switchers per expected switcher
    giveaway_c = false_pos * (p * bal * gap / 100).sum()
    nii_c = base_nii - lost_c + saved_c - giveaway_c - A["retention_desk_cost_eur"]

    return {
        "baseline_nii": base_nii,
        "expected_switchers": p.sum(),
        "A": {"nii": nii_a, "lost_to_switching": lost_a},
        "B": {"nii": nii_b, "giveaway": giveaway_b, "loans_repriced": int(target.sum())},
        "C": {"nii": nii_c, "saved": saved_c, "giveaway": giveaway_c,
              "offers_made": p.sum() * R / P, "customers_kept": p.sum() * R * a},
    }


def breakeven_precision(lb, p, funding, acceptance):
    """Precision at which a trigger-based offer stops losing money (desk cost aside)."""
    bal, gap = lb.balance_eur.values, lb.gap.values
    kept = acceptance * (p * bal * (A["benchmark_rate_pct"] - funding) / 100).sum()
    give = (p * bal * gap / 100).sum()
    # kept = (1-P)/P * give  ->  P = give / (give + kept)
    return give / (give + kept)


def bank_analysis(con, market):
    lb = prepare_book(con)
    book_rate = market["switch_rate_pct_of_accounts"] / 100
    p = switch_probabilities(lb, book_rate)
    lb["p_switch"] = p
    o = options(lb, p)

    book_bal = lb.balance_eur.sum()
    gross_interest = (lb.balance_eur * lb.current_rate_pct / 100).sum()
    funding_cost = book_bal * A["funding_cost_pct"] / 100

    def bps(x):
        return 1e4 * x / book_bal

    opt_table = pd.DataFrame([
        {"option": "A. Status quo", "nii_eur_m": o["A"]["nii"] / 1e6,
         "vs_status_quo_eur_m": 0.0, "book_margin_bps_change": 0.0},
        {"option": "B. Reprice everyone 0.5+ points above market", "nii_eur_m": o["B"]["nii"] / 1e6,
         "vs_status_quo_eur_m": (o["B"]["nii"] - o["A"]["nii"]) / 1e6,
         "book_margin_bps_change": bps(o["B"]["nii"] - o["A"]["nii"])},
        {"option": "C. Match the market only when a redemption request arrives", "nii_eur_m": o["C"]["nii"] / 1e6,
         "vs_status_quo_eur_m": (o["C"]["nii"] - o["A"]["nii"]) / 1e6,
         "book_margin_bps_change": bps(o["C"]["nii"] - o["A"]["nii"])},
    ]).round(2)

    # C across signal quality: precision x acceptance
    grid = []
    desk = A["retention_desk_cost_eur"]
    for P in [0.10, 0.25, 0.50, 0.70, 0.90]:
        for a in [0.20, 0.35, 0.50, 0.75]:
            oc = options(lb, p, precision=P, acceptance=a)
            net = oc["C"]["nii"] - oc["A"]["nii"] + desk
            grid.append({"precision": P, "acceptance": a,
                         "net_before_running_cost_eur_m": round(net / 1e6, 2),
                         "vs_status_quo_eur_m": round((net - desk) / 1e6, 2)})
    grid = pd.DataFrame(grid)

    be = {f"{a:.2f}": round(100 * breakeven_precision(lb, p, A["funding_cost_pct"], a), 1)
          for a in [0.20, 0.35, 0.50, 0.75]}
    net_c = o["C"]["nii"] - o["A"]["nii"] + desk          # option C before its running cost
    breakeven_multiple = desk / net_c if net_c > 0 else float("nan")

    # Per-loan break-even: how likely must a customer be to leave before matching the market pays?
    be_rows = []
    for r in [3.75, 4.00, 4.25, 4.50, 5.00]:
        for f in [1.75, 2.25, 2.75]:
            be_rows.append({"current_rate_pct": r, "funding_cost_pct": f,
                            "breakeven_leave_probability_pct":
                                round(100 * (r - A["benchmark_rate_pct"]) / (r - f), 1)})
    be_table = pd.DataFrame(be_rows)

    # Stress: what if switching and internal repricing both rise?
    stress = []
    in_play_above_reneg = lb.in_play & (lb.do_nothing_rate > A["reneg_rate_pct"])
    reprice_pool = (lb.balance_eur * (lb.do_nothing_rate - A["reneg_rate_pct"]) / 100)[in_play_above_reneg].sum()
    for mult in [1, 2, 4]:
        pm = switch_probabilities(lb, book_rate * mult)
        lost = (pm * lb.balance_eur * (lb.do_nothing_rate - A["funding_cost_pct"]) / 100).sum()
        for q in [0.0, 0.10, 0.25, 0.50]:
            # customers who reprice internally stay; those who would have switched are counted once
            internal = q * ((1 - pm) * lb.balance_eur * (lb.do_nothing_rate - A["reneg_rate_pct"]) / 100
                            )[in_play_above_reneg].sum()
            stress.append({"switching_multiple": mult, "book_switch_rate_pct": round(100 * book_rate * mult, 2),
                           "internal_repricing_share": q,
                           "nii_lost_eur_m": round((lost + internal) / 1e6, 2),
                           "pct_of_book_net_interest": round(100 * (lost + internal) / o["baseline_nii"], 1),
                           "book_margin_bps": round(bps(lost + internal), 1)})
    stress = pd.DataFrame(stress)

    shape_alt = options(lb, switch_probabilities(lb, book_rate, "flat"))

    # Tipping point: how high must switching go before repricing everyone beats doing nothing?
    target = lb.gap.values >= 0.5
    tip = None
    for mult in np.arange(1, 40.01, 0.1):
        pm = switch_probabilities(lb, book_rate * mult)
        om = options(lb, pm)
        if om["B"]["nii"] >= om["A"]["nii"]:
            tip = {"switching_multiple": round(float(mult), 1),
                   "book_switch_rate_pct": round(100 * book_rate * mult, 1),
                   "leave_rate_among_repriced_pct": round(100 * pm[target].mean(), 1)}
            break
    today_leave_rate_target = round(100 * p[target].mean(), 1)

    seg = {
        "loans": len(lb),
        "book_balance_eur_m": book_bal / 1e6,
        "gross_interest_eur_m": gross_interest / 1e6,
        "funding_cost_eur_m": funding_cost / 1e6,
        "net_interest_eur_m": (gross_interest - funding_cost) / 1e6,
        "book_margin_pct": 100 * (gross_interest - funding_cost) / book_bal,
        "in_play_loans": int(lb.in_play.sum()),
        "in_play_with_saving": int((lb.annual_saving > 0).sum()),
        "in_play_balance_eur_m": lb.balance_eur[lb.in_play].sum() / 1e6,
        "interest_above_market_eur_m": lb.annual_saving.sum() / 1e6,
        "expected_switchers": o["expected_switchers"],
        "avg_p_among_savers_pct": 100 * p[lb.annual_saving > 0].mean(),
    }
    res = {
        "book": {k: round(v, 2) for k, v in seg.items()},
        "options": opt_table.to_dict("records"),
        "option_detail": {
            "A_lost_to_switching_eur_m": round(o["A"]["lost_to_switching"] / 1e6, 2),
            "B_giveaway_eur_m": round(o["B"]["giveaway"] / 1e6, 2),
            "B_loans_repriced": o["B"]["loans_repriced"],
            "C_saved_eur_m": round(o["C"]["saved"] / 1e6, 2),
            "C_giveaway_eur_m": round(o["C"]["giveaway"] / 1e6, 2),
            "C_offers_made": round(o["C"]["offers_made"]),
            "C_customers_kept": round(o["C"]["customers_kept"]),
            "C_desk_cost_eur_m": A["retention_desk_cost_eur"] / 1e6,
            "C_net_before_running_cost_eur_m": round(net_c / 1e6, 2),
            "C_breakeven_switching_multiple": round(breakeven_multiple, 1),
            "C_breakeven_book_switch_rate_pct": round(100 * book_rate * breakeven_multiple, 1),
        },
        "run_rate_net_interest_eur_m": round(o["baseline_nii"] / 1e6, 2),
        "breakeven_precision_pct_by_acceptance": be,
        "flat_propensity_check": {
            "A_lost_eur_m": round(shape_alt["A"]["lost_to_switching"] / 1e6, 2),
            "C_vs_A_eur_m": round((shape_alt["C"]["nii"] - shape_alt["A"]["nii"]) / 1e6, 2)},
        "reprice_pool_eur_m": round(reprice_pool / 1e6, 2),
        "blanket_reprice_tipping_point": tip,
        "leave_rate_among_repriced_today_pct": today_leave_rate_target,
        "B_cost_pct_of_book_net_interest": round(100 * (o["A"]["nii"] - o["B"]["nii"]) / o["A"]["nii"], 1),
        "A_loss_pct_of_run_rate": round(100 * o["A"]["lost_to_switching"] / o["baseline_nii"], 1),
    }
    opt_table.to_csv(TABLES / "bank_options.csv", index=False)
    grid.to_csv(TABLES / "bank_option_c_grid.csv", index=False)
    be_table.to_csv(TABLES / "bank_breakeven_by_rate.csv", index=False)
    stress.to_csv(TABLES / "bank_stress.csv", index=False)
    return res, grid, be_table, stress


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OUT / "loyalty_penalty.db")
    market, b, sens, thr = market_analysis(con)
    bank, grid, be_table, stress = bank_analysis(con, market)
    con.close()
    (OUT / "results.json").write_text(json.dumps({"market": market, "bank": bank}, indent=2))
    print(json.dumps({"market": market, "bank": bank}, indent=2))
    print("\nThresholds\n", thr.to_string(index=False))
    print("\nSensitivity\n", sens.to_string(index=False))
    print("\nOption C grid, net before running cost\n",
          grid.pivot(index="precision", columns="acceptance", values="net_before_running_cost_eur_m"))
    print("\nBreak-even leave probability\n",
          be_table.pivot(index="current_rate_pct", columns="funding_cost_pct", values="breakeven_leave_probability_pct"))
    print("\nStress\n", stress.to_string(index=False))


if __name__ == "__main__":
    main()
