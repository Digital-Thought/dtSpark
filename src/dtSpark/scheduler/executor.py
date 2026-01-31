"""
Action Executor module.

Handles LLM invocation and result handling for autonomous actions.


"""

import logging
import json
import time
import asyncio
import concurrent.futures
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, Tuple
import markdown


# Compaction prompt template for action context compaction
ACTION_COMPACTION_PROMPT = '''You are compacting the context for an ongoing autonomous action. Distill the conversation history into a compressed format that preserves critical information.

## RULES
- PRESERVE: Tool results, findings, errors, partial work, next steps
- COMPRESS: Completed tasks to brief outcomes, verbose tool outputs to key data
- DISCARD: Redundant results, superseded plans, verbose confirmations

## OUTPUT FORMAT
# COMPACTED ACTION CONTEXT

## Completed Work
[Brief list of what has been accomplished]

## Key Findings/Data
[Important results, numbers, file paths discovered]

## Current State
[What was being worked on when compaction occurred]

## Pending Tasks
[What still needs to be done based on original prompt]

## Original Task
{original_prompt}

## CONVERSATION TO COMPACT ({message_count} messages, ~{token_count:,} tokens)

{conversation_history}

Begin compacted context now:'''


class ActionContextCompactor:
    """
    Lightweight context compactor for autonomous actions.

    Works with in-memory message lists rather than database storage.
    Compacts when token usage exceeds threshold to allow long-running actions.
    """

    def __init__(self, llm_manager, compaction_threshold: float = 0.6,
                 emergency_threshold: float = 0.85):
        """
        Initialise the action context compactor.

        Args:
            llm_manager: LLMManager instance for LLM invocation and token counting
            compaction_threshold: Fraction of context to trigger compaction (default 0.6)
            emergency_threshold: Fraction for emergency compaction (default 0.85)
        """
        self.llm_manager = llm_manager
        self.compaction_threshold = compaction_threshold
        self.emergency_threshold = emergency_threshold
        logging.info(f"ActionContextCompactor initialised with threshold={compaction_threshold}")

    def check_and_compact(self, messages: List[Dict], original_prompt: str,
                          context_window: int, in_tool_loop: bool = True) -> Tuple[List[Dict], bool]:
        """
        Check if compaction is needed and perform it.

        Args:
            messages: Current message list
            original_prompt: The original action prompt (preserved)
            context_window: Model's context window size
            in_tool_loop: Whether currently in tool use loop

        Returns:
            Tuple of (possibly compacted messages, whether compaction occurred)
        """
        # Estimate current token usage
        current_tokens = self._estimate_tokens(messages)

        # Calculate thresholds
        normal_threshold = int(context_window * self.compaction_threshold)
        emergency_threshold = int(context_window * self.emergency_threshold)

        logging.debug(f"Action compaction check: {current_tokens:,}/{context_window:,} tokens "
                     f"(threshold: {normal_threshold:,}, emergency: {emergency_threshold:,})")

        # Emergency compaction - always perform
        if current_tokens >= emergency_threshold:
            logging.warning(f"EMERGENCY action compaction: {current_tokens:,}/{context_window:,} tokens")
            return self._perform_compaction(messages, original_prompt, current_tokens), True

        # Normal threshold - defer during tool loop unless close to emergency
        if current_tokens >= normal_threshold:
            if in_tool_loop and current_tokens < emergency_threshold * 0.9:
                logging.debug("Deferring action compaction during tool loop")
                return messages, False
            logging.info(f"Action compaction triggered: {current_tokens:,} tokens")
            return self._perform_compaction(messages, original_prompt, current_tokens), True

        return messages, False

    def _estimate_tokens(self, messages: List[Dict]) -> int:
        """
        Estimate token count for messages.

        Args:
            messages: Message list

        Returns:
            Estimated token count
        """
        total = 0
        for msg in messages:
            total += self._estimate_message_tokens(msg)
        return total

    def _estimate_message_tokens(self, msg: Dict) -> int:
        """
        Estimate token count for a single message.

        Args:
            msg: Message dictionary

        Returns:
            Estimated token count
        """
        content = msg.get('content', '')
        if isinstance(content, str):
            # Rough estimate: ~4 chars per token
            return len(content) // 4
        if isinstance(content, list):
            return self._estimate_content_blocks_tokens(content)
        return 0

    def _estimate_content_blocks_tokens(self, blocks: list) -> int:
        """
        Estimate token count for a list of content blocks.

        Args:
            blocks: List of content block dictionaries

        Returns:
            Estimated token count
        """
        total = 0
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get('type')
            if block_type == 'text':
                total += len(block.get('text', '')) // 4
            elif block_type == 'tool_use':
                total += len(json.dumps(block.get('input', {}))) // 4
            elif block_type == 'tool_result':
                total += len(str(block.get('content', ''))) // 4
        return total

    def _check_rate_limits(self, prompt: str) -> Dict[str, Any]:
        """
        Check if the compaction request would exceed provider rate limits.

        Args:
            prompt: The compaction prompt to be sent

        Returns:
            Dictionary with:
            - can_proceed: bool - Whether compaction can proceed
            - message: str - Explanation message
        """
        # Get rate limits from the LLM manager
        if not hasattr(self.llm_manager, 'get_rate_limits'):
            return {'can_proceed': True, 'message': 'No rate limit info available'}

        rate_limits = self.llm_manager.get_rate_limits()

        # If provider doesn't have rate limits, proceed
        if not rate_limits or not rate_limits.get('has_limits', False):
            return {'can_proceed': True, 'message': 'No rate limits'}

        # Estimate tokens for the prompt
        if hasattr(self.llm_manager, 'count_tokens'):
            try:
                estimated_tokens = self.llm_manager.count_tokens(prompt)
            except Exception:
                estimated_tokens = len(prompt) // 4
        else:
            estimated_tokens = len(prompt) // 4

        # Check against input token limit
        input_limit = rate_limits.get('input_tokens_per_minute')
        if input_limit and estimated_tokens > input_limit:
            provider_name = "the current provider"
            if hasattr(self.llm_manager, 'get_active_provider'):
                provider_name = self.llm_manager.get_active_provider() or provider_name

            return {
                'can_proceed': False,
                'message': (
                    f"Request ({estimated_tokens:,} tokens) exceeds {provider_name} "
                    f"rate limit ({input_limit:,} tokens/minute)"
                ),
                'estimated_tokens': estimated_tokens,
                'rate_limit': input_limit
            }

        return {'can_proceed': True, 'message': 'Within rate limits'}

    def _perform_compaction(self, messages: List[Dict], original_prompt: str,
                            current_tokens: int) -> List[Dict]:
        """
        Perform the actual compaction.

        Args:
            messages: Messages to compact
            original_prompt: Original action prompt
            current_tokens: Current estimated token count

        Returns:
            Compacted message list
        """
        if len(messages) <= 2:
            logging.warning("Not enough messages to compact")
            return messages

        try:
            # Format messages for compaction
            formatted = self._format_messages(messages)

            # Build compaction prompt
            prompt = ACTION_COMPACTION_PROMPT.format(
                original_prompt=original_prompt,
                message_count=len(messages),
                token_count=current_tokens,
                conversation_history=formatted
            )

            # Check rate limits before attempting compaction
            rate_limit_check = self._check_rate_limits(prompt)
            if not rate_limit_check['can_proceed']:
                logging.warning(f"Action compaction blocked by rate limits: {rate_limit_check['message']}")
                return messages

            # Invoke LLM for compaction (low temperature for consistency)
            response = self.llm_manager.invoke_model(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=4096,
                temperature=0.2
            )

            if not response or response.get('error'):
                logging.error("Compaction failed - keeping original messages")
                return messages

            # Extract compacted content
            compacted_content = response.get('content', '')
            if isinstance(compacted_content, list):
                text_parts = [b.get('text', '') for b in compacted_content if b.get('type') == 'text']
                compacted_content = '\n'.join(text_parts)

            if len(compacted_content) < 100:
                logging.warning("Compacted content too brief, keeping original")
                return messages

            # Create new message list with compacted context
            compacted_tokens = len(compacted_content) // 4
            reduction = ((current_tokens - compacted_tokens) / current_tokens * 100) if current_tokens > 0 else 0

            reduction_str = f"{reduction:.1f}% reduction"
            logging.info(f"Action compaction: {len(messages)} messages → 1 summary, "
                        f"{current_tokens:,} → {compacted_tokens:,} tokens ({reduction_str})")

            # Return compacted context as single user message
            return [{
                'role': 'user',
                'content': f"[COMPACTED CONTEXT - {len(messages)} messages compacted]\n\n{compacted_content}"
            }]

        except Exception as e:
            logging.error(f"Action compaction failed: {e}", exc_info=True)
            return messages

    def _format_messages(self, messages: List[Dict]) -> str:
        """
        Format messages for compaction prompt.

        Args:
            messages: Message list

        Returns:
            Formatted string
        """
        lines = []
        for msg in messages:
            role = msg.get('role', 'unknown').upper()
            content = msg.get('content', '')
            formatted = self._format_single_message_content(role, content)
            if formatted:
                lines.append(formatted)

        return '\n\n'.join(lines)

    def _format_single_message_content(self, role: str, content) -> str:
        """
        Format content of a single message for compaction.

        Args:
            role: Message role (uppercased)
            content: Message content (string or list of blocks)

        Returns:
            Formatted string for this message
        """
        if isinstance(content, str):
            if len(content) > 1500:
                content = content[:1500] + f"... [truncated, {len(content) - 1500} more chars]"
            return f"[{role}]: {content}"

        if isinstance(content, list):
            parts = [self._format_content_block(block) for block in content
                     if isinstance(block, dict)]
            parts = [p for p in parts if p]
            return f"[{role}]: {' | '.join(parts)}"

        return ''

    @staticmethod
    def _format_content_block(block: Dict) -> Optional[str]:
        """
        Format a single content block for compaction output.

        Args:
            block: Content block dictionary

        Returns:
            Formatted string or None
        """
        block_type = block.get('type')
        if block_type == 'text':
            text = block.get('text', '')
            if len(text) > 500:
                text = text[:500] + "..."
            return text
        if block_type == 'tool_use':
            return f"[Tool: {block.get('name', 'unknown')}]"
        if block_type == 'tool_result':
            result = str(block.get('content', ''))
            if len(result) > 300:
                result = result[:300] + "..."
            return f"[Result: {result}]"
        return None


class ActionExecutor:
    """
    Executes autonomous actions by invoking the LLM.

    Handles:
    - Context preparation (fresh vs cumulative)
    - Tool filtering by action permissions
    - LLM invocation with action prompt
    - Result storage and error handling
    - Auto-disable after N failures
    """

    def __init__(self, database, llm_manager, mcp_manager=None,
                 get_tools_func: Callable[[], List[Dict]] = None,
                 config: Optional[Dict[str, Any]] = None,
                 context_limit_resolver=None):
        """
        Initialise the action executor.

        Args:
            database: ConversationDatabase instance
            llm_manager: LLMManager instance
            mcp_manager: Optional MCPManager for tool access
            get_tools_func: Optional function to get available tools
            config: Optional application configuration for builtin tools
            context_limit_resolver: Optional ContextLimitResolver for model limits
        """
        self.database = database
        self.llm_manager = llm_manager
        self.mcp_manager = mcp_manager
        self.get_tools_func = get_tools_func
        self.config = config or {}
        self.context_limit_resolver = context_limit_resolver

        # Context storage for cumulative mode
        self._cumulative_contexts: Dict[int, List[Dict]] = {}

        # Initialise context compactor for long-running actions
        compaction_config = self.config.get('conversation', {}).get('compaction', {})
        self.context_compactor = ActionContextCompactor(
            llm_manager=llm_manager,
            compaction_threshold=compaction_config.get('action_threshold', 0.6),
            emergency_threshold=compaction_config.get('action_emergency_threshold', 0.85)
        )

        logging.info("ActionExecutor initialised with context compaction support")

    def execute(self, action_id: int, _user_guid: str, is_manual: bool = False) -> Dict[str, Any]:
        """
        Execute an autonomous action.

        Args:
            action_id: ID of the action to execute
            _user_guid: User GUID (reserved for future use)
            is_manual: Whether this is a manual "Run Now" execution

        Returns:
            Dict with 'success', 'run_id', 'result', 'error' keys
        """
        logging.info(f"Executing action {action_id} (manual: {is_manual})")

        # Get action details
        action = self.database.get_action(action_id)
        if not action:
            logging.error(f"Action {action_id} not found")
            return {
                'success': False,
                'run_id': None,
                'result': None,
                'error': 'Action not found'
            }

        if not action['is_enabled'] and not is_manual:
            logging.warning(f"Action {action_id} is disabled, skipping")
            return {
                'success': False,
                'run_id': None,
                'result': None,
                'error': 'Action is disabled'
            }

        # Record run start
        run_id = self.database.record_action_run(
            action_id=action_id,
            status='running'
        )

        try:
            # Execute the action
            result = self._execute_action(action, is_manual)

            # Update run with success
            self.database.update_action_run(
                run_id=run_id,
                status='completed',
                result_text=result.get('text'),
                result_html=result.get('html'),
                input_tokens=result.get('input_tokens', 0),
                output_tokens=result.get('output_tokens', 0),
                context_snapshot=result.get('context_snapshot')
            )

            # Update last run time
            next_run = self._calculate_next_run(action)
            self.database.update_action_last_run(action_id, next_run)

            logging.info(f"Action {action_id} completed successfully (run {run_id})")
            return {
                'success': True,
                'run_id': run_id,
                'result': result.get('text'),
                'error': None
            }

        except Exception as e:
            error_message = str(e)
            logging.error(f"Action {action_id} failed: {error_message}")

            # Update run with failure
            self.database.update_action_run(
                run_id=run_id,
                status='failed',
                error_message=error_message
            )

            # Increment failure count
            failure_info = self.database.increment_action_failure_count(action_id)

            if failure_info.get('auto_disabled'):
                logging.error(
                    f"Action {action_id} ({action['name']}) auto-disabled "
                    f"after {failure_info['failure_count']} failures"
                )

            return {
                'success': False,
                'run_id': run_id,
                'result': None,
                'error': error_message
            }

    def _execute_action(self, action: Dict, _is_manual: bool = False) -> Dict[str, Any]:
        """
        Execute the actual LLM invocation for an action.

        Args:
            action: Action dictionary
            _is_manual: Whether this is a manual execution (reserved for future use)

        Returns:
            Dict with 'text', 'html', 'input_tokens', 'output_tokens', 'context_snapshot'
        """
        model_id = action['model_id']
        self._set_action_model(model_id)

        # Prepare context, tools, system prompt, and max tokens
        messages = self._prepare_context(action)
        tools = self._get_filtered_tools(action['id'])
        system_prompt = self._build_system_prompt(action)
        action_max_tokens = action.get('max_tokens', 8192)

        # Initial model invocation
        response = self._invoke_initial_model(
            action, messages, action_max_tokens, tools, system_prompt
        )

        # Run the tool use loop
        loop_result = self._run_tool_loop(
            action, model_id, messages, response,
            action_max_tokens, tools, system_prompt
        )

        # Assemble final result
        return self._assemble_action_result(
            action, loop_result['messages'], loop_result['response'],
            loop_result['all_text_responses'], loop_result['tool_calls_summary'],
            loop_result['compaction_count']
        )

    def _set_action_model(self, model_id: str) -> None:
        """
        Set the LLM model for action execution.

        Args:
            model_id: Model identifier to set

        Raises:
            RuntimeError: If model cannot be set
        """
        try:
            self.llm_manager.set_model(model_id)
        except Exception as e:
            self._log_available_models()
            raise RuntimeError(f"Failed to set model {model_id}: {e}")

    def _log_available_models(self) -> None:
        """Log available models for diagnostic purposes."""
        try:
            available = self.llm_manager.list_all_models()
            available_ids = [m.get('id', 'unknown') for m in available]
            logging.error(f"Available models: {available_ids}")
        except Exception as list_err:
            logging.error(f"Failed to list available models: {list_err}")

    def _invoke_initial_model(self, action: Dict, messages: List[Dict],
                              action_max_tokens: int, tools: Optional[List[Dict]],
                              system_prompt: str) -> Dict:
        """
        Perform the initial model invocation and validate the response.

        Args:
            action: Action dictionary
            messages: Prepared message context
            action_max_tokens: Maximum tokens for output
            tools: Filtered tool definitions
            system_prompt: System prompt string

        Returns:
            Validated model response dictionary

        Raises:
            RuntimeError: If no response or LLM returns an error
        """
        response = self.llm_manager.invoke_model(
            messages=messages,
            max_tokens=action_max_tokens,
            temperature=0.7,
            tools=tools if tools else None,
            system=system_prompt
        )

        if not response:
            raise RuntimeError("No response from LLM")

        if response.get('error'):
            raise RuntimeError(
                f"LLM error: {response.get('error_message', 'Unknown error')}"
            )

        stop_reason = response.get('stop_reason', 'unknown')
        usage = response.get('usage', {})
        output_tokens = usage.get('output_tokens', 0)
        logging.debug(
            f"Action {action['id']} initial response: stop_reason={stop_reason}, "
            f"output_tokens={output_tokens}, max_tokens={action_max_tokens}"
        )
        return response

    def _run_tool_loop(self, action: Dict, model_id: str,
                       messages: List[Dict], response: Dict,
                       action_max_tokens: int, tools: Optional[List[Dict]],
                       system_prompt: str) -> Dict[str, Any]:
        """
        Run the tool use loop until the LLM stops requesting tools.

        Args:
            action: Action dictionary
            model_id: Model identifier (for context window lookup)
            messages: Current message list
            response: Initial model response
            action_max_tokens: Maximum tokens for output
            tools: Filtered tool definitions
            system_prompt: System prompt string

        Returns:
            Dict with 'messages', 'response', 'all_text_responses',
            'tool_calls_summary', 'compaction_count'
        """
        max_tool_iterations = action.get('max_tool_iterations', None)
        if max_tool_iterations is None:
            max_tool_iterations = self.config.get('conversation', {}).get('max_tool_iterations', 25)
        logging.debug(f"Action {action['id']} max tool iterations: {max_tool_iterations}")

        all_text_responses = []
        tool_calls_summary = []
        compaction_count = 0
        context_window = self._get_context_window(model_id)
        iteration = 0

        initial_text = self._extract_text_response(response)
        if initial_text:
            all_text_responses.append(initial_text)

        while iteration < max_tool_iterations:
            content_blocks = response.get('content_blocks', [])
            tool_use_blocks = [b for b in content_blocks if b.get('type') == 'tool_use']

            if not tool_use_blocks:
                break

            iteration += 1
            logging.debug(f"Action {action['id']} tool iteration {iteration}/{max_tool_iterations}")

            # Track tool calls for summary
            for block in tool_use_blocks:
                tool_calls_summary.append({
                    'iteration': iteration,
                    'tool': block.get('name', 'unknown'),
                    'input': block.get('input', {})
                })

            # Execute tool calls and add results to messages
            tool_results = self._execute_tool_calls(action['id'], tool_use_blocks)
            messages = self._add_tool_results(messages, response, tool_results)

            # Periodic context compaction
            messages, compaction_count = self._maybe_compact_context(
                action, messages, iteration, context_window, compaction_count
            )

            # Next model invocation
            response = self._invoke_tool_iteration(
                action, messages, action_max_tokens, tools, system_prompt, iteration
            )

            iter_text = self._extract_text_response(response)
            if iter_text:
                all_text_responses.append(iter_text)

        if iteration >= max_tool_iterations:
            logging.warning(f"Action {action['id']} reached max tool iterations ({max_tool_iterations})")
            all_text_responses.append(
                f"\n\n---\n**Note:** Action reached maximum tool iterations ({max_tool_iterations}). "
                f"The task may be incomplete. Consider increasing max_tool_iterations in config."
            )

        return {
            'messages': messages,
            'response': response,
            'all_text_responses': all_text_responses,
            'tool_calls_summary': tool_calls_summary,
            'compaction_count': compaction_count
        }

    def _maybe_compact_context(self, action: Dict, messages: List[Dict],
                               iteration: int, context_window: int,
                               compaction_count: int) -> Tuple[List[Dict], int]:
        """
        Check and perform context compaction if needed.

        Args:
            action: Action dictionary
            messages: Current message list
            iteration: Current tool iteration number
            context_window: Model context window size
            compaction_count: Running count of compactions performed

        Returns:
            Tuple of (possibly compacted messages, updated compaction count)
        """
        if iteration % 3 != 0 or context_window <= 0:
            return messages, compaction_count

        messages, compacted = self.context_compactor.check_and_compact(
            messages=messages,
            original_prompt=action['action_prompt'],
            context_window=context_window,
            in_tool_loop=True
        )
        if compacted:
            compaction_count += 1
            logging.info(f"Action {action['id']} context compacted (compaction #{compaction_count})")

        return messages, compaction_count

    def _invoke_tool_iteration(self, action: Dict, messages: List[Dict],
                               action_max_tokens: int, tools: Optional[List[Dict]],
                               system_prompt: str, iteration: int) -> Dict:
        """
        Invoke the model during a tool use iteration.

        Args:
            action: Action dictionary
            messages: Current message list
            action_max_tokens: Maximum tokens for output
            tools: Filtered tool definitions
            system_prompt: System prompt string
            iteration: Current iteration number

        Returns:
            Model response dictionary

        Raises:
            RuntimeError: If the model returns an error
        """
        response = self.llm_manager.invoke_model(
            messages=messages,
            max_tokens=action_max_tokens,
            temperature=0.7,
            tools=tools if tools else None,
            system=system_prompt
        )

        if response.get('error'):
            raise RuntimeError(
                f"LLM error during tool iteration: {response.get('error_message', 'Unknown error')}"
            )

        iter_stop_reason = response.get('stop_reason', 'unknown')
        iter_usage = response.get('usage', {})
        iter_output_tokens = iter_usage.get('output_tokens', 0)
        logging.debug(
            f"Action {action['id']} iteration {iteration} response: "
            f"stop_reason={iter_stop_reason}, output_tokens={iter_output_tokens}"
        )
        return response

    def _assemble_action_result(self, action: Dict, messages: List[Dict],
                                response: Dict, all_text_responses: List[str],
                                tool_calls_summary: List[Dict],
                                compaction_count: int) -> Dict[str, Any]:
        """
        Assemble the final action result from accumulated data.

        Args:
            action: Action dictionary
            messages: Final message list
            response: Final model response
            all_text_responses: Accumulated text responses
            tool_calls_summary: Summary of tool calls made
            compaction_count: Number of compactions performed

        Returns:
            Dict with 'text', 'html', 'input_tokens', 'output_tokens', 'context_snapshot'
        """
        text_response = '\n\n'.join(all_text_responses) if all_text_responses else ''

        # Build execution summary
        text_response = self._append_execution_summary(
            text_response, tool_calls_summary, compaction_count
        )

        html_response = self._convert_to_html(text_response)

        # Update cumulative context if needed
        context_snapshot = None
        if action['context_mode'] == 'cumulative':
            self._update_cumulative_context(action['id'], messages, response)
            context_snapshot = json.dumps(self._cumulative_contexts.get(action['id'], []))

        usage = response.get('usage', {})
        return {
            'text': text_response,
            'html': html_response,
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'context_snapshot': context_snapshot
        }

    @staticmethod
    def _append_execution_summary(text_response: str, tool_calls_summary: List[Dict],
                                  compaction_count: int) -> str:
        """
        Append execution summary to the text response.

        Args:
            text_response: Current text response
            tool_calls_summary: Summary of tool calls made
            compaction_count: Number of compactions performed

        Returns:
            Text response with summary appended
        """
        summary_parts = []
        if tool_calls_summary:
            tools_used = set(tc['tool'] for tc in tool_calls_summary)
            summary_parts.append(
                f"**Tools used ({len(tool_calls_summary)} calls):** {', '.join(sorted(tools_used))}"
            )
        if compaction_count > 0:
            summary_parts.append(f"**Context compactions:** {compaction_count}")
        if summary_parts:
            text_response += "\n\n---\n" + " | ".join(summary_parts)
        return text_response

    def _prepare_context(self, action: Dict) -> List[Dict]:
        """
        Prepare the message context for the action.

        Args:
            action: Action dictionary

        Returns:
            List of message dictionaries
        """
        if action['context_mode'] == 'cumulative':
            # Use stored context plus new prompt
            context = self._cumulative_contexts.get(action['id'], []).copy()
            context.append({
                'role': 'user',
                'content': action['action_prompt']
            })
            return context
        else:
            # Fresh context - just the action prompt
            return [{
                'role': 'user',
                'content': action['action_prompt']
            }]

    def _update_cumulative_context(self, action_id: int,
                                   messages: List[Dict],
                                   response: Dict):
        """
        Update the cumulative context for an action.

        Args:
            action_id: Action ID
            messages: Messages sent to the model
            response: Model response
        """
        # Add assistant response to context
        content = self._extract_text_response(response)
        messages.append({
            'role': 'assistant',
            'content': content
        })

        # Store for next run
        self._cumulative_contexts[action_id] = messages

        # Trim if too long (keep last 10 exchanges)
        if len(messages) > 20:
            self._cumulative_contexts[action_id] = messages[-20:]

    def _get_filtered_tools(self, action_id: int) -> Optional[List[Dict]]:
        """
        Get tools filtered by action permissions.

        Includes both MCP tools and builtin tools (datetime, filesystem).
        Also populates self._tool_sources for routing during execution.

        Args:
            action_id: Action ID

        Returns:
            List of allowed tool definitions or None
        """
        from dtSpark.tools import builtin

        # Get action's tool permissions
        permissions = self.database.get_action_tool_permissions(action_id)
        if not permissions:
            return None  # No tools allowed

        allowed_tools = {p['tool_name'] for p in permissions
                         if p['permission_state'] == 'allowed'}

        filtered = []
        # Store tool sources for execution routing (not sent to API)
        self._tool_sources = {}

        # Get builtin tools (datetime, filesystem if enabled)
        builtin_tools = builtin.get_builtin_tools(self.config)
        for tool in builtin_tools:
            if tool['name'] in allowed_tools:
                filtered.append({
                    'name': tool['name'],
                    'description': tool['description'],
                    'input_schema': tool['input_schema']
                })
                self._tool_sources[tool['name']] = 'builtin'

        # Get MCP tools
        if self.get_tools_func:
            mcp_tools = self.get_tools_func()
            if mcp_tools:
                for tool in mcp_tools:
                    if tool['name'] in allowed_tools:
                        filtered.append({
                            'name': tool['name'],
                            'description': tool['description'],
                            'input_schema': tool['input_schema']
                        })
                        self._tool_sources[tool['name']] = 'mcp'

        return filtered if filtered else None

    def _execute_tool_calls(self, action_id: int,
                            tool_use_blocks: List[Dict]) -> List[Dict]:
        """
        Execute tool calls and return results.

        Handles both builtin tools and MCP tools.
        Uses self._tool_sources (populated by _get_filtered_tools) for routing.

        Args:
            action_id: Action ID for permission checking
            tool_use_blocks: Tool use blocks from model response

        Returns:
            List of tool result dictionaries
        """
        results = []
        tool_sources = getattr(self, '_tool_sources', {})

        for tool_block in tool_use_blocks:
            result = self._execute_single_tool_call(
                action_id, tool_block, tool_sources
            )
            results.append(result)

        return results

    def _execute_single_tool_call(self, action_id: int, tool_block: Dict,
                                  tool_sources: Dict[str, str]) -> Dict:
        """
        Execute a single tool call and return the result.

        Args:
            action_id: Action ID for permission checking
            tool_block: Tool use block from model response
            tool_sources: Mapping of tool names to their source ('builtin' or 'mcp')

        Returns:
            Tool result dictionary
        """
        tool_name = tool_block.get('name')
        tool_id = tool_block.get('id')
        tool_input = tool_block.get('input', {})

        self._log_write_file_debug(tool_name, tool_block, tool_input)

        try:
            if not self._is_tool_permitted(action_id, tool_name):
                return {
                    'type': 'tool_result',
                    'tool_use_id': tool_id,
                    'content': f"Tool '{tool_name}' is not permitted for this action"
                }

            tool_source = tool_sources.get(tool_name, 'mcp')

            if tool_source == 'builtin':
                return self._execute_builtin_tool_call(tool_name, tool_id, tool_input)

            if self.mcp_manager:
                return self._execute_mcp_tool_call(tool_name, tool_id, tool_input)

            return {
                'type': 'tool_result',
                'tool_use_id': tool_id,
                'content': "No tool execution handler available"
            }

        except Exception as e:
            logging.error(f"Tool {tool_name} execution failed: {e}")
            return {
                'type': 'tool_result',
                'tool_use_id': tool_id,
                'content': f"Error executing tool: {str(e)}",
                'is_error': True
            }

    @staticmethod
    def _log_write_file_debug(tool_name: str, tool_block: Dict, tool_input: Dict) -> None:
        """Log debug information for write_file tool calls."""
        if tool_name != 'write_file':
            return
        logging.debug(f"write_file tool_block keys: {list(tool_block.keys())}")
        logging.debug(f"write_file tool_input keys: {list(tool_input.keys()) if tool_input else 'None'}")
        content_preview = str(tool_input.get('content', ''))[:100] if tool_input else ''
        logging.debug(
            f"write_file content preview: '{content_preview}...' "
            f"(len={len(tool_input.get('content', '') or '')})"
        )

    def _is_tool_permitted(self, action_id: int, tool_name: str) -> bool:
        """
        Check whether a tool is permitted for the given action.

        Args:
            action_id: Action ID
            tool_name: Name of the tool to check

        Returns:
            True if the tool is allowed
        """
        permissions = self.database.get_action_tool_permissions(action_id)
        return any(
            p['tool_name'] == tool_name and p['permission_state'] == 'allowed'
            for p in permissions
        )

    def _execute_builtin_tool_call(self, tool_name: str, tool_id: str,
                                   tool_input: Dict) -> Dict:
        """
        Execute a builtin tool call and return the formatted result.

        Args:
            tool_name: Name of the builtin tool
            tool_id: Tool use ID for the response
            tool_input: Tool input parameters

        Returns:
            Tool result dictionary
        """
        from dtSpark.tools import builtin

        logging.debug(f"Executing builtin tool: {tool_name}")
        result = builtin.execute_builtin_tool(tool_name, tool_input, self.config)

        if result.get('success'):
            result_data = result.get('result', {})
            result_str = json.dumps(result_data, indent=2) if isinstance(result_data, dict) else str(result_data)
            return {
                'type': 'tool_result',
                'tool_use_id': tool_id,
                'content': result_str
            }

        return {
            'type': 'tool_result',
            'tool_use_id': tool_id,
            'content': result.get('error', 'Builtin tool execution failed'),
            'is_error': True
        }

    def _execute_mcp_tool_call(self, tool_name: str, tool_id: str,
                               tool_input: Dict) -> Dict:
        """
        Execute an MCP tool call and return the formatted result.

        Args:
            tool_name: Name of the MCP tool
            tool_id: Tool use ID for the response
            tool_input: Tool input parameters

        Returns:
            Tool result dictionary
        """
        logging.debug(f"Executing MCP tool: {tool_name}")
        result = self._call_mcp_tool_sync(tool_name, tool_input)

        if result and not result.get('isError'):
            return {
                'type': 'tool_result',
                'tool_use_id': tool_id,
                'content': self._extract_mcp_text_content(result)
            }

        return {
            'type': 'tool_result',
            'tool_use_id': tool_id,
            'content': self._extract_mcp_error_message(result),
            'is_error': True
        }

    @staticmethod
    def _extract_mcp_text_content(result: Dict) -> str:
        """
        Extract text content from an MCP tool result.

        Args:
            result: MCP tool result dictionary

        Returns:
            Concatenated text content or default message
        """
        content_parts = [
            content.get('text', '')
            for content in result.get('content', [])
            if content.get('type') == 'text'
        ]
        return '\n'.join(content_parts) if content_parts else 'Tool executed successfully (no output)'

    @staticmethod
    def _extract_mcp_error_message(result: Optional[Dict]) -> str:
        """
        Extract error message from an MCP tool result.

        Args:
            result: MCP tool result dictionary (may be None)

        Returns:
            Error message string
        """
        if not result:
            return "Tool execution failed"

        for content in result.get('content', []):
            if content.get('type') == 'text':
                return content.get('text', 'Tool execution failed')

        return "Tool execution failed"

    def _call_mcp_tool_sync(self, tool_name: str, tool_input: Dict) -> Optional[Dict]:
        """
        Call an async MCP tool from synchronous context.

        Uses the MCP manager's initialisation event loop or creates a new one
        to execute the async call_tool method.

        Args:
            tool_name: Name of the tool to call
            tool_input: Tool input parameters

        Returns:
            Tool result dictionary or None on failure
        """
        try:
            # Check if there's a running event loop
            try:
                loop = asyncio.get_running_loop()
                # Running in async context - use thread pool to avoid blocking
                logging.debug(f"Running event loop detected, using thread pool for tool {tool_name}")

                def run_tool_in_loop():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            asyncio.wait_for(
                                self.mcp_manager.call_tool(tool_name, tool_input),
                                timeout=30.0
                            )
                        )
                    except asyncio.TimeoutError:
                        logging.error(f"Timeout calling MCP tool {tool_name} after 30 seconds")
                        return None
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_tool_in_loop)
                    return future.result(timeout=35.0)

            except RuntimeError:
                # No running event loop - we're in sync context
                logging.debug(f"No running event loop, using standard approach for tool {tool_name}")

                # Use the MCP manager's initialisation loop if available
                if hasattr(self.mcp_manager, '_initialization_loop') and self.mcp_manager._initialization_loop:
                    loop = self.mcp_manager._initialization_loop
                    should_close_loop = False
                    logging.debug(f"Using stored initialisation event loop for tool {tool_name}")
                else:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    should_close_loop = True
                    logging.debug(f"Creating temporary event loop for tool {tool_name}")

                try:
                    return loop.run_until_complete(
                        asyncio.wait_for(
                            self.mcp_manager.call_tool(tool_name, tool_input),
                            timeout=30.0
                        )
                    )
                except asyncio.TimeoutError:
                    logging.error(f"Timeout calling MCP tool {tool_name} after 30 seconds")
                    return None
                finally:
                    if should_close_loop:
                        loop.close()

        except Exception as e:
            logging.error(f"Error calling MCP tool {tool_name}: {e}")
            return None

    def _add_tool_results(self, messages: List[Dict],
                          response: Dict,
                          tool_results: List[Dict]) -> List[Dict]:
        """
        Add tool results to the message history.

        Args:
            messages: Current messages
            response: Model response with tool_use
            tool_results: Tool execution results

        Returns:
            Updated message list
        """
        # Add assistant's tool use response
        # Note: Must use content_blocks which contains the tool_use blocks
        messages.append({
            'role': 'assistant',
            'content': response.get('content_blocks', [])
        })

        # Add tool results as user message
        messages.append({
            'role': 'user',
            'content': tool_results
        })

        return messages

    def _extract_text_response(self, response: Dict) -> str:
        """
        Extract text content from model response.

        Args:
            response: Model response dictionary

        Returns:
            Text content string
        """
        content = response.get('content', [])

        if isinstance(content, str):
            return content

        text_parts = []
        for block in content:
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))

        return '\n'.join(text_parts)

    def _convert_to_html(self, text: str) -> str:
        """
        Convert markdown text to HTML.

        Args:
            text: Markdown text

        Returns:
            HTML string
        """
        try:
            return markdown.markdown(
                text,
                extensions=['tables', 'fenced_code', 'codehilite']
            )
        except Exception as e:
            logging.warning(f"Failed to convert to HTML: {e}")
            return f"<pre>{text}</pre>"

    def _build_system_prompt(self, action: Dict) -> str:
        """
        Build the system prompt for the action.

        Includes current date/time for time awareness.

        Args:
            action: Action dictionary

        Returns:
            System prompt string
        """
        # Get current datetime with timezone
        now = datetime.now().astimezone()
        current_datetime = now.strftime("%A, %d %B %Y at %H:%M:%S %Z")
        iso_datetime = now.isoformat()

        return f"""You are an autonomous AI assistant executing a scheduled action.

Current Date and Time: {current_datetime}
ISO Format: {iso_datetime}

Action Name: {action['name']}
Action Description: {action['description']}

Execute the requested task to the best of your ability. Be concise and focused.
If you need to use tools, use only those that have been explicitly permitted for this action.
You have access to the get_current_datetime tool if you need precise time information with timezone support.
"""

    def _calculate_next_run(self, action: Dict) -> Optional[datetime]:
        """
        Calculate the next run time for a recurring action.

        Args:
            action: Action dictionary

        Returns:
            Next run datetime or None for one-off actions
        """
        if action['schedule_type'] == 'one_off':
            return None

        # For recurring actions, APScheduler handles the next run calculation
        # This is just a placeholder - the scheduler will update this
        return None

    def clear_cumulative_context(self, action_id: int):
        """
        Clear the cumulative context for an action.

        Args:
            action_id: Action ID
        """
        if action_id in self._cumulative_contexts:
            del self._cumulative_contexts[action_id]
            logging.info(f"Cleared cumulative context for action {action_id}")

    def load_cumulative_context(self, action_id: int, context_json: str):
        """
        Load cumulative context from a stored snapshot.

        Args:
            action_id: Action ID
            context_json: JSON string of context messages
        """
        try:
            context = json.loads(context_json)
            self._cumulative_contexts[action_id] = context
            logging.debug(f"Loaded cumulative context for action {action_id}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to load cumulative context: {e}")

    def _get_context_window(self, model_id: str) -> int:
        """
        Get the context window size for a model.

        Uses ContextLimitResolver if available, otherwise returns defaults
        based on model ID patterns.

        Args:
            model_id: Model identifier

        Returns:
            Context window size in tokens
        """
        # Try using the context limit resolver if available
        if self.context_limit_resolver:
            try:
                # Determine provider from model ID
                provider = self._get_provider_from_model_id(model_id)
                limits = self.context_limit_resolver.get_context_limits(model_id, provider)
                return limits.get('context_window', 200000)
            except Exception as e:
                logging.warning(f"Failed to get context limits for {model_id}: {e}")

        # Fallback defaults based on model patterns
        model_lower = model_id.lower()

        # Claude models
        if 'claude-3-5' in model_lower or 'claude-3.5' in model_lower:
            return 200000
        elif 'claude-3' in model_lower:
            return 200000
        elif 'claude-2' in model_lower:
            return 100000

        # Llama models
        if 'llama' in model_lower:
            return 128000

        # Mistral models
        if 'mistral' in model_lower:
            return 32000

        # Default fallback
        return 128000

    def _get_provider_from_model_id(self, model_id: str) -> str:
        """
        Determine provider from model ID.

        Args:
            model_id: Model identifier

        Returns:
            Provider name string
        """
        model_lower = model_id.lower()

        if 'claude' in model_lower or 'anthropic' in model_lower:
            return 'anthropic'
        if 'amazon.' in model_lower or 'titan' in model_lower:
            return 'aws_bedrock'
        if 'meta.' in model_lower or 'llama' in model_lower:
            return 'aws_bedrock'
        if 'mistral.' in model_lower:
            return 'aws_bedrock'

        return 'ollama'
