from datetime import datetime, timezone
from contextlib import nullcontext
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import screener.persistence as persistence
from screener.postgresql_factory import PostgresConnectionFactory
import screener.run_daily as run_daily
import screener.stocks_screener as stocks_screener
import screener.trade_analysis as trade_analysis


class FakeTransaction:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("transaction_started")

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("transaction_finished")


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.statements = []

    def begin(self):
        return FakeTransaction(self.events)

    def execute(self, statement, parameters):
        self.statements.append((str(statement), parameters))
        self.events.append("statement_executed")
        return type("UpdateResult", (), {"rowcount": 1})()


class ScreenerPersistenceTests(TestCase):
    def test_daily_runner_analyzes_its_screener_run_without_csv(self):
        screener_run_id = "47141ed8-aef5-42a1-a5c9-f6585600ee0d"
        with patch.dict("os.environ", {}, clear=True), patch.object(
            run_daily.stocks_screener, "main", return_value=screener_run_id
        ) as screener_main, patch.object(run_daily.stock_analysis, "main") as analysis_main:
            run_daily.main()

        screener_args = screener_main.call_args.args[0]
        analysis_args = analysis_main.call_args.args[0]
        self.assertNotIn("--output", screener_args)
        self.assertEqual(analysis_args[analysis_args.index("--screener-run-id") + 1], screener_run_id)

    def test_screener_does_not_write_csv_by_default(self):
        with patch.object(stocks_screener, "universe_tickers", return_value=["TEST"]), patch.object(
            stocks_screener, "process_ticker",
            return_value={"ticker": "TEST", "score": 1, "close": 10.0},
        ), patch.object(stocks_screener.time, "sleep"), patch.object(
            pd.DataFrame, "to_csv"
        ) as to_csv:
            stocks_screener.main(["--symbols", "TEST"])

        to_csv.assert_not_called()

    def test_database_screener_captures_inputs_for_historical_trade_plan(self):
        index = pd.date_range("2026-09-01", periods=30, freq="D")
        close = np.arange(100.0, 130.0)
        history = pd.DataFrame({
            "Open": close - 1,
            "High": close + 1,
            "Low": close - 2,
            "Close": close,
            "Volume": np.full(30, 1000.0),
        }, index=index)
        captured_indicators = []

        def add_captured_indicators(frame, requested):
            captured_indicators.extend(requested)
            enriched = frame.copy()
            enriched["EMA100"] = 110.0
            enriched["EMA200"] = 100.0
            enriched["ATRr_14"] = 2.0
            return enriched

        class Args:
            start = "2026-09-01"
            end = "2026-10-01"
            save_db = True
            above_filters = []
            above_mode = "any"
            green_only = False
            rr_ratio = 3.0

        with patch.object(stocks_screener.yf, "download", return_value=history), patch.object(
            stocks_screener, "add_indicators", side_effect=add_captured_indicators
        ):
            row = stocks_screener.process_ticker("TEST", Args(), indicators=["rsi"])

        self.assertEqual(set(captured_indicators), {"rsi", "ema100", "ema200", "atr"})
        self.assertEqual(row["stop"], 127.0)
        self.assertEqual(row["target"], 135.0)

    def test_config_values_strip_outer_quotes_only(self):
        self.assertEqual(persistence._strip_ini_quotes('"postgres"'), "postgres")
        self.assertEqual(persistence._strip_ini_quotes('"secret@part:two"'), "secret@part:two")
        self.assertEqual(persistence._strip_ini_quotes("plain-value"), "plain-value")

    def test_database_environment_overrides_ini_without_config_file(self):
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)
        environment = {
            "DB_HOST": "postgres.database.svc",
            "DB_PORT": "5433",
            "DB_USER": "screening",
            "DB_PASSWORD": "secret",
            "DB_NAME": "stocks",
        }

        with patch.dict("os.environ", environment, clear=True), patch.object(
            persistence.os.path, "exists", return_value=False
        ):
            db_config = manager.load_db_config("config.ini")

        self.assertEqual(db_config, {
            "host": "postgres.database.svc",
            "port": 5433,
            "user": "screening",
            "password": "secret",
            "database": "stocks",
        })

    def test_connection_url_preserves_reserved_password_characters(self):
        factory = object.__new__(PostgresConnectionFactory)
        db_config = {
            "user": "postgres",
            "password": "secret@part:two/three",
            "host": "database.example.test",
            "port": 5432,
            "database": "stocks",
        }

        with patch("screener.postgresql_factory.create_engine") as create_engine:
            factory.__init__(**db_config)

        url = create_engine.call_args.args[0]
        self.assertEqual(url.username, db_config["user"])
        self.assertEqual(url.password, db_config["password"])
        self.assertEqual(url.host, db_config["host"])
        self.assertEqual(url.port, db_config["port"])
        self.assertEqual(url.database, db_config["database"])

    def test_saves_run_and_results_in_one_transaction(self):
        events = []
        connection = FakeConnection(events)
        writes = []
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)

        def record_to_sql(frame, table_name, sql_connection, **kwargs):
            events.append(table_name)
            writes.append((table_name, frame.copy(), sql_connection, kwargs))

        metadata = {
            "run_id": "56b141db-b46b-43b1-97f1-e24c6386f5cc",
            "started_at": pd.Timestamp("2026-09-30T12:00:00Z"),
            "finished_at": pd.Timestamp("2026-09-30T12:01:00Z"),
            "universe": "sp500",
            "selected_symbols": "AAPL",
            "indicators": "rsi",
            "start_date": "2026-01-01",
            "end_date": "2026-09-30",
            "max_symbols": 200,
            "green_only": True,
            "above_filters": "",
            "above_mode": "any",
            "rr_ratio": 3.0,
            "result_count": 1,
            "output_file": "results.csv",
        }
        results = pd.DataFrame([{"ticker": "AAPL", "date": "2026-09-29", "score": 4}])

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ), patch.object(pd.DataFrame, "to_sql", new=record_to_sql):
            manager.save_screener_run(metadata, results)

        self.assertEqual(
            events,
            ["transaction_started", "screener_runs", "screener_results", "transaction_finished"],
        )
        self.assertEqual([write[0] for write in writes], ["screener_runs", "screener_results"])
        self.assertEqual(writes[1][1].loc[0, "run_id"], metadata["run_id"])
        self.assertIs(writes[1][2], connection)
        self.assertEqual(writes[1][3]["if_exists"], "append")

    def test_saves_run_metadata_when_no_tickers_pass(self):
        events = []
        connection = FakeConnection(events)
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)
        metadata = {"run_id": "56b141db-b46b-43b1-97f1-e24c6386f5cc"}
        results = pd.DataFrame()

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ), patch.object(pd.DataFrame, "to_sql") as to_sql:
            manager.save_screener_run(metadata, results)

        to_sql.assert_called_once()
        self.assertEqual(events, ["transaction_started", "transaction_finished"])

    def test_saves_analysis_json_and_screener_link_atomically(self):
        events = []
        connection = FakeConnection(events)
        writes = []
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)

        def record_to_sql(frame, table_name, sql_connection, **kwargs):
            events.append(table_name)
            writes.append((table_name, frame.copy(), kwargs))

        metadata = {
            "analysis_run_id": "56b141db-b46b-43b1-97f1-e24c6386f5cc",
            "started_at": datetime.now(timezone.utc),
            "finished_at": datetime.now(timezone.utc),
            "source_file": "results.csv",
            "requested_tickers": "AAPL",
            "min_score": None,
            "top_n": 10,
            "start_date": "2026-01-01",
            "end_date": "2026-09-30",
            "indicators": "rsi,atr",
            "rr_ratio": 3.0,
            "price_decimals": 2,
            "result_count": 1,
        }
        screener_run_id = "47141ed8-aef5-42a1-a5c9-f6585600ee0d"
        results = pd.DataFrame([{
            "screener_run_id": screener_run_id,
            "ticker": "AAPL",
            "as_of": "2026-09-29",
            "captured_at": datetime.now(timezone.utc),
            "actionable": True,
            "indicators": {"RSI_14": np.float64(60.0), "ATRr_14": float("nan")},
            "signals": {"rsi_bull": np.bool_(True)},
            "plan": {"entry": np.float64(100.0)},
            "screener_snapshot": {"ticker": "AAPL", "score": np.int64(5)},
        }])

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ), patch.object(pd.DataFrame, "to_sql", new=record_to_sql):
            manager.save_analysis_run(metadata, results)

        self.assertEqual(
            events,
            ["transaction_started", "analysis_runs", "analysis_results", "transaction_finished"],
        )
        saved = writes[1][1].iloc[0]
        self.assertEqual(saved["screener_run_id"], screener_run_id)
        self.assertIsNone(saved["indicators"]["ATRr_14"])
        self.assertTrue(saved["signals"]["rsi_bull"])
        self.assertEqual(saved["plan"]["entry"], 100.0)

    def test_saves_analysis_result_in_one_parameterized_transaction(self):
        events = []
        connection = FakeConnection(events)
        writes = []
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)
        snapshot = {
            "screener_run_id": "47141ed8-aef5-42a1-a5c9-f6585600ee0d",
            "ticker": "AAPL",
            "as_of": "2026-09-29",
            "captured_at": datetime.now(timezone.utc),
            "actionable": True,
            "indicators": {"RSI_14": np.float64(60.0)},
            "signals": {"rsi_bull": np.bool_(True)},
            "plan": {"entry": np.float64(100.0)},
            "screener_snapshot": {"ticker": "AAPL", "score": np.int64(5)},
        }

        def record_to_sql(frame, table_name, sql_connection, **kwargs):
            events.append(table_name)
            writes.append((table_name, frame.copy(), kwargs))

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ), patch.object(pd.DataFrame, "to_sql", new=record_to_sql):
            manager.save_analysis_result(
                "56b141db-b46b-43b1-97f1-e24c6386f5cc", snapshot
            )

        self.assertEqual(
            events,
            [
                "transaction_started",
                "statement_executed",
                "transaction_finished",
            ],
        )
        statement, parameters = connection.statements[0]
        self.assertIn("INSERT INTO public.analysis_results", statement)
        self.assertIn("result_count = run.result_count + 1", statement)
        self.assertEqual(parameters["ticker"], "AAPL")
        self.assertEqual(parameters["signals"], '{"rsi_bull":true}')
        self.assertEqual(
            parameters["screener_snapshot"], '{"ticker":"AAPL","score":5}'
        )

    def test_analysis_row_matches_shared_go_contract_fixture(self):
        fixture_path = Path(__file__).parents[2] / "contracts" / "analysis_result_row.json"
        fixture = json.loads(fixture_path.read_text())
        snapshot = dict(fixture)
        snapshot["captured_at"] = datetime.fromisoformat(fixture["captured_at"])
        connection = FakeConnection([])
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ):
            manager.save_analysis_result(fixture["analysis_run_id"], snapshot)

        _, parameters = connection.statements[0]
        self.assertEqual(set(parameters), set(fixture))
        json_columns = ("indicators", "signals", "plan", "screener_snapshot")
        for column in json_columns:
            self.assertEqual(json.loads(parameters[column]), fixture[column])
        for column, expected in fixture.items():
            if column not in json_columns and column != "captured_at":
                self.assertEqual(parameters[column], expected, column)
        self.assertEqual(parameters["captured_at"], snapshot["captured_at"])

    def test_analysis_run_lifecycle_stores_progress_and_terminal_status(self):
        events = []
        connection = FakeConnection(events)
        manager = persistence.PersistenceManager.__new__(persistence.PersistenceManager)
        run_metadata = {
            "analysis_run_id": "56b141db-b46b-43b1-97f1-e24c6386f5cc",
            "screener_run_id": "47141ed8-aef5-42a1-a5c9-f6585600ee0d",
            "started_at": datetime.now(timezone.utc),
            "source_file": "screener_run:47141ed8-aef5-42a1-a5c9-f6585600ee0d",
            "requested_tickers": "AAPL,MSFT",
            "min_score": None,
            "top_n": None,
            "start_date": "2026-01-01",
            "end_date": "2026-09-30",
            "indicators": "rsi,atr",
            "rr_ratio": 3.0,
            "price_decimals": 2,
            "expected_count": 2,
        }

        with patch.object(
            persistence.PersistenceManager,
            "connect",
            return_value=nullcontext(connection),
        ):
            manager.start_analysis_run(run_metadata)
            manager.finish_analysis_run(
                run_metadata["analysis_run_id"],
                datetime.now(timezone.utc),
                status="failed",
            )

        start_statement, start_parameters = connection.statements[0]
        self.assertIn("'running'", start_statement)
        self.assertIn("finished_at", start_statement)
        self.assertEqual(start_parameters["expected_count"], 2)
        finish_statement, finish_parameters = connection.statements[1]
        self.assertIn("status = :status", finish_statement)
        self.assertEqual(finish_parameters["status"], "failed")

    def test_analysis_infers_screener_run_id_from_input_csv(self):
        screener_run_id = "47141ed8-aef5-42a1-a5c9-f6585600ee0d"
        context = {
            "ticker": "AAPL",
            "as_of": "2026-09-29",
            "close": 120.0,
            "open": 119.0,
            "high": 121.0,
            "low": 118.0,
            "volume": 1000,
            "indicators": {"EMA50": 110.0, "EMA100": 108.0, "EMA200": 100.0, "RSI_14": 60.0, "ATRr_14": 5.0},
            "signals": {"rsi_bull": True},
            "plan": {
                "entry": 108.0, "entry_support": "EMA100", "stop": 103.0,
                "target": 123.0, "risk_per_share": 5.0, "actionable": True,
            },
            "history": pd.DataFrame(),
        }
        manager = MagicMock()

        with TemporaryDirectory() as directory:
            results_path = Path(directory) / "results.csv"
            pd.DataFrame([{
                "ticker": "AAPL", "run_id": screener_run_id,
                "score": 5, "stop": 100.0, "target": 130.0,
            }]).to_csv(results_path, index=False)
            with patch.object(trade_analysis, "fetch_ticker_context", return_value=context), patch.object(
                trade_analysis,
                "fetch_strategy_plans",
                return_value={"strategies": {"MAMA_daily": {"status": "WATCH"}}, "parameters": {}},
            ), patch.object(
                persistence, "PersistenceManager", return_value=manager
            ):
                trade_analysis.augment_screener_results(str(results_path), save_to_db=True)

        manager.start_analysis_run.assert_called_once()
        manager.save_analysis_run.assert_not_called()
        manager.finish_analysis_run.assert_called_once()
        manager.save_analysis_result.assert_called_once()
        snapshot = manager.save_analysis_result.call_args.args[1]
        self.assertEqual(snapshot["screener_run_id"], screener_run_id)
        self.assertEqual(snapshot["screener_snapshot"]["score"], 5)
        run_metadata = manager.start_analysis_run.call_args.args[0]
        self.assertEqual(run_metadata["screener_run_id"], screener_run_id)
        self.assertEqual(run_metadata["expected_count"], 1)

    def test_screener_run_analysis_adds_latest_strategy_suggestions(self):
        screener_run_id = "47141ed8-aef5-42a1-a5c9-f6585600ee0d"
        run_metadata = {
            "run_id": screener_run_id,
            "start_date": pd.Timestamp("2026-01-01").date(),
            "end_date": pd.Timestamp("2026-09-30").date(),
            "indicators": "ema100,ema200,atr,rsi",
        }
        source_rows = pd.DataFrame([{
            "run_id": screener_run_id,
            "ticker": "AAPL",
            "date": pd.Timestamp("2026-09-29").date(),
            "close": 120.0,
            "EMA100": 110.0,
            "EMA200": 100.0,
            "ATRr_14": 5.0,
            "RSI_14": 60.0,
            "rsi_bull": True,
            "score": 5,
            "stop": 115.0,
            "target": 135.0,
            "rr_ratio": 3.0,
        }])
        manager = MagicMock()
        manager.load_screener_run.return_value = (run_metadata, source_rows)

        latest_context = {
            "history": pd.DataFrame({
                "Close": [120.0, 121.0],
                "Open": [119.0, 120.0],
                "High": [122.0, 123.0],
                "Low": [118.0, 119.0],
                "Volume": [1000, 1100],
            }, index=pd.date_range("2026-10-01", periods=2)),
        }
        with patch.object(persistence, "PersistenceManager", return_value=manager), patch.object(
            trade_analysis, "fetch_ticker_context", return_value=latest_context
        ), patch.object(
            trade_analysis,
            "fetch_strategy_plans",
            return_value={"strategies": {"MAMA_daily": {"status": "WATCH"}}, "parameters": {}},
        ):
            analysis = trade_analysis.analyze_screener_run(
                "latest", min_score=5, top_n=10, save_to_db=True
            )

        self.assertEqual(analysis.loc[0, "as_of"], "2026-09-29")
        self.assertEqual(analysis.loc[0, "entry"], 110.0)
        self.assertEqual(analysis.loc[0, "stop"], 105.0)
        self.assertEqual(analysis.loc[0, "target"], 125.0)
        self.assertTrue(analysis.loc[0, "actionable"])
        self.assertEqual(analysis.loc[0, "strategy_plans"]["MAMA_daily"]["status"], "WATCH")
        manager.load_screener_run.assert_called_once_with("latest")
        metadata = manager.start_analysis_run.call_args.args[0]
        self.assertEqual(metadata["source_file"], f"screener_run:{screener_run_id}")
        self.assertEqual(metadata["start_date"], pd.Timestamp("2026-09-29").date())
        self.assertEqual(metadata["end_date"], pd.Timestamp("2026-09-29").date())
        self.assertEqual(manager.save_analysis_result.call_count, 1)
        saved_run_id, snapshot = manager.save_analysis_result.call_args.args
        self.assertEqual(saved_run_id, metadata["analysis_run_id"])
        self.assertEqual(snapshot["screener_run_id"], screener_run_id)
        self.assertEqual(snapshot["as_of"], "2026-09-29")
        manager.finish_analysis_run.assert_called_once()
        manager.close.assert_called_once()