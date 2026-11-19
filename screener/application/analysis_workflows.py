"""Use-case workflows for analysis and persistence of screener candidates."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from screener.application.analysis_ports import AnalysisDependencies
from screener.domain.indicators import DEFAULT_INDICATORS
from screener.domain.trade_plans import build_long_trade_plan, round_price, value_or_none


logger = logging.getLogger(__name__)


def _fail_analysis_run(manager, analysis_run_id):
    try:
        manager.finish_analysis_run(
            analysis_run_id, datetime.now(timezone.utc), status="failed"
        )
    except Exception:
        logger.exception("Could not mark analysis run %s as failed", analysis_run_id)
    finally:
        manager.close()


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
    *,
    dependencies: AnalysisDependencies,
):
    """Analyze captured screener levels and add strategy plans from latest history."""
    manager = dependencies.repository_factory()
    analysis_started_at = datetime.now(timezone.utc)
    analysis_run_id = str(uuid4())
    try:
        run_metadata, source_rows = manager.load_screener_run(screener_run_id)
        selected = source_rows.copy()
        if tickers:
            requested = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
            selected = selected[selected["ticker"].astype(str).str.upper().isin(requested)]
        if min_score is not None:
            selected = selected[selected["score"] >= min_score]
        selected = selected.sort_values("score", ascending=False)
        if top_n is not None:
            selected = selected.head(top_n)

        indicator_columns = (
            "ALMA", "MACDh_12_26_9", "AO", "PSARl_0.02_0.2", "EMA50", "EMA100",
            "EMA200", "SMA50", "SMA100", "SMA200", "BBM_20_2.0",
            "STOCHRSIk_14_14_3_3", "TEMA_21", "VolumeAvg20", "RSI_14",
            "ATRr_14", "CCI_20", "WILLR_14", "ADX_14", "OBV", "MOM_10",
            "ROC_12", "KCLe_20_2", "ISA_9", "ADOSC", "VPT",
        )
        analysis_rows = []
        source_run_id = str(run_metadata["run_id"])
        analysis_run_started = False
        if save_to_db:
            if selected.empty:
                analysis_start_date = run_metadata["end_date"]
                analysis_end_date = run_metadata["end_date"]
            else:
                captured_dates = pd.to_datetime(selected["date"])
                analysis_start_date = captured_dates.min().date()
                analysis_end_date = captured_dates.max().date()
            manager.start_analysis_run({
                "analysis_run_id": analysis_run_id,
                "screener_run_id": source_run_id,
                "started_at": analysis_started_at,
                "source_file": f"screener_run:{source_run_id}",
                "requested_tickers": ",".join(selected["ticker"].astype(str).tolist()),
                "min_score": min_score,
                "top_n": top_n,
                "start_date": analysis_start_date,
                "end_date": analysis_end_date,
                "indicators": run_metadata["indicators"],
                "rr_ratio": rr_ratio,
                "price_decimals": price_decimals,
                "expected_count": len(selected),
            })
            analysis_run_started = True

        for _, source_row in selected.iterrows():
            close = value_or_none(source_row, "close")
            atr = value_or_none(source_row, "ATRr_14")
            ema100 = value_or_none(source_row, "EMA100")
            ema200 = value_or_none(source_row, "EMA200")
            captured_rr_ratio = value_or_none(source_row, "rr_ratio") or rr_ratio
            if close is not None and atr is not None and atr > 0 and (ema100 is not None or ema200 is not None):
                plan = build_long_trade_plan(
                    pd.Series({
                        "Close": close,
                        "ATRr_14": atr,
                        "EMA100": ema100,
                        "EMA200": ema200,
                    }),
                    rr_ratio=captured_rr_ratio,
                    price_decimals=price_decimals,
                )
            else:
                captured_stop = value_or_none(source_row, "stop")
                captured_target = value_or_none(source_row, "target")
                captured_risk = close - captured_stop if close is not None and captured_stop is not None else None
                actionable = bool(
                    captured_risk is not None
                    and captured_risk > 0
                    and captured_target is not None
                    and captured_target > close
                )
                plan = {
                    "setup": "captured_screener_levels",
                    "actionable": actionable,
                    "entry_rule": "use captured close and screener stop/target",
                    "entry": round_price(close, price_decimals) if actionable else None,
                    "entry_support": "screener_close" if actionable else None,
                    "stop": round_price(captured_stop, price_decimals) if actionable else None,
                    "target": round_price(captured_target, price_decimals) if actionable else None,
                    "risk_per_share": round_price(captured_risk, price_decimals) if actionable else None,
                    "rr_ratio": captured_rr_ratio,
                    "data_note": None if actionable else "Captured run lacks EMA/ATR inputs and usable stop/target levels",
                }

            as_of = pd.Timestamp(source_row["date"]).date().isoformat()
            indicators = {
                column: value_or_none(source_row, column)
                for column in indicator_columns
                if column in source_row.index
            }
            signals = {}
            for column, value in source_row.items():
                if column.endswith(("_bull", "_bear")) or "_cross_" in column or "_above_" in column or "_below_" in column:
                    signals[column] = None if pd.isna(value) else bool(value)

            try:
                latest_context = dependencies.fetch_ticker_context(source_row["ticker"])
                strategy_analysis = dependencies.fetch_strategy_plans(
                    source_row["ticker"],
                    latest_context["history"],
                    rsi_threshold=rsi_threshold,
                    macd_zero_tolerance_pct=macd_zero_tolerance_pct,
                    support_lookback=fishball_support_lookback,
                )
                analysis_note = plan.get("data_note")
            except Exception as exc:
                logger.exception(
                    "Strategy analysis failed for %s; continuing with remaining screened tickers",
                    source_row["ticker"],
                )
                strategy_analysis = {"strategies": {}, "parameters": {}}
                analysis_note = f"Strategy analysis unavailable: {exc}"
            plan = {
                **plan,
                "strategies": strategy_analysis["strategies"],
                "strategy_parameters": strategy_analysis["parameters"],
                "manual_review_only": True,
                "data_note": analysis_note,
            }
            analysis_rows.append({
                "ticker": source_row["ticker"],
                "as_of": as_of,
                "close": close,
                "score": source_row["score"],
                "signals": ",".join(name for name, value in signals.items() if value is True),
                "entry": plan["entry"],
                "entry_support": plan["entry_support"],
                "stop": plan["stop"],
                "target": plan["target"],
                "risk_per_share": plan["risk_per_share"],
                "actionable": plan["actionable"],
                "analysis_note": analysis_note,
                "strategy_plans": strategy_analysis["strategies"],
            })

            if save_to_db:
                manager.save_analysis_result(analysis_run_id, {
                    "screener_run_id": source_run_id,
                    "ticker": source_row["ticker"],
                    "as_of": as_of,
                    "captured_at": datetime.now(timezone.utc),
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": close,
                    "volume": None,
                    "ema50": indicators.get("EMA50"),
                    "ema100": ema100,
                    "ema200": ema200,
                    "rsi_14": indicators.get("RSI_14"),
                    "atr_14": atr,
                    "entry": plan["entry"],
                    "entry_support": plan["entry_support"],
                    "stop": plan["stop"],
                    "target": plan["target"],
                    "risk_per_share": plan["risk_per_share"],
                    "actionable": plan["actionable"],
                    "indicators": indicators,
                    "signals": signals,
                    "plan": plan,
                    "screener_snapshot": source_row.to_dict(),
                })

        analysis_columns = [
            "ticker", "as_of", "close", "score", "signals", "entry", "entry_support",
            "stop", "target", "risk_per_share", "actionable", "analysis_note",
            "strategy_plans",
        ]
        analysis_results = pd.DataFrame(analysis_rows, columns=analysis_columns)

        if save_to_db:
            manager.finish_analysis_run(analysis_run_id, datetime.now(timezone.utc))
            analysis_run_started = False
        return analysis_results
    except Exception:
        if save_to_db and locals().get("analysis_run_started", False):
            try:
                manager.finish_analysis_run(
                    analysis_run_id, datetime.now(timezone.utc), status="failed"
                )
            except Exception:
                logger.exception("Could not mark analysis run %s as failed", analysis_run_id)
        raise
    finally:
        manager.close()


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
    *,
    dependencies: AnalysisDependencies,
):
    """Augment selected screener rows with fresh data, indicators, and plans.

    When ``tickers`` is omitted, rows are read from ``results_path`` and can be
    selected with ``min_score`` and/or ``top_n``. The returned DataFrame keeps
    the original screener columns and appends the latest market context and
    rule-based long plan fields. Set ``include_strategies=False`` for consumers
    that only need the existing EMA/ATR plan.
    """
    analysis_started_at = datetime.now(timezone.utc)
    analysis_run_id = str(uuid4())
    results = pd.read_csv(Path(results_path))
    if "ticker" not in results.columns:
        raise ValueError(f"{results_path}: expected a ticker column")

    if tickers is not None:
        requested = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
        selected = results[results["ticker"].str.upper().isin(requested)].copy()
    else:
        selected = results.copy()
        if min_score is not None:
            if "score" not in selected.columns:
                raise ValueError(f"{results_path}: score filtering requires a score column")
            selected = selected[selected["score"] >= min_score]
        selected = selected.sort_values("score", ascending=False) if "score" in selected.columns else selected
        if top_n is not None:
            selected = selected.head(top_n)

    # The source CSV may already contain stop/target values calculated at the
    # screening close. Preserve them under explicit names so fresh plan values
    # can remain the canonical stop/target columns in the augmented output.
    selected = selected.rename(
        columns={"stop": "screener_stop", "target": "screener_target"}
    )

    manager = None
    if save_to_db:
        manager = dependencies.repository_factory()
        source_run_ids = (
            selected["run_id"].dropna().astype(str).unique()
            if "run_id" in selected.columns
            else []
        )
        try:
            manager.start_analysis_run({
                "analysis_run_id": analysis_run_id,
                "screener_run_id": screener_run_id or (
                    source_run_ids[0] if len(source_run_ids) == 1 else None
                ),
                "started_at": analysis_started_at,
                "source_file": str(results_path),
                "requested_tickers": ",".join(selected["ticker"].astype(str).tolist()),
                "min_score": min_score,
                "top_n": top_n,
                "start_date": start,
                "end_date": end or pd.Timestamp.today().strftime("%Y-%m-%d"),
                "indicators": ",".join(indicators or DEFAULT_INDICATORS),
                "rr_ratio": rr_ratio,
                "price_decimals": price_decimals,
                "expected_count": len(selected["ticker"].drop_duplicates()),
            })
        except Exception:
            manager.close()
            raise

    augmented = []
    for ticker in selected["ticker"].drop_duplicates().tolist():
        source_row = selected.loc[
            selected["ticker"].astype(str).str.upper() == str(ticker).upper()
        ].iloc[0]
        source_run_id = screener_run_id or source_row.get("run_id")
        if pd.isna(source_run_id):
            source_run_id = None
        elif source_run_id is not None:
            source_run_id = str(source_run_id)

        try:
            context = dependencies.fetch_ticker_context(
                ticker,
                start=start,
                end=end,
                indicators=indicators,
                rr_ratio=rr_ratio,
                price_decimals=price_decimals,
            )
            plan = context["plan"]
            strategy_history = context["history"]
            if include_strategies and end is not None:
                strategy_history = dependencies.fetch_ticker_context(
                    ticker,
                    start=start,
                    indicators=indicators,
                    rr_ratio=rr_ratio,
                    price_decimals=price_decimals,
                )["history"]
            strategy_analysis = (
                dependencies.fetch_strategy_plans(
                    ticker,
                    strategy_history,
                    rsi_threshold=rsi_threshold,
                    macd_zero_tolerance_pct=macd_zero_tolerance_pct,
                    support_lookback=fishball_support_lookback,
                )
                if include_strategies
                else {"strategies": {}, "parameters": {}}
            )
        except Exception:
            if manager is not None:
                _fail_analysis_run(manager, analysis_run_id)
                manager = None
            raise
        plan = {
            **plan,
            "strategies": strategy_analysis["strategies"],
            "strategy_parameters": strategy_analysis["parameters"],
            "manual_review_only": True,
        }
        indicators_now = context["indicators"]
        augmented.append({
            "ticker": ticker,
            "as_of": context["as_of"],
            "current_close": context["close"],
            "current_volume": context["volume"],
            "ema100": indicators_now["EMA100"],
            "ema200": indicators_now["EMA200"],
            "rsi_14": indicators_now["RSI_14"],
            "atr_14": indicators_now["ATRr_14"],
            "entry": plan["entry"],
            "entry_support": plan["entry_support"],
            "stop": plan["stop"],
            "target": plan["target"],
            "risk_per_share": plan["risk_per_share"],
            "actionable": plan["actionable"],
            "signals": ",".join(name for name, value in context["signals"].items() if value),
            "strategy_plans": strategy_analysis["strategies"],
        })

        if manager is not None:
            try:
                manager.save_analysis_result(analysis_run_id, {
                    "screener_run_id": source_run_id,
                    "ticker": ticker,
                    "as_of": context["as_of"],
                    "captured_at": datetime.now(timezone.utc),
                    "open": context.get("open"),
                    "high": context.get("high"),
                    "low": context.get("low"),
                    "close": context.get("close"),
                    "volume": context.get("volume"),
                    "ema50": indicators_now.get("EMA50"),
                    "ema100": indicators_now.get("EMA100"),
                    "ema200": indicators_now.get("EMA200"),
                    "rsi_14": indicators_now.get("RSI_14"),
                    "atr_14": indicators_now.get("ATRr_14"),
                    "entry": plan.get("entry"),
                    "entry_support": plan.get("entry_support"),
                    "stop": plan.get("stop"),
                    "target": plan.get("target"),
                    "risk_per_share": plan.get("risk_per_share"),
                    "actionable": plan.get("actionable"),
                    "indicators": context["indicators"],
                    "signals": context["signals"],
                    "plan": plan,
                    "screener_snapshot": source_row.to_dict(),
                })
            except Exception:
                _fail_analysis_run(manager, analysis_run_id)
                manager = None
                raise

    analysis_columns = [
        "ticker", "as_of", "current_close", "current_volume", "ema100", "ema200",
        "rsi_14", "atr_14", "entry", "entry_support", "stop", "target",
        "risk_per_share", "actionable", "signals", "strategy_plans",
    ]
    analysis_frame = pd.DataFrame(augmented, columns=analysis_columns)
    combined = selected.merge(analysis_frame, on="ticker", how="left")

    if manager is not None:
        try:
            manager.finish_analysis_run(analysis_run_id, datetime.now(timezone.utc))
        finally:
            manager.close()

    return combined