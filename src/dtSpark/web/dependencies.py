"""
Shared dependencies for web endpoints.


"""

from typing import Optional
from fastapi import Cookie, HTTPException, Request


async def get_current_session(
    request: Request,
    session_id: Optional[str] = Cookie(default=None)
) -> str:
    """
    Dependency to validate the current session.

    Args:
        request: FastAPI request object
        session_id: Session ID from cookie

    Returns:
        Valid session ID

    Raises:
        HTTPException: If session is invalid or expired
    """
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get session manager from app state
    session_manager = request.app.state.session_manager

    if not session_manager.validate_session(session_id):
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return session_id
