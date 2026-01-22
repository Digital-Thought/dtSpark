"""
Database connection management module.

This module handles:
- Multi-database backend support (SQLite, MySQL, PostgreSQL, MSSQL)
- Database connection setup
- Connection lifecycle management
- Directory management for database files


"""

import sqlite3
import logging
import threading
from pathlib import Path
from typing import Optional, Any

from .backends import (
    DatabaseBackend,
    DatabaseCredentials,
    create_backend,
    validate_credentials
)


class DatabaseConnection:
    """Manages database connection lifecycle with multi-backend support."""

    def __init__(self, db_type: str = 'sqlite', credentials: Optional[DatabaseCredentials] = None,
                 db_path: Optional[str] = None):
        """
        Initialise the database connection.

        Args:
            db_type: Database type (sqlite, mysql, mariadb, postgresql, mssql)
            credentials: Database connection credentials
            db_path: Path to SQLite database file (for backward compatibility)
        """
        self.db_type = db_type.lower()
        self._lock = threading.RLock()  # Reentrant lock for thread-safe operations

        # Handle backward compatibility with old SQLite-only constructor
        if credentials is None and db_path:
            credentials = DatabaseCredentials(path=db_path)
            self.db_type = 'sqlite'

        if credentials is None:
            raise ValueError("Database credentials are required")

        # Validate credentials
        is_valid, error_msg = validate_credentials(self.db_type, credentials)
        if not is_valid:
            raise ValueError(f"Invalid database credentials: {error_msg}")

        # Create appropriate backend
        self.backend = create_backend(self.db_type, credentials)

        # For SQLite, ensure directory exists
        if self.db_type == 'sqlite':
            self._ensure_database_directory(credentials.path)

        # Establish connection
        self.conn = self.backend.connect()

        # Configure connection based on backend
        self._configure_connection()

        logging.info(f"Database connection established: type={self.db_type}")

    def _ensure_database_directory(self, db_path: str):
        """
        Ensure the directory for the database file exists (SQLite only).

        Args:
            db_path: Path to database file
        """
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _configure_connection(self):
        """Configure connection based on database backend."""
        if self.db_type == 'sqlite':
            # Enable WAL (Write-Ahead Logging) mode for better concurrency
            cursor = self.conn.execute("PRAGMA journal_mode=WAL")
            journal_mode = cursor.fetchone()[0]
            cursor.close()
            logging.info(f"SQLite journal mode: {journal_mode}")

    def get_connection(self) -> Any:
        """
        Get the database connection.

        Returns:
            Database connection object
        """
        return self.conn

    def get_backend(self) -> DatabaseBackend:
        """
        Get the database backend.

        Returns:
            DatabaseBackend instance
        """
        return self.backend

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.backend.close()
            self.conn = None
            logging.info(f"Database connection closed: type={self.db_type}")

    def test_connection(self) -> bool:
        """
        Test database connection.

        Returns:
            True if connection is working
        """
        return self.backend.test_connection()
