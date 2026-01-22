"""
Execution coordinator for preventing duplicate action runs.

Provides functionality for:
- Acquiring execution locks on actions
- Preventing concurrent execution by daemon and UI
- Cleaning up stale locks from crashed processes


"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ActionLockedError(Exception):
    """Raised when an action is locked by another process."""

    def __init__(self, action_id: int, locked_by: str, message: str = None):
        self.action_id = action_id
        self.locked_by = locked_by
        self.message = message or f"Action {action_id} is locked by {locked_by}"
        super().__init__(self.message)


class ExecutionCoordinator:
    """
    Coordinates action execution to prevent conflicts.

    Uses database locking mechanism to prevent duplicate execution
    when both daemon and UI try to run the same action.
    """

    def __init__(
        self,
        database,
        process_id: str,
        user_guid: str,
        lock_timeout_seconds: int = 300
    ):
        """
        Initialise the execution coordinator.

        Args:
            database: Database instance with autonomous_actions methods
            process_id: Unique identifier for this process (daemon_id or session_id)
            user_guid: User GUID for database operations
            lock_timeout_seconds: Seconds after which a lock is considered stale
        """
        self.database = database
        self.process_id = process_id
        self.user_guid = user_guid
        self.lock_timeout_seconds = lock_timeout_seconds

    def try_acquire_lock(self, action_id: int) -> bool:
        """
        Attempt to acquire an execution lock for an action.

        Args:
            action_id: ID of the action to lock

        Returns:
            True if lock acquired, False if another process holds it
        """
        # First, clear any stale locks
        self._clear_stale_locks()

        # Try to acquire lock
        from dtSpark.database.autonomous_actions import try_lock_action
        success = try_lock_action(
            conn=self.database.conn,
            action_id=action_id,
            locked_by=self.process_id,
            user_guid=self.user_guid
        )

        if success:
            logger.debug(f"Acquired lock on action {action_id}")
        else:
            logger.debug(f"Failed to acquire lock on action {action_id}")

        return success

    def release_lock(self, action_id: int) -> bool:
        """
        Release an execution lock for an action.

        Args:
            action_id: ID of the action to unlock

        Returns:
            True if unlocked successfully, False otherwise
        """
        from dtSpark.database.autonomous_actions import unlock_action
        success = unlock_action(
            conn=self.database.conn,
            action_id=action_id,
            locked_by=self.process_id,
            user_guid=self.user_guid
        )

        if success:
            logger.debug(f"Released lock on action {action_id}")
        else:
            logger.warning(f"Failed to release lock on action {action_id}")

        return success

    def is_action_locked(self, action_id: int) -> bool:
        """
        Check if an action is currently locked by another process.

        Args:
            action_id: ID of the action to check

        Returns:
            True if locked by another process, False otherwise
        """
        from dtSpark.database.autonomous_actions import get_action_lock_info
        lock_info = get_action_lock_info(
            conn=self.database.conn,
            action_id=action_id,
            user_guid=self.user_guid
        )

        if not lock_info or not lock_info.get('locked_by'):
            return False

        # Not locked by another process if we hold the lock
        if lock_info['locked_by'] == self.process_id:
            return False

        return True

    def get_lock_holder(self, action_id: int) -> Optional[str]:
        """
        Get the identifier of the process holding the lock.

        Args:
            action_id: ID of the action

        Returns:
            Process identifier if locked, None otherwise
        """
        from dtSpark.database.autonomous_actions import get_action_lock_info
        lock_info = get_action_lock_info(
            conn=self.database.conn,
            action_id=action_id,
            user_guid=self.user_guid
        )

        if lock_info:
            return lock_info.get('locked_by')
        return None

    def _clear_stale_locks(self):
        """Clear locks that are older than the timeout."""
        from dtSpark.database.autonomous_actions import clear_stale_locks
        clear_stale_locks(
            conn=self.database.conn,
            lock_timeout_seconds=self.lock_timeout_seconds,
            user_guid=self.user_guid
        )

    def execute_with_lock(self, action_id: int, execute_func, *args, **kwargs):
        """
        Execute a function while holding an action lock.

        Args:
            action_id: ID of the action to lock
            execute_func: Function to execute
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Result of execute_func

        Raises:
            ActionLockedError: If action is locked by another process
        """
        if not self.try_acquire_lock(action_id):
            lock_holder = self.get_lock_holder(action_id)
            raise ActionLockedError(
                action_id=action_id,
                locked_by=lock_holder or "unknown",
                message=f"Action {action_id} is currently being executed by another process"
            )

        try:
            return execute_func(*args, **kwargs)
        finally:
            self.release_lock(action_id)
