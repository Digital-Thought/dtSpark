"""
Daemon module for autonomous action execution.

Provides a background daemon process that:
- Runs autonomous actions on schedule
- Polls database for action changes (new, modified, deleted)
- Coordinates execution to prevent conflicts with web UI/CLI


"""

from .pid_file import PIDFile
from .daemon_manager import DaemonManager

__all__ = [
    'PIDFile',
    'DaemonManager',
]


def daemon_main():
    """
    Entry point for daemon CLI commands.

    Usage:
        dtSpark daemon start [--poll-interval N]
        dtSpark daemon stop
        dtSpark daemon status
        dtSpark daemon restart
    """
    import sys
    import time
    from pathlib import Path

    # Get settings for PID file location
    try:
        from dtPyAppFramework.settings import Settings
        settings = Settings()
        pid_file_path = settings.get('daemon.pid_file', './daemon.pid')
    except Exception:
        # Fallback if settings can't be loaded
        pid_file_path = './daemon.pid'

    manager = DaemonManager(pid_file_path=pid_file_path)

    # Handle direct module invocation: python -m dtSpark.daemon --run
    # In this case, --run is at sys.argv[1] instead of sys.argv[2]
    if len(sys.argv) >= 2 and sys.argv[1] == '--run':
        command = '--run'
        args = sys.argv[2:]
    elif len(sys.argv) < 3:
        print("Usage: dtSpark daemon {start|stop|status|restart} [options]")
        print("")
        print("Commands:")
        print("  start     Start the daemon in the background")
        print("  stop      Stop the running daemon")
        print("  status    Check if daemon is running")
        print("  restart   Restart the daemon")
        print("")
        print("Options for 'start':")
        print("  --poll-interval N   Seconds between database polls (default: 30)")
        print("  --foreground        Run in foreground (for debugging)")
        sys.exit(1)
    else:
        command = sys.argv[2]
        args = sys.argv[3:]

    if command == 'start':
        sys.exit(manager.start(args))
    elif command == 'stop':
        sys.exit(manager.stop())
    elif command == 'status':
        sys.exit(manager.status())
    elif command == 'restart':
        manager.stop()
        time.sleep(2)
        sys.exit(manager.start(args))
    elif command == '--run':
        _run_daemon_internal(args)
    else:
        print(f"Unknown command: {command}")
        print("Use: dtSpark daemon {start|stop|status|restart}")
        sys.exit(1)


def _run_daemon_internal(args):
    """
    Run the daemon application directly (called by start in background).

    Sets up sys.argv for AbstractApp and handles error logging for
    background mode debugging.

    Args:
        args: Additional command-line arguments for the daemon
    """
    import sys

    # Clean up sys.argv - AbstractApp expects program name and valid args
    sys.argv = ['dtSpark-daemon'] + args

    # Set up error logging to file for background mode debugging
    error_log_path = './daemon_error.log'

    try:
        from .daemon_app import DaemonApplication
        app = DaemonApplication()
        app.run()
    except Exception as e:
        import traceback
        error_msg = f"Daemon failed to start: {e}\n{traceback.format_exc()}"
        print(error_msg)
        # Also write to error log file for background mode
        try:
            with open(error_log_path, 'w') as f:
                f.write(error_msg)
        except Exception:
            pass
        sys.exit(1)
