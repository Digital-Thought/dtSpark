"""
Unit tests for tool selector module.

This module tests the ToolSelector functionality for intelligent tool selection.
"""

import unittest
from dtSpark.mcp_integration.tool_selector import ToolSelector


class TestToolSelector(unittest.TestCase):
    """Test cases for ToolSelector."""

    def setUp(self):
        """Set up test fixtures."""
        self.selector = ToolSelector(max_tools_per_request=10)

        # Create sample tools
        self.all_tools = [
            {
                'name': 'get_prowler_findings',
                'description': 'Get Prowler security scan findings',
                'input_schema': {'type': 'object'},
                'server': 'aws-scanner'
            },
            {
                'name': 'list_scans',
                'description': 'List all security scans',
                'input_schema': {'type': 'object'},
                'server': 'aws-scanner'
            },
            {
                'name': 'list_containers',
                'description': 'List Docker containers',
                'input_schema': {'type': 'object'},
                'server': 'mcp-docker'
            },
            {
                'name': 'create_note',
                'description': 'Create an Obsidian note',
                'input_schema': {'type': 'object'},
                'server': 'dt-ragstore-MCP'
            },
            {
                'name': 'search_indicators',
                'description': 'Search threat indicators in OpenCTI',
                'input_schema': {'type': 'object'},
                'server': 'opencti'
            },
            {
                'name': 'list_ec2_instances',
                'description': 'List EC2 instances',
                'input_schema': {'type': 'object'},
                'server': 'aws-diagram'
            },
            {
                'name': 'search_elasticsearch',
                'description': 'Search Elasticsearch index',
                'input_schema': {'type': 'object'},
                'server': 'elasticsearch-mcp-server'
            },
            {
                'name': 'get_current_datetime',
                'description': 'Get current date and time',
                'input_schema': {'type': 'object'},
                'server': 'builtin'
            },
        ]

    def test_initialization(self):
        """Test ToolSelector initialisation."""
        selector = ToolSelector(max_tools_per_request=20)
        self.assertEqual(selector.max_tools_per_request, 20)

    def test_select_tools_security_category(self):
        """Test tool selection for security-related queries."""
        user_message = "Show me the Prowler security scan findings for my AWS account"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should include built-in tools
        builtin_tools = [t for t in selected if t['server'] == 'builtin']
        self.assertGreater(len(builtin_tools), 0)

        # Should include security-related tools
        tool_names = [t['name'] for t in selected]
        self.assertIn('get_prowler_findings', tool_names)

        # Should not exceed max tools
        self.assertLessEqual(len(selected), self.selector.max_tools_per_request)

    def test_select_tools_docker_category(self):
        """Test tool selection for Docker-related queries."""
        user_message = "Can you list all running Docker containers?"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should include Docker tools
        tool_names = [t['name'] for t in selected]
        self.assertIn('list_containers', tool_names)

    def test_select_tools_documentation_category(self):
        """Test tool selection for documentation-related queries."""
        user_message = "Create a new note in Obsidian about this finding"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should include documentation tools
        tool_names = [t['name'] for t in selected]
        self.assertIn('create_note', tool_names)

    def test_select_tools_multiple_categories(self):
        """Test tool selection when multiple categories are detected."""
        user_message = "Get Prowler findings and create an Obsidian note summarising them"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should include tools from both categories
        tool_names = [t['name'] for t in selected]
        self.assertIn('get_prowler_findings', tool_names)
        self.assertIn('create_note', tool_names)

    def test_select_tools_with_history(self):
        """Test tool selection with conversation history."""
        user_message = "List the critical ones"
        history = [
            {'content': 'Show me the Prowler findings', 'role': 'user'},
            {'content': 'Here are the findings...', 'role': 'assistant'}
        ]

        selected = self.selector.select_tools(self.all_tools, user_message, history)

        # Should detect security category from history
        tool_names = [t['name'] for t in selected]
        self.assertIn('get_prowler_findings', tool_names)

    def test_select_tools_no_specific_category(self):
        """Test tool selection when no specific category is detected."""
        user_message = "What can you help me with?"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should return diverse sample
        self.assertGreater(len(selected), 0)
        self.assertLessEqual(len(selected), self.selector.max_tools_per_request)

        # Should include built-in tools
        tool_names = [t['name'] for t in selected]
        self.assertIn('get_current_datetime', tool_names)

    def test_select_tools_respects_max_limit(self):
        """Test that tool selection respects the maximum limit."""
        # Create many tools
        many_tools = self.all_tools * 10  # 80 tools

        user_message = "Show me security findings"
        selected = self.selector.select_tools(many_tools, user_message)

        # Should not exceed maximum
        self.assertLessEqual(len(selected), self.selector.max_tools_per_request)

    def test_select_tools_empty_tools_list(self):
        """Test tool selection with empty tools list."""
        selected = self.selector.select_tools([], "any message")
        self.assertEqual(len(selected), 0)

    def test_select_tools_always_includes_builtin(self):
        """Test that built-in tools are always included."""
        user_message = "Random message"
        selected = self.selector.select_tools(self.all_tools, user_message)

        # Should include built-in tools
        builtin_count = sum(1 for t in selected if t['server'] == 'builtin')
        self.assertGreater(builtin_count, 0)

    def test_detect_categories_security(self):
        """Test category detection for security keywords."""
        categories = self.selector._detect_categories(
            "Show me the security vulnerabilities and compliance issues",
            None
        )
        self.assertIn('aws_security', categories)

    def test_detect_categories_threat_intelligence(self):
        """Test category detection for threat intelligence keywords."""
        categories = self.selector._detect_categories(
            "Search for malware indicators in OpenCTI",
            None
        )
        self.assertIn('threat_intelligence', categories)

    def test_detect_categories_aws_infrastructure(self):
        """Test category detection for AWS infrastructure keywords."""
        categories = self.selector._detect_categories(
            "List all EC2 instances in my VPC",
            None
        )
        self.assertIn('aws_infrastructure', categories)

    def test_diverse_sample_selection(self):
        """Test that diverse sample selection works correctly."""
        builtin_tools = [t for t in self.all_tools if t['server'] == 'builtin']
        diverse = self.selector._select_diverse_sample(self.all_tools, builtin_tools)

        # Should include tools from different categories
        servers = set(t['server'] for t in diverse)
        self.assertGreater(len(servers), 1)

        # Should not exceed maximum
        self.assertLessEqual(len(diverse), self.selector.max_tools_per_request)


if __name__ == '__main__':
    unittest.main()
