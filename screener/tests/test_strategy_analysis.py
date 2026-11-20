import numpy as np
import pandas as pd

from screener import market_indicators, strategy_analysis
from screener.strategy_analysis import (
    _alligator_plan,
    _bread_and_butter_plan,
    _bunso_plan,
    _kasambahay_plan,
    _lolo_plan,
    _mama_plan,
    _papa_plan,
    _supertrend_plan,
    _tito_plan,
    _tita_plan,
    analyze_strategy_histories,
)


def test_mama_rejects_five_percent_risk_boundary():
    history = pd.DataFrame(
        {
            "Open": np.full(35, 95.0),
            "Close": np.full(35, 94.0),
            "ALMA": np.full(35, 95.0),
            "MACD_12_26_9": np.full(35, -0.5),
            "MACDs_12_26_9": np.zeros(35),
        },
        index=pd.date_range("2026-10-01", periods=35),
    )
    history.iloc[-1, history.columns.get_loc("Open")] = 99.0
    history.iloc[-1, history.columns.get_loc("Close")] = 100.0
    history.iloc[-1, history.columns.get_loc("ALMA")] = 95.0
    history.iloc[-1, history.columns.get_loc("MACD_12_26_9")] = 0.1

    plan = _mama_plan(history, "1d", 5.0)

    assert plan["conditions_met"] is True
    assert plan["entry_trigger"] is False
    assert plan["status"] == "RISK_TOO_HIGH"
    assert plan["risk_pct"] == 5.0


def test_tita_accepts_five_percent_risk_and_parameterized_rsi_cross():
    history = pd.DataFrame(
        {
            "Close": np.full(35, 99.0),
            "ALMA": np.full(35, 100.0),
            "RSI_14": np.full(35, 54.0),
        },
        index=pd.date_range("2026-10-01", periods=35),
    )
    history.iloc[-1, history.columns.get_loc("Close")] = 100.0
    history.iloc[-1, history.columns.get_loc("ALMA")] = 95.0
    history.iloc[-1, history.columns.get_loc("RSI_14")] = 56.0

    plan = _tita_plan(history, rsi_threshold=55.0, risk_cap_pct=5.0)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["risk_pct"] == 5.0
    assert plan["parameters"]["rsi_threshold"] == 55.0


def test_papa_requires_envelope_breakout_and_macd_cross():
    history = pd.DataFrame(
        {
            "Close": np.full(42, 100.0),
            "SMA40": np.full(42, 100.0),
            "EnvelopeUpper": np.full(42, 103.0),
            "MACD_12_26_9": np.full(42, -1.0),
            "MACDs_12_26_9": np.full(42, -0.5),
        },
        index=pd.date_range("2026-08-01", periods=42),
    )
    history.iloc[-2, history.columns.get_loc("Close")] = 103.0
    history.iloc[-1, history.columns.get_loc("Close")] = 104.0
    history.iloc[-1, history.columns.get_loc("MACD_12_26_9")] = 0.1
    history.iloc[-1, history.columns.get_loc("MACDs_12_26_9")] = 0.0

    plan = _papa_plan(history, macd_zero_tolerance_pct=0.5)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["entry"] == 104.0
    assert plan["stop"] == 100.0
    assert plan["parameters"]["envelope_deviation_pct"] == 3.0


def test_strategy_analysis_reports_intraday_data_unavailable_explicitly():
    index = pd.date_range("2025-01-01", periods=160, freq="B")
    close = np.linspace(80.0, 120.0, len(index))
    daily = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(len(index), 1000.0),
        },
        index=index,
    )

    analysis = analyze_strategy_histories("TEST", daily)

    assert set(analysis["strategies"]) == {
        "MAMA_daily", "MAMA_4h", "PAPA_daily", "TITA_daily",
        "CALMA_weekly", "FISHBALL_30m", "BOPIS_daily",
        "BUNSO_15m", "BUNSO_1h", "LOLO_weekly", "TITO_daily",
        "KASAMBAHAY_daily",
        "SUPERTREND_daily", "SUPERTREND_5m", "SUPERTREND_15m",
        "ALLIGATOR_daily", "BREAD_AND_BUTTER_daily", "BREAD_AND_BUTTER_1h",
    }
    assert analysis["strategies"]["MAMA_4h"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["FISHBALL_30m"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["BUNSO_15m"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["SUPERTREND_5m"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["ALLIGATOR_daily"]["status"] == "WATCH"
    assert analysis["strategies"]["BREAD_AND_BUTTER_1h"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["LOLO_weekly"]["status"] == "UNAVAILABLE"
    assert analysis["strategies"]["MAMA_daily"]["as_of"] == index[-1].date().isoformat()


def test_strategy_analysis_enriches_hourly_and_30_minute_histories():
    sessions = pd.date_range("2025-01-06", periods=35, freq="B")
    hourly_rows = []
    half_hour_rows = []
    for session_index, session in enumerate(sessions):
        for bar_index in range(7):
            close = 100.0 + session_index * 0.1 + bar_index * 0.02
            hourly_rows.append({
                "Date": session + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(hours=bar_index),
                "Open": close - 0.01,
                "High": close + 0.1,
                "Low": close - 0.1,
                "Close": close,
                "Volume": 1000.0,
            })
        for bar_index in range(13):
            close = 100.0 + session_index * 0.1 + bar_index * 0.01
            half_hour_rows.append({
                "Date": session + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=30 * bar_index),
                "Open": close - 0.01,
                "High": close + 0.1,
                "Low": close - 0.1,
                "Close": close,
                "Volume": 1000.0,
            })
    hourly = pd.DataFrame(hourly_rows).set_index("Date")
    half_hour = pd.DataFrame(half_hour_rows).set_index("Date")
    daily_close = np.linspace(95.0, 110.0, len(sessions))
    daily = pd.DataFrame(
        {
            "Open": daily_close - 0.2,
            "High": daily_close + 0.4,
            "Low": daily_close - 0.4,
            "Close": daily_close,
            "Volume": np.full(len(sessions), 5000.0),
        },
        index=sessions,
    )

    analysis = analyze_strategy_histories(
        "TEST", daily, hourly_history=hourly, intraday_history=half_hour
    )

    assert analysis["strategies"]["MAMA_4h"]["status"] != "UNAVAILABLE"
    assert analysis["strategies"]["FISHBALL_30m"]["status"] != "UNAVAILABLE"


def test_enrich_drops_precomputed_columns_before_recomputing_indicators():
    index = pd.date_range("2025-01-01", periods=80, freq="B")
    close = np.linspace(80.0, 120.0, len(index))
    history = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(len(index), 1000.0),
        },
        index=index,
    )
    already_enriched = market_indicators.add_indicators(
        history, ["alma", "macd", "rsi", "cci", "psar", "atr", "volume"]
    )

    enriched = strategy_analysis._enrich(already_enriched)

    assert enriched.columns.is_unique
    assert isinstance(enriched.iloc[-1].get("MACD_12_26_9"), (float, np.floating))
    analysis = analyze_strategy_histories("TEST", already_enriched)
    assert analysis["strategies"]["MAMA_daily"]["status"] in {
        "WATCH", "ENTRY_TRIGGERED", "EXIT_TRIGGERED", "RISK_TOO_HIGH"
    }


def test_fetch_strategy_plans_downloads_bunso_and_long_weekly_histories(monkeypatch):
    short_index = pd.date_range("2025-01-01", periods=160, freq="B")
    short_close = np.linspace(80.0, 120.0, len(short_index))
    daily = pd.DataFrame(
        {
            "Open": short_close - 0.5,
            "High": short_close + 1.0,
            "Low": short_close - 1.0,
            "Close": short_close,
            "Volume": np.full(len(short_index), 1000.0),
        },
        index=short_index,
    )
    long_index = pd.date_range(
        end=pd.Timestamp.now().normalize() - pd.Timedelta(days=1),
        periods=2200,
        freq="B",
    )
    long_close = np.linspace(50.0, 150.0, len(long_index))
    long_daily = pd.DataFrame(
        {
            "Open": long_close - 0.5,
            "High": long_close + 1.0,
            "Low": long_close - 1.0,
            "Close": long_close,
            "Volume": np.full(len(long_index), 1000.0),
        },
        index=long_index,
    )
    calls = []

    def fake_download(_ticker, interval, _start, _end):
        calls.append(interval)
        return long_daily if interval == "1d" else pd.DataFrame()

    monkeypatch.setattr(strategy_analysis, "_download_history", fake_download)

    result = strategy_analysis.fetch_strategy_plans("TEST", daily)

    assert "15m" in calls
    assert "5m" in calls
    assert "1d" in calls
    assert result["strategies"]["LOLO_weekly"]["status"] != "UNAVAILABLE"
    assert result["strategies"]["BUNSO_15m"]["status"] == "UNAVAILABLE"
    assert result["strategies"]["BUNSO_1h"]["status"] == "UNAVAILABLE"


def test_bunso_requires_consolidation_breakout_volume_rsi_and_52_week_high():
    index = pd.date_range("2026-11-02 09:30", periods=35, freq="15min")
    history = pd.DataFrame(
        {
            "Close": np.full(35, 100.0),
            "High": np.full(35, 101.0),
            "Low": np.full(35, 99.0),
            "Volume": np.full(35, 100.0),
            "ALMA9": np.full(35, 99.0),
            "RSI_14": np.full(35, 69.0),
        },
        index=index,
    )
    history.iloc[-1, history.columns.get_loc("Close")] = 110.0
    history.iloc[-1, history.columns.get_loc("High")] = 111.0
    history.iloc[-1, history.columns.get_loc("Volume")] = 250.0
    history.iloc[-1, history.columns.get_loc("RSI_14")] = 71.0
    daily_index = pd.date_range("2025-11-03", periods=260, freq="B")
    daily = pd.DataFrame(
        {
            "High": np.full(260, 109.0),
            "Low": np.full(260, 90.0),
            "Close": np.full(260, 100.0),
        },
        index=daily_index,
    )

    plan = _bunso_plan(history, "15m", daily)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["parameters"]["volume_multiplier"] == 2.0
    assert plan["parameters"]["requires_52_week_high"] is True
    assert "institutional buying" in plan["manual_precondition"]


def test_lolo_requires_weekly_sma200_and_bullish_macd_cross():
    history = pd.DataFrame(
        {
            "Close": np.full(200, 110.0),
            "SMA200": np.full(200, 100.0),
            "MACD_12_26_9": np.full(200, -1.0),
            "MACDs_12_26_9": np.full(200, -0.5),
        },
        index=pd.date_range("2020-01-03", periods=200, freq="W-FRI"),
    )
    history.iloc[-1, history.columns.get_loc("MACD_12_26_9")] = 0.1
    history.iloc[-1, history.columns.get_loc("MACDs_12_26_9")] = 0.0

    plan = _lolo_plan(history, macd_zero_tolerance_pct=0.5)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["stop"] == 100.0
    assert "index membership" in plan["manual_precondition"]


def test_tito_requires_prior_squeeze_and_bollinger_breakout():
    history = pd.DataFrame(
        {
            "Close": np.full(35, 100.0),
            "BBL_20_2.0": np.full(35, 95.0),
            "BBU_20_2.0": np.full(35, 105.0),
            "KCLe_20_1.5": np.full(35, 90.0),
            "KCUe_20_1.5": np.full(35, 110.0),
            "SMA20": np.full(35, 98.0),
            "MACDh_12_26_9": np.full(35, 0.1),
        },
        index=pd.date_range("2026-09-01", periods=35),
    )
    history.iloc[-1, history.columns.get_loc("Close")] = 106.0
    history.iloc[-1, history.columns.get_loc("BBU_20_2.0")] = 105.0
    history.iloc[-1, history.columns.get_loc("MACDh_12_26_9")] = 0.2

    plan = _tito_plan(history)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["partial_exit_trigger"] is False
    assert plan["remaining_exit_trigger"] is False


def test_kasambahay_enters_on_oversold_lower_envelope_pierce_without_invented_stop():
    history = pd.DataFrame(
        {
            "Open": np.full(35, 95.0),
            "High": np.full(35, 96.0),
            "Low": np.full(35, 94.0),
            "Close": np.full(35, 95.0),
            "Envelope20Lower5": np.full(35, 90.0),
            "SMA20": np.full(35, 100.0),
            "RSI_14": np.full(35, 35.0),
        },
        index=pd.date_range("2026-09-01", periods=35),
    )
    history.iloc[-1, history.columns.get_loc("Low")] = 89.0
    history.iloc[-1, history.columns.get_loc("RSI_14")] = 29.0

    plan = _kasambahay_plan(history)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["stop"] is None
    assert plan["risk_pct"] is None
    assert "company quality" in plan["manual_precondition"]


def test_supertrend_requires_green_flip_and_close_above_ema9():
    history = pd.DataFrame(
        {
            "Close": [99.0] * 8 + [101.0, 102.0],
            "EMA9": [100.0] * 8 + [100.0, 100.0],
            "SUPERTd_7_2.1": [-1.0] * 9 + [1.0],
            "SUPERTl_7_2.1": [np.nan] * 9 + [98.0],
        },
        index=pd.date_range("2026-10-01", periods=10),
    )

    plan = _supertrend_plan(history, "1d")

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["stop"] == 98.0
    assert plan["parameters"]["supertrend_multiplier"] == 2.1


def test_alligator_requires_waking_fan_and_expanding_green_macd():
    history = pd.DataFrame(
        {
            "Close": np.full(40, 110.0),
            "AlligatorJaw": np.full(40, 100.0),
            "AlligatorTeeth": np.full(40, 103.0),
            "AlligatorLips": np.full(40, 106.0),
            "MACDh_12_26_9": np.full(40, 0.1),
        },
        index=pd.date_range("2026-09-01", periods=40),
    )
    history.iloc[-2, history.columns.get_loc("AlligatorJaw")] = 101.0
    history.iloc[-2, history.columns.get_loc("AlligatorTeeth")] = 100.0
    history.iloc[-2, history.columns.get_loc("AlligatorLips")] = 99.0
    history.iloc[-1, history.columns.get_loc("MACDh_12_26_9")] = 0.2

    plan = _alligator_plan(history)

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["stop"] == 103.0
    assert plan["parameters"]["jaw_forward_shift"] == 8


def test_bread_and_butter_requires_volume_breakout_then_bullish_ema20_retest():
    history = pd.DataFrame(
        {
            "Open": np.full(50, 99.0),
            "High": np.full(50, 100.0),
            "Low": np.full(50, 98.0),
            "Close": np.full(50, 99.0),
            "Volume": np.full(50, 100.0),
            "EMA20": np.full(50, 99.0),
        },
        index=pd.date_range("2026-09-01", periods=50),
    )
    history.iloc[45, history.columns.get_loc("Close")] = 102.0
    history.iloc[45, history.columns.get_loc("High")] = 103.0
    history.iloc[45, history.columns.get_loc("Volume")] = 200.0
    history.iloc[-1, history.columns.get_loc("Open")] = 99.0
    history.iloc[-1, history.columns.get_loc("Low")] = 98.5
    history.iloc[-1, history.columns.get_loc("Close")] = 100.0
    history.iloc[-1, history.columns.get_loc("High")] = 101.0

    plan = _bread_and_butter_plan(history, "1d")

    assert plan["status"] == "ENTRY_TRIGGERED"
    assert plan["breakout_resistance"] == 100.0
    assert plan["stop"] == 99.0
    assert plan["target"] == 103.0
