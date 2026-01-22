# Spark Documentation

Welcome to the Spark documentation. Spark (Secure Personal AI Research Kit) is a comprehensive multi-provider LLM interface designed for conversational AI with advanced tool integration capabilities.

## What is Spark?

Spark provides a unified interface to interact with large language models from multiple providers:

- **AWS Bedrock** - Access Claude, Llama, Mistral, Cohere, Titan, and other models through AWS
- **Anthropic Direct API** - Direct access to Claude models without AWS infrastructure
- **Ollama** - Run open-source models locally for privacy and offline use

## Key Capabilities

```mermaid
mindmap
  root((Spark))
    LLM Providers
      AWS Bedrock
      Anthropic API
      Ollama Local
    Interfaces
      CLI Terminal
      Web Browser
    Tool Integration
      MCP Servers
      Built-in Tools
      Filesystem Access
    Data Management
      SQLite
      MySQL
      PostgreSQL
      MSSQL
    Security
      Prompt Inspection
      Tool Permissions
      Audit Logging
```

## Documentation Contents

### Getting Started

- **[Installation Guide](installation.md)** - How to install Spark and its dependencies
- **[Configuration Reference](configuration.md)** - Complete guide to config.yaml settings

### Features

- **[Features Guide](features.md)** - Detailed documentation of all Spark features
- **[CLI Reference](cli-reference.md)** - Command-line options and chat commands
- **[Web Interface](web-interface.md)** - Using the browser-based interface

### Integration

- **[MCP Integration](mcp-integration.md)** - Connecting external tools via Model Context Protocol
- **[Security](security.md)** - Security features, prompt inspection, and best practices

## Quick Start

### 1. Install Spark

```bash
pip install dtSpark
```

### 2. Run Setup Wizard

```bash
spark --setup
```

### 3. Start Spark

```bash
spark
```

## Application Flow

```mermaid
flowchart TD
    START([Start]) --> SETUP{First Run?}
    SETUP -->|Yes| WIZARD[Run --setup Wizard]
    WIZARD --> CONFIG[Create config.yaml]
    CONFIG --> AUTH
    SETUP -->|No| AUTH[Authenticate]

    AUTH --> INIT[Initialise Components]
    INIT --> MENU{Main Menu}

    MENU -->|1| COSTS[View AWS Costs]
    MENU -->|2| NEW[New Conversation]
    MENU -->|3| LIST[List Conversations]
    MENU -->|4| QUIT([Exit])

    COSTS --> MENU
    NEW --> CHAT[Chat Loop]
    LIST --> SELECT[Select Conversation]
    SELECT --> CHAT

    CHAT --> MESSAGE[User Message]
    MESSAGE --> PROCESS[Process with LLM]
    PROCESS --> TOOLS{Tool Use?}
    TOOLS -->|Yes| EXECUTE[Execute Tools]
    EXECUTE --> CONTINUE
    TOOLS -->|No| CONTINUE[Continue]
    CONTINUE --> RESPONSE[Display Response]
    RESPONSE --> MORE{Continue?}
    MORE -->|Yes| MESSAGE
    MORE -->|No| MENU
```

## Architecture

```mermaid
graph TB
    subgraph "User Interfaces"
        CLI[CLI Interface<br/>Rich Terminal]
        WEB[Web Interface<br/>FastAPI + SSE]
    end

    subgraph "Core Application"
        APP[Application Core]
        CM[Conversation Manager]
        CC[Context Compactor]
    end

    subgraph "LLM Providers"
        LLM_MGR[LLM Manager]
        BEDROCK[AWS Bedrock<br/>Provider]
        ANTHROPIC[Anthropic Direct<br/>Provider]
        OLLAMA[Ollama<br/>Provider]
    end

    subgraph "Tool Integration"
        MCP_MGR[MCP Manager]
        TOOL_SEL[Tool Selector]
        BUILTIN[Built-in Tools]
    end

    subgraph "Data Layer"
        DB[Database<br/>Abstraction]
        SQLITE[(SQLite)]
        MYSQL[(MySQL)]
        PGSQL[(PostgreSQL)]
        MSSQL[(MSSQL)]
    end

    subgraph "Security"
        INSPECT[Prompt Inspector]
        PERMS[Tool Permissions]
        AUDIT[Audit Logger]
    end

    CLI --> APP
    WEB --> APP
    APP --> CM
    CM --> CC
    CM --> LLM_MGR
    LLM_MGR --> BEDROCK
    LLM_MGR --> ANTHROPIC
    LLM_MGR --> OLLAMA
    CM --> MCP_MGR
    MCP_MGR --> TOOL_SEL
    CM --> BUILTIN
    CM --> DB
    DB --> SQLITE
    DB --> MYSQL
    DB --> PGSQL
    DB --> MSSQL
    CM --> INSPECT
    CM --> PERMS
    CM --> AUDIT
```

## Support

- **Issues**: [GitHub Issues](https://github.com/digital-thought/dtSpark/issues)
- **Email**: matthew@digital-thought.org

---

*Spark - Secure Personal AI Research Kit*
*Copyright 2024-2025 Matthew Westwood-Hill*
