"""
Chat API endpoints.

Provides REST API for chat operations:
- Load conversation
- Send message
- Execute commands (history, info, attach, etc.)
- Export conversation


"""

import asyncio
import logging
import tempfile
import os
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..dependencies import get_current_session


logger = logging.getLogger(__name__)

router = APIRouter()


class Message(BaseModel):
    """Chat message."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime
    tokens: Optional[int] = None


class ChatHistory(BaseModel):
    """Chat history for a conversation."""
    conversation_id: int
    conversation_name: str
    messages: List[Message]


class CommandResponse(BaseModel):
    """Response from a chat command."""
    command: str
    status: str
    data: Optional[dict] = None
    message: Optional[str] = None


@router.get("/chat/{conversation_id}/history")
async def get_chat_history(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ChatHistory:
    """
    Get chat history for a conversation.

    Args:
        conversation_id: ID of the conversation

    Returns:
        ChatHistory with all messages
    """
    try:
        app_instance = request.app.state.app_instance
        conversation_manager = app_instance.conversation_manager
        database = app_instance.database

        # Load the conversation (will set it as current)
        conversation_manager.load_conversation(conversation_id)

        # Get conversation name from database
        conv = database.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv_name = conv['name']

        # Set the model from the conversation and update service references
        model_id = conv['model_id']
        app_instance.llm_manager.set_model(model_id)
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()
        conversation_manager.update_service(app_instance.bedrock_service)

        # Get conversation history from conversation manager
        history = conversation_manager.get_conversation_history(include_rolled_up=False)

        # Format messages
        messages = []
        for msg in history:
            messages.append(
                Message(
                    role=msg['role'],
                    content=msg['content'],
                    timestamp=msg['timestamp'],
                    tokens=msg.get('tokens'),
                )
            )

        return ChatHistory(
            conversation_id=conversation_id,
            conversation_name=conv_name,
            messages=messages,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chat history for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/message")
async def send_message(
    conversation_id: int,
    request: Request,
    message: str = Form(...),
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Send a message in a conversation.

    Args:
        conversation_id: ID of the conversation
        message: Message text to send

    Returns:
        Response with assistant's reply
    """
    try:
        app_instance = request.app.state.app_instance
        conversation_manager = app_instance.conversation_manager

        # Load conversation in conversation manager
        conversation_manager.load_conversation(conversation_id)

        # Set the model from the conversation and update service references
        conv_info = conversation_manager.get_current_conversation_info()
        model_id = conv_info['model_id']
        app_instance.llm_manager.set_model(model_id)
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()
        conversation_manager.update_service(app_instance.bedrock_service)

        # Send message (this will handle tool use, streaming, etc.)
        response = conversation_manager.send_message(message)

        return {
            "status": "success",
            "response": response,
        }

    except Exception as e:
        logger.error(f"Error sending message in conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/info")
async def command_info(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Execute 'info' command to get conversation information.

    Args:
        conversation_id: ID of the conversation

    Returns:
        CommandResponse with conversation info
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database
        conversation_manager = app_instance.conversation_manager

        # Get conversation
        conv = database.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get model usage breakdown
        model_usage = database.get_model_usage_breakdown(conversation_id)

        # Get attached files
        files = database.get_conversation_files(conversation_id)

        # Get MCP server states (if available)
        mcp_servers = []
        if app_instance.mcp_manager:
            # Load conversation to set current_conversation_id
            conversation_manager.load_conversation(conversation_id)
            mcp_servers = conversation_manager.get_mcp_server_states()

        # Handle created_at - could be datetime or string from database
        created_at = conv['created_at']
        if hasattr(created_at, 'isoformat'):
            created_at_str = created_at.isoformat()
        else:
            created_at_str = str(created_at)

        # Get rollup/compaction settings
        rollup_info = {}
        try:
            model_id = conv.get('model_id', '')
            provider = app_instance.llm_manager.get_active_provider() if app_instance.llm_manager else 'unknown'

            # Get context limits from resolver
            context_limits = conversation_manager.context_limit_resolver.get_context_limits(model_id, provider)
            context_window = context_limits.get('context_window', 8192)
            max_output = context_limits.get('max_output', 4096)

            # Get compaction thresholds from compactor
            compaction_threshold = conversation_manager.context_compactor.compaction_threshold
            emergency_threshold = conversation_manager.context_compactor.emergency_threshold

            # Calculate threshold token counts
            compaction_trigger_tokens = int(context_window * compaction_threshold)
            emergency_trigger_tokens = int(context_window * emergency_threshold)

            # Get current token count
            current_tokens = conv.get('tokens_sent', 0) + conv.get('tokens_received', 0)
            context_usage_percent = (current_tokens / context_window * 100) if context_window > 0 else 0

            rollup_info = {
                "context_window": context_window,
                "max_output": max_output,
                "compaction_threshold": compaction_threshold,
                "compaction_trigger_tokens": compaction_trigger_tokens,
                "emergency_threshold": emergency_threshold,
                "emergency_trigger_tokens": emergency_trigger_tokens,
                "current_tokens": current_tokens,
                "context_usage_percent": round(context_usage_percent, 1),
                "provider": provider,
            }
        except Exception as e:
            logger.warning(f"Could not get rollup info: {e}")
            rollup_info = {"error": str(e)}

        return CommandResponse(
            command="info",
            status="success",
            data={
                "conversation": {
                    "id": conv['id'],
                    "name": conv['name'],
                    "model_id": conv['model_id'],
                    "created_at": created_at_str,
                    "tokens_sent": conv.get('tokens_sent', 0),
                    "tokens_received": conv.get('tokens_received', 0),
                    "total_tokens": conv.get('tokens_sent', 0) + conv.get('tokens_received', 0),
                    "instructions": conv.get('instructions', ''),
                },
                "model_usage": model_usage,
                "files": [f['filename'] for f in files],
                "attached_files": [
                    {
                        "id": f['id'],
                        "filename": f['filename'],
                        "size_bytes": f.get('size_bytes', 0),
                        "mime_type": f.get('mime_type', 'application/octet-stream'),
                    }
                    for f in files
                ],
                "mcp_servers": mcp_servers,
                "rollup_settings": rollup_info,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting info for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/attach")
async def command_attach(
    conversation_id: int,
    request: Request,
    files: List[UploadFile] = File(...),
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Execute 'attach' command to attach files to conversation.

    Args:
        conversation_id: ID of the conversation
        files: Files to attach

    Returns:
        CommandResponse with status
    """
    try:
        app_instance = request.app.state.app_instance
        conversation_manager = app_instance.conversation_manager
        database = app_instance.database

        # Load conversation
        conversation_manager.load_conversation(conversation_id)

        # Set the model from the conversation and update service references
        conv = database.get_conversation(conversation_id)
        if conv:
            app_instance.llm_manager.set_model(conv['model_id'])
            app_instance.bedrock_service = app_instance.llm_manager.get_active_service()
            conversation_manager.update_service(app_instance.bedrock_service)

        # Save uploaded files to temporary locations and attach
        temp_files = []
        attached_filenames = []

        try:
            # Save uploaded files to temporary locations
            for upload_file in files:
                # Create temporary file
                suffix = os.path.splitext(upload_file.filename)[1]
                temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
                os.close(temp_fd)

                # Write uploaded content to temp file asynchronously
                content = await upload_file.read()
                await asyncio.to_thread(Path(temp_path).write_bytes, content)

                temp_files.append(temp_path)
                attached_filenames.append(upload_file.filename)
                logger.info("Saved uploaded file to %s", temp_path)

            # Attach files using conversation manager
            if temp_files:
                success = conversation_manager.attach_files(temp_files)

                if success:
                    logger.info(f"Successfully attached {len(temp_files)} file(s) to conversation {conversation_id}")
                    return CommandResponse(
                        command="attach",
                        status="success",
                        message=f"Attached {len(attached_filenames)} file(s)",
                        data={"files": attached_filenames},
                    )
                else:
                    logger.warning("Some files failed to attach")
                    return CommandResponse(
                        command="attach",
                        status="partial",
                        message="Some files failed to attach",
                        data={"files": attached_filenames},
                    )
            else:
                return CommandResponse(
                    command="attach",
                    status="error",
                    message="No files provided",
                )

        except Exception as e:
            logger.error(f"Error processing file uploads: {e}")
            raise

        finally:
            # Clean up temporary files
            for temp_path in temp_files:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError:
                    pass

    except Exception as e:
        logger.error(f"Error attaching files to conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/export")
async def command_export(
    conversation_id: int,
    request: Request,
    format: str = Form(...),  # 'markdown', 'html', or 'csv'
    include_tools: bool = Form(True),
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Execute 'export' command to export conversation.

    Args:
        conversation_id: ID of the conversation
        format: Export format ('markdown', 'html', or 'csv')
        include_tools: Whether to include tool use details

    Returns:
        Export data
    """
    try:
        app_instance = request.app.state.app_instance

        # Load conversation
        app_instance.conversation_manager.load_conversation(conversation_id)

        # Export conversation
        if format == 'markdown':
            content = app_instance.conversation_manager.export_to_markdown(
                include_tool_details=include_tools
            )
        elif format == 'html':
            content = app_instance.conversation_manager.export_to_html(
                include_tool_details=include_tools
            )
        elif format == 'csv':
            content = app_instance.conversation_manager.export_to_csv(
                include_tool_details=include_tools
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid export format")

        return {
            "status": "success",
            "format": format,
            "content": content,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/changemodel")
async def command_change_model(
    conversation_id: int,
    request: Request,
    model_id: str = Form(...),
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Execute 'changemodel' command to change conversation model.

    Args:
        conversation_id: ID of the conversation
        model_id: New model ID

    Returns:
        CommandResponse with status
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if model is locked via configuration
        mandatory_model = getattr(app_instance, 'configured_model_id', None)
        if mandatory_model:
            return CommandResponse(
                command="changemodel",
                status="error",
                message=f"Model changing is disabled - model is locked to '{mandatory_model}' via configuration",
                data=None,
            )

        # Load conversation
        app_instance.conversation_manager.load_conversation(conversation_id)

        # Change model
        app_instance.conversation_manager.change_model(model_id)

        return CommandResponse(
            command="changemodel",
            status="success",
            message=f"Model changed to {model_id}",
            data={"model_id": model_id},
        )

    except Exception as e:
        logger.error(f"Error changing model for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/{conversation_id}/command/mcpaudit")
async def command_mcp_audit(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Execute 'mcpaudit' command to get MCP transaction audit log.

    Args:
        conversation_id: ID of the conversation

    Returns:
        CommandResponse with audit log
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        # Get MCP transactions for this conversation
        transactions = database.get_mcp_transactions(conversation_id=conversation_id)

        return CommandResponse(
            command="mcpaudit",
            status="success",
            data={"transactions": transactions},
        )

    except Exception as e:
        logger.error(f"Error getting MCP audit for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/{conversation_id}/command/mcpservers")
async def command_mcp_servers(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Execute 'mcpservers' command to get MCP server states.

    Args:
        conversation_id: ID of the conversation

    Returns:
        CommandResponse with MCP server states
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        # Get all server names from MCP manager
        all_server_names = []
        if app_instance.mcp_manager and hasattr(app_instance.mcp_manager, 'clients'):
            all_server_names = list(app_instance.mcp_manager.clients.keys())

        # Get MCP server states for this conversation
        servers = database.get_all_mcp_server_states(conversation_id, all_server_names)

        return CommandResponse(
            command="mcpservers",
            status="success",
            data={"servers": servers},
        )

    except Exception as e:
        logger.error(f"Error getting MCP servers for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/mcpservers/toggle")
async def toggle_mcp_server(
    conversation_id: int,
    request: Request,
    server_name: str = Form(...),
    enabled: bool = Form(...),
    session_id: str = Depends(get_current_session),
) -> CommandResponse:
    """
    Toggle MCP server enabled/disabled state.

    Args:
        conversation_id: ID of the conversation
        server_name: Name of the server to toggle
        enabled: New enabled state

    Returns:
        CommandResponse with status
    """
    try:
        app_instance = request.app.state.app_instance

        # Load conversation
        app_instance.conversation_manager.load_conversation(conversation_id)

        # Toggle server
        app_instance.conversation_manager.set_mcp_server_enabled(server_name, enabled)

        return CommandResponse(
            command="mcpservers",
            status="success",
            message=f"Server '{server_name}' {'enabled' if enabled else 'disabled'}",
            data={
                "server_name": server_name,
                "enabled": enabled,
            },
        )

    except Exception as e:
        logger.error(f"Error toggling MCP server for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/instructions")
async def update_instructions(
    request: Request,
    conversation_id: int,
    instructions: str = Form(""),
    session_id: str = Depends(get_current_session),
):
    """
    Update conversation instructions/system prompt.

    Args:
        request: FastAPI request
        conversation_id: ID of the conversation
        instructions: New instructions text (empty to clear)
        session_id: Current session ID

    Returns:
        CommandResponse with status
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if conversation is predefined
        if app_instance.database.is_conversation_predefined(conversation_id):
            return CommandResponse(
                command="instructions",
                status="error",
                message="Cannot modify instructions for predefined conversations",
                data=None,
            )

        # Set conversation context if needed
        if app_instance.conversation_manager.current_conversation_id != conversation_id:
            app_instance.conversation_manager.load_conversation(conversation_id)

        # Update instructions (None to clear, or the text)
        new_instructions = instructions.strip() if instructions.strip() else None
        success = app_instance.conversation_manager.update_instructions(new_instructions)

        if success:
            return CommandResponse(
                command="instructions",
                status="success",
                message="Instructions updated successfully",
                data={"instructions": new_instructions},
            )
        else:
            return CommandResponse(
                command="instructions",
                status="error",
                message="Failed to update instructions",
                data=None,
            )

    except Exception as e:
        logger.error(f"Error updating instructions for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/{conversation_id}/command/deletefiles")
async def delete_files(
    request: Request,
    conversation_id: int,
    session_id: str = Depends(get_current_session),
):
    """
    Delete attached files from a conversation.

    Args:
        request: FastAPI request
        conversation_id: ID of the conversation
        session_id: Current session ID

    Returns:
        CommandResponse with deletion status
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if conversation is predefined
        if app_instance.database.is_conversation_predefined(conversation_id):
            return CommandResponse(
                command="deletefiles",
                status="error",
                message="Cannot delete files from predefined conversations",
                data=None,
            )

        # Parse JSON body for file_ids
        body = await request.json()
        file_ids = body.get('file_ids', [])

        if not file_ids:
            return CommandResponse(
                command="deletefiles",
                status="error",
                message="No file IDs provided",
                data=None,
            )

        # Delete each file
        deleted_count = 0
        failed_ids = []

        for file_id in file_ids:
            try:
                if app_instance.database.delete_file(file_id):
                    deleted_count += 1
                else:
                    failed_ids.append(file_id)
            except Exception as e:
                logger.warning(f"Failed to delete file {file_id}: {e}")
                failed_ids.append(file_id)

        if deleted_count > 0:
            return CommandResponse(
                command="deletefiles",
                status="success",
                message=f"Deleted {deleted_count} file(s)",
                data={
                    "deleted_count": deleted_count,
                    "failed_ids": failed_ids,
                },
            )
        else:
            return CommandResponse(
                command="deletefiles",
                status="error",
                message="Failed to delete files",
                data={"failed_ids": failed_ids},
            )

    except Exception as e:
        logger.error(f"Error deleting files for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/permission/respond")
async def respond_to_permission_request(
    request: Request,
    request_id: str = Form(...),
    response: str = Form(...),
    session_id: str = Depends(get_current_session)
):
    """
    Submit a response to a tool permission request.

    Args:
        request: FastAPI request
        request_id: The permission request ID
        response: User's response ('once', 'allowed', 'denied', or 'cancel')
        session_id: Current session ID

    Returns:
        CommandResponse with status
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if web interface is available
        if not hasattr(app_instance.conversation_manager, 'web_interface') or not app_instance.conversation_manager.web_interface:
            raise HTTPException(status_code=400, detail="Web interface not initialized")

        # Submit the response
        success = app_instance.conversation_manager.web_interface.submit_permission_response(
            request_id, None if response == 'cancel' else response
        )

        if not success:
            raise HTTPException(status_code=404, detail="Permission request not found")

        return CommandResponse(
            command="permission_response",
            status="success",
            message=f"Permission response submitted: {response}",
            data={
                "request_id": request_id,
                "response": response,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting permission response: {e}")
        raise HTTPException(status_code=500, detail=str(e))
