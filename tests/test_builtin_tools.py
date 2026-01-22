"""
Unit tests for built-in tools module.

This module tests the functionality of built-in tools like get_current_datetime.
"""

import unittest
import json
from datetime import datetime
from dtSpark.tools import builtin as builtin_tools


class TestBuiltinTools(unittest.TestCase):
    """Test cases for built-in tools."""

    def test_get_builtin_tools(self):
        """Test that get_builtin_tools returns a list of tool definitions."""
        tools = builtin_tools.get_builtin_tools()

        # Should return a list
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        # Each tool should have required fields
        for tool in tools:
            self.assertIn('name', tool)
            self.assertIn('description', tool)
            self.assertIn('input_schema', tool)

    def test_get_current_datetime_default(self):
        """Test get_current_datetime with default parameters."""
        result = builtin_tools.execute_builtin_tool('get_current_datetime', {})

        # Should succeed
        self.assertTrue(result.get('success'))
        self.assertIn('result', result)

        # Result should have expected fields
        result_data = result['result']
        self.assertIn('datetime', result_data)
        self.assertIn('timezone', result_data)

    def test_get_current_datetime_utc(self):
        """Test get_current_datetime with UTC timezone."""
        result = builtin_tools.execute_builtin_tool(
            'get_current_datetime',
            {'timezone': 'UTC'}
        )

        # Should succeed
        self.assertTrue(result.get('success'))

        # Result should have UTC timezone
        result_data = result['result']
        self.assertEqual(result_data['timezone'], 'UTC')

    def test_get_current_datetime_sydney(self):
        """Test get_current_datetime with Australia/Sydney timezone."""
        result = builtin_tools.execute_builtin_tool(
            'get_current_datetime',
            {'timezone': 'Australia/Sydney'}
        )

        # Should succeed
        self.assertTrue(result.get('success'))

        # Result should have Sydney timezone
        result_data = result['result']
        self.assertIn('Australia', result_data['timezone'])

    def test_get_current_datetime_human_format(self):
        """Test get_current_datetime with human-readable format."""
        result = builtin_tools.execute_builtin_tool(
            'get_current_datetime',
            {'format': 'human'}
        )

        # Should succeed
        self.assertTrue(result.get('success'))

        # Result should have human-readable fields
        result_data = result['result']
        self.assertIn('datetime', result_data)
        # Human format should include day of week
        self.assertRegex(
            result_data['datetime'],
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
        )

    def test_get_current_datetime_invalid_timezone(self):
        """Test get_current_datetime with invalid timezone."""
        result = builtin_tools.execute_builtin_tool(
            'get_current_datetime',
            {'timezone': 'Invalid/Timezone'}
        )

        # Should fail
        self.assertFalse(result.get('success'))
        self.assertIn('error', result)
        self.assertIn('Invalid timezone', result['error'])

    def test_execute_unknown_tool(self):
        """Test executing an unknown tool name."""
        result = builtin_tools.execute_builtin_tool('unknown_tool', {})

        # Should fail
        self.assertFalse(result.get('success'))
        self.assertIn('error', result)
        self.assertIn('Unknown built-in tool', result['error'])

    def test_validate_timezone(self):
        """Test timezone validation function."""
        # Valid timezones
        self.assertTrue(builtin_tools.validate_timezone('UTC'))
        self.assertTrue(builtin_tools.validate_timezone('Australia/Sydney'))
        self.assertTrue(builtin_tools.validate_timezone('America/New_York'))

        # Invalid timezones
        self.assertFalse(builtin_tools.validate_timezone('Invalid/Timezone'))
        self.assertFalse(builtin_tools.validate_timezone('Not_A_Zone'))

    def test_get_available_timezones(self):
        """Test getting available timezones."""
        timezones = builtin_tools.get_available_timezones()

        # Should return a list
        self.assertIsInstance(timezones, list)
        self.assertGreater(len(timezones), 0)

        # Should include common timezones
        self.assertIn('UTC', timezones)
        self.assertIn('Australia/Sydney', timezones)

        # Should be sorted
        self.assertEqual(timezones, sorted(timezones))


if __name__ == '__main__':
    unittest.main()
