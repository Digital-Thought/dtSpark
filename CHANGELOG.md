# Changelog

All notable changes to Spark will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nothing yet

### Changed
- Nothing yet

### Fixed
- Nothing yet

---

## [1.0.10]

### Fixed
- Setup wizard now creates config.yaml directly in user data directory (not in config subfolder)

---

## [1.0.9]

### Changed
- Setup wizard now writes secrets to `secrets.yaml` instead of directly to secrets manager
  - Secrets are automatically ingested on next application startup
  - `secrets.yaml` is deleted after successful ingestion
- Setup wizard config location now respects `CONTAINER_MODE` environment variable:
  - If `CONTAINER_MODE=true`: config created in `./config/config.yaml` (working directory)
  - Otherwise: config created directly in user data directory

---

## [1.0.8]

### Added
- Setup wizard now supports AWS Bedrock authentication method selection:
  - SSO Profile (recommended for interactive use)
  - IAM Access Keys (recommended for autonomous actions - no timeout)
  - Session Credentials (temporary credentials with token)
- AWS account name and account ID fields for reference/logging
- Advisement in wizard about SSO/session timeouts affecting autonomous actions
- AWS credentials securely stored in secrets manager with SEC/ references

---

## [1.0.7]

### Fixed
- Setup wizard now correctly writes Anthropic API key reference to config.yaml (was writing null)

---

## [1.0.6]

### Security
- Setup wizard now masks sensitive input (API keys, database passwords) during entry
- Secrets are stored securely via dtPyAppFramework secrets_manager rather than in plain text config

---

## [1.0.5]

### Changed
- Removed forced container mode - application now uses dtPyAppFramework default locations for configuration files

---

## [1.0.4]

### Added
- Daemon mode for background execution of scheduled autonomous actions
- Daemon CLI commands: `spark daemon start`, `spark daemon stop`, `spark daemon status`
- Scheduler coordination - daemon handles all scheduled execution, UI handles manual "Run Now"
- Warning displayed in CLI and web UI when daemon is not running but scheduled actions exist
- Web API endpoint `/daemon/status` to check daemon status

### Changed
- Scheduled actions now only execute via daemon process (not web UI)
- Session cookies now properly support SSL and configurable timeout

### Fixed
- LLM provider registration in daemon (was calling non-existent `add_provider` method)
- Embedded tools not appearing in AI-assisted action creation
- Session cookie not persisting with `session_timeout_minutes: 0` configuration

---

## [1.0.3]

### Added

#### MCP Remote Server Support
- HTTP (Streamable HTTP) transport for remote MCP server connections
- SSE (Server-Sent Events) transport for streaming MCP connections
- Authentication support for remote MCP servers:
  - Bearer token authentication (`Authorization: Bearer <token>`)
  - API key authentication (configurable header name)
  - HTTP Basic authentication (username/password)
  - Custom headers for complex authentication schemes
- SSL certificate verification control (`ssl_verify` option)
  - Allows connection to servers with self-signed certificates
  - Warning logged when SSL verification is disabled

### Fixed
- MCP HTTP connection error handling for failed connections
- Graceful handling of `asyncio.CancelledError` during connection failures
- Proper resource cleanup for failed HTTP/SSE connections

---

## [1.0.2]

### Added

#### Autonomous Actions (Scheduled AI Tasks)
- Create scheduled AI tasks that run automatically
- One-off scheduling (specific date/time) or recurring (cron expressions)
- Two creation methods:
  - Manual wizard with step-by-step configuration
  - Prompt-driven creation with LLM assistance
- Context modes: fresh (stateless) or cumulative (maintains history)
- Per-action tool permissions with snapshotting
- Automatic failure handling with configurable max failures
- Action execution history with detailed run logs
- Web API endpoints for action management
- CLI menu for action administration

#### Action Context Compaction
- Lightweight context compaction for long-running autonomous actions
- Configurable thresholds for action context management
- Emergency compaction support during tool iteration loops

### Changed
- Updated configuration templates with autonomous action settings
- Enhanced CLI documentation

---

## [1.0.1]

### Added

#### Rate Limit Awareness
- Pre-request rate limit checking for LLM providers
- Rate limit information exposed via `get_rate_limits()` method
- Anthropic Direct API: 30,000 input tokens per minute (default tier)

### Fixed
- Context compaction infinite retry loop when request exceeds provider rate limits
- Compaction now skips with warning if estimated tokens exceed provider limits
- Prevents failed compaction attempts that would never succeed

---

## [1.0.0]

### Added

#### Multi-Provider LLM Support
- AWS Bedrock integration with Claude, Llama, Mistral, Cohere, Titan, and AI21 models
- Anthropic Direct API support with rate limit handling and exponential backoff
- Ollama integration for local model execution
- Model switching mid-conversation with per-model token tracking
- Model locking via configuration for standardisation

#### Dual Interface
- Rich CLI terminal interface with Markdown rendering
- Web browser interface with real-time SSE streaming
- One-time authentication code for web security
- Dark theme support for web interface

#### Conversation Management
- Persistent conversation storage with multiple database backends
- SQLite (default), MySQL/MariaDB, PostgreSQL, Microsoft SQL Server support
- Conversation export to Markdown, HTML, and CSV formats
- File attachments for conversations
- Per-conversation settings (max_tokens, MCP server states)

#### Intelligent Context Compaction
- LLM-driven context summarisation with selective preservation
- Model-specific context window awareness
- Automatic compaction at configurable thresholds
- Numerical data extraction and preservation during compaction
- Emergency compaction during tool use sequences

#### Tool Integration
- MCP (Model Context Protocol) server support
- Stdio and HTTP transport options
- Built-in filesystem tools with path validation
- Tool permission system with persistent storage
- Per-conversation MCP server enable/disable
- Automatic duplicate tool name resolution

#### Security Features
- Prompt injection detection (basic, standard, strict levels)
- LLM-based semantic analysis for strict inspection
- MCP transaction audit logging with CSV export
- Tool execution permission prompts
- Multi-user data isolation via user_guid
- Path traversal prevention for filesystem tools

#### Token Management
- Independent input/output token tracking
- Rolling time window limits
- Warning thresholds at 75%, 85%, 95%
- Override mechanism for temporary limit increases
- Per-model usage breakdown

#### Developer Experience
- Interactive setup wizard (`spark --setup`)
- Automatic AWS SSO re-authentication
- Detailed error messages with suggestions
- Automatic retry for transient failures
- Comprehensive documentation

### Security
- One-time authentication codes for web interface
- SSL/TLS support with auto-generated certificates
- Localhost-only binding for web server
- Session timeout management
- Secure credential prompting (no plaintext storage)

---

## Version History

| Version | Description |
|---------|-------------|
| 1.0.10 | Fix config.yaml created in wrong directory |
| 1.0.9 | Secrets written to secrets.yaml, CONTAINER_MODE config path support |
| 1.0.8 | AWS Bedrock IAM/session authentication in setup wizard |
| 1.0.7 | Fix Anthropic API key not written to config |
| 1.0.6 | Secure secret input masking in setup wizard |
| 1.0.5 | Use default config locations instead of forced container mode |
| 1.0.4 | Daemon mode for scheduled action execution |
| 1.0.3 | MCP HTTP/SSE transport with authentication and SSL options |
| 1.0.2 | Autonomous actions for scheduled AI tasks |
| 1.0.1 | Rate limit protection for context compaction |
| 1.0.0 | Initial public release |

---

## Upgrade Notes

### Upgrading to 1.0.0

This is the initial release. For users of the pre-release version:

1. **Configuration**: Run `spark --setup` to generate new configuration
2. **Database**: Existing SQLite databases will auto-migrate
3. **Module name**: Import from `dtSpark` instead of `dtAWSBedrockCLI`

```bash
# Install new version
pip install --upgrade dtSpark

# Run setup wizard
spark --setup
```
