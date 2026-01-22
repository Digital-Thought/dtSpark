"""
Module entry point for daemon.

Allows running the daemon with: python -m dtSpark.daemon
"""

from . import daemon_main

if __name__ == "__main__":
    daemon_main()
