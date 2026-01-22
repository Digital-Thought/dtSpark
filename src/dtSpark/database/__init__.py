"""
Database module for managing conversation storage.

Supports multiple database backends:
- SQLite (default, local file-based)
- MySQL/MariaDB (remote database server)
- PostgreSQL (remote database server)
- Microsoft SQL Server (remote database server)

This module provides functionality for:
- Creating and managing conversation records
- Storing and retrieving messages
- Managing conversation rollup history
- File attachments
- MCP transaction tracking
- Usage tracking for token management


"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Import sub-modules
from . import schema
from . import connection as conn_module
from . import conversations as conv_module
from . import messages as msg_module
from . import files as files_module
from . import mcp_ops
from . import usage as usage_module
from . import backends
from . import credential_prompt
from . import tool_permissions
from . import autonomous_actions as actions_module


class ConversationDatabase:
    """
    Manages SQLite database operations for conversation storage.

    This class provides a unified interface to all database operations,
    delegating to specialised modules for different concerns.
    """

    def __init__(self, user_guid: str, db_type: str = 'sqlite',
                 credentials=None, db_path: str = None):
        """
        Initialise the database connection with multi-database support.

        Args:
            user_guid: Unique identifier for the current user
            db_type: Database type (sqlite, mysql, mariadb, postgresql, mssql)
            credentials: DatabaseCredentials object for connection
            db_path: Path to SQLite database file (deprecated, for backward compatibility)
        """
        from .backends import DatabaseCredentials

        self.user_guid = user_guid
        self.db_type = db_type

        # Backward compatibility: if db_path provided, use SQLite
        if db_path and credentials is None:
            credentials = DatabaseCredentials(path=db_path)
            db_type = 'sqlite'
            self.db_type = 'sqlite'

        # Create database connection with appropriate backend
        self._conn_manager = conn_module.DatabaseConnection(
            db_type=db_type,
            credentials=credentials
        )
        self.conn = self._conn_manager.get_connection()
        self.db_path = credentials.path if db_type == 'sqlite' else None

        # Get backend for SQL dialect-specific operations
        self.backend = self._conn_manager.get_backend()

        # Initialise schema (handles different SQL dialects)
        schema.initialise_schema(self.conn, self.backend)

        # Migrate existing records to current user if needed
        schema.migrate_user_guid(self.conn, self.user_guid)

    # Conversation operations
    def create_conversation(self, name: str, model_id: str,
                           instructions: Optional[str] = None,
                           compaction_threshold: Optional[float] = None) -> int:
        """Create a new conversation."""
        return conv_module.create_conversation(self.conn, name, model_id, instructions,
                                              user_guid=self.user_guid,
                                              compaction_threshold=compaction_threshold)

    def get_active_conversations(self) -> List[Dict]:
        """Retrieve all active conversations."""
        return conv_module.get_active_conversations(self.conn, user_guid=self.user_guid)

    def get_conversation(self, conversation_id: int) -> Optional[Dict]:
        """Retrieve a specific conversation."""
        with self._conn_manager._lock:
            return conv_module.get_conversation(self.conn, conversation_id, user_guid=self.user_guid)

    def get_conversation_token_count(self, conversation_id: int) -> int:
        """Get the total token count for a conversation."""
        return conv_module.get_conversation_token_count(self.conn, conversation_id,
                                                        user_guid=self.user_guid)

    def recalculate_total_tokens(self, conversation_id: int) -> int:
        """
        Recalculate and update total_tokens from active (non-rolled-up) messages.

        This ensures accuracy after compaction operations by summing only
        the tokens from messages that haven't been rolled up.

        Returns:
            The new total token count
        """
        with self._conn_manager._lock:
            return conv_module.recalculate_total_tokens(self.conn, conversation_id,
                                                        user_guid=self.user_guid)

    def delete_conversation(self, conversation_id: int) -> bool:
        """Delete a conversation and all its messages."""
        return conv_module.delete_conversation(self.conn, conversation_id, user_guid=self.user_guid)

    def update_conversation_max_tokens(self, conversation_id: int, max_tokens: int):
        """Update the max_tokens setting for a specific conversation."""
        conv_module.update_conversation_max_tokens(self.conn, conversation_id, max_tokens,
                                                   user_guid=self.user_guid)

    def update_conversation_compaction_threshold(self, conversation_id: int,
                                                  compaction_threshold: float):
        """Update the compaction_threshold setting for a specific conversation."""
        conv_module.update_conversation_compaction_threshold(self.conn, conversation_id,
                                                              compaction_threshold,
                                                              user_guid=self.user_guid)

    def update_conversation_instructions(self, conversation_id: int,
                                        instructions: Optional[str]):
        """Update the instructions for a specific conversation."""
        conv_module.update_conversation_instructions(self.conn, conversation_id, instructions,
                                                     user_guid=self.user_guid)

    def update_token_usage(self, conversation_id: int, tokens_sent: int,
                          tokens_received: int, model_id: str = None):
        """Update the API token usage for a conversation and track per-model usage."""
        with self._conn_manager._lock:
            conv_module.update_token_usage(self.conn, conversation_id, tokens_sent,
                                          tokens_received, model_id, user_guid=self.user_guid)

    def get_model_usage_breakdown(self, conversation_id: int) -> List[Dict]:
        """Get per-model token usage breakdown for a conversation."""
        return conv_module.get_model_usage_breakdown(self.conn, conversation_id,
                                                      user_guid=self.user_guid)

    def get_predefined_conversation_by_name(self, name: str) -> Optional[Dict]:
        """Retrieve a predefined conversation by name."""
        return conv_module.get_predefined_conversation_by_name(self.conn, name,
                                                                user_guid=self.user_guid)

    def create_predefined_conversation(self, name: str, model_id: str,
                                      instructions: Optional[str], config_hash: str) -> int:
        """Create a new predefined conversation."""
        return conv_module.create_predefined_conversation(self.conn, name, model_id,
                                                         instructions, config_hash,
                                                         user_guid=self.user_guid)

    def update_predefined_conversation(self, conversation_id: int, model_id: str,
                                      instructions: Optional[str], config_hash: str):
        """Update a predefined conversation's settings."""
        conv_module.update_predefined_conversation(self.conn, conversation_id, model_id,
                                                   instructions, config_hash,
                                                   user_guid=self.user_guid)

    def is_conversation_predefined(self, conversation_id: int) -> bool:
        """Check if a conversation is predefined."""
        return conv_module.is_conversation_predefined(self.conn, conversation_id,
                                                       user_guid=self.user_guid)

    # Message operations
    def add_message(self, conversation_id: int, role: str, content: str,
                   token_count: int) -> int:
        """Add a message to a conversation."""
        with self._conn_manager._lock:
            return msg_module.add_message(self.conn, conversation_id, role, content, token_count,
                                         user_guid=self.user_guid)

    def get_conversation_messages(self, conversation_id: int,
                                 include_rolled_up: bool = False) -> List[Dict]:
        """Retrieve messages for a conversation."""
        with self._conn_manager._lock:
            return msg_module.get_conversation_messages(self.conn, conversation_id, include_rolled_up,
                                                        user_guid=self.user_guid)

    def mark_messages_as_rolled_up(self, message_ids: List[int]):
        """Mark messages as rolled up."""
        with self._conn_manager._lock:
            msg_module.mark_messages_as_rolled_up(self.conn, message_ids, user_guid=self.user_guid)

    def record_rollup(self, conversation_id: int, original_message_count: int,
                     summarised_content: str, original_token_count: int,
                     summarised_token_count: int):
        """Record a rollup operation in history."""
        with self._conn_manager._lock:
            msg_module.record_rollup(self.conn, conversation_id, original_message_count,
                                    summarised_content, original_token_count, summarised_token_count,
                                    user_guid=self.user_guid)

    # File operations
    def add_file(self, conversation_id: int, filename: str, file_type: str, file_size: int,
                content_text: Optional[str] = None, content_base64: Optional[str] = None,
                mime_type: Optional[str] = None, token_count: int = 0,
                tags: Optional[str] = None) -> int:
        """Add a file to a conversation."""
        return files_module.add_file(self.conn, conversation_id, filename, file_type,
                                    file_size, content_text, content_base64, mime_type,
                                    token_count, tags, user_guid=self.user_guid)

    def get_conversation_files(self, conversation_id: int) -> List[Dict]:
        """Retrieve all files for a conversation."""
        return files_module.get_conversation_files(self.conn, conversation_id,
                                                    user_guid=self.user_guid)

    def get_files_by_tag(self, conversation_id: int, tag: str) -> List[Dict]:
        """Retrieve files for a conversation filtered by tag."""
        return files_module.get_files_by_tag(self.conn, conversation_id, tag,
                                             user_guid=self.user_guid)

    def delete_conversation_files(self, conversation_id: int):
        """Delete all files for a conversation."""
        files_module.delete_conversation_files(self.conn, conversation_id, user_guid=self.user_guid)

    def delete_file(self, file_id: int) -> bool:
        """Delete a specific file by ID."""
        return files_module.delete_file(self.conn, file_id, user_guid=self.user_guid)

    # MCP operations
    def record_mcp_transaction(self, conversation_id: int, user_prompt: str, tool_name: str,
                              tool_server: str, tool_input: str, tool_response: str,
                              is_error: bool = False, execution_time_ms: Optional[int] = None,
                              message_id: Optional[int] = None) -> int:
        """Record an MCP tool transaction for Cyber Security monitoring and audit trails."""
        with self._conn_manager._lock:
            return mcp_ops.record_mcp_transaction(self.conn, conversation_id, user_prompt, tool_name,
                                                 tool_server, tool_input, tool_response, is_error,
                                                 execution_time_ms, message_id, user_guid=self.user_guid)

    def get_mcp_transactions(self, conversation_id: Optional[int] = None,
                            tool_name: Optional[str] = None,
                            tool_server: Optional[str] = None,
                            limit: Optional[int] = None) -> List[Dict]:
        """Retrieve MCP transactions with optional filtering."""
        return mcp_ops.get_mcp_transactions(self.conn, conversation_id, tool_name,
                                           tool_server, limit, user_guid=self.user_guid)

    def get_mcp_transaction_stats(self) -> Dict:
        """Get statistics about MCP transactions for Cyber Security monitoring."""
        return mcp_ops.get_mcp_transaction_stats(self.conn, user_guid=self.user_guid)

    def export_mcp_transactions_to_csv(self, file_path: str,
                                       conversation_id: Optional[int] = None) -> bool:
        """Export MCP transactions to CSV for Cyber Security audit."""
        return mcp_ops.export_mcp_transactions_to_csv(self.conn, file_path, conversation_id,
                                                       user_guid=self.user_guid)

    def get_enabled_mcp_servers(self, conversation_id: int) -> List[str]:
        """Get list of enabled MCP servers for a conversation."""
        return mcp_ops.get_enabled_mcp_servers(self.conn, conversation_id, user_guid=self.user_guid)

    def is_mcp_server_enabled(self, conversation_id: int, server_name: str) -> bool:
        """Check if an MCP server is enabled for a conversation."""
        return mcp_ops.is_mcp_server_enabled(self.conn, conversation_id, server_name,
                                             user_guid=self.user_guid)

    def set_mcp_server_enabled(self, conversation_id: int, server_name: str,
                              enabled: bool) -> bool:
        """Enable or disable an MCP server for a conversation."""
        return mcp_ops.set_mcp_server_enabled(self.conn, conversation_id, server_name, enabled,
                                              user_guid=self.user_guid)

    def get_all_mcp_server_states(self, conversation_id: int,
                                  all_server_names: List[str]) -> List[Dict]:
        """Get enabled/disabled state for all MCP servers."""
        return mcp_ops.get_all_mcp_server_states(self.conn, conversation_id, all_server_names,
                                                  user_guid=self.user_guid)

    # Tool permissions operations
    def check_tool_permission(self, conversation_id: int, tool_name: str) -> Optional[str]:
        """
        Check the permission state for a tool in a conversation.
        Returns None if no record exists (first-time usage, should prompt).
        """
        return tool_permissions.check_tool_permission(self.conn, conversation_id, tool_name,
                                                       user_guid=self.user_guid)

    def set_tool_permission(self, conversation_id: int, tool_name: str,
                           permission_state: str) -> bool:
        """Set the permission state for a tool in a conversation."""
        return tool_permissions.set_tool_permission(self.conn, conversation_id, tool_name,
                                                     permission_state, user_guid=self.user_guid)

    def get_all_tool_permissions(self, conversation_id: int) -> List[Dict]:
        """Get all tool permissions for a conversation."""
        return tool_permissions.get_all_tool_permissions(self.conn, conversation_id,
                                                          user_guid=self.user_guid)

    def delete_tool_permission(self, conversation_id: int, tool_name: str) -> bool:
        """Delete a tool permission record (reset to first-time usage behavior)."""
        return tool_permissions.delete_tool_permission(self.conn, conversation_id, tool_name,
                                                        user_guid=self.user_guid)

    def is_tool_allowed(self, conversation_id: int, tool_name: str) -> Optional[bool]:
        """
        Check if a tool is allowed to run.
        Returns None if permission should be requested from user (first-time usage).
        Returns True if allowed, False if denied.
        """
        return tool_permissions.is_tool_allowed(self.conn, conversation_id, tool_name,
                                                 user_guid=self.user_guid)

    # Autonomous action operations
    def create_action(self, name: str, description: str, action_prompt: str,
                      model_id: str, schedule_type: str, schedule_config: Dict,
                      context_mode: str = 'fresh', max_failures: int = 3,
                      max_tokens: int = 8192) -> int:
        """Create a new autonomous action."""
        return actions_module.create_action(self.conn, name, description, action_prompt,
                                            model_id, schedule_type, schedule_config,
                                            context_mode, max_failures, max_tokens,
                                            user_guid=self.user_guid)

    def get_action(self, action_id: int) -> Optional[Dict]:
        """Retrieve a specific action."""
        return actions_module.get_action(self.conn, action_id, user_guid=self.user_guid)

    def get_action_by_name(self, name: str) -> Optional[Dict]:
        """Retrieve an action by name."""
        return actions_module.get_action_by_name(self.conn, name, user_guid=self.user_guid)

    def get_all_actions(self, include_disabled: bool = True) -> List[Dict]:
        """Retrieve all actions."""
        return actions_module.get_all_actions(self.conn, user_guid=self.user_guid,
                                              include_disabled=include_disabled)

    def update_action(self, action_id: int, updates: Dict) -> bool:
        """Update an action's configuration."""
        return actions_module.update_action(self.conn, action_id, updates,
                                            user_guid=self.user_guid)

    def delete_action(self, action_id: int) -> bool:
        """Delete an action and all its related data."""
        return actions_module.delete_action(self.conn, action_id, user_guid=self.user_guid)

    def enable_action(self, action_id: int) -> bool:
        """Enable a disabled action."""
        return actions_module.enable_action(self.conn, action_id, user_guid=self.user_guid)

    def disable_action(self, action_id: int) -> bool:
        """Disable an action."""
        return actions_module.disable_action(self.conn, action_id, user_guid=self.user_guid)

    def increment_action_failure_count(self, action_id: int) -> Dict:
        """Increment failure count and auto-disable if threshold reached."""
        return actions_module.increment_failure_count(self.conn, action_id,
                                                       user_guid=self.user_guid)

    def update_action_last_run(self, action_id: int,
                               next_run_at: Optional[datetime] = None) -> bool:
        """Update last_run_at and optionally next_run_at."""
        return actions_module.update_last_run(self.conn, action_id, next_run_at,
                                               user_guid=self.user_guid)

    # Action run operations
    def record_action_run(self, action_id: int, status: str,
                          result_text: str = None, result_html: str = None,
                          error_message: str = None, input_tokens: int = 0,
                          output_tokens: int = 0, context_snapshot: str = None) -> int:
        """Record a new action run."""
        return actions_module.record_action_run(self.conn, action_id, status,
                                                 user_guid=self.user_guid,
                                                 result_text=result_text,
                                                 result_html=result_html,
                                                 error_message=error_message,
                                                 input_tokens=input_tokens,
                                                 output_tokens=output_tokens,
                                                 context_snapshot=context_snapshot)

    def update_action_run(self, run_id: int, status: str,
                          result_text: str = None, result_html: str = None,
                          error_message: str = None, input_tokens: int = None,
                          output_tokens: int = None, context_snapshot: str = None) -> bool:
        """Update an existing action run record."""
        return actions_module.update_action_run(self.conn, run_id, status,
                                                 user_guid=self.user_guid,
                                                 result_text=result_text,
                                                 result_html=result_html,
                                                 error_message=error_message,
                                                 input_tokens=input_tokens,
                                                 output_tokens=output_tokens,
                                                 context_snapshot=context_snapshot)

    def get_action_run(self, run_id: int) -> Optional[Dict]:
        """Retrieve a specific action run."""
        return actions_module.get_action_run(self.conn, run_id, user_guid=self.user_guid)

    def get_action_runs(self, action_id: int, limit: int = 50,
                        offset: int = 0) -> List[Dict]:
        """Retrieve runs for an action."""
        return actions_module.get_action_runs(self.conn, action_id, user_guid=self.user_guid,
                                               limit=limit, offset=offset)

    def get_recent_action_runs(self, limit: int = 20) -> List[Dict]:
        """Retrieve recent runs across all actions."""
        return actions_module.get_recent_runs(self.conn, user_guid=self.user_guid,
                                               limit=limit)

    def get_failed_action_count(self) -> int:
        """Get count of disabled actions (for home screen indicator)."""
        return actions_module.get_failed_action_count(self.conn, user_guid=self.user_guid)

    # Action tool permission operations
    def set_action_tool_permission(self, action_id: int, tool_name: str,
                                   server_name: str, permission_state: str) -> bool:
        """Set a tool permission for an action."""
        return actions_module.set_action_tool_permission(self.conn, action_id,
                                                          tool_name, server_name,
                                                          permission_state,
                                                          user_guid=self.user_guid)

    def set_action_tool_permissions_batch(self, action_id: int,
                                          permissions: List[Dict]) -> bool:
        """Set multiple tool permissions for an action."""
        return actions_module.set_action_tool_permissions_batch(self.conn, action_id,
                                                                  permissions,
                                                                  user_guid=self.user_guid)

    def get_action_tool_permissions(self, action_id: int) -> List[Dict]:
        """Get all tool permissions for an action."""
        return actions_module.get_action_tool_permissions(self.conn, action_id,
                                                           user_guid=self.user_guid)

    # Usage tracking operations
    def record_usage(self, conversation_id: int, model_id: str, region: str,
                    input_tokens: int, output_tokens: int, cost: float,
                    timestamp: datetime):
        """Record usage for token management and billing."""
        usage_module.record_usage(self.conn, conversation_id, model_id, region,
                                 input_tokens, output_tokens, cost, timestamp,
                                 user_guid=self.user_guid)

    def get_usage_in_window(self, window_start: datetime) -> float:
        """Get total cost for usage since window_start."""
        return usage_module.get_usage_in_window(self.conn, window_start, user_guid=self.user_guid)

    def get_oldest_usage_in_window(self, window_start: datetime) -> Optional[datetime]:
        """Get timestamp of oldest usage in the rolling window."""
        return usage_module.get_oldest_usage_in_window(self.conn, window_start,
                                                        user_guid=self.user_guid)

    def get_token_usage_in_window(self, window_start: datetime) -> Tuple[int, int]:
        """Get total token usage (input and output separately) since window_start."""
        return usage_module.get_token_usage_in_window(self.conn, window_start,
                                                       user_guid=self.user_guid)

    def get_usage_summary(self, window_start: datetime) -> List[Dict]:
        """Get detailed usage summary for the rolling window."""
        return usage_module.get_usage_summary(self.conn, window_start, user_guid=self.user_guid)

    def cleanup_old_usage(self, cutoff_date: datetime):
        """Clean up usage records older than cutoff_date."""
        usage_module.cleanup_old_usage(self.conn, cutoff_date, user_guid=self.user_guid)

    # Connection management
    def close(self):
        """Close the database connection."""
        self._conn_manager.close()


# Export the main class
__all__ = ['ConversationDatabase']
