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
            emitted_security_requests = set()  # Track which security requests we've already emitted

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

                    # Check for pending security confirmation requests
                    security_request = conversation_manager.web_interface.get_pending_security_request()
                    if security_request:
                        request_id = security_request['request_id']
                        if request_id not in emitted_security_requests:
                            emitted_security_requests.add(request_id)
                            yield {
                                "event": "security_confirmation",
                                "data": json.dumps({
                                    "request_id": request_id,
                                    "severity": security_request.get('severity', 'warning'),
                                    "issues": security_request.get('issues', []),
                                    "explanation": security_request.get('explanation', ''),
                                    "patterns": security_request.get('patterns', []),
                                    "detection_method": security_request.get('detection_method', 'unknown'),
                                }),
                            }

                    # Check for compaction status updates
                    compaction_status = conversation_manager.web_interface.get_compaction_status()
                    if compaction_status:
                        yield {
                            "event": "compaction_status",
                            "data": json.dumps({
                                "status": compaction_status.get('status'),
                                "message": compaction_status.get('message'),
                                "original_tokens": compaction_status.get('original_tokens'),
                                "compacted_tokens": compaction_status.get('compacted_tokens'),
                                "reduction_pct": compaction_status.get('reduction_pct'),
                                "elapsed_time": compaction_status.get('elapsed_time'),
                            }),
                        }

                    # Check for conflict resolution requests (orphan tool_results)
                    conflict_request = conversation_manager.web_interface.get_pending_conflict_request()
                    if conflict_request:
                        request_id = conflict_request['request_id']
                        if request_id not in emitted_permission_requests:  # Reuse this set to track
                            emitted_permission_requests.add(request_id)
                            yield {
                                "event": "conflict_resolution",
                                "data": json.dumps({
                                    "request_id": request_id,
                                    "tool_use_id": conflict_request.get('tool_use_id'),
                                    "error_message": conflict_request.get('error_message'),
                                    "conversation_id": conversation_id,
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
                                    elif block.get('type') == 'server_tool_use':
                                        # Emit web search start event
                                        yield {
                                            "event": "web_search_start",
                                            "data": json.dumps({
                                                "tool_name": block.get('name', 'web_search'),
                                                "tool_use_id": block.get('id'),
                                                "input": block.get('input', {}),
                                            }),
                                        }
                                    elif block.get('type') == 'web_search_tool_result':
                                        # Emit web search results event
                                        content = block.get('content', [])
                                        # Extract source information from results
                                        sources = []
                                        if isinstance(content, list):
                                            for result in content:
                                                if isinstance(result, dict) and result.get('type') == 'web_search_result':
                                                    sources.append({
                                                        'url': result.get('url', ''),
                                                        'title': result.get('title', ''),
                                                        'page_age': result.get('page_age', ''),
                                                    })
                                        yield {
                                            "event": "web_search_results",
                                            "data": json.dumps({
                                                "tool_use_id": block.get('tool_use_id'),
                                                "sources": sources,
                                                "source_count": len(sources),
                                            }),
                                        }
                        except ValueError:
                            pass

                last_message_count = len(current_messages)

                # Small delay before next poll
                await asyncio.sleep(0.2)

            # Thread finished - do one final poll to catch any messages we missed
            try:
                final_messages = database.get_conversation_messages(conversation_id)
                for msg in final_messages[last_message_count:]:
                    msg_id = msg['id']
                    if msg_id in emitted_messages:
                        continue

                    emitted_messages.add(msg_id)
                    role = msg['role']
                    content = msg['content']

                    # Check for web search blocks in assistant messages
                    if role == 'assistant' and content.strip().startswith('['):
                        try:
                            blocks = json.loads(content)
                            if isinstance(blocks, list):
                                for block in blocks:
                                    if block.get('type') == 'text' and block.get('text'):
                                        # Skip text blocks here - they'll be in the final response
                                        pass
                                    elif block.get('type') == 'server_tool_use':
                                        yield {
                                            "event": "web_search_start",
                                            "data": json.dumps({
                                                "tool_name": block.get('name', 'web_search'),
                                                "tool_use_id": block.get('id'),
                                                "input": block.get('input', {}),
                                            }),
                                        }
                                    elif block.get('type') == 'web_search_tool_result':
                                        content_list = block.get('content', [])
                                        sources = []
                                        if isinstance(content_list, list):
                                            for result in content_list:
                                                if isinstance(result, dict) and result.get('type') == 'web_search_result':
                                                    sources.append({
                                                        'url': result.get('url', ''),
                                                        'title': result.get('title', ''),
                                                        'page_age': result.get('page_age', ''),
                                                    })
                                        yield {
                                            "event": "web_search_results",
                                            "data": json.dumps({
                                                "tool_use_id": block.get('tool_use_id'),
                                                "sources": sources,
                                                "source_count": len(sources),
                                            }),
                                        }
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                logger.warning(f"Final poll failed: {e}")

            # Check result
            if result_container['error']:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": result_container['error'],
                        "error_type": "Exception",
                        "suggestion": "Check the application logs for more details.",
                    }),
                }
            elif result_container['response']:
                response = result_container['response']

                # Check if response is a structured error (dict with _error flag)
                if isinstance(response, dict) and response.get('_error'):
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "message": response.get('error_message', 'An error occurred'),
                            "error_type": response.get('error_type', 'Unknown'),
                            "error_code": response.get('error_code', 'Unknown'),
                            "suggestion": response.get('suggestion', ''),
                            "retries_attempted": response.get('retries_attempted', 0),
                        }),
                    }
                else:
                    # Emit final response
                    yield {
                        "event": "response",
                        "data": json.dumps({
                            "type": "text",
                            "content": response,
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
                        "message": "No response received from the model",
                        "error_type": "NoResponse",
                        "suggestion": "The model did not respond. Try again or check your connection.",
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
    web_search_active: bool = False,
    session_id: str = Depends(get_current_session),
):
    """
    SSE endpoint for streaming chat responses.

    Args:
        request: FastAPI request object
        conversation_id: Conversation ID
        message: User message to send
        web_search_active: Whether web search should be used for this request
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

    # Set per-request web search toggle
    conversation_manager.set_web_search_active(web_search_active)

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
