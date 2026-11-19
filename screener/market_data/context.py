"""Yahoo Finance retrieval and indicator-enriched ticker context."""

import pandas as pd
import yfinance as yf

from screener.domain.indicators import (
    DEFAULT_INDICATORS,
    add_indicators,
    evaluate_signals,
)
from screener.domain.trade_plans import build_long_trade_plan, round_price, value_or_none


def _download_history(ticker, start, end):
    history = yf.download(
        ticker, start=start, end=end, progress=False, interval="1d", auto_adjust=False
    )
    if isinstance(history.columns, pd.MultiIndex):
        history.columns = history.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required.difference(history.columns)
    if history.empty or missing:
        raise ValueError(f"{ticker}: missing price columns: {sorted(missing)}")
    return history


def fetch_ticker_context(
    ticker,
    start="2024-01-01",
    end=None,
    indicators=None,
    rr_ratio=3.0,
    price_decimals=2,
):
    """Fetch Yahoo daily history and build a latest-row analysis context.

    Args:
        ticker: Yahoo Finance symbol.
        start: Inclusive history start date in ``YYYY-MM-DD`` form.
        end: Exclusive history end date; defaults to the current date.
        indicators: Optional indicator selector names. Required EMA, RSI, and
            volume selectors are added when absent because plans/signals use
            those values.
        rr_ratio: Positive reward-to-risk multiple used by the reference plan.
        price_decimals: Decimal places for displayed prices.

    Returns:
        A mapping with ticker/date, latest OHLCV values, selected indicator
        values, signals, an advisory plan, and the full enriched history.

    Raises:
        ValueError: If Yahoo returns missing OHLCV columns or fewer than 21
            daily bars.
    """
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    chosen = [
        item.strip().lower()
        for item in (indicators or DEFAULT_INDICATORS)
        if item.strip()
    ]
    for required_indicator in ("ema50", "ema100", "ema200", "rsi", "volume"):
        if required_indicator not in chosen:
            chosen.append(required_indicator)
    history = _download_history(ticker, start, end)
    if len(history) < 21:
        raise ValueError(f"{ticker}: at least 21 daily bars are required")

    enriched = add_indicators(history, chosen)
    latest = enriched.iloc[-1]
    previous = enriched.iloc[-2] if len(enriched) > 1 else None
    signals = evaluate_signals(latest, chosen, prev=previous)
    plan = build_long_trade_plan(latest, rr_ratio=rr_ratio, price_decimals=price_decimals)
    context = {
        "ticker": ticker,
        "as_of": str(enriched.index[-1].date()),
        "close": round_price(value_or_none(latest, "Close"), price_decimals),
        "open": round_price(value_or_none(latest, "Open"), price_decimals),
        "high": round_price(value_or_none(latest, "High"), price_decimals),
        "low": round_price(value_or_none(latest, "Low"), price_decimals),
        "volume": value_or_none(latest, "Volume"),
        "indicators": {
            column: round_price(value_or_none(latest, column), price_decimals)
            for column in (
                "ALMA", "EMA50", "EMA100", "EMA200", "RSI_14", "ATRr_14",
                "VolumeAvg20", "MACDh_12_26_9", "PSARl_0.02_0.2",
            )
        },
        "signals": signals,
        "plan": plan,
        "history": enriched,
    }
    return context
