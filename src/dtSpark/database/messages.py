"""
Message operations module.

This module handles:
- Adding messages to conversations
- Retrieving conversation messages
- Message rollup management
- Message token tracking
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict


def add_message(conn: sqlite3.Connection, conversation_id: int, role: str,
               content: str, token_count: int, user_guid: str = None) -> int:
    """
    Add a message to a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        role: Message role (user, assistant, system)
        content: Message content
        token_count: Number of tokens in the message
        user_guid: User GUID for multi-user support

    Returns:
        ID of the newly created message
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO messages (conversation_id, role, content, token_count, timestamp, user_guid)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (conversation_id, role, content, token_count, now, user_guid))

    # Update conversation total tokens and last_updated
    cursor.execute('''
        UPDATE conversations
        SET total_tokens = total_tokens + ?,
            last_updated = ?
        WHERE id = ? AND user_guid = ?
    ''', (token_count, now, conversation_id, user_guid))

    conn.commit()
    message_id = cursor.lastrowid
    logging.debug(f"Added message {message_id} to conversation {conversation_id}")
    return message_id


def get_conversation_messages(conn: sqlite3.Connection, conversation_id: int,
                              include_rolled_up: bool = False, user_guid: str = None) -> List[Dict]:
    """
    Retrieve messages for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        include_rolled_up: Whether to include rolled-up messages
        user_guid: User GUID for multi-user support

    Returns:
        List of message dictionaries
    """
    cursor = conn.cursor()

    if include_rolled_up:
        query = '''
            SELECT id, role, content, token_count, timestamp, is_rolled_up
            FROM messages
            WHERE conversation_id = ? AND user_guid = ?
            ORDER BY timestamp ASC
        '''
    else:
        query = '''
            SELECT id, role, content, token_count, timestamp, is_rolled_up
            FROM messages
            WHERE conversation_id = ? AND user_guid = ? AND is_rolled_up = 0
            ORDER BY timestamp ASC
        '''

    cursor.execute(query, (conversation_id, user_guid))

    messages = []
    for row in cursor.fetchall():
        messages.append({
            'id': row['id'],
            'role': row['role'],
            'content': row['content'],
            'token_count': row['token_count'],
            'timestamp': row['timestamp'],
            'is_rolled_up': bool(row['is_rolled_up'])
        })

    return messages


def mark_messages_as_rolled_up(conn: sqlite3.Connection, message_ids: List[int],
                                user_guid: str = None):
    """
    Mark messages as rolled up.

    Args:
        conn: Database connection
        message_ids: List of message IDs to mark
        user_guid: User GUID for multi-user support (for safety filtering)
    """
    cursor = conn.cursor()
    placeholders = ','.join('?' * len(message_ids))
    # Add user_guid filtering for security
    cursor.execute(f'''
        UPDATE messages
        SET is_rolled_up = 1
        WHERE id IN ({placeholders}) AND user_guid = ?
    ''', message_ids + [user_guid])
    conn.commit()
    logging.info(f"Marked {len(message_ids)} messages as rolled up")


def record_rollup(conn: sqlite3.Connection, conversation_id: int,
                 original_message_count: int, summarised_content: str,
                 original_token_count: int, summarised_token_count: int,
                 user_guid: str = None):
    """
    Record a rollup operation in history.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        original_message_count: Number of messages that were summarised
        summarised_content: The summary content
        original_token_count: Original token count
        summarised_token_count: Token count after summarisation
        user_guid: User GUID for multi-user support
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO rollup_history
        (conversation_id, original_message_count, summarised_content,
         original_token_count, summarised_token_count, rollup_timestamp, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (conversation_id, original_message_count, summarised_content,
          original_token_count, summarised_token_count, now, user_guid))

    # Update conversation total tokens
    token_reduction = original_token_count - summarised_token_count
    cursor.execute('''
        UPDATE conversations
        SET total_tokens = total_tokens - ?
        WHERE id = ? AND user_guid = ?
    ''', (token_reduction, conversation_id, user_guid))

    conn.commit()
    logging.info(f"Recorded rollup for conversation {conversation_id}, "
                f"reduced tokens by {token_reduction}")
