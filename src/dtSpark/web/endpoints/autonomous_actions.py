"""
Autonomous Actions API endpoints.

Provides REST API for managing autonomous actions:
- List, create, update, delete actions
- View action runs and export results
- Enable/disable actions
- Trigger manual runs


"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..dependencies import get_current_session

# Error message constants
_ERR_ACTION_NOT_FOUND = "Action not found"


logger = logging.getLogger(__name__)

router = APIRouter()


def parse_datetime(dt_value):
    """Parse datetime from string or return datetime object."""
    if dt_value is None:
        return None
    if isinstance(dt_value, datetime):
        return dt_value
    if isinstance(dt_value, str):
        try:
            return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            try:
                return datetime.strptime(dt_value, '%Y-%m-%d %H:%M:%S.%f')
            except (ValueError, TypeError):
                return None
    return None


# Pydantic Models

class ScheduleConfig(BaseModel):
    """Schedule configuration for an action."""
    run_date: Optional[str] = None  # For one_off
    cron_expression: Optional[str] = None  # For recurring


class ToolPermission(BaseModel):
    """Tool permission for an action."""
    tool_name: str
    server_name: Optional[str] = None
    permission_state: str = "allowed"


class ActionCreate(BaseModel):
    """Request model for creating an action."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    action_prompt: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    schedule_type: str = Field(..., pattern="^(one_off|recurring)$")
    schedule_config: ScheduleConfig
    context_mode: str = Field(default="fresh", pattern="^(fresh|cumulative)$")
    max_failures: int = Field(default=3, ge=1, le=100)
    tool_permissions: Optional[List[ToolPermission]] = None


class ActionUpdate(BaseModel):
    """Request model for updating an action."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    action_prompt: Optional[str] = Field(None, min_length=1)
    schedule_type: Optional[str] = Field(None, pattern="^(one_off|recurring)$")
    schedule_config: Optional[ScheduleConfig] = None
    context_mode: Optional[str] = Field(None, pattern="^(fresh|cumulative)$")
    max_failures: Optional[int] = Field(None, ge=1, le=100)


class ActionSummary(BaseModel):
    """Summary information for an action."""
    id: int
    name: str
    description: str
    model_id: str
    schedule_type: str
    schedule_config: dict
    context_mode: str
    is_enabled: bool
    failure_count: int
    max_failures: int
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime


class ActionDetail(BaseModel):
    """Detailed information for an action."""
    id: int
    name: str
    description: str
    action_prompt: str
    model_id: str
    schedule_type: str
    schedule_config: dict
    context_mode: str
    is_enabled: bool
    failure_count: int
    max_failures: int
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    tool_permissions: List[dict]


class ActionRunSummary(BaseModel):
    """Summary information for an action run."""
    id: int
    action_id: int
    action_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    input_tokens: int
    output_tokens: int


class ActionRunDetail(BaseModel):
    """Detailed information for an action run."""
    id: int
    action_id: int
    action_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    result_text: Optional[str]
    result_html: Optional[str]
    error_message: Optional[str]
    input_tokens: int
    output_tokens: int


# Endpoints

@router.get("/actions")
async def list_actions(
    request: Request,
    include_disabled: bool = Query(True, description="Include disabled actions"),
    session_id: str = Depends(get_current_session),
) -> List[ActionSummary]:
    """
    List all autonomous actions.

    Args:
        include_disabled: Whether to include disabled actions

    Returns:
        List of ActionSummary objects
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        actions = database.get_all_actions(include_disabled=include_disabled)

        return [
            ActionSummary(
                id=action['id'],
                name=action['name'],
                description=action['description'],
                model_id=action['model_id'],
                schedule_type=action['schedule_type'],
                schedule_config=action.get('schedule_config', {}),
                context_mode=action['context_mode'],
                is_enabled=action['is_enabled'],
                failure_count=action['failure_count'],
                max_failures=action['max_failures'],
                last_run_at=parse_datetime(action.get('last_run_at')),
                next_run_at=parse_datetime(action.get('next_run_at')),
                created_at=parse_datetime(action['created_at']),
            )
            for action in actions
        ]

    except Exception as e:
        logger.error(f"Error listing actions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/{action_id}")
async def get_action(
    action_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ActionDetail:
    """
    Get detailed information about an action.

    Args:
        action_id: ID of the action

    Returns:
        ActionDetail object
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        tool_permissions = database.get_action_tool_permissions(action_id)

        return ActionDetail(
            id=action['id'],
            name=action['name'],
            description=action['description'],
            action_prompt=action['action_prompt'],
            model_id=action['model_id'],
            schedule_type=action['schedule_type'],
            schedule_config=action.get('schedule_config', {}),
            context_mode=action['context_mode'],
            is_enabled=action['is_enabled'],
            failure_count=action['failure_count'],
            max_failures=action['max_failures'],
            last_run_at=parse_datetime(action.get('last_run_at')),
            next_run_at=parse_datetime(action.get('next_run_at')),
            created_at=parse_datetime(action['created_at']),
            tool_permissions=tool_permissions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions")
async def create_action(
    action_data: ActionCreate,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ActionDetail:
    """
    Create a new autonomous action.

    Args:
        action_data: Action creation data

    Returns:
        ActionDetail for the created action
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        # Check for duplicate name
        existing = database.get_action_by_name(action_data.name)
        if existing:
            raise HTTPException(status_code=400, detail="An action with this name already exists")

        # Create action
        action_id = database.create_action(
            name=action_data.name,
            description=action_data.description,
            action_prompt=action_data.action_prompt,
            model_id=action_data.model_id,
            schedule_type=action_data.schedule_type,
            schedule_config=action_data.schedule_config.dict(),
            context_mode=action_data.context_mode,
            max_failures=action_data.max_failures,
        )

        # Set tool permissions if provided
        if action_data.tool_permissions:
            permissions = [p.dict() for p in action_data.tool_permissions]
            database.set_action_tool_permissions_batch(action_id, permissions)

        # Schedule the action if scheduler is available
        if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
            app_instance.action_scheduler.schedule_action(
                action_id=action_id,
                action_name=action_data.name,
                schedule_type=action_data.schedule_type,
                schedule_config=action_data.schedule_config.dict(),
                user_guid=database.user_guid
            )

        # Return the created action
        return await get_action(action_id, request, session_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/actions/{action_id}")
async def update_action(
    action_id: int,
    action_data: ActionUpdate,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ActionDetail:
    """
    Update an action.

    Args:
        action_id: ID of the action to update
        action_data: Update data

    Returns:
        Updated ActionDetail
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        # Build updates dict
        updates = {}
        if action_data.name is not None:
            updates['name'] = action_data.name
        if action_data.description is not None:
            updates['description'] = action_data.description
        if action_data.action_prompt is not None:
            updates['action_prompt'] = action_data.action_prompt
        if action_data.schedule_type is not None:
            updates['schedule_type'] = action_data.schedule_type
        if action_data.schedule_config is not None:
            updates['schedule_config'] = action_data.schedule_config.dict()
        if action_data.context_mode is not None:
            updates['context_mode'] = action_data.context_mode
        if action_data.max_failures is not None:
            updates['max_failures'] = action_data.max_failures

        if updates:
            database.update_action(action_id, updates)

            # Reschedule if schedule changed
            if 'schedule_type' in updates or 'schedule_config' in updates:
                if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
                    updated_action = database.get_action(action_id)
                    app_instance.action_scheduler.schedule_action(
                        action_id=action_id,
                        action_name=updated_action['name'],
                        schedule_type=updated_action['schedule_type'],
                        schedule_config=updated_action['schedule_config'],
                        user_guid=database.user_guid
                    )

        return await get_action(action_id, request, session_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/actions/{action_id}")
async def delete_action(
    action_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Delete an action.

    Args:
        action_id: ID of the action to delete

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        # Unschedule the action
        if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
            app_instance.action_scheduler.unschedule_action(action_id)

        # Delete from database
        database.delete_action(action_id)

        return {
            "status": "success",
            "message": f"Action '{action['name']}' deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/{action_id}/enable")
async def enable_action(
    action_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Enable a disabled action.

    Args:
        action_id: ID of the action

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        database.enable_action(action_id)

        # Reschedule the action
        if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
            app_instance.action_scheduler.schedule_action(
                action_id=action_id,
                action_name=action['name'],
                schedule_type=action['schedule_type'],
                schedule_config=action['schedule_config'],
                user_guid=database.user_guid
            )

        return {
            "status": "success",
            "message": f"Action '{action['name']}' enabled",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/{action_id}/disable")
async def disable_action(
    action_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Disable an action.

    Args:
        action_id: ID of the action

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        database.disable_action(action_id)

        # Unschedule the action
        if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
            app_instance.action_scheduler.unschedule_action(action_id)

        return {
            "status": "success",
            "message": f"Action '{action['name']}' disabled",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/{action_id}/run-now")
async def run_action_now(
    action_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Trigger an action to run immediately.

    Args:
        action_id: ID of the action

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        # Check if action is currently locked by another process (e.g., daemon)
        from dtSpark.database.autonomous_actions import get_action_lock_info
        lock_info = get_action_lock_info(
            conn=database.conn,
            action_id=action_id,
            user_guid=database.user_guid
        )
        if lock_info and lock_info.get('locked_by'):
            raise HTTPException(
                status_code=409,
                detail=f"Action is currently being executed by another process ({lock_info['locked_by']})"
            )

        # Trigger immediate execution
        if hasattr(app_instance, 'action_scheduler') and app_instance.action_scheduler:
            success = app_instance.action_scheduler.run_action_now(
                action_id=action_id,
                user_guid=database.user_guid
            )
            if not success:
                raise HTTPException(status_code=500, detail="Failed to trigger action")
        else:
            raise HTTPException(status_code=503, detail="Action scheduler not available")

        return {
            "status": "success",
            "message": f"Action '{action['name']}' triggered for immediate execution",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/{action_id}/runs")
async def list_action_runs(
    action_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_id: str = Depends(get_current_session),
) -> List[ActionRunSummary]:
    """
    List runs for a specific action.

    Args:
        action_id: ID of the action
        limit: Maximum number of runs to return
        offset: Offset for pagination

    Returns:
        List of ActionRunSummary objects
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        action = database.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail=_ERR_ACTION_NOT_FOUND)

        runs = database.get_action_runs(action_id, limit=limit, offset=offset)

        return [
            ActionRunSummary(
                id=run['id'],
                action_id=run['action_id'],
                action_name=run.get('action_name', action['name']),
                started_at=parse_datetime(run['started_at']),
                completed_at=parse_datetime(run.get('completed_at')),
                status=run['status'],
                input_tokens=run.get('input_tokens', 0),
                output_tokens=run.get('output_tokens', 0),
            )
            for run in runs
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing runs for action {action_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/{action_id}/runs/{run_id}")
async def get_action_run(
    action_id: int,
    run_id: int,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> ActionRunDetail:
    """
    Get detailed information about a specific run.

    Args:
        action_id: ID of the action
        run_id: ID of the run

    Returns:
        ActionRunDetail object
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        run = database.get_action_run(run_id)
        if not run or run['action_id'] != action_id:
            raise HTTPException(status_code=404, detail="Run not found")

        return ActionRunDetail(
            id=run['id'],
            action_id=run['action_id'],
            action_name=run.get('action_name', 'Unknown'),
            started_at=parse_datetime(run['started_at']),
            completed_at=parse_datetime(run.get('completed_at')),
            status=run['status'],
            result_text=run.get('result_text'),
            result_html=run.get('result_html'),
            error_message=run.get('error_message'),
            input_tokens=run.get('input_tokens', 0),
            output_tokens=run.get('output_tokens', 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/{action_id}/runs/{run_id}/export")
async def export_run_result(
    action_id: int,
    run_id: int,
    request: Request,
    format: str = Query("text", pattern="^(text|html|markdown)$"),
    session_id: str = Depends(get_current_session),
):
    """
    Export run result in specified format.

    Args:
        action_id: ID of the action
        run_id: ID of the run
        format: Export format (text, html, markdown)

    Returns:
        Exported content in requested format
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        run = database.get_action_run(run_id)
        if not run or run['action_id'] != action_id:
            raise HTTPException(status_code=404, detail="Run not found")

        if format == "html":
            content = run.get('result_html') or f"<pre>{run.get('result_text', 'No result')}</pre>"
            return HTMLResponse(content=content)

        elif format == "markdown":
            result = run.get('result_text', 'No result')
            header = f"# Action Run {run_id}\n\n"
            header += f"**Action:** {run.get('action_name', 'Unknown')}\n"
            header += f"**Status:** {run['status']}\n"
            header += f"**Started:** {run.get('started_at', 'N/A')}\n"
            header += f"**Completed:** {run.get('completed_at', 'N/A')}\n\n"
            header += "## Result\n\n"
            content = header + result
            return PlainTextResponse(content=content, media_type="text/markdown")

        else:  # text
            content = run.get('result_text', 'No result')
            return PlainTextResponse(content=content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/runs/recent")
async def list_recent_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    session_id: str = Depends(get_current_session),
) -> List[ActionRunSummary]:
    """
    List recent runs across all actions.

    Args:
        limit: Maximum number of runs to return

    Returns:
        List of ActionRunSummary objects
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        runs = database.get_recent_action_runs(limit=limit)

        return [
            ActionRunSummary(
                id=run['id'],
                action_id=run['action_id'],
                action_name=run.get('action_name', 'Unknown'),
                started_at=parse_datetime(run['started_at']),
                completed_at=parse_datetime(run.get('completed_at')),
                status=run['status'],
                input_tokens=run.get('input_tokens', 0),
                output_tokens=run.get('output_tokens', 0),
            )
            for run in runs
        ]

    except Exception as e:
        logger.error(f"Error listing recent runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions/status/failed-count")
async def get_failed_action_count(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Get count of failed/disabled actions.

    Returns:
        Count of failed actions
    """
    try:
        app_instance = request.app.state.app_instance
        database = app_instance.database

        count = database.get_failed_action_count()

        return {
            "failed_count": count,
        }

    except Exception as e:
        logger.error(f"Error getting failed action count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# AI-ASSISTED ACTION CREATION
# =============================================================================

class AICreationStart(BaseModel):
    """Request model for starting AI-assisted action creation."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    model_id: str = Field(..., min_length=1)


class AICreationMessage(BaseModel):
    """Request model for sending a message in AI creation chat."""
    message: str = Field(..., min_length=1)


# Store for active creation sessions (in-memory, per-session)
_creation_sessions = {}


@router.post("/actions/ai-create/start")
async def start_ai_creation(
    request: Request,
    data: AICreationStart,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Start an AI-assisted action creation session.

    This initialises a chat session with the LLM to help create an action.

    Args:
        data: Action name, description, and model to use

    Returns:
        Session information and initial LLM response
    """
    import json
    from dtSpark.scheduler.creation_tools import (
        ACTION_CREATION_SYSTEM_PROMPT,
        get_action_creation_tools,
        execute_creation_tool
    )

    try:
        app_instance = request.app.state.app_instance

        # Validate model exists
        models = app_instance.llm_manager.list_all_models()
        model_exists = any(m['id'] == data.model_id for m in models)
        if not model_exists:
            raise HTTPException(status_code=400, detail=f"Model not found: {data.model_id}")

        # Create unique creation session ID
        import secrets
        creation_id = secrets.token_hex(16)

        # Set the model for this creation session
        app_instance.llm_manager.set_model(data.model_id)
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()

        # Initial message to the LLM with the action name and description
        initial_prompt = (
            f"I want to create an autonomous action with the following details:\n\n"
            f"**Name:** {data.name}\n"
            f"**Description:** {data.description}\n\n"
            f"Please help me configure this action. Ask me any questions needed to "
            f"understand what the action should do, when it should run, and what tools it needs."
        )

        # Initialise conversation messages
        messages = [
            {'role': 'user', 'content': [{'type': 'text', 'text': initial_prompt}]}
        ]

        # Get creation tools
        creation_tools = get_action_creation_tools()
        tools_for_api = [{'toolSpec': t} for t in creation_tools]

        # Invoke the LLM
        response = app_instance.llm_manager.invoke_model(
            messages=messages,
            system=ACTION_CREATION_SYSTEM_PROMPT,
            tools=tools_for_api,
            max_tokens=4096,
            temperature=0.7
        )

        if response.get('error'):
            raise HTTPException(
                status_code=500,
                detail=f"LLM error: {response.get('error_message', 'Unknown error')}"
            )

        # Extract response text
        response_text = ""
        content_blocks = response.get('content_blocks', [])
        for block in content_blocks:
            if block.get('type') == 'text':
                response_text += block.get('text', '')

        # If no content_blocks, try direct content
        if not response_text and response.get('content'):
            response_text = response.get('content', '')

        # Add assistant response to messages
        messages.append({
            'role': 'assistant',
            'content': content_blocks if content_blocks else [{'type': 'text', 'text': response_text}]
        })

        # Store session state
        _creation_sessions[creation_id] = {
            'name': data.name,
            'description': data.description,
            'model_id': data.model_id,
            'messages': messages,
            'created': datetime.now().isoformat(),
            'completed': False,
            'action_id': None
        }

        return {
            'creation_id': creation_id,
            'response': response_text,
            'completed': False
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting AI creation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/ai-create/{creation_id}/message")
async def send_ai_creation_message(
    creation_id: str,
    request: Request,
    data: AICreationMessage,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Send a message in an AI creation chat session.

    Args:
        creation_id: The creation session ID
        data: The user's message

    Returns:
        LLM response and completion status
    """
    import json
    from dtSpark.scheduler.creation_tools import (
        ACTION_CREATION_SYSTEM_PROMPT,
        get_action_creation_tools,
        execute_creation_tool
    )

    try:
        # Get session state
        if creation_id not in _creation_sessions:
            raise HTTPException(status_code=404, detail="Creation session not found")

        session_state = _creation_sessions[creation_id]

        if session_state.get('completed'):
            return {
                'response': 'This action has already been created.',
                'completed': True,
                'action_id': session_state.get('action_id')
            }

        app_instance = request.app.state.app_instance

        # Pre-fetch available tools (same as /tools endpoint)
        available_tools = []
        # Get MCP tools
        if hasattr(app_instance, 'mcp_manager') and app_instance.mcp_manager:
            try:
                mcp_tools = await app_instance.mcp_manager.list_all_tools()
                for tool in mcp_tools:
                    available_tools.append({
                        'name': tool.get('name', 'unknown'),
                        'description': tool.get('description', 'No description available'),
                        'source': tool.get('server', 'mcp')
                    })
            except Exception as e:
                logger.warning(f"Error getting MCP tools for AI creation: {e}")
        # Get embedded tools
        if hasattr(app_instance, 'conversation_manager') and app_instance.conversation_manager:
            try:
                embedded = app_instance.conversation_manager.get_embedded_tools()
                for tool in embedded:
                    # Embedded tools are wrapped in toolSpec format
                    tool_spec = tool.get('toolSpec', tool)
                    available_tools.append({
                        'name': tool_spec.get('name', 'unknown'),
                        'description': tool_spec.get('description', 'No description available'),
                        'source': 'embedded'
                    })
            except Exception as e:
                logger.warning(f"Error getting embedded tools for AI creation: {e}")

        # Set the model for this creation session
        app_instance.llm_manager.set_model(session_state['model_id'])
        app_instance.bedrock_service = app_instance.llm_manager.get_active_service()

        # Add user message
        messages = session_state['messages']
        messages.append({
            'role': 'user',
            'content': [{'type': 'text', 'text': data.message}]
        })

        # Get creation tools
        creation_tools = get_action_creation_tools()
        tools_for_api = [{'toolSpec': t} for t in creation_tools]

        # Tool execution loop
        max_iterations = 10
        iteration = 0
        final_response = ""
        action_created = False
        created_action_id = None

        while iteration < max_iterations:
            iteration += 1

            # Invoke the LLM
            response = app_instance.llm_manager.invoke_model(
                messages=messages,
                system=ACTION_CREATION_SYSTEM_PROMPT,
                tools=tools_for_api,
                max_tokens=4096,
                temperature=0.7
            )

            if response.get('error'):
                raise HTTPException(
                    status_code=500,
                    detail=f"LLM error: {response.get('error_message', 'Unknown error')}"
                )

            # Extract response content
            content_blocks = response.get('content_blocks', [])
            stop_reason = response.get('stop_reason', 'end_turn')

            # Check for tool use
            tool_use_blocks = [b for b in content_blocks if b.get('type') == 'tool_use']

            if tool_use_blocks:
                # Add assistant response with tool calls
                messages.append({
                    'role': 'assistant',
                    'content': content_blocks
                })

                # Execute tools
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.get('name')
                    tool_input = tool_block.get('input', {})
                    tool_id = tool_block.get('id')

                    # Execute the creation tool
                    result = execute_creation_tool(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        mcp_manager=app_instance.mcp_manager,
                        database=app_instance.database,
                        scheduler_manager=getattr(app_instance, 'scheduler_manager', None),
                        model_id=session_state['model_id'],
                        user_guid=getattr(app_instance.database, 'user_guid', None),
                        config=getattr(app_instance, 'config', None),
                        available_tools=available_tools
                    )

                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': json.dumps(result) if isinstance(result, dict) else str(result)
                    })

                    # Check if action was created
                    if tool_name == 'create_autonomous_action' and result.get('success'):
                        action_created = True
                        created_action_id = result.get('action_id')

                # Add tool results to messages
                messages.append({
                    'role': 'user',
                    'content': tool_results
                })

                # Continue loop to get LLM's response to tool results
                continue

            else:
                # No tool use - extract text response
                for block in content_blocks:
                    if block.get('type') == 'text':
                        final_response += block.get('text', '')

                # Add final assistant response to messages
                messages.append({
                    'role': 'assistant',
                    'content': content_blocks if content_blocks else [{'type': 'text', 'text': final_response}]
                })

                break

        # Update session state
        session_state['messages'] = messages
        if action_created:
            session_state['completed'] = True
            session_state['action_id'] = created_action_id

        return {
            'response': final_response,
            'completed': action_created,
            'action_id': created_action_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in AI creation message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/actions/ai-create/{creation_id}")
async def cancel_ai_creation(
    creation_id: str,
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Cancel an AI creation session.

    Args:
        creation_id: The creation session ID to cancel

    Returns:
        Confirmation message
    """
    if creation_id in _creation_sessions:
        del _creation_sessions[creation_id]

    return {'status': 'cancelled', 'message': 'Creation session cancelled'}
