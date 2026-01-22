"""
Violation logger for Cyber Security audit trail.

This module handles database operations for logging prompt inspection violations,
enabling security monitoring, compliance, and incident response.


"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional


class ViolationLogger:
    """
    Logs prompt inspection violations to database for audit trail.
    """

    def __init__(self, database_connection: sqlite3.Connection, config: Dict):
        """
        Initialise violation logger.

        Args:
            database_connection: SQLite database connection
            config: Configuration dictionary
        """
        self.conn = database_connection
        self.config = config
        self.enabled = config.get('log_violations', True)
        self.alert_threshold = config.get('violation_threshold', 5)
        self.alert_enabled = config.get('alert_on_repeated_violations', True)

    def log_violation(self, user_guid: str, violation_types: List[str],
                     severity: str, prompt_snippet: str, detection_method: str,
                     action_taken: str, confidence_score: Optional[float] = None,
                     conversation_id: Optional[int] = None):
        """
        Log a prompt inspection violation to database.

        Args:
            user_guid: User's unique identifier
            violation_types: List of violation types detected
            severity: Severity level (none, low, medium, high, critical)
            prompt_snippet: First 500 characters of the violating prompt
            detection_method: How violation was detected (pattern, llm, hybrid)
            action_taken: Action taken (blocked, warned, sanitised, logged)
            confidence_score: Optional confidence score (0.0-1.0)
            conversation_id: Optional conversation ID
        """
        if not self.enabled:
            return

        try:
            cursor = self.conn.cursor()

            # Log each violation type separately for better analysis
            for violation_type in violation_types:
                cursor.execute('''
                    INSERT INTO prompt_inspection_violations
                    (user_guid, conversation_id, violation_type, severity,
                     prompt_snippet, detection_method, action_taken,
                     confidence_score, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_guid,
                    conversation_id,
                    violation_type,
                    severity,
                    prompt_snippet[:500],  # Ensure max 500 chars
                    detection_method,
                    action_taken,
                    confidence_score,
                    datetime.now()
                ))

            self.conn.commit()

            logging.info(f"Logged {len(violation_types)} violation(s) for user {user_guid}: {', '.join(violation_types)}")

            # Check if alert threshold reached
            if self.alert_enabled:
                self._check_alert_threshold(user_guid)

        except Exception as e:
            logging.error(f"Failed to log violation: {e}")
            self.conn.rollback()

    def get_user_violation_count(self, user_guid: str, hours: int = 24) -> int:
        """
        Get count of violations for a user in the last N hours.

        Args:
            user_guid: User's unique identifier
            hours: Number of hours to look back (default 24)

        Returns:
            Count of violations
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT COUNT(*)
                FROM prompt_inspection_violations
                WHERE user_guid = ?
                AND timestamp >= datetime('now', '-' || ? || ' hours')
            ''', (user_guid, hours))

            return cursor.fetchone()[0]

        except Exception as e:
            logging.error(f"Failed to get user violation count: {e}")
            return 0

    def get_user_violations(self, user_guid: str, limit: int = 50) -> List[Dict]:
        """
        Get recent violations for a user.

        Args:
            user_guid: User's unique identifier
            limit: Maximum number of records to return

        Returns:
            List of violation records
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT id, conversation_id, violation_type, severity,
                       prompt_snippet, detection_method, action_taken,
                       confidence_score, timestamp
                FROM prompt_inspection_violations
                WHERE user_guid = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (user_guid, limit))

            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'conversation_id': row[1],
                    'violation_type': row[2],
                    'severity': row[3],
                    'prompt_snippet': row[4],
                    'detection_method': row[5],
                    'action_taken': row[6],
                    'confidence_score': row[7],
                    'timestamp': row[8]
                }
                for row in rows
            ]

        except Exception as e:
            logging.error(f"Failed to get user violations: {e}")
            return []

    def get_violation_statistics(self, user_guid: Optional[str] = None,
                                 days: int = 30) -> Dict:
        """
        Get violation statistics for reporting and analysis.

        Args:
            user_guid: Optional user to filter by
            days: Number of days to analyse (default 30)

        Returns:
            Dictionary with statistics
        """
        try:
            cursor = self.conn.cursor()

            # Base query
            base_where = "WHERE timestamp >= datetime('now', '-' || ? || ' days')"
            params = [days]

            if user_guid:
                base_where += " AND user_guid = ?"
                params.append(user_guid)

            # Total violations
            cursor.execute(f'''
                SELECT COUNT(*)
                FROM prompt_inspection_violations
                {base_where}
            ''', params)
            total = cursor.fetchone()[0]

            # By severity
            cursor.execute(f'''
                SELECT severity, COUNT(*)
                FROM prompt_inspection_violations
                {base_where}
                GROUP BY severity
            ''', params)
            by_severity = {row[0]: row[1] for row in cursor.fetchall()}

            # By violation type
            cursor.execute(f'''
                SELECT violation_type, COUNT(*)
                FROM prompt_inspection_violations
                {base_where}
                GROUP BY violation_type
                ORDER BY COUNT(*) DESC
                LIMIT 10
            ''', params)
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # By action taken
            cursor.execute(f'''
                SELECT action_taken, COUNT(*)
                FROM prompt_inspection_violations
                {base_where}
                GROUP BY action_taken
            ''', params)
            by_action = {row[0]: row[1] for row in cursor.fetchall()}

            # Top users (if not filtered by user)
            top_users = []
            if not user_guid:
                cursor.execute(f'''
                    SELECT user_guid, COUNT(*) as count
                    FROM prompt_inspection_violations
                    {base_where}
                    GROUP BY user_guid
                    ORDER BY count DESC
                    LIMIT 10
                ''', params)
                top_users = [{'user_guid': row[0], 'count': row[1]} for row in cursor.fetchall()]

            return {
                'total': total,
                'by_severity': by_severity,
                'by_type': by_type,
                'by_action': by_action,
                'top_users': top_users,
                'days': days
            }

        except Exception as e:
            logging.error(f"Failed to get violation statistics: {e}")
            return {
                'total': 0,
                'by_severity': {},
                'by_type': {},
                'by_action': {},
                'top_users': [],
                'days': days
            }

    def _check_alert_threshold(self, user_guid: str):
        """
        Check if user has exceeded violation threshold and log alert.

        Args:
            user_guid: User's unique identifier
        """
        count = self.get_user_violation_count(user_guid, hours=24)

        if count >= self.alert_threshold:
            logging.warning(
                f"SECURITY ALERT: User {user_guid} has {count} violations in the last 24 hours "
                f"(threshold: {self.alert_threshold})"
            )

    def export_violations_to_csv(self, file_path: str, user_guid: Optional[str] = None,
                                days: int = 30) -> bool:
        """
        Export violations to CSV for audit and analysis.

        Args:
            file_path: Path to output CSV file
            user_guid: Optional user to filter by
            days: Number of days to export (default 30)

        Returns:
            True if successful
        """
        try:
            import csv

            cursor = self.conn.cursor()

            # Build query
            base_where = "WHERE timestamp >= datetime('now', '-' || ? || ' days')"
            params = [days]

            if user_guid:
                base_where += " AND user_guid = ?"
                params.append(user_guid)

            cursor.execute(f'''
                SELECT user_guid, conversation_id, violation_type, severity,
                       prompt_snippet, detection_method, action_taken,
                       confidence_score, timestamp
                FROM prompt_inspection_violations
                {base_where}
                ORDER BY timestamp DESC
            ''', params)

            rows = cursor.fetchall()

            # Write to CSV
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow([
                    'User GUID', 'Conversation ID', 'Violation Type', 'Severity',
                    'Prompt Snippet', 'Detection Method', 'Action Taken',
                    'Confidence Score', 'Timestamp'
                ])

                # Data rows
                writer.writerows(rows)

            logging.info(f"Exported {len(rows)} violation records to {file_path}")
            return True

        except Exception as e:
            logging.error(f"Failed to export violations to CSV: {e}")
            return False

    def cleanup_old_violations(self, days: int = 90):
        """
        Clean up old violation records.

        Args:
            days: Delete records older than this many days (default 90)
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                DELETE FROM prompt_inspection_violations
                WHERE timestamp < datetime('now', '-' || ? || ' days')
            ''', (days,))

            deleted = cursor.rowcount
            self.conn.commit()

            logging.info(f"Cleaned up {deleted} old violation records (older than {days} days)")

        except Exception as e:
            logging.error(f"Failed to cleanup old violations: {e}")
            self.conn.rollback()
