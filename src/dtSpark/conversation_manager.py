"""
Conversation manager module for handling chat sessions with intelligent context compaction.

This module provides functionality for:
- Managing conversation state and history
- Intelligent context compaction using model-specific context windows
- Message history management with selective preservation
- MCP tool integration
"""

import logging
import asyncio
import json
import concurrent.futures
from typing import List, Dict, Optional, Tuple, Any, Union
from datetime import datetime
from dtSpark.tools import builtin
from dtSpark.mcp_integration import ToolSelector
from dtSpark.limits import LimitStatus
from dtSpark.safety import PromptInspector
from dtSpark.database.tool_permissions import PERMISSION_ALLOWED, PERMISSION_DENIED
from dtSpark.llm.context_limits import ContextLimitResolver
from dtSpark.core.context_compaction import ContextCompactor, get_provider_from_model_id

# String constants to avoid duplication
_ERR_NO_ACTIVE_CONVERSATION = "No active conversation. Create or load a conversation first."
_TOOL_RESULTS_MARKER = '[TOOL_RESULTS]'
_SUMMARY_MARKER = '[Summary of previous conversation]'
_ERR_NO_CONVERSATION_TO_EXPORT = "No conversation loaded to export"
_LABEL_TOKEN_COUNT = 'Token Count'


class ConversationManager:
    """Manages conversation state and automatic rollup for token management."""

    def __init__(self, database, bedrock_service, max_tokens: int = 4096,
                 rollup_threshold: float = 0.8, rollup_summary_ratio: float = 0.3,
                 max_tool_result_tokens: int = 10000, max_tool_iterations: int = 25,
                 max_tool_selections: int = 30, emergency_rollup_threshold: float = 0.95,
                 mcp_manager = None, cli_interface = None, web_interface = None,
                 global_instructions: Optional[str] = None,
                 token_manager = None, prompt_inspector: Optional[PromptInspector] = None,
                 user_guid: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialise the conversation manager.

        Args:
            database: ConversationDatabase instance
            bedrock_service: BedrockService instance
            max_tokens: Maximum token limit for the model
            rollup_threshold: Fraction of max_tokens at which to trigger rollup (0.0-1.0)
            rollup_summary_ratio: Target ratio for summarised content (0.0-1.0)
            max_tool_result_tokens: Maximum tokens per tool result (prevents context overflow)
            max_tool_iterations: Maximum consecutive tool calls before stopping
            max_tool_selections: Maximum number of tools to send with each request
            emergency_rollup_threshold: Force rollup threshold even during tool use (0.0-1.0)
            mcp_manager: Optional MCPManager instance for tool support
            cli_interface: Optional CLI interface for displaying tool calls
            web_interface: Optional Web interface for tool permission prompts
            global_instructions: Optional global instructions that apply to all conversations
            token_manager: Optional TokenManager instance for usage limit enforcement
            prompt_inspector: Optional PromptInspector for security analysis
            user_guid: Optional user GUID for multi-user support
            config: Optional configuration dictionary for embedded tools
        """
        self.database = database
        self.bedrock_service = bedrock_service
        self.default_max_tokens = max_tokens  # Store global default
        self.max_tokens = max_tokens  # Current max_tokens (can be overridden per-conversation)
        self.rollup_threshold = rollup_threshold
        self.rollup_summary_ratio = rollup_summary_ratio
        self.max_tool_result_tokens = max_tool_result_tokens
        self.max_tool_iterations = max_tool_iterations
        self.max_tool_selections = max_tool_selections
        self.emergency_rollup_threshold = emergency_rollup_threshold
        self.current_conversation_id = None
        self.current_instructions: Optional[str] = None
        self.global_instructions: Optional[str] = global_instructions
        self.mcp_manager = mcp_manager
        self.cli_interface = cli_interface
        self.web_interface = web_interface
        self.token_manager = token_manager
        self.prompt_inspector = prompt_inspector
        self.user_guid = user_guid
        self.config = config  # Store config for embedded tools
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._in_tool_use_loop = False  # Flag to defer rollup during tool use sequences
        # Initialise tool selector for intelligent tool selection
        self.tool_selector = ToolSelector(max_tools_per_request=max_tool_selections)

        # Initialise intelligent context compaction system
        self.context_limit_resolver = ContextLimitResolver(config)
        self.context_compactor = ContextCompactor(
            bedrock_service=bedrock_service,
            database=database,
            context_limit_resolver=self.context_limit_resolver,
            cli_interface=cli_interface,
            web_interface=web_interface,
            compaction_threshold=rollup_threshold,
            emergency_threshold=emergency_rollup_threshold,
            compaction_ratio=rollup_summary_ratio
        )
        logging.info("ConversationManager initialised with intelligent context compaction")

    def update_service(self, bedrock_service):
        """
        Update the LLM service used for conversation and compaction.

        This should be called when the active provider/model changes.

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

        # Also update the context compactor's service
        if hasattr(self, 'context_compactor') and self.context_compactor:
            self.context_compactor.update_service(bedrock_service)

        logging.info(f"ConversationManager service updated: {old_provider} -> {new_provider}")

    def get_embedded_tools(self) -> List[Dict[str, Any]]:
        """
        Get embedded/built-in tools in toolSpec format for the web UI.

        Returns:
            List of tool definitions wrapped in {'toolSpec': tool} format
        """
        try:
            # Get raw builtin tools
            raw_tools = builtin.get_builtin_tools(config=self.config)

            # Wrap each tool in toolSpec format for web UI compatibility
            embedded_tools = []
            for tool in raw_tools:
                embedded_tools.append({
                    'toolSpec': {
                        'name': tool.get('name', 'unknown'),
                        'description': tool.get('description', ''),
                        'inputSchema': tool.get('input_schema', {})
                    }
                })

            return embedded_tools

        except Exception as e:
            logging.warning(f"Error getting embedded tools: {e}")
            return []

    @staticmethod
    def _extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
        """
        Extract text from content which can be either a string or list of content blocks.

        Args:
            content: Either a string or list of content blocks (e.g., [{'text': 'Hello'}])

        Returns:
            Extracted text as a string
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Extract text from all text blocks and concatenate
            text_parts = []
            for block in content:
                if isinstance(block, dict) and 'text' in block:
                    text_parts.append(block['text'])
            return ''.join(text_parts)
        else:
            return ''

    def create_conversation(self, name: str, model_id: str, instructions: Optional[str] = None,
                            compaction_threshold: Optional[float] = None) -> int:
        """
        Create a new conversation.

        Args:
            name: Name for the conversation
            model_id: Bedrock model ID to use
            instructions: Optional instructions/system prompt for the conversation
            compaction_threshold: Optional compaction threshold override (0.0-1.0, None uses global default)

        Returns:
            ID of the newly created conversation
        """
        conversation_id = self.database.create_conversation(name, model_id, instructions,
                                                             compaction_threshold=compaction_threshold)
        self.current_conversation_id = conversation_id
        self.current_instructions = instructions

        # Update context compactor with conversation-specific threshold if set
        if compaction_threshold is not None:
            self.context_compactor.compaction_threshold = compaction_threshold
            logging.info(f"Using conversation-specific compaction threshold: {compaction_threshold:.0%}")
        else:
            # Reset to global default
            self.context_compactor.compaction_threshold = self.rollup_threshold
            logging.info(f"Using global default compaction threshold: {self.rollup_threshold:.0%}")

        logging.info(f"Created new conversation: {name} (ID: {conversation_id})")
        return conversation_id

    def load_conversation(self, conversation_id: int) -> bool:
        """
        Load an existing conversation.

        Args:
            conversation_id: ID of the conversation to load

        Returns:
            True if loaded successfully, False otherwise
        """
        conversation = self.database.get_conversation(conversation_id)
        if conversation:
            self.current_conversation_id = conversation_id
            self.current_instructions = conversation.get('instructions')

            # Load conversation-specific max_tokens if set (otherwise use global default)
            conversation_max_tokens = conversation.get('max_tokens')
            if conversation_max_tokens is not None:
                self.max_tokens = conversation_max_tokens
                logging.info(f"Using conversation-specific max_tokens: {conversation_max_tokens}")
            else:
                # Reset to global default (in case previous conversation had custom value)
                self.max_tokens = self.default_max_tokens
                logging.info(f"Using global default max_tokens: {self.default_max_tokens}")

            # Load conversation-specific compaction_threshold if set (otherwise use global default)
            conversation_compaction_threshold = conversation.get('compaction_threshold')
            if conversation_compaction_threshold is not None:
                self.context_compactor.compaction_threshold = conversation_compaction_threshold
                logging.info(f"Using conversation-specific compaction threshold: {conversation_compaction_threshold:.0%}")
            else:
                # Reset to global default (in case previous conversation had custom value)
                self.context_compactor.compaction_threshold = self.rollup_threshold
                logging.info(f"Using global default compaction threshold: {self.rollup_threshold:.0%}")

            logging.info(f"Loaded conversation: {conversation['name']} (ID: {conversation_id})")
            return True
        else:
            logging.error(f"Conversation {conversation_id} not found")
            return False

    def add_user_message(self, content: str) -> int:
        """
        Add a user message to the current conversation.

        Args:
            content: Message content

        Returns:
            Message ID
        """
        if not self.current_conversation_id:
            raise ValueError(_ERR_NO_ACTIVE_CONVERSATION)

        token_count = self.bedrock_service.count_tokens(content)
        message_id = self.database.add_message(
            self.current_conversation_id,
            'user',
            content,
            token_count
        )

        logging.debug(f"Added user message ({token_count} tokens)")

        # Check if rollup is needed after adding the message
        self._check_and_perform_rollup()

        return message_id

    def add_assistant_message(self, content: str) -> int:
        """
        Add an assistant message to the current conversation.

        Args:
            content: Message content

        Returns:
            Message ID
        """
        if not self.current_conversation_id:
            raise ValueError(_ERR_NO_ACTIVE_CONVERSATION)

        token_count = self.bedrock_service.count_tokens(content)
        message_id = self.database.add_message(
            self.current_conversation_id,
            'assistant',
            content,
            token_count
        )

        logging.debug(f"Added assistant message ({token_count} tokens)")

        # Check if rollup is needed after adding the message
        self._check_and_perform_rollup()

        return message_id

    def get_messages_for_model(self) -> List[Dict[str, Any]]:
        """
        Get messages formatted for model input (excluding rolled-up messages).
        Properly formats tool use and tool result messages for Claude API.
        Validates that tool_use blocks have corresponding tool_result blocks.

        Returns:
            List of message dictionaries with 'role' and 'content'
        """
        if not self.current_conversation_id:
            return []

        messages = self.database.get_conversation_messages(
            self.current_conversation_id,
            include_rolled_up=False
        )

        # Format for model
        formatted_messages = []
        for msg in messages:
            content = msg['content']

            # Check if this is a tool-related message (stored as JSON)
            if msg['role'] == 'assistant' and content.startswith('['):
                # This is likely a tool_use message stored as JSON
                try:
                    content_blocks = json.loads(content)
                    formatted_messages.append({
                        'role': 'assistant',
                        'content': content_blocks
                    })
                    continue
                except json.JSONDecodeError:
                    pass  # Not JSON, treat as regular message

            if msg['role'] == 'user' and content.startswith(_TOOL_RESULTS_MARKER):
                # This is a tool results message
                try:
                    tool_results_json = content.replace(_TOOL_RESULTS_MARKER, '', 1)
                    tool_results = json.loads(tool_results_json)
                    formatted_messages.append({
                        'role': 'user',
                        'content': tool_results
                    })
                    continue
                except json.JSONDecodeError:
                    pass  # Not JSON, treat as regular message

            # Regular message
            formatted_messages.append({
                'role': msg['role'],
                'content': content
            })

        # Validate tool_use/tool_result pairing to prevent API errors
        validated_messages = []
        orphaned_tool_ids = set()  # Track tool_use IDs that were filtered out
        i = 0

        while i < len(formatted_messages):
            msg = formatted_messages[i]

            # Check if this is an assistant message with tool_use blocks
            if msg['role'] == 'assistant' and isinstance(msg['content'], list):
                has_tool_use = any(block.get('type') == 'tool_use' for block in msg['content'] if isinstance(block, dict))

                if has_tool_use:
                    # Verify the next message is a user message with tool_results
                    if i + 1 < len(formatted_messages):
                        next_msg = formatted_messages[i + 1]
                        if next_msg['role'] == 'user' and isinstance(next_msg['content'], list):
                            has_tool_result = any(block.get('type') == 'tool_result' for block in next_msg['content'] if isinstance(block, dict))
                            if has_tool_result:
                                # Valid pair - add both messages
                                validated_messages.append(msg)
                                validated_messages.append(next_msg)
                                i += 2
                                continue

                    # Orphaned tool_use - collect IDs and filter out tool_use blocks
                    tool_use_ids = [block.get('id') for block in msg['content']
                                   if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id')]
                    orphaned_tool_ids.update(tool_use_ids)

                    logging.warning(f"Found orphaned tool_use blocks at message {i} (IDs: {tool_use_ids}), filtering out")
                    filtered_content = [block for block in msg['content']
                                       if not (isinstance(block, dict) and block.get('type') == 'tool_use')]
                    if filtered_content:
                        validated_messages.append({
                            'role': 'assistant',
                            'content': filtered_content
                        })
                    i += 1
                    continue

            # Check if this is a user message with tool_results for orphaned tool_use blocks
            if msg['role'] == 'user' and isinstance(msg['content'], list) and orphaned_tool_ids:
                # Filter out tool_results that reference orphaned tool_use IDs
                filtered_content = [block for block in msg['content']
                                   if not (isinstance(block, dict) and
                                          block.get('type') == 'tool_result' and
                                          block.get('tool_use_id') in orphaned_tool_ids)]

                # If we filtered out any tool_results, log it
                if len(filtered_content) < len(msg['content']):
                    removed_ids = [block.get('tool_use_id') for block in msg['content']
                                  if isinstance(block, dict) and
                                  block.get('type') == 'tool_result' and
                                  block.get('tool_use_id') in orphaned_tool_ids]
                    logging.warning(f"Filtered out orphaned tool_results at message {i} (tool_use_ids: {removed_ids})")

                # Only add the message if there's content left
                if filtered_content:
                    validated_messages.append({
                        'role': 'user',
                        'content': filtered_content
                    })
                i += 1
                continue

            # Regular message or already validated - add it
            validated_messages.append(msg)
            i += 1

        return validated_messages

    def get_conversation_history(self, include_rolled_up: bool = False) -> List[Dict]:
        """
        Get full conversation history including metadata.

        Args:
            include_rolled_up: Whether to include messages that have been rolled up (default: False for chat, True for export)

        Returns:
            List of message dictionaries with all fields
        """
        if not self.current_conversation_id:
            return []

        return self.database.get_conversation_messages(
            self.current_conversation_id,
            include_rolled_up=include_rolled_up
        )

    def get_last_assistant_message(self) -> Optional[str]:
        """
        Get the last assistant message content for copying to clipboard.

        Returns:
            The text content of the last assistant message, or None if no assistant message exists
        """
        if not self.current_conversation_id:
            return None

        messages = self.get_conversation_history(include_rolled_up=False)

        # Find the last assistant message
        for message in reversed(messages):
            if message['role'] == 'assistant':
                content = message['content']

                # Check if it's a JSON tool use message
                if content.startswith('[') and content.strip().endswith(']'):
                    try:
                        blocks = json.loads(content)
                        if isinstance(blocks, list):
                            # Extract text blocks only (skip tool_use blocks)
                            text_parts = []
                            for block in blocks:
                                if isinstance(block, dict) and block.get('type') == 'text':
                                    text_parts.append(block.get('text', ''))
                            if text_parts:
                                return '\n'.join(text_parts)
                    except ValueError:
                        # Not JSON, return as-is
                        pass

                # Check if it's a rollup summary
                if content.startswith(_SUMMARY_MARKER):
                    return content

                # Regular assistant message
                return content

        return None

    def _check_and_perform_rollup(self):
        """
        Check if context compaction is needed and perform it if threshold is exceeded.

        Uses intelligent context compaction with model-specific context window limits.
        Defers compaction if currently in a tool use loop to avoid breaking
        tool_use/tool_result sequences, unless we've reached the emergency threshold.
        """
        if not self.current_conversation_id:
            return

        # Get current model ID and provider for context limit lookup
        model_id = self._get_current_model_id()
        provider = self._get_current_provider()

        # Delegate to the intelligent context compactor
        self.context_compactor.check_and_compact(
            conversation_id=self.current_conversation_id,
            model_id=model_id,
            provider=provider,
            in_tool_use_loop=self._in_tool_use_loop
        )

    def _get_current_model_id(self) -> str:
        """
        Get the model ID for the current conversation.

        Returns:
            Model ID string, or 'unknown' if not available
        """
        if self.current_conversation_id:
            conv = self.database.get_conversation(self.current_conversation_id)
            if conv:
                return conv.get('model_id', 'unknown')
        return 'unknown'

    def _get_current_provider(self) -> str:
        """
        Get the provider for the current model.

        Attempts to determine the provider from:
        1. The bedrock_service type
        2. The model ID pattern

        Returns:
            Provider name string
        """
        # Try to get provider from service type
        if hasattr(self.bedrock_service, 'get_provider_name'):
            provider = self.bedrock_service.get_provider_name()
            if provider:
                return provider.lower().replace(' ', '_')

        # Fall back to inferring from model ID
        model_id = self._get_current_model_id()
        return get_provider_from_model_id(model_id)

    def _perform_rollup(self):
        """
        Perform conversation rollup by summarising older messages.
        Ensures tool_use/tool_result pairs are never split.
        """
        # Display rollup start notification
        if self.cli_interface:
            self.cli_interface.print_separator("─")
            self.cli_interface.print_info("⚙️  Starting conversation rollup to manage token usage...")
            self.cli_interface.print_separator("─")

        messages = self.database.get_conversation_messages(
            self.current_conversation_id,
            include_rolled_up=False
        )

        if len(messages) <= 2:
            logging.warning("Not enough messages to perform rollup")
            if self.cli_interface:
                self.cli_interface.print_warning("Not enough messages to perform rollup")
            return

        # Find a safe cutoff point that doesn't split tool_use/tool_result pairs
        # Start with keeping at least the last 2 complete exchanges (4 messages)
        messages_to_keep_count = 4

        # Look backwards from the cutoff point to ensure we don't split tool pairs
        # If the message at the cutoff is a tool_result, we need to keep its tool_use too
        cutoff_index = len(messages) - messages_to_keep_count

        while cutoff_index > 0:
            cutoff_msg = messages[cutoff_index] if cutoff_index < len(messages) else None

            if cutoff_msg and cutoff_msg['content'].startswith(_TOOL_RESULTS_MARKER):
                # This is a tool_result message, we need to keep the preceding tool_use
                # Move cutoff back one more message
                cutoff_index -= 1
                messages_to_keep_count += 1
            else:
                # Safe to cut here
                break

        # Also check if the message right before cutoff is a tool_use without result
        if cutoff_index > 0:
            prev_msg = messages[cutoff_index - 1]
            if prev_msg['role'] == 'assistant' and prev_msg['content'].startswith('['):
                try:
                    # Check if it's a tool_use message
                    content_blocks = json.loads(prev_msg['content'])
                    if any(block.get('type') == 'tool_use' for block in content_blocks):
                        # Move cutoff back to include this tool_use and its result
                        cutoff_index -= 1
                        messages_to_keep_count += 1
                except ValueError:
                    pass

        messages_to_summarise = messages[:cutoff_index] if cutoff_index > 0 else []

        if not messages_to_summarise or len(messages_to_summarise) == 0:
            logging.warning("No messages available for rollup after ensuring tool pairs stay together")
            if self.cli_interface:
                self.cli_interface.print_warning("No messages available for rollup")
            return

        # Calculate original token count
        original_token_count = sum(msg['token_count'] for msg in messages_to_summarise)

        # Display rollup details
        if self.cli_interface:
            self.cli_interface.print_info(f"Summarising {len(messages_to_summarise)} messages ({original_token_count:,} tokens)...")

        # Create a summary of the older messages
        summary_content = self._create_summary(messages_to_summarise)
        summary_token_count = self.bedrock_service.count_tokens(summary_content)

        # Add the summary as a user message (Claude doesn't accept 'system' role in messages)
        self.database.add_message(
            self.current_conversation_id,
            'user',
            f"{_SUMMARY_MARKER}\n{summary_content}",
            summary_token_count
        )

        # Mark old messages as rolled up
        message_ids = [msg['id'] for msg in messages_to_summarise]
        self.database.mark_messages_as_rolled_up(message_ids)

        # Record the rollup operation
        self.database.record_rollup(
            self.current_conversation_id,
            len(messages_to_summarise),
            summary_content,
            original_token_count,
            summary_token_count
        )

        token_reduction = original_token_count - summary_token_count
        logging.info(f"Rollup completed: {len(messages_to_summarise)} messages summarised, "
                    f"reduced tokens by {token_reduction}")

        # Display rollup completion
        if self.cli_interface:
            reduction_pct = (token_reduction / original_token_count * 100) if original_token_count > 0 else 0
            self.cli_interface.print_success(f"✓ Rollup completed: {len(messages_to_summarise)} messages → 1 summary")
            self.cli_interface.print_info(f"Token reduction: {original_token_count:,} → {summary_token_count:,} ({reduction_pct:.1f}% reduction)")
            self.cli_interface.print_separator("─")

    def _calculate_suggested_max_tokens(self) -> int:
        """
        Calculate a suggested max_tokens value when current limit is hit.
        Uses common model token limits as suggestions.

        Returns:
            Suggested max_tokens value
        """
        current = self.max_tokens

        # Common model token limits
        common_limits = [4096, 8192, 16384, 32768, 65536, 131072, 200000]

        # Find next higher limit
        for limit in common_limits:
            if limit > current:
                return limit

        # If already at highest, suggest 2x current
        return current * 2

    def update_conversation_max_tokens(self, new_max_tokens: int) -> bool:
        """
        Update the max_tokens setting for the current conversation.

        Args:
            new_max_tokens: New max_tokens value

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.error("Cannot update max_tokens: no active conversation")
            return False

        try:
            # Update in database
            self.database.update_conversation_max_tokens(
                self.current_conversation_id,
                new_max_tokens
            )

            # Update in memory
            self.max_tokens = new_max_tokens

            logging.info(f"Updated max_tokens for conversation {self.current_conversation_id} to {new_max_tokens}")
            return True
        except Exception as e:
            logging.error(f"Failed to update max_tokens: {e}")
            return False

    def _detect_synthesis_response(self, assistant_message: str, tool_call_history: List[str]) -> bool:
        """
        Detect if the assistant's response appears to be creating a synthesis/summary document
        that aggregates data from multiple sources.

        Args:
            assistant_message: The assistant's message content
            tool_call_history: List of tool names called in this conversation turn

        Returns:
            True if synthesis/aggregation is detected
        """
        if not assistant_message:
            return False

        message_lower = assistant_message.lower()

        # Patterns that indicate synthesis/summary documents
        synthesis_patterns = [
            'executive summary',
            'cost summary',
            'overall summary',
            'combined total',
            'total savings',
            'in total',
            'altogether',
            'aggregated',
            'consolidated',
            'across all accounts',
            'across all',
            'total potential',
            'combined savings',
            'grand total',
            'overall cost'
        ]

        # Check for synthesis patterns in message
        for pattern in synthesis_patterns:
            if pattern in message_lower:
                logging.debug(f"Synthesis pattern detected: '{pattern}'")
                return True

        # Check if creating summary documents via tools
        summary_tool_patterns = ['summary', 'executive', 'total', 'overview']
        for tool_name in tool_call_history[-5:]:  # Check last 5 tools
            tool_lower = tool_name.lower()
            for pattern in summary_tool_patterns:
                if pattern in tool_lower or ('append' in tool_lower and pattern in message_lower):
                    logging.debug(f"Summary document creation detected via tool: {tool_name}")
                    return True

        # Check for numerical aggregation patterns with currency
        aggregation_with_numbers = [
            r'total.*\$[\d,]+',
            r'combined.*\$[\d,]+',
            r'overall.*\$[\d,]+',
            r'savings.*\$[\d,]+.*-.*\$[\d,]+'  # Range of savings
        ]

        import re
        for pattern in aggregation_with_numbers:
            if re.search(pattern, message_lower):
                logging.debug(f"Numerical aggregation pattern detected: '{pattern}'")
                return True

        return False

    def _extract_numerical_data(self, content: str) -> Optional[str]:
        """
        Extract numerical data and key findings from tool results.

        Args:
            content: Tool result content string

        Returns:
            Extracted numerical data summary or None
        """
        try:
            import json
            import re

            # Remove [TOOL_RESULTS] prefix if present
            if content.startswith(_TOOL_RESULTS_MARKER):
                content = content[len(_TOOL_RESULTS_MARKER):].strip()

            # Try to parse as JSON
            try:
                data = json.loads(content)
            except ValueError:
                # Not JSON, try to extract numbers from text
                data = None

            findings = []

            # Extract from JSON structure
            if data:
                # Look for common patterns in tool results
                if isinstance(data, dict):
                    # Look for summary, total, savings, cost patterns
                    for key in ['summary', 'total', 'savings', 'cost', 'amount', 'count', 'potential_savings']:
                        if key in data:
                            value = data[key]
                            if isinstance(value, (int, float)):
                                findings.append(f"{key}: {value}")
                            elif isinstance(value, dict):
                                # Nested summary data
                                for subkey, subval in value.items():
                                    if isinstance(subval, (int, float)):
                                        findings.append(f"{key}.{subkey}: {subval}")

                elif isinstance(data, list) and len(data) > 0:
                    # List of items - report count
                    findings.append(f"Items count: {len(data)}")

            # Extract currency amounts from text (e.g., $1,234.56, USD $1,234)
            currency_pattern = r'(?:USD\s*)?\$\s*[\d,]+(?:\.\d{2})?(?:\s*(?:million|thousand|billion|[KMB]))?'
            currencies = re.findall(currency_pattern, content, re.IGNORECASE)
            if currencies:
                # Limit to first 5 to avoid overwhelming the summary
                findings.extend([f"Currency value: {c.strip()}" for c in currencies[:5]])

            # Extract percentages
            percentage_pattern = r'\d+(?:\.\d+)?%'
            percentages = re.findall(percentage_pattern, content)
            if percentages:
                findings.extend([f"Percentage: {p}" for p in percentages[:5]])

            # Extract large numbers (likely significant)
            number_pattern = r'\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b'
            numbers = re.findall(number_pattern, content)
            if numbers:
                findings.extend([f"Value: {n}" for n in numbers[:5]])

            if findings:
                return "Key data: " + "; ".join(findings[:10])  # Limit to 10 findings

            return None

        except Exception as e:
            logging.debug(f"Error extracting numerical data: {e}")
            return None

    def _create_summary(self, messages: List[Dict]) -> str:
        """
        Create a summary of messages using the Bedrock model.

        Args:
            messages: List of message dictionaries to summarise

        Returns:
            Summary text
        """
        # Build a prompt for summarisation - clean up tool use content
        conversation_text = []
        numerical_data_found = []

        for msg in messages:
            role = msg['role'].capitalize()
            content = msg['content']

            # Parse and clean tool-related content for better summarization
            if content.startswith(_TOOL_RESULTS_MARKER):
                # Extract numerical data from tool results
                numerical_summary = self._extract_numerical_data(content)
                if numerical_summary:
                    conversation_text.append(f"{role}: [Tool execution results - {numerical_summary}]")
                    numerical_data_found.append(numerical_summary)
                else:
                    conversation_text.append(f"{role}: [Received tool execution results]")
            elif content.startswith('['):
                # Try to parse tool_use blocks
                try:
                    import json
                    content_blocks = json.loads(content)
                    text_parts = []
                    tool_parts = []
                    for block in content_blocks:
                        if block.get('type') == 'text':
                            text_parts.append(block.get('text', ''))
                        elif block.get('type') == 'tool_use':
                            tool_parts.append(f"used tool {block.get('name')}")

                    # Combine text and tool use descriptions
                    if text_parts:
                        conversation_text.append(f"{role}: {' '.join(text_parts)}")
                    if tool_parts:
                        conversation_text.append(f"{role}: [Called tools: {', '.join(tool_parts)}]")
                except ValueError:
                    # If parsing fails, include content as-is
                    conversation_text.append(f"{role}: {content}")
            else:
                conversation_text.append(f"{role}: {content}")

        full_conversation = '\n\n'.join(conversation_text)

        # Calculate sensible token targets
        original_tokens = sum(msg['token_count'] for msg in messages)
        target_tokens = int(original_tokens * self.rollup_summary_ratio)
        # Ensure minimum of 500 tokens and maximum of 3000 for summary
        max_summary_tokens = max(500, min(target_tokens, 3000))

        # Build the summary prompt with emphasis on numerical data if present
        numerical_data_section = ""
        if numerical_data_found:
            numerical_data_section = f"""
CRITICAL - NUMERICAL DATA DETECTED:
The conversation contains important numerical data from tool results. You MUST preserve these exact values in your summary:
{chr(10).join(['- ' + data for data in numerical_data_found[:20]])}

When summarising, explicitly include these numerical values to maintain accuracy.
"""

        summary_prompt = [
            {
                'role': 'user',
                'content': f"""Please provide a comprehensive summary of the following conversation.

IMPORTANT: Focus on preserving:
- Key decisions and conclusions
- Important data, numbers, and findings (especially calculations, totals, costs, savings)
- Action items and tasks completed
- Critical context needed to continue the conversation
- Any errors or corrections that were identified
{numerical_data_section}
The original conversation contained {len(messages)} messages with {original_tokens} tokens.
Your summary should capture the essential information in approximately {target_tokens} tokens.

Conversation to summarise:
{full_conversation}

Summary:"""
            }
        ]

        # Use the current model to generate the summary
        response = self.bedrock_service.invoke_model(
            summary_prompt,
            max_tokens=max_summary_tokens,
            temperature=0.3  # Lower temperature for more focused summary
        )

        if response and response.get('content'):
            summary_text = response['content'].strip()
            # Verify summary is not trivial
            if len(summary_text) < 50:
                logging.warning(f"Summary too brief ({len(summary_text)} chars), using detailed fallback")
                return f"Previous conversation covered {len(messages)} messages discussing:\n" + '\n'.join(conversation_text[:5])
            return summary_text
        else:
            # Fallback to simple concatenation if summarisation fails
            logging.warning("Model summarisation failed, using detailed fallback")
            return f"Previous conversation covered {len(messages)} messages:\n" + '\n'.join(conversation_text[:10])

    def get_active_conversations(self) -> List[Dict]:
        """
        Get list of all active conversations.

        Returns:
            List of conversation dictionaries
        """
        return self.database.get_active_conversations()

    def get_current_token_count(self) -> int:
        """
        Get the current token count for the active conversation.

        Returns:
            Total token count
        """
        if not self.current_conversation_id:
            return 0

        return self.database.get_conversation_token_count(self.current_conversation_id)

    def get_current_conversation_info(self) -> Optional[Dict]:
        """
        Get information about the current conversation.

        Returns:
            Conversation dictionary or None
        """
        if not self.current_conversation_id:
            return None

        return self.database.get_conversation(self.current_conversation_id)

    def get_context_window(self) -> int:
        """
        Get the context window size for the current conversation's model.

        Uses the ContextLimitResolver to determine the actual context window
        based on the model ID and provider.

        Returns:
            Context window size in tokens, or default of 8192 if unavailable
        """
        conv_info = self.get_current_conversation_info()
        if not conv_info:
            return 8192  # Safe default

        model_id = conv_info.get('model_id', '')
        if not model_id:
            return 8192

        # Determine provider from model ID
        provider = get_provider_from_model_id(model_id)

        # Get context window from resolver
        return self.context_limit_resolver.get_context_window(model_id, provider)

    def change_model(self, new_model_id: str) -> bool:
        """
        Change the model for the current conversation.

        Args:
            new_model_id: ID of the new model to use

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.warning("No conversation loaded to change model")
            return False

        try:
            # Update conversation model in database
            cursor = self.database.conn.cursor()
            cursor.execute('''
                UPDATE conversations
                SET model_id = ?
                WHERE id = ?
            ''', (new_model_id, self.current_conversation_id))
            self.database.conn.commit()

            # Update bedrock service to use new model
            self.bedrock_service.set_model(new_model_id)

            logging.info(f"Changed model to {new_model_id} for conversation {self.current_conversation_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to change model: {e}")
            self.database.conn.rollback()
            return False

    def update_instructions(self, instructions: Optional[str]) -> bool:
        """
        Update the instructions/system prompt for the current conversation.

        Args:
            instructions: New instructions (None to clear)

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.warning("No conversation loaded to update instructions")
            return False

        try:
            # Update instructions in database
            self.database.update_conversation_instructions(self.current_conversation_id, instructions)

            logging.info(f"Updated instructions for conversation {self.current_conversation_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to update instructions: {e}")
            return False

    def get_model_usage_breakdown(self) -> List[Dict]:
        """
        Get per-model token usage breakdown for the current conversation.

        Returns:
            List of dictionaries with model usage details
        """
        if not self.current_conversation_id:
            return []

        return self.database.get_model_usage_breakdown(self.current_conversation_id)

    def _get_embedded_system_instructions(self) -> str:
        """
        Generate embedded system instructions that take priority over all other instructions.
        These include Spark's identity and current date/time with timezone.

        Returns:
            Embedded system instructions string
        """
        # Get current datetime with timezone
        now = datetime.now().astimezone()

        # Format: "Monday, 17 November 2025 at 02:30:45 PM AEDT (UTC+1100)"
        datetime_str = now.strftime("%A, %d %B %Y at %I:%M:%S %p %Z (UTC%z)")

        # Build embedded instructions
        embedded_instructions = f"""Your name is Spark which is short for "Secure Personal AI Research Kit".

Current date and time: {datetime_str}"""

        return embedded_instructions

    def _get_combined_instructions(self) -> Optional[str]:
        """
        Combine embedded, global and conversation-specific instructions.
        Priority order (highest to lowest):
        1. Embedded system instructions (identity, date/time)
        2. Global instructions (prepended to prevent override)
        3. Conversation-specific instructions

        Returns:
            Combined instructions string, or None if no instructions exist
        """
        instructions_parts = []

        # Add embedded system instructions first (highest priority - always present)
        instructions_parts.append(self._get_embedded_system_instructions())

        # Add global instructions second (if they exist)
        if self.global_instructions:
            instructions_parts.append(self.global_instructions)

        # Add conversation-specific instructions last (if they exist)
        if self.current_instructions:
            instructions_parts.append(self.current_instructions)

        # Return combined instructions (always at least embedded instructions)
        return '\n\n'.join(instructions_parts)

    def get_all_mcp_server_names(self) -> List[str]:
        """Get names of all available MCP servers."""
        if not self.mcp_manager:
            return []
        # MCPManager uses 'clients' attribute, not 'servers'
        if not hasattr(self.mcp_manager, 'clients'):
            logging.warning("MCPManager does not have 'clients' attribute")
            return []
        return list(self.mcp_manager.clients.keys())

    def get_mcp_server_states(self) -> List[Dict]:
        """
        Get enabled/disabled state for all MCP servers in current conversation.

        Returns:
            List of dicts with 'server_name' and 'enabled' keys
        """
        if not self.current_conversation_id or not self.mcp_manager:
            return []

        all_servers = self.get_all_mcp_server_names()
        return self.database.get_all_mcp_server_states(self.current_conversation_id, all_servers)

    def set_mcp_server_enabled(self, server_name: str, enabled: bool) -> bool:
        """
        Enable or disable an MCP server for the current conversation.
        Invalidates tool cache to force reload with new server states.

        Args:
            server_name: Name of the MCP server
            enabled: True to enable, False to disable

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.error("No active conversation")
            return False

        if not self.mcp_manager:
            logging.error("MCP manager not available")
            return False

        # Check if server exists (MCPManager uses 'clients' attribute)
        if not hasattr(self.mcp_manager, 'clients') or server_name not in self.mcp_manager.clients:
            logging.error(f"MCP server '{server_name}' not found")
            return False

        # Update database
        if self.database.set_mcp_server_enabled(self.current_conversation_id, server_name, enabled):
            # Invalidate tools cache to force reload with new enabled servers
            self._tools_cache = None
            logging.info(f"Invalidated tools cache after {'enabling' if enabled else 'disabling'} server '{server_name}'")
            return True
        return False

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """
        Get available tools from MCP servers and built-in tools in Claude-compatible format.

        Returns:
            List of tool definitions
        """
        # Cache tools to avoid repeated async calls
        if self._tools_cache is not None:
            logging.debug(f"Returning cached tools: {len(self._tools_cache)} tools")
            return self._tools_cache

        # Start with built-in tools (always available)
        all_tools = []
        try:
            builtin_tool_list = builtin.get_builtin_tools(config=self.config)
            for tool in builtin_tool_list:
                # Mark as built-in tool
                tool['server'] = 'builtin'
                tool['original_name'] = tool['name']  # Built-in tools don't need renaming
                all_tools.append(tool)
            logging.info(f"Loaded {len(builtin_tool_list)} built-in tool(s)")
        except Exception as e:
            logging.error(f"Failed to load built-in tools: {e}")

        # Return early if no MCP manager (just built-in tools)
        if not self.mcp_manager:
            self._tools_cache = all_tools
            return all_tools

        try:
            logging.debug("Fetching tools from MCP servers...")

            # Check if we're already in a running event loop (e.g., from FastAPI)
            try:
                running_loop = asyncio.get_running_loop()
                # We're in an async context - use run_coroutine_threadsafe
                logging.debug("Detected running event loop, using thread-safe approach")

                # Run the coroutine in the existing loop from a thread pool
                def run_in_loop():
                    # Create a new event loop for this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(
                            asyncio.wait_for(
                                self.mcp_manager.list_all_tools(),
                                timeout=10.0
                            )
                        )
                        return result
                    except asyncio.TimeoutError:
                        logging.error("Timeout fetching MCP tools after 10 seconds")
                        return []
                    finally:
                        new_loop.close()

                # Run in thread pool to avoid event loop conflict
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_in_loop)
                    mcp_tools = future.result(timeout=15.0)  # Give extra time for thread overhead

            except RuntimeError:
                # No running event loop - we're in sync context
                logging.debug("No running event loop detected, using standard approach")

                # Use the initialization loop if available, otherwise create new one
                if hasattr(self.mcp_manager, '_initialization_loop') and self.mcp_manager._initialization_loop:
                    loop = self.mcp_manager._initialization_loop
                    # Add timeout to prevent indefinite hanging
                    mcp_tools = loop.run_until_complete(
                        asyncio.wait_for(
                            self.mcp_manager.list_all_tools(),
                            timeout=10.0  # 10 second timeout
                        )
                    )
                else:
                    # Fallback: create temporary loop (shouldn't normally happen)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        mcp_tools = loop.run_until_complete(
                            asyncio.wait_for(
                                self.mcp_manager.list_all_tools(),
                                timeout=10.0
                            )
                        )
                    except asyncio.TimeoutError:
                        logging.error("Timeout fetching MCP tools after 10 seconds")
                        mcp_tools = []
                    finally:
                        loop.close()

            logging.debug(f"Fetched {len(mcp_tools)} tools from MCP servers")

            # Detect and handle duplicate tool names by prefixing with server name
            tool_name_counts = {}
            for tool in mcp_tools:
                tool_name = tool['name']
                tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1

            # Identify which tools need prefixing (appear more than once)
            duplicates = {name for name, count in tool_name_counts.items() if count > 1}

            if duplicates:
                logging.warning(f"Found {len(duplicates)} duplicate tool names across servers: {', '.join(sorted(duplicates))}")

            # Convert to Claude format, prefixing duplicates with server name
            mcp_claude_tools = []
            for tool in mcp_tools:
                original_name = tool['name']
                server_name = tool.get('server', 'unknown')

                # If tool name is duplicated, prefix with server name
                if original_name in duplicates:
                    prefixed_name = f"{server_name}__{original_name}"
                    logging.info(f"Renaming duplicate tool '{original_name}' from server '{server_name}' to '{prefixed_name}'")
                    tool_name = prefixed_name
                else:
                    tool_name = original_name

                mcp_claude_tools.append({
                    'name': tool_name,
                    'description': tool['description'],
                    'input_schema': tool['input_schema'],
                    'server': server_name,  # Keep server info for tool calling
                    'original_name': original_name  # Keep original name for MCP calls
                })

            # Filter MCP tools based on enabled servers for this conversation
            if self.current_conversation_id:
                filtered_tools = []
                for tool in mcp_claude_tools:
                    server_name = tool['server']
                    if self.database.is_mcp_server_enabled(self.current_conversation_id, server_name):
                        filtered_tools.append(tool)
                    else:
                        logging.debug(f"Excluding tool '{tool['name']}' from disabled server '{server_name}'")

                disabled_count = len(mcp_claude_tools) - len(filtered_tools)
                if disabled_count > 0:
                    logging.info(f"Filtered out {disabled_count} tools from disabled MCP servers")
                mcp_claude_tools = filtered_tools

            # Merge MCP tools with built-in tools
            all_tools.extend(mcp_claude_tools)

            self._tools_cache = all_tools
            logging.info(f"Loaded {len(all_tools)} total tools: {len(all_tools) - len(mcp_claude_tools)} built-in, {len(mcp_claude_tools)} from MCP servers ({len(duplicates)} renamed to resolve conflicts)")
            return all_tools

        except Exception as e:
            logging.error(f"Failed to get MCP tools: {e}", exc_info=True)
            # Still return built-in tools even if MCP tools fail
            self._tools_cache = all_tools
            return all_tools

    def _call_mcp_tool(self, tool_name: str, tool_input: Dict[str, Any],
                       user_prompt: str = "") -> Tuple[str, int, bool]:
        """
        Call an MCP tool or built-in tool and return the result with metrics.
        Handles prefixed tool names (server__toolname) for duplicate resolution.

        Args:
            tool_name: Name of the tool to call (may be prefixed with server name)
            tool_input: Tool input parameters
            user_prompt: The original user prompt that triggered this tool call

        Returns:
            Tuple of (result_string, execution_time_ms, is_error)
        """
        import time

        start_time = time.time()
        is_error = False

        try:
            # Check if this is a built-in tool
            is_builtin_tool = False
            original_tool_name = tool_name

            if self._tools_cache:
                for cached_tool in self._tools_cache:
                    if cached_tool['name'] == tool_name:
                        if cached_tool.get('server') == 'builtin':
                            is_builtin_tool = True
                            original_tool_name = cached_tool['original_name']
                            logging.debug(f"Identified built-in tool: {original_tool_name}")
                            break
                        elif '__' in tool_name:
                            # Prefixed MCP tool name
                            original_tool_name = cached_tool['original_name']
                            logging.debug(f"Resolved prefixed tool name '{tool_name}' to original '{original_tool_name}'")
                            break

            # Execute built-in tool
            if is_builtin_tool:
                logging.debug(f"Calling built-in tool: {original_tool_name} with input: {tool_input}")
                result = builtin.execute_builtin_tool(original_tool_name, tool_input, config=self.config)
                execution_time = int((time.time() - start_time) * 1000)

                if result.get('success'):
                    # Format result as string
                    result_data = result.get('result', {})
                    if isinstance(result_data, dict):
                        result_str = json.dumps(result_data, indent=2)
                    else:
                        result_str = str(result_data)
                    return result_str, execution_time, False
                else:
                    error_msg = result.get('error', 'Unknown error')
                    return f"Error: {error_msg}", execution_time, True

            # Execute MCP tool
            if not self.mcp_manager:
                return "Error: MCP manager not available", 0, True

            logging.debug(f"Calling MCP tool: {original_tool_name} with input: {tool_input}")

            # Check if we're in a running event loop (e.g., from FastAPI)
            try:
                running_loop = asyncio.get_running_loop()
                # We're in an async context - run in a separate thread
                logging.debug("Detected running event loop, using thread-safe approach for tool call")

                def run_tool_in_loop():
                    # Create a new event loop for this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(
                            asyncio.wait_for(
                                self.mcp_manager.call_tool(original_tool_name, tool_input),
                                timeout=30.0
                            )
                        )
                        return result
                    except asyncio.TimeoutError:
                        logging.error(f"Timeout calling MCP tool {original_tool_name} after 30 seconds")
                        return None
                    finally:
                        new_loop.close()

                # Run in thread pool to avoid event loop conflict
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_tool_in_loop)
                    result = future.result(timeout=35.0)  # Give extra time for thread overhead

                    if result is None:
                        execution_time = int((time.time() - start_time) * 1000)
                        return f"Error: Tool execution timed out after 30 seconds", execution_time, True

            except RuntimeError:
                # No running event loop - we're in sync context
                logging.debug("No running event loop detected, using standard approach for tool call")

                # Use the initialisation loop if available, otherwise create a temporary one
                if hasattr(self.mcp_manager, '_initialization_loop') and self.mcp_manager._initialization_loop:
                    loop = self.mcp_manager._initialization_loop
                    should_close_loop = False
                    logging.debug("Using stored initialisation event loop for tool call")
                else:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    should_close_loop = True
                    logging.warning("No stored event loop found, creating temporary loop")

                try:
                    result = loop.run_until_complete(
                        asyncio.wait_for(
                            self.mcp_manager.call_tool(original_tool_name, tool_input),
                            timeout=30.0  # 30 second timeout for tool execution
                        )
                    )
                except asyncio.TimeoutError:
                    logging.error(f"Timeout calling MCP tool {original_tool_name} after 30 seconds")
                    execution_time = int((time.time() - start_time) * 1000)
                    return f"Error: Tool execution timed out after 30 seconds", execution_time, True
                finally:
                    # Only close the loop if we created it temporarily
                    if should_close_loop:
                        loop.close()

            execution_time = int((time.time() - start_time) * 1000)

            if result and not result.get('isError'):
                # Extract text content from result
                content_parts = []
                for content in result.get('content', []):
                    if content.get('type') == 'text':
                        content_parts.append(content.get('text', ''))

                result_str = '\n'.join(content_parts) if content_parts else 'Tool executed successfully (no output)'
                return result_str, execution_time, False
            else:
                error_msg = "Tool execution failed"
                if result:
                    for content in result.get('content', []):
                        if content.get('type') == 'text':
                            error_msg = content.get('text', error_msg)
                return f"Error: {error_msg}", execution_time, True

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logging.error(f"Failed to call MCP tool {tool_name}: {e}")
            return f"Error calling tool: {str(e)}", execution_time, True

    def send_message(self, user_message: str) -> Optional[str]:
        """
        Send a user message and get the assistant's response.
        Handles MCP tool calls automatically.

        Args:
            user_message: User's message content

        Returns:
            Assistant's response content or None on failure
        """
        if not self.current_conversation_id:
            raise ValueError(_ERR_NO_ACTIVE_CONVERSATION)

        logging.debug(f"send_message called with: {user_message[:50]}...")

        # NEW: Prompt inspection before processing
        if self.prompt_inspector and self.prompt_inspector.enabled:
            inspection_result = self.prompt_inspector.inspect_prompt(
                prompt=user_message,
                user_guid=self.user_guid or 'unknown',
                conversation_id=self.current_conversation_id
            )

            if inspection_result.blocked:
                # Log violation and notify user
                if self.cli_interface:
                    self.cli_interface.display_prompt_violation(inspection_result)
                logging.warning(f"Prompt blocked: {inspection_result.explanation}")
                return None

            elif inspection_result.needs_confirmation:
                # Show warning and ask for confirmation
                if self.cli_interface:
                    confirmed = self.cli_interface.confirm_risky_prompt(inspection_result)
                    if not confirmed:
                        logging.info("User declined to send risky prompt")
                        return None

            # Use sanitised version if available
            if inspection_result.sanitised_prompt:
                logging.info("Using sanitised version of prompt")
                user_message = inspection_result.sanitised_prompt

        # Check if this is the first message - if so, prepend file context
        messages = self.get_conversation_history()
        is_first_message = len(messages) == 0

        if is_first_message:
            file_context = self._get_file_context()
            if file_context:
                # Prepend file context to the first user message
                user_message = f"{file_context}\n\n{user_message}"
                logging.info("Added file context to first message")

        # Add user message to conversation
        self.add_user_message(user_message)
        logging.debug("User message added to database")

        # Get available tools
        logging.debug("About to fetch MCP tools...")
        all_tools = self._get_mcp_tools()
        logging.debug(f"Got {len(all_tools)} tools")

        # Use tool selector to choose relevant tools for this conversation
        # This significantly reduces token usage by only sending relevant tools
        tools = self.tool_selector.select_tools(
            all_tools=all_tools,
            user_message=user_message,
            conversation_history=self.get_messages_for_model() if all_tools else None
        )
        logging.debug(f"Tool selector reduced {len(all_tools)} tools to {len(tools)} relevant tools")

        # Tool use loop - continue until model gives a final answer
        # Set flag to defer rollup during tool use sequences (prevents splitting tool_use/tool_result pairs)
        self._in_tool_use_loop = True
        iteration = 0
        tool_call_history = []  # Track tool calls to detect loops

        while iteration < self.max_tool_iterations:
            iteration += 1
            logging.debug(f"Tool use iteration {iteration}/{self.max_tool_iterations}")

            # Get conversation history for the model
            messages = self.get_messages_for_model()
            logging.debug(f"Sending {len(messages)} messages to model (tools: {len(tools) if tools else 0})")

            # Filter tools to only include Claude API fields (remove internal metadata)
            filtered_tools = None
            if tools:
                filtered_tools = [
                    {
                        'name': tool['name'],
                        'description': tool['description'],
                        'input_schema': tool['input_schema']
                    }
                    for tool in tools
                ]

            # Token Management: Check limits before making API call
            if self.token_manager:
                # Estimate input tokens
                input_token_estimate = self.bedrock_service.count_message_tokens(messages)

                # Check limits
                model_id = self.bedrock_service.current_model_id
                region = self.bedrock_service.bedrock_runtime_client.meta.region_name

                allowed, warning_message, limit_status = self.token_manager.check_limits_before_request(
                    model_id, region, input_token_estimate, self.max_tokens
                )

                # Display warnings based on limit status
                if warning_message and self.cli_interface:
                    if limit_status == LimitStatus.WARNING_75:
                        self.cli_interface.print_budget_warning(warning_message, "75")
                    elif limit_status == LimitStatus.WARNING_85:
                        self.cli_interface.print_budget_warning(warning_message, "85")
                    elif limit_status == LimitStatus.WARNING_95:
                        self.cli_interface.print_budget_warning(warning_message, "95")

                # Handle limit exceeded
                if not allowed:
                    if self.cli_interface:
                        self.cli_interface.print_separator("─")
                        self.cli_interface.print_error("Token Limit Reached")
                        self.cli_interface.print_error(warning_message)
                        self.cli_interface.print_separator("─")

                        # Offer override if allowed
                        if self.token_manager.allow_override:
                            override_accepted, additional_percentage = self.cli_interface.prompt_budget_override()

                            if override_accepted:
                                # Apply override
                                self.token_manager.apply_override(additional_percentage)
                                new_input_limit = self.token_manager.max_input_tokens + self.token_manager.current_input_override
                                new_output_limit = self.token_manager.max_output_tokens + self.token_manager.current_output_override
                                self.cli_interface.print_success(
                                    f"Token limit override applied: +{additional_percentage}% "
                                    f"(new limits: {new_input_limit:,} input, {new_output_limit:,} output tokens)"
                                )
                                # Continue with request
                            else:
                                # User declined override
                                self.cli_interface.print_info("Request cancelled due to token limit")
                                self._in_tool_use_loop = False
                                self._check_and_perform_rollup()
                                return "I apologise, but the token limit has been reached and I cannot process this request at this time. Please wait for the limit to reset or contact your administrator to increase the limit."
                        else:
                            # No override allowed
                            self.cli_interface.print_info("Request cancelled due to token limit (no override allowed)")
                            self._in_tool_use_loop = False
                            self._check_and_perform_rollup()
                            return "I apologise, but the token limit has been reached and I cannot process this request at this time. Please wait for the limit to reset."
                    else:
                        # No CLI interface, just log and return
                        logging.warning("Budget limit reached, request blocked")
                        self._in_tool_use_loop = False
                        self._check_and_perform_rollup()
                        return "Budget limit reached."

            # Invoke the model with tools and combined instructions (global + conversation-specific)
            response = self.bedrock_service.invoke_model(
                messages,
                max_tokens=self.max_tokens,
                tools=filtered_tools,
                system=self._get_combined_instructions()
            )

            if not response or response.get('error'):
                # Handle error response
                if response and response.get('error'):
                    error_code = response.get('error_code', 'Unknown')
                    error_message = response.get('error_message', 'No details available')
                    error_type = response.get('error_type', 'Unknown')
                    retries_attempted = response.get('retries_attempted', 0)

                    logging.error(f"Model invocation failed - Type: {error_type}, Code: {error_code}, Message: {error_message}")
                    if retries_attempted > 0:
                        logging.error(f"Failed after {retries_attempted} retry attempt(s)")

                    if self.cli_interface:
                        self.cli_interface.print_separator("─")
                        self.cli_interface.print_error(f"✗ Failed to get response from the model")
                        if retries_attempted > 0:
                            self.cli_interface.print_error(f"(Failed after {retries_attempted} retry attempt(s))")
                        self.cli_interface.print_error(f"Error Code: {error_code}")
                        self.cli_interface.print_error(f"Error Message: {error_message}")

                        # Provide helpful suggestions based on error type
                        if 'ThrottlingException' in error_code or 'TooManyRequestsException' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: You're hitting rate limits. Wait a moment and try again.")
                        elif 'ModelTimeoutException' in error_code or 'timeout' in error_message.lower():
                            self.cli_interface.print_info("💡 Suggestion: The request timed out. Try simplifying your request or reducing conversation history.")
                        elif 'ValidationException' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: There's an issue with the request format. Check your message content and tool configurations.")
                        elif 'ModelNotReadyException' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: The model is not ready. Wait a moment and try again.")
                        elif 'ServiceUnavailableException' in error_code or 'InternalServerError' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: AWS Bedrock service is experiencing issues. Wait a moment and try again.")
                        elif 'AccessDeniedException' in error_code or 'UnauthorizedException' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: Check your AWS credentials and permissions for Bedrock access.")
                        elif 'ModelStreamErrorException' in error_code:
                            self.cli_interface.print_info("💡 Suggestion: There was an error in the model's response stream. Try again.")
                        else:
                            self.cli_interface.print_info("💡 Suggestion: Check the application logs for more details.")

                        self.cli_interface.print_separator("─")
                else:
                    logging.error("Failed to get response from model - no response received")
                    if self.cli_interface:
                        self.cli_interface.print_error("✗ Failed to get response from the model (no response received)")

                # Clear tool use flag even on failure
                self._in_tool_use_loop = False
                self._check_and_perform_rollup()

                return None

            # Track API token usage
            usage = response.get('usage', {})
            if usage:
                input_tokens = usage.get('input_tokens', 0)
                output_tokens = usage.get('output_tokens', 0)
                if input_tokens or output_tokens:
                    # Record usage with model_id for per-model tracking
                    model_id = self.bedrock_service.current_model_id
                    self.database.update_token_usage(
                        self.current_conversation_id,
                        input_tokens,
                        output_tokens,
                        model_id
                    )
                    logging.debug(f"API usage: {input_tokens} input tokens, {output_tokens} output tokens (model: {model_id})")

                    # Token Management: Record actual usage for token tracking
                    if self.token_manager:
                        region = self.bedrock_service.bedrock_runtime_client.meta.region_name
                        recorded_input, recorded_output = self.token_manager.record_usage(
                            conversation_id=self.current_conversation_id,
                            model_id=model_id,
                            region=region,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens
                        )
                        logging.debug(f"Token tracking: {recorded_input:,} input, {recorded_output:,} output tokens for this request")

            # Check if model wants to use tools
            content_blocks = response.get('content_blocks', [])
            stop_reason = response.get('stop_reason')
            logging.debug(f"Model response: stop_reason={stop_reason}, content_blocks={len(content_blocks)}")

            # Check for tool use
            tool_uses = [block for block in content_blocks if block.get('type') == 'tool_use']

            if tool_uses and stop_reason == 'tool_use':
                # Model wants to use tools
                logging.info(f"Model requested {len(tool_uses)} tool call(s)")

                # Store assistant's tool use message (with all content blocks)
                assistant_content_json = json.dumps(content_blocks)
                self.add_assistant_message(assistant_content_json)
                logging.debug(f"Stored assistant tool use message")

                # Display any text blocks that appear with tool calls (e.g., "Let me check that...")
                if self.cli_interface:
                    text_blocks = [block for block in content_blocks if block.get('type') == 'text']
                    for text_block in text_blocks:
                        text_content = text_block.get('text', '')
                        if text_content:
                            # Display as assistant message (not markdown since it's usually brief)
                            self.cli_interface.console.print(f"[bold cyan]Assistant:[/bold cyan] {text_content}")

                # Call each tool and collect results
                tool_results = []
                for tool_use in tool_uses:
                    tool_name = tool_use.get('name')
                    tool_input = tool_use.get('input', {})
                    tool_id = tool_use.get('id')

                    # Check tool permission
                    permission_allowed = self.database.is_tool_allowed(self.current_conversation_id, tool_name)

                    if permission_allowed is None:
                        # First-time usage - check if auto-approve is enabled
                        auto_approve = self.config.get('tool_permissions', {}).get('auto_approve', False)

                        if auto_approve:
                            # Auto-approve enabled - allow this time without storing permission
                            logging.info(f"Tool {tool_name} auto-approved (tool_permissions.auto_approve=true)")
                            permission_response = 'once'  # Allow but don't store in database
                        else:
                            # Prompt user for permission
                            logging.info(f"First-time tool usage detected: {tool_name}, prompting user for permission")

                            # Get tool description from cache if available
                            tool_description = None
                            if self._tools_cache:
                                for cached_tool in self._tools_cache:
                                    if cached_tool.get('name') == tool_name:
                                        input_schema = cached_tool.get('input_schema', {})
                                        tool_description = input_schema.get('description', cached_tool.get('description'))
                                        break

                            # Prompt user via the appropriate interface (Web takes priority over CLI)
                            if hasattr(self, 'web_interface') and self.web_interface:
                                # User is in web mode, prompt via web interface
                                permission_response = self.web_interface.prompt_tool_permission(tool_name, tool_description)
                            elif self.cli_interface:
                                # User is in CLI mode, prompt via CLI interface
                                permission_response = self.cli_interface.prompt_tool_permission(tool_name, tool_description)
                            else:
                                # No interface available, deny by default for security
                                logging.warning(f"No interface available to prompt for tool permission, denying tool: {tool_name}")
                                permission_response = 'denied'

                        if permission_response == 'once':
                            # Allow this time only, don't store permission
                            logging.info(f"Tool {tool_name} allowed for this use only")
                            permission_allowed = True
                        elif permission_response == 'allowed':
                            # Store permission and proceed
                            self.database.set_tool_permission(self.current_conversation_id, tool_name, PERMISSION_ALLOWED)
                            logging.info(f"Tool {tool_name} permission granted for all future uses")
                            permission_allowed = True
                        elif permission_response == 'denied':
                            # Store denial
                            self.database.set_tool_permission(self.current_conversation_id, tool_name, PERMISSION_DENIED)
                            logging.info(f"Tool {tool_name} permission denied")
                            permission_allowed = False
                        else:
                            # Cancelled or error - skip this tool
                            logging.info(f"Tool {tool_name} permission cancelled by user")
                            permission_allowed = False

                    # If tool is denied, skip it and add error result
                    if not permission_allowed:
                        logging.warning(f"Tool {tool_name} denied by user permission settings, skipping")
                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': tool_id,
                            'content': f"Error: Tool '{tool_name}' is not allowed. Permission was denied by user.",
                            'is_error': True
                        })
                        continue

                    # Track tool call for loop detection
                    tool_call_history.append(tool_name)
                    logging.info(f"Calling tool: {tool_name} (iteration {iteration})")

                    # Display tool call if CLI interface available
                    if self.cli_interface:
                        self.cli_interface.display_tool_call(tool_name, tool_input)

                    # Call the tool and get metrics
                    result, execution_time_ms, is_error = self._call_mcp_tool(tool_name, tool_input, user_message)

                    # Find which server this tool belongs to
                    tool_server = "unknown"
                    if self._tools_cache:
                        for cached_tool in self._tools_cache:
                            if cached_tool.get('name') == tool_name:
                                tool_server = cached_tool.get('server', 'unknown')
                                break

                    # Record MCP transaction for security monitoring
                    try:
                        self.database.record_mcp_transaction(
                            conversation_id=self.current_conversation_id,
                            user_prompt=user_message,
                            tool_name=tool_name,
                            tool_server=tool_server,
                            tool_input=json.dumps(tool_input),
                            tool_response=result,
                            is_error=is_error,
                            execution_time_ms=execution_time_ms
                        )
                    except Exception as txn_err:
                        logging.error(f"Failed to record MCP transaction: {txn_err}")

                    # Display tool result if CLI interface available
                    if self.cli_interface:
                        self.cli_interface.display_tool_result(tool_name, result, is_error)

                    # Truncate very large tool results to prevent token explosion
                    # Most models can't handle more than ~200K tokens total
                    result_tokens = self.bedrock_service.count_tokens(result)

                    if result_tokens > self.max_tool_result_tokens:
                        # Truncate the result and add a warning
                        truncated_result = result[:int(len(result) * (self.max_tool_result_tokens / result_tokens))]
                        truncated_result += f"\n\n[Result truncated: {result_tokens} tokens reduced to ~{self.max_tool_result_tokens} tokens]"
                        logging.warning(f"Tool {tool_name} result truncated from {result_tokens} to ~{self.max_tool_result_tokens} tokens")
                        result = truncated_result

                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': result
                    })

                # Add tool results as a user message
                tool_results_json = json.dumps(tool_results)
                self.add_user_message(f"{_TOOL_RESULTS_MARKER}{tool_results_json}")

                # Continue loop to get model's next response
                continue

            else:
                # Model gave a final answer (or incomplete response)
                assistant_message = self._extract_text_from_content(response.get('content', ''))

                # Check if this looks like an incomplete response (model said it would do something but didn't)
                if assistant_message and stop_reason == 'max_tokens':
                    logging.warning(f"Model response may be incomplete (stop_reason: max_tokens). "
                                   f"Response: {assistant_message[:100]}...")
                    if self.cli_interface:
                        suggested_max_tokens = self._calculate_suggested_max_tokens()
                        self.cli_interface.print_separator("─")
                        self.cli_interface.print_warning(
                            "⚠️  Model response may be incomplete (hit token limit)."
                        )
                        self.cli_interface.print_info(
                            f"Current max_tokens: {self.max_tokens:,}"
                        )
                        self.cli_interface.print_info(
                            f"💡 Suggested max_tokens: {suggested_max_tokens:,}"
                        )

                        # Prompt user if they want to increase max_tokens
                        try:
                            response = input(f"\nWould you like to increase max_tokens to {suggested_max_tokens:,} for this conversation? (y/n): ").strip().lower()
                            if response == 'y' or response == 'yes':
                                if self.update_conversation_max_tokens(suggested_max_tokens):
                                    self.cli_interface.print_success(
                                        f"✓ max_tokens increased to {suggested_max_tokens:,} for this conversation"
                                    )
                                    self.cli_interface.print_info(
                                        "This setting will be retained when you return to this conversation."
                                    )
                                else:
                                    self.cli_interface.print_error(
                                        "Failed to update max_tokens. Please try again or modify config.yaml."
                                    )
                            else:
                                self.cli_interface.print_info(
                                    "max_tokens unchanged. Consider simplifying your request or manually adjusting in config.yaml."
                                )
                        except (EOFError, KeyboardInterrupt):
                            # User cancelled or EOF
                            self.cli_interface.print_info("\nmax_tokens unchanged.")

                        self.cli_interface.print_separator("─")

                # Detect potential incomplete tool use (model says it will do something but no tool calls)
                intent_keywords = ['let me', "i'll", "i will", "now i", "now let me"]
                if assistant_message and not tool_uses and any(keyword in assistant_message.lower() for keyword in intent_keywords):
                    logging.warning(f"Model indicated intent to act but made no tool calls. "
                                   f"Response: {assistant_message[:150]}...")
                    if self.cli_interface and stop_reason != 'max_tokens':
                        self.cli_interface.print_warning(
                            "⚠️  Model indicated an action but didn't execute it. You may need to prompt again or rephrase your request."
                        )

                if assistant_message:
                    # Add assistant's final response to conversation
                    self.add_assistant_message(assistant_message)

                    # Detect if this is a synthesis/summary response that aggregates data
                    # If so, prompt user to verify calculations to catch potential errors
                    if self._detect_synthesis_response(assistant_message, tool_call_history):
                        logging.info("Synthesis response detected - suggesting verification to user")
                        if self.cli_interface:
                            self.cli_interface.print_separator("─")
                            self.cli_interface.print_warning(
                                "📊 Synthesis/Summary Detected: This response aggregates data from multiple sources. "
                                "To ensure accuracy, consider asking the assistant to verify its calculations "
                                "by comparing with the detailed source data."
                            )
                            self.cli_interface.print_info(
                                "💡 Suggested verification prompt: "
                                "\"Please verify your calculations by reviewing the detailed reports and confirming all totals are accurate.\""
                            )
                            self.cli_interface.print_separator("─")

                    # Clear tool use flag and check for deferred rollup
                    self._in_tool_use_loop = False
                    self._check_and_perform_rollup()

                    return assistant_message
                else:
                    logging.warning(f"Model returned empty response (stop_reason: {stop_reason})")

                    # Clear tool use flag even on empty response
                    self._in_tool_use_loop = False
                    self._check_and_perform_rollup()

                    return None

        # Max iterations reached
        from collections import Counter
        tool_counts = Counter(tool_call_history)
        most_common = tool_counts.most_common(3)
        tool_summary = ', '.join([f"{name}({count})" for name, count in most_common])

        logging.warning(f"Max tool iterations ({self.max_tool_iterations}) reached. "
                       f"Tools called: {tool_summary}. Total calls: {len(tool_call_history)}")

        # Clear tool use flag and check for deferred rollup
        self._in_tool_use_loop = False
        self._check_and_perform_rollup()

        return (f"I apologise, but I've reached the maximum number of tool calls ({self.max_tool_iterations}) "
                f"for this request. I called {len(tool_call_history)} tools in total. "
                f"You may need to rephrase your request or break it into smaller tasks.")

    def delete_current_conversation(self) -> bool:
        """
        Delete the current conversation.

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.warning("No conversation loaded to delete")
            return False

        success = self.database.delete_conversation(self.current_conversation_id)
        if success:
            self.current_conversation_id = None
            logging.info("Current conversation deleted")
        return success

    def attach_files(self, file_data: Union[List[str], List[Dict]]) -> bool:
        """
        Process and attach files to the current conversation.

        Args:
            file_data: List of file paths (strings) or list of dicts with 'path' and 'tags' keys

        Returns:
            True if all files attached successfully
        """
        if not self.current_conversation_id:
            logging.warning("No conversation loaded to attach files to")
            return False

        from dtSpark.files.manager import FileManager

        file_manager = FileManager(bedrock_service=self.bedrock_service)
        success_count = 0

        # Normalize input to list of dicts format
        normalized_files = []
        if file_data and isinstance(file_data[0], str):
            # Old format: list of strings
            normalized_files = [{'path': fp, 'tags': None} for fp in file_data]
        else:
            # New format: list of dicts
            normalized_files = file_data

        for file_info in normalized_files:
            file_path = file_info['path']
            tags = file_info.get('tags')

            try:
                # Process the file
                result = file_manager.process_file(file_path)

                if 'error' in result:
                    logging.error(f"Failed to process file {file_path}: {result['error']}")
                    continue

                # Add to database
                file_id = self.database.add_file(
                    conversation_id=self.current_conversation_id,
                    filename=result['filename'],
                    file_type=result['file_type'],
                    file_size=result['file_size'],
                    content_text=result.get('content_text'),
                    content_base64=result.get('content_base64'),
                    mime_type=result.get('mime_type'),
                    token_count=result['token_count'],
                    tags=tags
                )

                tags_str = f" with tags '{tags}'" if tags else ""
                logging.info(f"Attached file {result['filename']} (ID: {file_id}, {result['token_count']} tokens{tags_str})")
                success_count += 1

            except Exception as e:
                logging.error(f"Error attaching file {file_path}: {e}")
                continue

        return success_count == len(normalized_files)

    def attach_files_with_message(self, file_data: Union[List[str], List[Dict]]) -> bool:
        """
        Process and attach files to the current conversation, adding their content
        as a user message so the model can immediately access them.

        Args:
            file_data: List of file paths (strings) or list of dicts with 'path' and 'tags' keys

        Returns:
            True if all files attached successfully
        """
        if not self.current_conversation_id:
            logging.warning("No conversation loaded to attach files to")
            return False

        from dtSpark.files.manager import FileManager

        file_manager = FileManager(bedrock_service=self.bedrock_service)
        success_count = 0
        attached_file_info = []

        # Normalize input to list of dicts format
        normalized_files = []
        if file_data and isinstance(file_data[0], str):
            # Old format: list of strings
            normalized_files = [{'path': fp, 'tags': None} for fp in file_data]
        else:
            # New format: list of dicts
            normalized_files = file_data

        for file_info in normalized_files:
            file_path = file_info['path']
            tags = file_info.get('tags')

            try:
                # Process the file
                result = file_manager.process_file(file_path)

                if 'error' in result:
                    logging.error(f"Failed to process file {file_path}: {result['error']}")
                    continue

                # Add to database
                file_id = self.database.add_file(
                    conversation_id=self.current_conversation_id,
                    filename=result['filename'],
                    file_type=result['file_type'],
                    file_size=result['file_size'],
                    content_text=result.get('content_text'),
                    content_base64=result.get('content_base64'),
                    mime_type=result.get('mime_type'),
                    token_count=result['token_count'],
                    tags=tags
                )

                tags_str = f" with tags '{tags}'" if tags else ""
                logging.info(f"Attached file {result['filename']} (ID: {file_id}, {result['token_count']} tokens{tags_str})")

                # Store result with tags for message generation
                result['tags'] = tags
                attached_file_info.append(result)
                success_count += 1

            except Exception as e:
                logging.error(f"Error attaching file {file_path}: {e}")
                continue

        # If files were successfully attached, add their content as a user message
        if attached_file_info:
            context_parts = ["=== Newly Attached Files ===\n"]

            for file_info in attached_file_info:
                # Include tags in file header if present
                tags_str = f" [Tags: {file_info.get('tags')}]" if file_info.get('tags') else ""
                context_parts.append(f"File: {file_info['filename']} ({file_info['file_type']}){tags_str}")
                context_parts.append("")

                # Add text content if available
                if file_info.get('content_text'):
                    context_parts.append(file_info['content_text'])
                    context_parts.append("")

                # For images, just note that they're attached
                elif file_info.get('content_base64'):
                    context_parts.append(f"[Image file: {file_info.get('mime_type')}]")
                    context_parts.append("")

                context_parts.append("---")
                context_parts.append("")

            context_parts.append("The above files have been attached to this conversation for reference.")

            # Add as user message
            file_context_message = '\n'.join(context_parts)
            self.add_user_message(file_context_message)
            logging.info(f"Added file context message for {len(attached_file_info)} newly attached files")

        return success_count == len(normalized_files)

    def get_attached_files(self) -> List[Dict]:
        """
        Get all files attached to the current conversation.

        Returns:
            List of file dictionaries
        """
        if not self.current_conversation_id:
            return []

        return self.database.get_conversation_files(self.current_conversation_id)

    def get_files_by_tag(self, tag: str) -> List[Dict]:
        """
        Get files attached to the current conversation filtered by tag.

        Args:
            tag: Tag to filter by (case-insensitive)

        Returns:
            List of file dictionaries with matching tag
        """
        if not self.current_conversation_id:
            return []

        return self.database.get_files_by_tag(self.current_conversation_id, tag)

    def _get_file_context(self) -> str:
        """
        Build context string from attached files.

        Returns:
            Formatted string with file contents
        """
        files = self.get_attached_files()
        if not files:
            return ""

        context_parts = ["=== Attached Files ===\n"]

        for file_info in files:
            context_parts.append(f"File: {file_info['filename']} ({file_info['file_type']})")
            context_parts.append("")

            # Add text content if available
            if file_info.get('content_text'):
                context_parts.append(file_info['content_text'])
                context_parts.append("")

            # For images, just note that they're attached
            elif file_info.get('content_base64'):
                context_parts.append(f"[Image file: {file_info['mime_type']}]")
                context_parts.append("")

            context_parts.append("---")
            context_parts.append("")

        return '\n'.join(context_parts)

    def export_conversation(self, file_path: str, format: str = 'markdown', include_tools: bool = True) -> bool:
        """
        Export the current conversation to a file in specified format.

        Args:
            file_path: Path to save the file
            format: Export format ('markdown', 'html', 'csv')
            include_tools: Whether to include tool use details

        Returns:
            True if successful, False otherwise
        """
        if format == 'markdown':
            return self._export_to_markdown(file_path, include_tools)
        elif format == 'html':
            return self._export_to_html(file_path, include_tools)
        elif format == 'csv':
            return self._export_to_csv(file_path, include_tools)
        else:
            logging.error(f"Unsupported export format: {format}")
            return False

    def export_conversation_to_markdown(self, file_path: str) -> bool:
        """
        Export the current conversation to a markdown file (legacy method).

        Args:
            file_path: Path to save the markdown file

        Returns:
            True if successful, False otherwise
        """
        return self._export_to_markdown(file_path, include_tools=True)

    def export_to_markdown(self, include_tool_details: bool = True) -> str:
        """
        Export the current conversation to markdown format and return as string.

        This method is designed for web API use where content is returned rather
        than written to a file.

        Args:
            include_tool_details: Whether to include tool use details

        Returns:
            Markdown-formatted string of the conversation
        """
        return self._generate_markdown_content(include_tool_details)

    def export_to_html(self, include_tool_details: bool = True) -> str:
        """
        Export the current conversation to HTML format and return as string.

        This method is designed for web API use where content is returned rather
        than written to a file.

        Args:
            include_tool_details: Whether to include tool use details

        Returns:
            HTML-formatted string of the conversation
        """
        return self._generate_html_content(include_tool_details)

    def export_to_csv(self, include_tool_details: bool = True) -> str:
        """
        Export the current conversation to CSV format and return as string.

        This method is designed for web API use where content is returned rather
        than written to a file.

        Args:
            include_tool_details: Whether to include tool use details

        Returns:
            CSV-formatted string of the conversation
        """
        return self._generate_csv_content(include_tool_details)

    def _generate_markdown_content(self, include_tools: bool = True) -> str:
        """
        Generate markdown-formatted content for the current conversation.

        Args:
            include_tools: Whether to include tool use details

        Returns:
            Markdown-formatted string of the conversation
        """
        if not self.current_conversation_id:
            logging.warning(_ERR_NO_CONVERSATION_TO_EXPORT)
            return ""

        # Get conversation info
        conv_info = self.get_current_conversation_info()
        if not conv_info:
            return ""

        # Get messages (including rolled-up messages for complete history)
        messages = self.get_conversation_history(include_rolled_up=True)

        # Build markdown content
        md_lines = []

        # Header
        md_lines.append(f"# {conv_info['name']}")
        md_lines.append("")
        md_lines.append(f"**Model:** {conv_info['model_id']}")
        md_lines.append(f"**Created:** {conv_info['created_at']}")
        md_lines.append(f"**Last Updated:** {conv_info['last_updated']}")
        md_lines.append(f"**Total Tokens:** {conv_info['total_tokens']:,}")
        md_lines.append("")

        # Include instructions if they exist
        if conv_info.get('instructions'):
            md_lines.append("## Instructions")
            md_lines.append("")
            md_lines.append(conv_info['instructions'])
            md_lines.append("")

        # Include attached files if they exist
        attached_files = self.get_attached_files()
        if attached_files:
            md_lines.append("## Attached Files")
            md_lines.append("")
            for file_info in attached_files:
                size_kb = file_info['file_size'] / 1024
                md_lines.append(f"- **{file_info['filename']}** ({file_info['file_type']}, {size_kb:.1f} KB, {file_info['token_count']} tokens)")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("")

        # Messages
        for msg in messages:
            timestamp = datetime.fromisoformat(msg['timestamp'])
            role = msg['role'].capitalize()
            content = msg['content']

            # Detect special message types
            is_rollup_summary = content.startswith(_SUMMARY_MARKER)
            is_tool_result = content.startswith(_TOOL_RESULTS_MARKER)

            # Check if this is a tool call message (assistant with tool_use blocks)
            is_tool_call = False
            if role.lower() == 'assistant':
                try:
                    content_blocks = json.loads(content)
                    if isinstance(content_blocks, list) and any(block.get('type') == 'tool_use' for block in content_blocks):
                        is_tool_call = True
                except ValueError:
                    pass

            # Format role header based on message type
            if is_rollup_summary:
                md_lines.append(f"## 📋 Rollup Summary")
            elif is_tool_result:
                md_lines.append(f"## 🔧 Tool Results")
            elif is_tool_call:
                md_lines.append(f"## 🤖 Assistant (with Tool Calls)")
            elif role.lower() == 'user':
                md_lines.append(f"## 👤 {role}")
            elif role.lower() == 'assistant':
                md_lines.append(f"## 🤖 {role}")
            else:
                md_lines.append(f"## {role}")

            md_lines.append(f"*{timestamp.strftime('%Y-%m-%d %H:%M:%S')}*")
            md_lines.append("")

            # Clean up content if it's tool-related
            if content.startswith(_TOOL_RESULTS_MARKER) and include_tools:
                # Parse and format tool results
                try:
                    tool_results_json = content.replace(_TOOL_RESULTS_MARKER, '', 1)
                    tool_results = json.loads(tool_results_json)
                    md_lines.append("**Tool Results:**")
                    md_lines.append("")
                    for result in tool_results:
                        md_lines.append(f"- Tool: `{result.get('tool_use_id', 'unknown')}`")
                        md_lines.append(f"  Result: {result.get('content', '')}")
                    md_lines.append("")
                except ValueError:
                    md_lines.append(content)
                    md_lines.append("")
            elif content.startswith(_TOOL_RESULTS_MARKER) and not include_tools:
                # Skip tool results if not including tools
                md_lines.append("*[Tool execution details omitted]*")
                md_lines.append("")
            elif content.startswith('['):
                # Try to parse as JSON (tool use blocks)
                try:
                    content_blocks = json.loads(content)
                    for block in content_blocks:
                        if block.get('type') == 'text':
                            md_lines.append(block.get('text', ''))
                            md_lines.append("")
                        elif block.get('type') == 'tool_use' and include_tools:
                            md_lines.append(f"**Tool Call:** `{block.get('name')}`")
                            md_lines.append(f"**Input:** {json.dumps(block.get('input', {}), indent=2)}")
                            md_lines.append("")
                except ValueError:
                    md_lines.append(content)
                    md_lines.append("")
            else:
                md_lines.append(content)
                md_lines.append("")

            md_lines.append("---")
            md_lines.append("")

        # Return the joined content
        return '\n'.join(md_lines)

    def _export_to_markdown(self, file_path: str, include_tools: bool = True) -> bool:
        """
        Export the current conversation to a markdown file.

        Args:
            file_path: Path to save the markdown file
            include_tools: Whether to include tool use details

        Returns:
            True if successful, False otherwise
        """
        try:
            content = self._generate_markdown_content(include_tools)
            if not content:
                return False

            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            logging.info(f"Exported conversation to {file_path}")
            return True

        except Exception as e:
            logging.error(f"Failed to export conversation: {e}")
            return False

    def _generate_html_content(self, include_tools: bool = True) -> str:
        """
        Generate HTML-formatted content for the current conversation.

        Args:
            include_tools: Whether to include tool use details

        Returns:
            HTML-formatted string of the conversation
        """
        import tempfile
        import os

        # Use temporary file approach to reuse existing export logic
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as tmp:
                tmp_path = tmp.name

            # Export to temporary file
            success = self._export_to_html(tmp_path, include_tools)
            if not success:
                return ""

            # Read content back
            with open(tmp_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Clean up temporary file
            os.unlink(tmp_path)

            return content

        except Exception as e:
            logging.error(f"Failed to generate HTML content: {e}")
            return ""

    def _generate_csv_content(self, include_tools: bool = True) -> str:
        """
        Generate CSV-formatted content for the current conversation.

        Args:
            include_tools: Whether to include tool use details

        Returns:
            CSV-formatted string of the conversation
        """
        import tempfile
        import os

        # Use temporary file approach to reuse existing export logic
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp:
                tmp_path = tmp.name

            # Export to temporary file
            success = self._export_to_csv(tmp_path, include_tools)
            if not success:
                return ""

            # Read content back
            with open(tmp_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Clean up temporary file
            os.unlink(tmp_path)

            return content

        except Exception as e:
            logging.error(f"Failed to generate CSV content: {e}")
            return ""

    def _export_to_html(self, file_path: str, include_tools: bool = True) -> bool:
        """
        Export the current conversation to an HTML file with chat styling.

        Args:
            file_path: Path to save the HTML file
            include_tools: Whether to include tool use details

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.warning(_ERR_NO_CONVERSATION_TO_EXPORT)
            return False

        try:
            # Get conversation info
            conv_info = self.get_current_conversation_info()
            if not conv_info:
                return False

            # Get messages (including rolled-up messages for complete history)
            messages = self.get_conversation_history(include_rolled_up=True)

            # Build HTML content
            html_parts = []

            # HTML header with styling
            html_parts.append('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>''' + conv_info['name'] + '''</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            line-height: 1.6;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .header .metadata {
            font-size: 14px;
            opacity: 0.9;
        }
        .chat-container {
            padding: 20px;
            max-height: 80vh;
            overflow-y: auto;
        }
        .message {
            margin-bottom: 20px;
            animation: fadeIn 0.3s ease-in;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message-user {
            display: flex;
            justify-content: flex-end;
        }
        .message-assistant {
            display: flex;
            justify-content: flex-start;
        }
        .message-bubble {
            max-width: 70%;
            padding: 15px 20px;
            border-radius: 18px;
            position: relative;
        }
        .message-user .message-bubble {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .message-assistant .message-bubble {
            background: #f0f0f0;
            color: #333;
        }
        .message-tool-result {
            display: flex;
            justify-content: center;
        }
        .message-tool-result .message-bubble {
            background: #fff9e6;
            color: #333;
            border: 1px solid #ffc107;
            max-width: 85%;
        }
        .message-rollup {
            display: flex;
            justify-content: center;
        }
        .message-rollup .message-bubble {
            background: #e8f5e9;
            color: #333;
            border: 1px solid #4caf50;
            max-width: 85%;
            font-style: italic;
        }
        .message-tool-call {
            display: flex;
            justify-content: flex-start;
        }
        .message-tool-call .message-bubble {
            background: #e3f2fd;
            color: #333;
            border: 1px solid #2196f3;
        }
        .message-role {
            font-weight: bold;
            font-size: 12px;
            margin-bottom: 5px;
            opacity: 0.8;
        }
        .message-timestamp {
            font-size: 11px;
            opacity: 0.6;
            margin-top: 5px;
        }
        .message-content {
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .tool-section {
            background: transparent;
            border-left: none;
            padding: 0;
            margin-top: 0;
            border-radius: 0;
            font-size: 13px;
        }
        .tool-section .tool-title {
            font-weight: bold;
            margin-bottom: 10px;
            color: #f57c00;
        }
        .tool-call {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 10px;
            margin-top: 10px;
            border-radius: 4px;
            font-size: 13px;
        }
        .tool-title {
            font-weight: bold;
            margin-bottom: 5px;
        }
        code {
            background: rgba(0,0,0,0.05);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }
        pre {
            background: rgba(0,0,0,0.05);
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 10px 0;
        }
        .info-section {
            background: #f8f9fa;
            padding: 20px;
            border-top: 1px solid #dee2e6;
        }
        .info-section h3 {
            margin-bottom: 10px;
            color: #667eea;
        }
        .info-section ul {
            list-style: none;
        }
        .info-section li {
            padding: 5px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>''' + conv_info['name'] + '''</h1>
            <div class="metadata">
                <div>Model: ''' + conv_info['model_id'] + '''</div>
                <div>Created: ''' + conv_info['created_at'] + '''</div>
                <div>Total Tokens: ''' + f"{conv_info['total_tokens']:,}" + '''</div>
            </div>
        </div>
''')

            # Instructions section if exists
            if conv_info.get('instructions'):
                html_parts.append('''
        <div class="info-section">
            <h3>Instructions</h3>
            <p>''' + conv_info['instructions'].replace('\n', '<br>') + '''</p>
        </div>
''')

            # Attached files if exist
            attached_files = self.get_attached_files()
            if attached_files:
                html_parts.append('''
        <div class="info-section">
            <h3>Attached Files</h3>
            <ul>
''')
                for file_info in attached_files:
                    size_kb = file_info['file_size'] / 1024
                    html_parts.append(f'''                <li><strong>{file_info['filename']}</strong> ({file_info['file_type']}, {size_kb:.1f} KB, {file_info['token_count']} tokens)</li>
''')
                html_parts.append('''            </ul>
        </div>
''')

            # Chat messages
            html_parts.append('''
        <div class="chat-container">
''')

            for msg in messages:
                timestamp = datetime.fromisoformat(msg['timestamp'])
                role = msg['role'].capitalize()
                content = msg['content']

                # Detect special message types
                is_rollup_summary = content.startswith(_SUMMARY_MARKER)
                is_tool_result = content.startswith(_TOOL_RESULTS_MARKER)

                # Check if this is a tool call message (assistant with tool_use blocks)
                is_tool_call = False
                if role.lower() == 'assistant' and not is_tool_result:
                    try:
                        content_blocks = json.loads(content)
                        if isinstance(content_blocks, list) and any(block.get('type') == 'tool_use' for block in content_blocks):
                            is_tool_call = True
                    except ValueError:
                        pass

                # Assign message class and labels based on type
                if is_rollup_summary:
                    message_class = "message-rollup"
                    role_icon = "📋"
                    role_label = "Rollup Summary"
                elif is_tool_result:
                    message_class = "message-tool-result"
                    role_icon = "🔧"
                    role_label = "Tool Results"
                elif is_tool_call:
                    message_class = "message-tool-call"
                    role_icon = "🛠️"
                    role_label = "Assistant (Tool Calls)"
                else:
                    message_class = f"message-{msg['role']}"
                    role_icon = '👤 ' if role == 'User' else '🤖 '
                    role_label = role

                html_parts.append(f'''
            <div class="message {message_class}">
                <div class="message-bubble">
                    <div class="message-role">{role_icon}{role_label}</div>
                    <div class="message-timestamp">{timestamp.strftime('%Y-%m-%d %H:%M:%S')}</div>
                    <div class="message-content">
''')

                # Process content
                if content.startswith(_TOOL_RESULTS_MARKER) and include_tools:
                    try:
                        tool_results_json = content.replace(_TOOL_RESULTS_MARKER, '', 1)
                        tool_results = json.loads(tool_results_json)
                        html_parts.append('''                        <div class="tool-section">
                            <div class="tool-title">🔧 Tool Results:</div>
''')
                        for idx, result in enumerate(tool_results, 1):
                            result_content = result.get('content', '')
                            # Truncate very long results for display
                            if len(result_content) > 500:
                                result_content = result_content[:500] + '... [truncated]'
                            html_parts.append(f'''                            <div style="margin-bottom: 15px; padding: 10px; background: rgba(255,255,255,0.5); border-radius: 4px;">
                                <div style="font-weight: bold; color: #f57c00; margin-bottom: 5px;">Result {idx}</div>
                                <div style="font-size: 12px; color: #666; margin-bottom: 5px;">Tool ID: <code style="background: rgba(0,0,0,0.05); padding: 2px 4px; border-radius: 2px;">{result.get('tool_use_id', 'unknown')}</code></div>
                                <div style="white-space: pre-wrap; word-wrap: break-word;">{result_content.replace('<', '&lt;').replace('>', '&gt;')}</div>
                            </div>
''')
                        html_parts.append('''                        </div>
''')
                    except ValueError:
                        html_parts.append(f'''                        {content.replace('<', '&lt;').replace('>', '&gt;')}
''')
                elif content.startswith(_TOOL_RESULTS_MARKER) and not include_tools:
                    html_parts.append('''                        <em>[Tool execution details omitted]</em>
''')
                elif content.startswith('['):
                    try:
                        content_blocks = json.loads(content)
                        for block in content_blocks:
                            if block.get('type') == 'text':
                                html_parts.append(f'''                        {block.get('text', '').replace('<', '&lt;').replace('>', '&gt;')}
''')
                            elif block.get('type') == 'tool_use' and include_tools:
                                html_parts.append(f'''                        <div class="tool-call">
                            <div class="tool-title">Tool Call: <code>{block.get('name')}</code></div>
                            <pre>{json.dumps(block.get('input', {}), indent=2)}</pre>
                        </div>
''')
                    except ValueError:
                        html_parts.append(f'''                        {content.replace('<', '&lt;').replace('>', '&gt;')}
''')
                else:
                    escaped_content = content.replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
                    html_parts.append(f'''                        {escaped_content}
''')

                html_parts.append('''                    </div>
                </div>
            </div>
''')

            html_parts.append('''
        </div>
    </div>
</body>
</html>
''')

            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(''.join(html_parts))

            logging.info(f"Exported conversation to HTML: {file_path}")
            return True

        except Exception as e:
            logging.error(f"Failed to export conversation to HTML: {e}")
            return False

    def _export_to_csv(self, file_path: str, include_tools: bool = True) -> bool:
        """
        Export the current conversation to a CSV file.

        Args:
            file_path: Path to save the CSV file
            include_tools: Whether to include tool use details

        Returns:
            True if successful, False otherwise
        """
        if not self.current_conversation_id:
            logging.warning(_ERR_NO_CONVERSATION_TO_EXPORT)
            return False

        try:
            import csv

            # Get conversation info
            conv_info = self.get_current_conversation_info()
            if not conv_info:
                return False

            # Get messages (including rolled-up messages for complete history)
            messages = self.get_conversation_history(include_rolled_up=True)

            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Timestamp', 'Type', 'Role', 'Content', _LABEL_TOKEN_COUNT]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                # Write header
                writer.writeheader()

                # Write metadata as comments
                writer.writerow({
                    'Timestamp': 'METADATA',
                    'Type': '',
                    'Role': 'Conversation',
                    'Content': conv_info['name'],
                    _LABEL_TOKEN_COUNT: ''
                })
                writer.writerow({
                    'Timestamp': 'METADATA',
                    'Type': '',
                    'Role': 'Model',
                    'Content': conv_info['model_id'],
                    _LABEL_TOKEN_COUNT: ''
                })
                writer.writerow({
                    'Timestamp': 'METADATA',
                    'Type': '',
                    'Role': 'Total Tokens',
                    'Content': str(conv_info['total_tokens']),
                    _LABEL_TOKEN_COUNT: ''
                })

                # Write messages
                for msg in messages:
                    timestamp = datetime.fromisoformat(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    role = msg['role'].capitalize()
                    content = msg['content']

                    # Detect special message types
                    is_rollup_summary = content.startswith(_SUMMARY_MARKER)
                    is_tool_result = content.startswith(_TOOL_RESULTS_MARKER)

                    # Check if this is a tool call message
                    is_tool_call = False
                    if role.lower() == 'assistant' and not is_tool_result:
                        try:
                            content_blocks = json.loads(content)
                            if isinstance(content_blocks, list) and any(block.get('type') == 'tool_use' for block in content_blocks):
                                is_tool_call = True
                        except ValueError:
                            pass

                    # Assign type label
                    if is_rollup_summary:
                        msg_type = 'Rollup Summary'
                    elif is_tool_result:
                        msg_type = 'Tool Results'
                    elif is_tool_call:
                        msg_type = 'Tool Call'
                    else:
                        msg_type = 'Message'

                    # Process tool-related content
                    if content.startswith(_TOOL_RESULTS_MARKER):
                        if include_tools:
                            try:
                                tool_results_json = content.replace(_TOOL_RESULTS_MARKER, '', 1)
                                tool_results = json.loads(tool_results_json)
                                content = f"Tool Results: {json.dumps(tool_results, indent=2)}"
                            except ValueError:
                                pass
                        else:
                            content = "[Tool execution details omitted]"
                    elif content.startswith('['):
                        try:
                            content_blocks = json.loads(content)
                            text_parts = []
                            for block in content_blocks:
                                if block.get('type') == 'text':
                                    text_parts.append(block.get('text', ''))
                                elif block.get('type') == 'tool_use' and include_tools:
                                    text_parts.append(f"Tool Call: {block.get('name')} - Input: {json.dumps(block.get('input', {}))}")
                            content = '\n'.join(text_parts) if text_parts else content
                        except ValueError:
                            pass

                    writer.writerow({
                        'Timestamp': timestamp,
                        'Type': msg_type,
                        'Role': role,
                        'Content': content,
                        _LABEL_TOKEN_COUNT: msg.get('token_count', '')
                    })

            logging.info(f"Exported conversation to CSV: {file_path}")
            return True

        except Exception as e:
            logging.error(f"Failed to export conversation to CSV: {e}")
            return False
