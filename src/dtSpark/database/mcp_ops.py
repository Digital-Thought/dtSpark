"""
MCP (Model Context Protocol) operations module.

This module handles:
- Recording MCP tool transactions for Cyber Security monitoring
- Retrieving transaction audit trails
- Managing MCP server enabled/disabled states per conversation
- Exporting transaction data for security audits
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional


def record_mcp_transaction(conn: sqlite3.Connection, conversation_id: int,
                           user_prompt: str, tool_name: str, tool_server: str,
                           tool_input: str, tool_response: str, is_error: bool = False,
                           execution_time_ms: Optional[int] = None,
                           message_id: Optional[int] = None, user_guid: str = None) -> int:
    """
    Record an MCP tool transaction for Cyber Security monitoring and audit trails.

    Args:
        conn: Database connection
        conversation_id: ID of the conversation
        user_prompt: The user's original prompt that triggered the tool call
        tool_name: Name of the MCP tool called
        tool_server: Name of the MCP server
        tool_input: JSON string of tool input parameters
        tool_response: Response from the tool
        is_error: Whether the transaction resulted in an error
        execution_time_ms: Execution time in milliseconds
        message_id: Optional ID of the related message
        user_guid: User GUID for multi-user support

    Returns:
        ID of the newly created transaction record
    """
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO mcp_transactions
        (conversation_id, message_id, user_prompt, tool_name, tool_server,
         tool_input, tool_response, is_error, execution_time_ms, transaction_timestamp, user_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (conversation_id, message_id, user_prompt, tool_name, tool_server,
          tool_input, tool_response, 1 if is_error else 0, execution_time_ms, now, user_guid))

    conn.commit()
    transaction_id = cursor.lastrowid
    logging.info(f"Recorded MCP transaction: {tool_server}.{tool_name} (ID: {transaction_id})")
    return transaction_id


def get_mcp_transactions(conn: sqlite3.Connection, conversation_id: Optional[int] = None,
                        tool_name: Optional[str] = None, tool_server: Optional[str] = None,
                        limit: Optional[int] = None, user_guid: str = None) -> List[Dict]:
    """
    Retrieve MCP transactions with optional filtering.

    Args:
        conn: Database connection
        conversation_id: Optional filter by conversation ID
        tool_name: Optional filter by tool name
        tool_server: Optional filter by server name
        limit: Optional limit on number of results
        user_guid: User GUID for multi-user support

    Returns:
        List of transaction dictionaries
    """
    cursor = conn.cursor()

    query = '''
        SELECT id, conversation_id, message_id, user_prompt, tool_name, tool_server,
               tool_input, tool_response, is_error, execution_time_ms, transaction_timestamp
        FROM mcp_transactions
        WHERE user_guid = ?
    '''
    params = [user_guid]

    if conversation_id is not None:
        query += ' AND conversation_id = ?'
        params.append(conversation_id)

    if tool_name is not None:
        query += ' AND tool_name = ?'
        params.append(tool_name)

    if tool_server is not None:
        query += ' AND tool_server = ?'
        params.append(tool_server)

    query += ' ORDER BY transaction_timestamp DESC'

    if limit is not None:
        query += ' LIMIT ?'
        params.append(limit)

    cursor.execute(query, params)

    transactions = []
    for row in cursor.fetchall():
        transactions.append({
            'id': row['id'],
            'conversation_id': row['conversation_id'],
            'message_id': row['message_id'],
            'user_prompt': row['user_prompt'],
            'tool_name': row['tool_name'],
            'tool_server': row['tool_server'],
            'tool_input': row['tool_input'],
            'tool_response': row['tool_response'],
            'is_error': bool(row['is_error']),
            'execution_time_ms': row['execution_time_ms'],
            'transaction_timestamp': row['transaction_timestamp']
        })

    return transactions


def get_mcp_transaction_stats(conn: sqlite3.Connection, user_guid: str = None) -> Dict:
    """
    Get statistics about MCP transactions for Cyber Security monitoring.

    Args:
        conn: Database connection
        user_guid: User GUID for multi-user support

    Returns:
        Dictionary with transaction statistics
    """
    cursor = conn.cursor()

    # Total transactions
    cursor.execute('SELECT COUNT(*) as total FROM mcp_transactions WHERE user_guid = ?',
                  (user_guid,))
    total = cursor.fetchone()['total']

    # Error count
    cursor.execute('SELECT COUNT(*) as errors FROM mcp_transactions WHERE is_error = 1 AND user_guid = ?',
                  (user_guid,))
    errors = cursor.fetchone()['errors']

    # Most used tools
    cursor.execute('''
        SELECT tool_server || '.' || tool_name as tool, COUNT(*) as count
        FROM mcp_transactions
        WHERE user_guid = ?
        GROUP BY tool_server, tool_name
        ORDER BY count DESC
        LIMIT 10
    ''', (user_guid,))
    top_tools = [{'tool': row['tool'], 'count': row['count']} for row in cursor.fetchall()]

    # Recent transactions by conversation
    cursor.execute('''
        SELECT c.name, COUNT(t.id) as count
        FROM mcp_transactions t
        JOIN conversations c ON t.conversation_id = c.id
        WHERE t.user_guid = ? AND c.user_guid = ?
        GROUP BY c.id
        ORDER BY count DESC
        LIMIT 10
    ''', (user_guid, user_guid))
    top_conversations = [{'conversation': row['name'], 'count': row['count']} for row in cursor.fetchall()]

    return {
        'total_transactions': total,
        'error_count': errors,
        'error_rate': (errors / total * 100) if total > 0 else 0,
        'top_tools': top_tools,
        'top_conversations': top_conversations
    }


def export_mcp_transactions_to_csv(conn: sqlite3.Connection, file_path: str,
                                   conversation_id: Optional[int] = None,
                                   user_guid: str = None) -> bool:
    """
    Export MCP transactions to CSV for Cyber Security audit.

    Args:
        conn: Database connection
        file_path: Path to save the CSV file
        conversation_id: Optional filter by conversation ID
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        import csv

        transactions = get_mcp_transactions(conn, conversation_id=conversation_id,
                                           user_guid=user_guid)

        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'id', 'transaction_timestamp', 'conversation_id', 'tool_server',
                'tool_name', 'user_prompt', 'tool_input', 'tool_response',
                'is_error', 'execution_time_ms'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for txn in transactions:
                writer.writerow({
                    'id': txn['id'],
                    'transaction_timestamp': txn['transaction_timestamp'],
                    'conversation_id': txn['conversation_id'],
                    'tool_server': txn['tool_server'],
                    'tool_name': txn['tool_name'],
                    'user_prompt': txn['user_prompt'][:100] + '...' if len(txn['user_prompt']) > 100 else txn['user_prompt'],
                    'tool_input': txn['tool_input'],
                    'tool_response': txn['tool_response'][:200] + '...' if len(txn['tool_response']) > 200 else txn['tool_response'],
                    'is_error': txn['is_error'],
                    'execution_time_ms': txn['execution_time_ms']
                })

        logging.info(f"Exported {len(transactions)} MCP transactions to {file_path}")
        return True

    except Exception as e:
        logging.error(f"Failed to export MCP transactions: {e}")
        return False


def get_enabled_mcp_servers(conn: sqlite3.Connection, conversation_id: int,
                            user_guid: str = None) -> List[str]:
    """
    Get list of enabled MCP servers for a conversation.
    If no records exist, all servers are considered enabled by default.

    Args:
        conn: Database connection
        conversation_id: Conversation ID
        user_guid: User GUID for multi-user support

    Returns:
        List of enabled server names (empty list if all disabled)
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT server_name
        FROM conversation_mcp_servers
        WHERE conversation_id = ? AND enabled = 1 AND user_guid = ?
    ''', (conversation_id, user_guid))

    return [row['server_name'] for row in cursor.fetchall()]


def is_mcp_server_enabled(conn: sqlite3.Connection, conversation_id: int,
                          server_name: str, user_guid: str = None) -> bool:
    """
    Check if an MCP server is enabled for a conversation.
    Returns True by default if no record exists (all servers enabled by default).

    Args:
        conn: Database connection
        conversation_id: Conversation ID
        server_name: Name of the MCP server
        user_guid: User GUID for multi-user support

    Returns:
        True if enabled, False if disabled
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT enabled
        FROM conversation_mcp_servers
        WHERE conversation_id = ? AND server_name = ? AND user_guid = ?
    ''', (conversation_id, server_name, user_guid))

    row = cursor.fetchone()
    if row is None:
        # No record exists, default to enabled
        return True
    return bool(row['enabled'])


def set_mcp_server_enabled(conn: sqlite3.Connection, conversation_id: int,
                           server_name: str, enabled: bool, user_guid: str = None) -> bool:
    """
    Enable or disable an MCP server for a conversation.

    Args:
        conn: Database connection
        conversation_id: Conversation ID
        server_name: Name of the MCP server
        enabled: True to enable, False to disable
        user_guid: User GUID for multi-user support

    Returns:
        True if successful, False otherwise
    """
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute('''
            INSERT INTO conversation_mcp_servers
                (conversation_id, server_name, enabled, updated_at, user_guid)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, server_name) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
        ''', (conversation_id, server_name, int(enabled), now, user_guid))

        conn.commit()
        logging.info(f"MCP server '{server_name}' {'enabled' if enabled else 'disabled'} for conversation {conversation_id}")
        return True

    except Exception as e:
        logging.error(f"Failed to update MCP server state: {e}")
        conn.rollback()
        return False


def get_all_mcp_server_states(conn: sqlite3.Connection, conversation_id: int,
                              all_server_names: List[str], user_guid: str = None) -> List[Dict]:
    """
    Get enabled/disabled state for all MCP servers.
    Servers with no record are considered enabled by default.

    Args:
        conn: Database connection
        conversation_id: Conversation ID
        all_server_names: List of all available MCP server names
        user_guid: User GUID for multi-user support

    Returns:
        List of dicts with 'server_name' and 'enabled' keys
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT server_name, enabled
        FROM conversation_mcp_servers
        WHERE conversation_id = ? AND user_guid = ?
    ''', (conversation_id, user_guid))

    # Create a dict of server states
    server_states = {row['server_name']: bool(row['enabled']) for row in cursor.fetchall()}

    # Build result list with all servers, defaulting to enabled
    result = []
    for server_name in all_server_names:
        result.append({
            'server_name': server_name,
            'enabled': server_states.get(server_name, True)  # Default to enabled
        })

    return result
