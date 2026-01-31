"""
Autonomous Actions CRUD operations module.

This module handles:
- Creating and managing scheduled action definitions
- Recording and retrieving action execution history
- Managing tool permissions for actions


"""

import sqlite3
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional, Any


def create_action(conn: sqlite3.Connection, name: str, description: str,
                  action_prompt: str, model_id: str, schedule_type: str,
                  schedule_config: Dict[str, Any], context_mode: str = 'fresh',
                  max_failures: int = 3, max_tokens: int = 8192,
                  user_guid: str = None) -> int:
    """
    Create a new autonomous action.

    Args:
        conn: Database connection
        name: Unique name for the action
        description: Human-readable description
        action_prompt: The prompt to execute
        model_id: Model ID to use for execution
        schedule_type: 'one_off' or 'recurring'
        schedule_config: JSON-serialisable schedule configuration
        context_mode: 'fresh' (new each run) or 'cumulative' (uses prior context)
        max_failures: Number of failures before auto-disable
        max_tokens: Maximum tokens for LLM response (default 8192)
        user_guid: User GUID for multi-user support

    Returns:
        ID of the newly created action
    """
    cursor = conn.cursor()
    now = datetime.now()
    config_json = json.dumps(schedule_config)

    cursor.execute('''
        INSERT INTO autonomous_actions
            (name, description, action_prompt, model_id, schedule_type,
             schedule_config, context_mode, max_failures, max_tokens, created_at, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, description, action_prompt, model_id, schedule_type,
          config_json, context_mode, max_failures, max_tokens, now, user_guid))

    conn.commit()
    action_id = cursor.lastrowid
    logging.info(f"Created autonomous action '{name}' with ID {action_id} for user {user_guid}")
    return action_id


def get_action(conn: sqlite3.Connection, action_id: int,
               user_guid: str = None) -> Optional[Dict]:
    """
    Retrieve a specific action.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support

    Returns:
        Action dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, description, action_prompt, model_id, schedule_type,
               schedule_config, context_mode, max_failures, failure_count,
               is_enabled, max_tokens, created_at, last_run_at, next_run_at
        FROM autonomous_actions
        WHERE id = ? AND user_guid = ?
    ''', (action_id, user_guid))

    row = cursor.fetchone()
    if row:
        return _row_to_action_dict(row)
    return None


def get_action_by_name(conn: sqlite3.Connection, name: str,
                       user_guid: str = None) -> Optional[Dict]:
    """
    Retrieve an action by name.

    Args:
        conn: Database connection
        name: Name of the action
        user_guid: User GUID for multi-user support

    Returns:
        Action dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, description, action_prompt, model_id, schedule_type,
               schedule_config, context_mode, max_failures, failure_count,
               is_enabled, max_tokens, created_at, last_run_at, next_run_at
        FROM autonomous_actions
        WHERE name = ? AND user_guid = ?
    ''', (name, user_guid))

    row = cursor.fetchone()
    if row:
        return _row_to_action_dict(row)
    return None


def get_all_actions(conn: sqlite3.Connection, user_guid: str = None,
                    include_disabled: bool = True) -> List[Dict]:
    """
    Retrieve all actions for a user.

    Args:
        conn: Database connection
        user_guid: User GUID for multi-user support
        include_disabled: Whether to include disabled actions

    Returns:
        List of action dictionaries
    """
    cursor = conn.cursor()

    if include_disabled:
        cursor.execute('''
            SELECT id, name, description, action_prompt, model_id, schedule_type,
                   schedule_config, context_mode, max_failures, failure_count,
                   is_enabled, max_tokens, created_at, last_run_at, next_run_at
            FROM autonomous_actions
            WHERE user_guid = ?
            ORDER BY created_at DESC
        ''', (user_guid,))
    else:
        cursor.execute('''
            SELECT id, name, description, action_prompt, model_id, schedule_type,
                   schedule_config, context_mode, max_failures, failure_count,
                   is_enabled, max_tokens, created_at, last_run_at, next_run_at
            FROM autonomous_actions
            WHERE user_guid = ? AND is_enabled = 1
            ORDER BY created_at DESC
        ''', (user_guid,))

    return [_row_to_action_dict(row) for row in cursor.fetchall()]


def update_action(conn: sqlite3.Connection, action_id: int,
                  updates: Dict[str, Any], user_guid: str = None) -> bool:
    """
    Update an action's configuration.

    Automatically increments the version column for daemon change detection.

    Args:
        conn: Database connection
        action_id: ID of the action
        updates: Dictionary of fields to update
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()

        # Build dynamic UPDATE statement
        allowed_fields = ['name', 'description', 'action_prompt', 'model_id',
                          'schedule_type', 'schedule_config', 'context_mode',
                          'max_failures', 'max_tokens', 'next_run_at']
        set_clauses = []
        values = []

        for field, value in updates.items():
            if field in allowed_fields:
                if field == 'schedule_config' and isinstance(value, dict):
                    value = json.dumps(value)
                set_clauses.append(f"{field} = ?")
                values.append(value)

        if not set_clauses:
            return False

        # Always increment version and update timestamp for daemon change detection
        set_clauses.append("version = COALESCE(version, 0) + 1")
        set_clauses.append("updated_at = ?")
        values.append(datetime.now().isoformat())

        values.extend([action_id, user_guid])
        query = f'''
            UPDATE autonomous_actions
            SET {', '.join(set_clauses)}
            WHERE id = ? AND user_guid = ?
        '''

        cursor.execute(query, values)
        conn.commit()
        logging.info(f"Updated action {action_id}: {list(updates.keys())}")
        return cursor.rowcount > 0

    except Exception as e:
        logging.error(f"Failed to update action {action_id}: {e}")
        conn.rollback()
        return False


def delete_action(conn: sqlite3.Connection, action_id: int,
                  user_guid: str = None) -> bool:
    """
    Delete an action and all its related data.

    Args:
        conn: Database connection
        action_id: ID of the action to delete
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()

        # Delete tool permissions
        cursor.execute('''
            DELETE FROM action_tool_permissions
            WHERE action_id = ? AND user_guid = ?
        ''', (action_id, user_guid))

        # Delete run history
        cursor.execute('''
            DELETE FROM action_runs
            WHERE action_id = ? AND user_guid = ?
        ''', (action_id, user_guid))

        # Delete the action
        cursor.execute('''
            DELETE FROM autonomous_actions
            WHERE id = ? AND user_guid = ?
        ''', (action_id, user_guid))

        conn.commit()
        logging.info(f"Deleted action {action_id} for user {user_guid}")
        return True

    except Exception as e:
        logging.error(f"Failed to delete action {action_id}: {e}")
        conn.rollback()
        return False


def enable_action(conn: sqlite3.Connection, action_id: int,
                  user_guid: str = None) -> bool:
    """
    Enable a disabled action.

    Automatically increments the version column for daemon change detection.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            UPDATE autonomous_actions
            SET is_enabled = 1, failure_count = 0,
                version = COALESCE(version, 0) + 1,
                updated_at = ?
            WHERE id = ? AND user_guid = ?
        ''', (now, action_id, user_guid))
        conn.commit()
        logging.info(f"Enabled action {action_id}")
        return cursor.rowcount > 0

    except Exception as e:
        logging.error(f"Failed to enable action {action_id}: {e}")
        conn.rollback()
        return False


def disable_action(conn: sqlite3.Connection, action_id: int,
                   user_guid: str = None) -> bool:
    """
    Disable an action.

    Automatically increments the version column for daemon change detection.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            UPDATE autonomous_actions
            SET is_enabled = 0,
                version = COALESCE(version, 0) + 1,
                updated_at = ?
            WHERE id = ? AND user_guid = ?
        ''', (now, action_id, user_guid))
        conn.commit()
        logging.info(f"Disabled action {action_id}")
        return cursor.rowcount > 0

    except Exception as e:
        logging.error(f"Failed to disable action {action_id}: {e}")
        conn.rollback()
        return False


def increment_failure_count(conn: sqlite3.Connection, action_id: int,
                            user_guid: str = None) -> Dict[str, Any]:
    """
    Increment failure count and auto-disable if threshold reached.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support

    Returns:
        Dict with 'failure_count', 'max_failures', 'auto_disabled' keys
    """
    try:
        cursor = conn.cursor()

        # Get current counts
        cursor.execute('''
            SELECT failure_count, max_failures
            FROM autonomous_actions
            WHERE id = ? AND user_guid = ?
        ''', (action_id, user_guid))

        row = cursor.fetchone()
        if not row:
            return {'failure_count': 0, 'max_failures': 3, 'auto_disabled': False}

        new_count = row['failure_count'] + 1
        max_failures = row['max_failures']
        auto_disabled = new_count >= max_failures

        if auto_disabled:
            cursor.execute('''
                UPDATE autonomous_actions
                SET failure_count = ?, is_enabled = 0
                WHERE id = ? AND user_guid = ?
            ''', (new_count, action_id, user_guid))
            logging.error(f"Action {action_id} auto-disabled after {new_count} failures")
        else:
            cursor.execute('''
                UPDATE autonomous_actions
                SET failure_count = ?
                WHERE id = ? AND user_guid = ?
            ''', (new_count, action_id, user_guid))
            logging.warning(f"Action {action_id} failure count: {new_count}/{max_failures}")

        conn.commit()
        return {
            'failure_count': new_count,
            'max_failures': max_failures,
            'auto_disabled': auto_disabled
        }

    except Exception as e:
        logging.error(f"Failed to increment failure count for action {action_id}: {e}")
        conn.rollback()
        return {'failure_count': 0, 'max_failures': 3, 'auto_disabled': False}


def update_last_run(conn: sqlite3.Connection, action_id: int,
                    next_run_at: Optional[datetime] = None,
                    user_guid: str = None) -> bool:
    """
    Update last_run_at and optionally next_run_at.

    Args:
        conn: Database connection
        action_id: ID of the action
        next_run_at: Next scheduled run time (None for one-off)
        user_guid: User GUID for multi-user support

    Returns:
        True if successful
    """
    try:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute('''
            UPDATE autonomous_actions
            SET last_run_at = ?, next_run_at = ?
            WHERE id = ? AND user_guid = ?
        ''', (now, next_run_at, action_id, user_guid))

        conn.commit()
        return True

    except Exception as e:
        logging.error(f"Failed to update last run for action {action_id}: {e}")
        conn.rollback()
        return False


# --- Action Runs ---

def record_action_run(conn: sqlite3.Connection, action_id: int,
                      status: str, user_guid: str = None,
                      result_text: str = None, result_html: str = None,
                      error_message: str = None, input_tokens: int = 0,
                      output_tokens: int = 0, context_snapshot: str = None) -> int:
    """
    Record a new action run.

    Args:
        conn: Database connection
        action_id: ID of the action
        status: 'running', 'completed', or 'failed'
        user_guid: User GUID for multi-user support
        result_text: Plain text result
        result_html: HTML formatted result
        error_message: Error message if failed
        input_tokens: Input tokens used
        output_tokens: Output tokens used
        context_snapshot: JSON snapshot of context if cumulative mode

    Returns:
        ID of the run record
    """
    cursor = conn.cursor()
    now = datetime.now()
    completed_at = now if status in ('completed', 'failed') else None

    cursor.execute('''
        INSERT INTO action_runs
            (action_id, started_at, completed_at, status, result_text, result_html,
             error_message, input_tokens, output_tokens, context_snapshot, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (action_id, now, completed_at, status, result_text, result_html,
          error_message, input_tokens, output_tokens, context_snapshot, user_guid))

    conn.commit()
    run_id = cursor.lastrowid
    logging.info(f"Recorded action run {run_id} for action {action_id} with status '{status}'")
    return run_id


def update_action_run(conn: sqlite3.Connection, run_id: int,
                      status: str, user_guid: str = None,
                      result_text: str = None, result_html: str = None,
                      error_message: str = None, input_tokens: int = None,
                      output_tokens: int = None, context_snapshot: str = None) -> bool:
    """
    Update an existing action run record.

    Args:
        conn: Database connection
        run_id: ID of the run
        status: New status
        user_guid: User GUID for multi-user support
        result_text: Plain text result
        result_html: HTML formatted result
        error_message: Error message if failed
        input_tokens: Input tokens used
        output_tokens: Output tokens used
        context_snapshot: JSON snapshot of context

    Returns:
        True if successful
    """
    try:
        cursor = conn.cursor()
        completed_at = datetime.now() if status in ('completed', 'failed') else None

        cursor.execute('''
            UPDATE action_runs
            SET status = ?, completed_at = ?, result_text = ?, result_html = ?,
                error_message = ?, input_tokens = COALESCE(?, input_tokens),
                output_tokens = COALESCE(?, output_tokens),
                context_snapshot = COALESCE(?, context_snapshot)
            WHERE id = ? AND user_guid = ?
        ''', (status, completed_at, result_text, result_html, error_message,
              input_tokens, output_tokens, context_snapshot, run_id, user_guid))

        conn.commit()
        return True

    except Exception as e:
        logging.error(f"Failed to update action run {run_id}: {e}")
        conn.rollback()
        return False


def get_action_run(conn: sqlite3.Connection, run_id: int,
                   user_guid: str = None) -> Optional[Dict]:
    """
    Retrieve a specific action run.

    Args:
        conn: Database connection
        run_id: ID of the run
        user_guid: User GUID for multi-user support

    Returns:
        Run dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.action_id, r.started_at, r.completed_at, r.status,
               r.result_text, r.result_html, r.error_message, r.input_tokens,
               r.output_tokens, r.context_snapshot, a.name as action_name
        FROM action_runs r
        JOIN autonomous_actions a ON r.action_id = a.id
        WHERE r.id = ? AND r.user_guid = ?
    ''', (run_id, user_guid))

    row = cursor.fetchone()
    if row:
        return _row_to_run_dict(row)
    return None


def get_action_runs(conn: sqlite3.Connection, action_id: int,
                    user_guid: str = None, limit: int = 50,
                    offset: int = 0) -> List[Dict]:
    """
    Retrieve runs for an action.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support
        limit: Maximum number of runs to return
        offset: Offset for pagination

    Returns:
        List of run dictionaries
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.action_id, r.started_at, r.completed_at, r.status,
               r.result_text, r.result_html, r.error_message, r.input_tokens,
               r.output_tokens, r.context_snapshot, a.name as action_name
        FROM action_runs r
        JOIN autonomous_actions a ON r.action_id = a.id
        WHERE r.action_id = ? AND r.user_guid = ?
        ORDER BY r.started_at DESC
        LIMIT ? OFFSET ?
    ''', (action_id, user_guid, limit, offset))

    return [_row_to_run_dict(row) for row in cursor.fetchall()]


def get_recent_runs(conn: sqlite3.Connection, user_guid: str = None,
                    limit: int = 20) -> List[Dict]:
    """
    Retrieve recent runs across all actions.

    Args:
        conn: Database connection
        user_guid: User GUID for multi-user support
        limit: Maximum number of runs to return

    Returns:
        List of run dictionaries
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.action_id, r.started_at, r.completed_at, r.status,
               r.result_text, r.result_html, r.error_message, r.input_tokens,
               r.output_tokens, r.context_snapshot, a.name as action_name
        FROM action_runs r
        JOIN autonomous_actions a ON r.action_id = a.id
        WHERE r.user_guid = ?
        ORDER BY r.started_at DESC
        LIMIT ?
    ''', (user_guid, limit))

    return [_row_to_run_dict(row) for row in cursor.fetchall()]


def get_failed_action_count(conn: sqlite3.Connection,
                            user_guid: str = None) -> int:
    """
    Get count of disabled actions (for home screen indicator).

    Args:
        conn: Database connection
        user_guid: User GUID for multi-user support

    Returns:
        Count of disabled actions
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM autonomous_actions
        WHERE user_guid = ? AND is_enabled = 0 AND failure_count > 0
    ''', (user_guid,))

    row = cursor.fetchone()
    return row['count'] if row else 0


# --- Tool Permissions ---

def set_action_tool_permission(conn: sqlite3.Connection, action_id: int,
                               tool_name: str, server_name: str,
                               permission_state: str,
                               user_guid: str = None) -> bool:
    """
    Set a tool permission for an action.

    Args:
        conn: Database connection
        action_id: ID of the action
        tool_name: Name of the tool
        server_name: Name of the MCP server
        permission_state: Permission state ('allowed', 'denied')
        user_guid: User GUID for multi-user support

    Returns:
        True if successful
    """
    try:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute('''
            INSERT INTO action_tool_permissions
                (action_id, tool_name, server_name, permission_state, granted_at, user_guid)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_id, tool_name) DO UPDATE SET
                server_name = excluded.server_name,
                permission_state = excluded.permission_state,
                granted_at = excluded.granted_at
        ''', (action_id, tool_name, server_name, permission_state, now, user_guid))

        conn.commit()
        return True

    except Exception as e:
        logging.error(f"Failed to set tool permission: {e}")
        conn.rollback()
        return False


def set_action_tool_permissions_batch(conn: sqlite3.Connection, action_id: int,
                                      permissions: List[Dict[str, str]],
                                      user_guid: str = None) -> bool:
    """
    Set multiple tool permissions for an action.

    Args:
        conn: Database connection
        action_id: ID of the action
        permissions: List of dicts with 'tool_name', 'server_name', 'permission_state'
        user_guid: User GUID for multi-user support

    Returns:
        True if successful
    """
    try:
        cursor = conn.cursor()
        now = datetime.now()

        # Clear existing permissions
        cursor.execute('''
            DELETE FROM action_tool_permissions
            WHERE action_id = ? AND user_guid = ?
        ''', (action_id, user_guid))

        # Insert new permissions
        for perm in permissions:
            cursor.execute('''
                INSERT INTO action_tool_permissions
                    (action_id, tool_name, server_name, permission_state, granted_at, user_guid)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (action_id, perm['tool_name'], perm.get('server_name'),
                  perm['permission_state'], now, user_guid))

        conn.commit()
        logging.info(f"Set {len(permissions)} tool permissions for action {action_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to set tool permissions batch: {e}")
        conn.rollback()
        return False


def get_action_tool_permissions(conn: sqlite3.Connection, action_id: int,
                                user_guid: str = None) -> List[Dict]:
    """
    Get all tool permissions for an action.

    Args:
        conn: Database connection
        action_id: ID of the action
        user_guid: User GUID for multi-user support

    Returns:
        List of permission dictionaries
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tool_name, server_name, permission_state, granted_at
        FROM action_tool_permissions
        WHERE action_id = ? AND user_guid = ?
    ''', (action_id, user_guid))

    return [
        {
            'tool_name': row['tool_name'],
            'server_name': row['server_name'],
            'permission_state': row['permission_state'],
            'granted_at': row['granted_at']
        }
        for row in cursor.fetchall()
    ]


# --- Helper Functions ---

def _row_to_action_dict(row) -> Dict:
    """Convert a database row to an action dictionary."""
    schedule_config = row['schedule_config']
    if isinstance(schedule_config, str):
        try:
            schedule_config = json.loads(schedule_config)
        except json.JSONDecodeError:
            schedule_config = {}

    result = {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'action_prompt': row['action_prompt'],
        'model_id': row['model_id'],
        'schedule_type': row['schedule_type'],
        'schedule_config': schedule_config,
        'context_mode': row['context_mode'],
        'max_failures': row['max_failures'],
        'failure_count': row['failure_count'],
        'is_enabled': bool(row['is_enabled']),
        'max_tokens': row['max_tokens'] if 'max_tokens' in row.keys() else 8192,
        'created_at': row['created_at'],
        'last_run_at': row['last_run_at'],
        'next_run_at': row['next_run_at']
    }

    # Add daemon support fields if available
    if 'version' in row.keys():
        result['version'] = row['version'] or 1
    if 'locked_by' in row.keys():
        result['locked_by'] = row['locked_by']
    if 'locked_at' in row.keys():
        result['locked_at'] = row['locked_at']
    if 'updated_at' in row.keys():
        result['updated_at'] = row['updated_at']

    return result


def _row_to_run_dict(row) -> Dict:
    """Convert a database row to a run dictionary."""
    return {
        'id': row['id'],
        'action_id': row['action_id'],
        'action_name': row['action_name'],
        'started_at': row['started_at'],
        'completed_at': row['completed_at'],
        'status': row['status'],
        'result_text': row['result_text'],
        'result_html': row['result_html'],
        'error_message': row['error_message'],
        'input_tokens': row['input_tokens'],
        'output_tokens': row['output_tokens'],
        'context_snapshot': row['context_snapshot']
    }


# --- Daemon Support Functions ---

def get_all_actions_with_version(
    conn: sqlite3.Connection,
    user_guid: str,
    include_disabled: bool = False
) -> List[Dict]:
    """
    Get all actions with version information for change detection.

    Used by daemon to detect new, modified, or deleted actions.

    Args:
        conn: Database connection
        user_guid: User GUID for filtering
        include_disabled: Whether to include disabled actions

    Returns:
        List of action dictionaries with version field
    """
    cursor = conn.cursor()

    if include_disabled:
        cursor.execute('''
            SELECT * FROM autonomous_actions
            WHERE user_guid = ?
            ORDER BY name
        ''', (user_guid,))
    else:
        cursor.execute('''
            SELECT * FROM autonomous_actions
            WHERE user_guid = ? AND is_enabled = 1
            ORDER BY name
        ''', (user_guid,))

    return [_row_to_action_dict(row) for row in cursor.fetchall()]


def increment_action_version(
    conn: sqlite3.Connection,
    action_id: int,
    user_guid: str
) -> bool:
    """
    Increment the version of an action to signal a change.

    Should be called whenever an action is modified.

    Args:
        conn: Database connection
        action_id: Action ID
        user_guid: User GUID for verification

    Returns:
        True if successful, False otherwise
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute('''
        UPDATE autonomous_actions
        SET version = COALESCE(version, 0) + 1,
            updated_at = ?
        WHERE id = ? AND user_guid = ?
    ''', (now, action_id, user_guid))

    conn.commit()
    return cursor.rowcount > 0


def try_lock_action(
    conn: sqlite3.Connection,
    action_id: int,
    locked_by: str,
    user_guid: str
) -> bool:
    """
    Attempt to acquire an execution lock on an action.

    Uses optimistic locking - only succeeds if action is not already locked.

    Args:
        conn: Database connection
        action_id: Action ID to lock
        locked_by: Identifier of the locking process (daemon_id or session_id)
        user_guid: User GUID for verification

    Returns:
        True if lock acquired, False if already locked by another process
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # Try to acquire lock only if not already locked
    cursor.execute('''
        UPDATE autonomous_actions
        SET locked_by = ?,
            locked_at = ?
        WHERE id = ? AND user_guid = ?
        AND (locked_by IS NULL OR locked_by = ?)
    ''', (locked_by, now, action_id, user_guid, locked_by))

    conn.commit()
    return cursor.rowcount > 0


def unlock_action(
    conn: sqlite3.Connection,
    action_id: int,
    locked_by: str,
    user_guid: str
) -> bool:
    """
    Release an execution lock on an action.

    Only releases if the lock is held by the specified process.

    Args:
        conn: Database connection
        action_id: Action ID to unlock
        locked_by: Identifier of the process holding the lock
        user_guid: User GUID for verification

    Returns:
        True if unlocked successfully, False otherwise
    """
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE autonomous_actions
        SET locked_by = NULL,
            locked_at = NULL
        WHERE id = ? AND user_guid = ? AND locked_by = ?
    ''', (action_id, user_guid, locked_by))

    conn.commit()
    return cursor.rowcount > 0


def get_action_lock_info(
    conn: sqlite3.Connection,
    action_id: int,
    user_guid: str
) -> Optional[Dict]:
    """
    Get lock information for an action.

    Args:
        conn: Database connection
        action_id: Action ID
        user_guid: User GUID for verification

    Returns:
        Dictionary with locked_by and locked_at, or None if not found
    """
    cursor = conn.cursor()

    cursor.execute('''
        SELECT locked_by, locked_at
        FROM autonomous_actions
        WHERE id = ? AND user_guid = ?
    ''', (action_id, user_guid))

    row = cursor.fetchone()
    if row:
        return {
            'locked_by': row['locked_by'],
            'locked_at': row['locked_at']
        }
    return None


def clear_stale_locks(
    conn: sqlite3.Connection,
    lock_timeout_seconds: int = 300,
    user_guid: Optional[str] = None
) -> int:
    """
    Clear locks that are older than the timeout.

    Used to recover from crashed processes that didn't release their locks.

    Args:
        conn: Database connection
        lock_timeout_seconds: Seconds after which a lock is considered stale
        user_guid: Optional user GUID filter (clears all if None)

    Returns:
        Number of stale locks cleared
    """
    cursor = conn.cursor()
    from datetime import timedelta
    cutoff_time = (datetime.now() - timedelta(seconds=lock_timeout_seconds)).isoformat()

    if user_guid:
        cursor.execute('''
            UPDATE autonomous_actions
            SET locked_by = NULL,
                locked_at = NULL
            WHERE locked_at IS NOT NULL
            AND locked_at < ?
            AND user_guid = ?
        ''', (cutoff_time, user_guid))
    else:
        cursor.execute('''
            UPDATE autonomous_actions
            SET locked_by = NULL,
                locked_at = NULL
            WHERE locked_at IS NOT NULL
            AND locked_at < ?
        ''', (cutoff_time,))

    conn.commit()
    cleared = cursor.rowcount

    if cleared > 0:
        logging.info(f"Cleared {cleared} stale action lock(s)")

    return cleared


# --- Daemon Registry Functions ---

def register_daemon(
    conn: sqlite3.Connection,
    daemon_id: str,
    hostname: str,
    pid: int,
    user_guid: str
) -> bool:
    """
    Register a daemon process in the database.

    Args:
        conn: Database connection
        daemon_id: Unique daemon identifier
        hostname: Hostname where daemon is running
        pid: Process ID
        user_guid: User GUID

    Returns:
        True if registered successfully
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    try:
        cursor.execute('''
            INSERT INTO daemon_registry (daemon_id, hostname, pid, started_at, last_heartbeat, status, user_guid)
            VALUES (?, ?, ?, ?, ?, 'running', ?)
        ''', (daemon_id, hostname, pid, now, now, user_guid))
        conn.commit()
        logging.info(f"Daemon registered: {daemon_id} (PID: {pid})")
        return True
    except sqlite3.IntegrityError:
        # Daemon ID already exists, update it
        cursor.execute('''
            UPDATE daemon_registry
            SET hostname = ?, pid = ?, started_at = ?, last_heartbeat = ?, status = 'running'
            WHERE daemon_id = ?
        ''', (hostname, pid, now, now, daemon_id))
        conn.commit()
        logging.info(f"Daemon re-registered: {daemon_id} (PID: {pid})")
        return True
    except sqlite3.Error as e:
        logging.error(f"Failed to register daemon {daemon_id}: {e}")
        return False


def update_daemon_heartbeat(
    conn: sqlite3.Connection,
    daemon_id: str
) -> bool:
    """
    Update daemon heartbeat timestamp.

    Should be called periodically to indicate daemon is alive.

    Args:
        conn: Database connection
        daemon_id: Daemon identifier

    Returns:
        True if updated successfully
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute('''
        UPDATE daemon_registry
        SET last_heartbeat = ?
        WHERE daemon_id = ?
    ''', (now, daemon_id))

    conn.commit()
    return cursor.rowcount > 0


def unregister_daemon(
    conn: sqlite3.Connection,
    daemon_id: str
) -> bool:
    """
    Unregister a daemon process.

    Args:
        conn: Database connection
        daemon_id: Daemon identifier

    Returns:
        True if unregistered successfully
    """
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE daemon_registry
        SET status = 'stopped'
        WHERE daemon_id = ?
    ''', (daemon_id,))

    conn.commit()
    logging.info(f"Daemon unregistered: {daemon_id}")
    return cursor.rowcount > 0


def get_running_daemons(
    conn: sqlite3.Connection,
    user_guid: Optional[str] = None
) -> List[Dict]:
    """
    Get list of running daemons.

    Args:
        conn: Database connection
        user_guid: Optional user GUID filter

    Returns:
        List of daemon dictionaries
    """
    cursor = conn.cursor()

    if user_guid:
        cursor.execute('''
            SELECT * FROM daemon_registry
            WHERE status = 'running' AND user_guid = ?
        ''', (user_guid,))
    else:
        cursor.execute('''
            SELECT * FROM daemon_registry
            WHERE status = 'running'
        ''')

    return [
        {
            'daemon_id': row['daemon_id'],
            'hostname': row['hostname'],
            'pid': row['pid'],
            'started_at': row['started_at'],
            'last_heartbeat': row['last_heartbeat'],
            'user_guid': row['user_guid']
        }
        for row in cursor.fetchall()
    ]


def cleanup_stale_daemons(
    conn: sqlite3.Connection,
    heartbeat_timeout_seconds: int = 120
) -> int:
    """
    Mark daemons as stopped if their heartbeat is stale.

    Args:
        conn: Database connection
        heartbeat_timeout_seconds: Seconds without heartbeat to consider stale

    Returns:
        Number of stale daemons cleaned up
    """
    cursor = conn.cursor()
    from datetime import timedelta
    cutoff_time = (datetime.now() - timedelta(seconds=heartbeat_timeout_seconds)).isoformat()

    cursor.execute('''
        UPDATE daemon_registry
        SET status = 'stale'
        WHERE status = 'running'
        AND last_heartbeat < ?
    ''', (cutoff_time,))

    conn.commit()
    cleaned = cursor.rowcount

    if cleaned > 0:
        logging.info(f"Marked {cleaned} stale daemon(s) as stopped")

    return cleaned
