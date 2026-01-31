"""
Unit tests for web interface session management.

Tests the SessionManager class for session creation, validation, and timeout.

"""

import time
from datetime import timedelta
from dtSpark.web.session import SessionManager


class TestSessionManager:
    """Test cases for SessionManager."""

    def test_create_session(self):
        """Test that session creation works correctly."""
        manager = SessionManager()
        session_id = manager.create_session()

        assert session_id is not None
        assert len(session_id) == 64  # 32 bytes = 64 hex characters

    def test_validate_session_success(self):
        """Test that valid session is accepted."""
        manager = SessionManager()
        session_id = manager.create_session()

        assert manager.validate_session(session_id) is True

    def test_validate_session_wrong_id(self):
        """Test that wrong session ID is rejected."""
        manager = SessionManager()
        manager.create_session()

        assert manager.validate_session("wrong_session_id") is False

    def test_validate_session_not_exists(self):
        """Test that validation fails when no session exists."""
        manager = SessionManager()

        assert manager.validate_session("any_session_id") is False

    def test_session_timeout(self):
        """Test that session expires after timeout."""
        manager = SessionManager(timeout_minutes=0.01)  # 0.6 seconds
        session_id = manager.create_session()

        # Should be valid initially
        assert manager.validate_session(session_id) is True

        # Wait for timeout
        time.sleep(1)

        # Should be invalid after timeout
        assert manager.validate_session(session_id) is False

    def test_invalidate_session(self):
        """Test that session can be manually invalidated."""
        manager = SessionManager()
        session_id = manager.create_session()

        assert manager.validate_session(session_id) is True

        manager.invalidate_session()

        assert manager.validate_session(session_id) is False

    def test_session_replacement(self):
        """Test that new session replaces old one."""
        manager = SessionManager()
        session_id1 = manager.create_session()
        session_id2 = manager.create_session()

        # Old session should be invalid
        assert manager.validate_session(session_id1) is False

        # New session should be valid
        assert manager.validate_session(session_id2) is True

    def test_get_session_info(self):
        """Test retrieving session information."""
        manager = SessionManager()
        session_id = manager.create_session()

        info = manager.get_session_info()

        assert info is not None
        assert info['session_id'] == session_id
        assert info['timeout_minutes'] == 30
        assert info['is_expired'] is False

    def test_get_session_info_no_session(self):
        """Test that get_session_info returns None when no session exists."""
        manager = SessionManager()

        assert manager.get_session_info() is None

    def test_update_timeout(self):
        """Test updating session timeout."""
        manager = SessionManager(timeout_minutes=30)
        manager.update_timeout(60)

        info = manager.get_session_info()
        # Info will be None until a session is created
        assert info is None

        session_id = manager.create_session()
        info = manager.get_session_info()

        assert info['timeout_minutes'] == 60

    def test_get_remaining_time(self):
        """Test getting remaining session time."""
        manager = SessionManager(timeout_minutes=30)
        manager.create_session()

        remaining = manager.get_remaining_time()

        assert remaining is not None
        assert isinstance(remaining, timedelta)
        assert remaining.total_seconds() > 0

    def test_get_remaining_time_no_session(self):
        """Test that get_remaining_time returns None when no session exists."""
        manager = SessionManager()

        assert manager.get_remaining_time() is None

    def test_last_activity_update(self):
        """Test that last activity is updated on validation."""
        manager = SessionManager(timeout_minutes=30)
        session_id = manager.create_session()

        # Get initial remaining time
        initial_remaining = manager.get_remaining_time()

        # Wait a bit
        time.sleep(1)

        # Validate session (should update last activity)
        manager.validate_session(session_id)

        # Get new remaining time
        new_remaining = manager.get_remaining_time()

        # Remaining time should be approximately the same or slightly more
        # (because last_activity was updated)
        assert new_remaining >= initial_remaining
