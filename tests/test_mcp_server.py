#!/usr/bin/env python3
"""
Simple MCP Test Server for AWS Bedrock CLI

This is a basic MCP server for testing the MCP integration.
It provides several simple tools for demonstration purposes.
"""

import sys
import datetime
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)


# Create the MCP server
mcp = FastMCP("Test Server")


@mcp.tool()
def add_numbers(a: float, b: float) -> float:
    """
    Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        The sum of a and b
    """
    result = a + b
    return result


@mcp.tool()
def multiply_numbers(a: float, b: float) -> float:
    """
    Multiply two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        The product of a and b
    """
    result = a * b
    return result


@mcp.tool()
def text_to_uppercase(text: str) -> str:
    """
    Convert text to uppercase.

    Args:
        text: The text to convert

    Returns:
        The text in uppercase
    """
    return text.upper()


@mcp.tool()
def text_to_lowercase(text: str) -> str:
    """
    Convert text to lowercase.

    Args:
        text: The text to convert

    Returns:
        The text in lowercase
    """
    return text.lower()


@mcp.tool()
def reverse_text(text: str) -> str:
    """
    Reverse a text string.

    Args:
        text: The text to reverse

    Returns:
        The reversed text
    """
    return text[::-1]


@mcp.tool()
def count_words(text: str) -> int:
    """
    Count the number of words in text.

    Args:
        text: The text to count words in

    Returns:
        Number of words
    """
    words = text.split()
    return len(words)


@mcp.tool()
def get_current_time(timezone: Optional[str] = None) -> str:
    """
    Get the current date and time.

    Args:
        timezone: Optional timezone (not implemented in this simple version)

    Returns:
        Current date and time as a string
    """
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool()
def create_greeting(name: str, formal: bool = False) -> str:
    """
    Create a personalised greeting.

    Args:
        name: The name to greet
        formal: Whether to use formal greeting (default: False)

    Returns:
        A personalised greeting message
    """
    if formal:
        return f"Good day, {name}. It is a pleasure to make your acquaintance."
    else:
        return f"G'day, {name}! How are you going?"


@mcp.tool()
def calculate_percentage(value: float, total: float, decimals: int = 2) -> str:
    """
    Calculate what percentage a value is of a total.

    Args:
        value: The value to calculate percentage for
        total: The total amount
        decimals: Number of decimal places (default: 2)

    Returns:
        Percentage as a formatted string
    """
    if total == 0:
        return "Error: Cannot calculate percentage of zero"

    percentage = (value / total) * 100
    return f"{percentage:.{decimals}f}%"


@mcp.tool()
def concatenate_strings(strings: list[str], separator: str = " ") -> str:
    """
    Join multiple strings together with a separator.

    Args:
        strings: List of strings to concatenate
        separator: String to use between items (default: space)

    Returns:
        Concatenated string
    """
    return separator.join(strings)


@mcp.tool()
def server_info() -> dict:
    """
    Get information about this MCP server.

    Returns:
        Dictionary with server information
    """
    return {
        "name": "Test Server",
        "version": "1.0.0",
        "description": "Simple MCP server for testing AWS Bedrock CLI integration",
        "tools_count": 11,
        "purpose": "Demonstration and testing"
    }


# Resource example
@mcp.resource("config://server")
def get_server_config() -> str:
    """Server configuration information."""
    return """
Test MCP Server Configuration
==============================
Server Name: Test Server
Purpose: Testing MCP integration with AWS Bedrock CLI
Available Tools: 11
- Mathematical: add_numbers, multiply_numbers, calculate_percentage
- Text manipulation: text_to_uppercase, text_to_lowercase, reverse_text, count_words
- Utility: get_current_time, create_greeting, concatenate_strings, server_info
"""


if __name__ == "__main__":
    print("Starting Test MCP Server...", file=sys.stderr)
    print("Available tools:", file=sys.stderr)
    print("  - add_numbers: Add two numbers", file=sys.stderr)
    print("  - multiply_numbers: Multiply two numbers", file=sys.stderr)
    print("  - text_to_uppercase: Convert text to uppercase", file=sys.stderr)
    print("  - text_to_lowercase: Convert text to lowercase", file=sys.stderr)
    print("  - reverse_text: Reverse text", file=sys.stderr)
    print("  - count_words: Count words in text", file=sys.stderr)
    print("  - get_current_time: Get current date/time", file=sys.stderr)
    print("  - create_greeting: Create personalised greeting", file=sys.stderr)
    print("  - calculate_percentage: Calculate percentages", file=sys.stderr)
    print("  - concatenate_strings: Join strings together", file=sys.stderr)
    print("  - server_info: Get server information", file=sys.stderr)
    print("", file=sys.stderr)

    # Run the server
    mcp.run()
