"""
MCP Manager module for managing Model Context Protocol server connections.

This module provides functionality for:
- Connecting to MCP servers via stdio, HTTP, or SSE transports
- Authentication support (Bearer tokens, API keys, Basic auth, custom headers)
- Listing available tools from connected servers
- Calling tools on MCP servers
- Managing server lifecycles
"""

import asyncio
import logging
import base64
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.client.sse import sse_client
    import mcp.types as types
    from pydantic import AnyUrl
    import httpx
    MCP_AVAILABLE = True
except ImportError as e:
    MCP_AVAILABLE = False
    logging.warning(f"MCP library not available. Import error: {e}")
    logging.warning("Install required packages with: pip install 'mcp>=1.1.0' 'pydantic>=2.0.0' 'httpx'")


@dataclass
class MCPServerConfig:
    """
    Configuration for an MCP server.

    Attributes:
        name: Unique identifier for this server
        transport: Transport type - 'stdio', 'http', or 'sse'
        command: Command to run for stdio transport
        args: Arguments for stdio command
        url: URL for http/sse transports
        env: Environment variables for stdio transport
        enabled: Whether this server is enabled
        auth_type: Authentication type - 'none', 'bearer', 'api_key', 'basic', 'custom'
        auth_token: Bearer token or API key value
        auth_header_name: Custom header name for api_key auth (default: 'X-API-Key')
        basic_username: Username for basic auth
        basic_password: Password for basic auth
        custom_headers: Additional custom headers as dict
        timeout: Connection timeout in seconds
        ssl_verify: Whether to verify SSL certificates (default: True)
                    Set to False for self-signed certificates
    """
    name: str
    transport: str  # 'stdio', 'http', or 'sse'
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    enabled: bool = True
    # Authentication options
    auth_type: str = 'none'  # 'none', 'bearer', 'api_key', 'basic', 'custom'
    auth_token: Optional[str] = None
    auth_header_name: str = 'X-API-Key'  # For api_key auth type
    basic_username: Optional[str] = None
    basic_password: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    timeout: float = 30.0
    # SSL options
    ssl_verify: bool = True  # Set to False for self-signed certificates


class MCPClient:
    """Manages a single MCP server connection."""

    def __init__(self, config: MCPServerConfig):
        """
        Initialise an MCP client for a specific server.

        Args:
            config: Server configuration
        """
        self.config = config
        self.session: Optional[ClientSession] = None
        self.read = None
        self.write = None
        self._context = None
        self._connected = False
        self._httpx_client = None  # Custom httpx client for SSL options

    def _build_auth_headers(self) -> Dict[str, str]:
        """
        Build authentication headers based on configuration.

        Returns:
            Dictionary of headers for authentication
        """
        headers = {}

        # Add custom headers first (can be overridden by auth)
        if self.config.custom_headers:
            headers.update(self.config.custom_headers)

        auth_type = self.config.auth_type.lower()

        if auth_type == 'bearer':
            if self.config.auth_token:
                headers['Authorization'] = f'Bearer {self.config.auth_token}'
            else:
                logging.warning(f"Bearer auth selected but no auth_token provided for {self.config.name}")

        elif auth_type == 'api_key':
            if self.config.auth_token:
                header_name = self.config.auth_header_name or 'X-API-Key'
                headers[header_name] = self.config.auth_token
            else:
                logging.warning(f"API key auth selected but no auth_token provided for {self.config.name}")

        elif auth_type == 'basic':
            if self.config.basic_username and self.config.basic_password:
                credentials = f"{self.config.basic_username}:{self.config.basic_password}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers['Authorization'] = f'Basic {encoded}'
            else:
                logging.warning(f"Basic auth selected but credentials incomplete for {self.config.name}")

        elif auth_type == 'custom':
            # Custom auth relies entirely on custom_headers
            if not self.config.custom_headers:
                logging.warning(f"Custom auth selected but no custom_headers provided for {self.config.name}")

        elif auth_type != 'none':
            logging.warning(f"Unknown auth_type '{auth_type}' for {self.config.name}")

        return headers

    async def connect(self) -> bool:
        """
        Connect to the MCP server.

        Returns:
            True if connection successful, False otherwise
        """
        if not MCP_AVAILABLE:
            logging.error(f"Cannot connect to {self.config.name}: MCP library not installed")
            return False

        try:
            if self.config.transport == 'stdio':
                if not self.config.command:
                    logging.error(f"stdio transport requires a command for {self.config.name}")
                    return False

                server_params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args or [],
                    env=self.config.env or None
                )

                self._context = stdio_client(server_params)
                self.read, self.write = await self._context.__aenter__()

            elif self.config.transport == 'http':
                if not self.config.url:
                    logging.error(f"HTTP transport requires a URL for {self.config.name}")
                    return False

                # Build authentication headers
                headers = self._build_auth_headers()

                logging.debug(f"Connecting to HTTP MCP server {self.config.name} at {self.config.url}")
                if headers:
                    logging.debug(f"Using {len(headers)} custom headers for authentication")

                # Log SSL verification status
                if not self.config.ssl_verify:
                    logging.warning(f"SSL certificate verification disabled for {self.config.name} "
                                   f"(not recommended for production)")

                # Create custom httpx client if SSL verification is disabled
                httpx_client = None
                if not self.config.ssl_verify:
                    httpx_client = httpx.AsyncClient(
                        headers=headers if headers else None,
                        timeout=self.config.timeout,
                        verify=False  # NOSONAR - intentional, gated by ssl_verify config
                    )

                # Use streamable HTTP client with headers
                if httpx_client:
                    self._httpx_client = httpx_client  # Store for cleanup
                    self._context = streamablehttp_client(
                        url=self.config.url,
                        httpx_client=httpx_client
                    )
                else:
                    self._context = streamablehttp_client(
                        url=self.config.url,
                        headers=headers if headers else None,
                        timeout=self.config.timeout
                    )
                self.read, self.write, _ = await self._context.__aenter__()

            elif self.config.transport == 'sse':
                if not self.config.url:
                    logging.error(f"SSE transport requires a URL for {self.config.name}")
                    return False

                # Build authentication headers
                headers = self._build_auth_headers()

                logging.debug(f"Connecting to SSE MCP server {self.config.name} at {self.config.url}")
                if headers:
                    logging.debug(f"Using {len(headers)} custom headers for authentication")

                # Log SSL verification status
                if not self.config.ssl_verify:
                    logging.warning(f"SSL certificate verification disabled for {self.config.name} "
                                   f"(not recommended for production)")

                # Create custom httpx client if SSL verification is disabled
                httpx_client = None
                if not self.config.ssl_verify:
                    httpx_client = httpx.AsyncClient(
                        headers=headers if headers else None,
                        timeout=self.config.timeout,
                        verify=False  # NOSONAR - intentional, gated by ssl_verify config
                    )

                # Use SSE client with headers
                if httpx_client:
                    self._httpx_client = httpx_client  # Store for cleanup
                    self._context = sse_client(
                        url=self.config.url,
                        httpx_client=httpx_client
                    )
                else:
                    self._context = sse_client(
                        url=self.config.url,
                        headers=headers if headers else None,
                        timeout=self.config.timeout
                    )
                self.read, self.write = await self._context.__aenter__()

            else:
                logging.error(f"Unknown transport type: {self.config.transport}")
                return False

            # Create session and initialize with timeout
            self.session = ClientSession(self.read, self.write)
            await self.session.__aenter__()

            # Apply timeout to initialization to prevent hanging on failed connections
            try:
                await asyncio.wait_for(
                    self.session.initialize(),
                    timeout=self.config.timeout
                )
            except asyncio.TimeoutError:
                logging.error(f"Timeout during MCP session initialization for {self.config.name}")
                await self._cleanup_failed_connection()
                return False
            except asyncio.CancelledError:
                logging.error(f"MCP session initialization cancelled for {self.config.name} "
                             f"(server may have returned an error)")
                await self._cleanup_failed_connection()
                raise

            self._connected = True
            logging.info(f"Connected to MCP server: {self.config.name} (transport: {self.config.transport})")
            return True

        except asyncio.CancelledError:
            logging.error(f"Connection cancelled for MCP server {self.config.name} "
                         f"(check server URL and authentication)")
            await self._cleanup_failed_connection()
            raise
        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common issues
            if '401' in error_msg or 'Unauthorized' in error_msg:
                logging.error(f"Authentication failed for MCP server {self.config.name}: "
                             f"Check auth_type and credentials")
            elif '403' in error_msg or 'Forbidden' in error_msg:
                logging.error(f"Access forbidden for MCP server {self.config.name}: "
                             f"Check permissions and API key")
            elif '404' in error_msg or 'Not Found' in error_msg:
                logging.error(f"MCP endpoint not found for {self.config.name}: "
                             f"Check URL is correct ({self.config.url})")
            elif 'Connection refused' in error_msg:
                logging.error(f"Connection refused for MCP server {self.config.name}: "
                             f"Check server is running at {self.config.url}")
            else:
                logging.error(f"Failed to connect to MCP server {self.config.name}: {e}")
            await self._cleanup_failed_connection()
            return False

    async def _cleanup_failed_connection(self):
        """Clean up resources after a failed connection attempt."""
        try:
            if self.session:
                try:
                    await self.session.__aexit__(None, None, None)
                except Exception:
                    pass
                self.session = None

            if self._context:
                try:
                    await self._context.__aexit__(None, None, None)
                except Exception:
                    pass
                self._context = None

            if self._httpx_client:
                try:
                    await self._httpx_client.aclose()
                except Exception:
                    pass
                self._httpx_client = None

            self.read = None
            self.write = None
            self._connected = False
        except Exception as e:
            logging.debug(f"Error during connection cleanup for {self.config.name}: {e}")

    async def disconnect(self):
        """Disconnect from the MCP server."""
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
                self.session = None

            if self._context:
                await self._context.__aexit__(None, None, None)
                self._context = None

            if self._httpx_client:
                await self._httpx_client.aclose()
                self._httpx_client = None

            self._connected = False
            logging.info(f"Disconnected from MCP server: {self.config.name}")

        except Exception as e:
            logging.error(f"Error disconnecting from {self.config.name}: {e}")

    @property
    def connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        List all available tools from this server.

        Returns:
            List of tool dictionaries with name, description, and schema
        """
        if not self.session or not self._connected:
            logging.warning(f"Cannot list tools: not connected to {self.config.name}")
            return []

        try:
            result = await self.session.list_tools()
            tools = []

            for tool in result.tools:
                tools.append({
                    'name': tool.name,
                    'description': tool.description or '',
                    'input_schema': tool.inputSchema,
                    'server': self.config.name
                })

            logging.debug(f"Found {len(tools)} tools from {self.config.name}")
            return tools

        except Exception as e:
            logging.error(f"Failed to list tools from {self.config.name}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Call a tool on this server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result dictionary or None on failure
        """
        if not self.session or not self._connected:
            logging.warning(f"Cannot call tool: not connected to {self.config.name}")
            return None

        try:
            logging.debug(f"Calling tool {tool_name} on {self.config.name} with args: {arguments}")
            result = await self.session.call_tool(tool_name, arguments)

            # Parse the result
            content = []
            for item in result.content:
                if isinstance(item, types.TextContent):
                    content.append({
                        'type': 'text',
                        'text': item.text
                    })
                elif isinstance(item, types.ImageContent):
                    content.append({
                        'type': 'image',
                        'data': item.data,
                        'mimeType': item.mimeType
                    })
                elif isinstance(item, types.EmbeddedResource):
                    content.append({
                        'type': 'resource',
                        'resource': item.resource
                    })

            return {
                'content': content,
                'isError': result.isError if hasattr(result, 'isError') else False
            }

        except Exception as e:
            logging.error(f"Failed to call tool {tool_name} on {self.config.name}: {e}")
            return {
                'content': [{'type': 'text', 'text': f"Error calling tool: {str(e)}"}],
                'isError': True
            }


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        """Initialise the MCP manager."""
        self.clients: Dict[str, MCPClient] = {}
        self._loop = None
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._initialization_loop = None  # Store the loop used during init

    def add_server(self, config: MCPServerConfig):
        """
        Add an MCP server configuration.

        Args:
            config: Server configuration
        """
        if not config.enabled:
            logging.info(f"Skipping disabled MCP server: {config.name}")
            return

        if config.name in self.clients:
            logging.warning(f"MCP server {config.name} already exists, replacing")

        self.clients[config.name] = MCPClient(config)
        logging.info(f"Added MCP server configuration: {config.name}")

    async def connect_all(self, progress_callback=None) -> Dict[str, bool]:
        """
        Connect to all configured MCP servers.

        Args:
            progress_callback: Optional callback function(server_name, success) called after each server connection

        Returns:
            Dictionary mapping server names to connection status
        """
        if not self.clients:
            logging.info("No MCP servers configured")
            return {}

        results = {}
        for name, client in self.clients.items():
            success = await client.connect()
            results[name] = success

            # Call progress callback after each server connection
            if progress_callback:
                progress_callback(name, success)

        connected_count = sum(1 for success in results.values() if success)
        logging.info(f"Connected to {connected_count}/{len(self.clients)} MCP servers")

        return results

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for client in self.clients.values():
            await client.disconnect()

    async def list_all_tools(self) -> List[Dict[str, Any]]:
        """
        List all available tools from all connected servers.
        Results are cached after first successful fetch.

        Returns:
            List of tool dictionaries
        """
        # Return cached tools if available
        if self._tools_cache is not None:
            logging.debug(f"Returning cached tools: {len(self._tools_cache)}")
            return self._tools_cache

        all_tools = []

        for client in self.clients.values():
            if client.connected:
                try:
                    # Add timeout to each client's list_tools call
                    tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
                    all_tools.extend(tools)
                except asyncio.TimeoutError:
                    logging.error(f"Timeout listing tools from {client.config.name}")
                except Exception as e:
                    logging.error(f"Error listing tools from {client.config.name}: {e}")

        logging.info(f"Found {len(all_tools)} total tools across all MCP servers")

        # Cache the results
        self._tools_cache = all_tools

        return all_tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                       server_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Call a tool on an MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            server_name: Optional server name (if None, searches all servers)

        Returns:
            Tool result or None on failure
        """
        # If server is specified, call on that server
        if server_name:
            client = self.clients.get(server_name)
            if not client:
                logging.error(f"Server {server_name} not found")
                return None
            return await client.call_tool(tool_name, arguments)

        # Otherwise, search for the tool across all servers
        for client in self.clients.values():
            if client.connected:
                tools = await client.list_tools()
                if any(tool['name'] == tool_name for tool in tools):
                    return await client.call_tool(tool_name, arguments)

        logging.error(f"Tool {tool_name} not found on any connected server")
        return None

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Get tools schema in Claude-compatible format.

        Returns:
            List of tool definitions for Claude API
        """
        # This needs to be called from an async context
        # We'll need to handle this in the conversation manager
        return []

    @classmethod
    def from_config(cls, config_dict: Dict[str, Any]) -> 'MCPManager':
        """
        Create an MCP manager from configuration dictionary.

        Args:
            config_dict: Configuration dictionary with MCP server definitions

        Returns:
            Configured MCPManager instance

        Example configuration:
            mcp_config:
              servers:
                # Local stdio server
                - name: local-tools
                  transport: stdio
                  command: python
                  args: ["-m", "my_mcp_server"]
                  enabled: true

                # Remote HTTP server with bearer auth
                - name: remote-api
                  transport: http
                  url: https://api.example.com/mcp
                  auth_type: bearer
                  auth_token: ${REMOTE_API_TOKEN}
                  timeout: 60

                # SSE server with API key auth
                - name: sse-service
                  transport: sse
                  url: https://events.example.com/mcp
                  auth_type: api_key
                  auth_token: ${SSE_API_KEY}
                  auth_header_name: X-API-Key

                # HTTP server with basic auth
                - name: internal-service
                  transport: http
                  url: https://internal.example.com/mcp
                  auth_type: basic
                  basic_username: ${SERVICE_USER}
                  basic_password: ${SERVICE_PASS}

                # HTTP server with custom headers
                - name: custom-auth-service
                  transport: http
                  url: https://custom.example.com/mcp
                  auth_type: custom
                  custom_headers:
                    X-Tenant-ID: "my-tenant"
                    X-Custom-Auth: "secret-value"
        """
        manager = cls()

        servers_config = config_dict.get('mcp_config', {}).get('servers', [])

        for server_config in servers_config:
            config = MCPServerConfig(
                name=server_config.get('name', 'unknown'),
                transport=server_config.get('transport', 'stdio'),
                command=server_config.get('command'),
                args=server_config.get('args', []),
                url=server_config.get('url'),
                env=server_config.get('env'),
                enabled=server_config.get('enabled', True),
                # Authentication options
                auth_type=server_config.get('auth_type', 'none'),
                auth_token=server_config.get('auth_token'),
                auth_header_name=server_config.get('auth_header_name', 'X-API-Key'),
                basic_username=server_config.get('basic_username'),
                basic_password=server_config.get('basic_password'),
                custom_headers=server_config.get('custom_headers'),
                timeout=server_config.get('timeout', 30.0),
                # SSL options
                ssl_verify=server_config.get('ssl_verify', True)
            )
            manager.add_server(config)

        return manager
