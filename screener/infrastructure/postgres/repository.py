"""PostgreSQL implementation of the screener persistence repository."""
from contextlib import contextmanager
import configparser
from datetime import date, datetime
from decimal import Decimal
import json
import math
import os
import logging as log
import sys

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from screener.infrastructure.postgres.connection_factory import PostgresConnectionFactory
from uuid import UUID as PythonUUID
log.basicConfig(level=log.INFO)


def _strip_ini_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return str(value)


class PersistenceManager:
    """PostgreSQL repository for screener runs and analysis snapshots.

    Configuration is read from ``config.ini`` with environment variables
    taking precedence. Methods map application dictionaries to the existing
    PostgreSQL schema and use database transactions for writes.
    """

    def __init__(self ):
        """Load configuration for the repository's database connection."""
        config_file="config.ini"
        self.load_db_config(config_file)
    
    

    def load_db_config(self,config_file):
        """Load database configuration from an INI file with validation."""
        log.info(f"Loading database configuration from {config_file}")
        config = configparser.ConfigParser()

        config.read(config_file)

        ini_value = lambda key, fallback: _strip_ini_quotes(
            config.get("database", key, fallback=fallback)
        )
        db_config = {
            "host": os.getenv("DB_HOST", ini_value("host", "localhost")) or None,
            "port": int(os.getenv("DB_PORT", ini_value("port", "5432"))),
            "user": os.getenv("DB_USER", ini_value("user", "")) or None,
            "password": os.getenv("DB_PASSWORD", ini_value("password", "")) or None,
            "database": os.getenv("DB_NAME", ini_value("database", "")) or None,
        }

        # Validate required fields
        missing = [k for k, v in db_config.items() if v is None]
        if missing:
            log.error(f"Error: Missing required database config keys: {', '.join(missing)}")
            sys.exit(1)

        self.db_config = db_config
        return db_config

    @contextmanager
    def connect(self):
        """Yield a database connection from the configured engine."""
        log.info("Establishing database connection")
        # database_url = (
        #     f"postgresql+psycopg2://{self.db_config['user']}:{self.db_config['password']}@"
        #     f"{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        # )
        # engine = create_engine(database_url)
        postgresConnectionFactory = PostgresConnectionFactory(**self.db_config)
        try:
            with postgresConnectionFactory.get_connection() as connection:
                log.info("Database connection established successfully")
                yield connection
        except Exception as e:
            log.error(f"Database connection error: {e}")
            raise
        # finally:
        #     postgresConnectionFactory.release_connection(connection)

    def save_screener_run(self, run_metadata, results):
        """Append one run and its ticker results atomically."""
        results_to_save = results.copy()
        run_id = str(run_metadata["run_id"])
        if "run_id" in results_to_save.columns:
            result_run_ids = results_to_save["run_id"].dropna().astype(str).unique()
            if len(result_run_ids) > 1 or (len(result_run_ids) == 1 and result_run_ids[0] != run_id):
                raise ValueError("Screener result run_id values must match the run metadata")
        else:
            results_to_save.insert(0, "run_id", run_id)
        run_data = pd.DataFrame([run_metadata])
        uuid_type = UUID(as_uuid=False)

        with self.connect() as connection:
            with connection.begin():
                run_data.to_sql(
                    "screener_runs",
                    connection,
                    schema="public",
                    if_exists="append",
                    index=False,
                    dtype={"run_id": uuid_type},
                )
                if not results_to_save.empty:
                    results_to_save.to_sql(
                        "screener_results",
                        connection,
                        schema="public",
                        if_exists="append",
                        index=False,
                        dtype={"run_id": uuid_type},
                    )

    def load_screener_run(self, run_id="latest"):
        """Load a captured screener run and its saved ticker results."""
        if run_id is None or str(run_id).lower() == "latest":
            run_query = text(
                "SELECT * FROM screener_runs ORDER BY started_at DESC, run_id DESC LIMIT 1"
            )
            params = {}
        else:
            try:
                run_id = str(PythonUUID(str(run_id)))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("screener_run_id must be a UUID or 'latest'") from exc
            run_query = text(
                "SELECT * FROM screener_runs WHERE run_id = CAST(:run_id AS UUID)"
            )
            params = {"run_id": run_id}

        with self.connect() as connection:
            run = connection.execute(run_query, params).mappings().first()
            if run is None:
                requested = run_id if params else "latest"
                raise ValueError(f"No screener run found for {requested}")
            run_metadata = dict(run)
            result_rows = pd.read_sql(
                text(
                    "SELECT * FROM screener_results "
                    "WHERE run_id = CAST(:run_id AS UUID) ORDER BY ticker"
                ),
                connection,
                params={"run_id": str(run_metadata["run_id"])},
            )
        return run_metadata, result_rows

    def start_analysis_run(self, run_metadata):
        """Create an analysis-run record before processing ticker snapshots."""
        with self.connect() as connection:
            with connection.begin():
                connection.execute(
                    text(
                        """
                        INSERT INTO public.analysis_runs (
                            analysis_run_id, screener_run_id, started_at, finished_at,
                            status, source_file, requested_tickers, min_score, top_n,
                            start_date, end_date, indicators, rr_ratio,
                            price_decimals, result_count, expected_count
                        ) VALUES (
                            CAST(:analysis_run_id AS UUID),
                            CAST(:screener_run_id AS UUID),
                            :started_at, NULL, 'running', :source_file,
                            :requested_tickers, :min_score, :top_n, :start_date,
                            :end_date, :indicators, :rr_ratio, :price_decimals, 0,
                            :expected_count
                        )
                        """
                    ),
                    {
                        **run_metadata,
                        "screener_run_id": run_metadata.get("screener_run_id"),
                        "expected_count": run_metadata["expected_count"],
                    },
                )

    def save_analysis_result(self, analysis_run_id, result):
        """Insert one ticker and increment run progress in a single transaction."""
        json_columns = ("indicators", "signals", "plan", "screener_snapshot")
        parameters = {
            key: value if key == "captured_at" else _json_safe(value)
            for key, value in result.items()
            if key not in json_columns
        }
        parameters["analysis_run_id"] = str(analysis_run_id)
        for column in json_columns:
            parameters[column] = json.dumps(
                _json_safe(result[column]), allow_nan=False, separators=(",", ":")
            )
        with self.connect() as connection:
            with connection.begin():
                updated = connection.execute(
                    text(
                        """
                        WITH inserted AS (
                            INSERT INTO public.analysis_results (
                                analysis_run_id, screener_run_id, ticker, as_of,
                                captured_at, open, high, low, close, volume, ema50,
                                ema100, ema200, rsi_14, atr_14, entry, entry_support,
                                stop, target, risk_per_share, actionable, indicators,
                                signals, plan, screener_snapshot
                            ) VALUES (
                                CAST(:analysis_run_id AS UUID),
                                CAST(:screener_run_id AS UUID),
                                :ticker, CAST(:as_of AS DATE), :captured_at,
                                :open, :high, :low, :close, :volume, :ema50,
                                :ema100, :ema200, :rsi_14, :atr_14, :entry,
                                :entry_support, :stop, :target, :risk_per_share,
                                :actionable, CAST(:indicators AS JSONB),
                                CAST(:signals AS JSONB), CAST(:plan AS JSONB),
                                CAST(:screener_snapshot AS JSONB)
                            )
                            RETURNING analysis_run_id
                        )
                        UPDATE public.analysis_runs AS run
                        SET result_count = run.result_count + 1
                        FROM inserted
                        WHERE run.analysis_run_id = inserted.analysis_run_id
                          AND run.status = 'running'
                        """
                    ),
                    parameters,
                )
                if updated.rowcount != 1:
                    raise ValueError(
                        f"Analysis run {analysis_run_id} was not found or is not running"
                    )

    def finish_analysis_run(self, analysis_run_id, finished_at, status="completed"):
        """Mark an analysis run completed or failed."""
        if status not in {"completed", "failed"}:
            raise ValueError("Analysis run status must be completed or failed")
        with self.connect() as connection:
            with connection.begin():
                updated = connection.execute(
                    text(
                        "UPDATE public.analysis_runs "
                        "SET finished_at = :finished_at, status = :status "
                        "WHERE analysis_run_id = CAST(:analysis_run_id AS UUID) "
                        "AND status = 'running'"
                    ),
                    {
                        "analysis_run_id": str(analysis_run_id),
                        "finished_at": finished_at,
                        "status": status,
                    },
                )
                if updated.rowcount != 1:
                    raise ValueError(
                        f"Analysis run {analysis_run_id} was not found or is not running"
                    )

    def save_analysis_run(self, run_metadata, results):
        """Append an analysis run and its ticker snapshots atomically."""
        results_to_save = results.copy()
        analysis_run_id = str(run_metadata["analysis_run_id"])
        results_to_save.insert(0, "analysis_run_id", analysis_run_id)
        json_columns = ("indicators", "signals", "plan", "screener_snapshot")
        for column in json_columns:
            if column in results_to_save:
                results_to_save[column] = results_to_save[column].map(_json_safe)

        run_data = pd.DataFrame([run_metadata])
        uuid_type = UUID(as_uuid=False)
        with self.connect() as connection:
            with connection.begin():
                run_data.to_sql(
                    "analysis_runs",
                    connection,
                    schema="public",
                    if_exists="append",
                    index=False,
                    dtype={
                        "analysis_run_id": uuid_type,
                        "screener_run_id": uuid_type,
                    },
                )
                if not results_to_save.empty:
                    results_to_save.to_sql(
                        "analysis_results",
                        connection,
                        schema="public",
                        if_exists="append",
                        index=False,
                        dtype={
                            "analysis_run_id": uuid_type,
                            "screener_run_id": uuid_type,
                            "indicators": JSONB,
                            "signals": JSONB,
                            "plan": JSONB,
                            "screener_snapshot": JSONB,
                        },
                    )
    
    def close(self):
        """Dispose the shared PostgreSQL connection pool."""
        log.info("Closing all database connections")
        postgresConnectionFactory = PostgresConnectionFactory(**self.db_config)
        postgresConnectionFactory.close_all()
