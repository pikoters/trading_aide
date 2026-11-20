import numpy as np
import pandas as pd
import pytest

import screener.trade_analysis as trade_analysis


def make_history(rows=30):
    index = pd.date_range("2026-08-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "Open": np.full(rows, 100.0),
            "High": np.full(rows, 105.0),
            "Low": np.full(rows, 95.0),
            "Close": np.full(rows, 120.0),
            "Volume": np.full(rows, 1000),
        },
        index=index,
    )


def test_build_long_trade_plan_uses_ma_support_and_atr():
    latest = pd.Series({"Close": 120.0, "EMA100": 110.0, "EMA200": 100.0, "ATRr_14": 5.0})

    plan = trade_analysis.build_long_trade_plan(latest, rr_ratio=3.0)

    assert plan["actionable"] is True
    assert plan["entry"] == 110.0
    assert plan["entry_support"] == "EMA100"
    assert plan["stop"] == 105.0
    assert plan["target"] == 125.0
    assert plan["risk_per_share"] == 5.0


def test_build_long_trade_plan_is_not_actionable_when_rounded_risk_is_zero():
    latest = pd.Series({
        "Close": 1.01, "EMA100": 1.00, "EMA200": 0.90, "ATRr_14": 0.001,
    })

    plan = trade_analysis.build_long_trade_plan(latest, price_decimals=2)

    assert plan["entry"] == plan["stop"] == 1.0
    assert plan["risk_per_share"] == 0.0
    assert plan["actionable"] is False


def test_build_reference_report_matches_requested_plan():
    history = make_history()
    history["High"] = 69.0
    history.iloc[-2, history.columns.get_loc("High")] = 70.50
    context = {
        "ticker": "MO",
        "as_of": "2026-09-18",
        "close": 69.52,
        "volume": 1200.0,
        "indicators": {
            "EMA50": 67.66,
            "EMA100": 67.58,
            "EMA200": 65.20,
            "RSI_14": 57.90,
            "VolumeAvg20": 1000.0,
        },
        "signals": {"ema50_bull": True, "ema100_bull": True, "ema200_bull": True, "rsi_bull": True},
        "history": history,
    }

    report = trade_analysis.build_reference_report(context)

    assert report["reference"]["all_bull_flags"] is True
    assert report["conservative_pullback"]["atr_proxy"] == 0.695
    assert report["conservative_pullback"]["entry"] == 67.83
    assert report["conservative_pullback"]["stop"] == 66.44
    assert report["conservative_pullback"]["target"] == 69.92
    assert report["aggressive_breakout"]["entry"] == 70.5
    assert report["aggressive_breakout"]["stop"] == 69.81
    assert report["aggressive_breakout"]["target"] == 72.59
    assert report["aggressive_breakout"]["volume_confirmed"] is True


def test_format_reference_report_displays_missing_indicators_without_crashing():
    context = {
        "ticker": "NEW",
        "as_of": "2026-09-18",
        "close": 12.0,
        "volume": 1200.0,
        "indicators": {
            "EMA50": None, "EMA100": None, "EMA200": None,
            "RSI_14": None, "VolumeAvg20": None,
        },
        "signals": {},
        "history": make_history(),
    }

    report = trade_analysis.build_reference_report(context)
    formatted = trade_analysis.format_reference_report(report)

    assert "- EMA50: n/a" in formatted
    assert "- EMA100: n/a" in formatted
    assert "- RSI_14: n/a" in formatted
    assert "Conservative entry: EMA50 + 0.25% = n/a" in formatted


def test_augment_screener_results_selects_top_scores(tmp_path, monkeypatch):
    results_path = tmp_path / "results.csv"
    pd.DataFrame({
        "ticker": ["LOW", "HIGH", "MID"],
        "score": [1, 9, 5],
        "stop": [90.0, 90.0, 90.0],
        "target": [130.0, 130.0, 130.0],
    }).to_csv(results_path, index=False)
    calls = []

    def fake_context(ticker, **kwargs):
        calls.append(ticker)
        return {
            "as_of": "2026-09-18",
            "close": 120.0,
            "volume": 1000,
            "indicators": {
                "EMA100": 110.0, "EMA200": 100.0, "RSI_14": 60.0,
                "ATRr_14": 5.0, "ALMA": 115.0, "MACDh_12_26_9": 1.0,
                "PSARl_0.02_0.2": 105.0,
            },
            "signals": {"ema100_bull": True},
            "history": make_history(),
            "plan": {
                "entry": 110.0, "entry_support": "EMA100", "stop": 105.0,
                "target": 125.0, "risk_per_share": 5.0, "actionable": True,
            },
        }

    monkeypatch.setattr(trade_analysis, "fetch_ticker_context", fake_context)
    monkeypatch.setattr(
        trade_analysis,
        "fetch_strategy_plans",
        lambda *_args, **_kwargs: {"strategies": {}, "parameters": {}},
    )
    augmented = trade_analysis.augment_screener_results(results_path, min_score=1, top_n=2)

    assert calls == ["HIGH", "MID"]
    assert augmented["ticker"].tolist() == ["HIGH", "MID"]
    assert augmented["entry"].tolist() == [110.0, 110.0]
    assert augmented["stop"].tolist() == [105.0, 105.0]
    assert augmented["target"].tolist() == [125.0, 125.0]
    assert augmented["screener_stop"].tolist() == [90.0, 90.0]


def test_augment_marks_database_run_failed_when_ticker_analysis_raises(tmp_path, monkeypatch):
    results_path = tmp_path / "results.csv"
    pd.DataFrame({"ticker": ["FAIL"], "score": [3]}).to_csv(results_path, index=False)
    events = []

    class FakePersistenceManager:
        def start_analysis_run(self, metadata):
            events.append(("started", metadata["expected_count"]))

        def finish_analysis_run(self, _run_id, _finished_at, status="completed"):
            events.append(("finished", status))

        def close(self):
            events.append(("closed",))

    monkeypatch.setattr(
        trade_analysis.persistence, "PersistenceManager", FakePersistenceManager
    )

    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(
        trade_analysis,
        "fetch_ticker_context",
        fail_fetch,
    )

    with pytest.raises(RuntimeError, match="fetch failed"):
        trade_analysis.augment_screener_results(results_path, save_to_db=True)

    assert events == [("started", 1), ("finished", "failed"), ("closed",)]


def test_analyze_screener_run_defaults_to_all_scores(monkeypatch):
    rows = pd.DataFrame({
        "ticker": ["LOW", "HIGH", "MID"],
        "date": ["2026-09-18"] * 3,
        "score": [1, 9, 5],
        "close": [120.0] * 3,
        "ATRr_14": [5.0] * 3,
        "EMA100": [110.0] * 3,
        "EMA200": [100.0] * 3,
    })

    class FakePersistenceManager:
        def load_screener_run(self, _run_id):
            return {"run_id": "test-run"}, rows

        def close(self):
            pass

    monkeypatch.setattr(
        trade_analysis.persistence, "PersistenceManager", FakePersistenceManager
    )
    monkeypatch.setattr(
        trade_analysis,
        "fetch_ticker_context",
        lambda *_args, **_kwargs: {"history": make_history()},
    )
    monkeypatch.setattr(
        trade_analysis,
        "fetch_strategy_plans",
        lambda *_args, **_kwargs: {"strategies": {"MAMA_daily": {"status": "WATCH"}}, "parameters": {}},
    )

    analysis = trade_analysis.analyze_screener_run("test-run")

    assert analysis["ticker"].tolist() == ["HIGH", "MID", "LOW"]
    assert analysis.iloc[0]["strategy_plans"]["MAMA_daily"]["status"] == "WATCH"


def test_analyze_screener_run_continues_and_persists_when_one_ticker_fails(monkeypatch):
    rows = pd.DataFrame({
        "ticker": ["LOW", "HIGH", "MID"],
        "date": ["2026-09-18"] * 3,
        "score": [1, 9, 5],
        "close": [120.0] * 3,
        "ATRr_14": [5.0] * 3,
        "EMA100": [110.0] * 3,
        "EMA200": [100.0] * 3,
    })

    class FakePersistenceManager:
        def load_screener_run(self, _run_id):
            return {
                "run_id": "test-run",
                "screener_run_id": "test-screener-run",
                "end_date": "2026-09-18",
                "indicators": "ema50,ema100",
            }, rows

        def start_analysis_run(self, metadata):
            self.metadata = metadata
            self.snapshots = []
            self.events = ["run_started"]

        def save_analysis_result(self, _run_id, snapshot):
            self.events.append(snapshot["ticker"])
            self.snapshots.append(snapshot)

        def finish_analysis_run(self, _run_id, _finished_at):
            self.events.append("run_finished")

        def close(self):
            pass

    manager = FakePersistenceManager()
    monkeypatch.setattr(
        trade_analysis.persistence, "PersistenceManager", lambda: manager
    )

    def fake_context(ticker, *_args, **_kwargs):
        if ticker == "MID":
            raise RuntimeError("market data request failed")
        return {"history": make_history()}

    monkeypatch.setattr(trade_analysis, "fetch_ticker_context", fake_context)
    monkeypatch.setattr(
        trade_analysis,
        "fetch_strategy_plans",
        lambda *_args, **_kwargs: {
            "strategies": {"MAMA_daily": {"status": "WATCH"}},
            "parameters": {},
        },
    )

    analysis = trade_analysis.analyze_screener_run("test-run", save_to_db=True)

    assert analysis["ticker"].tolist() == ["HIGH", "MID", "LOW"]
    assert "market data request failed" in analysis.loc[
        analysis["ticker"] == "MID", "analysis_note"
    ].iloc[0]
    assert [snapshot["ticker"] for snapshot in manager.snapshots] == ["HIGH", "MID", "LOW"]
    assert manager.events == ["run_started", "HIGH", "MID", "LOW", "run_finished"]
    assert manager.metadata["expected_count"] == len(rows)
    failed_plan = next(
        snapshot["plan"] for snapshot in manager.snapshots if snapshot["ticker"] == "MID"
    )
    assert "market data request failed" in failed_plan["data_note"]