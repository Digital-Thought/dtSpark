# Unit Tests Documentation

This directory contains unit tests for the Spark application.

## Test Structure

The test suite is organised to mirror the source code structure in `src/dtSpark/`.

## Test Coverage

### Database Module Tests (`test_database.py`)
**Purpose**: Verify database operations for conversation storage and retrieval

**Test Cases**:
- Database initialisation and schema creation
- Conversation creation and retrieval
- Message storage and retrieval
- Token count tracking
- Rollup history recording
- Message marking as rolled up
- Conversation filtering (active/inactive)

**Key Scenarios Tested**:
- Creating conversations with valid data
- Adding messages to conversations
- Retrieving conversation history
- Updating token counts correctly
- Recording rollup operations
- Handling edge cases (empty conversations, non-existent IDs)

### AWS Authentication Module Tests (`test_aws_auth.py`)
**Purpose**: Verify AWS SSO authentication and session management

**Test Cases**:
- Authentication with valid SSO profile
- Authentication failure scenarios
- Session credential validation
- Client creation for AWS services
- Account information retrieval
- Expired token handling

**Key Scenarios Tested**:
- Successful authentication with configured profile
- Handling missing or invalid profiles
- Detecting expired credentials
- Creating boto3 clients for various services
- Retrieving AWS account details

### Bedrock Service Module Tests (`test_bedrock_service.py`)
**Purpose**: Verify interactions with AWS Bedrock foundation models

**Test Cases**:
- Listing available models
- Model selection and configuration
- Request formatting for different model providers (Claude, Titan, Llama, etc.)
- Response parsing from different model formats
- Token counting functionality
- Model invocation with various parameters

**Key Scenarios Tested**:
- Fetching model list from Bedrock
- Setting and retrieving current model
- Formatting requests for Anthropic Claude models
- Formatting requests for Amazon Titan models
- Parsing responses correctly
- Handling model invocation failures
- Token estimation accuracy

### Conversation Manager Tests (`test_conversation_manager.py`)
**Purpose**: Verify conversation management and automatic rollup functionality

**Test Cases**:
- Creating new conversations
- Loading existing conversations
- Adding user and assistant messages
- Token count tracking
- Automatic rollup triggering
- Message summarisation
- Rollup threshold detection
- Conversation history retrieval

**Key Scenarios Tested**:
- Creating conversations with model assignment
- Loading and resuming conversations
- Adding messages and updating token counts
- Triggering rollup at threshold
- Summarising old messages
- Preserving recent conversation context
- Reducing token count through rollup
- Handling rollup failures gracefully

### CLI Interface Tests (`test_cli_interface.py`)
**Purpose**: Verify command-line interface functionality

**Test Cases**:
- Menu display and selection
- User input handling
- Model selection interface
- Conversation selection interface
- Message display formatting
- Error and success message display
- Conversation information display
- Token usage visualisation

**Key Scenarios Tested**:
- Displaying menus correctly
- Handling valid and invalid user selections
- Formatting chat messages
- Displaying conversation history
- Showing token usage with visual indicators
- Handling multiline input
- Confirmation prompts

### Built-in Tools Tests (`test_builtin_tools.py`)
**Purpose**: Verify built-in tool functionality for date/time operations

**Test Cases**:
- Tool definition retrieval
- Tool execution with valid parameters
- Tool execution with invalid parameters
- Timezone validation
- Datetime formatting (ISO and human-readable)
- Timezone availability
- Error handling

**Key Scenarios Tested**:
- Retrieving built-in tool definitions
- Getting current datetime with default settings
- Getting datetime for specific timezones (UTC, Australia/Sydney)
- Formatting output in ISO 8601 format
- Formatting output in human-readable format
- Handling invalid timezone identifiers
- Executing unknown tool names
- Validating timezone strings
- Listing available timezones

**Built-in Tools Available**:
- `get_current_datetime` - Get current date/time with timezone awareness
  - Optional timezone parameter (e.g., 'UTC', 'Australia/Sydney')
  - Optional format parameter ('iso' or 'human')
  - Returns datetime information with timezone offset and Unix timestamp

**Dependencies**:
- `tzdata` - Required on Windows for timezone data (automatically installed)
- `zoneinfo` - Python standard library for timezone handling

### Tool Selector Tests (`test_tool_selector.py`)
**Purpose**: Verify intelligent tool selection for optimising token usage

**Test Cases**:
- Tool selector initialisation
- Category detection from user messages
- Category detection from conversation history
- Tool selection for specific categories (security, Docker, documentation, etc.)
- Multiple category detection and tool selection
- Diverse sample selection when no categories detected
- Maximum tool limit enforcement
- Built-in tools always included
- Duplicate tool handling

**Key Scenarios Tested**:
- Selecting security-related tools for security queries
- Selecting Docker tools for container queries
- Selecting documentation tools for note-taking queries
- Detecting multiple categories from complex queries
- Using conversation history to infer context
- Respecting maximum tool limit (prevents token overflow)
- Handling empty tool lists gracefully
- Always including built-in tools
- Preventing duplicate tool selection

**Token Usage Optimisation**:
- Reduces tools sent from 168 to ~30 per request
- Saves ~30,000 tokens per API call
- Intelligently selects relevant tools based on context
- Prevents max_tokens errors in conversations

### Status Indicator Tests (`test_status_indicator.py`)
**Purpose**: Verify animated progress indicator functionality for improved user experience

**Test Cases**:
- StatusIndicator context manager functionality
- Animated spinner display with elapsed time
- Status message updates during operations
- Elapsed time calculation accuracy
- CLIInterface integration

**Key Scenarios Tested**:
- Using StatusIndicator as context manager
- Using StatusIndicator with `with` statement
- Updating status message mid-operation
- Calculating and displaying elapsed time correctly
- Integration with CLIInterface.status_indicator() method

**User Experience Benefits**:
- Animated spinner provides visual feedback during long operations
- Real-time elapsed time display shows progress
- Completion message confirms operation finished
- Replaces static "⏳ Thinking..." with dynamic feedback
- Improves perceived responsiveness during AI model inference

**Implementation Details**:
- Uses Rich library's Spinner component with "dots" style
- Context manager pattern for automatic start/stop
- `update()` method allows changing message during operation
- Displays completion time when operation finishes
- Integrated into chat loop for model inference operations

### Web Interface Tests (`test_web_auth.py`, `test_web_session.py`)
**Purpose**: Verify web interface authentication and session management

**Authentication Tests** (`test_web_auth.py`):
- One-time code generation (8-character alphanumeric)
- Code validation with correct/incorrect codes
- Case-insensitive code validation
- Single-use enforcement (code invalidated after use)
- Code hashing for security (SHA-256)
- Code reset functionality
- Timestamp tracking

**Session Management Tests** (`test_web_session.py`):
- Session creation with secure random IDs (64 hex characters)
- Session validation with correct/incorrect IDs
- Session timeout enforcement (configurable minutes)
- Manual session invalidation
- Session replacement (single session at a time)
- Session information retrieval
- Last activity tracking and updates
- Remaining time calculation

**Key Security Features Tested**:
- Cryptographically secure random code generation
- One-time use enforcement prevents code reuse
- Session IDs use 32-byte secure random tokens
- Automatic session expiration after inactivity
- Single active session limitation
- Localhost-only access (enforced in server configuration)

**Web Interface Technology Stack**:
- FastAPI web framework
- Server-Sent Events (SSE) for real-time streaming
- Bootstrap 5 dark theme
- Jinja2 templates
- Session management with HTTP-only cookies

**Web Interface Feature Coverage**:
- All main menu operations (costs, new conversation, list conversations)
- Conversation creation and management
- Full chat interface with real-time streaming
- All CLI commands available in web UI
- Information panels (AWS account, costs, MCP servers)
- Markdown rendering for assistant responses
- File attachment support
- Conversation export (Markdown, HTML, CSV)

## Test MCP Server

**File**: `test_mcp_server.py`

**Purpose**: A simple MCP (Model Context Protocol) server for testing MCP integration

This test server provides 11 tools across different categories to verify that the MCP integration is working correctly with the AWS Bedrock CLI.

### Available Tools

**Mathematical Operations**:
- `add_numbers(a, b)` - Add two numbers together
- `multiply_numbers(a, b)` - Multiply two numbers together
- `calculate_percentage(value, total, decimals)` - Calculate percentage

**Text Manipulation**:
- `text_to_uppercase(text)` - Convert text to uppercase
- `text_to_lowercase(text)` - Convert text to lowercase
- `reverse_text(text)` - Reverse a text string
- `count_words(text)` - Count words in text

**Utility Tools**:
- `get_current_time(timezone)` - Get current date and time
- `create_greeting(name, formal)` - Create personalised greeting (Aussie style!)
- `concatenate_strings(strings, separator)` - Join strings together
- `server_info()` - Get information about the server

### Running the Test Server

**Standalone (for testing)**:
```bash
python tests/test_mcp_server.py
```

**With AWS Bedrock CLI**:

1. Edit `running/config/config.yaml`:
```yaml
mcp_config:
  enabled: true
  servers:
    - name: test-server
      transport: stdio
      command: python
      args:
        - ./tests/test_mcp_server.py
      enabled: true
```

2. Run the CLI:
```bash
python run_cli.py
```

3. The test server will automatically connect and its tools will be available to the AI model.

### Example Usage in Conversation

```
User: Can you add 123 and 456 for me?
AI: [Uses add_numbers tool]
AI: The sum of 123 and 456 is 579.

User: Now convert the text "hello world" to uppercase and reverse it
AI: [Uses text_to_uppercase and reverse_text tools]
AI: First I converted "hello world" to "HELLO WORLD", then reversed it to "DLROW OLLEH".

User: What's the current time?
AI: [Uses get_current_time tool]
AI: The current time is 2025-10-30 14:30:00.

User: Can you create an informal greeting for Bob?
AI: [Uses create_greeting tool]
AI: G'day, Bob! How are you going?
```

### Testing MCP Integration

To verify MCP integration is working:

1. Enable the test server in config as shown above
2. Start the application
3. Look for connection confirmation: "Connected to 1 MCP server(s)"
4. In a conversation, ask the AI to use one of the test tools
5. Check the logs for tool call messages

### Troubleshooting

- **Server won't start**: Ensure `mcp` package is installed (`pip install mcp`)
- **Tools not available**: Check that `enabled: true` in both `mcp_config` and the server config
- **Connection fails**: Check the logs in `running/logs/` for detailed error messages

## Running Tests

To run all tests:
```bash
python -m pytest tests/
```

To run tests with coverage:
```bash
python -m pytest --cov=src/dtSpark tests/
```

To run a specific test file:
```bash
python -m pytest tests/test_database.py
```

To run a specific test case:
```bash
python -m pytest tests/test_database.py::TestDatabase::test_create_conversation
```

## Test Dependencies

Tests require the following additional packages:
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-mock` - Mocking support
- `moto` - AWS service mocking

Install test dependencies:
```bash
pip install pytest pytest-cov pytest-mock moto
```

## Writing New Tests

When adding new functionality to the application, ensure corresponding unit tests are created following these guidelines:

1. **File Naming**: Test files should be named `test_<module_name>.py`
2. **Class Naming**: Test classes should be named `Test<ClassName>`
3. **Method Naming**: Test methods should be named `test_<scenario_description>`
4. **Documentation**: Each test should have a docstring explaining its purpose
5. **Isolation**: Tests should be independent and not rely on execution order
6. **Mocking**: External dependencies (AWS services, file system) should be mocked
7. **Assertions**: Use clear, descriptive assertion messages
8. **Coverage**: Aim for at least 80% code coverage

### Example Test Structure

```python
import pytest
from unittest.mock import Mock, patch
from dtSpark.module_name import ClassName


class TestClassName:
    """Test suite for ClassName functionality."""

    @pytest.fixture
    def mock_dependency(self):
        """Create a mock dependency for testing."""
        return Mock()

    def test_specific_functionality(self, mock_dependency):
        """
        Test that specific functionality works correctly.

        This test verifies that when X happens, Y is the expected result.
        """
        # Arrange
        instance = ClassName(mock_dependency)
        expected_result = "expected"

        # Act
        actual_result = instance.method_to_test()

        # Assert
        assert actual_result == expected_result
```

## Continuous Integration

Tests are automatically run in the CI/CD pipeline on:
- Pull request creation
- Commits to main branch
- Release tagging

All tests must pass before code can be merged.

## Test Coverage Goals

- **Overall Coverage**: Minimum 80%
- **Critical Modules**: Minimum 90%
  - Database operations
  - AWS authentication
  - Conversation manager
- **UI Components**: Minimum 70%
  - CLI interface

## Known Limitations

- Tests for AWS services use mocking and may not catch all integration issues
- Some rollup scenarios with very large conversations may need integration testing
- MCP server/client integration tests are pending implementation

## Future Test Additions

- Integration tests for complete conversation flows
- Performance tests for large conversation histories
- MCP server/client integration tests
- End-to-end tests with real Bedrock models (manual/scheduled)
- Load testing for concurrent conversations

## Contact

For questions about tests or to report test failures, please refer to the main project documentation.
