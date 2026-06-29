CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code VARCHAR PRIMARY KEY,
    symbol VARCHAR,
    name VARCHAR,
    area VARCHAR,
    industry VARCHAR,
    market VARCHAR,
    list_date VARCHAR,
    delist_date VARCHAR,
    is_hs VARCHAR
);

CREATE TABLE IF NOT EXISTS trade_calendar (
    exchange VARCHAR,
    cal_date VARCHAR,
    is_open INTEGER,
    pretrade_date VARCHAR,
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS daily_price (
    ts_code VARCHAR,
    trade_date VARCHAR,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    pre_close DOUBLE,
    change DOUBLE,
    pct_chg DOUBLE,
    vol DOUBLE,
    amount DOUBLE,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code VARCHAR,
    trade_date VARCHAR,
    turnover_rate DOUBLE,
    volume_ratio DOUBLE,
    pe DOUBLE,
    pb DOUBLE,
    ps DOUBLE,
    total_mv DOUBLE,
    circ_mv DOUBLE,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS adj_factor (
    ts_code VARCHAR,
    trade_date VARCHAR,
    adj_factor DOUBLE,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS factor_values (
    ts_code VARCHAR,
    trade_date VARCHAR,
    factor_name VARCHAR,
    factor_value DOUBLE,
    PRIMARY KEY (ts_code, trade_date, factor_name)
);

CREATE TABLE IF NOT EXISTS factor_scores (
    ts_code VARCHAR,
    trade_date VARCHAR,
    trend_score DOUBLE,
    momentum_score DOUBLE,
    liquidity_score DOUBLE,
    volatility_score DOUBLE,
    fundamental_score DOUBLE,
    total_score DOUBLE,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS strategy_result (
    trade_date VARCHAR,
    rank INTEGER,
    ts_code VARCHAR,
    name VARCHAR,
    industry VARCHAR,
    total_score DOUBLE,
    select_reason VARCHAR,
    risk_note VARCHAR,
    PRIMARY KEY (trade_date, rank, ts_code)
);

CREATE TABLE IF NOT EXISTS backtest_result (
    strategy_name VARCHAR,
    start_date VARCHAR,
    end_date VARCHAR,
    annual_return DOUBLE,
    max_drawdown DOUBLE,
    sharpe_ratio DOUBLE,
    win_rate DOUBLE,
    turnover DOUBLE,
    created_at TIMESTAMP,
    PRIMARY KEY (strategy_name, start_date, end_date, created_at)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id VARCHAR PRIMARY KEY,
    ts_code VARCHAR,
    name VARCHAR,
    selection_date VARCHAR,
    review_date VARCHAR,
    decision VARCHAR,
    review_status VARCHAR,
    reviewer VARCHAR,
    reason VARCHAR,
    notes VARCHAR,
    data_quality_note VARCHAR,
    source_report_path VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    ts_code VARCHAR,
    name VARCHAR,
    snapshot_date VARCHAR,
    selection_date VARCHAR,
    review_date VARCHAR,
    decision VARCHAR,
    industry VARCHAR,
    market VARCHAR,
    list_date VARCHAR,
    latest_trade_date VARCHAR,
    latest_close DOUBLE,
    pe DOUBLE,
    pb DOUBLE,
    total_score DOUBLE,
    trend_score DOUBLE,
    momentum_score DOUBLE,
    liquidity_score DOUBLE,
    volatility_score DOUBLE,
    fundamental_score DOUBLE,
    return_20d DOUBLE,
    avg_amount_20d DOUBLE,
    avg_turnover_20d DOUBLE,
    volatility_20d DOUBLE,
    score_missing_reason VARCHAR,
    data_quality_note VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_decision_history (
    history_id VARCHAR PRIMARY KEY,
    ts_code VARCHAR,
    name VARCHAR,
    selection_date VARCHAR,
    old_decision VARCHAR,
    new_decision VARCHAR,
    old_review_status VARCHAR,
    new_review_status VARCHAR,
    reason VARCHAR,
    notes VARCHAR,
    reviewer VARCHAR,
    action_type VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    position_id VARCHAR PRIMARY KEY,
    ts_code VARCHAR,
    name VARCHAR,
    entry_date VARCHAR,
    entry_price DOUBLE,
    quantity DOUBLE,
    entry_reason VARCHAR,
    source VARCHAR,
    entry_total_score DOUBLE,
    entry_elder_score DOUBLE,
    initial_stop DOUBLE,
    plan VARCHAR,
    status VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
