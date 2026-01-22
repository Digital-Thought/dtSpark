I am # MCP Integration Guide

Spark supports the Model Context Protocol (MCP) for connecting external tools to LLM conversations.

## What is MCP?

MCP (Model Context Protocol) is a standard for connecting AI models to external tools and data sources. It enables:

- **Tool Discovery** - Models can see what tools are available
- **Tool Execution** - Models can call tools with parameters
- **Result Handling** - Tool outputs returned to models

```mermaid
graph LR
    subgraph "Spark"
        LLM[LLM Provider]
        MGR[MCP Manager]
    end

    subgraph "MCP Servers"
        FS[Filesystem Server]
        DB[Database Server]
        API[API Server]
    end

    LLM <--> MGR
    MGR <--> FS
    MGR <--> DB
    MGR <--> API
```

## Configuration

### Enabling MCP

```yaml
mcp_config:
  enabled: true
  servers:
    # Server configurations here
```

### Server Configuration

#### Stdio Transport (Local Process)

For servers that run as local processes:

```yaml
mcp_config:
  enabled: true
  servers:
    - name: filesystem
      transport: stdio
      command: uvx
      args:
        - mcp-server-filesystem
        - /path/to/directory
      env:
        SOME_VAR: value
      enabled: true
```

| Field | Description |
|-------|-------------|
| `name` | Unique identifier for the server |
| `transport` | `stdio` for local process |
| `command` | Executable to run |
| `args` | Command-line arguments |
| `env` | Environment variables (optional) |
| `enabled` | Whether to connect on startup |

#### HTTP Transport (Remote Server)

For servers accessible via HTTP:

```yaml
mcp_config:
  enabled: true
  servers:
    - name: remote-api
      transport: http
      url: http://localhost:8000/mcp
      enabled: true
```

| Field | Description |
|-------|-------------|
| `name` | Unique identifier |
| `transport` | `http` for remote |
| `url` | Server endpoint URL |
| `enabled` | Whether to connect |

### Multiple Servers

Configure multiple servers:

```yaml
mcp_config:
  enabled: true
  servers:
    - name: filesystem
      transport: stdio
      command: uvx
      args:
        - mcp-server-filesystem
        - ./working
      enabled: true

    - name: github
      transport: stdio
      command: uvx
      args:
        - mcp-server-github
      env:
        GITHUB_TOKEN: ${GITHUB_TOKEN}
      enabled: true

    - name: database
      transport: http
      url: http://localhost:8080/mcp
      enabled: true
```

---

## Server Management

### Startup Behaviour

```mermaid
sequenceDiagram
    participant Spark
    participant Config
    participant Server1
    participant Server2

    Spark->>Config: Load mcp_config
    Config->>Spark: Server definitions

    par Connect to servers
        Spark->>Server1: Connect (stdio)
        Server1->>Spark: Tool list
    and
        Spark->>Server2: Connect (http)
        Server2->>Spark: Tool list
    end

    Spark->>Spark: Merge tool lists
    Spark->>Spark: Resolve duplicates
```

### Connection Status Display

On startup, Spark displays MCP server status:

```
MCP Servers
─────────────────────────────────────────
✓ filesystem    (STDIO) - 6 tools
✓ github        (STDIO) - 12 tools
✗ database      (HTTP)  - Connection failed

Available Tools:
  filesystem:
    - list_files_recursive
    - search_files
    - read_file_text
    - read_file_binary
    - write_file
    - create_directories

  github:
    - create_issue
    - list_issues
    - ...
```

### Per-Conversation Control

Each conversation can enable/disable servers independently:

```
> mcpservers

MCP Server Status
─────────────────────────────────────────
1. [✓] filesystem - 6 tools
2. [✓] github - 12 tools
3. [✗] database - 4 tools

Toggle server (1-3) or [q]uit: 3
✓ database enabled
```

Changes persist when conversation is reloaded.

---

## Tool Discovery

### Automatic Tool Selection

Spark intelligently selects relevant tools:

```mermaid
flowchart TD
    MSG[User Message] --> ANALYSE[Analyse Context]
    ANALYSE --> MATCH[Match Tool Keywords]
    MATCH --> FILTER[Filter by Enabled Servers]
    FILTER --> LIMIT[Limit to max_tool_selections]
    LIMIT --> SEND[Send to LLM]
```

### Tool Limits

```yaml
conversation:
  max_tool_selections: 30    # Max tools per request
  max_tool_iterations: 25    # Max consecutive tool calls
```

### Duplicate Tool Names

When multiple servers have tools with the same name, Spark auto-prefixes:

| Original | Server | Becomes |
|----------|--------|---------|
| `search` | elasticsearch | `elasticsearch__search` |
| `search` | database | `database__search` |

The prefix is transparent to the LLM and removed before execution.

---

## Tool Execution

### Execution Flow

```mermaid
sequenceDiagram
    participant LLM
    participant Spark
    participant Permission
    participant Server
    participant Audit

    LLM->>Spark: tool_use request
    Spark->>Permission: Check permission

    alt First Time Use
        Permission->>User: Request permission
        User->>Permission: Allow/Deny
    end

    alt Allowed
        Spark->>Server: Execute tool
        Server->>Spark: Result
        Spark->>Audit: Log transaction
        Spark->>LLM: tool_result
    else Denied
        Spark->>LLM: tool_result (error)
    end
```

### Tool Use Loop

The LLM can chain multiple tool calls:

```
User: Analyse all Python files in src/

LLM: I'll examine the Python files.
     [Tool: list_files_recursive path="src"]

     Found 15 Python files. Let me read the main ones.
     [Tool: read_file_text path="src/main.py"]
     [Tool: read_file_text path="src/core.py"]
     [Tool: read_file_text path="src/utils.py"]

     Based on my analysis...
```

### Iteration Limits

Prevent infinite loops:

```yaml
conversation:
  max_tool_iterations: 25  # Max consecutive tool calls
```

After reaching the limit:
- Current tool sequence completes
- Warning displayed to user
- Conversation continues normally

---

## Built-in Tools

Spark includes built-in filesystem tools (no MCP server needed):

### Configuration

```yaml
embedded_tools:
  filesystem:
    enabled: true
    allowed_path: ./working
    access_mode: read_write  # or 'read'
```

### Available Tools

| Tool | Mode | Description |
|------|------|-------------|
| `list_files_recursive` | read | List all files and directories |
| `search_files` | read | Search by filename pattern |
| `read_file_text` | read | Read text file contents |
| `read_file_binary` | read | Read binary files (base64) |
| `write_file` | read_write | Write content to file |
| `create_directories` | read_write | Create directory structure |

### Security

All paths validated to stay within `allowed_path`:

```mermaid
flowchart TD
    REQ[Tool Request] --> VALIDATE{Path Within allowed_path?}
    VALIDATE -->|No| REJECT[Reject Request]
    VALIDATE -->|Yes| MODE{Access Mode?}
    MODE -->|read| READ_CHECK{Read Tool?}
    MODE -->|read_write| EXECUTE[Execute Tool]
    READ_CHECK -->|Yes| EXECUTE
    READ_CHECK -->|No| REJECT
```

---

## Audit Logging

### What's Logged

Every MCP tool execution is logged:

| Field | Description |
|-------|-------------|
| `conversation_id` | Which conversation |
| `user_prompt` | Triggering user message |
| `tool_name` | Tool that was called |
| `tool_server` | Server that provided tool |
| `tool_input` | Parameters sent to tool |
| `tool_response` | Response from tool |
| `is_error` | Whether call failed |
| `execution_time_ms` | Duration |
| `timestamp` | When it occurred |
| `user_guid` | Which user |

### Viewing Audit Logs

```
> mcpaudit

MCP Transaction Audit
─────────────────────────────────────────
1. 2024-12-05 10:30:15 | filesystem | list_files_recursive
   Input: {"path": "./src"}
   Duration: 45ms
   Status: Success

2. 2024-12-05 10:30:18 | filesystem | read_file_text
   Input: {"path": "./src/main.py"}
   Duration: 12ms
   Status: Success

Options: [f]ilter, [e]xport, [q]uit:
```

### Filtering

Filter by various criteria:

- **Server**: Show only specific server's transactions
- **Tool**: Show only specific tool calls
- **Date Range**: Show transactions within date range
- **Status**: Show only errors or successes

### Exporting

Export to CSV for compliance or analysis:

```
Options: [f]ilter, [e]xport, [q]uit: e
Export filename: audit_2024_12.csv
✓ Exported 150 transactions to audit_2024_12.csv
```

---

## Common MCP Servers

### Official Servers

| Server | Description | Install |
|--------|-------------|---------|
| mcp-server-filesystem | File access | `uvx mcp-server-filesystem` |
| mcp-server-github | GitHub API | `uvx mcp-server-github` |
| mcp-server-postgres | PostgreSQL | `uvx mcp-server-postgres` |
| mcp-server-sqlite | SQLite | `uvx mcp-server-sqlite` |

### Example Configurations

#### Filesystem Server

```yaml
- name: filesystem
  transport: stdio
  command: uvx
  args:
    - mcp-server-filesystem
    - /home/user/projects
  enabled: true
```

#### GitHub Server

```yaml
- name: github
  transport: stdio
  command: uvx
  args:
    - mcp-server-github
  env:
    GITHUB_TOKEN: ghp_xxxxxxxxxxxx
  enabled: true
```

#### PostgreSQL Server

```yaml
- name: postgres
  transport: stdio
  command: uvx
  args:
    - mcp-server-postgres
    - postgresql://user:pass@localhost/mydb
  enabled: true
```

---

## Troubleshooting

### Server Won't Connect

1. **Check command exists**: Verify the command is installed
2. **Check path**: Ensure args contain valid paths
3. **Check permissions**: Verify access to resources
4. **Check logs**: Review Spark log files for errors

### Tools Not Appearing

1. **Verify server enabled**: Check `enabled: true` in config
2. **Check conversation state**: Use `mcpservers` to verify
3. **Restart Spark**: Some changes require restart

### Tool Execution Fails

1. **Check permissions**: Tool may need approval
2. **Verify parameters**: Check tool received correct input
3. **Review audit log**: Use `mcpaudit` to see error details

### Duplicate Tool Names

If you see warnings about duplicate tools:

```
⚠️  Duplicate tool name 'search' from servers: elasticsearch, database
    Renamed to: elasticsearch__search, database__search
```

This is automatic - no action needed.

---

## Best Practices

### Security

1. **Limit permissions**: Use `read` mode unless write needed
2. **Restrict paths**: Set `allowed_path` to minimum necessary
3. **Review audit logs**: Regularly check for unexpected activity
4. **Use tool permissions**: Enable approval prompts in production

### Performance

1. **Limit tool count**: Keep `max_tool_selections` reasonable
2. **Disable unused servers**: Don't connect servers you don't need
3. **Use local transport**: Stdio is faster than HTTP for local servers

### Reliability

1. **Handle failures gracefully**: LLM will adapt if tool fails
2. **Set reasonable timeouts**: Configure server timeouts appropriately
3. **Monitor connections**: Watch for disconnected servers

---

## Next Steps

- [Features Guide](features.md) - All Spark features
- [Security](security.md) - Security best practices
- [Configuration](configuration.md) - Full config reference
