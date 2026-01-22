"""
Database backend abstraction for multi-database support.

Supports:
- SQLite (default, local file-based)
- MySQL/MariaDB (remote database server)
- PostgreSQL (remote database server)
- Microsoft SQL Server (remote database server)


"""

import logging
import sqlite3
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass

from dtPyAppFramework.paths import ApplicationPaths

@dataclass
class DatabaseCredentials:
    """Database connection credentials."""
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ssl: bool = False
    driver: Optional[str] = None  # For MSSQL
    path: Optional[str] = None  # For SQLite


class DatabaseBackend(ABC):
    """Abstract base class for database backends."""

    def __init__(self, credentials: DatabaseCredentials):
        """
        Initialise database backend.

        Args:
            credentials: Database connection credentials
        """
        self.credentials = credentials
        self.connection = None

    @abstractmethod
    def connect(self):
        """
        Establish database connection.

        Returns:
            Database connection object
        """
        pass

    @abstractmethod
    def get_placeholder(self) -> str:
        """
        Get SQL parameter placeholder for this database.

        Returns:
            Placeholder string (?, %s, etc.)
        """
        pass

    @abstractmethod
    def get_autoincrement_syntax(self) -> str:
        """
        Get auto-increment syntax for this database.

        Returns:
            Auto-increment SQL syntax
        """
        pass

    @abstractmethod
    def supports_returning(self) -> bool:
        """
        Check if database supports RETURNING clause.

        Returns:
            True if RETURNING is supported
        """
        pass

    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def test_connection(self) -> bool:
        """
        Test database connection.

        Returns:
            True if connection successful
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Database connection test failed: {e}")
            return False


class SQLiteBackend(DatabaseBackend):
    """SQLite database backend (local file-based)."""

    def connect(self):
        """Establish SQLite connection."""
        if self.connection is None:
            self.connection = sqlite3.connect(
                os.path.join(ApplicationPaths().usr_data_root_path, "conversations.db"),
                check_same_thread=False
            )
            self.connection.row_factory = sqlite3.Row
        return self.connection

    def get_placeholder(self) -> str:
        return "?"

    def get_autoincrement_syntax(self) -> str:
        return "AUTOINCREMENT"

    def supports_returning(self) -> bool:
        return False  # SQLite < 3.35 doesn't support RETURNING


class MySQLBackend(DatabaseBackend):
    """MySQL/MariaDB database backend."""

    def connect(self):
        """Establish MySQL connection."""
        try:
            import mysql.connector
        except ImportError:
            raise ImportError(
                "mysql-connector-python is required for MySQL support. "
                "Install it with: pip install mysql-connector-python"
            )

        if self.connection is None:
            connection_params = {
                'host': self.credentials.host,
                'port': self.credentials.port or 3306,
                'database': self.credentials.database,
                'user': self.credentials.username,
                'password': self.credentials.password,
                'autocommit': False
            }

            if self.credentials.ssl:
                connection_params['ssl_disabled'] = False

            self.connection = mysql.connector.connect(**connection_params)

        return self.connection

    def get_placeholder(self) -> str:
        return "%s"

    def get_autoincrement_syntax(self) -> str:
        return "AUTO_INCREMENT"

    def supports_returning(self) -> bool:
        return False  # MySQL doesn't support RETURNING


class PostgreSQLBackend(DatabaseBackend):
    """PostgreSQL database backend."""

    def connect(self):
        """Establish PostgreSQL connection."""
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL support. "
                "Install it with: pip install psycopg2-binary"
            )

        if self.connection is None:
            connection_params = {
                'host': self.credentials.host,
                'port': self.credentials.port or 5432,
                'database': self.credentials.database,
                'user': self.credentials.username,
                'password': self.credentials.password
            }

            if self.credentials.ssl:
                connection_params['sslmode'] = 'require'

            self.connection = psycopg2.connect(**connection_params)
            self.connection.autocommit = False

        return self.connection

    def get_placeholder(self) -> str:
        return "%s"

    def get_autoincrement_syntax(self) -> str:
        return "SERIAL"

    def supports_returning(self) -> bool:
        return True


class MSSQLBackend(DatabaseBackend):
    """Microsoft SQL Server database backend."""

    def connect(self):
        """Establish MSSQL connection."""
        try:
            import pyodbc
        except ImportError:
            raise ImportError(
                "pyodbc is required for Microsoft SQL Server support. "
                "Install it with: pip install pyodbc"
            )

        if self.connection is None:
            driver = self.credentials.driver or "ODBC Driver 17 for SQL Server"

            connection_string = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self.credentials.host};"
                f"DATABASE={self.credentials.database};"
                f"UID={self.credentials.username};"
                f"PWD={self.credentials.password};"
            )

            if self.credentials.port:
                connection_string = connection_string.replace(
                    f"SERVER={self.credentials.host};",
                    f"SERVER={self.credentials.host},{self.credentials.port};"
                )

            if self.credentials.ssl:
                connection_string += "Encrypt=yes;TrustServerCertificate=no;"

            self.connection = pyodbc.connect(connection_string)
            self.connection.autocommit = False

        return self.connection

    def get_placeholder(self) -> str:
        return "?"

    def get_autoincrement_syntax(self) -> str:
        return "IDENTITY"

    def supports_returning(self) -> bool:
        return False  # MSSQL uses OUTPUT clause instead


def create_backend(db_type: str, credentials: DatabaseCredentials) -> DatabaseBackend:
    """
    Factory function to create appropriate database backend.

    Args:
        db_type: Database type (sqlite, mysql, mariadb, postgresql, mssql)
        credentials: Database connection credentials

    Returns:
        Appropriate DatabaseBackend instance

    Raises:
        ValueError: If database type is not supported
    """
    db_type_lower = db_type.lower()

    if db_type_lower == 'sqlite':
        return SQLiteBackend(credentials)
    elif db_type_lower in ('mysql', 'mariadb'):
        return MySQLBackend(credentials)
    elif db_type_lower == 'postgresql':
        return PostgreSQLBackend(credentials)
    elif db_type_lower in ('mssql', 'sqlserver', 'mssqlserver'):
        return MSSQLBackend(credentials)
    else:
        raise ValueError(
            f"Unsupported database type: {db_type}. "
            f"Supported types: sqlite, mysql, mariadb, postgresql, mssql"
        )


def validate_credentials(db_type: str, credentials: DatabaseCredentials) -> tuple[bool, Optional[str]]:
    """
    Validate database credentials for given database type.

    Args:
        db_type: Database type
        credentials: Database credentials

    Returns:
        Tuple of (is_valid, error_message)
    """
    db_type_lower = db_type.lower()

    if db_type_lower == 'sqlite':
        if not credentials.path:
            return False, "SQLite database path is required"
        return True, None

    # Remote databases require connection details
    required_fields = ['host', 'database', 'username', 'password']

    missing = []
    if not credentials.host:
        missing.append('host')
    if not credentials.database:
        missing.append('database')
    if not credentials.username:
        missing.append('username')
    if not credentials.password:
        missing.append('password')

    if missing:
        return False, f"Missing required credentials: {', '.join(missing)}"

    return True, None
