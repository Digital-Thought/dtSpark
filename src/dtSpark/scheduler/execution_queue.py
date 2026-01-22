"""
Action Execution Queue module.

Provides thread-safe sequential execution queue for autonomous actions.


"""

import logging
import queue
import threading
from typing import Callable, Any, Optional
from dataclasses import dataclass


@dataclass
class ActionTask:
    """Represents an action execution task."""
    action_id: int
    user_guid: str
    is_manual: bool = False


class ActionExecutionQueue:
    """
    Thread-safe queue for sequential action execution.

    Ensures actions are processed one at a time to prevent
    resource contention and ensure predictable behaviour.
    """

    def __init__(self, executor_func: Callable[[int, str, bool], Any]):
        """
        Initialise the execution queue.

        Args:
            executor_func: Function(action_id, user_guid, is_manual) to execute actions
        """
        self.executor_func = executor_func
        self._queue: queue.Queue[Optional[ActionTask]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._shutdown_event = threading.Event()

        logging.info("ActionExecutionQueue initialised")

    def start(self):
        """
        Start the queue worker thread.
        """
        if self._is_running:
            logging.warning("Execution queue already running")
            return

        self._shutdown_event.clear()
        self._is_running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="ActionExecutionWorker",
            daemon=True
        )
        self._worker_thread.start()
        logging.info("Action execution queue started")

    def stop(self, timeout: float = 30.0):
        """
        Stop the queue worker gracefully.

        Args:
            timeout: Maximum time to wait for current task to complete
        """
        if not self._is_running:
            return

        logging.info("Stopping action execution queue...")
        self._is_running = False
        self._shutdown_event.set()

        # Put a sentinel value to unblock the queue
        self._queue.put(None)

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logging.warning("Worker thread did not stop within timeout")

        logging.info("Action execution queue stopped")

    def is_running(self) -> bool:
        """Check if the queue is running."""
        return self._is_running

    def enqueue(self, action_id: int, user_guid: str, is_manual: bool = False):
        """
        Add an action to the execution queue.

        Args:
            action_id: ID of the action to execute
            user_guid: User GUID for execution context
            is_manual: Whether this is a manual "Run Now" execution
        """
        if not self._is_running:
            logging.warning("Cannot enqueue action: queue not running")
            return

        task = ActionTask(action_id=action_id, user_guid=user_guid, is_manual=is_manual)
        self._queue.put(task)
        logging.info(f"Enqueued action {action_id} (manual: {is_manual})")

    def get_queue_size(self) -> int:
        """Get the number of pending tasks in the queue."""
        return self._queue.qsize()

    def _worker_loop(self):
        """
        Worker loop that processes tasks from the queue.
        """
        logging.info("Action execution worker started")

        while self._is_running or not self._queue.empty():
            try:
                # Wait for a task with timeout to allow shutdown checks
                try:
                    task = self._queue.get(timeout=1.0)
                except queue.Empty:
                    # Check if we should shut down
                    if self._shutdown_event.is_set():
                        break
                    continue

                # Check for sentinel value
                if task is None:
                    logging.debug("Received shutdown sentinel")
                    break

                # Execute the task
                self._execute_task(task)
                self._queue.task_done()

            except Exception as e:
                logging.error(f"Error in worker loop: {e}")

        logging.info("Action execution worker stopped")

    def _execute_task(self, task: ActionTask):
        """
        Execute a single task.

        Args:
            task: The task to execute
        """
        try:
            logging.info(f"Executing action {task.action_id} (manual: {task.is_manual})")
            self.executor_func(task.action_id, task.user_guid, task.is_manual)
            logging.info(f"Completed action {task.action_id}")

        except Exception as e:
            logging.error(f"Failed to execute action {task.action_id}: {e}")
            # Don't re-raise - we want to continue processing other tasks
