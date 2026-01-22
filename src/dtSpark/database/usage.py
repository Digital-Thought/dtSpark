"""
Usage tracking module.

This module handles:
- Recording token and cost usage
- Retrieving usage within time windows
- Usage summary and reporting
- Cleanup of old usage data
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def record_usage(conn: sqlite3.Connection, conversation_id: int, model_id: str,
                region: str, input_tokens: int, output_tokens: int, cost: float,
                timestamp: datetime, user_guid: str = None):
    """
    Record usage for token management and billing.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        model_id: Bedrock model ID
        region: AWS region
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cost: Cost in USD
        timestamp: Timestamp of usage
        user_guid: User GUID for multi-user support
    """
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO usage_tracking
        (conversation_id, model_id, region, input_tokens, output_tokens, cost, timestamp, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (conversation_id, model_id, region, input_tokens, output_tokens, cost, timestamp, user_guid))
    conn.commit()


def get_usage_in_window(conn: sqlite3.Connection, window_start: datetime,
                        user_guid: str = None) -> float:
    """
    Get total cost for usage since window_start.

    Args:
        conn: Database connection
        window_start: Start of rolling window
        user_guid: User GUID for multi-user support

    Returns:
        Total cost in USD
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(cost) as total_cost
        FROM usage_tracking
        WHERE timestamp >= ? AND user_guid = ?
    ''', (window_start, user_guid))

    result = cursor.fetchone()
    return result['total_cost'] if result['total_cost'] is not None else 0.0


def get_oldest_usage_in_window(conn: sqlite3.Connection,
                               window_start: datetime, user_guid: str = None) -> Optional[datetime]:
    """
    Get timestamp of oldest usage in the rolling window.

    Args:
        conn: Database connection
        window_start: Start of rolling window
        user_guid: User GUID for multi-user support

    Returns:
        Timestamp of oldest usage or None
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT MIN(timestamp) as oldest_timestamp
        FROM usage_tracking
        WHERE timestamp >= ? AND user_guid = ?
    ''', (window_start, user_guid))

    result = cursor.fetchone()
    if result and result['oldest_timestamp']:
        return datetime.fromisoformat(result['oldest_timestamp'])
    return None


def get_token_usage_in_window(conn: sqlite3.Connection,
                              window_start: datetime, user_guid: str = None) -> Tuple[int, int]:
    """
    Get total token usage (input and output separately) since window_start.

    Args:
        conn: Database connection
        window_start: Start of rolling window
        user_guid: User GUID for multi-user support

    Returns:
        Tuple of (total_input_tokens, total_output_tokens)
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            SUM(input_tokens) as total_input,
            SUM(output_tokens) as total_output
        FROM usage_tracking
        WHERE timestamp >= ? AND user_guid = ?
    ''', (window_start, user_guid))

    result = cursor.fetchone()
    total_input = result['total_input'] if result['total_input'] is not None else 0
    total_output = result['total_output'] if result['total_output'] is not None else 0
    return int(total_input), int(total_output)


def get_usage_summary(conn: sqlite3.Connection, window_start: datetime,
                      user_guid: str = None) -> List[Dict]:
    """
    Get detailed usage summary for the rolling window.

    Args:
        conn: Database connection
        window_start: Start of rolling window
        user_guid: User GUID for multi-user support

    Returns:
        List of usage records with model, tokens, and costs
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT model_id, region,
               SUM(input_tokens) as total_input_tokens,
               SUM(output_tokens) as total_output_tokens,
               SUM(cost) as total_cost,
               COUNT(*) as request_count
        FROM usage_tracking
        WHERE timestamp >= ? AND user_guid = ?
        GROUP BY model_id, region
        ORDER BY total_cost DESC
    ''', (window_start, user_guid))

    return [dict(row) for row in cursor.fetchall()]


def cleanup_old_usage(conn: sqlite3.Connection, cutoff_date: datetime,
                      user_guid: str = None):
    """
    Clean up usage records older than cutoff_date.

    Args:
        conn: Database connection
        cutoff_date: Delete records older than this date
        user_guid: User GUID for multi-user support (for safety filtering)
    """
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM usage_tracking
        WHERE timestamp < ? AND user_guid = ?
    ''', (cutoff_date, user_guid))
    deleted_count = cursor.rowcount
    conn.commit()
    logging.info(f"Cleaned up {deleted_count} old usage records for user {user_guid}")
