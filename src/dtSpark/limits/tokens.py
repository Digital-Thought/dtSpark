"""
Token management module for AWS Bedrock usage.

This module provides functionality for:
- Tracking token usage (input and output separately) over rolling time windows
- Token limit monitoring and warnings
- Token-based usage limits with override options
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from enum import Enum


class LimitStatus(Enum):
    """Token limit status levels."""
    OK = "ok"
    WARNING_75 = "warning_75"
    WARNING_85 = "warning_85"
    WARNING_95 = "warning_95"
    EXCEEDED = "exceeded"


class TokenManager:
    """Manages token usage tracking and limit enforcement."""

    def __init__(self, database, config: Dict):
        """
        Initialise the token manager.

        Args:
            database: ConversationDatabase instance
            config: Token management configuration dictionary
        """
        self.database = database
        self.enabled = config.get('enabled', False)
        self.max_input_tokens = int(config.get('max_input_tokens', 100000))
        self.max_output_tokens = int(config.get('max_output_tokens', 50000))
        self.period_hours = int(config.get('period_hours', 24))
        self.allow_override = config.get('allow_override', True)

        # Override tracking
        self.current_input_override = 0  # Additional input tokens allowed
        self.current_output_override = 0  # Additional output tokens allowed
        self.override_expires = None  # When the override expires

    def check_limits_before_request(self, _model_id: str, region: str,
                                    input_tokens: int, max_output_tokens: int) -> Tuple[bool, str, LimitStatus]:
        """
        Check if a request would exceed the token limits.

        Args:
            model_id: Bedrock model ID
            region: AWS region
            input_tokens: Number of input tokens
            max_output_tokens: Maximum output tokens expected

        Returns:
            Tuple of (allowed, message, status)
        """
        if not self.enabled:
            return True, "", LimitStatus.OK

        # Get current usage in rolling window
        current_input, current_output = self._get_rolling_window_usage()

        # Calculate effective limits (base + override)
        effective_input_limit = self.max_input_tokens + self.current_input_override
        effective_output_limit = self.max_output_tokens + self.current_output_override

        # Calculate projected usage
        projected_input = current_input + input_tokens
        projected_output = current_output + max_output_tokens

        # Check input tokens
        input_percentage = (projected_input / effective_input_limit) * 100 if effective_input_limit > 0 else 0

        # Check output tokens
        output_percentage = (projected_output / effective_output_limit) * 100 if effective_output_limit > 0 else 0

        # Use the higher percentage for status determination
        max_percentage = max(input_percentage, output_percentage)

        # Check if either limit exceeded
        if projected_input > effective_input_limit or projected_output > effective_output_limit:
            time_until_reset = self._time_until_reset()
            return False, self._format_exceeded_message(
                current_input, current_output,
                effective_input_limit, effective_output_limit,
                input_tokens, max_output_tokens,
                time_until_reset
            ), LimitStatus.EXCEEDED

        elif max_percentage >= 95:
            return True, self._format_warning_message(
                max_percentage, current_input, current_output,
                effective_input_limit, effective_output_limit,
                input_tokens, max_output_tokens
            ), LimitStatus.WARNING_95

        elif max_percentage >= 85:
            return True, self._format_warning_message(
                max_percentage, current_input, current_output,
                effective_input_limit, effective_output_limit,
                input_tokens, max_output_tokens
            ), LimitStatus.WARNING_85

        elif max_percentage >= 75:
            return True, self._format_warning_message(
                max_percentage, current_input, current_output,
                effective_input_limit, effective_output_limit,
                input_tokens, max_output_tokens
            ), LimitStatus.WARNING_75

        else:
            return True, "", LimitStatus.OK

    def record_usage(self, conversation_id: int, model_id: str, region: str,
                    input_tokens: int, output_tokens: int) -> Tuple[int, int]:
        """
        Record actual token usage after a request completes.

        Args:
            conversation_id: Conversation ID
            model_id: Bedrock model ID
            region: AWS region
            input_tokens: Actual input tokens used
            output_tokens: Actual output tokens used

        Returns:
            Tuple of (input_tokens, output_tokens) recorded
        """
        if not self.enabled:
            return 0, 0

        # Store usage in database
        self.database.record_usage(
            conversation_id=conversation_id,
            model_id=model_id,
            region=region,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=0.0,  # Not tracking cost anymore
            timestamp=datetime.now()
        )

        logging.debug(f"Recorded usage: {input_tokens} input tokens, {output_tokens} output tokens")
        return input_tokens, output_tokens

    def _get_rolling_window_usage(self) -> Tuple[int, int]:
        """
        Get total token usage in the current rolling window.

        Returns:
            Tuple of (total_input_tokens, total_output_tokens)
        """
        # Check if override has expired
        if self.override_expires and datetime.now() >= self.override_expires:
            self.current_input_override = 0
            self.current_output_override = 0
            self.override_expires = None
            logging.info("Token override has expired")

        # Calculate start of rolling window
        window_start = datetime.now() - timedelta(hours=self.period_hours)

        # Get usage from database
        total_input, total_output = self.database.get_token_usage_in_window(window_start)

        return total_input, total_output

    def _time_until_reset(self) -> timedelta:
        """
        Calculate time until the rolling window resets.

        Returns:
            Time delta until oldest usage expires
        """
        window_start = datetime.now() - timedelta(hours=self.period_hours)
        oldest_usage_time = self.database.get_oldest_usage_in_window(window_start)

        if oldest_usage_time:
            # Time until this usage falls out of the window
            reset_time = oldest_usage_time + timedelta(hours=self.period_hours)
            time_remaining = reset_time - datetime.now()
            return max(time_remaining, timedelta(0))
        else:
            # No usage in window, resets immediately
            return timedelta(0)

    def _format_warning_message(self, percentage: float,
                                current_input: int, current_output: int,
                                input_limit: int, output_limit: int,
                                request_input: int, request_output: int) -> str:
        """
        Format a token limit warning message.

        Args:
            percentage: Percentage of limit used (highest of input/output)
            current_input: Current input tokens used
            current_output: Current output tokens used
            input_limit: Input token limit
            output_limit: Output token limit
            request_input: Input tokens for current request
            request_output: Output tokens for current request

        Returns:
            Formatted warning message
        """
        input_remaining = input_limit - current_input - request_input
        output_remaining = output_limit - current_output - request_output

        message = (
            f"Token Limit Warning: {percentage:.1f}% of limits used. "
            f"Input: {current_input:,}/{input_limit:,} (+{request_input:,} this request, {input_remaining:,} remaining). "
            f"Output: {current_output:,}/{output_limit:,} (+{request_output:,} this request, {output_remaining:,} remaining). "
            f"Window: {self.period_hours}h"
        )

        return message

    def _format_exceeded_message(self, current_input: int, current_output: int,
                                 input_limit: int, output_limit: int,
                                 request_input: int, request_output: int,
                                 time_until_reset: timedelta) -> str:
        """
        Format a token limit exceeded message.

        Args:
            current_input: Current input tokens used
            current_output: Current output tokens used
            input_limit: Input token limit
            output_limit: Output token limit
            request_input: Input tokens for request
            request_output: Output tokens for request
            time_until_reset: Time until limit resets

        Returns:
            Formatted exceeded message
        """
        hours = int(time_until_reset.total_seconds() // 3600)
        minutes = int((time_until_reset.total_seconds() % 3600) // 60)

        # Determine which limit was exceeded
        input_exceeded = (current_input + request_input) > input_limit
        output_exceeded = (current_output + request_output) > output_limit

        message = "Token Limit Reached: "

        if input_exceeded and output_exceeded:
            message += "Both limits exceeded. "
        elif input_exceeded:
            message += f"Input limit exceeded: {current_input:,}/{input_limit:,} used, {request_input:,} requested. "
        else:
            message += f"Output limit exceeded: {current_output:,}/{output_limit:,} used, {request_output:,} requested. "

        if time_until_reset.total_seconds() > 0:
            message += f"Limit resets in {hours}h {minutes}m. "
        else:
            message += "Limit resets now (no recent usage). "

        if self.allow_override:
            message += "Override available."
        else:
            message += "No override allowed."

        return message

    def apply_override(self, additional_percentage: float) -> bool:
        """
        Apply a token limit override for the current period.

        Args:
            additional_percentage: Additional percentage to allow (e.g., 10.0 for 10%)

        Returns:
            True if override applied successfully
        """
        if not self.allow_override:
            logging.warning("Token limit override not allowed by configuration")
            return False

        # Calculate additional tokens allowed for both input and output
        additional_input = int(self.max_input_tokens * (additional_percentage / 100.0))
        additional_output = int(self.max_output_tokens * (additional_percentage / 100.0))

        self.current_input_override = additional_input
        self.current_output_override = additional_output

        # Set override to expire after the current period
        self.override_expires = datetime.now() + timedelta(hours=self.period_hours)

        logging.info(
            f"Token limit override applied: +{additional_input:,} input tokens, "
            f"+{additional_output:,} output tokens ({additional_percentage}%) "
            f"until {self.override_expires}"
        )

        return True

    def get_usage_summary(self) -> Dict:
        """
        Get current token usage status summary.

        Returns:
            Dictionary with usage information
        """
        if not self.enabled:
            return {'enabled': False}

        current_input, current_output = self._get_rolling_window_usage()
        effective_input_limit = self.max_input_tokens + self.current_input_override
        effective_output_limit = self.max_output_tokens + self.current_output_override

        input_percentage = (current_input / effective_input_limit * 100) if effective_input_limit > 0 else 0
        output_percentage = (current_output / effective_output_limit * 100) if effective_output_limit > 0 else 0

        input_remaining = effective_input_limit - current_input
        output_remaining = effective_output_limit - current_output

        time_until_reset = self._time_until_reset()

        return {
            'enabled': True,
            'current_input_tokens': current_input,
            'current_output_tokens': current_output,
            'input_limit': self.max_input_tokens,
            'output_limit': self.max_output_tokens,
            'effective_input_limit': effective_input_limit,
            'effective_output_limit': effective_output_limit,
            'input_override_amount': self.current_input_override,
            'output_override_amount': self.current_output_override,
            'input_percentage_used': input_percentage,
            'output_percentage_used': output_percentage,
            'input_remaining': input_remaining,
            'output_remaining': output_remaining,
            'period_hours': self.period_hours,
            'time_until_reset_seconds': time_until_reset.total_seconds(),
            'override_active': self.current_input_override > 0 or self.current_output_override > 0,
            'override_expires': self.override_expires.isoformat() if self.override_expires else None
        }
