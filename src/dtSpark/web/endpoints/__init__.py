"""
API endpoints for the web interface.


"""

from .main_menu import router as main_menu_router
from .conversations import router as conversations_router
from .chat import router as chat_router
from .streaming import router as streaming_router

__all__ = [
    'main_menu_router',
    'conversations_router',
    'chat_router',
    'streaming_router',
]
