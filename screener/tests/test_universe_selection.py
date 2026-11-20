from types import SimpleNamespace

import pandas as pd
import pytest

import screener.stocks_screener as stocks_screener


def _args(symbols="", universe="", max_symbols=200):
    return SimpleNamespace(
        symbols=symbols,
        universe=universe,
        symbols_file="",
        max_symbols=max_symbols,
    )


def test_nasdaq_universe_uses_nasdaq_listings(monkeypatch):
    monkeypatch.setattr(stocks_screener, "get_nasdaq_tickers", lambda: ["NVDA", "MSFT"])
    monkeypatch.setattr(
        stocks_screener, "get_sp500_tickers",
        lambda: pytest.fail("Nasdaq universe must not use S&P 500 constituents"),
    )

    assert stocks_screener.universe_tickers(_args(universe="nasdaq")) == ["MSFT", "NVDA"]


def test_nasdaq_directory_excludes_test_issues_and_etfs(monkeypatch):
    class Response:
        text = (
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares\n"
            "AAPL|Apple Inc.|Q|N|N|100|N|N\n"
            "QQQ|ETF|G|N|N|100|Y|N\n"
            "TEST|Test security|Q|Y|N|100|N|N\n"
            "File Creation Time: 2026111816:00|||||||\n"
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(stocks_screener.requests, "get", lambda *_args, **_kwargs: Response())

    assert stocks_screener.get_nasdaq_tickers() == ["AAPL"]


def test_symbol_limit_is_applied_after_deterministic_sorting():
    args = _args(symbols="D,A,C,B", max_symbols=2)

    assert stocks_screener.universe_tickers(args) == ["A", "B"]
    assert stocks_screener.universe_tickers(args) == ["A", "B"]


def test_indicator_calculation_errors_are_not_replaced_with_nan(monkeypatch):
    def fail(*_args, **_kwargs):
        raise ValueError("invalid input")

    monkeypatch.setattr(
        stocks_screener.ta,
        "alma",
        fail,
    )

    with pytest.raises(stocks_screener.IndicatorCalculationError, match="ALMA"):
        stocks_screener.add_indicators(pd.DataFrame({"Close": [1.0, 2.0]}), ["alma"])
