"""
Database schema management for conversation storage.

This module handles:
- Table creation
- Schema migrations
- Index management

Note: Current schema is optimized for SQLite. Support for other databases
(MySQL, PostgreSQL, MSSQL) requires schema adaptations for proper data types
and auto-increment syntax.


"""

import sqlite3
import logging


def initialise_schema(conn, backend=None):
    """
    Create database tables and indices if they don't exist.

    Args:
        conn: Database connection (SQLite or other backend)
        backend: DatabaseBackend instance for SQL dialect-specific operations

    Note: Schema is currently SQLite-optimized. Future versions will use
    backend parameter to generate database-specific SQL.
    """
    cursor = conn.cursor()

    # TODO: Use backend.get_autoincrement_syntax() for cross-database support
    # For now, schema works with SQLite and databases that support similar DDL

    # Conversations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            model_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            total_tokens INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            instructions TEXT,
            tokens_sent INTEGER DEFAULT 0,
            tokens_received INTEGER DEFAULT 0
        )
    ''')

    # Migration: Add instructions column if it doesn't exist
    try:
        cursor.execute("SELECT instructions FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cursor.execute("ALTER TABLE conversations ADD COLUMN instructions TEXT")
        conn.commit()
        logging.info("Added instructions column to conversations table")

    # Migration: Add token tracking columns if they don't exist
    try:
        cursor.execute("SELECT tokens_sent, tokens_received FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Columns don't exist, add them
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN tokens_sent INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN tokens_received INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()
        logging.info("Added token tracking columns to conversations table")

    # Migration: Add max_tokens column if it doesn't exist
    try:
        cursor.execute("SELECT max_tokens FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it (NULL means use global default)
        cursor.execute("ALTER TABLE conversations ADD COLUMN max_tokens INTEGER DEFAULT NULL")
        conn.commit()
        logging.info("Added max_tokens column to conversations table")

    # Migration: Add is_predefined column if it doesn't exist
    try:
        cursor.execute("SELECT is_predefined FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cursor.execute("ALTER TABLE conversations ADD COLUMN is_predefined INTEGER DEFAULT 0")
        conn.commit()
        logging.info("Added is_predefined column to conversations table")

    # Migration: Add config_hash column if it doesn't exist
    try:
        cursor.execute("SELECT config_hash FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it (stores hash of config to detect changes)
        cursor.execute("ALTER TABLE conversations ADD COLUMN config_hash TEXT DEFAULT NULL")
        conn.commit()
        logging.info("Added config_hash column to conversations table")

    # Migration: Add compaction_threshold column if it doesn't exist
    try:
        cursor.execute("SELECT compaction_threshold FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it (NULL means use global default from config)
        cursor.execute("ALTER TABLE conversations ADD COLUMN compaction_threshold REAL DEFAULT NULL")
        conn.commit()
        logging.info("Added compaction_threshold column to conversations table")

    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            is_rolled_up INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    # Rollup history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rollup_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            original_message_count INTEGER NOT NULL,
            summarised_content TEXT NOT NULL,
            original_token_count INTEGER NOT NULL,
            summarised_token_count INTEGER NOT NULL,
            rollup_timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    # Conversation files table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER,
            content_text TEXT,
            content_base64 TEXT,
            mime_type TEXT,
            token_count INTEGER DEFAULT 0,
            added_at TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    # Migration: Add tags column to conversation_files if it doesn't exist
    try:
        cursor.execute("SELECT tags FROM conversation_files LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cursor.execute("ALTER TABLE conversation_files ADD COLUMN tags TEXT DEFAULT NULL")
        conn.commit()
        logging.info("Added tags column to conversation_files table")

    # MCP transactions table - for Cyber Security monitoring and audit trails
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mcp_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            message_id INTEGER,
            user_prompt TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_server TEXT NOT NULL,
            tool_input TEXT NOT NULL,
            tool_response TEXT NOT NULL,
            is_error INTEGER DEFAULT 0,
            execution_time_ms INTEGER,
            transaction_timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
    ''')

    # Conversation model usage table - tracks token usage per model
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            first_used TIMESTAMP NOT NULL,
            last_used TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            UNIQUE(conversation_id, model_id)
        )
    ''')

    # Conversation MCP servers table - tracks which MCP servers are enabled per conversation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_mcp_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            server_name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            UNIQUE(conversation_id, server_name)
        )
    ''')

    # Usage tracking table - for token management and billing
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            region TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost REAL NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    # Prompt inspection violations table - for Cyber Security audit trail
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_inspection_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_guid TEXT NOT NULL,
            conversation_id INTEGER,
            violation_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            prompt_snippet TEXT NOT NULL,
            detection_method TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            confidence_score REAL,
            timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    # Tool permissions table - tracks user permissions for tool usage per conversation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_tool_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            permission_state TEXT NOT NULL,
            granted_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            UNIQUE(conversation_id, tool_name)
        )
    ''')

    # Autonomous actions table - stores scheduled action definitions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS autonomous_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            action_prompt TEXT NOT NULL,
            model_id TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_config TEXT NOT NULL,
            context_mode TEXT NOT NULL DEFAULT 'fresh',
            max_failures INTEGER NOT NULL DEFAULT 3,
            failure_count INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            max_tokens INTEGER NOT NULL DEFAULT 8192,
            created_at TIMESTAMP NOT NULL,
            last_run_at TIMESTAMP,
            next_run_at TIMESTAMP,
            user_guid TEXT
        )
    ''')

    # Action runs table - stores execution history for autonomous actions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS action_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER NOT NULL,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP,
            status TEXT NOT NULL,
            result_text TEXT,
            result_html TEXT,
            error_message TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            context_snapshot TEXT,
            user_guid TEXT,
            FOREIGN KEY (action_id) REFERENCES autonomous_actions(id)
        )
    ''')

    # Action tool permissions table - snapshotted tool permissions for actions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS action_tool_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            server_name TEXT,
            permission_state TEXT NOT NULL,
            granted_at TIMESTAMP NOT NULL,
            user_guid TEXT,
            FOREIGN KEY (action_id) REFERENCES autonomous_actions(id),
            UNIQUE(action_id, tool_name)
        )
    ''')

    # Create indices for better query performance
    _create_indices(conn)

    # Migration: Add user_guid columns to all tables for multi-user support
    _add_user_guid_columns(conn)

    # Migration: Add max_tokens column to autonomous_actions table
    _add_max_tokens_column(conn)

    # Migration: Add daemon support columns and tables
    _add_daemon_support(conn)

    conn.commit()
    logging.info("Database schema initialised")


def _create_indices(conn: sqlite3.Connection):
    """
    Create database indices for improved query performance.

    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()

    # Messages indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp
        ON messages(timestamp)
    ''')

    # Conversations indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conversations_active
        ON conversations(is_active)
    ''')

    # Files indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_files_conversation
        ON conversation_files(conversation_id)
    ''')

    # MCP transactions indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_mcp_transactions_conversation
        ON mcp_transactions(conversation_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_mcp_transactions_timestamp
        ON mcp_transactions(transaction_timestamp)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_mcp_transactions_tool
        ON mcp_transactions(tool_name)
    ''')

    # Model usage indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_model_usage_conversation
        ON conversation_model_usage(conversation_id)
    ''')

    # MCP servers indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conversation_mcp_servers
        ON conversation_mcp_servers(conversation_id)
    ''')

    # Usage tracking indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_usage_tracking_timestamp
        ON usage_tracking(timestamp)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_usage_tracking_conversation
        ON usage_tracking(conversation_id)
    ''')

    # Prompt inspection violations indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_violations_user_guid
        ON prompt_inspection_violations(user_guid)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_violations_timestamp
        ON prompt_inspection_violations(timestamp)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_violations_conversation
        ON prompt_inspection_violations(conversation_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_violations_severity
        ON prompt_inspection_violations(severity)
    ''')

    # Tool permissions indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_tool_permissions_conversation
        ON conversation_tool_permissions(conversation_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_tool_permissions_tool_name
        ON conversation_tool_permissions(tool_name)
    ''')

    # Autonomous actions indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_autonomous_actions_enabled
        ON autonomous_actions(is_enabled)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_autonomous_actions_schedule_type
        ON autonomous_actions(schedule_type)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_autonomous_actions_next_run
        ON autonomous_actions(next_run_at)
    ''')

    # Action runs indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_action_runs_action_id
        ON action_runs(action_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_action_runs_status
        ON action_runs(status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_action_runs_started_at
        ON action_runs(started_at)
    ''')

    # Action tool permissions indices
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_action_tool_permissions_action_id
        ON action_tool_permissions(action_id)
    ''')


def _add_user_guid_columns(conn: sqlite3.Connection):
    """
    Add user_guid columns to all tables for multi-user database support.

    This migration prepares the database for future MySQL/MariaDB/PostgreSQL support
    where multiple users may share the same database instance.

    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()
    tables_to_migrate = [
        'conversations',
        'messages',
        'rollup_history',
        'conversation_files',
        'mcp_transactions',
        'conversation_model_usage',
        'conversation_mcp_servers',
        'usage_tracking',
        'conversation_tool_permissions',
        'autonomous_actions',
        'action_runs',
        'action_tool_permissions'
    ]

    for table in tables_to_migrate:
        try:
            # Check if user_guid column exists
            cursor.execute(f"SELECT user_guid FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN user_guid TEXT")
            conn.commit()
            logging.info(f"Added user_guid column to {table} table")

    # Create indices for user_guid columns for better query performance
    for table in tables_to_migrate:
        try:
            cursor.execute(f'''
                CREATE INDEX IF NOT EXISTS idx_{table}_user_guid
                ON {table}(user_guid)
            ''')
        except sqlite3.OperationalError as e:
            logging.warning(f"Could not create index on {table}.user_guid: {e}")

    conn.commit()


def _add_max_tokens_column(conn: sqlite3.Connection):
    """
    Add max_tokens column to autonomous_actions table for existing databases.

    This migration adds support for configurable max_tokens per action,
    allowing different actions to have different token limits based on their needs.

    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()

    try:
        # Check if max_tokens column exists
        cursor.execute("SELECT max_tokens FROM autonomous_actions LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it with default value
        cursor.execute(
            "ALTER TABLE autonomous_actions ADD COLUMN max_tokens INTEGER NOT NULL DEFAULT 8192"
        )
        conn.commit()
        logging.info("Added max_tokens column to autonomous_actions table")


def _add_daemon_support(conn: sqlite3.Connection):
    """
    Add daemon support columns and tables for autonomous action execution.

    This migration adds:
    - version column to autonomous_actions for change detection
    - locked_by/locked_at columns for execution coordination
    - daemon_registry table for daemon process tracking

    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()

    # Add version column for change detection
    try:
        cursor.execute("SELECT version FROM autonomous_actions LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(
            "ALTER TABLE autonomous_actions ADD COLUMN version INTEGER DEFAULT 1"
        )
        conn.commit()
        logging.info("Added version column to autonomous_actions table")

    # Add locked_by column for execution coordination
    try:
        cursor.execute("SELECT locked_by FROM autonomous_actions LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(
            "ALTER TABLE autonomous_actions ADD COLUMN locked_by TEXT DEFAULT NULL"
        )
        conn.commit()
        logging.info("Added locked_by column to autonomous_actions table")

    # Add locked_at column for execution coordination
    try:
        cursor.execute("SELECT locked_at FROM autonomous_actions LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(
            "ALTER TABLE autonomous_actions ADD COLUMN locked_at TIMESTAMP DEFAULT NULL"
        )
        conn.commit()
        logging.info("Added locked_at column to autonomous_actions table")

    # Add updated_at column for tracking modifications
    try:
        cursor.execute("SELECT updated_at FROM autonomous_actions LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(
            "ALTER TABLE autonomous_actions ADD COLUMN updated_at TIMESTAMP DEFAULT NULL"
        )
        conn.commit()
        logging.info("Added updated_at column to autonomous_actions table")

    # Create daemon_registry table for tracking daemon processes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daemon_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            daemon_id TEXT NOT NULL UNIQUE,
            hostname TEXT NOT NULL,
            pid INTEGER NOT NULL,
            started_at TIMESTAMP NOT NULL,
            last_heartbeat TIMESTAMP NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            user_guid TEXT
        )
    ''')

    # Create index for daemon_registry
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_daemon_registry_status
        ON daemon_registry(status)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_daemon_registry_user_guid
        ON daemon_registry(user_guid)
    ''')

    conn.commit()
    logging.info("Daemon support schema migration complete")


def migrate_user_guid(conn: sqlite3.Connection, user_guid: str):
    """
    Migrate existing records to assign current user's GUID.

    This function assigns the current user's GUID to all records that don't have one,
    ensuring backward compatibility with existing databases.

    Args:
        conn: SQLite database connection
        user_guid: The current user's GUID
    """
    cursor = conn.cursor()
    tables_to_migrate = [
        'conversations',
        'messages',
        'rollup_history',
        'conversation_files',
        'mcp_transactions',
        'conversation_model_usage',
        'conversation_mcp_servers',
        'usage_tracking',
        'conversation_tool_permissions',
        'autonomous_actions',
        'action_runs',
        'action_tool_permissions'
    ]

    for table in tables_to_migrate:
        try:
            # Update records with NULL or empty user_guid
            cursor.execute(f'''
                UPDATE {table}
                SET user_guid = ?
                WHERE user_guid IS NULL OR user_guid = ''
            ''', (user_guid,))

            rows_updated = cursor.rowcount
            if rows_updated > 0:
                logging.info(f"Migrated {rows_updated} records in {table} table to user GUID: {user_guid}")
        except sqlite3.OperationalError as e:
            # Table might not have user_guid column yet, or doesn't exist
            logging.debug(f"Could not migrate {table}: {e}")

    conn.commit()
