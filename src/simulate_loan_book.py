"""Simulate a loan book for a FICTIONAL mid-sized Irish lender.

No real customer data is used. The book is calibrated to published aggregates:
  - interest rates follow the Central Bank's June 2026 distribution for bank-held PDH loans
  - the average balance matches the derived average for bank-held PDH accounts
  - the product mix matches the BPFI split of the PDH stock
  - the variable-rate average is tuned to the Central Bank's published bank average
Everything else (terms, loan-to-value, roll-off dates, balance dispersion) is assumed.
"""
import numpy as np
import pandas as pd

from config import SYNTHETIC


def inverse_cdf_sample(u, thresholds, cum_pct):
    """Draw rates from a cumulative distribution, linear within each 0.5-point bucket."""
    x = np.concatenate([[0.0], thresholds])
    p = np.concatenate([[0.0], np.asarray(cum_pct) / 100.0])
    # remove flat steps so interpolation is well defined
    keep = np.concatenate([[True], np.diff(p) > 0])
    return np.interp(u, p[keep], x[keep])


def simulate(dist: pd.DataFrame, avg_balance: float) -> pd.DataFrame:
    cfg = SYNTHETIC
    rng = np.random.default_rng(cfg["seed"])
    n = cfg["n_loans"]

    rate = inverse_cdf_sample(rng.random(n), dist["rate_upper_pct"].values, dist["bank_cum_pct"].values)

    balance = rng.lognormal(mean=0.0, sigma=cfg["balance_sigma"], size=n)
    balance = np.clip(balance * avg_balance / balance.mean(), 5_000, 1_500_000)
    balance = balance * avg_balance / balance.mean()

    # Variable loans: the higher-rate end of the book, with noise tuned so that
    # the simulated variable average matches the published bank average.
    n_var = int(round(cfg["share_variable"] * n))
    best = None
    for sd in np.arange(0.0, 2.01, 0.02):
        score = rate + np.random.default_rng(cfg["seed"] + 1).normal(0, sd, n)
        idx = np.argsort(-score)[:n_var]
        err = abs(rate[idx].mean() - cfg["target_variable_rate"])
        if best is None or err < best[0]:
            best = (err, sd, idx)
    _, noise_sd, var_idx = best

    product = np.full(n, "fixed", dtype=object)
    product[var_idx] = "variable"

    # Trackers: loans closest to the published tracker average, with noise.
    n_trk = int(round(cfg["share_tracker"] * n))
    rest = np.where(product == "fixed")[0]
    closeness = -np.abs(rate[rest] - cfg["target_tracker_rate"]) + rng.normal(0, 0.6, rest.size)
    product[rest[np.argsort(-closeness)[:n_trk]]] = "tracker"

    remaining = rng.integers(60, 361, n)
    rolloff = np.where(product == "fixed", rng.integers(1, 61, n), -1)
    ltv = np.clip(rng.beta(2.6, 2.6, n) * 100, 5, 105)
    arrears = (rng.random(n) < cfg["arrears_share"]).astype(int)

    df = pd.DataFrame({
        "loan_id": np.arange(1, n + 1),
        "product_type": product,
        "current_rate_pct": np.round(rate, 2),
        "balance_eur": np.round(balance, 0),
        "remaining_months": remaining,
        "months_to_rolloff": rolloff,
        "current_ltv_pct": np.round(ltv, 1),
        "arrears_flag": arrears,
    })
    df["months_to_rolloff"] = df["months_to_rolloff"].where(df["months_to_rolloff"] > 0).astype("Int64")
    df.attrs["variable_noise_sd"] = float(noise_sd)
    return df
