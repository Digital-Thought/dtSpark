# Changelog

All notable changes to Spark will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [1.1.0a25] - 2026-02-16

### Fixed
- **SonarQube Code Quality Issues** - Resolved all code quality violations
  - S1192: Extracted duplicate string literals into constants
  - S3457: Removed f-string prefix from strings without replacements
  - S1066: Merged collapsible nested if statements
  - S5886: Fixed return type hint mismatch in `get_compaction_status()`
  - S1874: Replaced deprecated `substr()` with `substring()` in JavaScript
  - S7735: Fixed negated conditions in ternary expressions

---

## [1.1.0a24] - 2026-02-16

### Added
- **Cancel Request Feature** - Users can now cancel long-running requests in the web UI
  - Send button transforms to Cancel button while processing
  - Press Escape key to cancel from keyboard
  - Visual feedback with pulsing animation on Cancel button
  - Shows "Request cancelled" message when cancelled

- **Timestamps on Tool Calls/Results** - Tool call and result bubbles now display timestamps
  - Tool calls show timestamp when invoked
  - Tool results show timestamp when received
  - Consistent styling with other message timestamps

### Fixed
- **Compaction Tool Use/Result Pairing** - Fixed API error "unexpected tool_use_id found in tool_result blocks"
  - Added `_find_in_flight_tool_use_messages()` to identify pending tool_use blocks
  - Modified `_store_compaction_results()` to preserve messages with pending tool_use
  - Prevents compaction from breaking tool_use/tool_result pairs during emergency compaction

- **Web Search Token Bloat** - Fixed context window exhaustion from web search (3K → 1M+ tokens)
  - Removed `encrypted_content` field from web search result storage
  - Only stores essential fields: url, title, page_age
  - Prevents rapid context explosion when using web search

- **Embedded Tools Validation** - Improved error messages when content is missing
  - `write_file`: Now provides example when content parameter is missing
  - `create_word_document`: Made content required in schema, added validation with examples
  - Helps model understand required parameters and correct tool usage

- **Compaction Status Indicator Not Appearing** - Fixed indicator not displaying during chunked compaction
  - Progress events now create indicator if it doesn't exist (handles missed 'start' events)
  - Complete/warning/error events also create indicator if needed
  - Ensures visual feedback appears even if some SSE events are missed during rapid updates

---

## [1.1.0a23] - 2026-02-14

### Added
- **Chunked Compaction for Large Conversations** - Fallback strategy when full compaction exceeds rate limits
  - Automatically splits large conversations into chunks that fit within rate limits
  - Compacts each chunk separately, then combines summaries
  - Prevents "compaction exceeds rate limit" errors that would lock out conversations

- **Emergency Truncation Fallback** - Last resort when even chunked compaction fails
  - Keeps the most recent messages up to 20% of context window
  - Adds truncation notice explaining what was removed
  - Prevents complete conversation lockout in extreme cases

### Fixed
- Conversations no longer get stuck when they grow too large for single-pass compaction
- Anthropic Direct rate limit errors during compaction now trigger chunked fallback

---

## [1.1.0a22] - 2026-02-14

### Added
- **Compaction Status Indicator in Web UI** - Visual feedback when context compaction occurs
  - Displays "Context compacting..." indicator with spinner when compaction starts
  - Shows progress messages during compaction analysis
  - Displays completion summary with token reduction stats and elapsed time
  - Auto-hides after 5 seconds on completion
  - Warning/error states for compaction issues
  - Styled indicator with cyan accent for in-progress, green for complete

### Fixed
- Web interface now properly connected to context compactor for status updates

---

## [1.1.0a21] - 2026-02-14

### Added
- **Security Warning Modal in Web UI** - Prompt inspection security warnings now display as modal dialogs
  - When security concerns are detected in user input, a modal dialog appears instead of CLI prompts
  - Users can choose to proceed or cancel directly in the web interface
  - Displays severity level, detected issues, explanation, and matched patterns
  - Styled with appropriate warning/danger colours based on severity

### Changed
- **Compaction Settings Model Dropdown** - Model selection now uses a dropdown instead of text input
  - Fetches available models from API and displays them in a select dropdown
  - Shows model provider information similar to new conversation dialog
  - "Use conversation model" option for default behaviour
  - Model dropdown is disabled when compaction model is locked via configuration

---

## [1.1.0a20] - 2026-02-13

### Fixed
- **Web Search JSON Serialisation Error** - Fix "Object of type WebSearchResultBlock is not JSON serializable" error
  - Convert Anthropic SDK `WebSearchResultBlock` objects to plain dictionaries before JSON serialisation
  - Properly extract `url`, `title`, `page_age`, and `encrypted_content` fields from search results
  - Also handle `server_tool_use` input objects that may be SDK types

---

## [1.1.0a19] - 2026-02-12

### Added
- **Word Document Rich Text Formatting** - Support for inline formatting in placeholder replacement values
  - `**bold**` for bold text
  - `*italic*` or `_italic_` for italic text
  - `__underline__` for underlined text
  - `` `code` `` for monospace/Courier New font (10pt)
  - Formatting works in both document body and table cells
- Updated `create_word_document` tool description to document formatting syntax for MCP clients

---

## [1.1.0a18] - 2026-02-12

### Added
- **Word Document List Formatting** - Automatic detection and formatting of lists in replacement text
  - Lines starting with `1.`, `2)`, etc. are converted to Word numbered lists (`List Number` style)
  - Lines starting with `-`, `*`, `•` are converted to Word bullet lists (`List Bullet` style)
  - Multi-line content creates proper separate paragraphs with appropriate styles
  - Works in both document body paragraphs and table cells

---

## [1.1.0a17] - 2026-02-12

### Fixed
- **Word Document Multi-line Content** - Replacement text with newlines now renders correctly
  - `\n` characters in replacement values are converted to Word line breaks (`w:br` elements)
  - Multi-line content in table cells handled properly
  - Preserves paragraph formatting while supporting multi-line text

---

## [1.1.0a16] - 2026-02-12

### Added
- **Configurable Compaction Settings** - Hierarchical control over context compaction
  - Global config option `compaction.model` to lock compaction model for all conversations
  - Global defaults for `compaction.threshold` and `compaction.summary_ratio`
  - Per-conversation commands: `/compaction`, `/compaction-model`, `/compaction-threshold`, `/compaction-ratio`
  - Database migration adds `compaction_model` and `compaction_summary_ratio` columns
- **Web Search Feedback** - Real-time visibility into web search operations
  - "Searching the web" indicator with spinner when web search starts
  - Collapsible source list showing URLs, titles, and page dates accessed
  - SSE events `web_search_start` and `web_search_results` for streaming updates
  - Stores full content blocks (including `server_tool_use` and `web_search_tool_result`) in database

### Fixed
- **LLM API Error Display** - Errors now display in distinct error bubbles instead of assistant messages
  - Structured error responses with `error_type`, `error_code`, and `suggestion` fields
  - Context-aware suggestions (e.g., "Your account has insufficient credits" for billing errors)
  - Visual styling with red gradient background and amber suggestion box
- **Word Document Template Replacement** - Fix placeholder replacement not working
  - Placeholders split across Word XML runs now replaced correctly
  - Tool now reports only placeholders that were actually found and replaced
  - Added `placeholders_not_found` field to identify missing placeholders in templates
  - Placeholder keys used exactly as provided (include delimiters like `<>` or `{{}}` in keys)

---

## [1.1.0a12] - 2026-02-09

### Added
- **Anthropic Web Search Integration** - AI can now search the web for current information
  - Hierarchical control: global configuration, per-conversation setting, per-request toggle
  - Web search enabled via setup wizard or `llm_providers.anthropic.web_search.enabled` config
  - When creating a conversation with Anthropic model, checkbox to enable web search appears
  - Per-request toggle button in chat UI to enable/disable web search for individual messages
  - Optional domain filtering (`allowed_domains`, `blocked_domains`) and user location settings
  - Pricing: $0.01 per search + standard token costs
- Database migration adds `web_search_enabled` column to conversations table

### Changed
- LLM provider `invoke_model` methods now accept `**kwargs` for provider-specific parameters

---

## [1.1.0a11] - 2026-02-08

### Added
- `predefined_conversations.allow_new_conversations` configuration option to control whether users can create new ad-hoc conversations
  - When disabled, "Start New Conversation" is hidden from CLI menu, Web UI navigation, main menu, and conversations page
  - `POST /api/conversations` returns 403 when disabled
  - `GET /conversations/new` redirects to conversations list when disabled
  - Existing and predefined conversations remain fully accessible

### Changed
- Web UI: Tool calls now appear on the left side (like assistant messages), tool results on the right side (like user messages)
- Web UI: Tool calls and results are now collapsible by default, showing just the summary (e.g., "Tool Call: tool_name")
- Web UI: Added copy-to-clipboard and expand/collapse icons to tool call and result bubbles

### Fixed
- Fixed `tool_permissions.auto_approve` setting not being passed to ConversationManager, causing tools to prompt for approval even when auto-approve was enabled during setup
- Improved embedded tool descriptions to prevent LLM from using Microsoft Office tools (Word, Excel, PowerPoint) for text-based file formats (HTML, CSS, JS, etc.)
  - `write_file` description now explicitly lists supported text-based formats
  - Office tool descriptions now clarify they should only be used for their specific binary formats
- Improved `create_word_document`, `create_excel_document`, and `create_powerpoint_document` tool descriptions with:
  - Clear warnings that content parameters are required to avoid empty documents
  - Inline examples showing the correct parameter structure
  - Better documentation of required vs optional parameters
- Removed overly generic `document` keyword from tool selector categories to reduce false matches

### Changed
- Updated dtPyAppFramework dependency to >=4.2.1

---

## [1.1.0a5] - 2026-01-31

### Added
- Browser heartbeat auto-shutdown: application automatically shuts down when browser tab is closed
  - Configurable heartbeat interval and timeout via `interface.web.browser_heartbeat` settings
- `autonomous_actions.enabled` configuration option to enable/disable autonomous actions globally
  - When disabled, Actions navigation is hidden from both Web UI and CLI menus
  - Action scheduler initialisation is skipped entirely when disabled

### Fixed
- Send button now stays disabled throughout the entire LLM response stream (was re-enabling prematurely)
- SSL certificate validation vulnerabilities marked with NOSONAR for intentional config-driven bypass
- `asyncio.CancelledError` not re-raised in MCP manager connection handling
- Pricing fallback method now correctly returns `False` when using fallback data
- Background tasks saved to variables to prevent premature garbage collection (web server)
- Synchronous file operations replaced with async equivalents in async endpoints
- User-controlled data sanitised before logging in web endpoints

### Changed
- Refactored 40+ functions to reduce cognitive complexity below SonarCloud threshold (15)
- Extracted duplicate string literals into module-level constants (pricing, model IDs)
- Replaced bare `except:` clauses with specific exception types across codebase
- Modernised JavaScript DOM API usage (optional chaining, `.remove()`, `.dataset`)
- Replaced ARIA roles with semantic HTML elements for improved accessibility
- Merged duplicate CSS selectors and improved colour contrast for WCAG AA compliance
- Removed unused function parameters and empty f-strings across codebase
- Removed commented-out code blocks

---

## [1.1.0a3] - 2026-01-29

### Fixed
- Web UI now enforces `mandatory_model` and `mandatory_provider` configuration settings
- Model selection is locked and displays info message when mandatory model is configured
- Change Model command in chat blocked when model is locked via configuration
- `mandatory_provider` not defined error in predefined conversation synchronisation (NameError)
- Inline instruction text (e.g., "You are a helpful assistant.") no longer triggers ResourceManager file lookup errors

### Changed
- `/api/models` endpoint now returns mandatory model configuration alongside model list
- `POST /api/conversations` enforces mandatory model by overriding submitted model_id

---

## [1.1.0a2] - 2026-01-28

### Fixed
- Create Word document tool now gracefully handles invalid/custom styles by falling back to 'Normal' style
- Remove settings diagnostics that were logging sensitive API keys in plain text (security fix)

---

## [1.1.0a1] - 2026-01-28

### Added

#### Web UI Commands
- Change Instructions command to edit conversation system prompt
- Copy Last Response command to copy assistant's last message to clipboard
- Delete Attached Files command to remove files from conversation
- Delete Conversation command

#### API Endpoints
- `POST /command/instructions` endpoint for updating conversation instructions
- `POST /command/deletefiles` endpoint for deleting attached files
- Info endpoint now returns `instructions` field and full `attached_files` data with IDs and sizes

### Fixed
- Document and archive tools not loading when enabled in config (config not passed to ConversationManager)

---

## [1.0.11]

### Added

#### MS Office Document Tools
- Read Word documents (.docx) - extract text, paragraphs, and tables
- Read Excel spreadsheets (.xlsx) - extract sheets and data with configurable row limits
- Read PowerPoint presentations (.pptx) - extract slides, text, and speaker notes
- Read PDF documents (.pdf) - extract text by page with configurable page limits
- Create Word documents from content or templates with placeholder substitution
- Create Excel spreadsheets from structured data or templates
- Create PowerPoint presentations from slides or templates
- File metadata tool (get_file_info) - get MIME type, size, and extension
- Template support with `{{placeholder}}` syntax for document creation

#### Archive Tools
- List archive contents (.zip, .tar, .tar.gz, .tgz)
- Read specific files from archives without extraction
- Extract archives to disk (when access_mode is read_write)

#### Tool Selector Categories
- Added 'documents' category for MS Office and PDF related queries
- Added 'archives' category for archive-related queries

### Changed
- Setup wizard now prompts for document and archive tool configuration
- Web UI Integrations tab now dynamically loads embedded tools from API

### Fixed
- Web UI Integrations tab was showing hardcoded embedded tools instead of actual enabled tools
- Added `/api/embedded-tools` endpoint for dynamic tool discovery

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
| 1.1.0a12 | Anthropic Web Search integration with hierarchical control (global, conversation, request) |
| 1.1.0a11 | Allow new conversations toggle, tool call/result UI improvements, auto-approve fix, Office tool descriptions |
| 1.1.0a5 | SonarCloud remediation, browser heartbeat auto-shutdown, autonomous actions config, accessibility fixes |
| 1.1.0a3 | Enforce mandatory model in Web UI, fix predefined conversation errors |
| 1.1.0a2 | Fix create_word_document style handling, remove sensitive data from logs |
| 1.1.0a1 | Web UI commands (instructions, copy, delete files/conversation), document tools config fix |
| 1.0.11 | MS Office document tools, archive tools, Web UI embedded tools fix |
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
