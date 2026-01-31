"""
Daemon lifecycle manager.

Provides CLI commands for starting, stopping, and checking daemon status.


"""

import os
import sys
import time
import signal
import logging
import subprocess
from typing import List, Optional

from .pid_file import PIDFile

logger = logging.getLogger(__name__)


class DaemonManager:
    """
    Manages daemon lifecycle via CLI commands.

    Supports: start, stop, status, restart
    Works across Windows and Unix platforms.
    """

    def __init__(self, pid_file_path: str):
        """
        Initialise the daemon manager.

        Args:
            pid_file_path: Path to the PID file
        """
        self.pid_file = PIDFile(pid_file_path)

    def start(self, args: Optional[List[str]] = None) -> int:
        """
        Start the daemon process.

        Args:
            args: Additional arguments to pass to daemon

        Returns:
            0 on success, non-zero on failure
        """
        # Check if already running
        if self.pid_file.is_running():
            pid = self.pid_file.read_pid()
            print(f"Daemon already running (PID: {pid})")
            return 1

        # Check for --foreground flag
        foreground = False
        if args and '--foreground' in args:
            foreground = True
            args = [a for a in args if a != '--foreground']

        if foreground:
            # Run in foreground (for debugging)
            return self._run_foreground(args)
        else:
            # Start in background
            return self._start_background(args)

    def _run_foreground(self, args: Optional[List[str]] = None) -> int:
        """Run daemon in foreground mode."""
        print("Starting daemon in foreground mode...")
        print("Press Ctrl+C to stop")
        print("")

        # Import and run directly
        from .daemon_app import DaemonApplication
        app = DaemonApplication()

        # Clean up sys.argv - AbstractApp expects only arguments it recognises
        # Remove 'daemon', 'start', '--foreground' and keep only daemon-specific args
        clean_args = ['dtSpark-daemon']
        if args:
            clean_args.extend(args)
        sys.argv = clean_args

        try:
            app.run()
            return 0
        except KeyboardInterrupt:
            print("\nDaemon stopped by user")
            return 0
        except Exception as e:
            print(f"Daemon error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def _start_background(self, args: Optional[List[str]] = None) -> int:
        """Start daemon as a background process."""
        # Build command to run daemon
        daemon_cmd = [
            sys.executable,
            '-m', 'dtSpark.daemon',
            '--run'
        ]
        if args:
            daemon_cmd.extend(args)

        # Log file for daemon output (helps with debugging startup issues)
        daemon_log_path = str(self.pid_file.path) + '.log'

        try:
            # Open log file for daemon output
            log_file = open(daemon_log_path, 'w')

            if sys.platform == 'win32':
                # Windows: use CREATE_NEW_PROCESS_GROUP and DETACHED_PROCESS
                process = subprocess.Popen(
                    daemon_cmd,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        subprocess.DETACHED_PROCESS
                    ),
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                )
            else:
                # Unix: start new session
                process = subprocess.Popen(
                    daemon_cmd,
                    start_new_session=True,
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                )

            # Wait for daemon to start and write PID file
            # Poll with increasing intervals up to a maximum wait time
            max_wait = 10  # seconds
            waited = 0
            check_interval = 0.5

            while waited < max_wait:
                time.sleep(check_interval)
                waited += check_interval

                if self.pid_file.is_running():
                    pid = self.pid_file.read_pid()
                    print(f"Daemon started (PID: {pid})")
                    print(f"Daemon log: {daemon_log_path}")
                    return 0

            # Daemon didn't start within timeout
            print("Daemon failed to start. Check daemon log for details:")
            print(f"  {daemon_log_path}")
            # Try to show recent log content
            try:
                log_file.close()
                with open(daemon_log_path, 'r') as f:
                    content = f.read()
                    if content:
                        print("\nDaemon output:")
                        print(content[-2000:] if len(content) > 2000 else content)
            except Exception:
                pass
            return 1

        except Exception as e:
            print(f"Failed to start daemon: {e}")
            logger.error(f"Failed to start daemon: {e}", exc_info=True)
            return 1

    def stop(self, timeout: int = 30) -> int:
        """
        Stop the daemon gracefully.

        Args:
            timeout: Seconds to wait for graceful shutdown

        Returns:
            0 on success, non-zero on failure
        """
        pid = self.pid_file.read_pid()
        if not pid or not self.pid_file.is_running():
            print("Daemon is not running")
            # Clean up stale PID file if exists
            self.pid_file.remove()
            return 0

        print(f"Stopping daemon (PID: {pid})...")

        # Send termination signal
        signal_result = self._send_stop_signal(pid)
        if signal_result is not None:
            return signal_result

        # Wait for graceful shutdown
        for i in range(timeout):
            if not self.pid_file.is_running():
                print("Daemon stopped")
                self._cleanup_stop_file()
                return 0
            time.sleep(1)
            if (i + 1) % 5 == 0:
                print(f"Waiting for shutdown... ({i + 1}/{timeout}s)")

        # Process didn't stop gracefully - clean up and report
        self._cleanup_stop_file()
        return self._handle_stop_timeout(pid, timeout)

    def _send_stop_signal(self, pid: int) -> Optional[int]:
        """
        Send a termination signal to the daemon process.

        Args:
            pid: Process ID of the daemon

        Returns:
            Exit code if the stop completed immediately (success or failure),
            or None if the caller should wait for shutdown
        """
        try:
            if sys.platform == 'win32':
                self._send_stop_signal_windows(pid)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            print("Daemon process not found")
            self.pid_file.remove()
            return 0
        except PermissionError:
            print("Permission denied to stop daemon")
            return 1
        except Exception as e:
            print(f"Error stopping daemon: {e}")
            return 1
        return None

    def _send_stop_signal_windows(self, pid: int) -> None:
        """
        Send a stop signal on Windows using a signal file.

        Falls back to taskkill if the signal file cannot be created.

        Args:
            pid: Process ID of the daemon
        """
        stop_file = str(self.pid_file.path) + '.stop'
        try:
            with open(stop_file, 'w') as f:
                f.write(str(pid))
            print("Stop signal sent")
        except Exception as e:
            print(f"Failed to create stop signal: {e}")
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)

    def _handle_stop_timeout(self, pid: int, timeout: int) -> int:
        """
        Handle the case where the daemon did not stop within the timeout.

        Args:
            pid: Process ID of the daemon
            timeout: The timeout that was exceeded

        Returns:
            0 if force-terminated successfully, 1 otherwise
        """
        print(f"Daemon did not stop within {timeout} seconds")
        if sys.platform == 'win32':
            print("Forcing termination...")
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
            time.sleep(1)
            if not self.pid_file.is_running():
                print("Daemon terminated")
                return 0
        print("Consider using 'kill -9' manually if needed")
        return 1

    def _cleanup_stop_file(self):
        """Remove the stop signal file if it exists."""
        stop_file = str(self.pid_file.path) + '.stop'
        try:
            if os.path.exists(stop_file):
                os.remove(stop_file)
        except Exception:
            pass

    def status(self) -> int:
        """
        Check daemon status.

        Returns:
            0 if running, 1 if not running
        """
        pid = self.pid_file.read_pid()

        if pid and self.pid_file.is_running():
            print(f"Daemon is running (PID: {pid})")
            return 0
        else:
            print("Daemon is not running")
            # Clean up stale PID file if exists
            if pid:
                self.pid_file.remove()
            return 1

    def restart(self, args: Optional[List[str]] = None) -> int:
        """
        Restart the daemon.

        Args:
            args: Additional arguments to pass to daemon

        Returns:
            0 on success, non-zero on failure
        """
        # Stop if running
        if self.pid_file.is_running():
            stop_result = self.stop()
            if stop_result != 0:
                return stop_result
            time.sleep(2)

        # Start daemon
        return self.start(args)
