"""
Conversation CRUD operations module.

This module handles:
- Creating new conversations
- Retrieving conversation records
- Updating conversation settings
- Deleting conversations
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional


def create_conversation(conn: sqlite3.Connection, name: str, model_id: str,
                       instructions: Optional[str] = None, user_guid: str = None,
                       compaction_threshold: Optional[float] = None) -> int:
    """
    Create a new conversation.

    Args:
        conn: Database connection
        name: Name of the conversation
        model_id: ID of the Bedrock model being used
        instructions: Optional instructions/system prompt for the conversation
        user_guid: User GUID for multi-user support
        compaction_threshold: Optional compaction threshold override (0.0-1.0, NULL uses config default)

    Returns:
        ID of the newly created conversation
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO conversations (name, model_id, created_at, last_updated, instructions, user_guid, compaction_threshold)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (name, model_id, now, now, instructions, user_guid, compaction_threshold))

    conn.commit()
    conversation_id = cursor.lastrowid
    logging.info(f"Created conversation '{name}' with ID {conversation_id} for user {user_guid} (compaction_threshold: {compaction_threshold})")
    return conversation_id


def get_active_conversations(conn: sqlite3.Connection, user_guid: str = None) -> List[Dict]:
    """
    Retrieve all active conversations for a user.

    Args:
        conn: Database connection
        user_guid: User GUID for multi-user support

    Returns:
        List of conversation dictionaries
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            c.id,
            c.name,
            c.model_id,
            c.created_at,
            c.last_updated,
            c.total_tokens,
            c.instructions,
            c.tokens_sent,
            c.tokens_received,
            COUNT(m.id) as message_count,
            MAX(m.timestamp) as last_message_at
        FROM conversations c
        LEFT JOIN messages m ON c.id = m.conversation_id AND m.user_guid = ?
        WHERE c.is_active = 1 AND c.user_guid = ?
        GROUP BY c.id
        ORDER BY c.last_updated DESC
    ''', (user_guid, user_guid))

    conversations = []
    for row in cursor.fetchall():
        conversations.append({
            'id': row['id'],
            'name': row['name'],
            'model_id': row['model_id'],
            'created_at': row['created_at'],
            'last_updated': row['last_updated'],
            'total_tokens': row['total_tokens'],
            'instructions': row['instructions'],
            'tokens_sent': row['tokens_sent'] or 0,
            'tokens_received': row['tokens_received'] or 0,
            'message_count': row['message_count'],
            'last_message_at': row['last_message_at']
        })

    return conversations


def get_conversation(conn: sqlite3.Connection, conversation_id: int, user_guid: str = None) -> Optional[Dict]:
    """
    Retrieve a specific conversation for a user.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        Conversation dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, model_id, created_at, last_updated, total_tokens, instructions,
               tokens_sent, tokens_received, max_tokens, compaction_threshold
        FROM conversations
        WHERE id = ? AND user_guid = ?
    ''', (conversation_id, user_guid))

    row = cursor.fetchone()
    if row:
        return {
            'id': row['id'],
            'name': row['name'],
            'model_id': row['model_id'],
            'created_at': row['created_at'],
            'last_updated': row['last_updated'],
            'total_tokens': row['total_tokens'],
            'instructions': row['instructions'],
            'tokens_sent': row['tokens_sent'] or 0,
            'tokens_received': row['tokens_received'] or 0,
            'max_tokens': row['max_tokens'],  # NULL means use global default
            'compaction_threshold': row['compaction_threshold']  # NULL means use global default
        }
    return None


def get_conversation_token_count(conn: sqlite3.Connection, conversation_id: int, user_guid: str = None) -> int:
    """
    Get the total token count for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        Total token count
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT total_tokens FROM conversations WHERE id = ? AND user_guid = ?
    ''', (conversation_id, user_guid))

    row = cursor.fetchone()
    return row['total_tokens'] if row else 0


def recalculate_total_tokens(conn: sqlite3.Connection, conversation_id: int,
                             user_guid: str = None) -> int:
    """
    Recalculate and update total_tokens from active (non-rolled-up) messages.

    This function recalculates total_tokens by summing token_count from all
    messages that are NOT marked as rolled up. This ensures accuracy after
    compaction operations.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        The new total token count
    """
    cursor = conn.cursor()

    # Sum tokens from active (non-rolled-up) messages only
    cursor.execute('''
        SELECT COALESCE(SUM(token_count), 0) as active_tokens
        FROM messages
        WHERE conversation_id = ? AND user_guid = ? AND is_rolled_up = 0
    ''', (conversation_id, user_guid))

    row = cursor.fetchone()
    new_total = row['active_tokens'] if row else 0

    # Update the conversation's total_tokens
    cursor.execute('''
        UPDATE conversations
        SET total_tokens = ?
        WHERE id = ? AND user_guid = ?
    ''', (new_total, conversation_id, user_guid))

    conn.commit()
    logging.info(f"Recalculated total_tokens for conversation {conversation_id}: {new_total}")
    return new_total


def delete_conversation(conn: sqlite3.Connection, conversation_id: int, user_guid: str = None) -> bool:
    """
    Delete a conversation and all its messages for a user.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation to delete
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()

        # Delete all messages for this conversation (filtered by user_guid for safety)
        cursor.execute('''
            DELETE FROM messages
            WHERE conversation_id = ? AND user_guid = ?
        ''', (conversation_id, user_guid))

        # Delete all rollup history for this conversation
        cursor.execute('''
            DELETE FROM rollup_history
            WHERE conversation_id = ? AND user_guid = ?
        ''', (conversation_id, user_guid))

        # Delete the conversation (filtered by user_guid for security)
        cursor.execute('''
            DELETE FROM conversations
            WHERE id = ? AND user_guid = ?
        ''', (conversation_id, user_guid))

        conn.commit()
        logging.info(f"Deleted conversation {conversation_id} for user {user_guid}")
        return True

    except Exception as e:
        logging.error(f"Failed to delete conversation {conversation_id}: {e}")
        conn.rollback()
        return False


def update_conversation_max_tokens(conn: sqlite3.Connection, conversation_id: int,
                                   max_tokens: int, user_guid: str = None):
    """
    Update the max_tokens setting for a specific conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        max_tokens: Maximum tokens for this conversation (overrides global default)
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE conversations
            SET max_tokens = ?
            WHERE id = ? AND user_guid = ?
        ''', (max_tokens, conversation_id, user_guid))
        conn.commit()
        logging.info(f"Updated max_tokens for conversation {conversation_id} to {max_tokens}")
    except Exception as e:
        logging.error(f"Failed to update max_tokens: {e}")
        conn.rollback()


def update_conversation_compaction_threshold(conn: sqlite3.Connection, conversation_id: int,
                                              compaction_threshold: float, user_guid: str = None):
    """
    Update the compaction_threshold setting for a specific conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        compaction_threshold: Compaction threshold (0.0-1.0) for this conversation (overrides global default)
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE conversations
            SET compaction_threshold = ?
            WHERE id = ? AND user_guid = ?
        ''', (compaction_threshold, conversation_id, user_guid))
        conn.commit()
        logging.info(f"Updated compaction_threshold for conversation {conversation_id} to {compaction_threshold}")
    except Exception as e:
        logging.error(f"Failed to update compaction_threshold: {e}")
        conn.rollback()


def update_conversation_instructions(conn: sqlite3.Connection, conversation_id: int,
                                     instructions: Optional[str], user_guid: str = None):
    """
    Update the instructions for a specific conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        instructions: New instructions/system prompt (None to clear)
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE conversations
            SET instructions = ?
            WHERE id = ? AND user_guid = ?
        ''', (instructions, conversation_id, user_guid))
        conn.commit()
        if instructions:
            logging.info(f"Updated instructions for conversation {conversation_id}")
        else:
            logging.info(f"Cleared instructions for conversation {conversation_id}")
    except Exception as e:
        logging.error(f"Failed to update instructions: {e}")
        conn.rollback()


def update_token_usage(conn: sqlite3.Connection, conversation_id: int,
                      tokens_sent: int, tokens_received: int, model_id: str = None,
                      user_guid: str = None):
    """
    Update the API token usage for a conversation and track per-model usage.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tokens_sent: Number of tokens sent to the API (input tokens)
        tokens_received: Number of tokens received from the API (output tokens)
        model_id: Model used for this request (for per-model tracking)
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()

        # Update overall conversation token counts
        cursor.execute('''
            UPDATE conversations
            SET tokens_sent = tokens_sent + ?,
                tokens_received = tokens_received + ?
            WHERE id = ? AND user_guid = ?
        ''', (tokens_sent, tokens_received, conversation_id, user_guid))

        # Update per-model token usage if model_id provided
        if model_id:
            now = datetime.now().isoformat()

            # Try to update existing record
            cursor.execute('''
                INSERT INTO conversation_model_usage
                    (conversation_id, model_id, input_tokens, output_tokens, first_used, last_used, user_guid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id, model_id) DO UPDATE SET
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    last_used = excluded.last_used
            ''', (conversation_id, model_id, tokens_sent, tokens_received, now, now, user_guid))

        conn.commit()
        logging.debug(f"Updated token usage for conversation {conversation_id}: +{tokens_sent} sent, +{tokens_received} received (model: {model_id or 'unknown'})")

    except Exception as e:
        logging.error(f"Failed to update token usage: {e}")
        conn.rollback()


def get_model_usage_breakdown(conn: sqlite3.Connection, conversation_id: int,
                              user_guid: str = None) -> List[Dict]:
    """
    Get per-model token usage breakdown for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        List of dictionaries with model usage details
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT model_id, input_tokens, output_tokens, first_used, last_used
        FROM conversation_model_usage
        WHERE conversation_id = ? AND user_guid = ?
        ORDER BY first_used ASC
    ''', (conversation_id, user_guid))

    results = []
    for row in cursor.fetchall():
        results.append({
            'model_id': row['model_id'],
            'input_tokens': row['input_tokens'],
            'output_tokens': row['output_tokens'],
            'total_tokens': row['input_tokens'] + row['output_tokens'],
            'first_used': row['first_used'],
            'last_used': row['last_used']
        })

    return results


def get_predefined_conversation_by_name(conn: sqlite3.Connection, name: str,
                                        user_guid: str = None) -> Optional[Dict]:
    """
    Retrieve a predefined conversation by name for a user.

    Args:
        conn: Database connection
        name: Name of the predefined conversation
        user_guid: User GUID for multi-user support

    Returns:
        Conversation dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, model_id, created_at, last_updated, instructions, config_hash, is_predefined
        FROM conversations
        WHERE name = ? AND is_predefined = 1 AND is_active = 1 AND user_guid = ?
    ''', (name, user_guid))

    row = cursor.fetchone()
    if row:
        return {
            'id': row['id'],
            'name': row['name'],
            'model_id': row['model_id'],
            'created_at': row['created_at'],
            'last_updated': row['last_updated'],
            'instructions': row['instructions'],
            'config_hash': row['config_hash'],
            'is_predefined': row['is_predefined']
        }
    return None


def create_predefined_conversation(conn: sqlite3.Connection, name: str, model_id: str,
                                   instructions: Optional[str], config_hash: str,
                                   user_guid: str = None) -> int:
    """
    Create a new predefined conversation.

    Args:
        conn: Database connection
        name: Name of the conversation
        model_id: ID of the model being used
        instructions: Instructions/system prompt for the conversation
        config_hash: Hash of the configuration to detect changes
        user_guid: User GUID for multi-user support

    Returns:
        ID of the newly created conversation
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO conversations (name, model_id, created_at, last_updated, instructions,
                                  is_predefined, config_hash, user_guid)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    ''', (name, model_id, now, now, instructions, config_hash, user_guid))

    conn.commit()
    conversation_id = cursor.lastrowid
    logging.info(f"Created predefined conversation '{name}' with ID {conversation_id} for user {user_guid}")
    return conversation_id


def update_predefined_conversation(conn: sqlite3.Connection, conversation_id: int,
                                   model_id: str, instructions: Optional[str],
                                   config_hash: str, user_guid: str = None):
    """
    Update a predefined conversation's settings.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        model_id: New model ID
        instructions: New instructions/system prompt
        config_hash: New config hash
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()
        now = datetime.now()

        cursor.execute('''
            UPDATE conversations
            SET model_id = ?, instructions = ?, config_hash = ?, last_updated = ?
            WHERE id = ? AND is_predefined = 1 AND user_guid = ?
        ''', (model_id, instructions, config_hash, now, conversation_id, user_guid))

        conn.commit()
        logging.info(f"Updated predefined conversation {conversation_id}")
    except Exception as e:
        logging.error(f"Failed to update predefined conversation: {e}")
        conn.rollback()


def is_conversation_predefined(conn: sqlite3.Connection, conversation_id: int,
                                user_guid: str = None) -> bool:
    """
    Check if a conversation is predefined.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        True if conversation is predefined, False otherwise
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT is_predefined FROM conversations WHERE id = ? AND user_guid = ?
    ''', (conversation_id, user_guid))

    row = cursor.fetchone()
    return bool(row['is_predefined']) if row else False
