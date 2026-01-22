"""
Unit tests for StatusIndicator class.

This module tests the animated progress indicator functionality.
"""

import unittest
import time
from io import StringIO
from unittest.mock import patch
from rich.console import Console
from dtSpark.cli_interface import StatusIndicator, CLIInterface


class TestStatusIndicator(unittest.TestCase):
    """Test cases for StatusIndicator context manager."""

    def setUp(self):
        """Set up test fixtures."""
        # Use a StringIO to capture Rich console output
        self.output = StringIO()
        self.console = Console(file=self.output, force_terminal=True)

    def test_status_indicator_context_manager(self):
        """Test StatusIndicator as context manager."""
        indicator = StatusIndicator(self.console, "Testing...")

        # Test __enter__
        result = indicator.__enter__()
        self.assertIsNotNone(indicator.start_time)
        self.assertIsNotNone(indicator.live)
        self.assertEqual(result, indicator)

        # Simulate some work
        time.sleep(0.1)

        # Test __exit__
        indicator.__exit__(None, None, None)
        self.assertIsNotNone(indicator.start_time)

        # Check that output contains completion message
        output = self.output.getvalue()
        self.assertIn("Completed in", output)

    def test_status_indicator_with_block(self):
        """Test StatusIndicator using with statement."""
        with StatusIndicator(self.console, "Processing..."):
            # Simulate some work
            time.sleep(0.1)

        # Check output
        output = self.output.getvalue()
        self.assertIn("Completed in", output)

    def test_status_indicator_update(self):
        """Test updating status message."""
        with StatusIndicator(self.console, "Step 1...") as indicator:
            time.sleep(0.05)
            indicator.update("Step 2...")
            time.sleep(0.05)

        # Should have completion message
        output = self.output.getvalue()
        self.assertIn("Completed in", output)

    def test_status_indicator_elapsed_time(self):
        """Test that elapsed time is calculated correctly."""
        with StatusIndicator(self.console, "Waiting..."):
            time.sleep(0.2)

        output = self.output.getvalue()
        # Should show approximately 0.2 seconds
        self.assertIn("0.", output)  # Should have decimal
        self.assertIn("s", output)  # Should have 's' for seconds

    def test_cli_interface_status_indicator(self):
        """Test CLIInterface.status_indicator() method."""
        # Create CLIInterface with custom console
        cli = CLIInterface()
        cli.console = self.console

        # Use the status_indicator method
        with cli.status_indicator("Working..."):
            time.sleep(0.1)

        output = self.output.getvalue()
        self.assertIn("Completed in", output)


if __name__ == '__main__':
    unittest.main()
