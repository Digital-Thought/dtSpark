"""
Test Ollama conversation context preservation with tool calling.

This test verifies that tool calls and results are properly preserved
in the conversation history when using Ollama.
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dtSpark.llm.ollama import OllamaService


def test_message_conversion_with_tools():
    """Test that tool_use and tool_result blocks are properly converted."""

    service = OllamaService(base_url="http://dt-docker01.digital-thought.home:11434")

    # Simulate conversation history with tool calls
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
                    'input': {'timezone': None}
                }
            ]
        },
        {
            'role': 'user',
            'content': [
                {
                    'type': 'tool_result',
                    'tool_use_id': 'tool_123',
                    'content': '2025-11-06 15:24:08'
                }
            ]
        }
    ]

    # Convert messages
    ollama_messages = service._convert_messages_to_ollama(messages)

    # Verify conversion
    print("Converted messages:")
    for i, msg in enumerate(ollama_messages):
        print(f"\n{i+1}. Role: {msg['role']}")
        print(f"   Content: {msg.get('content', '')[:100]}")
        if 'tool_calls' in msg:
            print(f"   Tool calls: {len(msg['tool_calls'])} call(s)")
            for tc in msg['tool_calls']:
                print(f"     - {tc['function']['name']}({tc['function']['arguments']})")
        if 'tool_name' in msg:
            print(f"   Tool name: {msg['tool_name']}")

    # Assertions
    # Tool result messages use role "tool" (OpenAI/Ollama format)
    assert len(ollama_messages) == 3, f"Expected 3 messages, got {len(ollama_messages)}"

    # First message should be user question
    assert ollama_messages[0]['role'] == 'user'
    assert 'current time' in ollama_messages[0]['content'].lower()

    # Second message should be assistant with tool_calls
    assert ollama_messages[1]['role'] == 'assistant'
    assert 'tool_calls' in ollama_messages[1], "Assistant message should have tool_calls"
    assert len(ollama_messages[1]['tool_calls']) == 1
    assert ollama_messages[1]['tool_calls'][0]['function']['name'] == 'get_current_time'

    # Third message should be tool result with role "tool" (Ollama SDK format)
    assert ollama_messages[2]['role'] == 'tool', "Tool result should have role 'tool'"
    assert '2025-11-06 15:24:08' in ollama_messages[2]['content'], "Tool result should contain the time"
    assert 'tool_name' in ollama_messages[2], "Tool result should have tool_name (Ollama SDK format)"
    assert ollama_messages[2]['tool_name'] == 'get_current_time', "Tool name should match"

    print("\n[OK] All assertions passed!")
    print("\nConclusion:")
    print("- Tool calls are preserved in assistant message as 'tool_calls' field")
    print("- Tool results are converted to role 'tool' (Ollama SDK format)")
    print("- Tool results include 'tool_name' field for Ollama SDK compatibility")
    print("- Model can properly use tool results to answer questions")


if __name__ == '__main__':
    print("Testing Ollama message conversion with tool calls...")
    print("=" * 80)
    test_message_conversion_with_tools()
