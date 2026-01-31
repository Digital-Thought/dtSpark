"""
Web interface adapter for ConversationManager.

This module provides a web-compatible interface for handling tool permissions
and other interactive prompts via HTTP/SSE.


"""

import logging
import queue
import uuid
from typing import Optional, Dict


logger = logging.getLogger(__name__)


class WebInterface:
    """
    Web interface adapter for handling interactive prompts.

    This class acts as a bridge between ConversationManager and the web UI,
    managing permission requests and responses via queues.
    """

    def __init__(self):
        """Initialise the web interface."""
        self._permission_requests = {}  # request_id -> request_data
        self._permission_responses = {}  # request_id -> response
        self._pending_request_id = None

    def prompt_tool_permission(self, tool_name: str, tool_description: str = None) -> Optional[str]:
        """
        Request tool permission from web user.

        This method:
        1. Creates a permission request with a unique ID
        2. Stores it for the web UI to retrieve
        3. Waits for a response (with timeout)
        4. Returns the user's choice

        Args:
            tool_name: Name of the tool
            tool_description: Optional description of the tool

        Returns:
            'allowed' if user grants permission for all future uses
            'denied' if user denies this and all future uses
            'once' if user grants permission for this time only
            None if user cancelled or timeout
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Store the permission request
        self._permission_requests[request_id] = {
            'tool_name': tool_name,
            'tool_description': tool_description,
            'status': 'pending'
        }

        # Store the current pending request ID
        self._pending_request_id = request_id

        logger.info(f"Web permission request created: {request_id} for tool: {tool_name}")

        # Wait for response (with timeout)
        # In a real implementation, this would use asyncio or threading.Event
        # For now, we implement a simple polling mechanism
        import time
        timeout_seconds = 300  # 5 minutes timeout
        poll_interval = 0.5  # Poll every 0.5 seconds
        elapsed = 0

        while elapsed < timeout_seconds:
            if request_id in self._permission_responses:
                response = self._permission_responses[request_id]

                # Clean up
                del self._permission_requests[request_id]
                del self._permission_responses[request_id]
                if self._pending_request_id == request_id:
                    self._pending_request_id = None

                logger.info(f"Web permission response received for {request_id}: {response}")
                return response

            time.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout - clean up and return None
        logger.warning(f"Web permission request {request_id} timed out after {timeout_seconds}s")
        if request_id in self._permission_requests:
            del self._permission_requests[request_id]
        if self._pending_request_id == request_id:
            self._pending_request_id = None

        return None

    def get_pending_permission_request(self) -> Optional[Dict]:
        """
        Get the current pending permission request if any.

        Returns:
            Dictionary with request_id, tool_name, tool_description, or None
        """
        if self._pending_request_id and self._pending_request_id in self._permission_requests:
            return {
                'request_id': self._pending_request_id,
                **self._permission_requests[self._pending_request_id]
            }
        return None

    def submit_permission_response(self, request_id: str, response: str) -> bool:
        """
        Submit a response to a pending permission request.

        Args:
            request_id: The request ID
            response: User's response ('once', 'allowed', 'denied', or None for cancel)

        Returns:
            True if response was accepted, False if request not found
        """
        if request_id not in self._permission_requests:
            logger.warning("Permission response submitted for unknown request")
            return False

        # Store the response
        self._permission_responses[request_id] = response

        # Update request status
        self._permission_requests[request_id]['status'] = 'responded'

        logger.info("Permission response submitted and recorded")
        return True
