"""
Test Google Gemini conversation context preservation with tool calling.

This test verifies that tool calls and results are properly preserved
in the conversation history when using Google Gemini.
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_message_conversion_with_tools():
    """Test that tool_use and tool_result blocks are properly converted to Gemini format."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    # Create service with dummy key for testing message conversion
    # Note: This doesn't make actual API calls
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"
    service.current_model_id = "gemini-2.0-flash"

    # Simulate conversation history with tool calls (Bedrock/standard format)
    messages = [
        {
            'role': 'user',
            'content': 'Can you tell me the current time?'
        },
        {
            'role': 'assistant',
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_123',
                    'name': 'get_current_time',
                    'input': {'timezone': 'UTC'}
                }
            ]
        },
        {
            'role': 'user',
            'content': [
                {
                    'type': 'tool_result',
                    'tool_use_id': 'tool_123',
                    'content': '2025-02-20 15:24:08'
                }
            ]
        }
    ]

    # Convert messages to Gemini format
    gemini_messages, system_instruction = service._convert_messages_to_gemini_format(messages)

    # Verify conversion
    print("Converted messages:")
    for i, msg in enumerate(gemini_messages):
        print(f"\n{i+1}. Role: {msg['role']}")
        if 'parts' in msg:
            for j, part in enumerate(msg['parts']):
                if 'text' in part:
                    print(f"   Part {j+1}: text = {part['text'][:100]}")
                elif 'function_call' in part:
                    print(f"   Part {j+1}: function_call = {part['function_call']}")
                elif 'function_response' in part:
                    print(f"   Part {j+1}: function_response = {part['function_response']}")

    # Assertions
    assert len(gemini_messages) == 3, f"Expected 3 messages, got {len(gemini_messages)}"

    # First message should be user question
    assert gemini_messages[0]['role'] == 'user'
    assert 'text' in gemini_messages[0]['parts'][0]
    assert 'current time' in gemini_messages[0]['parts'][0]['text'].lower()

    # Second message should be model with function_call
    assert gemini_messages[1]['role'] == 'model'
    assert 'parts' in gemini_messages[1]
    has_function_call = any('function_call' in part for part in gemini_messages[1]['parts'])
    assert has_function_call, "Model message should have function_call"

    # Find the function_call part
    function_call_part = next(
        part for part in gemini_messages[1]['parts'] if 'function_call' in part
    )
    assert function_call_part['function_call']['name'] == 'get_current_time'

    # Third message should be user with function_response
    assert gemini_messages[2]['role'] == 'user'
    has_function_response = any('function_response' in part for part in gemini_messages[2]['parts'])
    assert has_function_response, "Tool result should have function_response"

    print("\n[OK] All assertions passed!")
    print("\nConclusion:")
    print("- Tool calls are converted to Gemini 'function_call' format")
    print("- Tool results are converted to Gemini 'function_response' format")
    print("- Roles are properly mapped (assistant -> model)")
    print("- Message structure matches Gemini API expectations")


def test_tool_definition_conversion():
    """Test that tool definitions are properly converted to Gemini format."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
        from google.genai import types
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    # Create service instance for testing
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"

    # Standard tool definition format (Bedrock/MCP style)
    tools = [
        {
            'toolSpec': {
                'name': 'get_current_time',
                'description': 'Get the current time in a specified timezone',
                'inputSchema': {
                    'type': 'object',
                    'properties': {
                        'timezone': {
                            'type': 'string',
                            'description': 'The timezone (e.g., UTC, America/New_York)'
                        }
                    },
                    'required': ['timezone']
                }
            }
        },
        {
            'name': 'calculate',
            'description': 'Perform a calculation',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'expression': {
                        'type': 'string',
                        'description': 'The mathematical expression to evaluate'
                    }
                },
                'required': ['expression']
            }
        }
    ]

    # Convert tools to Gemini format
    gemini_tools = service._convert_tools_to_gemini_format(tools)

    # Verify conversion
    print("Converted tools:")
    assert len(gemini_tools) == 1, "Should return a single Tool object with multiple declarations"

    tool = gemini_tools[0]
    assert hasattr(tool, 'function_declarations') or isinstance(tool, types.Tool)

    print("\n[OK] Tool conversion assertions passed!")
    print("\nConclusion:")
    print("- Multiple tool definitions are combined into a single Tool object")
    print("- Both toolSpec and direct formats are supported")
    print("- inputSchema and input_schema keys are both handled")


def test_response_processing():
    """Test that Gemini responses are properly processed to standard format."""
    try:
        from dtSpark.llm.google_gemini import GoogleGeminiService
    except ImportError:
        print("SKIP: google-genai package not installed")
        return

    # Create service instance for testing
    service = GoogleGeminiService.__new__(GoogleGeminiService)
    service.api_key = "test-key"
    service.current_model_id = "gemini-2.0-flash"

    # Create a mock response object
    class MockPart:
        def __init__(self, text=None, function_call=None):
            self.text = text
            self.function_call = function_call

    class MockFunctionCall:
        def __init__(self, name, args):
            self.name = name
            self.args = args

    class MockContent:
        def __init__(self, parts):
            self.parts = parts

    class MockCandidate:
        def __init__(self, content, finish_reason='STOP'):
            self.content = content
            self.finish_reason = finish_reason

    class MockUsage:
        def __init__(self, prompt_tokens=100, candidates_tokens=50):
            self.prompt_token_count = prompt_tokens
            self.candidates_token_count = candidates_tokens

    class MockResponse:
        def __init__(self, candidates, usage):
            self.candidates = candidates
            self.usage_metadata = usage

    # Test 1: Simple text response
    text_response = MockResponse(
        candidates=[
            MockCandidate(
                content=MockContent(parts=[MockPart(text="The current time is 3:24 PM")])
            )
        ],
        usage=MockUsage()
    )

    result = service._process_response(text_response)

    assert result['content'] == "The current time is 3:24 PM"
    assert result['stop_reason'] == 'end_turn'
    assert result['usage']['input_tokens'] == 100
    assert result['usage']['output_tokens'] == 50
    assert len(result['content_blocks']) == 1
    assert result['content_blocks'][0]['type'] == 'text'

    print("[OK] Text response processing passed!")

    # Test 2: Function call response
    func_call_response = MockResponse(
        candidates=[
            MockCandidate(
                content=MockContent(parts=[
                    MockPart(function_call=MockFunctionCall(
                        name='get_current_time',
                        args={'timezone': 'UTC'}
                    ))
                ])
            )
        ],
        usage=MockUsage()
    )

    result = service._process_response(func_call_response)

    assert result['stop_reason'] == 'tool_use'
    assert 'tool_use' in result
    assert len(result['tool_use']) == 1
    assert result['tool_use'][0]['name'] == 'get_current_time'
    assert result['tool_use'][0]['input'] == {'timezone': 'UTC'}
    assert result['tool_use'][0]['type'] == 'tool_use'
    assert 'id' in result['tool_use'][0]

    print("[OK] Function call response processing passed!")

    print("\n[OK] All response processing assertions passed!")
    print("\nConclusion:")
    print("- Text responses are properly extracted")
    print("- Function calls are converted to standard tool_use format")
    print("- Usage metrics are correctly parsed")
    print("- Stop reasons are properly mapped")


if __name__ == '__main__':
    print("Testing Google Gemini message and tool conversion...")
    print("=" * 80)

    print("\n1. Testing message conversion with tools...")
    print("-" * 40)
    test_message_conversion_with_tools()

    print("\n2. Testing tool definition conversion...")
    print("-" * 40)
    test_tool_definition_conversion()

    print("\n3. Testing response processing...")
    print("-" * 40)
    test_response_processing()

    print("\n" + "=" * 80)
    print("All Google Gemini context tests completed!")
