"""
Cost tracking module for AWS Bedrock usage.

This module provides functionality for:
- Retrieving Bedrock usage costs from AWS Cost Explorer
- Breaking down costs by model/usage type
- Reporting on monthly and daily costs
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from botocore.exceptions import ClientError

# Period name constants
_PERIOD_CURRENT_MONTH = 'Current Month'
_PERIOD_LAST_MONTH = 'Last Month'


class CostTracker:
    """Tracks AWS Bedrock costs using Cost Explorer API."""

    def __init__(self, cost_explorer_client):
        """
        Initialise the cost tracker.

        Args:
            cost_explorer_client: Boto3 Cost Explorer client
        """
        self.ce_client = cost_explorer_client
        self.has_permissions = None  # Cache permission check

    def check_permissions(self) -> bool:
        """
        Check if the authenticated user has Cost Explorer permissions.

        Returns:
            True if user has permissions, False otherwise
        """
        if self.has_permissions is not None:
            return self.has_permissions

        try:
            # Try a minimal query to check permissions
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=1)

            self.ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_date.strftime('%Y-%m-%d'),
                    'End': end_date.strftime('%Y-%m-%d')
                },
                Granularity='DAILY',
                Metrics=['UnblendedCost']
            )

            self.has_permissions = True
            logging.info("Cost Explorer permissions verified")
            return True

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['AccessDeniedException', 'UnauthorizedException']:
                logging.info("User does not have Cost Explorer permissions")
                self.has_permissions = False
                return False
            else:
                logging.warning(f"Error checking Cost Explorer permissions: {e}")
                self.has_permissions = False
                return False
        except Exception as e:
            logging.warning(f"Unexpected error checking permissions: {e}")
            self.has_permissions = False
            return False

    def get_bedrock_costs(self) -> Optional[Dict]:
        """
        Retrieve Bedrock costs for current month, last month and last 24 hours.

        Returns:
            Dictionary with cost information, or None if unavailable
        """
        if not self.check_permissions():
            return None

        try:
            # Calculate date ranges
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)

            # Current month (from 1st of this month to today)
            first_day_this_month = today.replace(day=1)

            # Last month (from 1st to last day of previous month)
            last_day_last_month = first_day_this_month - timedelta(days=1)
            first_day_last_month = last_day_last_month.replace(day=1)

            # Get current month's costs (month-to-date)
            current_month_costs = self._get_costs_for_period(
                first_day_this_month,
                today + timedelta(days=1),  # End date is exclusive, so add 1 day to include today
                _PERIOD_CURRENT_MONTH
            )

            # Get last month's costs
            last_month_costs = self._get_costs_for_period(
                first_day_last_month,
                first_day_this_month,  # End date is exclusive
                _PERIOD_LAST_MONTH
            )

            # Get last 24 hours costs
            last_24h_costs = self._get_costs_for_period(
                yesterday,
                today,
                'Last 24 Hours'
            )

            return {
                'current_month': current_month_costs,
                'last_month': last_month_costs,
                'last_24h': last_24h_costs,
                'currency': 'USD'  # Cost Explorer returns USD by default
            }

        except Exception as e:
            logging.error(f"Error retrieving Bedrock costs: {e}")
            return None

    def _get_costs_for_period(self, start_date, end_date, period_name: str) -> Dict:
        """
        Get Bedrock costs for a specific time period with model breakdown.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (exclusive)
            period_name: Human-readable period name for logging

        Returns:
            Dictionary with total cost and breakdown by usage type
        """
        try:
            # Query 1: Get total Bedrock costs
            # Note: AWS Cost Explorer uses model-specific service names for Bedrock
            # We search for services containing "Amazon Bedrock Edition"
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_date.strftime('%Y-%m-%d'),
                    'End': end_date.strftime('%Y-%m-%d')
                },
                Granularity='MONTHLY' if period_name in [_PERIOD_LAST_MONTH, _PERIOD_CURRENT_MONTH] else 'DAILY',
                Metrics=['UnblendedCost'],
                GroupBy=[{
                    'Type': 'DIMENSION',
                    'Key': 'SERVICE'
                }]
            )

            # Extract total cost and breakdown by filtering for Bedrock services
            # AWS uses service names like "Claude 3.5 Sonnet (Amazon Bedrock Edition)"
            total_cost = 0.0
            breakdown = {}

            if response.get('ResultsByTime'):
                for result in response['ResultsByTime']:
                    for group in result.get('Groups', []):
                        service_name = group.get('Keys', [''])[0]

                        # Filter for Bedrock services (contain "Amazon Bedrock Edition")
                        if 'Amazon Bedrock Edition' in service_name or 'Bedrock' in service_name:
                            amount = float(group.get('Metrics', {}).get('UnblendedCost', {}).get('Amount', '0'))

                            if amount > 0:
                                total_cost += amount

                                # Extract model name from service name
                                # Example: "Claude 3.5 Sonnet (Amazon Bedrock Edition)" -> "Claude 3.5 Sonnet"
                                model_name = service_name.replace(' (Amazon Bedrock Edition)', '').strip()

                                if model_name in breakdown:
                                    breakdown[model_name] += amount
                                else:
                                    breakdown[model_name] = amount

            logging.info(f"{period_name} Bedrock costs: ${total_cost:.4f}")
            if breakdown:
                logging.debug(f"{period_name} breakdown: {breakdown}")

            return {
                'total': total_cost,
                'breakdown': breakdown,
                'period': period_name,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }

        except Exception as e:
            logging.error(f"Error getting costs for {period_name}: {e}")
            return {
                'total': 0.0,
                'breakdown': {},
                'period': period_name,
                'error': str(e)
            }

    def _parse_model_from_usage_type(self, usage_type: str) -> str:
        """
        Parse model name from AWS usage type string.

        Usage types typically look like:
        - "APS2-ModelInference-Claude-3-5-Sonnet-v2"
        - "USE1-ModelInference-Titan-Text-Express"
        - "APS2-OnDemand-Throughput"

        Args:
            usage_type: AWS usage type string

        Returns:
            Human-readable model name
        """
        # Remove region prefix (e.g., "APS2-", "USE1-")
        parts = usage_type.split('-')

        if 'ModelInference' in usage_type:
            # Find the index of ModelInference and take everything after it
            try:
                idx = parts.index('ModelInference')
                model_parts = parts[idx + 1:]

                # Join and clean up
                model_name = ' '.join(model_parts)

                # Common model name mappings for readability
                replacements = {
                    'Claude 3 5 Sonnet v2': 'Claude 3.5 Sonnet v2',
                    'Claude 3 5 Sonnet': 'Claude 3.5 Sonnet',
                    'Claude 3 Opus': 'Claude 3 Opus',
                    'Claude 3 Haiku': 'Claude 3 Haiku',
                    'Titan Text Express': 'Titan Text Express',
                    'Titan Text Lite': 'Titan Text Lite',
                }

                for old, new in replacements.items():
                    if old in model_name:
                        model_name = new
                        break

                return model_name
            except (ValueError, IndexError):
                pass

        # If we can't parse it, return the usage type
        return usage_type

    def format_cost_report(self, costs: Optional[Dict]) -> List[str]:
        """
        Format cost information into human-readable lines.

        Args:
            costs: Cost dictionary from get_bedrock_costs()

        Returns:
            List of formatted strings for display
        """
        if not costs:
            return ["Financial tracking not available with current user permissions"]

        lines = []
        currency = costs.get('currency', 'USD')

        # Current Month
        current_month = costs.get('current_month', {})
        if current_month:
            total = current_month.get('total', 0.0)
            breakdown = current_month.get('breakdown', {})
            period = current_month.get('period', _PERIOD_CURRENT_MONTH)

            lines.append(f"{period}: ${total:.2f} {currency}")

            if breakdown and total > 0:
                # Sort by cost (descending)
                sorted_breakdown = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
                for model, cost in sorted_breakdown:
                    percentage = (cost / total * 100) if total > 0 else 0
                    lines.append(f"  • {model}: ${cost:.2f} ({percentage:.1f}%)")

        # Last Month
        last_month = costs.get('last_month', {})
        if last_month:
            total = last_month.get('total', 0.0)
            breakdown = last_month.get('breakdown', {})
            period = last_month.get('period', _PERIOD_LAST_MONTH)

            lines.append(f"{period}: ${total:.2f} {currency}")

            if breakdown and total > 0:
                # Sort by cost (descending)
                sorted_breakdown = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
                for model, cost in sorted_breakdown:
                    percentage = (cost / total * 100) if total > 0 else 0
                    lines.append(f"  • {model}: ${cost:.2f} ({percentage:.1f}%)")

        # Last 24 Hours
        last_24h = costs.get('last_24h', {})
        if last_24h:
            total = last_24h.get('total', 0.0)
            breakdown = last_24h.get('breakdown', {})
            period = last_24h.get('period', 'Last 24 Hours')

            lines.append(f"{period}: ${total:.4f} {currency}")

            if breakdown and total > 0:
                # Sort by cost (descending)
                sorted_breakdown = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
                for model, cost in sorted_breakdown:
                    percentage = (cost / total * 100) if total > 0 else 0
                    lines.append(f"  • {model}: ${cost:.4f} ({percentage:.1f}%)")

        if not lines:
            lines.append("No Bedrock usage costs found for the specified periods")

        return lines
