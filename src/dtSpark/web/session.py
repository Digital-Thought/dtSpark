"""
Session manager for web interface.

Implements single-session authentication with configurable timeout.

"""

import logging
import secrets
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages user sessions for the web interface.

    Features:
    - Single active session at a time (new login invalidates old session)
    - Configurable inactivity timeout
    - Secure session ID generation
    - Automatic session expiration
    """

    def __init__(self, timeout_minutes: int = 30):
        """
        Initialise the session manager.

        Args:
            timeout_minutes: Minutes of inactivity before session expires
        """
        self._timeout_minutes = timeout_minutes
        self._session_id: Optional[str] = None
        self._last_activity: Optional[datetime] = None
        self._created_at: Optional[datetime] = None

    def create_session(self) -> str:
        """
        Create a new session.

        If a session already exists, it is invalidated and replaced.

        Returns:
            The new session ID

        Note:
            Session IDs are cryptographically secure random strings.
        """
        # Generate secure random session ID (32 bytes = 64 hex characters)
        self._session_id = secrets.token_hex(32)
        self._created_at = datetime.now()
        self._last_activity = datetime.now()

        return self._session_id

    def validate_session(self, session_id: str) -> bool:
        """
        Validate a session ID and check if it's expired.

        Args:
            session_id: The session ID to validate

        Returns:
            True if session is valid and not expired, False otherwise

        Note:
            If validation succeeds, the last activity timestamp is updated.
        """
        # Check if session exists
        if self._session_id is None:
            logger.debug("Session validation failed: no active session exists")
            return False

        # Check if session ID matches
        if session_id != self._session_id:
            logger.debug(f"Session validation failed: ID mismatch (provided: {session_id[:8]}..., "
                        f"expected: {self._session_id[:8]}...)")
            return False

        # Check if session has expired
        if self._is_expired():
            logger.info(f"Session expired after {self._timeout_minutes} minutes of inactivity")
            self._invalidate_session()
            return False

        # Update last activity timestamp
        self._last_activity = datetime.now()

        return True

    def invalidate_session(self):
        """
        Explicitly invalidate the current session.

        Used when user logs out or when session is replaced.
        """
        self._invalidate_session()

    def get_session_info(self) -> Optional[dict]:
        """
        Get information about the current session.

        Returns:
            Dictionary with session information, or None if no active session
        """
        if self._session_id is None:
            return None

        return {
            'session_id': self._session_id,
            'created_at': self._created_at,
            'last_activity': self._last_activity,
            'timeout_minutes': self._timeout_minutes,
            'is_expired': self._is_expired(),
        }

    def update_timeout(self, timeout_minutes: int):
        """
        Update the session timeout duration.

        Args:
            timeout_minutes: New timeout duration in minutes
        """
        self._timeout_minutes = timeout_minutes

    def get_remaining_time(self) -> Optional[timedelta]:
        """
        Get the remaining time before session expires.

        Returns:
            Timedelta representing remaining time, or None if no active session
        """
        if self._session_id is None or self._last_activity is None:
            return None

        expiry_time = self._last_activity + timedelta(minutes=self._timeout_minutes)
        remaining = expiry_time - datetime.now()

        return remaining if remaining.total_seconds() > 0 else timedelta(0)

    def _is_expired(self) -> bool:
        """
        Check if the current session has expired.

        Returns:
            True if session is expired, False otherwise

        Note:
            If timeout_minutes is 0 or negative, session never expires.
        """
        if self._last_activity is None:
            return True

        # Timeout of 0 or less means session never expires
        if self._timeout_minutes <= 0:
            return False

        expiry_time = self._last_activity + timedelta(minutes=self._timeout_minutes)
        return datetime.now() > expiry_time

    def _invalidate_session(self):
        """Internal method to clear session data."""
        self._session_id = None
        self._created_at = None
        self._last_activity = None
