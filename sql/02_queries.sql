-- Loyalty Penalty project: analytical queries (SQLite)
-- Each query is named with a "-- name:" line so src/run_queries.py can run and export it.

-- name: q01_data_quality_reconciliation
-- Do the BPFI segments add up to the published total in every quarter?
SELECT
    quarter,
    SUM(CASE WHEN segment <> 'Total' THEN volume END)       AS sum_of_segments,
    MAX(CASE WHEN segment = 'Total'  THEN volume END)       AS published_total,
    SUM(CASE WHEN segment <> 'Total' THEN volume END)
      - MAX(CASE WHEN segment = 'Total' THEN volume END)    AS volume_difference,
    ROUND(SUM(CASE WHEN segment <> 'Total' THEN value_eur_m END)
      - MAX(CASE WHEN segment = 'Total' THEN value_eur_m END), 1) AS value_difference_eur_m
FROM bpfi_drawdowns
GROUP BY quarter
ORDER BY quarter;

-- name: q02_switching_trend
-- Switching volume, average loan, share of all drawdowns and year-on-year growth.
WITH s AS (
    SELECT quarter, volume, value_eur_m
    FROM bpfi_drawdowns
    WHERE segment = 'Re-mortgage/Switching'
),
t AS (
    SELECT quarter, volume AS total_volume
    FROM bpfi_drawdowns
    WHERE segment = 'Total'
)
SELECT
    s.quarter,
    s.volume                                                    AS switches,
    s.value_eur_m,
    ROUND(s.value_eur_m * 1e6 / s.volume, -2)                   AS avg_switch_loan_eur,
    ROUND(100.0 * s.volume / t.total_volume, 1)                 AS share_of_drawdowns_pct,
    ROUND(100.0 * (s.volume * 1.0 / LAG(s.volume, 4) OVER (ORDER BY s.quarter) - 1), 1) AS yoy_volume_pct
FROM s
JOIN t USING (quarter)
ORDER BY s.quarter;

-- name: q03_annual_switching_rate
-- Rolling four-quarter switches against the stock of home-loan accounts.
WITH s AS (
    SELECT quarter, volume, value_eur_m
    FROM bpfi_drawdowns
    WHERE segment = 'Re-mortgage/Switching'
),
r AS (
    SELECT
        quarter,
        SUM(volume)      OVER (ORDER BY quarter ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS switches_4q,
        SUM(value_eur_m) OVER (ORDER BY quarter ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS value_4q_eur_m,
        COUNT(*)         OVER (ORDER BY quarter ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS quarters_in_window
    FROM s
)
SELECT
    r.quarter,
    r.switches_4q,
    r.value_4q_eur_m,
    ROUND(100.0 * r.switches_4q / m.value, 2) AS pct_of_pdh_accounts
FROM r
CROSS JOIN (SELECT value FROM market_size WHERE metric = 'pdh_accounts_total') m
WHERE r.quarters_in_window = 4
ORDER BY r.quarter;

-- name: q04_ireland_vs_euro_area
-- The gap between Irish and euro-area rates on new mortgages, in basis points.
SELECT
    month,
    ie_new_rate_pct,
    ea_new_rate_pct,
    ROUND((ie_new_rate_pct - ea_new_rate_pct) * 100) AS gap_bps,
    ie_rank_in_ea
FROM new_lending_rates
WHERE ea_new_rate_pct IS NOT NULL
ORDER BY month;

-- name: q05_rate_buckets_by_lender
-- Turn the cumulative distribution into accounts per half-point rate bucket.
SELECT
    b.lender_type,
    b.rate_lower_pct,
    b.rate_upper_pct,
    ROUND(b.share_pct, 2)                         AS share_of_loans_pct,
    CAST(ROUND(b.share_pct / 100.0 * l.accounts) AS INTEGER) AS est_accounts
FROM v_rate_buckets b
JOIN v_lender_base l USING (lender_type)
WHERE b.share_pct > 0
ORDER BY b.lender_type, b.rate_upper_pct;

-- name: q06_loyalty_penalty_by_bucket
-- Excess interest paid above the benchmark rate, by lender type and bucket.
WITH p AS (
    SELECT
        MAX(CASE WHEN name = 'benchmark_rate_pct' THEN value END)         AS benchmark,
        MAX(CASE WHEN name = 'material_gap_threshold_pct' THEN value END) AS threshold
    FROM assumptions
)
SELECT
    b.lender_type,
    b.rate_lower_pct || '-' || b.rate_upper_pct                         AS rate_bucket,
    CAST(ROUND(b.share_pct / 100.0 * l.accounts) AS INTEGER)            AS est_accounts,
    ROUND(b.rate_mid_pct - p.benchmark, 2)                              AS gap_pct_points,
    ROUND(l.avg_balance_eur * (b.rate_mid_pct - p.benchmark) / 100.0)   AS excess_interest_per_account_eur,
    ROUND(b.share_pct / 100.0 * l.accounts * l.avg_balance_eur
          * (b.rate_mid_pct - p.benchmark) / 100.0 / 1e6, 1)            AS excess_interest_eur_m
FROM v_rate_buckets b
JOIN v_lender_base l USING (lender_type)
CROSS JOIN p
WHERE b.rate_lower_pct >= p.threshold AND b.share_pct > 0
ORDER BY b.lender_type, b.rate_upper_pct;

-- name: q07_headline
-- The headline: how many households pay materially above market, and what it costs.
WITH p AS (
    SELECT
        MAX(CASE WHEN name = 'benchmark_rate_pct' THEN value END)         AS benchmark,
        MAX(CASE WHEN name = 'material_gap_threshold_pct' THEN value END) AS threshold
    FROM assumptions
),
x AS (
    SELECT
        b.lender_type,
        b.share_pct / 100.0 * l.accounts                                              AS accounts,
        b.share_pct / 100.0 * l.accounts * l.avg_balance_eur
            * (b.rate_mid_pct - p.benchmark) / 100.0                                  AS excess_eur
    FROM v_rate_buckets b
    JOIN v_lender_base l USING (lender_type)
    CROSS JOIN p
    WHERE b.rate_lower_pct >= p.threshold
)
SELECT
    lender_type,
    CAST(ROUND(SUM(accounts), -2) AS INTEGER)   AS households_above_4pct,
    ROUND(SUM(excess_eur) / 1e6, 0)             AS excess_interest_eur_m_per_year,
    ROUND(SUM(excess_eur) / SUM(accounts), -1)  AS avg_per_household_eur
FROM x
GROUP BY lender_type
UNION ALL
SELECT 'ALL LENDERS',
       CAST(ROUND(SUM(accounts), -2) AS INTEGER),
       ROUND(SUM(excess_eur) / 1e6, 0),
       ROUND(SUM(excess_eur) / SUM(accounts), -1)
FROM x;

-- name: q08_bank_benchmarks
-- What one basis point of margin is worth, and how income moved year on year.
SELECT
    bank,
    fiscal_year,
    net_interest_income_eur_m                                         AS nii_eur_m,
    net_interest_margin_pct                                           AS nim_pct,
    cost_income_ratio_pct                                             AS cir_pct,
    ROUND(net_interest_income_eur_m / net_interest_margin_pct / 10, 1) AS avg_earning_assets_eur_bn,
    ROUND(net_interest_income_eur_m / net_interest_margin_pct / 100, 1) AS nii_per_bp_of_nim_eur_m,
    ROUND(net_interest_income_eur_m
          - LAG(net_interest_income_eur_m) OVER (PARTITION BY bank ORDER BY fiscal_year)) AS nii_change_eur_m,
    ROUND((net_interest_margin_pct
          - LAG(net_interest_margin_pct) OVER (PARTITION BY bank ORDER BY fiscal_year)) * 100) AS nim_change_bps
FROM bank_financials
ORDER BY bank, fiscal_year;

-- name: q09_book_segmentation
-- Simulated book: who is in play for switching, and how much interest is at stake.
WITH p AS (
    SELECT
        MAX(CASE WHEN name = 'benchmark_rate_pct' THEN value END)      AS benchmark,
        MAX(CASE WHEN name = 'rolloff_window_months' THEN value END)   AS win,
        MAX(CASE WHEN name = 'min_switch_balance_eur' THEN value END)  AS min_bal,
        MAX(CASE WHEN name = 'max_switch_ltv_pct' THEN value END)      AS max_ltv,
        MAX(CASE WHEN name = 'rollover_rate_pct' THEN value END)       AS rollover
    FROM assumptions
),
seg AS (
    SELECT
        l.*,
        CASE
            WHEN l.arrears_flag = 1 OR l.balance_eur < p.min_bal OR l.current_ltv_pct > p.max_ltv
                THEN '5 Not eligible to switch'
            WHEN l.product_type = 'tracker'                              THEN '4 Tracker'
            WHEN l.product_type = 'fixed' AND l.months_to_rolloff > p.win THEN '3 Fixed, locked in'
            WHEN l.product_type = 'fixed'                                THEN '2 Fixed, rolling off within 12 months'
            WHEN l.current_rate_pct - p.benchmark >= 0.5                 THEN '1 Variable, 0.5+ points above market'
            ELSE '1b Variable, near market'
        END AS segment,
        -- rate the customer pays if they do nothing: fixed loans roll to the variable rate
        CASE WHEN l.product_type = 'fixed' AND l.months_to_rolloff <= p.win
             THEN p.rollover ELSE l.current_rate_pct END AS do_nothing_rate_pct,
        p.benchmark
    FROM loan_book_synthetic l CROSS JOIN p
)
SELECT
    segment,
    COUNT(*)                                                       AS loans,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)             AS pct_of_loans,
    ROUND(SUM(balance_eur) / 1e6)                                  AS balance_eur_m,
    ROUND(AVG(current_rate_pct), 2)                                AS avg_current_rate_pct,
    ROUND(SUM(balance_eur * MAX(do_nothing_rate_pct - benchmark, 0)) / 100.0 / 1e6, 1) AS interest_above_market_eur_m
FROM seg
GROUP BY segment
ORDER BY segment;

-- name: q10_rolloff_ladder
-- Simulated book: fixed-rate loans reaching the end of their term, by quarter.
WITH p AS (
    SELECT
        MAX(CASE WHEN name = 'benchmark_rate_pct' THEN value END) AS benchmark,
        MAX(CASE WHEN name = 'rollover_rate_pct' THEN value END)  AS rollover
    FROM assumptions
)
SELECT
    (months_to_rolloff - 1) / 3 + 1                                   AS quarters_ahead,
    COUNT(*)                                                          AS loans_rolling_off,
    ROUND(SUM(balance_eur) / 1e6)                                     AS balance_eur_m,
    ROUND(AVG(current_rate_pct), 2)                                   AS avg_fixed_rate_now_pct,
    ROUND(SUM(balance_eur) * (p.rollover - p.benchmark) / 100.0 / 1e6, 2) AS annual_cost_if_left_on_variable_eur_m,
    ROUND(SUM(SUM(balance_eur)) OVER (ORDER BY (months_to_rolloff - 1) / 3 + 1) / 1e6) AS cumulative_balance_eur_m
FROM loan_book_synthetic CROSS JOIN p
WHERE product_type = 'fixed' AND arrears_flag = 0 AND months_to_rolloff <= 24
GROUP BY quarters_ahead
ORDER BY quarters_ahead;

-- name: q11_concentration
-- Simulated book: how concentrated is the interest paid above market? (deciles by saving)
WITH p AS (SELECT value AS benchmark FROM assumptions WHERE name = 'benchmark_rate_pct'),
g AS (
    SELECT
        loan_id,
        balance_eur * (current_rate_pct - p.benchmark) / 100.0 AS annual_saving_eur
    FROM loan_book_synthetic CROSS JOIN p
    WHERE product_type = 'variable' AND arrears_flag = 0 AND current_rate_pct > p.benchmark
),
d AS (
    SELECT *, NTILE(10) OVER (ORDER BY annual_saving_eur DESC) AS decile FROM g
)
SELECT
    decile,
    COUNT(*)                                                    AS loans,
    ROUND(MIN(annual_saving_eur))                               AS min_saving_eur,
    ROUND(AVG(annual_saving_eur))                               AS avg_saving_eur,
    ROUND(100.0 * SUM(annual_saving_eur) / SUM(SUM(annual_saving_eur)) OVER (), 1) AS share_of_total_pct,
    ROUND(100.0 * SUM(SUM(annual_saving_eur)) OVER (ORDER BY decile)
          / SUM(SUM(annual_saving_eur)) OVER (), 1)             AS cumulative_share_pct
FROM d
GROUP BY decile
ORDER BY decile;

-- name: q12_calibration_check
-- Does the simulated book reproduce the published figures it was calibrated to?
SELECT 'Average balance, EUR' AS measure,
       ROUND((SELECT avg_balance_eur FROM v_lender_base WHERE lender_type = 'bank')) AS published,
       ROUND(AVG(balance_eur)) AS simulated
FROM loan_book_synthetic
UNION ALL
SELECT 'Variable average rate, %', 4.15, ROUND(AVG(current_rate_pct), 2)
FROM loan_book_synthetic WHERE product_type = 'variable'
UNION ALL
SELECT 'Tracker average rate, %', 3.39, ROUND(AVG(current_rate_pct), 2)
FROM loan_book_synthetic WHERE product_type = 'tracker'
UNION ALL
SELECT 'Share of loans at or below 3.5%, %',
       (SELECT bank_cum_pct FROM rate_distribution WHERE rate_upper_pct = 3.5),
       ROUND(100.0 * SUM(current_rate_pct <= 3.5) / COUNT(*), 2)
FROM loan_book_synthetic
UNION ALL
SELECT 'Share of loans above 4.0%, %',
       ROUND(100 - (SELECT bank_cum_pct FROM rate_distribution WHERE rate_upper_pct = 4.0), 2),
       ROUND(100.0 * SUM(current_rate_pct > 4.0) / COUNT(*), 2)
FROM loan_book_synthetic
UNION ALL
SELECT 'Share on variable rates, %', 15, ROUND(100.0 * SUM(product_type = 'variable') / COUNT(*), 1)
FROM loan_book_synthetic
UNION ALL
SELECT 'Share on tracker rates, %', 18, ROUND(100.0 * SUM(product_type = 'tracker') / COUNT(*), 1)
FROM loan_book_synthetic;
