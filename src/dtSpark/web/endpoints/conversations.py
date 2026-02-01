"""
Conversation management API endpoints.

Provides REST API for conversation operations:
- List conversations
- Create conversation
- Delete conversation
- Get conversation details


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


def parse_datetime(dt_value):
    """Parse datetime from string or return datetime object."""
    if dt_value is None:
        return None
    if isinstance(dt_value, datetime):
        return dt_value
    if isinstance(dt_value, str):
        # SQLite returns timestamps as strings
        try:
            return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return datetime.strptime(dt_value, '%Y-%m-%d %H:%M:%S.%f')
    return None


class ConversationSummary(BaseModel):
    """Summary information for a conversation."""
    id: int
    name: str
    model_id: str
    created_at: datetime
    message_count: int
    last_message_at: Optional[datetime]


class ConversationDetail(BaseModel):
    """Detailed information for a conversation."""
    id: int
    name: str
    model_id: str
    instructions: Optional[str]
    created_at: datetime
    message_count: int
    tokens_sent: int
    tokens_received: int
    total_tokens: int
    attached_files: List[str]
    warnings: Optional[List[str]] = None


@router.get("/conversations")
async def list_conversations(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> List[ConversationSummary]:
    """
    List all conversations.

    Returns:
        List of ConversationSummary objects
    """
    try:
        app_instance = request.app.state.app_instance

        # Get active conversations via conversation manager
        conversations = app_instance.conversation_manager.get_active_conversations()

        summaries = []
        for conv in conversations:
            summaries.append(
                ConversationSummary(
                    id=conv['id'],
                    name=conv['name'],
                    model_id=conv['model_id'],
                    created_at=parse_datetime(conv['created_at']),
                    message_count=conv.get('message_count', 0),
                    last_message_at=parse_datetime(conv.get('last_message_at')),
                )
            )

        return summaries

    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ConversationDetail:
    """
    Get detailed information about a conversation.

    Args:
        conversation_id: ID of the conversation

    Returns:
        ConversationDetail object
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        # Get conversation
        conv = database.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get attached files
        files = database.get_conversation_files(conversation_id)
        file_names = [f['filename'] for f in files]

        return ConversationDetail(
            id=conv['id'],
            name=conv['name'],
            model_id=conv['model_id'],
            instructions=conv.get('instructions'),
            created_at=parse_datetime(conv['created_at']),
            message_count=conv.get('message_count', 0),
            tokens_sent=conv.get('tokens_sent', 0),
            tokens_received=conv.get('tokens_received', 0),
            total_tokens=conv.get('tokens_sent', 0) + conv.get('tokens_received', 0),
            attached_files=file_names,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations")
async def create_conversation(
    request: Request,
    name: str = Form(...),
    model_id: str = Form(...),
    instructions: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    session_id: str = Depends(get_current_session),
) -> ConversationDetail:
    """
    Create a new conversation.

    Args:
        name: Conversation name
        model_id: Model ID to use
        instructions: Optional system instructions
        files: Optional file attachments
        session_id: Validated session ID

    Returns:
        ConversationDetail for the created conversation
    """
    try:
        # Check if new conversations are allowed
        if not getattr(request.app.state, 'new_conversations_allowed', True):
            raise HTTPException(
                status_code=403,
                detail="Creating new conversations is disabled by configuration"
            )

        app_instance = request.app.state.app_instance
        database = app_instance.database
        conversation_manager = app_instance.conversation_manager

        # Enforce mandatory model if configured
        mandatory_model = getattr(app_instance, 'configured_model_id', None)
        mandatory_provider = getattr(app_instance, 'configured_provider', None)
        if mandatory_model:
            model_id = mandatory_model
            logger.info(f"Mandatory model enforced: {model_id}"
                        f"{f' via {mandatory_provider}' if mandatory_provider else ''}")

        # Create conversation in database
        conversation_id = database.create_conversation(
            name=name,
            model_id=model_id,
            instructions=instructions,
        )

        # Load the conversation to set it as current
        conversation_manager.load_conversation(conversation_id)

        # Set the model from the conversation and update service references
        app_instance.llm_manager.set_model(model_id, mandatory_provider)
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()
        conversation_manager.update_service(app_instance.bedrock_service)

        # Handle file uploads if provided
        attached_file_paths = []
        upload_errors = []
        if files:
            temp_files = []
            try:
                # Save uploaded files to temporary locations
                for upload_file in files:
                    # Validate filename and extension
                    if not upload_file.filename:
                        upload_errors.append("File uploaded without a filename")
                        logger.warning("Received file upload without filename")
                        continue

                    # Extract file extension
                    suffix = os.path.splitext(upload_file.filename)[1]
                    if not suffix:
                        upload_errors.append(f"File '{upload_file.filename}' has no file extension")
                        logger.warning("File uploaded without extension")
                        continue

                    # Check if extension is supported (using FileManager's validation)
                    from dtSpark.files import FileManager
                    if suffix.lower() not in (FileManager.SUPPORTED_TEXT_FILES |
                                             FileManager.SUPPORTED_CODE_FILES |
                                             FileManager.SUPPORTED_DOCUMENT_FILES |
                                             FileManager.SUPPORTED_IMAGE_FILES):
                        upload_errors.append(f"File type '{suffix}' is not supported for '{upload_file.filename}'")
                        logger.warning("Unsupported file type uploaded")
                        continue

                    # Create temporary file with proper extension
                    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
                    os.close(temp_fd)

                    # Write uploaded content to temp file asynchronously
                    content = await upload_file.read()
                    await asyncio.to_thread(Path(temp_path).write_bytes, content)

                    temp_files.append(temp_path)
                    logger.info("Saved uploaded file to %s", temp_path)

                # Attach files using conversation manager
                if temp_files:
                    success = conversation_manager.attach_files(temp_files)
                    if success:
                        # Get attached files from database
                        db_files = database.get_conversation_files(conversation_id)
                        attached_file_paths = [f['file_path'] for f in db_files]
                        logger.info(f"Attached {len(attached_file_paths)} file(s) to conversation {conversation_id}")
                    else:
                        logger.warning("Some files failed to attach")

            except Exception as e:
                logger.error(f"Error processing file uploads: {e}")
                # Continue anyway - files are optional

            finally:
                # Clean up temporary files
                for temp_path in temp_files:
                    try:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                    except OSError:
                        pass

        # Get the created conversation details
        conv = database.get_conversation(conversation_id)

        return ConversationDetail(
            id=conv['id'],
            name=conv['name'],
            model_id=conv['model_id'],
            instructions=conv.get('instructions'),
            created_at=parse_datetime(conv['created_at']),
            message_count=0,
            tokens_sent=0,
            tokens_received=0,
            total_tokens=0,
            attached_files=attached_file_paths,
            warnings=upload_errors if upload_errors else None,
        )

    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Delete a conversation.

    Args:
        conversation_id: ID of the conversation to delete

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        # Check if conversation exists
        conv = database.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Delete conversation
        database.delete_conversation(conversation_id)

        return {
            "status": "success",
            "message": f"Conversation '{conv['name']}' deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Get available models and mandatory model configuration.

    Returns:
        Dictionary with models list and mandatory model info
    """
    try:
        app_instance = request.app.state.app_instance

        mandatory_model = getattr(app_instance, 'configured_model_id', None)
        mandatory_provider = getattr(app_instance, 'configured_provider', None)

        # Get available models from LLM manager
        all_models = app_instance.llm_manager.list_all_models()

        models = [
            {
                "id": model.get('id', model.get('name', 'unknown')),
                "name": model.get('name', 'Unknown'),
                "provider": model.get('provider', 'Unknown'),
                "model_maker": model.get('model_maker'),
            }
            for model in all_models
        ]

        # If mandatory model is set, filter to matching models only
        if mandatory_model:
            filtered = [
                m for m in models
                if m['id'] == mandatory_model
                or m['name'] == mandatory_model
            ]

            # Further filter by provider if mandatory_provider is set
            if mandatory_provider and filtered:
                provider_filtered = [
                    m for m in filtered
                    if m['provider'] == mandatory_provider
                ]
                if provider_filtered:
                    filtered = provider_filtered

            if filtered:
                models = filtered

        return {
            "models": models,
            "mandatory_model": mandatory_model,
            "mandatory_provider": mandatory_provider,
            "model_locked": mandatory_model is not None,
        }

    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
