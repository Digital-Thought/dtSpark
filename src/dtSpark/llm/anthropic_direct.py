"""
Anthropic Direct API service module.

This module provides functionality for:
- Listing available Anthropic models
- Invoking Anthropic models via direct API
- Tool/function calling support
- Token counting
- Rate limit handling with exponential backoff
"""

import logging
import os
import time
from typing import List, Dict, Optional, Any
from dtSpark.llm.base import LLMService

try:
    from anthropic import Anthropic, RateLimitError
except ImportError:
    logging.error("anthropic module not installed. Please run: pip install anthropic")
    raise


class AnthropicService(LLMService):
    """Manages interactions with Anthropic API directly using official SDK."""

    # Rate limits for Anthropic API (default tier)
    # Source: https://docs.anthropic.com/en/api/rate-limits
    # These are conservative defaults - actual limits depend on account tier
    DEFAULT_RATE_LIMITS = {
        'input_tokens_per_minute': 30000,   # Default tier limit
        'output_tokens_per_minute': 8000,   # Default tier limit
        'requests_per_minute': 50,          # Default tier limit
        'has_limits': True
    }

    # Model specifications: pricing and max tokens by model ID pattern
    # Source: https://www.anthropic.com/pricing and model documentation
    MODEL_SPECS = {
        # Pricing per million tokens (MTok)
        'claude-opus-4': {'input': 15.00, 'output': 75.00, 'max_output': 32000},
        'claude-sonnet-4': {'input': 3.00, 'output': 15.00, 'max_output': 64000},
        'claude-3-7-sonnet': {'input': 3.00, 'output': 15.00, 'max_output': 64000},  # claude-3-7-sonnet-20250219
        'claude-sonnet-3.7': {'input': 3.00, 'output': 15.00, 'max_output': 64000},  # alias
        'claude-haiku-4': {'input': 0.80, 'output': 4.00, 'max_output': 64000},
        'claude-3-5-sonnet': {'input': 3.00, 'output': 15.00, 'max_output': 8192},
        'claude-3-5-haiku': {'input': 0.80, 'output': 4.00, 'max_output': 8192},
        'claude-3-opus': {'input': 15.00, 'output': 75.00, 'max_output': 4096},
        'claude-3-sonnet': {'input': 3.00, 'output': 15.00, 'max_output': 4096},
        'claude-3-haiku': {'input': 0.25, 'output': 1.25, 'max_output': 4096},
        # Default for unknown models
        'default': {'input': 3.00, 'output': 15.00, 'max_output': 8192}
    }

    def __init__(self, api_key: Optional[str] = None, default_max_tokens: int = 8192,
                 rate_limit_max_retries: int = 5, rate_limit_base_delay: float = 2.0):
        """
        Initialise the Anthropic service.

        Args:
            api_key: Anthropic API key (or use ANTHROPIC_API_KEY env var)
            default_max_tokens: Default maximum tokens to request (will be capped to model's limit)
            rate_limit_max_retries: Maximum number of retries for rate limit errors (default: 5)
            rate_limit_base_delay: Base delay in seconds for exponential backoff (default: 2.0)
        """
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set via parameter or ANTHROPIC_API_KEY env var")

        self.client = Anthropic(api_key=self.api_key)
        self.current_model_id = None
        self.default_max_tokens = default_max_tokens
        self.rate_limit_max_retries = rate_limit_max_retries
        self.rate_limit_base_delay = rate_limit_base_delay


    def get_provider_name(self) -> str:
        """Get provider name."""
        return "Anthropic Direct"

    def get_access_info(self) -> str:
        """Get access information."""
        return "Anthropic API"

    def _get_model_spec(self, model_id: str) -> Dict[str, Any]:
        """
        Get specifications for a model by matching ID pattern.

        Args:
            model_id: Full model ID from API

        Returns:
            Dictionary with input, output pricing and max_output
        """
        # Try to match model ID with spec patterns
        for pattern, spec in self.MODEL_SPECS.items():
            if pattern in model_id:
                return spec

        # Return default if no match found
        logging.warning(f"No specs found for model {model_id}, using defaults")
        return self.MODEL_SPECS['default']

    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List all available Anthropic models from the API.

        Returns:
            List of model dictionaries
        """
        models = []

        try:
            # Fetch models from Anthropic API
            response = self.client.models.list()

            for model in response.data:
                # Get specs for this model
                specs = self._get_model_spec(model.id)

                models.append({
                    'id': model.id,
                    'name': model.display_name if hasattr(model, 'display_name') else model.id,
                    'provider': 'Anthropic',
                    'access_info': self.get_access_info(),
                    'supports_tools': True,  # All Claude models support tools
                    'context_length': 200000,  # All current Claude models have 200K context
                    'max_output': specs['max_output'],
                    'response_streaming': True,
                    'pricing': {'input': specs['input'], 'output': specs['output']}
                })

            logging.info(f"Found {len(models)} Anthropic models from API")

        except Exception as e:
            logging.error(f"Failed to fetch models from Anthropic API: {e}")
            # Return empty list if API call fails
            logging.warning("Returning empty model list due to API error")

        return models

    def set_model(self, model_id: str):
        """Set the active Anthropic model."""
        self.current_model_id = model_id
        logging.info(f"Anthropic model set to: {model_id}")

    def get_model_max_tokens(self, model_id: str) -> int:
        """
        Get the maximum output tokens for a specific model.

        Args:
            model_id: The model ID to look up

        Returns:
            Maximum output tokens for the model (defaults to 8192 if not found)
        """
        specs = self._get_model_spec(model_id)
        return specs['max_output']

    def invoke_model(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[Dict[str, Any]]:
        """
        Invoke Anthropic model with conversation.

        Args:
            messages: Conversation messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            tools: Optional tool definitions
            system: Optional system prompt
            max_retries: Maximum retry attempts

        Returns:
            Response dictionary in standard format
        """
        if not self.current_model_id:
            return {
                'error': True,
                'error_code': 'NoModelSelected',
                'error_message': 'No Anthropic model selected',
                'error_type': 'ConfigurationError'
            }

        try:
            api_params = self._build_api_params(messages, max_tokens, temperature, tools, system)
            return self._execute_streaming_request(api_params)

        except Exception as e:
            logging.error(f"Anthropic API error: {e}")
            return {
                'error': True,
                'error_code': 'AnthropicAPIError',
                'error_message': str(e),
                'error_type': 'RequestError'
            }

    def _build_api_params(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]],
        system: Optional[str]
    ) -> Dict[str, Any]:
        """
        Build API parameters for an Anthropic request.

        Handles max_tokens capping, message conversion, and tool conversion.

        Args:
            messages: Conversation messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            tools: Optional tool definitions
            system: Optional system prompt

        Returns:
            Dictionary of API parameters ready for the Anthropic client
        """
        # Use provided max_tokens or fall back to default from config
        requested_max_tokens = max_tokens if max_tokens != 4096 else self.default_max_tokens

        # Get model's max output tokens to ensure we don't exceed it
        model_max_output = self.get_model_max_tokens(self.current_model_id)

        # Cap max_tokens to model's limit
        actual_max_tokens = min(requested_max_tokens, model_max_output)
        if actual_max_tokens < requested_max_tokens:
            logging.info(
                f"Capping max_tokens from {requested_max_tokens} to {actual_max_tokens} "
                f"(model {self.current_model_id} limit)"
            )

        # Convert messages to Anthropic format
        anthropic_messages = self._convert_messages_to_anthropic(messages)

        # Build API parameters
        api_params = {
            'model': self.current_model_id,
            'messages': anthropic_messages,
            'max_tokens': actual_max_tokens,
            'temperature': temperature
        }

        if system:
            api_params['system'] = system

        if tools:
            api_params['tools'] = self._convert_tools_to_anthropic(tools)
            logging.debug(f"Sending {len(api_params['tools'])} tools to Anthropic API")

        logging.debug(f"Invoking Anthropic model: {self.current_model_id}")
        self._log_api_params(api_params)

        return api_params

    def _log_api_params(self, api_params: Dict[str, Any]) -> None:
        """Log API parameters for debugging (excluding message content)."""
        debug_info = {
            'model': api_params['model'],
            'max_tokens': api_params['max_tokens'],
            'temperature': api_params['temperature'],
            'has_system': 'system' in api_params,
            'has_tools': 'tools' in api_params,
            'num_tools': len(api_params.get('tools', []))
        }
        logging.debug("API params (excluding messages): %s", debug_info)

    def _execute_streaming_request(self, api_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a streaming request with rate limit retry logic.

        Args:
            api_params: Pre-built API parameters

        Returns:
            Response dictionary in standard format, or error dictionary
        """
        text_parts = []
        content_blocks = []
        tool_use_blocks = []
        stop_reason = None
        usage_info = {'input_tokens': 0, 'output_tokens': 0}

        for retry_attempt in range(self.rate_limit_max_retries):
            try:
                with self.client.messages.stream(**api_params) as stream:
                    self._process_stream_events(stream, text_parts)

                    final_message = stream.get_final_message()
                    self._extract_final_message_data(
                        final_message, usage_info, content_blocks, tool_use_blocks
                    )
                    if hasattr(final_message, 'stop_reason'):
                        stop_reason = final_message.stop_reason

                # Successfully completed - break out of retry loop
                break

            except RateLimitError as e:
                error_response = self._handle_rate_limit_error(e, retry_attempt)
                if error_response is not None:
                    return error_response

        return self._build_response(text_parts, content_blocks, tool_use_blocks, stop_reason, usage_info)

    def _process_stream_events(
        self,
        stream,
        text_parts: List[str]
    ) -> None:
        """
        Process streaming events, accumulating text deltas.

        Args:
            stream: The Anthropic streaming response
            text_parts: List to accumulate text delta strings into
        """
        for event in stream:
            if not hasattr(event, 'type'):
                continue

            if event.type == 'content_block_delta':
                self._handle_content_block_delta(event, text_parts)

    def _handle_content_block_delta(self, event, text_parts: List[str]) -> None:
        """Handle a content_block_delta event by extracting text."""
        if not hasattr(event, 'delta'):
            return
        if not hasattr(event.delta, 'type'):
            return
        if event.delta.type == 'text_delta':
            text_parts.append(event.delta.text)

    def _extract_final_message_data(
        self,
        final_message,
        usage_info: Dict[str, int],
        content_blocks: List[Dict[str, Any]],
        tool_use_blocks: List[Dict[str, Any]]
    ) -> None:
        """
        Extract usage, stop reason, and content blocks from the final message.

        Args:
            final_message: The final message object from the stream
            usage_info: Dictionary to update with token usage
            content_blocks: List to append content blocks to
            tool_use_blocks: List to append tool use blocks to
        """
        if hasattr(final_message, 'usage'):
            usage_info['input_tokens'] = final_message.usage.input_tokens
            usage_info['output_tokens'] = final_message.usage.output_tokens

        if not hasattr(final_message, 'content'):
            return

        for block in final_message.content:
            if not hasattr(block, 'type'):
                continue
            if block.type == 'text':
                content_blocks.append({'type': 'text', 'text': block.text})
            elif block.type == 'tool_use':
                tool_block = {
                    'type': 'tool_use',
                    'id': block.id,
                    'name': block.name,
                    'input': block.input
                }
                tool_use_blocks.append(tool_block)
                content_blocks.append(tool_block)

    def _handle_rate_limit_error(self, error: Exception, retry_attempt: int) -> Optional[Dict[str, Any]]:
        """
        Handle a rate limit error with exponential backoff.

        Args:
            error: The RateLimitError exception
            retry_attempt: Current retry attempt index (0-based)

        Returns:
            None if retrying (caller should continue), or an error dict if retries exhausted
        """
        if retry_attempt < self.rate_limit_max_retries - 1:
            wait_time = self.rate_limit_base_delay ** retry_attempt
            logging.warning(
                f"Rate limit exceeded (attempt {retry_attempt + 1}/{self.rate_limit_max_retries}). "
                f"Waiting {wait_time:.1f} seconds before retrying..."
            )
            logging.debug(f"Rate limit error details: {str(error)}")
            time.sleep(wait_time)
            return None

        # Final retry failed
        logging.error(
            f"Rate limit exceeded after {self.rate_limit_max_retries} attempts. "
            "Please reduce request frequency or contact Anthropic for rate limit increase."
        )
        logging.error(f"Rate limit error details: {str(error)}")
        return {
            'error': True,
            'error_code': 'RateLimitExceeded',
            'error_message': f"Rate limit exceeded after {self.rate_limit_max_retries} retry attempts. {str(error)}",
            'error_type': 'RateLimitError'
        }

    def _build_response(
        self,
        text_parts: List[str],
        content_blocks: List[Dict[str, Any]],
        tool_use_blocks: List[Dict[str, Any]],
        stop_reason: Optional[str],
        usage_info: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Build the standard response dictionary from accumulated stream data.

        Args:
            text_parts: Accumulated text parts from streaming
            content_blocks: All content blocks (text and tool use)
            tool_use_blocks: Tool use blocks specifically
            stop_reason: The stop reason from the API
            usage_info: Token usage information

        Returns:
            Response dictionary in standard format
        """
        response = {
            'stop_reason': stop_reason,
            'usage': usage_info,
            'content_blocks': content_blocks,
            'content': ''.join(text_parts)
        }

        if tool_use_blocks:
            response['tool_use'] = tool_use_blocks
            response['stop_reason'] = 'tool_use'

        return response

    def _convert_messages_to_anthropic(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert standard message format to Anthropic format.

        The Anthropic API uses the same format as our standard, so minimal conversion needed.
        """
        anthropic_messages = []

        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', [])

            # Anthropic uses the same content block format
            anthropic_messages.append({
                'role': role,
                'content': content
            })

        return anthropic_messages

    def _convert_tools_to_anthropic(
        self,
        tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert tool definitions to Anthropic format.

        Anthropic requires the input_schema to have a 'type' field.
        """
        anthropic_tools = []

        logging.debug(f"Converting {len(tools)} tools to Anthropic format")

        for tool in tools:
            # Extract toolSpec
            tool_spec = tool.get('toolSpec', tool)

            logging.debug(f"Original tool spec: {tool_spec}")

            # Get input schema and ensure it has 'type' field
            # Check both 'inputSchema' (Bedrock format) and 'input_schema' (MCP format)
            input_schema = tool_spec.get('inputSchema') or tool_spec.get('input_schema', {})

            # Anthropic requires 'type' field in input_schema
            if 'type' not in input_schema:
                input_schema = {
                    'type': 'object',
                    'properties': input_schema.get('properties', {}),
                    'required': input_schema.get('required', [])
                }

            anthropic_tool = {
                'name': tool_spec.get('name', ''),
                'description': tool_spec.get('description', ''),
                'input_schema': input_schema
            }

            logging.debug(f"Converted Anthropic tool: {anthropic_tool}")
            anthropic_tools.append(anthropic_tool)

        return anthropic_tools

    def supports_streaming(self) -> bool:
        """Check if Anthropic supports streaming."""
        return True  # Streaming is implemented and used by default

    def count_tokens(self, text: str) -> int:
        """
        Count tokens using Anthropic's token counting API.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        try:
            # Use Anthropic's messages.count_tokens endpoint
            # This requires a model and messages in the proper format
            model = self.current_model_id or 'claude-sonnet-4-20250514'
            response = self.client.messages.count_tokens(
                model=model,
                messages=[{'role': 'user', 'content': text}]
            )
            return response.input_tokens
        except Exception as e:
            logging.warning(f"Token counting failed: {e}")
            # Fallback: rough estimate of 4 chars per token
            return len(text) // 4

    def get_rate_limits(self) -> dict:
        """
        Get rate limit information for Anthropic Direct API.

        Returns:
            Dictionary with rate limit information.
            Note: Actual limits depend on account tier.
        """
        return self.DEFAULT_RATE_LIMITS.copy()

