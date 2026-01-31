"""
Context compaction module for intelligent conversation history management.

This module implements a single-pass LLM-driven compaction system that:
- Analyses conversation history for importance categorisation
- Selectively preserves critical information (architectural decisions, bugs, implementation details)
- Compresses less critical information (resolved tasks, exploration)
- Discards redundant information (duplicates, superseded decisions)

Design Goals:
Compaction is designed to "distill the contents of a context window in a high-fidelity manner,
enabling the agent to continue with minimal performance degradation."
"""

import logging
import json
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime


# Compaction prompt template for single-pass intelligent compaction
COMPACTION_PROMPT_TEMPLATE = '''You are performing context compaction for an ongoing conversation. Your task is to distill the conversation history into a high-fidelity compressed format that enables continuation with minimal performance degradation.

## CATEGORISATION RULES

Analyse each segment of the conversation and categorise it:

### MUST PRESERVE (Full Fidelity)
- **Architectural Decisions**: Any decisions about system design, patterns, or structure with their rationale
- **Unresolved Issues**: Bugs, errors, or problems that have not been fully resolved
- **Implementation Details**: Specific code paths, file locations, configurations that affect future work
- **User Preferences**: Explicit requests, constraints, or preferences stated by the user
- **Critical Data**: Important numbers, calculations, findings, and their sources
- **Active Tasks**: Work in progress, next steps, or pending actions
- **Error Context**: Error messages, stack traces, and debugging information for unresolved issues

### COMPRESS (Reduced Fidelity)
- **Resolved Tasks**: Brief outcome note only (e.g., "Fixed authentication bug in auth.py")
- **Exploratory Discussion**: Conclusions only, not the exploration process
- **Tool Outputs**: Key findings only, not raw output
- **Explanations**: Final understanding only, not iterative clarification

### DISCARD
- **Redundant Information**: Duplicate tool outputs, repeated explanations
- **Superseded Decisions**: Earlier decisions that were later changed
- **Verbose Completions**: Detailed explanations of work that is finished and won't be referenced
- **Pleasantries**: Greetings, acknowledgments, conversational filler

## OUTPUT FORMAT

Produce a structured compacted context in the following format:

# COMPACTED CONTEXT

## Critical Decisions & Architecture
[List architectural decisions with brief rationale - preserve exact details]

## Unresolved Issues
[List any bugs, errors, or problems still being worked on - preserve full context]

## Implementation State
[Current state of implementation: what's done, what's in progress, key file paths]

## Key Data & Findings
[Important numbers, calculations, discoveries with sources - preserve exact values]

## User Preferences & Constraints
[Explicit user requirements and constraints]

## Recent Context Summary
[Brief summary of the most recent exchanges not covered above]

## Discarded Topics
[List topics that were discussed but are no longer relevant - titles only for reference]

## CONVERSATION TO COMPACT

The original conversation contained {message_count} messages with approximately {token_count:,} tokens.

{conversation_history}

## INSTRUCTIONS

1. Read through the entire conversation carefully
2. Categorise each meaningful segment according to the rules above
3. PRESERVE critical information with HIGH FIDELITY - do not lose important details
4. COMPRESS resolved/completed items to brief summaries
5. DISCARD redundant and superseded information
6. Output the structured compacted context
7. Ensure the compacted context contains ALL information needed to continue the conversation effectively
8. For numerical data, preserve EXACT values - do not round or approximate

Begin your compacted context output now:'''


class ContextCompactor:
    """
    Manages intelligent context compaction for conversations.

    This class implements a single-pass LLM-driven compaction that analyses
    conversation history and produces a structured, compressed representation
    while preserving critical information.
    """

    def __init__(self, bedrock_service, database, context_limit_resolver,
                 cli_interface=None, web_interface=None,
                 compaction_threshold: float = 0.7,
                 emergency_threshold: float = 0.95,
                 compaction_ratio: float = 0.3):
        """
        Initialise the context compactor.

        Args:
            bedrock_service: Service for LLM invocation
            database: Database instance for message storage
            context_limit_resolver: ContextLimitResolver instance for model limits
            cli_interface: Optional CLI interface for progress display
            web_interface: Optional web interface for progress display
            compaction_threshold: Fraction of context window to trigger compaction (default 0.7)
            emergency_threshold: Fraction of context window for emergency compaction (default 0.95)
            compaction_ratio: Target ratio for compacted content (default 0.3)
        """
        self.bedrock_service = bedrock_service
        self.database = database
        self.context_limit_resolver = context_limit_resolver
        self.cli_interface = cli_interface
        self.web_interface = web_interface
        self.compaction_threshold = compaction_threshold
        self.emergency_threshold = emergency_threshold
        self.compaction_ratio = compaction_ratio

        logging.info(f"ContextCompactor initialised with threshold={compaction_threshold}, "
                    f"emergency={emergency_threshold}, ratio={compaction_ratio}")

    def update_service(self, bedrock_service):
        """
        Update the LLM service used for compaction.

        This should be called when the active provider changes.

        Args:
            bedrock_service: The new LLM service to use
        """
        old_provider = "unknown"
        new_provider = "unknown"

        if self.bedrock_service and hasattr(self.bedrock_service, 'get_provider_name'):
            old_provider = self.bedrock_service.get_provider_name()
        if bedrock_service and hasattr(bedrock_service, 'get_provider_name'):
            new_provider = bedrock_service.get_provider_name()

        self.bedrock_service = bedrock_service
        logging.info(f"ContextCompactor service updated: {old_provider} -> {new_provider}")

    def check_and_compact(self, conversation_id: int, model_id: str,
                          provider: str, in_tool_use_loop: bool = False) -> bool:
        """
        Check if compaction is needed and perform it.

        Args:
            conversation_id: Current conversation ID
            model_id: Current model ID
            provider: Current provider name
            in_tool_use_loop: Whether currently in tool use sequence

        Returns:
            True if compaction was performed, False otherwise
        """
        # Get context limits for current model
        limits = self.context_limit_resolver.get_context_limits(model_id, provider)
        context_window = limits['context_window']

        # Calculate current token usage
        current_tokens = self.database.get_conversation_token_count(conversation_id)

        # Calculate thresholds
        compaction_threshold_tokens = int(context_window * self.compaction_threshold)
        emergency_threshold_tokens = int(context_window * self.emergency_threshold)

        logging.debug(f"Compaction check: {current_tokens:,}/{context_window:,} tokens "
                     f"(threshold: {compaction_threshold_tokens:,}, emergency: {emergency_threshold_tokens:,})")

        # Check emergency threshold (force compaction even during tool use)
        if current_tokens >= emergency_threshold_tokens:
            usage_pct = current_tokens / context_window * 100
            logging.warning(f"EMERGENCY COMPACTION: {current_tokens:,}/{context_window:,} tokens "
                           f"({usage_pct:.1f}%% of context window)")
            if self.cli_interface:
                self.cli_interface.print_warning(
                    f"Emergency compaction triggered at {current_tokens/context_window*100:.1f}% of context window"
                )
            return self._perform_compaction(conversation_id, model_id, provider, limits)

        # Defer during tool use unless emergency
        if in_tool_use_loop:
            logging.debug(f"Deferring compaction during tool use loop "
                         f"({current_tokens:,}/{emergency_threshold_tokens:,} tokens)")
            return False

        # Normal threshold check
        if current_tokens > compaction_threshold_tokens:
            usage_pct = current_tokens / context_window * 100
            logging.info(f"Compaction triggered: {current_tokens:,}/{compaction_threshold_tokens:,} tokens "
                        f"({usage_pct:.1f}%% of context window)")
            return self._perform_compaction(conversation_id, model_id, provider, limits)

        return False

    def _perform_compaction(self, conversation_id: int, model_id: str,  # noqa: S1172
                            provider: str, limits: Dict[str, int]) -> bool:
        """
        Perform the actual context compaction.

        Args:
            conversation_id: Conversation to compact
            model_id: Current model ID
            provider: Current provider name
            limits: Context limits dict with 'context_window' and 'max_output'

        Returns:
            True if successful, False otherwise
        """
        start_time = datetime.now()
        self._display_progress("🗜️  Starting intelligent context compaction...")
        self._display_separator()

        try:
            messages = self.database.get_conversation_messages(
                conversation_id, include_rolled_up=True
            )
            if len(messages) <= 4:
                logging.warning("Not enough messages to compact")
                self._display_warning("Not enough messages to compact")
                return False

            original_token_count = sum(msg.get('token_count', 0) for msg in messages)
            original_message_count = len(messages)
            self._display_info(
                f"Analysing {original_message_count} messages ({original_token_count:,} tokens)..."
            )

            compaction_prompt = self._build_compaction_prompt(
                self._format_messages_for_compaction(messages),
                original_message_count,
                original_token_count
            )

            rate_limit_check = self._check_rate_limits_for_compaction(
                compaction_prompt, original_token_count
            )
            if not rate_limit_check['can_proceed']:
                self._display_warning(rate_limit_check['message'])
                logging.warning(f"Compaction skipped: {rate_limit_check['message']}")
                return False

            max_compaction_tokens, _ = self._calculate_compaction_tokens(
                compaction_prompt, original_token_count, limits
            )

            self._display_info(f"Generating compacted context (target: {max_compaction_tokens:,} tokens)...")

            compacted_content = self._invoke_compaction_model(compaction_prompt, max_compaction_tokens)
            if compacted_content is None:
                return False

            compacted_token_count = self.bedrock_service.count_tokens(compacted_content)
            if len(compacted_content) < 200:
                logging.warning(f"Compacted content too brief ({len(compacted_content)} chars), aborting")
                self._display_warning("Compacted content too brief, keeping original messages")
                return False

            self._store_compaction_results(
                conversation_id, messages, compacted_content,
                original_message_count, original_token_count,
                compacted_token_count, limits['context_window']
            )

            self._report_compaction_success(
                start_time, original_message_count,
                original_token_count, compacted_token_count
            )
            return True

        except Exception as e:
            logging.error(f"Compaction failed with error: {e}", exc_info=True)
            self._display_error(f"Compaction failed: {str(e)}")
            return False

    def _calculate_compaction_tokens(self, compaction_prompt: str,
                                     original_token_count: int,
                                     limits: Dict[str, int]) -> Tuple[int, int]:
        """Calculate max compaction output tokens and estimate prompt size."""
        max_compaction_tokens = min(
            limits.get('max_output', 8192),
            max(2000, int(original_token_count * self.compaction_ratio)),
            16000
        )

        context_window = limits.get('context_window', 8192)
        if hasattr(self.bedrock_service, 'count_tokens'):
            try:
                prompt_tokens = self.bedrock_service.count_tokens(compaction_prompt)
            except Exception:
                prompt_tokens = len(compaction_prompt) // 4
        else:
            prompt_tokens = len(compaction_prompt) // 4

        max_input_tokens = context_window - max_compaction_tokens - 1000
        if prompt_tokens > max_input_tokens:
            logging.warning(
                f"Compaction prompt ({prompt_tokens:,} tokens) too large for context window "
                f"({context_window:,} tokens with {max_compaction_tokens:,} reserved for output)"
            )
            self._display_warning(
                f"Conversation too large ({prompt_tokens:,} tokens) for compaction in a single pass. "
                f"Context window: {context_window:,} tokens"
            )

        logging.info(
            f"Compaction: input={prompt_tokens:,} tokens, target_output={max_compaction_tokens:,} tokens, "
            f"context_window={context_window:,} tokens"
        )
        return max_compaction_tokens, prompt_tokens

    def _invoke_compaction_model(self, compaction_prompt: str, max_tokens: int) -> Optional[str]:
        """Invoke the LLM for compaction and return content, or None on failure."""
        response = self.bedrock_service.invoke_model(
            [{'role': 'user', 'content': compaction_prompt}],
            max_tokens=max_tokens,
            temperature=0.2
        )

        if not response:
            logging.error("Compaction failed - null response from model")
            self._display_error("Compaction failed - no response from model")
            return None

        if response.get('error'):
            error_msg = response.get('error_message', 'Unknown error')
            error_type = response.get('error_type', 'Unknown')
            logging.error(f"Compaction failed - {error_type}: {error_msg}")
            self._display_error(f"Compaction failed: {error_msg}")
            return None

        content = response.get('content', '')
        if not content and response.get('content_blocks'):
            for block in response.get('content_blocks', []):
                if block.get('type') == 'text':
                    content += block.get('text', '')

        if not content:
            logging.error(f"Compaction failed - empty response. Response keys: {list(response.keys())}")
            self._display_error("Compaction failed - no content in model response")
            return None

        return content.strip()

    def _store_compaction_results(self, conversation_id: int, messages: List[Dict],
                                  compacted_content: str, original_message_count: int,
                                  original_token_count: int, compacted_token_count: int,
                                  context_window: int):
        """Store compaction results in the database."""
        compaction_marker = self._create_compaction_marker(
            original_message_count=original_message_count,
            original_token_count=original_token_count,
            compacted_token_count=compacted_token_count,
            context_window=context_window
        )

        self.database.add_message(
            conversation_id, 'user',
            f"[COMPACTED CONTEXT - {compaction_marker}]\n\n{compacted_content}",
            compacted_token_count
        )

        message_ids = [msg['id'] for msg in messages]
        self.database.mark_messages_as_rolled_up(message_ids)
        self.database.record_rollup(
            conversation_id, original_message_count,
            compacted_content, original_token_count, compacted_token_count
        )

        actual_token_count = self.database.recalculate_total_tokens(conversation_id)
        logging.debug(f"Recalculated total_tokens after compaction: {actual_token_count:,}")

    def _report_compaction_success(self, start_time, original_message_count: int,
                                    original_token_count: int, compacted_token_count: int):
        """Log and display compaction success metrics."""
        elapsed_time = (datetime.now() - start_time).total_seconds()
        reduction_pct = ((original_token_count - compacted_token_count) /
                        original_token_count * 100) if original_token_count > 0 else 0

        logging.info(f"Compaction completed in {elapsed_time:.1f}s: "
                    f"{original_message_count} messages → structured context, "
                    f"{original_token_count:,} → {compacted_token_count:,} tokens "
                    f"({reduction_pct:.1f}%% reduction)")

        self._display_success(
            f"✓ Compaction complete: {original_message_count} messages → structured context"
        )
        self._display_info(
            f"Token reduction: {original_token_count:,} → {compacted_token_count:,} "
            f"({reduction_pct:.1f}%% reduction)"
        )
        self._display_info(f"Completed in {elapsed_time:.1f} seconds")
        self._display_separator()

    def _check_rate_limits_for_compaction(
        self, compaction_prompt: str, original_token_count: int
    ) -> Dict[str, Any]:
        """
        Check if the compaction request would exceed provider rate limits.

        Args:
            compaction_prompt: The full compaction prompt to be sent
            original_token_count: Original token count of messages being compacted

        Returns:
            Dictionary with:
            - can_proceed: bool - Whether compaction can proceed
            - message: str - Explanation message
            - estimated_tokens: int - Estimated input tokens for the request
        """
        # Get rate limits from the service
        rate_limits = None
        if hasattr(self.bedrock_service, 'get_rate_limits'):
            rate_limits = self.bedrock_service.get_rate_limits()

        # If no rate limits or provider doesn't have limits, proceed
        if not rate_limits or not rate_limits.get('has_limits', False):
            return {
                'can_proceed': True,
                'message': 'No rate limits detected',
                'estimated_tokens': original_token_count
            }

        # Estimate input tokens for the compaction request
        # Use the service's token counter if available
        if hasattr(self.bedrock_service, 'count_tokens'):
            try:
                estimated_tokens = self.bedrock_service.count_tokens(compaction_prompt)
            except Exception:
                # Fallback: estimate at 4 chars per token
                estimated_tokens = len(compaction_prompt) // 4
        else:
            estimated_tokens = len(compaction_prompt) // 4

        # Get input token limit
        input_limit = rate_limits.get('input_tokens_per_minute')

        if input_limit and estimated_tokens > input_limit:
            # Request exceeds rate limit - cannot proceed
            provider_name = "Anthropic Direct"
            if hasattr(self.bedrock_service, 'get_provider_name'):
                provider_name = self.bedrock_service.get_provider_name()
            elif hasattr(self.bedrock_service, 'get_active_provider'):
                provider_name = self.bedrock_service.get_active_provider() or provider_name

            message = (
                f"Compaction request ({estimated_tokens:,} tokens) exceeds {provider_name} "
                f"rate limit ({input_limit:,} tokens/minute). "
                f"Consider using AWS Bedrock which has higher rate limits, "
                f"or wait for the conversation to naturally reduce in size."
            )

            logging.warning(
                f"Compaction blocked: {estimated_tokens:,} tokens exceeds "
                f"{input_limit:,} token rate limit for {provider_name}"
            )

            return {
                'can_proceed': False,
                'message': message,
                'estimated_tokens': estimated_tokens,
                'rate_limit': input_limit
            }

        # Within limits, can proceed
        return {
            'can_proceed': True,
            'message': f'Request within rate limits ({estimated_tokens:,}/{input_limit:,} tokens)',
            'estimated_tokens': estimated_tokens,
            'rate_limit': input_limit
        }

    def _format_messages_for_compaction(self, messages: List[Dict]) -> str:
        """
        Format messages into readable conversation history for compaction.

        Handles different message types including tool_use, tool_result,
        and regular messages.

        Args:
            messages: List of message dictionaries from database

        Returns:
            Formatted conversation history string
        """
        formatted_lines = []

        for msg in messages:
            role = msg.get('role', 'unknown').upper()
            content = msg.get('content', '')
            time_str = self._format_timestamp(msg.get('timestamp', ''))
            formatted_lines.extend(self._format_single_message(role, content, time_str))

        return '\n'.join(formatted_lines)

    @staticmethod
    def _format_timestamp(timestamp) -> str:
        """Format a message timestamp into a display string."""
        if not timestamp:
            return ""
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = timestamp
            return f" [{dt.strftime('%Y-%m-%d %H:%M')}]"
        except (ValueError, AttributeError):
            return ""

    def _format_single_message(self, role: str, content: str, time_str: str) -> List[str]:
        """Format a single message into lines. Returns a list of formatted lines."""
        if content.startswith('[COMPACTED CONTEXT'):
            return self._format_compacted_content(content, time_str)

        if content.startswith('[TOOL_RESULTS]'):
            return self._format_tool_results(role, content, time_str)

        if role == 'ASSISTANT' and content.startswith('['):
            result = self._format_tool_use_blocks(role, content, time_str)
            if result is not None:
                return result

        if content.startswith('[Summary of previous conversation]'):
            return [
                f"\n--- PREVIOUS SUMMARY{time_str} ---",
                content,
                "--- END PREVIOUS SUMMARY ---\n",
            ]

        return self._format_regular_message(role, content, time_str)

    @staticmethod
    def _format_compacted_content(content: str, time_str: str) -> List[str]:
        """Format a previously compacted context message."""
        compacted_preview = content[:2000] + "..." if len(content) > 2000 else content
        return [
            f"\n--- PREVIOUS COMPACTION{time_str} ---",
            "[Previous conversation was compacted - key points preserved below]",
            compacted_preview,
            "--- END PREVIOUS COMPACTION ---\n",
        ]

    @staticmethod
    def _format_tool_results(role: str, content: str, time_str: str) -> List[str]:
        """Format a tool results message."""
        lines = [f"\n[{role}]{time_str} Tool Results:"]
        try:
            tool_results_json = content.replace('[TOOL_RESULTS]', '', 1)
            tool_results = json.loads(tool_results_json)
            if isinstance(tool_results, list):
                for i, result in enumerate(tool_results, 1):
                    if isinstance(result, dict) and result.get('type') == 'tool_result':
                        tool_id = result.get('tool_use_id', 'unknown')[:8]
                        result_content = str(result.get('content', ''))
                        if len(result_content) > 500:
                            result_content = result_content[:500] + "... [truncated]"
                        lines.append(f"  Result {i} (tool:{tool_id}): {result_content}")
        except json.JSONDecodeError:
            lines.append(f"  [Raw tool results - {len(content)} chars]")
        return lines

    def _format_tool_use_blocks(self, role: str, content: str, time_str: str) -> Optional[List[str]]:
        """Format assistant tool-use blocks. Returns None if content is not valid JSON blocks."""
        try:
            content_blocks = json.loads(content)
        except json.JSONDecodeError:
            return None

        if not isinstance(content_blocks, list):
            return None

        lines = []
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
            elif block.get('type') == 'tool_use':
                input_summary = self._summarise_tool_input(block.get('input', {}))
                tool_calls.append(f"{block.get('name', 'unknown')}({input_summary})")

        if text_parts:
            lines.append(f"\n[{role}]{time_str}")
            lines.append(''.join(text_parts))
        if tool_calls:
            lines.append(f"[Tool calls: {', '.join(tool_calls)}]")
        return lines

    @staticmethod
    def _format_regular_message(role: str, content: str, time_str: str) -> List[str]:
        """Format a regular text message."""
        lines = [f"\n[{role}]{time_str}"]
        if len(content) > 3000:
            remaining = len(content) - 3000
            lines.append(f"{content[:3000]}\n... [message truncated, {remaining} more chars]")
        else:
            lines.append(content)
        return lines

    def _summarise_tool_input(self, tool_input: Dict) -> str:
        """
        Create a brief summary of tool input for readability.

        Args:
            tool_input: Tool input dictionary

        Returns:
            Brief summary string
        """
        if not tool_input:
            return ""

        # Get key parameters, truncate long values
        parts = []
        for key, value in list(tool_input.items())[:3]:  # Max 3 params
            value_str = str(value)
            if len(value_str) > 50:
                value_str = value_str[:50] + "..."
            parts.append(f"{key}={value_str}")

        if len(tool_input) > 3:
            parts.append(f"...+{len(tool_input) - 3} more")

        return ', '.join(parts)

    def _build_compaction_prompt(self, conversation_history: str,
                                  message_count: int, token_count: int) -> str:
        """
        Build the single-pass compaction prompt.

        Args:
            conversation_history: Formatted conversation history
            message_count: Number of messages being compacted
            token_count: Approximate token count

        Returns:
            Complete compaction prompt
        """
        return COMPACTION_PROMPT_TEMPLATE.format(
            message_count=message_count,
            token_count=token_count,
            conversation_history=conversation_history
        )

    def _create_compaction_marker(self, original_message_count: int,
                                   original_token_count: int,
                                   compacted_token_count: int,
                                   context_window: int) -> str:
        """
        Create a marker string for the compaction event.

        Args:
            original_message_count: Number of messages compacted
            original_token_count: Original token count
            compacted_token_count: Compacted token count
            context_window: Model's context window size

        Returns:
            Formatted marker string
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reduction_pct = ((original_token_count - compacted_token_count) /
                        original_token_count * 100) if original_token_count > 0 else 0

        return (f"Compacted at {timestamp} | "
                f"{original_message_count} messages | "
                f"{original_token_count:,} → {compacted_token_count:,} tokens "
                f"({reduction_pct:.1f}% reduction) | "
                f"Context: {context_window:,} tokens")

    # UI Helper Methods

    def _display_progress(self, message: str):
        """Display progress message via available interface."""
        if self.cli_interface:
            self.cli_interface.print_info(message)
        # Web interface handling would go here if needed

    def _display_info(self, message: str):
        """Display info message via available interface."""
        if self.cli_interface:
            self.cli_interface.print_info(message)

    def _display_success(self, message: str):
        """Display success message via available interface."""
        if self.cli_interface:
            self.cli_interface.print_success(message)

    def _display_warning(self, message: str):
        """Display warning message via available interface."""
        if self.cli_interface:
            self.cli_interface.print_warning(message)

    def _display_error(self, message: str):
        """Display error message via available interface."""
        if self.cli_interface:
            self.cli_interface.print_error(message)

    def _display_separator(self):
        """Display separator via available interface."""
        if self.cli_interface:
            self.cli_interface.print_separator("─")


def get_provider_from_model_id(model_id: str) -> str:
    """
    Attempt to determine provider from model ID.

    Args:
        model_id: The model identifier

    Returns:
        Provider name string
    """
    model_lower = model_id.lower()

    # Check for Anthropic/Claude models
    if 'claude' in model_lower or 'anthropic' in model_lower:
        return 'anthropic'

    # Check for Bedrock-specific patterns
    if 'amazon.' in model_lower or 'titan' in model_lower:
        return 'aws_bedrock'
    if 'meta.' in model_lower or 'llama' in model_lower:
        return 'aws_bedrock'
    if 'mistral.' in model_lower:
        return 'aws_bedrock'
    if 'cohere.' in model_lower:
        return 'aws_bedrock'
    if 'ai21.' in model_lower:
        return 'aws_bedrock'

    # Default to ollama for simple model names
    return 'ollama'
