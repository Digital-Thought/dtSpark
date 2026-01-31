"""
Ollama service module for interacting with local Ollama instances.

This module provides functionality for:
- Listing available Ollama models
- Invoking Ollama models for chat completions
- Converting between Bedrock and Ollama message formats
"""

import json
import logging
import os
import ssl
import urllib3
from typing import List, Dict, Optional, Any
from dtSpark.llm.base import LLMService
import tiktoken

try:
    from ollama import Client
    import httpx
except ImportError:
    logging.error("ollama module not installed. Please run: pip install ollama")
    raise


class OllamaService(LLMService):
    """Manages interactions with local Ollama instance using official ollama SDK."""

    def __init__(self, base_url: str = "http://localhost:11434", verify_ssl: bool = True):
        """
        Initialise the Ollama service.

        Args:
            base_url: Base URL for Ollama API
            verify_ssl: Whether to verify SSL certificates (set to False for self-signed certs)
        """
        self.base_url = base_url.rstrip('/')
        self.verify_ssl = verify_ssl
        self._ssl_warnings_disabled = False

        # Handle SSL verification settings and create client
        if not verify_ssl:
            logging.info(f"SSL certificate verification disabled for Ollama at {self.base_url}")
            self._disable_ssl_verification()
            self.client = self._create_client_with_ssl_disabled()
        else:
            self.client = Client(host=self.base_url)

        self.current_model_id = None
        self._verify_connection()

    def _disable_ssl_verification(self):
        """
        Disable SSL certificate verification for httpx/urllib3.

        This is necessary when connecting to Ollama instances with self-signed certificates.
        """
        # Suppress InsecureRequestWarning from urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._ssl_warnings_disabled = True

        # Create an unverified SSL context
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
        except AttributeError:
            # Legacy Python that doesn't support this
            pass

    def _create_client_with_ssl_disabled(self) -> Client:
        """
        Create an Ollama client with SSL verification disabled.

        This creates a custom httpx client and injects it into the Ollama client.
        """
        # Ensure base_url has trailing slash for httpx base_url
        base_url = self.base_url
        if not base_url.endswith('/'):
            base_url = base_url + '/'

        # Create httpx client with SSL verification disabled and proper base URL
        # SSL verification is intentionally disabled here - controlled by verify_ssl constructor parameter
        # which is set from user configuration (for self-signed certificates on local Ollama instances)
        custom_http_client = httpx.Client(
            base_url=base_url,
            verify=False,  # NOSONAR - intentional, gated by verify_ssl config
            timeout=httpx.Timeout(timeout=120.0)
        )

        # Create the Ollama client
        client = Client(host=self.base_url)

        # Monkey-patch the internal httpx client
        # The ollama SDK stores the client as _client
        if hasattr(client, '_client'):
            # Close the original client to free resources
            try:
                client._client.close()
            except Exception:
                pass
            client._client = custom_http_client
        else:
            # Fallback: try to find and replace the httpx client
            for attr_name in dir(client):
                attr = getattr(client, attr_name, None)
                if isinstance(attr, httpx.Client):
                    try:
                        attr.close()
                    except Exception:
                        pass
                    setattr(client, attr_name, custom_http_client)
                    break

        return client

    def _verify_connection(self):
        """Verify connection to Ollama instance."""
        try:
            self.client.list()
            logging.info(f"Connected to Ollama at {self.base_url}")
        except Exception as e:
            logging.warning(f"Cannot connect to Ollama at {self.base_url}: {e}")

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "Ollama"

    def get_access_info(self) -> str:
        """Get access information."""
        return f"Ollama ({self.base_url})"

    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List all available models from Ollama.

        Returns:
            List of model dictionaries
        """
        try:
            response = self.client.list()

            models = []
            # Handle both SDK response objects and dict responses
            if hasattr(response, 'models'):
                # SDK response object with attributes
                model_list = response.models
            else:
                # Dict response (for backward compatibility)
                model_list = response.get('models', [])

            for model in model_list:
                # Handle both SDK model objects and dict models
                if hasattr(model, 'model'):
                    # SDK model object
                    model_name = model.model
                    model_size = model.size if hasattr(model, 'size') else 0
                    model_modified = model.modified_at if hasattr(model, 'modified_at') else ''
                else:
                    # Dict model
                    model_name = model.get('name', '')
                    model_size = model.get('size', 0)
                    model_modified = model.get('modified_at', '')

                # Determine tool support based on model capabilities
                supports_tools = self._check_tool_support(model_name)

                models.append({
                    'id': model_name,
                    'name': model_name,
                    'provider': 'Ollama',
                    'access_info': self.get_access_info(),
                    'supports_tools': supports_tools,
                    'context_length': self._get_context_length(model_name),
                    'size': model_size,
                    'modified': model_modified
                })

            logging.info(f"Found {len(models)} Ollama models")
            return models

        except Exception as e:
            logging.error(f"Failed to list Ollama models: {e}")
            return []

    def _check_tool_support(self, model_name: str) -> bool:
        """
        Check if a model supports tool calling.

        Args:
            model_name: Name of the model

        Returns:
            True if model likely supports tools
        """
        # Models known to support function calling
        tool_capable_models = [
            'llama3.2', 'llama3.1', 'llama3',
            'mistral', 'mixtral',
            'qwen2.5', 'qwen2',
            'command-r',
        ]

        model_lower = model_name.lower()
        return any(capable in model_lower for capable in tool_capable_models)

    def _get_context_length(self, model_name: str) -> int:
        """
        Get context length for a model.

        Args:
            model_name: Name of the model

        Returns:
            Context length in tokens
        """
        # Common context lengths
        if 'llama3.2' in model_name.lower():
            return 128000
        elif 'llama3.1' in model_name.lower():
            return 128000
        elif 'mistral' in model_name.lower():
            return 32000
        else:
            return 8192  # Default

    def set_model(self, model_id: str):
        """Set the active Ollama model."""
        self.current_model_id = model_id
        logging.info(f"Ollama model set to: {model_id}")

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
        Invoke Ollama model with conversation.

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
                'error_message': 'No Ollama model selected',
                'error_type': 'ConfigurationError'
            }

        try:
            # Convert messages from Bedrock format to Ollama format
            ollama_messages = self._convert_messages_to_ollama(messages)

            # Add system message if provided
            if system:
                ollama_messages.insert(0, {
                    'role': 'system',
                    'content': system
                })

            # Build chat options
            chat_options = {
                'temperature': temperature,
                'num_predict': max_tokens
            }

            logging.debug(f"Invoking Ollama model: {self.current_model_id}")

            # Use ollama SDK to make the chat request
            if tools and self._check_tool_support(self.current_model_id):
                # Convert tools to Ollama format
                ollama_tools = self._convert_tools_to_ollama(tools)
                response = self.client.chat(
                    model=self.current_model_id,
                    messages=ollama_messages,
                    tools=ollama_tools,
                    options=chat_options
                )
            else:
                response = self.client.chat(
                    model=self.current_model_id,
                    messages=ollama_messages,
                    options=chat_options
                )

            # Convert response to standard format
            return self._convert_response_from_ollama(response)

        except Exception as e:
            logging.error(f"Ollama API error: {e}")
            return {
                'error': True,
                'error_code': 'OllamaAPIError',
                'error_message': str(e),
                'error_type': 'RequestError'
            }

    def _convert_messages_to_ollama(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert Bedrock message format to Ollama format.

        Bedrock format:
        {
            'role': 'user',
            'content': [{'text': '...'}] or [{'type': 'tool_use', ...}]
        }

        Ollama format:
        {
            'role': 'user',
            'content': '...',
            'tool_calls': [...]  # For assistant messages with tool use
        }
        """
        ollama_messages = []
        # Build a lookup map of tool_use_id -> tool_name for tool result matching
        tool_id_to_name = {}

        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', [])

            # Handle different content formats
            if isinstance(content, str):
                ollama_messages.append({
                    'role': role,
                    'content': content
                })
            elif isinstance(content, list):
                # Extract text and tool blocks
                text_parts = []
                tool_use_blocks = []
                tool_result_blocks = []

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get('type')

                        if block_type == 'text' or 'text' in block:
                            text_parts.append(block.get('text', ''))
                        elif block_type == 'tool_use':
                            tool_use_blocks.append(block)
                        elif block_type == 'tool_result':
                            tool_result_blocks.append(block)
                    elif isinstance(block, str):
                        text_parts.append(block)

                # Build message based on content
                if role == 'assistant' and tool_use_blocks:
                    # Assistant message with tool calls
                    ollama_msg = {
                        'role': 'assistant',
                        'content': '\n'.join(text_parts) if text_parts else '',
                        'tool_calls': []
                    }

                    # Convert tool_use blocks to Ollama tool_calls format
                    # Also build mapping of tool_id -> tool_name for later tool result matching
                    for tool_block in tool_use_blocks:
                        tool_id = tool_block.get('id', '')
                        tool_name = tool_block.get('name', '')

                        # Store mapping for tool results
                        if tool_id and tool_name:
                            tool_id_to_name[tool_id] = tool_name

                        ollama_msg['tool_calls'].append({
                            'id': tool_id,
                            'type': 'function',
                            'function': {
                                'name': tool_name,
                                'arguments': tool_block.get('input', {})
                            }
                        })

                    ollama_messages.append(ollama_msg)

                elif role == 'user' and tool_result_blocks:
                    # Convert tool results to Ollama SDK format using "tool" role
                    # Ollama SDK requires 'tool_name' field (not 'tool_call_id')
                    for result_block in tool_result_blocks:
                        tool_use_id = result_block.get('tool_use_id', '')
                        tool_name = tool_id_to_name.get(tool_use_id, 'unknown_tool')

                        ollama_messages.append({
                            'role': 'tool',
                            'tool_name': tool_name,
                            'content': result_block.get('content', '')
                        })

                    # If there's also regular text content, include that as user message
                    if text_parts:
                        ollama_messages.append({
                            'role': 'user',
                            'content': '\n'.join(text_parts)
                        })
                else:
                    # Regular message with just text
                    text = '\n'.join(text_parts) if text_parts else ''
                    ollama_messages.append({
                        'role': role,
                        'content': text
                    })
            else:
                ollama_messages.append({
                    'role': role,
                    'content': str(content)
                })

        return ollama_messages

    def _convert_tools_to_ollama(
        self,
        tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert Bedrock tool format to Ollama format.

        Ollama uses OpenAI-compatible function calling format.
        """
        ollama_tools = []

        for tool in tools:
            # Bedrock tools have 'toolSpec' wrapping
            tool_spec = tool.get('toolSpec', tool)

            ollama_tools.append({
                'type': 'function',
                'function': {
                    'name': tool_spec.get('name', ''),
                    'description': tool_spec.get('description', ''),
                    'parameters': tool_spec.get('inputSchema', {})
                }
            })

        return ollama_tools

    def _convert_response_from_ollama(
        self,
        ollama_response: Any
    ) -> Dict[str, Any]:
        """
        Convert Ollama SDK response to standard format.

        ollama SDK response has attributes:
        - message: with .content, .tool_calls, etc.
        - done: boolean
        """
        # Handle both SDK response objects and dict (for backward compatibility)
        if hasattr(ollama_response, 'message'):
            # SDK response object
            message = ollama_response.message
            content = message.content if hasattr(message, 'content') else ''
            tool_calls = message.tool_calls if hasattr(message, 'tool_calls') else []
            done = ollama_response.done if hasattr(ollama_response, 'done') else True
        else:
            # Dict response (backward compatibility for tests)
            message = ollama_response.get('message', {})
            content = message.get('content', '')
            tool_calls = message.get('tool_calls', [])
            done = ollama_response.get('done', True)

        # Estimate token usage (Ollama doesn't always provide this)
        input_tokens = self.count_tokens(str(ollama_response))
        output_tokens = self.count_tokens(content if content else '')

        # Build standard response format
        response = {
            'stop_reason': 'end_turn' if done else 'max_tokens',
            'usage': {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens
            }
        }

        # Handle content - build content_blocks array like Bedrock
        content_blocks = []

        if tool_calls:
            tool_use_blocks = self._convert_tool_calls(tool_calls)
            response['tool_use'] = tool_use_blocks
            response['stop_reason'] = 'tool_use'

            # Build content_blocks with text (if any) followed by tool calls
            if content:
                # Model provided both text and tool calls
                content_blocks.append({'type': 'text', 'text': content})
            # Add tool use blocks
            content_blocks.extend(tool_use_blocks)
        else:
            # No tool calls, just text content
            if content:
                content_blocks.append({'type': 'text', 'text': content})

        # Return both formats for compatibility:
        # - content: string (for backward compatibility and text extraction)
        # - content_blocks: array (for conversation manager)
        response['content'] = content
        response['content_blocks'] = content_blocks

        return response

    def _convert_tool_calls(
        self,
        tool_calls: List[Any]
    ) -> List[Dict[str, Any]]:
        """Convert Ollama SDK tool calls to standard format."""
        converted = []

        for call in tool_calls:
            # Handle both SDK objects and dicts (for backward compatibility)
            if hasattr(call, 'function'):
                # SDK response object
                function = call.function
                call_id = call.id if hasattr(call, 'id') else ''
                func_name = function.name if hasattr(function, 'name') else ''
                arguments = function.arguments if hasattr(function, 'arguments') else {}
            else:
                # Dict response (backward compatibility)
                function = call.get('function', {})
                call_id = call.get('id', '')
                func_name = function.get('name', '')
                arguments = function.get('arguments', '{}')

            # Handle arguments - can be dict or string
            if isinstance(arguments, str):
                # Parse JSON string
                arguments_dict = json.loads(arguments)
            elif isinstance(arguments, dict):
                # Already a dict
                arguments_dict = arguments
            else:
                # Default to empty dict
                arguments_dict = {}

            converted.append({
                'type': 'tool_use',
                'id': call_id,
                'name': func_name,
                'input': arguments_dict
            })

        return converted

    def supports_streaming(self) -> bool:
        """Check if Ollama supports streaming."""
        return True  # Ollama supports streaming, but not implemented yet

    def count_tokens(self, text: str) -> int:
        """
        Count tokens using tiktoken (approximation for Ollama models).

        Args:
            text: Text to count tokens for

        Returns:
            Approximate token count
        """
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception as e:
            logging.warning(f"Token counting failed: {e}")
            # Fallback: rough estimate of 4 chars per token
            return len(text) // 4
