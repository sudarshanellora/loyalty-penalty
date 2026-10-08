"""Every assumption used in the project, in one place.

basis: 'sourced'  = taken directly from a published release (see data/sources.csv)
       'derived'  = calculated from sourced figures
       'assumed'  = analyst judgement; tested in the sensitivity analysis
"""

ASSUMPTIONS = [
    # name, value, unit, basis
    ("benchmark_rate_pct", 3.46, "pct", "sourced"),         # avg new fixed rate, June 2026 (CBI)
    ("reneg_rate_pct", 3.23, "pct", "sourced"),             # avg fixed renegotiation rate, June 2026 (CBI)
    ("material_gap_threshold_pct", 4.00, "pct", "assumed"), # loans above this are 'materially above market'
    ("switch_cost_eur", 1850, "eur", "derived"),            # legal 1,200-1,500 + valuation 150, plus 23% VAT, midpoint
    ("funding_cost_pct", 2.25, "pct", "assumed"),           # funds transfer price used for margin
    ("min_switch_balance_eur", 30000, "eur", "assumed"),    # below this switching rarely pays
    ("max_switch_ltv_pct", 90, "pct", "assumed"),
    ("rolloff_window_months", 12, "months", "assumed"),
    ("rollover_rate_pct", 3.96, "pct", "sourced"),          # avg new variable rate, June 2026 (CBI)
    ("trigger_recall", 0.90, "share", "assumed"),           # switchers whose solicitor requests redemption figures
    ("trigger_precision", 0.70, "share", "assumed"),        # redemption requests that are real switches
    ("offer_acceptance", 0.35, "share", "assumed"),         # switchers who accept a matching offer at that stage
    ("retention_desk_cost_eur", 500000, "eur", "assumed"),  # annual running cost of the desk
]

SYNTHETIC = {
    "n_loans": 50_000,
    "seed": 42,
    "balance_sigma": 0.65,          # lognormal dispersion (assumed)
    "share_variable": 0.15,         # BPFI, June 2024
    "share_tracker": 0.18,          # BPFI, June 2024
    "target_variable_rate": 4.15,   # CBI Table A, banks, June 2025
    "target_tracker_rate": 3.39,    # CBI Table A, banks, June 2025
    "arrears_share": 0.021,         # banks: 0.88% over 90 days (derived) + 1.2% early arrears (CBI Q2 2026)
}

def as_dict():
    return {n: v for n, v, _, _ in ASSUMPTIONS}
