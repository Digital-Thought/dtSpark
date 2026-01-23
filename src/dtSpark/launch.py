"""
Application entry point for Spark.

This launcher handles:
- Main application (CLI or Web interface)
- Daemon mode for autonomous action execution

Usage:
    dtSpark              # Run main application
    dtSpark daemon start # Start daemon in background
    dtSpark daemon stop  # Stop daemon
    dtSpark daemon status # Check daemon status
"""

import sys

def main():
    """
    Main entry point that routes to appropriate handler.

    Routes daemon commands to the daemon module, otherwise runs
    the main application.
    """
    # Check for daemon commands
    if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
        from dtSpark.daemon import daemon_main
        daemon_main()
    else:
        # Run main application
        from dtSpark.core.application import main as app_main
        app_main()


# Entry point for console_scripts
if __name__ == "__main__":
    main()
