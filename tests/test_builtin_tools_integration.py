"""
Integration test for built-in tools with ConversationManager.

This test verifies that built-in tools are properly integrated with
the conversation manager and can be called during conversations.
"""

import unittest
import json
from unittest.mock import Mock, patch
from dtSpark.conversation_manager import ConversationManager


class TestBuiltinToolsIntegration(unittest.TestCase):
    """Integration tests for built-in tools with ConversationManager."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock database
        self.mock_db = Mock()
        self.mock_db.create_conversation.return_value = 1
        self.mock_db.add_message.return_value = None
        self.mock_db.update_token_count.return_value = None
        self.mock_db.is_mcp_server_enabled.return_value = True

        # Create mock bedrock service
        self.mock_bedrock = Mock()
        self.mock_bedrock.count_tokens.return_value = 100

        # Create conversation manager with no MCP manager (only built-in tools)
        self.conv_manager = ConversationManager(
            database=self.mock_db,
            bedrock_service=self.mock_bedrock,
            max_tokens=4096,
            mcp_manager=None  # No MCP manager, only built-in tools
        )

        # Create a conversation
        self.conv_manager.create_conversation("Test Conv", "test-model")

    def test_builtin_tools_loaded(self):
        """Test that built-in tools are loaded when conversation manager initializes."""
        tools = self.conv_manager._get_mcp_tools()

        # Should have at least the built-in tools
        self.assertGreater(len(tools), 0)

        # Should have get_current_datetime tool
        tool_names = [tool['name'] for tool in tools]
        self.assertIn('get_current_datetime', tool_names)

        # Tool should be marked as built-in
        for tool in tools:
            if tool['name'] == 'get_current_datetime':
                self.assertEqual(tool['server'], 'builtin')
                break

    def test_builtin_tool_structure(self):
        """Test that built-in tools have the correct structure."""
        tools = self.conv_manager._get_mcp_tools()

        for tool in tools:
            if tool['server'] == 'builtin':
                # Should have required fields
                self.assertIn('name', tool)
                self.assertIn('description', tool)
                self.assertIn('input_schema', tool)
                self.assertIn('server', tool)
                self.assertIn('original_name', tool)

                # Server should be 'builtin'
                self.assertEqual(tool['server'], 'builtin')

    def test_call_builtin_tool(self):
        """Test calling a built-in tool through the conversation manager."""
        # Populate tools cache first
        self.conv_manager._get_mcp_tools()

        result, execution_time, is_error = self.conv_manager._call_mcp_tool(
            'get_current_datetime',
            {'format': 'iso'}
        )

        # Should succeed
        self.assertFalse(is_error)
        self.assertGreaterEqual(execution_time, 0)

        # Result should be valid JSON
        result_data = json.loads(result)
        self.assertIn('datetime', result_data)
        self.assertIn('timezone', result_data)

    def test_call_builtin_tool_with_timezone(self):
        """Test calling built-in tool with specific timezone."""
        # Populate tools cache first
        self.conv_manager._get_mcp_tools()

        result, _execution_time, is_error = self.conv_manager._call_mcp_tool(
            'get_current_datetime',
            {'timezone': 'UTC', 'format': 'iso'}
        )

        # Should succeed
        self.assertFalse(is_error)

        # Result should have UTC timezone
        result_data = json.loads(result)
        self.assertEqual(result_data['timezone'], 'UTC')

    def test_call_builtin_tool_with_invalid_timezone(self):
        """Test calling built-in tool with invalid timezone."""
        # Populate tools cache first
        self.conv_manager._get_mcp_tools()

        result, _execution_time, is_error = self.conv_manager._call_mcp_tool(
            'get_current_datetime',
            {'timezone': 'Invalid/Timezone'}
        )

        # Should fail
        self.assertTrue(is_error)
        self.assertIn('Error:', result)
        self.assertIn('Invalid timezone', result)

    def test_builtin_tools_cached(self):
        """Test that built-in tools are cached."""
        # First call
        tools1 = self.conv_manager._get_mcp_tools()

        # Second call should return cached tools
        tools2 = self.conv_manager._get_mcp_tools()

        # Should be the same instance
        self.assertIs(tools1, tools2)

    def test_builtin_tools_with_mcp_manager(self):
        """Test that built-in tools work alongside MCP tools."""
        # Create a mock MCP manager
        mock_mcp = Mock()
        mock_mcp._initialization_loop = None

        # Create conversation manager with MCP manager
        conv_manager_with_mcp = ConversationManager(
            database=self.mock_db,
            bedrock_service=self.mock_bedrock,
            max_tokens=4096,
            mcp_manager=mock_mcp
        )

        conv_manager_with_mcp.create_conversation("Test Conv", "test-model")

        # Mock MCP tools
        with patch.object(mock_mcp, 'list_all_tools') as mock_list_tools:
            # Create a new event loop for the test
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            mock_mcp._initialization_loop = loop

            async def mock_list():
                return [{
                    'name': 'mcp_tool',
                    'description': 'Test MCP tool',
                    'input_schema': {'type': 'object'},
                    'server': 'test-server'
                }]

            mock_list_tools.return_value = mock_list()

            tools = conv_manager_with_mcp._get_mcp_tools()

            # Should have both built-in and MCP tools
            tool_names = [tool['name'] for tool in tools]
            self.assertIn('get_current_datetime', tool_names)
            self.assertIn('mcp_tool', tool_names)

            # Built-in tool should be marked as 'builtin'
            builtin_tools_found = [t for t in tools if t['server'] == 'builtin']
            self.assertGreater(len(builtin_tools_found), 0)

            loop.close()


if __name__ == '__main__':
    unittest.main()
