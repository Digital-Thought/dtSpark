"""
PID file management for daemon process.

Provides functionality for:
- Writing and reading PID files
- Checking if a process is running
- Preventing multiple daemon instances


"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PIDFile:
    """
    Manages PID file for daemon process.

    Prevents multiple daemon instances and enables status checking.
    Works across Windows and Unix platforms.
    """

    def __init__(self, path: str):
        """
        Initialise the PID file manager.

        Args:
            path: Path to the PID file
        """
        self.path = Path(path)

    def write_pid(self, pid: Optional[int] = None):
        """
        Write current process PID to file.

        Args:
            pid: Process ID to write (default: current process)
        """
        if pid is None:
            pid = os.getpid()

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.path.write_text(str(pid))
        logger.info(f"PID file written: {self.path} (PID: {pid})")

    def read_pid(self) -> Optional[int]:
        """
        Read PID from file.

        Returns:
            Process ID if file exists and is valid, None otherwise
        """
        try:
            return int(self.path.read_text().strip())
        except FileNotFoundError:
            return None
        except ValueError:
            logger.warning(f"Invalid PID file contents: {self.path}")
            return None

    def remove(self):
        """Remove PID file."""
        try:
            self.path.unlink()
            logger.info(f"PID file removed: {self.path}")
        except FileNotFoundError:
            pass

    def is_running(self) -> bool:
        """
        Check if process with stored PID is running.

        Returns:
            True if process is running, False otherwise
        """
        pid = self.read_pid()
        if not pid:
            return False

        return self._is_process_running(pid)

    def _is_process_running(self, pid: int) -> bool:
        """
        Check if a process with the given PID is running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise
        """
        if sys.platform == 'win32':
            return self._is_process_running_windows(pid)
        else:
            return self._is_process_running_unix(pid)

    def _is_process_running_windows(self, pid: int) -> bool:
        """Check if process is running on Windows."""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32

            # Windows constant: PROCESS_QUERY_LIMITED_INFORMATION
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception as e:
            logger.debug(f"Error checking process on Windows: {e}")
            return False

    def _is_process_running_unix(self, pid: int) -> bool:
        """Check if process is running on Unix."""
        try:
            # Signal 0 doesn't actually send a signal, just checks if process exists
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission to signal it
            return True
        except OSError:
            return False

    def acquire(self) -> bool:
        """
        Attempt to acquire the PID file (atomic operation).

        Returns:
            True if acquired successfully, False if daemon already running
        """
        if self.is_running():
            existing_pid = self.read_pid()
            logger.warning(f"Daemon already running with PID {existing_pid}")
            return False

        # Clean up stale PID file if process is not running
        if self.path.exists():
            logger.info("Removing stale PID file")
            self.remove()

        self.write_pid()
        return True

    def release(self):
        """
        Release the PID file.

        Only removes if the current process holds it.
        """
        current_pid = os.getpid()
        stored_pid = self.read_pid()

        if stored_pid == current_pid:
            self.remove()
        else:
            logger.warning(
                f"PID file contains different PID (stored: {stored_pid}, current: {current_pid})"
            )
