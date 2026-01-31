"""
Main menu API endpoints.

Provides REST API for main menu operations:
- Re-gather AWS Bedrock costs
- Get account information
- Get MCP server status
- Application status


"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from ..dependencies import get_current_session


logger = logging.getLogger(__name__)

router = APIRouter()


class AccountInfo(BaseModel):
    """Account information for configured provider."""
    provider: str
    user_arn: Optional[str] = None
    account_id: Optional[str] = None
    region: Optional[str] = None
    user_guid: str
    auth_method: Optional[str] = None


class CostInfo(BaseModel):
    """Cost information for a specific period."""
    total: float
    models: dict[str, dict]  # model_id -> {cost, percentage}


class MCPServerInfo(BaseModel):
    """MCP server information."""
    name: str
    transport: str
    connected: bool
    tool_count: int


class ProviderModelInfo(BaseModel):
    """Model information for a provider."""
    model_id: str
    display_name: str
    description: Optional[str] = None


class ProviderInfo(BaseModel):
    """Information about a configured LLM provider."""
    name: str
    type: str  # 'aws', 'anthropic', 'ollama'
    enabled: bool
    status: str  # 'connected', 'error', 'disabled'
    models: list[ProviderModelInfo] = []
    auth_method: Optional[str] = None
    region: Optional[str] = None
    base_url: Optional[str] = None


@router.get("/account")
async def get_account_info(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> AccountInfo:
    """
    Get account information for the configured provider.

    Returns:
        AccountInfo with provider-specific details
    """
    try:
        app_instance = request.app.state.app_instance
        llm_manager = getattr(app_instance, 'llm_manager', None)
        user_guid = getattr(app_instance, 'user_guid', 'unknown')

        if llm_manager and llm_manager.active_provider:
            result = _build_account_info_for_provider(
                app_instance, llm_manager.active_provider.lower(), user_guid
            )
            if result:
                return result

        return AccountInfo(provider='none', user_guid=user_guid)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_account_info_for_provider(
    app_instance, active_provider: str, user_guid: str
) -> Optional[AccountInfo]:
    """Build AccountInfo for the given active provider, or return None if unavailable."""
    if 'bedrock' in active_provider or 'aws' in active_provider:
        return _build_aws_account_info(app_instance, user_guid)

    if 'anthropic' in active_provider:
        return AccountInfo(provider='anthropic', user_guid=user_guid, auth_method='api_key')

    if 'ollama' in active_provider:
        return AccountInfo(provider='ollama', user_guid=user_guid, auth_method='local')

    return None


def _build_aws_account_info(app_instance, user_guid: str) -> Optional[AccountInfo]:
    """Build AccountInfo from the AWS authenticator, or return None."""
    auth = getattr(app_instance, 'authenticator', None)
    if not auth:
        return None
    account_info = auth.get_account_info()
    if not account_info:
        return None
    return AccountInfo(
        provider='aws',
        user_arn=account_info.get('user_arn'),
        account_id=account_info.get('account_id'),
        region=account_info.get('region'),
        user_guid=user_guid,
        auth_method=account_info.get('auth_method'),
    )


@router.get("/providers")
async def get_providers(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> list[ProviderInfo]:
    """
    Get all configured LLM providers and their available models.

    Returns:
        List of ProviderInfo with provider details and available models
    """
    try:
        app_instance = request.app.state.app_instance
        providers = []

        llm_manager = getattr(app_instance, 'llm_manager', None)
        if llm_manager and hasattr(llm_manager, 'providers'):
            for provider_name, service in llm_manager.providers.items():
                provider_info = _build_provider_info(app_instance, provider_name, service)
                providers.append(provider_info)

        return providers

    except Exception as e:
        logger.error(f"Error getting providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_provider_info(app_instance, provider_name: str, service) -> ProviderInfo:
    """Build a ProviderInfo for a single registered provider."""
    provider_type, auth_method, region, base_url = _detect_provider_type(
        app_instance, provider_name, service
    )

    models, status = _list_provider_models(provider_name, service)

    return ProviderInfo(
        name=provider_name,
        type=provider_type,
        enabled=True,
        status=status,
        models=models,
        auth_method=auth_method,
        region=region,
        base_url=base_url,
    )


def _detect_provider_type(app_instance, provider_name: str, service) -> tuple:
    """Detect the provider type, auth method, region, and base URL from the provider name."""
    provider_name_lower = provider_name.lower()
    auth_method = None
    region = None
    base_url = None

    if 'bedrock' in provider_name_lower or 'aws' in provider_name_lower:
        provider_type = 'aws'
        auth = getattr(app_instance, 'authenticator', None)
        if auth:
            account_info = auth.get_account_info()
            if account_info:
                auth_method = account_info.get('auth_method')
                region = account_info.get('region')
    elif 'anthropic' in provider_name_lower:
        provider_type = 'anthropic'
        auth_method = 'api_key'
    elif 'ollama' in provider_name_lower:
        provider_type = 'ollama'
        auth_method = 'local'
        base_url = getattr(service, 'base_url', 'http://localhost:11434')
    else:
        provider_type = 'unknown'

    return provider_type, auth_method, region, base_url


def _list_provider_models(provider_name: str, service) -> tuple:
    """List available models from a provider service. Returns (models, status)."""
    models = []
    status = 'connected'

    try:
        if hasattr(service, 'list_available_models'):
            available_models = service.list_available_models()
        elif hasattr(service, 'list_models'):
            available_models = service.list_models()
        else:
            available_models = []

        for model in available_models:
            models.append(_parse_model_info(model))
    except Exception as e:
        logger.warning(f"Failed to list models from {provider_name}: {e}")
        status = 'error'

    return models, status


def _parse_model_info(model) -> ProviderModelInfo:
    """Parse a model entry (dict or string) into a ProviderModelInfo."""
    if isinstance(model, dict):
        model_id = model.get('id') or model.get('modelId') or model.get('name') or str(model)
        display_name = model.get('display_name') or model.get('modelName') or model_id
    else:
        model_id = str(model)
        display_name = model_id

    return ProviderModelInfo(model_id=model_id, display_name=display_name)


@router.get("/costs/last-month")
async def get_last_month_costs(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> CostInfo:
    """
    Get AWS Bedrock costs for the last month.

    Returns:
        CostInfo with total cost and per-model breakdown
    """
    try:
        app_instance = request.app.state.app_instance

        # Get costs from app instance (cached from startup)
        if not hasattr(app_instance, 'bedrock_costs') or not app_instance.bedrock_costs:
            return CostInfo(total=0.0, models={})

        last_month_data = app_instance.bedrock_costs.get('last_month', {})

        # Extract total and models from the cost data structure
        total = last_month_data.get('total', 0.0)
        models_breakdown = last_month_data.get('breakdown', {})

        # Format per-model costs
        models = {}
        for model_id, cost in models_breakdown.items():
            percentage = (cost / total * 100) if total > 0 else 0

            models[model_id] = {
                'cost': cost,
                'percentage': round(percentage, 2),
            }

        return CostInfo(
            total=round(total, 2),
            models=models,
        )

    except Exception as e:
        logger.error(f"Error getting last month costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/costs/last-24-hours")
async def get_last_24_hours_costs(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> CostInfo:
    """
    Get AWS Bedrock costs for the last 24 hours.

    Returns:
        CostInfo with total cost and per-model breakdown
    """
    try:
        app_instance = request.app.state.app_instance

        # Get costs from app instance (cached from startup)
        if not hasattr(app_instance, 'bedrock_costs') or not app_instance.bedrock_costs:
            return CostInfo(total=0.0, models={})

        last_24h_data = app_instance.bedrock_costs.get('last_24h', {})

        # Extract total and models from the cost data structure
        total = last_24h_data.get('total', 0.0)
        models_breakdown = last_24h_data.get('breakdown', {})

        # Format per-model costs
        models = {}
        for model_id, cost in models_breakdown.items():
            percentage = (cost / total * 100) if total > 0 else 0

            models[model_id] = {
                'cost': cost,
                'percentage': round(percentage, 2),
            }

        return CostInfo(
            total=round(total, 2),
            models=models,
        )

    except Exception as e:
        logger.error(f"Error getting last 24 hours costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/costs/refresh")
async def refresh_costs(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Refresh AWS Bedrock cost information.

    Returns:
        Status message
    """
    try:
        app_instance = request.app.state.app_instance

        # Re-gather costs
        if hasattr(app_instance, 'cost_tracker') and app_instance.cost_tracker:
            app_instance.bedrock_costs = app_instance.cost_tracker.get_bedrock_costs()

            return {
                "status": "success",
                "message": "Costs refreshed successfully",
            }
        else:
            return {
                "status": "error",
                "message": "Cost tracker not available",
            }

    except Exception as e:
        logger.error(f"Error refreshing costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/servers")
async def get_mcp_servers(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> list[MCPServerInfo]:
    """
    Get MCP server status and information.

    Returns:
        List of MCPServerInfo with connection status and tool counts
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if MCP is enabled
        if not hasattr(app_instance, 'mcp_manager') or not app_instance.mcp_manager:
            return []

        servers = []
        mcp_manager = app_instance.mcp_manager

        # Get all tools from MCP servers (async call)
        all_tools = await mcp_manager.list_all_tools()

        # Count tools by server
        tool_counts = {}
        for tool in all_tools:
            server = tool.get('server', 'unknown')
            tool_counts[server] = tool_counts.get(server, 0) + 1

        # Get information for each server
        if hasattr(mcp_manager, 'clients'):
            for server_name, client in mcp_manager.clients.items():
                # Determine transport type
                transport = 'stdio'
                if hasattr(client, 'config') and hasattr(client.config, 'transport'):
                    transport = client.config.transport

                servers.append(
                    MCPServerInfo(
                        name=server_name,
                        transport=transport,
                        connected=client.connected if hasattr(client, 'connected') else True,
                        tool_count=tool_counts.get(server_name, 0),
                    )
                )

        return servers

    except Exception as e:
        logger.error(f"Error getting MCP servers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools")
async def get_all_tools(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> dict:
    """
    Get all available tools (MCP + embedded).

    Returns:
        Dictionary with 'tools' list containing all available tools
    """
    try:
        app_instance = request.app.state.app_instance
        all_tools = []

        # Get MCP tools
        if hasattr(app_instance, 'mcp_manager') and app_instance.mcp_manager:
            try:
                mcp_tools = await app_instance.mcp_manager.list_all_tools()
                for tool in mcp_tools:
                    all_tools.append({
                        'name': tool.get('name', 'unknown'),
                        'description': tool.get('description', ''),
                        'server': tool.get('server', ''),
                        'source': 'mcp',
                    })
            except Exception as e:
                logger.warning(f"Error getting MCP tools: {e}")

        # Get embedded tools
        if hasattr(app_instance, 'conversation_manager') and app_instance.conversation_manager:
            try:
                embedded = app_instance.conversation_manager.get_embedded_tools()
                for tool in embedded:
                    tool_spec = tool.get('toolSpec', {})
                    all_tools.append({
                        'name': tool_spec.get('name', 'unknown'),
                        'description': tool_spec.get('description', ''),
                        'server': '',
                        'source': 'embedded',
                    })
            except Exception as e:
                logger.warning(f"Error getting embedded tools: {e}")

        return {'tools': all_tools}

    except Exception as e:
        logger.error(f"Error getting tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/tools")
async def get_mcp_tools(
    request: Request,
    server: Optional[str] = None,
    session_id: str = Depends(get_current_session),
) -> list[dict]:
    """
    Get available tools from MCP servers.

    Args:
        server: Optional server name to filter tools by

    Returns:
        List of tool definitions with name, description, and input schema
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if MCP is enabled
        if not hasattr(app_instance, 'mcp_manager') or not app_instance.mcp_manager:
            return []

        mcp_manager = app_instance.mcp_manager

        # Get all tools from MCP servers
        all_tools = await mcp_manager.list_all_tools()

        # Filter by server if specified
        if server:
            all_tools = [t for t in all_tools if t.get('server') == server]

        # Format tool information
        tools = []
        for tool in all_tools:
            tools.append({
                'name': tool.get('name', 'unknown'),
                'description': tool.get('description', ''),
                'server': tool.get('server', 'unknown'),
                'input_schema': tool.get('inputSchema', {}),
            })

        return tools

    except Exception as e:
        logger.error(f"Error getting MCP tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EmbeddedToolInfo(BaseModel):
    """Embedded tool information."""
    name: str
    description: str
    category: str  # Core, Filesystem, Documents, Archives


@router.get("/embedded-tools")
async def get_embedded_tools(
    request: Request,
    session_id: str = Depends(get_current_session),
) -> list[EmbeddedToolInfo]:
    """
    Get all embedded tools with their categories.

    Returns:
        List of EmbeddedToolInfo with tool details and categories
    """
    try:
        app_instance = request.app.state.app_instance
        tools = []

        # Get embedded tools from conversation manager
        if hasattr(app_instance, 'conversation_manager') and app_instance.conversation_manager:
            try:
                embedded = app_instance.conversation_manager.get_embedded_tools()
                for tool in embedded:
                    # Handle both Bedrock format (toolSpec) and Claude format (direct)
                    if 'toolSpec' in tool:
                        tool_spec = tool.get('toolSpec', {})
                        name = tool_spec.get('name', 'unknown')
                        description = tool_spec.get('description', '')
                    else:
                        name = tool.get('name', 'unknown')
                        description = tool.get('description', '')

                    # Determine category based on tool name
                    category = _categorise_embedded_tool(name)

                    tools.append(EmbeddedToolInfo(
                        name=name,
                        description=description,
                        category=category,
                    ))
            except Exception as e:
                logger.warning(f"Error getting embedded tools: {e}")

        return tools

    except Exception as e:
        logger.error(f"Error getting embedded tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _categorise_embedded_tool(tool_name: str) -> str:
    """Categorise an embedded tool based on its name."""
    name_lower = tool_name.lower()

    # Document tools
    if any(kw in name_lower for kw in ['word', 'excel', 'powerpoint', 'pdf', 'document']):
        return 'Documents'

    # Archive tools
    if any(kw in name_lower for kw in ['archive', 'zip', 'tar', 'extract']):
        return 'Archives'

    # Filesystem tools
    if any(kw in name_lower for kw in ['file', 'directory', 'list_files', 'read_file',
                                        'write_file', 'create_directory', 'search_files']):
        return 'Filesystem'

    # Default to Core
    return 'Core'


@router.get("/daemon/status")
async def get_daemon_status(request: Request):
    """
    Get daemon status.

    Returns:
        Dictionary with daemon status information
    """
    try:
        app_instance = request.app.state.app_instance

        # Check if daemon is running using PID file
        daemon_running = False
        daemon_pid = None

        try:
            from dtSpark.daemon.pid_file import PIDFile
            from dtPyAppFramework.settings import Settings

            settings = app_instance.settings if hasattr(app_instance, 'settings') else Settings()
            pid_file_path = settings.get('daemon.pid_file', './daemon.pid')
            pid_file = PIDFile(pid_file_path)

            daemon_running = pid_file.is_running()
            if daemon_running:
                daemon_pid = pid_file.read_pid()

        except Exception as e:
            logger.warning(f"Error checking daemon status: {e}")

        # Count scheduled actions
        scheduled_count = 0
        try:
            actions = app_instance.database.get_all_actions(include_disabled=False)
            scheduled_count = sum(1 for a in actions if a.get('schedule_type') != 'manual')
        except Exception:
            pass

        if not daemon_running and scheduled_count > 0:
            warning_message = (
                f"Daemon is not running - {scheduled_count} scheduled action(s) will not execute"
            )
        else:
            warning_message = None

        return {
            'daemon_running': daemon_running,
            'daemon_pid': daemon_pid,
            'scheduled_actions_count': scheduled_count,
            'warning': warning_message,
        }

    except Exception as e:
        logger.error(f"Error getting daemon status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
