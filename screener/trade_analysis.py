"""Compatibility facade for stock-analysis workflows and CLI callers."""

import screener.persistence as persistence
from screener.application.analysis_ports import AnalysisDependencies
from screener.application.analysis_workflows import (
    analyze_screener_run as _analyze_screener_run,
    augment_screener_results as _augment_screener_results,
)
from screener.domain.indicators import DEFAULT_INDICATORS
from screener.domain.trade_plans import (
    build_long_trade_plan,
    build_reference_report,
    format_reference_report,
)
from screener.market_data.context import fetch_ticker_context
from screener.market_data.strategy_analysis import fetch_strategy_plans


def _dependencies():
    return AnalysisDependencies(
        repository_factory=persistence.PersistenceManager,
        fetch_ticker_context=fetch_ticker_context,
        fetch_strategy_plans=fetch_strategy_plans,
    )


def analyze_screener_run(
    screener_run_id="latest",
    tickers=None,
    min_score=None,
    top_n=None,
    rr_ratio=3.0,
    price_decimals=2,
    save_to_db=False,
    rsi_threshold=55.0,
    macd_zero_tolerance_pct=0.5,
    fishball_support_lookback=20,
):
    """Analyze a saved screener run using the configured repository/providers."""
    return _analyze_screener_run(
        screener_run_id=screener_run_id, tickers=tickers, min_score=min_score,
        top_n=top_n, rr_ratio=rr_ratio, price_decimals=price_decimals,
        save_to_db=save_to_db, rsi_threshold=rsi_threshold,
        macd_zero_tolerance_pct=macd_zero_tolerance_pct,
        fishball_support_lookback=fishball_support_lookback,
        dependencies=_dependencies(),
    )


def augment_screener_results(
    results_path="screener_results.csv",
    tickers=None,
    min_score=None,
    top_n=None,
    start="2024-01-01",
    end=None,
    indicators=None,
    rr_ratio=3.0,
    price_decimals=2,
    save_to_db=False,
    screener_run_id=None,
    rsi_threshold=55.0,
    macd_zero_tolerance_pct=0.5,
    fishball_support_lookback=20,
    include_strategies=True,
):
    """Augment a screener CSV with current context, plans, and optional persistence."""
    return _augment_screener_results(
        results_path=results_path, tickers=tickers, min_score=min_score,
        top_n=top_n, start=start, end=end, indicators=indicators,
        rr_ratio=rr_ratio, price_decimals=price_decimals, save_to_db=save_to_db,
        screener_run_id=screener_run_id, rsi_threshold=rsi_threshold,
        macd_zero_tolerance_pct=macd_zero_tolerance_pct,
        fishball_support_lookback=fishball_support_lookback,
        include_strategies=include_strategies, dependencies=_dependencies(),
    )
