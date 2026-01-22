"""
Built-in Tools module for providing default tool capabilities.

This module provides built-in tools that are always available to the LLM,
such as date/time information with timezone awareness and filesystem access.


"""

import logging
import os
import base64
import fnmatch
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from zoneinfo import ZoneInfo, available_timezones


def get_builtin_tools(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Get the list of built-in tool definitions.

    Args:
        config: Optional configuration dictionary containing embedded_tools settings

    Returns:
        List of tool definitions in Claude API format
    """
    tools = [
        {
            "name": "get_current_datetime",
            "description": "Get the current date and time with timezone awareness. "
                          "Returns the current datetime in ISO 8601 format. "
                          "Optionally specify a timezone to get the time in that zone.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Optional timezone identifier (e.g., 'Australia/Sydney', 'America/New_York', 'UTC'). "
                                      "If not provided, uses the system's local timezone.",
                        "default": None
                    },
                    "format": {
                        "type": "string",
                        "description": "Optional format for the datetime output. Options: 'iso' (ISO 8601), 'human' (human-readable). "
                                      "Default is 'iso'.",
                        "enum": ["iso", "human"],
                        "default": "iso"
                    }
                },
                "required": []
            }
        }
    ]

    # Add filesystem tools if enabled
    if config.get('embedded_tools', None):
        fs_config = config.get('embedded_tools', {}).get('filesystem', {})
        if fs_config.get('enabled', False):
            fs_tools = _get_filesystem_tools(fs_config)
            tools.extend(fs_tools)
            logging.info(f"Embedded filesystem tools enabled: {len(fs_tools)} tools added")

    return tools


def execute_builtin_tool(tool_name: str, tool_input: Dict[str, Any],
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a built-in tool.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        config: Optional configuration dictionary for filesystem tools

    Returns:
        Dictionary containing:
        - success: Boolean indicating if execution was successful
        - result: The tool execution result (if successful)
        - error: Error message (if failed)
    """
    try:
        if tool_name == "get_current_datetime":
            return _execute_get_current_datetime(tool_input)

        # Filesystem tools
        elif tool_name == "list_files_recursive":
            return _execute_list_files_recursive(tool_input, config)
        elif tool_name == "search_files":
            return _execute_search_files(tool_input, config)
        elif tool_name == "read_file_text":
            return _execute_read_file_text(tool_input, config)
        elif tool_name == "read_file_binary":
            return _execute_read_file_binary(tool_input, config)
        elif tool_name == "write_file":
            return _execute_write_file(tool_input, config)
        elif tool_name == "create_directories":
            return _execute_create_directories(tool_input, config)
        else:
            return {
                "success": False,
                "error": f"Unknown built-in tool: {tool_name}"
            }
    except Exception as e:
        logging.error(f"Error executing built-in tool {tool_name}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _execute_get_current_datetime(tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the get_current_datetime tool.

    Args:
        tool_input: Dictionary containing optional 'timezone' and 'format' keys

    Returns:
        Dictionary with success status and datetime result
    """
    timezone_str = tool_input.get("timezone")
    output_format = tool_input.get("format", "iso")

    try:
        # Get current datetime
        if timezone_str:
            # Validate timezone
            if timezone_str not in available_timezones():
                return {
                    "success": False,
                    "error": f"Invalid timezone: {timezone_str}. Use a valid IANA timezone identifier."
                }

            # Get datetime in specified timezone
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)
        else:
            # Get local datetime with system timezone
            now = datetime.now().astimezone()

        # Format output
        if output_format == "human":
            # Human-readable format
            result = {
                "datetime": now.strftime("%A, %d %B %Y at %I:%M:%S %p"),
                "timezone": now.strftime("%Z (UTC%z)"),
                "iso_format": now.isoformat()
            }
        else:
            # ISO 8601 format (default)
            result = {
                "datetime": now.isoformat(),
                "timezone": str(now.tzinfo),
                "timezone_offset": now.strftime("%z"),
                "unix_timestamp": int(now.timestamp())
            }

        logging.info(f"Built-in tool get_current_datetime executed: timezone={timezone_str or 'local'}, format={output_format}")

        return {
            "success": True,
            "result": result
        }

    except Exception as e:
        logging.error(f"Error in get_current_datetime: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def get_available_timezones() -> List[str]:
    """
    Get a list of all available timezone identifiers.

    Returns:
        Sorted list of timezone identifiers
    """
    return sorted(available_timezones())


def validate_timezone(timezone_str: str) -> bool:
    """
    Validate if a timezone string is valid.

    Args:
        timezone_str: Timezone identifier to validate

    Returns:
        True if valid, False otherwise
    """
    return timezone_str in available_timezones()


# ============================================================================
# Filesystem Tools
# ============================================================================

def _get_filesystem_tools(fs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get filesystem tool definitions based on configuration.

    Args:
        fs_config: Filesystem configuration dictionary

    Returns:
        List of filesystem tool definitions
    """
    access_mode = fs_config.get('access_mode', 'read')
    allowed_path = fs_config.get('allowed_path', '.')

    # Read-only tools (always included when filesystem is enabled)
    tools = [
        {
            "name": "list_files_recursive",
            "description": f"List all files and directories recursively within the allowed path ({allowed_path}). "
                          "Returns a structured list of all files with their paths, sizes, and modification times. "
                          "Useful for understanding directory structure and finding files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": f"Optional subdirectory within {allowed_path} to list. "
                                      "If not provided, lists from the root of the allowed path.",
                        "default": ""
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Include hidden files and directories (those starting with '.')",
                        "default": False
                    }
                },
                "required": []
            }
        },
        {
            "name": "search_files",
            "description": f"Search for files by filename within the allowed path ({allowed_path}). "
                          "Supports wildcards (* for any characters, ? for single character). "
                          "Returns matching file paths.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern for filename. Supports wildcards: * (any characters), ? (single character). "
                                      "Examples: '*.py' (all Python files), 'test_*.py' (test files), 'config.???' (config with 3-char extension)",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether the search should be case-sensitive",
                        "default": False
                    }
                },
                "required": ["pattern"]
            }
        },
        {
            "name": "read_file_text",
            "description": f"Read the contents of a text file within the allowed path ({allowed_path}). "
                          "Attempts to decode the file as UTF-8 text. Use read_file_binary for non-text files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read (relative to allowed path or absolute within allowed path)",
                    }
                },
                "required": ["path"]
            }
        },
        {
            "name": "read_file_binary",
            "description": f"Read the contents of a file as binary data within the allowed path ({allowed_path}). "
                          "Returns base64-encoded binary content. Use for images, PDFs, or other non-text files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read (relative to allowed path or absolute within allowed path)",
                    },
                    "max_size_mb": {
                        "type": "number",
                        "description": "Maximum file size in MB to read (default: 10MB). Prevents reading very large files.",
                        "default": 10
                    }
                },
                "required": ["path"]
            }
        }
    ]

    # Write tools (only added if access_mode is read_write)
    if access_mode == 'read_write':
        tools.extend([
            {
                "name": "write_file",
                "description": f"Write content to a file within the allowed path ({allowed_path}). "
                              "Creates the file if it doesn't exist, or overwrites if it exists. "
                              "Parent directories must already exist (use create_directories first if needed).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to write (relative to allowed path or absolute within allowed path)",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to the file",
                        },
                        "encoding": {
                            "type": "string",
                            "description": "Text encoding to use (default: utf-8)",
                            "default": "utf-8"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "create_directories",
                "description": f"Create one or more nested directories within the allowed path ({allowed_path}). "
                              "Creates all intermediate directories as needed (like 'mkdir -p'). "
                              "Safe to call even if directories already exist.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path to create (relative to allowed path or absolute within allowed path). "
                                          "Can include multiple nested levels (e.g., 'data/processed/reports')",
                        }
                    },
                    "required": ["path"]
                }
            }
        ])

    return tools


def _validate_path(file_path: str, allowed_path: str) -> Dict[str, Any]:
    """
    Validate that a file path is within the allowed directory.

    Args:
        file_path: File path to validate
        allowed_path: Root path that file must be within

    Returns:
        Dictionary with:
        - valid: Boolean indicating if path is valid
        - resolved_path: Absolute resolved path (if valid)
        - error: Error message (if invalid)
    """
    try:
        # Resolve allowed path to absolute
        allowed_abs = Path(allowed_path).resolve()

        # Handle empty file_path (means root of allowed path)
        if not file_path or file_path == '.':
            return {
                "valid": True,
                "resolved_path": str(allowed_abs),
                "error": None
            }

        # Resolve file path
        # If file_path is absolute, use it directly; otherwise treat as relative to allowed_path
        if Path(file_path).is_absolute():
            file_abs = Path(file_path).resolve()
        else:
            file_abs = (allowed_abs / file_path).resolve()

        # Check if file path is within allowed path
        try:
            file_abs.relative_to(allowed_abs)
        except ValueError:
            return {
                "valid": False,
                "resolved_path": None,
                "error": f"Access denied: Path '{file_path}' is outside allowed directory '{allowed_path}'"
            }

        return {
            "valid": True,
            "resolved_path": str(file_abs),
            "error": None
        }

    except Exception as e:
        return {
            "valid": False,
            "resolved_path": None,
            "error": f"Invalid path: {str(e)}"
        }


def _execute_list_files_recursive(tool_input: Dict[str, Any],
                                  config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the list_files_recursive tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status and file listing
    """
    if not config.get('embedded_tools'):
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')

    # Get parameters
    sub_path = tool_input.get('path', '')
    include_hidden = tool_input.get('include_hidden', False)

    # Validate path
    validation = _validate_path(sub_path, allowed_path)
    if not validation['valid']:
        return {"success": False, "error": validation['error']}

    root_path = Path(validation['resolved_path'])

    # Check if path exists
    if not root_path.exists():
        return {"success": False, "error": f"Path does not exist: {sub_path}"}

    if not root_path.is_dir():
        return {"success": False, "error": f"Path is not a directory: {sub_path}"}

    # Collect all files and directories
    files = []
    directories = []

    try:
        for item in root_path.rglob('*'):
            # Skip hidden files if not requested
            if not include_hidden and any(part.startswith('.') for part in item.parts):
                continue

            # Get relative path from root
            rel_path = item.relative_to(root_path)

            if item.is_file():
                files.append({
                    "path": str(rel_path),
                    "full_path": str(item),
                    "size_bytes": item.stat().st_size,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                    "type": "file"
                })
            elif item.is_dir():
                directories.append({
                    "path": str(rel_path),
                    "full_path": str(item),
                    "type": "directory"
                })

        result = {
            "root_path": str(root_path),
            "total_files": len(files),
            "total_directories": len(directories),
            "files": sorted(files, key=lambda x: x['path']),
            "directories": sorted(directories, key=lambda x: x['path'])
        }

        logging.info(f"Listed {len(files)} files and {len(directories)} directories from {root_path}")
        return {"success": True, "result": result}

    except Exception as e:
        logging.error(f"Error listing files: {e}")
        return {"success": False, "error": str(e)}


def _execute_search_files(tool_input: Dict[str, Any],
                          config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the search_files tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status and search results
    """
    if not config.get('embedded_tools'):
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')

    # Get parameters
    pattern = tool_input.get('pattern')
    case_sensitive = tool_input.get('case_sensitive', False)

    if not pattern:
        return {"success": False, "error": "Search pattern is required"}

    # Validate path
    validation = _validate_path('', allowed_path)
    if not validation['valid']:
        return {"success": False, "error": validation['error']}

    root_path = Path(validation['resolved_path'])

    # Search for matching files
    matches = []

    try:
        for item in root_path.rglob('*'):
            if item.is_file():
                filename = item.name

                # Apply pattern matching
                if case_sensitive:
                    match = fnmatch.fnmatch(filename, pattern)
                else:
                    match = fnmatch.fnmatch(filename.lower(), pattern.lower())

                if match:
                    rel_path = item.relative_to(root_path)
                    matches.append({
                        "filename": filename,
                        "path": str(rel_path),
                        "full_path": str(item),
                        "size_bytes": item.stat().st_size,
                        "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                    })

        result = {
            "pattern": pattern,
            "total_matches": len(matches),
            "matches": sorted(matches, key=lambda x: x['path'])
        }

        logging.info(f"Search for '{pattern}' found {len(matches)} matches")
        return {"success": True, "result": result}

    except Exception as e:
        logging.error(f"Error searching files: {e}")
        return {"success": False, "error": str(e)}


def _execute_read_file_text(tool_input: Dict[str, Any],
                            config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the read_file_text tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status and file content
    """
    if not config.get('embedded_tools'):
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')

    # Get parameters
    file_path = tool_input.get('path')

    if not file_path:
        return {"success": False, "error": "File path is required"}

    # Validate path
    validation = _validate_path(file_path, allowed_path)
    if not validation['valid']:
        return {"success": False, "error": validation['error']}

    full_path = Path(validation['resolved_path'])

    # Check if file exists
    if not full_path.exists():
        return {"success": False, "error": f"File does not exist: {file_path}"}

    if not full_path.is_file():
        return {"success": False, "error": f"Path is not a file: {file_path}"}

    # Read file as text
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        result = {
            "path": file_path,
            "full_path": str(full_path),
            "content": content,
            "size_bytes": full_path.stat().st_size,
            "encoding": "utf-8"
        }

        logging.info(f"Read text file: {file_path} ({result['size_bytes']} bytes)")
        return {"success": True, "result": result}

    except UnicodeDecodeError:
        return {
            "success": False,
            "error": f"File is not valid UTF-8 text. Use read_file_binary instead: {file_path}"
        }
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        return {"success": False, "error": str(e)}


def _execute_read_file_binary(tool_input: Dict[str, Any],
                              config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the read_file_binary tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status and base64-encoded content
    """
    if not config.get('embedded_tools'):
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')

    # Get parameters
    file_path = tool_input.get('path')
    max_size_mb = tool_input.get('max_size_mb', 10)

    if not file_path:
        return {"success": False, "error": "File path is required"}

    # Validate path
    validation = _validate_path(file_path, allowed_path)
    if not validation['valid']:
        return {"success": False, "error": validation['error']}

    full_path = Path(validation['resolved_path'])

    # Check if file exists
    if not full_path.exists():
        return {"success": False, "error": f"File does not exist: {file_path}"}

    if not full_path.is_file():
        return {"success": False, "error": f"Path is not a file: {file_path}"}

    # Check file size
    file_size = full_path.stat().st_size
    max_size_bytes = max_size_mb * 1024 * 1024

    if file_size > max_size_bytes:
        return {
            "success": False,
            "error": f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds maximum ({max_size_mb} MB)"
        }

    # Read file as binary
    try:
        with open(full_path, 'rb') as f:
            binary_content = f.read()

        # Encode as base64
        base64_content = base64.b64encode(binary_content).decode('utf-8')

        result = {
            "path": file_path,
            "full_path": str(full_path),
            "content_base64": base64_content,
            "size_bytes": file_size
        }

        logging.info(f"Read binary file: {file_path} ({file_size} bytes)")
        return {"success": True, "result": result}

    except Exception as e:
        logging.error(f"Error reading binary file {file_path}: {e}")
        return {"success": False, "error": str(e)}


def _execute_write_file(tool_input: Dict[str, Any],
                       config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the write_file tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status
    """
    logging.debug(f"write_file called with config keys: {list(config.keys()) if config else 'None'}")

    if not config.get('embedded_tools'):
        logging.warning("write_file failed: embedded_tools not in config")
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')
    access_mode = fs_config.get('access_mode', 'read')

    logging.debug(f"write_file fs_config: allowed_path={allowed_path}, access_mode={access_mode}")

    # Check if write access is enabled
    if access_mode != 'read_write':
        logging.warning(f"write_file failed: access_mode is '{access_mode}', not 'read_write'")
        return {
            "success": False,
            "error": "Write operations are disabled. Set access_mode to 'read_write' in configuration."
        }

    # Get parameters
    file_path = tool_input.get('path')
    content = tool_input.get('content')
    encoding = tool_input.get('encoding', 'utf-8')

    logging.debug(f"write_file params: path={file_path}, content_len={len(content) if content else 0}")

    if not file_path:
        logging.warning("write_file failed: no file path provided")
        return {"success": False, "error": "File path is required"}

    if content is None:
        logging.warning("write_file failed: no content provided")
        return {"success": False, "error": "Content is required"}

    # Validate path
    validation = _validate_path(file_path, allowed_path)
    if not validation['valid']:
        logging.warning(f"write_file failed: path validation error: {validation['error']}")
        return {"success": False, "error": validation['error']}

    full_path = Path(validation['resolved_path'])
    logging.debug(f"write_file resolved path: {full_path}")

    # Check if parent directory exists
    if not full_path.parent.exists():
        logging.warning(f"write_file failed: parent directory does not exist: {full_path.parent}")
        return {
            "success": False,
            "error": f"Parent directory does not exist: {full_path.parent}. Use create_directories first."
        }

    # Write file
    try:
        logging.debug(f"write_file: attempting to write {len(content)} chars to {full_path}")
        with open(full_path, 'w', encoding=encoding) as f:
            f.write(content)

        result = {
            "path": file_path,
            "full_path": str(full_path),
            "size_bytes": full_path.stat().st_size,
            "encoding": encoding
        }

        logging.info(f"Wrote file: {file_path} ({result['size_bytes']} bytes)")
        return {"success": True, "result": result}

    except Exception as e:
        logging.error(f"Error writing file {file_path}: {e}")
        return {"success": False, "error": str(e)}


def _execute_create_directories(tool_input: Dict[str, Any],
                                config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute the create_directories tool.

    Args:
        tool_input: Tool input parameters
        config: Configuration dictionary

    Returns:
        Dictionary with success status
    """
    if not config.get('embedded_tools'):
        return {"success": False, "error": "Filesystem tools not configured"}

    fs_config = config.get('embedded_tools', {}).get('filesystem', {})
    allowed_path = fs_config.get('allowed_path', '.')
    access_mode = fs_config.get('access_mode', 'read')

    # Check if write access is enabled
    if access_mode != 'read_write':
        return {
            "success": False,
            "error": "Write operations are disabled. Set access_mode to 'read_write' in configuration."
        }

    # Get parameters
    dir_path = tool_input.get('path')

    if not dir_path:
        return {"success": False, "error": "Directory path is required"}

    # Validate path
    validation = _validate_path(dir_path, allowed_path)
    if not validation['valid']:
        return {"success": False, "error": validation['error']}

    full_path = Path(validation['resolved_path'])

    # Create directories
    try:
        full_path.mkdir(parents=True, exist_ok=True)

        result = {
            "path": dir_path,
            "full_path": str(full_path),
            "created": not full_path.exists() or len(list(full_path.iterdir())) == 0
        }

        logging.info(f"Created directories: {dir_path}")
        return {"success": True, "result": result}

    except Exception as e:
        logging.error(f"Error creating directories {dir_path}: {e}")
        return {"success": False, "error": str(e)}
