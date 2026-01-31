"""
SSE streaming endpoints for real-time updates.

Provides Server-Sent Events streaming for model responses, tool execution,
and progress updates.


"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ..dependencies import get_current_session


logger = logging.getLogger(__name__)

router = APIRouter()


class StreamingManager:
    """
    Manages Server-Sent Events streams for real-time updates.

    Handles streaming for:
    - Model response text (token by token)
    - Tool execution progress
    - Token limit warnings
    - Progress bars and status updates
    """

    def __init__(self):
        """Initialise the streaming manager."""
        self._active_streams = {}

    async def stream_chat_response(
        self,
        conversation_manager,
        message: str,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a chat response with real-time updates including tool calls.

        Args:
            conversation_manager: ConversationManager instance
            message: User message to send

        Yields:
            Dictionary events for SSE streaming
        """
        import concurrent.futures
        import threading

        try:
            # Send initial "processing" event
            yield {
                "event": "status",
                "data": json.dumps({
                    "type": "processing",
                    "message": "",
                }),
            }

            # Get the current conversation ID and track starting message count
            conversation_id = conversation_manager.current_conversation_id
            database = conversation_manager.database

            # Get initial message count (before sending)
            try:
                initial_messages = database.get_conversation_messages(conversation_id)
                last_message_count = len(initial_messages)
            except Exception as e:
                logger.error(f"Failed to get initial message count: {e}")
                last_message_count = 0

            # Result container for the thread
            result_container = {'response': None, 'error': None, 'done': False}

            # Run send_message in a background thread
            def run_send_message():
                try:
                    result_container['response'] = conversation_manager.send_message(message)
                except Exception as e:
                    import traceback
                    logger.error(f"Error in send_message thread: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    result_container['error'] = str(e)
                finally:
                    result_container['done'] = True

            # Start the thread
            thread = threading.Thread(target=run_send_message)
            thread.start()

            # Poll for new messages while thread is running
            emitted_messages = set()  # Track which message IDs we've already emitted
            emitted_permission_requests = set()  # Track which permission requests we've already emitted

            while not result_container['done']:
                # Check for pending permission requests (if web interface is available)
                if hasattr(conversation_manager, 'web_interface') and conversation_manager.web_interface:
                    pending_request = conversation_manager.web_interface.get_pending_permission_request()
                    if pending_request:
                        request_id = pending_request['request_id']
                        if request_id not in emitted_permission_requests:
                            emitted_permission_requests.add(request_id)
                            yield {
                                "event": "permission_request",
                                "data": json.dumps({
                                    "request_id": request_id,
                                    "tool_name": pending_request['tool_name'],
                                    "tool_description": pending_request.get('tool_description'),
                                }),
                            }

                # Check for new messages
                try:
                    current_messages = database.get_conversation_messages(conversation_id)
                except Exception as e:
                    # Database might be locked, retry on next poll
                    logger.warning(f"Database query failed during polling: {e}")
                    await asyncio.sleep(0.2)
                    continue

                # Find new messages since last check
                for msg in current_messages[last_message_count:]:
                    msg_id = msg['id']
                    if msg_id in emitted_messages:
                        continue

                    emitted_messages.add(msg_id)
                    role = msg['role']
                    content = msg['content']

                    # Check message type and emit appropriate event
                    if content.startswith('[TOOL_RESULTS]'):
                        # Tool results
                        try:
                            json_content = content.replace('[TOOL_RESULTS]', '').strip()
                            results = json.loads(json_content)
                            for result in results:
                                yield {
                                    "event": "tool_complete",
                                    "data": json.dumps({
                                        "tool_use_id": result.get('tool_use_id', 'unknown'),
                                        "content": result.get('content', ''),
                                    }),
                                }
                        except ValueError:
                            pass

                    elif role == 'assistant' and content.strip().startswith('['):
                        # Check if this is a tool call message (may contain text + tool_use)
                        try:
                            blocks = json.loads(content)
                            if isinstance(blocks, list):
                                for block in blocks:
                                    if block.get('type') == 'text' and block.get('text'):
                                        # Emit text content that appears with tool calls
                                        yield {
                                            "event": "response",
                                            "data": json.dumps({
                                                "type": "text",
                                                "content": block.get('text'),
                                                "final": False,
                                            }),
                                        }
                                    elif block.get('type') == 'tool_use':
                                        # Emit tool call
                                        yield {
                                            "event": "tool_start",
                                            "data": json.dumps({
                                                "tool_name": block.get('name'),
                                                "input": block.get('input', {}),
                                            }),
                                        }
                        except ValueError:
                            pass

                last_message_count = len(current_messages)

                # Small delay before next poll
                await asyncio.sleep(0.2)

            # Thread finished, check result
            if result_container['error']:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": result_container['error'],
                    }),
                }
            elif result_container['response']:
                # Emit final response
                yield {
                    "event": "response",
                    "data": json.dumps({
                        "type": "text",
                        "content": result_container['response'],
                        "final": True,
                    }),
                }

                # Send completion event
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "status": "success",
                    }),
                }
            else:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": "Failed to get response from model",
                    }),
                }

        except Exception as e:
            logger.error(f"Error in stream_chat_response: {e}")
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": str(e),
                }),
            }

    async def stream_tool_execution(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream tool execution progress.

        Args:
            tool_name: Name of the tool being executed
            tool_input: Tool input parameters

        Yields:
            Dictionary events for SSE streaming
        """
        try:
            # Send start event
            yield {
                "event": "tool_start",
                "data": json.dumps({
                    "tool_name": tool_name,
                    "input": tool_input,
                }),
            }

            # Simulate tool execution
            # In actual implementation, this would integrate with MCP manager
            await asyncio.sleep(0.5)

            # Send completion event
            yield {
                "event": "tool_complete",
                "data": json.dumps({
                    "tool_name": tool_name,
                    "status": "success",
                }),
            }

        except Exception as e:
            logger.error(f"Error in stream_tool_execution: {e}")
            yield {
                "event": "tool_error",
                "data": json.dumps({
                    "tool_name": tool_name,
                    "error": str(e),
                }),
            }

    async def stream_progress(
        self,
        task_name: str,
        total_steps: int,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream progress updates.

        Args:
            task_name: Name of the task
            total_steps: Total number of steps

        Yields:
            Dictionary events for SSE streaming
        """
        try:
            for step in range(total_steps + 1):
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "task": task_name,
                        "step": step,
                        "total": total_steps,
                        "percentage": int((step / total_steps) * 100) if total_steps > 0 else 100,
                    }),
                }
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Error in stream_progress: {e}")
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": str(e),
                }),
            }


# Global streaming manager instance
streaming_manager = StreamingManager()


@router.get("/stream/chat")
async def stream_chat(
    request: Request,
    conversation_id: int,
    message: str,
    session_id: str = Depends(get_current_session),
):
    """
    SSE endpoint for streaming chat responses.

    Args:
        request: FastAPI request object
        conversation_id: Conversation ID
        message: User message to send
        session_id: Validated session ID from dependency

    Returns:
        EventSourceResponse with SSE stream
    """
    # Get app instance
    app_instance = request.app.state.app_instance
    conversation_manager = app_instance.conversation_manager

    # Load conversation and set model with proper provider routing
    conversation_manager.load_conversation(conversation_id)
    conv = app_instance.database.get_conversation(conversation_id)
    if conv:
        app_instance.llm_manager.set_model(conv['model_id'])
        # Update service references so conversation manager uses the correct provider
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()
        conversation_manager.update_service(app_instance.bedrock_service)

    # Create streaming generator
    async def event_generator():
        async for event in streaming_manager.stream_chat_response(
            conversation_manager=conversation_manager,
            message=message,
        ):
            yield event

    return EventSourceResponse(event_generator())


@router.get("/stream/tool")
async def stream_tool(
    request: Request,
    tool_name: str,
    session_id: str = Depends(get_current_session),
):
    """
    SSE endpoint for streaming tool execution.

    Args:
        request: FastAPI request object
        tool_name: Name of the tool to execute
        session_id: Validated session ID from dependency

    Returns:
        EventSourceResponse with SSE stream
    """
    # Create streaming generator
    async def event_generator():
        async for event in streaming_manager.stream_tool_execution(
            tool_name=tool_name,
            tool_input={},  # Placeholder
        ):
            yield event

    return EventSourceResponse(event_generator())


@router.get("/stream/progress")
async def stream_progress(
    request: Request,
    task_name: str,
    total_steps: int = 10,
    session_id: str = Depends(get_current_session),
):
    """
    SSE endpoint for streaming progress updates.

    Args:
        request: FastAPI request object
        task_name: Name of the task
        total_steps: Total number of steps
        session_id: Validated session ID from dependency

    Returns:
        EventSourceResponse with SSE stream
    """
    # Create streaming generator
    async def event_generator():
        async for event in streaming_manager.stream_progress(
            task_name=task_name,
            total_steps=total_steps,
        ):
            yield event

    return EventSourceResponse(event_generator())
