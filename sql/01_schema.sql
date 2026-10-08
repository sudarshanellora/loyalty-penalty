-- Loyalty Penalty project: database schema (SQLite)
-- Public data tables hold figures transcribed from official releases.
-- loan_book_synthetic is SIMULATED and contains no real customer data.

DROP TABLE IF EXISTS sources;
CREATE TABLE sources (
    source_id        TEXT PRIMARY KEY,
    publisher        TEXT NOT NULL,
    title            TEXT NOT NULL,
    reference_period TEXT,
    url              TEXT NOT NULL
);

DROP TABLE IF EXISTS rate_distribution;
CREATE TABLE rate_distribution (
    reference_month             TEXT NOT NULL,
    rate_upper_pct              REAL NOT NULL,   -- loans with rate <= this value
    bank_cum_pct                REAL NOT NULL,
    lending_nonbank_cum_pct     REAL NOT NULL,
    nonlending_nonbank_cum_pct  REAL NOT NULL,
    source_id                   TEXT REFERENCES sources(source_id),
    PRIMARY KEY (reference_month, rate_upper_pct)
);

DROP TABLE IF EXISTS new_lending_rates;
CREATE TABLE new_lending_rates (
    month                 TEXT PRIMARY KEY,      -- YYYY-MM
    ie_new_rate_pct       REAL,
    ea_new_rate_pct       REAL,
    ie_rank_in_ea         INTEGER,
    ie_fixed_rate_pct     REAL,
    ie_variable_rate_pct  REAL,
    fixed_share_pct       REAL,
    new_volume_eur_m      REAL,
    reneg_volume_eur_m    REAL,
    reneg_fixed_rate_pct  REAL,
    basis                 TEXT,
    source_id             TEXT REFERENCES sources(source_id)
);

DROP TABLE IF EXISTS outstanding_pdh_by_lender;
CREATE TABLE outstanding_pdh_by_lender (
    reference_month   TEXT NOT NULL,
    lender_type       TEXT NOT NULL,
    rate_type         TEXT NOT NULL,
    outstanding_eur_m REAL,
    accounts          INTEGER,
    avg_rate_pct      REAL,
    source_id         TEXT REFERENCES sources(source_id),
    PRIMARY KEY (reference_month, lender_type, rate_type)
);

DROP TABLE IF EXISTS market_size;
CREATE TABLE market_size (
    metric          TEXT PRIMARY KEY,
    value           REAL NOT NULL,
    unit            TEXT NOT NULL,
    reference_month TEXT,
    note            TEXT,
    source_id       TEXT REFERENCES sources(source_id)
);

DROP TABLE IF EXISTS bpfi_drawdowns;
CREATE TABLE bpfi_drawdowns (
    quarter     TEXT NOT NULL,                   -- YYYYQn
    segment     TEXT NOT NULL,
    volume      INTEGER NOT NULL,
    value_eur_m REAL NOT NULL,
    source_id   TEXT REFERENCES sources(source_id),
    PRIMARY KEY (quarter, segment)
);

DROP TABLE IF EXISTS bank_financials;
CREATE TABLE bank_financials (
    bank                       TEXT NOT NULL,
    fiscal_year                INTEGER NOT NULL,
    net_interest_income_eur_m  REAL,
    net_interest_margin_pct    REAL,
    cost_income_ratio_pct      REAL,
    total_income_eur_m         REAL,
    new_mortgage_share_pct     REAL,
    source_id                  TEXT REFERENCES sources(source_id),
    PRIMARY KEY (bank, fiscal_year)
);

DROP TABLE IF EXISTS switching_costs;
CREATE TABLE switching_costs (
    item      TEXT PRIMARY KEY,
    low_eur   REAL,
    high_eur  REAL,
    note      TEXT,
    source_id TEXT REFERENCES sources(source_id)
);

-- Analysis parameters kept in the database so every query states its assumptions.
DROP TABLE IF EXISTS assumptions;
CREATE TABLE assumptions (
    name   TEXT PRIMARY KEY,
    value  REAL NOT NULL,
    unit   TEXT NOT NULL,
    basis  TEXT NOT NULL      -- 'sourced', 'derived' or 'assumed'
);

DROP TABLE IF EXISTS loan_book_synthetic;
CREATE TABLE loan_book_synthetic (
    loan_id            INTEGER PRIMARY KEY,
    product_type       TEXT NOT NULL CHECK (product_type IN ('fixed','variable','tracker')),
    current_rate_pct   REAL NOT NULL,
    balance_eur        REAL NOT NULL,
    remaining_months   INTEGER NOT NULL,
    months_to_rolloff  INTEGER,                  -- fixed loans only
    current_ltv_pct    REAL NOT NULL,
    arrears_flag       INTEGER NOT NULL CHECK (arrears_flag IN (0,1))
);
CREATE INDEX idx_loan_product ON loan_book_synthetic(product_type);

-- Long-format view of the published distribution: one row per lender type and rate bucket.
DROP VIEW IF EXISTS v_rate_buckets;
CREATE VIEW v_rate_buckets AS
WITH long AS (
    SELECT reference_month, rate_upper_pct, 'bank' AS lender_type, bank_cum_pct AS cum_pct FROM rate_distribution
    UNION ALL
    SELECT reference_month, rate_upper_pct, 'lending_non_bank', lending_nonbank_cum_pct FROM rate_distribution
    UNION ALL
    SELECT reference_month, rate_upper_pct, 'nonlending_non_bank', nonlending_nonbank_cum_pct FROM rate_distribution
)
SELECT
    reference_month,
    lender_type,
    rate_upper_pct - 0.5                                   AS rate_lower_pct,
    rate_upper_pct,
    rate_upper_pct - 0.25                                  AS rate_mid_pct,
    cum_pct - COALESCE(LAG(cum_pct) OVER (
        PARTITION BY reference_month, lender_type ORDER BY rate_upper_pct), 0) AS share_pct
FROM long;

-- Accounts and average balance per lender type (derived from published totals).
DROP VIEW IF EXISTS v_lender_base;
CREATE VIEW v_lender_base AS
WITH m AS (
    SELECT
        MAX(CASE WHEN metric = 'pdh_accounts_total'    THEN value END) AS acc_total,
        MAX(CASE WHEN metric = 'pdh_accounts_non_bank' THEN value END) AS acc_nb,
        MAX(CASE WHEN metric = 'pdh_balance_total'     THEN value END) AS bal_total
    FROM market_size
),
nb AS (
    SELECT
        MAX(CASE WHEN lender_type = 'non_bank'            THEN outstanding_eur_m END) AS nb_bal,
        MAX(CASE WHEN lender_type = 'non_bank'            THEN accounts END)          AS nb_acc,
        MAX(CASE WHEN lender_type = 'lending_non_bank'    THEN outstanding_eur_m END) AS lnb_bal,
        MAX(CASE WHEN lender_type = 'lending_non_bank'    THEN accounts END)          AS lnb_acc,
        MAX(CASE WHEN lender_type = 'nonlending_non_bank' THEN outstanding_eur_m END) AS nlnb_bal,
        MAX(CASE WHEN lender_type = 'nonlending_non_bank' THEN accounts END)          AS nlnb_acc
    FROM outstanding_pdh_by_lender
    WHERE rate_type = 'total'
)
SELECT 'bank' AS lender_type,
       m.acc_total - m.acc_nb                                        AS accounts,
       (m.bal_total - nb.nb_bal) * 1e6 / (m.acc_total - m.acc_nb)    AS avg_balance_eur
FROM m, nb
UNION ALL
SELECT 'lending_non_bank',
       m.acc_nb * nb.lnb_acc * 1.0 / nb.nb_acc,
       nb.lnb_bal * 1e6 / nb.lnb_acc
FROM m, nb
UNION ALL
SELECT 'nonlending_non_bank',
       m.acc_nb * nb.nlnb_acc * 1.0 / nb.nb_acc,
       nb.nlnb_bal * 1e6 / nb.nlnb_acc
FROM m, nb;
