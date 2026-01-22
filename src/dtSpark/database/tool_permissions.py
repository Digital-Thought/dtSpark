"""
Tool permissions operations module.

This module handles:
- Checking tool permissions for conversations
- Setting tool permission states
- Managing first-time tool usage prompts
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, List


# Permission states
PERMISSION_ALLOWED = 'allowed'  # Run this time and all future times
PERMISSION_DENIED = 'denied'    # Never run this tool


def check_tool_permission(conn: sqlite3.Connection, conversation_id: int,
                          tool_name: str, user_guid: Optional[str] = None) -> Optional[str]:
    """
    Check the permission state for a tool in a conversation.
    Returns None if no record exists (first-time usage, should prompt).

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tool_name: Name of the tool
        user_guid: User GUID for multi-user support

    Returns:
        Permission state ('allowed', 'denied') or None if no record exists
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT permission_state
        FROM conversation_tool_permissions
        WHERE conversation_id = ? AND tool_name = ? AND user_guid = ?
    ''', (conversation_id, tool_name, user_guid))

    row = cursor.fetchone()
    if row is None:
        # No record exists - first time usage, should prompt user
        return None
    return row['permission_state']


def set_tool_permission(conn: sqlite3.Connection, conversation_id: int,
                        tool_name: str, permission_state: str,
                        user_guid: Optional[str] = None) -> bool:
    """
    Set the permission state for a tool in a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tool_name: Name of the tool
        permission_state: Permission state ('allowed' or 'denied')
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    if permission_state not in [PERMISSION_ALLOWED, PERMISSION_DENIED]:
        logging.error(f"Invalid permission state: {permission_state}")
        return False

    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute('''
            INSERT INTO conversation_tool_permissions
                (conversation_id, tool_name, permission_state, granted_at, updated_at, user_guid)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, tool_name) DO UPDATE SET
                permission_state = excluded.permission_state,
                updated_at = excluded.updated_at
        ''', (conversation_id, tool_name, permission_state, now, now, user_guid))

        conn.commit()
        logging.info(f"Tool permission '{tool_name}' set to '{permission_state}' for conversation {conversation_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to set tool permission: {e}")
        conn.rollback()
        return False


def get_all_tool_permissions(conn: sqlite3.Connection, conversation_id: int,
                             user_guid: Optional[str] = None) -> List[Dict]:
    """
    Get all tool permissions for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        List of dicts with 'tool_name', 'permission_state', 'granted_at', 'updated_at'
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tool_name, permission_state, granted_at, updated_at
        FROM conversation_tool_permissions
        WHERE conversation_id = ? AND user_guid = ?
        ORDER BY updated_at DESC
    ''', (conversation_id, user_guid))

    permissions = []
    for row in cursor.fetchall():
        permissions.append({
            'tool_name': row['tool_name'],
            'permission_state': row['permission_state'],
            'granted_at': row['granted_at'],
            'updated_at': row['updated_at']
        })

    return permissions


def delete_tool_permission(conn: sqlite3.Connection, conversation_id: int,
                          tool_name: str, user_guid: Optional[str] = None) -> bool:
    """
    Delete a tool permission record (reset to first-time usage behavior).

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tool_name: Name of the tool
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM conversation_tool_permissions
            WHERE conversation_id = ? AND tool_name = ? AND user_guid = ?
        ''', (conversation_id, tool_name, user_guid))

        conn.commit()
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logging.info(f"Deleted tool permission for '{tool_name}' in conversation {conversation_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to delete tool permission: {e}")
        conn.rollback()
        return False


def is_tool_allowed(conn: sqlite3.Connection, conversation_id: int,
                   tool_name: str, user_guid: Optional[str] = None) -> Optional[bool]:
    """
    Check if a tool is allowed to run.
    Returns None if permission should be requested from user (first-time usage).
    Returns True if allowed, False if denied.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tool_name: Name of the tool
        user_guid: User GUID for multi-user support

    Returns:
        True if allowed, False if denied, None if should prompt user
    """
    permission_state = check_tool_permission(conn, conversation_id, tool_name, user_guid)

    if permission_state is None:
        # No record exists - should prompt user
        return None
    elif permission_state == PERMISSION_ALLOWED:
        return True
    elif permission_state == PERMISSION_DENIED:
        return False
    else:
        logging.warning(f"Unknown permission state: {permission_state}")
        return None
