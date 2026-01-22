"""
Web interface module for Spark.

This module provides a FastAPI-based web interface as an alternative to the CLI,
with authentication, session management, and real-time streaming via SSE.


"""

from .server import create_app, run_server, WebServer
from .auth import AuthManager
from .session import SessionManager

__all__ = [
    'create_app',
    'run_server',
    'WebServer',
    'AuthManager',
    'SessionManager',
]
