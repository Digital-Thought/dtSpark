"""
File attachment operations module.

This module handles:
- Adding files to conversations
- Retrieving attached files
- File deletion
- Tag-based file filtering
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional


def add_file(conn: sqlite3.Connection, conversation_id: int, filename: str,
            file_type: str, file_size: int, content_text: Optional[str] = None,
            content_base64: Optional[str] = None, mime_type: Optional[str] = None,
            token_count: int = 0, tags: Optional[str] = None, user_guid: str = None) -> int:
    """
    Add a file to a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        filename: Original filename
        file_type: File extension (e.g., .pdf, .docx)
        file_size: Size in bytes
        content_text: Extracted text content
        content_base64: Base64 encoded content (for images)
        mime_type: MIME type (for images)
        token_count: Token count of extracted content
        tags: Comma-separated tags for the file
        user_guid: User GUID for multi-user support

    Returns:
        ID of the newly added file
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO conversation_files
        (conversation_id, filename, file_type, file_size, content_text,
         content_base64, mime_type, token_count, added_at, tags, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (conversation_id, filename, file_type, file_size, content_text,
          content_base64, mime_type, token_count, now, tags, user_guid))

    conn.commit()
    file_id = cursor.lastrowid
    tags_str = f" with tags '{tags}'" if tags else ""
    logging.info(f"Added file '{filename}' to conversation {conversation_id}{tags_str}")
    return file_id


def get_conversation_files(conn: sqlite3.Connection, conversation_id: int,
                           user_guid: str = None) -> List[Dict]:
    """
    Retrieve all files for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support

    Returns:
        List of file dictionaries
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, filename, file_type, file_size, content_text,
               content_base64, mime_type, token_count, added_at, tags
        FROM conversation_files
        WHERE conversation_id = ? AND user_guid = ?
        ORDER BY added_at ASC
    ''', (conversation_id, user_guid))

    files = []
    for row in cursor.fetchall():
        files.append({
            'id': row['id'],
            'filename': row['filename'],
            'file_type': row['file_type'],
            'file_size': row['file_size'],
            'content_text': row['content_text'],
            'content_base64': row['content_base64'],
            'mime_type': row['mime_type'],
            'token_count': row['token_count'],
            'added_at': row['added_at'],
            'tags': row['tags']
        })

    return files


def get_files_by_tag(conn: sqlite3.Connection, conversation_id: int, tag: str,
                     user_guid: str = None) -> List[Dict]:
    """
    Retrieve files for a conversation filtered by tag.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        tag: Tag to filter by (case-insensitive)
        user_guid: User GUID for multi-user support

    Returns:
        List of file dictionaries with matching tag
    """
    cursor = conn.cursor()
    # Use LIKE to match tag anywhere in the comma-separated tags field
    # We add commas around the search pattern to ensure we match whole tags
    tag_pattern = f"%{tag}%"

    cursor.execute('''
        SELECT id, filename, file_type, file_size, content_text,
               content_base64, mime_type, token_count, added_at, tags
        FROM conversation_files
        WHERE conversation_id = ?
        AND user_guid = ?
        AND tags LIKE ?
        ORDER BY added_at ASC
    ''', (conversation_id, user_guid, tag_pattern))

    files = []
    for row in cursor.fetchall():
        # Additional filtering to ensure we match whole tags (not partial matches)
        tags_list = [t.strip().lower() for t in (row['tags'] or '').split(',') if t.strip()]
        if tag.lower() in tags_list:
            files.append({
                'id': row['id'],
                'filename': row['filename'],
                'file_type': row['file_type'],
                'file_size': row['file_size'],
                'content_text': row['content_text'],
                'content_base64': row['content_base64'],
                'mime_type': row['mime_type'],
                'token_count': row['token_count'],
                'added_at': row['added_at'],
                'tags': row['tags']
            })

    return files


def delete_conversation_files(conn: sqlite3.Connection, conversation_id: int,
                               user_guid: str = None):
    """
    Delete all files for a conversation.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_guid: User GUID for multi-user support
    """
    try:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM conversation_files
            WHERE conversation_id = ? AND user_guid = ?
        ''', (conversation_id, user_guid))
        conn.commit()
        logging.info(f"Deleted all files for conversation {conversation_id}")
    except Exception as e:
        logging.error(f"Failed to delete files for conversation {conversation_id}: {e}")
        conn.rollback()


def delete_file(conn: sqlite3.Connection, file_id: int, user_guid: str = None) -> bool:
    """
    Delete a specific file by ID.

    Args:
        conn: Database connection
        file_id: ID of the file to delete
        user_guid: User GUID for multi-user support (for security filtering)

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()
        # First, get the filename for logging (filtered by user_guid for security)
        cursor.execute('SELECT filename FROM conversation_files WHERE id = ? AND user_guid = ?',
                      (file_id, user_guid))
        row = cursor.fetchone()

        if not row:
            logging.warning(f"File ID {file_id} not found for user {user_guid}")
            return False

        filename = row['filename']

        # Delete the file (filtered by user_guid for security)
        cursor.execute('DELETE FROM conversation_files WHERE id = ? AND user_guid = ?',
                      (file_id, user_guid))
        conn.commit()
        logging.info(f"Deleted file '{filename}' (ID: {file_id})")
        return True
    except Exception as e:
        logging.error(f"Failed to delete file {file_id}: {e}")
        conn.rollback()
        return False
