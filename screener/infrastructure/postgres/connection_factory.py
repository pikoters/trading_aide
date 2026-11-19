
"""SQLAlchemy engine and PostgreSQL connection lifecycle."""

import logging as log
import threading
import psycopg2
from psycopg2 import pool

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
log.basicConfig(level=log.INFO)

class PostgresConnectionFactory:
    """Lazily shared SQLAlchemy engine configured for PostgreSQL access.

    The first construction initializes the process-wide engine; subsequent
    instances reuse it. ``maxconn`` controls the base pool size, while the
    engine allows up to ten overflow connections.
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self, maxconn=5, **db_params):
        """Create the shared engine from PostgreSQL connection parameters."""
        # Initialize only once
        log.info("Initializing PostgresConnectionFactory")
        if not hasattr(self, "_initialized"):
            try:
                # self._pool = pool.SimpleConnectionPool(
                #     minconn,
                #     maxconn,
                #     **db_params
                # )
                log.info(f"Database connection parameters: {db_params['user']}")
                database_url = URL.create(
                    "postgresql+psycopg2",
                    username=db_params["user"],
                    password=db_params["password"],
                    host=db_params["host"],
                    port=db_params["port"],
                    database=db_params["database"],
                )
                self._engine = create_engine(
                    database_url,
                    pool_size=maxconn,            # Number of persistent connections
                    max_overflow=10,        # Extra connections beyond pool_size
                    pool_timeout=30,        # Seconds to wait before giving up
                    pool_recycle=1800,      # Recycle connections after 30 min
                    echo=False,             # Set True for SQL debug logging
                    future=True
                )
                if not self._engine:
                    log.error("Failed to create connection pool")
                    raise Exception("Failed to create connection pool")
                self._initialized = True
            except Exception as e:
                log.error(f"Error creating PostgreSQL connection pool: {e}")
                raise RuntimeError(f"Error creating PostgreSQL connection pool: {e}")

    def __new__(cls, *args, **kwargs):
        """Return the process-wide factory instance under a creation lock."""
        log.info("Creating instance of PostgresConnectionFactory")
        # Double-checked locking to ensure thread safety
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PostgresConnectionFactory, cls).__new__(cls)
        return cls._instance

    def get_connection(self):
        """Acquire a SQLAlchemy connection; caller must close the returned handle.

        Raises:
            RuntimeError: If SQLAlchemy cannot acquire a connection.
        """
        try:
            log.info("Getting connection from pool")
            # return self.
            return self._engine.connect()
        except Exception as e:
            log.error(f"Error getting connection from pool: {e}")
            raise RuntimeError(f"Error getting connection from pool: {e}")
    def release_connection(self, connection):
        """Dispose the engine when given a truthy connection handle.

        This legacy method disposes the pool rather than closing only the
        supplied handle; callers should normally close their SQLAlchemy
        connection directly.
        """
        try:
            if connection:
                # self._pool.putconn(connection)
                self._engine.dispose()  # Dispose the connection to return it to the pool
                log.info("Connection released back to pool")
        except Exception as e:
            log.error(f"Error releasing connection: {e}")
            raise RuntimeError(f"Error releasing connection: {e}")
    
    def close_all(self):
        """Dispose the shared engine and close all pooled connections."""
        try:
            log.info("Closing all connections in the pool")
            # self._pool.closeall()
            self._engine.dispose()  # Dispose the engine to close all connections
            log.info("All connections closed successfully")
        except Exception as e:
            log.error(f"Error closing all connections: {e}")
            raise RuntimeError(f"Error closing all connections: {e}")
            