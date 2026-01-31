"""
Tools for prompt-driven autonomous action creation.

Exposes tools that an LLM can use to create scheduled actions through
natural conversation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


# System instructions for the creation LLM
ACTION_CREATION_SYSTEM_PROMPT = """You are an assistant helping the user create an autonomous scheduled action. Your role is to:

1. UNDERSTAND the user's requirements for their scheduled task
2. GATHER all necessary information through conversation:
   - What the task should do (action prompt)
   - When it should run (schedule)
   - Whether it needs fresh context each run or should build on previous runs
   - What tools it will need access to

3. ASK CLARIFYING QUESTIONS if any of the following are unclear:
   - The schedule timing (be specific: "Every weekday at 8am" vs "Every day")
   - What specific actions the AI should take
   - Whether results should persist across runs (context mode)
   - What capabilities (tools) are needed

4. INFER APPROPRIATE TOOLS based on the task description:
   - Use the list_available_tools function to see what's available
   - Select only the tools necessary for the described task
   - If unsure, ask the user to confirm your tool selection

5. VALIDATE the schedule using validate_schedule before creating

6. GENERATE a suitable system prompt for the scheduled task that:
   - Defines the AI's role clearly
   - Provides context about the task's purpose
   - Includes any constraints or requirements

7. PRESENT A SUMMARY for confirmation before creating:
   - Action name and description
   - Schedule (human-readable)
   - Context mode
   - Selected tools
   - Generated system prompt (brief summary)
   - Action prompt

8. Only call create_autonomous_action AFTER the user confirms the summary

IMPORTANT:
- If the user types "cancel", acknowledge and stop the creation process
- Be concise but thorough in your questions
- Suggest sensible defaults when appropriate (e.g., fresh context mode for most tasks)
- Explain cron expressions in plain language when presenting summaries
- Default max_failures to 3 unless the user specifies otherwise
"""


def get_action_creation_tools() -> List[Dict[str, Any]]:
    """
    Return tool definitions for action creation.

    These tools are exposed to the LLM to help create autonomous actions
    through natural conversation.

    Returns:
        List of tool definitions in Claude API format
    """
    return [
        {
            'name': 'list_available_tools',
            'description': (
                'List all available tools that can be assigned to an autonomous action. '
                'Use this to see what capabilities are available before selecting tools '
                'for the scheduled task.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            }
        },
        {
            'name': 'validate_schedule',
            'description': (
                'Validate a schedule configuration before creating an action. '
                'Checks if the cron expression or datetime is valid and returns '
                'a human-readable description of when the action will run.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'schedule_type': {
                        'type': 'string',
                        'enum': ['one_off', 'recurring'],
                        'description': 'Type of schedule: one_off for single execution, recurring for repeated execution'
                    },
                    'schedule_value': {
                        'type': 'string',
                        'description': (
                            'For one_off: datetime in format "YYYY-MM-DD HH:MM" (e.g., "2025-12-20 14:30"). '
                            'For recurring: cron expression with 5 fields (minute hour day month day_of_week), '
                            'e.g., "0 8 * * MON-FRI" for weekdays at 8am, "0 9 * * *" for every day at 9am.'
                        )
                    }
                },
                'required': ['schedule_type', 'schedule_value']
            }
        },
        {
            'name': 'create_autonomous_action',
            'description': (
                'Create a new autonomous action with the specified configuration. '
                'Only call this AFTER presenting a summary to the user and receiving their confirmation.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'Unique name for the action (e.g., "Daily Cost Report")'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Human-readable description of what the action does'
                    },
                    'action_prompt': {
                        'type': 'string',
                        'description': 'The prompt/instructions for the AI to execute when the action runs'
                    },
                    'system_prompt': {
                        'type': 'string',
                        'description': 'System instructions that define the AI\'s role and constraints for this task'
                    },
                    'schedule_type': {
                        'type': 'string',
                        'enum': ['one_off', 'recurring'],
                        'description': 'Type of schedule'
                    },
                    'schedule_value': {
                        'type': 'string',
                        'description': 'Cron expression or datetime string'
                    },
                    'context_mode': {
                        'type': 'string',
                        'enum': ['fresh', 'cumulative'],
                        'description': (
                            'fresh: Start with empty context each run (default). '
                            'cumulative: Build on previous run\'s context.'
                        )
                    },
                    'max_failures': {
                        'type': 'integer',
                        'description': 'Auto-disable action after this many consecutive failures (default: 3)'
                    },
                    'max_tokens': {
                        'type': 'integer',
                        'description': (
                            'Maximum tokens for LLM response (default: 8192). '
                            'Use higher values (e.g., 16384) for tasks generating large content like reports.'
                        )
                    },
                    'tool_names': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of tool names the action is allowed to use'
                    }
                },
                'required': ['name', 'description', 'action_prompt', 'system_prompt',
                            'schedule_type', 'schedule_value', 'tool_names']
            }
        }
    ]


def execute_creation_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    mcp_manager,
    database,
    scheduler_manager,
    model_id: str,
    user_guid: str,
    config: Optional[Dict[str, Any]] = None,
    available_tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Execute an action creation tool.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        mcp_manager: MCP manager instance for listing tools (legacy, prefer available_tools)
        database: Database instance for creating actions
        scheduler_manager: Scheduler manager for scheduling actions
        model_id: Model ID to lock for the action
        user_guid: User GUID for multi-user isolation
        config: Optional application config for builtin tools
        available_tools: Pre-fetched list of available tools (preferred over mcp_manager)

    Returns:
        Result dictionary from the tool execution
    """
    logger.debug(f"Executing creation tool: {tool_name} with input: {tool_input}")

    try:
        if tool_name == 'list_available_tools':
            # Use pre-fetched tools if available, otherwise fall back to fetching
            if available_tools is not None:
                return {
                    'tools': available_tools,
                    'count': len(available_tools),
                    'message': f"Found {len(available_tools)} available tools"
                }
            return _list_available_tools(mcp_manager, config)

        elif tool_name == 'validate_schedule':
            return _validate_schedule(
                tool_input.get('schedule_type', ''),
                tool_input.get('schedule_value', '')
            )

        elif tool_name == 'create_autonomous_action':
            return _create_action(
                tool_input,
                database,
                scheduler_manager,
                model_id,
                user_guid
            )

        else:
            return {'error': f'Unknown tool: {tool_name}'}

    except Exception as e:
        logger.error(f"Error executing creation tool {tool_name}: {e}", exc_info=True)
        return {'error': str(e)}


def _list_available_tools(mcp_manager, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    List all available tools with descriptions.

    Args:
        mcp_manager: MCP manager instance
        config: Optional application config for builtin tools

    Returns:
        Dictionary with tools list and count
    """
    tools = []
    errors = []

    _collect_builtin_tools(tools, errors, config)
    _collect_mcp_tools(tools, errors, mcp_manager)

    result = {
        'tools': tools,
        'count': len(tools),
        'message': f"Found {len(tools)} available tools"
    }

    if errors:
        result['warnings'] = errors

    return result


def _collect_builtin_tools(
    tools: List[Dict[str, Any]],
    errors: List[str],
    config: Optional[Dict[str, Any]]
) -> None:
    """Collect built-in tools (including filesystem tools if enabled in config)."""
    try:
        from dtSpark.tools import builtin
        builtin_config = config or {}
        for tool in builtin.get_builtin_tools(builtin_config):
            tools.append({
                'name': tool['name'],
                'description': tool.get('description', 'No description available'),
                'source': 'builtin'
            })
        logger.debug(f"Loaded {len(tools)} builtin tools")
    except Exception as e:
        logger.warning(f"Failed to get built-in tools: {e}")
        errors.append(f"Builtin tools error: {e}")


def _collect_mcp_tools(
    tools: List[Dict[str, Any]],
    errors: List[str],
    mcp_manager
) -> None:
    """Collect tools from the MCP manager, handling async resolution."""
    if not mcp_manager:
        logger.debug("No MCP manager provided")
        return

    logger.debug(f"MCP manager present: {type(mcp_manager)}")

    if not hasattr(mcp_manager, 'list_all_tools'):
        logger.warning("MCP manager does not have list_all_tools method")
        errors.append("MCP manager missing list_all_tools method")
        return

    try:
        mcp_tools = _resolve_mcp_tools(mcp_manager)
        mcp_count = 0
        for tool in mcp_tools:
            tools.append({
                'name': tool.get('name', 'unknown'),
                'description': tool.get('description', 'No description available'),
                'source': tool.get('server', 'mcp')
            })
            mcp_count += 1
        logger.debug(f"Loaded {mcp_count} MCP tools")
    except Exception as e:
        logger.warning(f"Failed to get MCP tools: {e}", exc_info=True)
        errors.append(f"MCP tools error: {e}")


def _resolve_mcp_tools(mcp_manager) -> list:
    """Resolve MCP tools, handling both sync and async code paths."""
    loop = getattr(mcp_manager, '_initialization_loop', None)

    if loop and not loop.is_closed():
        return loop.run_until_complete(mcp_manager.list_all_tools())

    mcp_tools = mcp_manager.list_all_tools()
    if asyncio.iscoroutine(mcp_tools):
        loop = _get_or_create_event_loop()
        mcp_tools = loop.run_until_complete(mcp_tools)
    return mcp_tools


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Return an open event loop, creating one if necessary."""
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            return loop
    except RuntimeError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def _validate_schedule(schedule_type: str, schedule_value: str) -> Dict[str, Any]:
    """
    Validate schedule configuration.

    Args:
        schedule_type: 'one_off' or 'recurring'
        schedule_value: Datetime string or cron expression

    Returns:
        Validation result with human-readable description
    """
    if not schedule_type:
        return {'valid': False, 'error': 'schedule_type is required'}

    if not schedule_value:
        return {'valid': False, 'error': 'schedule_value is required'}

    if schedule_type == 'one_off':
        return _validate_one_off_schedule(schedule_value)

    if schedule_type == 'recurring':
        return _validate_recurring_schedule(schedule_value)

    return {
        'valid': False,
        'error': f'Unknown schedule type: {schedule_type}. Use "one_off" or "recurring"'
    }


def _validate_one_off_schedule(schedule_value: str) -> Dict[str, Any]:
    """Validate a one-off (single execution) schedule value."""
    try:
        dt = _parse_datetime(schedule_value)

        if dt is None:
            return {
                'valid': False,
                'error': 'Invalid datetime format. Use YYYY-MM-DD HH:MM (e.g., "2025-12-20 14:30")'
            }

        if dt <= datetime.now():
            return {
                'valid': False,
                'error': 'Date must be in the future'
            }

        return {
            'valid': True,
            'schedule_type': 'one_off',
            'parsed': dt.isoformat(),
            'human_readable': dt.strftime('%A, %d %B %Y at %H:%M')
        }

    except Exception as e:
        return {'valid': False, 'error': f'Invalid datetime: {e}'}


def _parse_datetime(value: str) -> Optional[datetime]:
    """Attempt to parse a datetime string using common formats."""
    formats = ['%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S']
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _validate_recurring_schedule(schedule_value: str) -> Dict[str, Any]:
    """Validate a recurring (cron-based) schedule value."""
    try:
        from apscheduler.triggers.cron import CronTrigger

        parts = schedule_value.split()
        if len(parts) != 5:
            return {
                'valid': False,
                'error': (
                    'Cron expression must have 5 fields: minute hour day month day_of_week. '
                    'Example: "0 8 * * MON-FRI" for weekdays at 8am'
                )
            }

        minute, hour, day, month, dow = parts

        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=dow
        )

        next_run = trigger.get_next_fire_time(None, datetime.now())

        return {
            'valid': True,
            'schedule_type': 'recurring',
            'cron_expression': schedule_value,
            'human_readable': _cron_to_human(schedule_value),
            'next_run': next_run.isoformat() if next_run else None
        }

    except Exception as e:
        return {
            'valid': False,
            'error': f'Invalid cron expression: {e}'
        }


# Mapping of day-of-week values to human-readable names.
_DOW_MAP = {
    'MON-FRI': 'Weekdays (Monday to Friday)',
    '1-5': 'Weekdays (Monday to Friday)',
    'SAT,SUN': 'Weekends',
    '0,6': 'Weekends',
    '6,0': 'Weekends',
}

# Single-day mappings (value or uppercase alias -> label).
_SINGLE_DOW_MAP = {
    '0': 'Every Sunday',   'SUN': 'Every Sunday',
    '1': 'Every Monday',   'MON': 'Every Monday',
    '2': 'Every Tuesday',  'TUE': 'Every Tuesday',
    '3': 'Every Wednesday', 'WED': 'Every Wednesday',
    '4': 'Every Thursday',  'THU': 'Every Thursday',
    '5': 'Every Friday',   'FRI': 'Every Friday',
    '6': 'Every Saturday',  'SAT': 'Every Saturday',
}


def _cron_to_human(cron: str) -> str:
    """
    Convert cron expression to human-readable string.

    Args:
        cron: 5-field cron expression

    Returns:
        Human-readable description
    """
    parts = cron.split()
    if len(parts) != 5:
        return f"Cron: {cron}"

    minute, hour, day, month, dow = parts

    time_str = _format_cron_time(minute, hour)
    freq = _describe_cron_frequency(minute, hour, day, month, dow)

    if freq is None:
        return f"Cron: {cron}"

    # Interval-based frequencies already include timing info
    if freq.startswith("Every ") and ("minutes" in freq or "hours" in freq):
        return freq

    return f"{freq} at {time_str}"


def _format_cron_time(minute: str, hour: str) -> str:
    """Build a human-readable time string from cron minute and hour fields."""
    if minute == '0':
        return f"{hour}:00"
    if minute.isdigit():
        return f"{hour}:{minute.zfill(2)}"
    return f"{hour}:{minute}"


def _describe_cron_frequency(
    minute: str, hour: str, day: str, month: str, dow: str
) -> Optional[str]:
    """
    Derive a human-readable frequency description from cron fields.

    Returns None when no known pattern matches.
    """
    # Every day
    if dow == '*' and day == '*' and month == '*':
        return "Every day"

    # Multi-day patterns (weekdays, weekends)
    if dow in _DOW_MAP:
        return _DOW_MAP[dow]

    # Single named/numbered day of week
    dow_label = _SINGLE_DOW_MAP.get(dow) or _SINGLE_DOW_MAP.get(dow.upper())
    if dow_label:
        return dow_label

    # Day-of-month pattern
    if day != '*' and month == '*':
        return f"Day {day} of each month"

    # Interval-based patterns
    if '/' in minute:
        interval = minute.split('/')[1]
        return f"Every {interval} minutes"
    if '/' in hour:
        interval = hour.split('/')[1]
        return f"Every {interval} hours"

    return None


def _create_action(
    params: Dict[str, Any],
    database,
    scheduler_manager,
    model_id: str,
    user_guid: str
) -> Dict[str, Any]:
    """
    Create the autonomous action in the database and schedule it.

    Args:
        params: Action parameters from the LLM
        database: ConversationDatabase instance
        scheduler_manager: Scheduler manager instance
        model_id: Model ID to lock for the action
        user_guid: User GUID (not used - database uses its own user_guid)

    Returns:
        Result dictionary with success status
    """
    # Validate required fields
    required = ['name', 'description', 'action_prompt', 'system_prompt',
                'schedule_type', 'schedule_value', 'tool_names']
    missing = [f for f in required if not params.get(f)]
    if missing:
        return {
            'success': False,
            'error': f'Missing required fields: {", ".join(missing)}'
        }

    # Build schedule config (as dict, not JSON string)
    if params['schedule_type'] == 'one_off':
        schedule_config = {'run_date': params['schedule_value']}
    else:
        schedule_config = {'cron_expression': params['schedule_value']}

    try:
        # Check for duplicate name using database wrapper method
        existing = database.get_action_by_name(params['name'])
        if existing:
            return {
                'success': False,
                'error': f'An action named "{params["name"]}" already exists'
            }

        full_prompt = _build_full_prompt(params)

        action_id = database.create_action(
            name=params['name'],
            description=params['description'],
            action_prompt=full_prompt,
            model_id=model_id,
            schedule_type=params['schedule_type'],
            schedule_config=schedule_config,
            context_mode=params.get('context_mode', 'fresh'),
            max_failures=params.get('max_failures', 3),
            max_tokens=params.get('max_tokens', 8192)
        )

        _set_tool_permissions(database, action_id, params.get('tool_names', []))

        next_run = _schedule_action(scheduler_manager, action_id, params, schedule_config, user_guid)

        # Build success message
        schedule_desc = (
            _cron_to_human(params['schedule_value'])
            if params['schedule_type'] == 'recurring'
            else params['schedule_value']
        )

        return {
            'success': True,
            'action_id': action_id,
            'name': params['name'],
            'schedule': schedule_desc,
            'next_run': next_run.isoformat() if next_run else None,
            'message': f"Action '{params['name']}' created successfully and scheduled"
        }

    except Exception as e:
        logger.error(f"Failed to create action: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def _build_full_prompt(params: Dict[str, Any]) -> str:
    """Combine system_prompt and action_prompt into a single prompt for storage."""
    full_prompt = params['action_prompt']
    if params.get('system_prompt'):
        full_prompt = f"[System Instructions]\n{params['system_prompt']}\n\n[Task]\n{params['action_prompt']}"
    return full_prompt


def _set_tool_permissions(database, action_id: str, tool_names: List[str]) -> None:
    """Set tool permissions for the newly created action."""
    if not tool_names:
        return
    tool_permissions = [
        {
            'tool_name': t,
            'server_name': None,
            'permission_state': 'allowed'
        }
        for t in tool_names
    ]
    database.set_action_tool_permissions_batch(action_id, tool_permissions)


def _schedule_action(
    scheduler_manager,
    action_id: str,
    params: Dict[str, Any],
    schedule_config: Dict[str, Any],
    user_guid: str
):
    """Schedule the action and return the next run time, or None on failure."""
    if not scheduler_manager:
        return None
    try:
        scheduler_manager.schedule_action(
            action_id=action_id,
            action_name=params['name'],
            schedule_type=params['schedule_type'],
            schedule_config=schedule_config,
            user_guid=user_guid
        )
        return scheduler_manager.get_next_run_time(action_id)
    except Exception as e:
        logger.warning(f"Failed to schedule action: {e}")
        return None
