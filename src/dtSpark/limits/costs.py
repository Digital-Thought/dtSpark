"""
Cost management module for AWS Bedrock usage.

This module provides functionality for:
- Tracking usage costs over rolling time windows
- Budget monitoring and warnings
- Cost-based usage limits with override options
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from enum import Enum


class BudgetStatus(Enum):
    """Budget status levels."""
    OK = "ok"
    WARNING_75 = "warning_75"
    WARNING_85 = "warning_85"
    WARNING_95 = "warning_95"
    EXCEEDED = "exceeded"


class CostManager:
    """Manages cost tracking and budget enforcement."""

    def __init__(self, database, pricing_manager, config: Dict):
        """
        Initialise the cost manager.

        Args:
            database: ConversationDatabase instance
            pricing_manager: BedrockPricing instance
            config: Cost management configuration dictionary
        """
        self.database = database
        self.pricing = pricing_manager
        self.enabled = config.get('enabled', False)
        self.max_spend = float(config.get('max_spend', 10.0))
        self.period_hours = int(config.get('period_hours', 24))
        self.allow_override = config.get('allow_override', True)
        self.current_override = 0.0  # Additional spend allowed for current period
        self.override_expires = None  # When the override expires

    def check_budget_before_request(self, model_id: str, region: str,
                                    input_tokens: int, max_output_tokens: int) -> Tuple[bool, str, BudgetStatus]:
        """
        Check if a request would exceed the budget.

        Args:
            model_id: Bedrock model ID
            region: AWS region
            input_tokens: Number of input tokens
            max_output_tokens: Maximum output tokens

        Returns:
            Tuple of (allowed, message, status)
        """
        if not self.enabled:
            return True, "", BudgetStatus.OK

        # Estimate maximum cost for this request
        estimated_cost = self.pricing.estimate_max_cost(
            model_id, region, input_tokens, max_output_tokens
        )

        # Get current spend in rolling window
        current_spend = self._get_rolling_window_spend()

        # Calculate effective limit (base + override)
        effective_limit = self.max_spend + self.current_override

        # Calculate projected spend
        projected_spend = current_spend + estimated_cost

        # Determine status
        percentage = (projected_spend / effective_limit) * 100

        if projected_spend > effective_limit:
            # Budget exceeded
            time_until_reset = self._time_until_reset()
            return False, self._format_exceeded_message(
                current_spend, effective_limit, estimated_cost, time_until_reset
            ), BudgetStatus.EXCEEDED

        elif percentage >= 95:
            return True, self._format_warning_message(
                percentage, current_spend, effective_limit, estimated_cost
            ), BudgetStatus.WARNING_95

        elif percentage >= 85:
            return True, self._format_warning_message(
                percentage, current_spend, effective_limit, estimated_cost
            ), BudgetStatus.WARNING_85

        elif percentage >= 75:
            return True, self._format_warning_message(
                percentage, current_spend, effective_limit, estimated_cost
            ), BudgetStatus.WARNING_75

        else:
            return True, "", BudgetStatus.OK

    def record_usage(self, conversation_id: int, model_id: str, region: str,
                    input_tokens: int, output_tokens: int) -> float:
        """
        Record actual usage after a request completes.

        Args:
            conversation_id: Conversation ID
            model_id: Bedrock model ID
            region: AWS region
            input_tokens: Actual input tokens used
            output_tokens: Actual output tokens used

        Returns:
            Actual cost in USD
        """
        if not self.enabled:
            return 0.0

        # Calculate actual cost
        cost, source = self.pricing.calculate_cost(
            model_id, region, input_tokens, output_tokens
        )

        # Store usage in database
        self.database.record_usage(
            conversation_id=conversation_id,
            model_id=model_id,
            region=region,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            timestamp=datetime.now()
        )

        logging.debug(f"Recorded usage: ${cost:.4f} ({source})")
        return cost

    def _get_rolling_window_spend(self) -> float:
        """
        Get total spend in the current rolling window.

        Returns:
            Total spend in USD
        """
        # Check if override has expired
        if self.override_expires and datetime.now() >= self.override_expires:
            self.current_override = 0.0
            self.override_expires = None
            logging.info("Cost override has expired")

        # Calculate start of rolling window
        window_start = datetime.now() - timedelta(hours=self.period_hours)

        # Get usage from database
        total_spend = self.database.get_usage_in_window(window_start)

        return total_spend

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

    def _format_warning_message(self, percentage: float, current_spend: float,
                                limit: float, estimated_cost: float) -> str:
        """
        Format a budget warning message.

        Args:
            percentage: Percentage of budget used
            current_spend: Current spend in USD
            limit: Budget limit in USD
            estimated_cost: Estimated cost of current request

        Returns:
            Formatted warning message
        """
        remaining = limit - current_spend - estimated_cost

        message = (
            f"Budget Warning: {percentage:.1f}% of ${limit:.2f} budget used "
            f"(${current_spend:.2f} spent, ${estimated_cost:.4f} this request, "
            f"${remaining:.2f} remaining in {self.period_hours}h window)"
        )

        return message

    def _format_exceeded_message(self, current_spend: float, limit: float,
                                 estimated_cost: float, time_until_reset: timedelta) -> str:
        """
        Format a budget exceeded message.

        Args:
            current_spend: Current spend in USD
            limit: Budget limit in USD
            estimated_cost: Estimated cost of request
            time_until_reset: Time until budget resets

        Returns:
            Formatted exceeded message
        """
        hours = int(time_until_reset.total_seconds() // 3600)
        minutes = int((time_until_reset.total_seconds() % 3600) // 60)

        message = (
            f"Budget Limit Reached: ${current_spend:.2f} of ${limit:.2f} spent. "
            f"This request (${estimated_cost:.4f}) would exceed the limit. "
        )

        if time_until_reset.total_seconds() > 0:
            message += f"Budget resets in {hours}h {minutes}m. "
        else:
            message += "Budget resets now (no recent usage). "

        if self.allow_override:
            message += "Override available."
        else:
            message += "No override allowed."

        return message

    def apply_override(self, additional_percentage: float) -> bool:
        """
        Apply a budget override for the current period.

        Args:
            additional_percentage: Additional percentage to allow (e.g., 10.0 for 10%)

        Returns:
            True if override applied successfully
        """
        if not self.allow_override:
            logging.warning("Budget override not allowed by configuration")
            return False

        # Calculate additional spend allowed
        additional_spend = self.max_spend * (additional_percentage / 100.0)
        self.current_override = additional_spend

        # Set override to expire after the current period
        self.override_expires = datetime.now() + timedelta(hours=self.period_hours)

        logging.info(
            f"Budget override applied: +${additional_spend:.2f} ({additional_percentage}%) "
            f"until {self.override_expires}"
        )

        return True

    def get_budget_summary(self) -> Dict:
        """
        Get current budget status summary.

        Returns:
            Dictionary with budget information
        """
        if not self.enabled:
            return {'enabled': False}

        current_spend = self._get_rolling_window_spend()
        effective_limit = self.max_spend + self.current_override
        percentage = (current_spend / effective_limit * 100) if effective_limit > 0 else 0
        remaining = effective_limit - current_spend
        time_until_reset = self._time_until_reset()

        return {
            'enabled': True,
            'current_spend': current_spend,
            'limit': self.max_spend,
            'effective_limit': effective_limit,
            'override_amount': self.current_override,
            'percentage_used': percentage,
            'remaining': remaining,
            'period_hours': self.period_hours,
            'time_until_reset_seconds': time_until_reset.total_seconds(),
            'override_active': self.current_override > 0,
            'override_expires': self.override_expires.isoformat() if self.override_expires else None
        }
