"""
Action change monitor for daemon process.

Polls the database for changes to autonomous actions and notifies
the scheduler when actions are added, modified, or deleted.


"""

import logging
import threading
from typing import Dict, Callable, Optional, List

logger = logging.getLogger(__name__)


class ActionChangeMonitor:
    """
    Monitors database for autonomous action changes.

    Uses version column to detect modifications efficiently.
    Notifies scheduler when actions are added, modified, or deleted.
    """

    def __init__(
        self,
        database,
        user_guid: str,
        poll_interval: int = 30,
        on_action_added: Optional[Callable[[Dict], None]] = None,
        on_action_modified: Optional[Callable[[Dict], None]] = None,
        on_action_deleted: Optional[Callable[[int], None]] = None,
    ):
        """
        Initialise the action change monitor.

        Args:
            database: Database instance with autonomous_actions methods
            user_guid: User GUID for filtering actions
            poll_interval: Seconds between database polls
            on_action_added: Callback when new action detected
            on_action_modified: Callback when action modified
            on_action_deleted: Callback when action deleted
        """
        self.database = database
        self.user_guid = user_guid
        self.poll_interval = poll_interval

        # Callbacks
        self.on_action_added = on_action_added
        self.on_action_modified = on_action_modified
        self.on_action_deleted = on_action_deleted

        # State tracking
        self._known_actions: Dict[int, int] = {}  # action_id -> version
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._is_running = False

    def start(self):
        """Start the monitoring thread."""
        if self._is_running:
            print("Action monitor already running")
            logger.warning("Action monitor already running")
            return

        self._stop_event.clear()
        self._is_running = True

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="ActionChangeMonitor",
            daemon=True
        )
        self._monitor_thread.start()
        print(f"Action monitor started (poll interval: {self.poll_interval}s)")
        logger.info(f"Action monitor started (poll interval: {self.poll_interval}s)")

    def stop(self, timeout: int = 10):
        """
        Stop the monitoring thread.

        Args:
            timeout: Seconds to wait for thread to stop
        """
        if not self._is_running:
            return

        logger.info("Stopping action monitor...")
        self._stop_event.set()

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=timeout)
            if self._monitor_thread.is_alive():
                logger.warning("Action monitor thread did not stop gracefully")

        self._is_running = False
        logger.info("Action monitor stopped")

    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._is_running

    def load_initial_state(self):
        """
        Load initial action state from database.

        Should be called before starting the monitor to establish baseline.
        """
        try:
            print(f"Loading initial action state for user_guid: {self.user_guid}")
            actions = self._get_actions_with_version()
            for action in actions:
                action_id = action['id']
                version = action.get('version', 1)
                self._known_actions[action_id] = version

            print(f"Loaded initial state: {len(self._known_actions)} actions")
            logger.info(f"Loaded initial state: {len(self._known_actions)} actions")
        except Exception as e:
            print(f"Failed to load initial action state: {e}")
            logger.error(f"Failed to load initial action state: {e}")

    def _monitor_loop(self):
        """Main monitoring loop."""
        # Load initial state on first run
        if not self._known_actions:
            self.load_initial_state()

        poll_count = 0
        while not self._stop_event.is_set():
            try:
                poll_count += 1
                logger.debug(f"Action monitor poll #{poll_count}")
                self._check_for_changes()
            except Exception as e:
                logger.error(f"Error in action monitor: {e}", exc_info=True)

            # Wait for next poll or stop signal
            self._stop_event.wait(timeout=self.poll_interval)

    def _check_for_changes(self):
        """Check database for action changes."""
        try:
            current_actions = self._get_actions_with_version()
            logger.info(f"Action monitor: found {len(current_actions)} actions in database (tracking {len(self._known_actions)})")
        except Exception as e:
            logger.error(f"Failed to query actions: {e}")
            return

        current_ids = set()

        for action in current_actions:
            action_id = action['id']
            version = action.get('version', 1)
            current_ids.add(action_id)

            if action_id not in self._known_actions:
                self._handle_new_action(action, version)
            elif self._known_actions[action_id] != version:
                self._handle_modified_action(action, version)

        # Check for deleted actions
        self._handle_deleted_actions(current_ids)

    def _handle_new_action(self, action: Dict, version: int) -> None:
        """
        Process a newly detected action.

        Args:
            action: The action dictionary from the database
            version: The action's version number
        """
        action_id = action['id']
        logger.info(f"New action detected: {action['name']} (ID: {action_id})")
        self._known_actions[action_id] = version
        if self.on_action_added:
            try:
                self.on_action_added(action)
            except Exception as e:
                logger.error(f"Error in on_action_added callback: {e}")

    def _handle_modified_action(self, action: Dict, version: int) -> None:
        """
        Process a modified action.

        Args:
            action: The action dictionary from the database
            version: The action's new version number
        """
        action_id = action['id']
        old_version = self._known_actions[action_id]
        logger.info(f"Action modified: {action['name']} (ID: {action_id}, v{old_version} -> v{version})")
        self._known_actions[action_id] = version
        if self.on_action_modified:
            try:
                self.on_action_modified(action)
            except Exception as e:
                logger.error(f"Error in on_action_modified callback: {e}")

    def _handle_deleted_actions(self, current_ids: set) -> None:
        """
        Process actions that have been deleted from the database.

        Args:
            current_ids: Set of action IDs currently present in the database
        """
        deleted_ids = set(self._known_actions.keys()) - current_ids
        for action_id in deleted_ids:
            logger.info(f"Action deleted: ID {action_id}")
            del self._known_actions[action_id]
            if self.on_action_deleted:
                try:
                    self.on_action_deleted(action_id)
                except Exception as e:
                    logger.error(f"Error in on_action_deleted callback: {e}")

    def _get_actions_with_version(self) -> List[Dict]:
        """Get all actions with version information."""
        from dtSpark.database.autonomous_actions import get_all_actions_with_version
        return get_all_actions_with_version(
            conn=self.database.conn,
            user_guid=self.user_guid,
            include_disabled=False  # Only monitor enabled actions
        )

    def force_refresh(self):
        """
        Force an immediate check for changes.

        Useful after making changes locally to detect them immediately.
        """
        logger.debug("Force refresh triggered")
        self._check_for_changes()

    def get_known_action_ids(self) -> List[int]:
        """Get list of known action IDs."""
        return list(self._known_actions.keys())

    def get_known_action_version(self, action_id: int) -> Optional[int]:
        """Get the known version of an action."""
        return self._known_actions.get(action_id)
