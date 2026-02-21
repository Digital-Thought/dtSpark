"""
Google Gemini LLM service provider.

This module provides integration with Google's Gemini API for LLM inference,
supporting text generation and function/tool calling capabilities.
"""

import json
import logging
import os
import time
from typing import List, Dict, Optional, Any

from .base import LLMService


class GoogleGeminiService(LLMService):
    """Google Gemini API service provider."""

    # Model specifications: pricing (per million tokens), context window, max output
    MODEL_SPECS = {
        # Gemini 3 series
        'gemini-3-pro': {'input': 1.25, 'output': 5.00, 'context': 1000000, 'max_output': 65536},
        'gemini-3-flash': {'input': 0.10, 'output': 0.40, 'context': 1000000, 'max_output': 65536},
        'gemini-3.1-pro': {'input': 1.25, 'output': 5.00, 'context': 1000000, 'max_output': 65536},
        # Gemini 2.5 series
        'gemini-2.5-pro': {'input': 1.25, 'output': 5.00, 'context': 1000000, 'max_output': 65536},
        'gemini-2.5-flash': {'input': 0.075, 'output': 0.30, 'context': 1000000, 'max_output': 65536},
        'gemini-2.5-flash-lite': {'input': 0.025, 'output': 0.10, 'context': 1000000, 'max_output': 65536},
        # Gemini 2.0 series
        'gemini-2.0-flash': {'input': 0.10, 'output': 0.40, 'context': 1000000, 'max_output': 8192},
        'gemini-2.0-flash-lite': {'input': 0.025, 'output': 0.10, 'context': 1000000, 'max_output': 8192},
        # Gemini 1.5 series (legacy)
        'gemini-1.5-pro': {'input': 1.25, 'output': 5.00, 'context': 2000000, 'max_output': 8192},
        'gemini-1.5-flash': {'input': 0.075, 'output': 0.30, 'context': 1000000, 'max_output': 8192},
        # Default for unknown models
        'default': {'input': 0.50, 'output': 2.00, 'context': 1000000, 'max_output': 8192}
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_max_tokens: int = 8192,
        rate_limit_max_retries: int = 5,
        rate_limit_base_delay: float = 2.0
    ):
        """
        Initialise the Google Gemini service.

        Args:
            api_key: Google API key (or use GEMINI_API_KEY or GOOGLE_API_KEY env var)
            default_max_tokens: Default maximum tokens to request
            rate_limit_max_retries: Maximum retries for rate limit errors
            rate_limit_base_delay: Base delay for exponential backoff
        """
        self.api_key = api_key or os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Google API key required. Set via parameter or GEMINI_API_KEY/GOOGLE_API_KEY env var"
            )

        self.default_max_tokens = default_max_tokens
        self.rate_limit_max_retries = rate_limit_max_retries
        self.rate_limit_base_delay = rate_limit_base_delay
        self.current_model_id = None

        # Initialise the Google GenAI client
        try:
            from google import genai
            self.genai = genai
            self.client = genai.Client(api_key=self.api_key)
            logging.info("Google Gemini client initialised successfully")
        except ImportError:
            raise ImportError(
                "google-genai package required. Install with: pip install google-genai"
            )
        except Exception as e:
            raise ValueError(f"Failed to initialise Google Gemini client: {e}")

    def get_provider_name(self) -> str:
        """Get the provider name."""
        return "Google Gemini"

    def get_access_info(self) -> str:
        """Get access information."""
        return "Google AI API"

    def _get_model_spec(self, model_id: str) -> Dict[str, Any]:
        """
        Get specifications for a model by matching ID pattern.

        Args:
            model_id: Full model ID

        Returns:
            Dictionary with pricing, context, and max_output
        """
        if not model_id:
            return self.MODEL_SPECS['default']

        # Normalise model ID for matching
        model_lower = model_id.lower()

        # Try exact match first
        for pattern, spec in self.MODEL_SPECS.items():
            if pattern == model_lower or pattern in model_lower:
                return spec

        logging.warning(f"No specs found for model {model_id}, using defaults")
        return self.MODEL_SPECS['default']

    def get_model_max_tokens(self, model_id: str) -> int:
        """
        Get the maximum output tokens for a specific model.

        Args:
            model_id: The model ID to look up

        Returns:
            Maximum output tokens for the model
        """
        specs = self._get_model_spec(model_id)
        return specs['max_output']

    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List all available Gemini models.

        Returns:
            List of model dictionaries
        """
        models = []

        try:
            # Fetch models from Google API
            response = self.client.models.list()

            for model in response:
                model_id = model.name if hasattr(model, 'name') else str(model)

                # Skip non-generative models
                if 'embedding' in model_id.lower() or 'aqa' in model_id.lower():
                    continue

                # Get specs for this model
                specs = self._get_model_spec(model_id)

                # Determine display name
                display_name = model.display_name if hasattr(model, 'display_name') else model_id

                models.append({
                    'id': model_id,
                    'name': display_name,
                    'provider': self.get_provider_name(),
                    'access_info': self.get_access_info(),
                    'supports_tools': True,  # All Gemini models support function calling
                    'context_length': specs['context'],
                    'max_output': specs['max_output'],
                    'pricing': {
                        'input': specs['input'],
                        'output': specs['output']
                    }
                })

            logging.info(f"Found {len(models)} Google Gemini models from API")

        except Exception as e:
            logging.warning(f"Failed to list models from API: {e}")
            # Return hardcoded list as fallback
            for model_id, specs in self.MODEL_SPECS.items():
                if model_id == 'default':
                    continue
                models.append({
                    'id': f"models/{model_id}",
                    'name': model_id.replace('-', ' ').title(),
                    'provider': self.get_provider_name(),
                    'access_info': self.get_access_info(),
                    'supports_tools': True,
                    'context_length': specs['context'],
                    'max_output': specs['max_output'],
                    'pricing': {
                        'input': specs['input'],
                        'output': specs['output']
                    }
                })

        return models

    def set_model(self, model_id: str):
        """
        Set the active model.

        Args:
            model_id: Model identifier to use
        """
        self.current_model_id = model_id
        logging.info(f"Google Gemini model set to: {model_id}")

    def _clean_schema_for_gemini(self, schema: Any) -> Any:
        """
        Recursively clean a JSON schema for Gemini API compatibility.

        Gemini's API doesn't support certain JSON Schema fields like:
        - additionalProperties
        - $schema
        - $defs / definitions
        - $ref
        - $id
        - default (in some contexts)
        - examples
        - etc.

        Additionally, Gemini requires:
        - All 'items' definitions must have a 'type' field
        - Nested items must be properly structured

        Args:
            schema: JSON schema object to clean

        Returns:
            Cleaned schema safe for Gemini API
        """
        # Fields that Gemini's API doesn't support
        unsupported_fields = {
            'additionalProperties',
            'additional_properties',  # Snake case variant
            '$schema',
            '$defs',
            'definitions',
            '$ref',
            '$id',
            'default',
            'examples',
            'const',
            'contentMediaType',
            'contentEncoding',
            'deprecated',
            'readOnly',
            'writeOnly',
            'externalDocs',
            '$comment',
            'if',
            'then',
            'else',
            'allOf',
            'anyOf',
            'oneOf',
            'not',
            'patternProperties',
            'unevaluatedProperties',
            'unevaluatedItems',
            'propertyNames',
            'minContains',
            'maxContains',
            'dependentRequired',
            'dependentSchemas',
        }

        if isinstance(schema, dict):
            cleaned = {}
            for key, value in schema.items():
                # Skip unsupported fields
                if key in unsupported_fields:
                    logging.debug(f"Stripping unsupported schema field: {key}")
                    continue

                # Recursively clean nested structures
                cleaned_value = self._clean_schema_for_gemini(value)

                # Special handling for 'items' - must have a type
                if key == 'items' and isinstance(cleaned_value, dict):
                    cleaned_value = self._ensure_valid_items_schema(cleaned_value)

                cleaned[key] = cleaned_value

            return cleaned

        elif isinstance(schema, list):
            return [self._clean_schema_for_gemini(item) for item in schema]

        else:
            # Primitive values pass through unchanged
            return schema

    def _ensure_valid_items_schema(self, items_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure an 'items' schema has all required fields for Gemini.

        Gemini requires 'items' to have a 'type' field. If missing, we add
        a sensible default based on the schema structure.

        Args:
            items_schema: The items schema to validate/fix

        Returns:
            Valid items schema
        """
        if not isinstance(items_schema, dict):
            return items_schema

        # If items is empty or only has 'items' (malformed), fix it
        if not items_schema:
            logging.debug("Empty items schema, defaulting to string type")
            return {'type': 'string'}

        # If items has nested 'items' without type, it's likely a malformed array
        if 'items' in items_schema and 'type' not in items_schema:
            # Check if the nested items is also problematic
            nested_items = items_schema.get('items')
            if isinstance(nested_items, dict):
                if not nested_items or 'type' not in nested_items:
                    # Remove malformed nested items and treat as simple array
                    logging.debug("Removing malformed nested items schema")
                    items_schema = {k: v for k, v in items_schema.items() if k != 'items'}
                    if 'type' not in items_schema:
                        items_schema['type'] = 'string'

        # If still no type, infer from structure
        if 'type' not in items_schema:
            if 'properties' in items_schema:
                items_schema['type'] = 'object'
            elif 'items' in items_schema:
                items_schema['type'] = 'array'
            else:
                # Default to string for unknown schemas
                items_schema['type'] = 'string'
                logging.debug("Items schema missing type, defaulting to string")

        # Recursively fix nested items
        if 'items' in items_schema and isinstance(items_schema['items'], dict):
            items_schema['items'] = self._ensure_valid_items_schema(items_schema['items'])

        # Also check properties for nested items schemas
        if 'properties' in items_schema and isinstance(items_schema['properties'], dict):
            for prop_name, prop_schema in items_schema['properties'].items():
                if isinstance(prop_schema, dict) and 'items' in prop_schema:
                    prop_schema['items'] = self._ensure_valid_items_schema(prop_schema['items'])

        return items_schema

    def _convert_tools_to_gemini_format(
        self,
        tools: List[Dict[str, Any]]
    ) -> List[Any]:
        """
        Convert tools from standard format to Gemini's function declaration format.

        Args:
            tools: List of tool definitions in standard format

        Returns:
            List of Gemini Tool objects
        """
        from google.genai import types

        function_declarations = []

        for tool in tools:
            # Extract tool spec (handle various formats)
            if 'toolSpec' in tool:
                spec = tool['toolSpec']
            elif 'function' in tool:
                spec = tool['function']
            else:
                spec = tool

            name = spec.get('name', '')
            description = spec.get('description', '')

            # Get parameters/input schema
            parameters = None
            if 'inputSchema' in spec:
                parameters = spec['inputSchema']
            elif 'input_schema' in spec:
                parameters = spec['input_schema']
            elif 'parameters' in spec:
                parameters = spec['parameters']

            # Build function declaration
            func_decl = {
                'name': name,
                'description': description
            }

            if parameters:
                # Clean the schema for Gemini compatibility
                cleaned_parameters = self._clean_schema_for_gemini(parameters)
                # Ensure proper format for Gemini
                if 'type' not in cleaned_parameters:
                    cleaned_parameters['type'] = 'object'
                func_decl['parameters'] = cleaned_parameters

            function_declarations.append(func_decl)

        if function_declarations:
            return [types.Tool(function_declarations=function_declarations)]
        return []

    def _convert_messages_to_gemini_format(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None
    ) -> tuple:
        """
        Convert messages from standard format to Gemini's content format.

        Args:
            messages: List of messages in standard format
            system: Optional system prompt

        Returns:
            Tuple of (contents list, system instruction)
        """
        contents = []

        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')

            # Map roles
            if role == 'assistant':
                gemini_role = 'model'
            elif role == 'user':
                gemini_role = 'user'
            else:
                gemini_role = 'user'  # Default to user for unknown roles

            # Handle different content types
            if isinstance(content, str):
                contents.append({
                    'role': gemini_role,
                    'parts': [{'text': content}]
                })
            elif isinstance(content, list):
                # Handle content blocks (text, tool_use, tool_result)
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get('type', '')

                        if block_type == 'text':
                            parts.append({'text': block.get('text', '')})

                        elif block_type == 'tool_use':
                            # Convert to Gemini function call format
                            parts.append({
                                'function_call': {
                                    'name': block.get('name', ''),
                                    'args': block.get('input', {})
                                }
                            })

                        elif block_type == 'tool_result':
                            # Convert to Gemini function response format
                            result_content = block.get('content', '')
                            if isinstance(result_content, list):
                                # Extract text from content blocks
                                result_text = ''
                                for item in result_content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        result_text += item.get('text', '')
                                    elif isinstance(item, str):
                                        result_text += item
                                result_content = result_text

                            parts.append({
                                'function_response': {
                                    'name': block.get('tool_use_id', 'unknown'),
                                    'response': {'result': str(result_content)}
                                }
                            })
                    elif isinstance(block, str):
                        parts.append({'text': block})

                if parts:
                    contents.append({
                        'role': gemini_role,
                        'parts': parts
                    })

        return contents, system

    def _build_web_search_tool(
        self,
        web_search_config: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Build a Google Search grounding tool based on configuration.

        Args:
            web_search_config: Web search configuration dictionary

        Returns:
            Google Search tool object or None
        """
        from google.genai import types

        try:
            # Determine which API to use based on model version
            model_lower = (self.current_model_id or '').lower()
            is_gemini_15 = '1.5' in model_lower

            if is_gemini_15:
                # Use GoogleSearchRetrieval for Gemini 1.5 models
                # This supports dynamic_retrieval_config
                dynamic_threshold = web_search_config.get('dynamic_threshold', 0.3)

                return types.Tool(
                    google_search_retrieval=types.GoogleSearchRetrieval(
                        dynamic_retrieval_config=types.DynamicRetrievalConfig(
                            dynamic_threshold=float(dynamic_threshold)
                        )
                    )
                )
            else:
                # Use GoogleSearch for Gemini 2.0+ models
                exclude_domains = web_search_config.get('exclude_domains', [])

                if exclude_domains:
                    return types.Tool(
                        google_search=types.GoogleSearch(
                            exclude_domains=exclude_domains
                        )
                    )
                else:
                    return types.Tool(
                        google_search=types.GoogleSearch()
                    )

        except Exception as e:
            logging.error(f"Failed to build web search tool: {e}")
            return None

    def _is_web_search_supported(self) -> bool:
        """
        Check if web search (grounding) is supported for the current model.

        Returns:
            True if web search is supported
        """
        if not self.current_model_id:
            return False

        model_lower = self.current_model_id.lower()

        # Web search is supported on Gemini 1.5+ models
        supported_patterns = ['gemini-1.5', 'gemini-2', 'gemini-3']
        return any(pattern in model_lower for pattern in supported_patterns)

    def supports_web_search(self) -> bool:
        """
        Public method to check if web search is supported.

        Returns:
            True if web search grounding is available
        """
        return self._is_web_search_supported()

    def invoke_model(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_retries: int = 3,
        web_search_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Invoke the Gemini model with a conversation.

        Args:
            messages: Conversation messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            tools: Optional tool definitions
            system: Optional system prompt
            max_retries: Maximum retry attempts
            web_search_config: Optional web search (grounding) configuration

        Returns:
            Response dictionary or error dictionary
        """
        if not self.current_model_id:
            return {
                'error': True,
                'error_code': 'NoModelSelected',
                'error_message': 'No model selected. Call set_model() first.',
                'error_type': 'ConfigurationError'
            }

        try:
            from google.genai import types

            # Convert messages to Gemini format
            contents, system_instruction = self._convert_messages_to_gemini_format(
                messages, system
            )

            # Build generation config
            model_max = self.get_model_max_tokens(self.current_model_id)
            actual_max_tokens = min(max_tokens, model_max) if max_tokens else self.default_max_tokens

            generation_config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=actual_max_tokens
            )

            # Add system instruction if provided
            if system_instruction:
                generation_config.system_instruction = system_instruction

            # Build tools list
            all_tools = []

            # Add web search (grounding) tool if enabled
            if web_search_config and web_search_config.get('enabled'):
                web_search_tool = self._build_web_search_tool(web_search_config)
                if web_search_tool:
                    all_tools.append(web_search_tool)
                    logging.info("Google Search grounding enabled for this request")

            # Add regular tools if provided
            if tools:
                gemini_tools = self._convert_tools_to_gemini_format(tools)
                all_tools.extend(gemini_tools)

            # Set tools in config
            if all_tools:
                generation_config.tools = all_tools

            # Make API call with retry logic
            response = None
            last_error = None

            for retry_attempt in range(self.rate_limit_max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.current_model_id,
                        contents=contents,
                        config=generation_config
                    )
                    break  # Success, exit retry loop

                except Exception as e:
                    error_str = str(e).lower()
                    last_error = e

                    # Check for rate limit errors
                    if 'rate' in error_str or 'quota' in error_str or '429' in error_str:
                        if retry_attempt < self.rate_limit_max_retries - 1:
                            wait_time = self.rate_limit_base_delay ** retry_attempt
                            logging.warning(
                                f"Rate limit hit, waiting {wait_time:.1f}s "
                                f"(attempt {retry_attempt + 1}/{self.rate_limit_max_retries})"
                            )
                            time.sleep(wait_time)
                            continue

                    # Re-raise non-rate-limit errors
                    raise

            if response is None:
                return {
                    'error': True,
                    'error_code': 'RateLimitExceeded',
                    'error_message': f'Rate limit exceeded after {self.rate_limit_max_retries} retries: {last_error}',
                    'error_type': 'RetryError'
                }

            # Process response
            return self._process_response(response)

        except Exception as e:
            logging.error(f"Google Gemini API error: {e}")
            return {
                'error': True,
                'error_code': 'GoogleGeminiError',
                'error_message': str(e),
                'error_type': 'APIError'
            }

    def _process_response(self, response) -> Dict[str, Any]:
        """
        Process the Gemini API response into standard format.

        Args:
            response: Raw API response

        Returns:
            Standardised response dictionary
        """
        content_blocks = []
        tool_use_blocks = []
        text_parts = []
        stop_reason = 'end_turn'
        grounding_metadata = None

        # Extract usage info
        usage_info = {
            'input_tokens': 0,
            'output_tokens': 0
        }

        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            if hasattr(usage, 'prompt_token_count'):
                usage_info['input_tokens'] = usage.prompt_token_count
            if hasattr(usage, 'candidates_token_count'):
                usage_info['output_tokens'] = usage.candidates_token_count

        # Process candidates
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]

            # Get finish reason
            if hasattr(candidate, 'finish_reason'):
                finish_reason = str(candidate.finish_reason).lower()
                if 'stop' in finish_reason:
                    stop_reason = 'end_turn'
                elif 'max_tokens' in finish_reason or 'length' in finish_reason:
                    stop_reason = 'max_tokens'
                elif 'safety' in finish_reason:
                    stop_reason = 'safety'

            # Process content parts
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    # Text content
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                        content_blocks.append({
                            'type': 'text',
                            'text': part.text
                        })

                    # Function call
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        tool_block = {
                            'type': 'tool_use',
                            'id': f"call_{hash(fc.name) % 10000:04d}_{int(time.time() * 1000) % 10000:04d}",
                            'name': fc.name,
                            'input': dict(fc.args) if hasattr(fc.args, 'items') else fc.args
                        }
                        tool_use_blocks.append(tool_block)
                        content_blocks.append(tool_block)
                        stop_reason = 'tool_use'

            # Extract grounding metadata (web search results)
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                grounding_metadata = self._extract_grounding_metadata(candidate.grounding_metadata)

        # Build response
        result = {
            'content': ''.join(text_parts),
            'content_blocks': content_blocks,
            'stop_reason': stop_reason,
            'usage': usage_info
        }

        if tool_use_blocks:
            result['tool_use'] = tool_use_blocks

        if grounding_metadata:
            result['grounding_metadata'] = grounding_metadata
            # Track search queries count for usage reporting
            if 'search_queries' in grounding_metadata:
                usage_info['web_search_queries'] = len(grounding_metadata['search_queries'])
                logging.info(f"Google Search queries: {len(grounding_metadata['search_queries'])}")

        return result

    def _extract_grounding_metadata(self, metadata) -> Dict[str, Any]:
        """
        Extract grounding metadata from Gemini response.

        Args:
            metadata: Grounding metadata from the API response

        Returns:
            Structured grounding metadata dictionary
        """
        result = {}

        try:
            # Extract search queries
            if hasattr(metadata, 'web_search_queries') and metadata.web_search_queries:
                result['search_queries'] = list(metadata.web_search_queries)

            # Extract grounding chunks (sources)
            if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                sources = []
                for chunk in metadata.grounding_chunks:
                    source = {}
                    if hasattr(chunk, 'web') and chunk.web:
                        if hasattr(chunk.web, 'uri'):
                            source['url'] = chunk.web.uri
                        if hasattr(chunk.web, 'title'):
                            source['title'] = chunk.web.title
                    if source:
                        sources.append(source)
                if sources:
                    result['sources'] = sources

            # Extract grounding supports (text spans linked to sources)
            if hasattr(metadata, 'grounding_supports') and metadata.grounding_supports:
                supports = []
                for support in metadata.grounding_supports:
                    support_info = {}
                    if hasattr(support, 'segment') and support.segment:
                        if hasattr(support.segment, 'text'):
                            support_info['text'] = support.segment.text
                    if hasattr(support, 'grounding_chunk_indices'):
                        support_info['chunk_indices'] = list(support.grounding_chunk_indices)
                    if support_info:
                        supports.append(support_info)
                if supports:
                    result['supports'] = supports

            # Extract search entry point (rendered HTML for display)
            if hasattr(metadata, 'search_entry_point') and metadata.search_entry_point:
                if hasattr(metadata.search_entry_point, 'rendered_content'):
                    result['rendered_content'] = metadata.search_entry_point.rendered_content

        except Exception as e:
            logging.warning(f"Error extracting grounding metadata: {e}")

        return result

    def supports_streaming(self) -> bool:
        """Check if streaming is supported."""
        return True  # Gemini supports streaming

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        try:
            # Use Gemini's token counting API
            if self.current_model_id:
                response = self.client.models.count_tokens(
                    model=self.current_model_id,
                    contents=text
                )
                if hasattr(response, 'total_tokens'):
                    return response.total_tokens
        except Exception as e:
            logging.debug(f"Token counting failed, using estimate: {e}")

        # Fallback to estimate (roughly 4 characters per token)
        return len(text) // 4

    def get_rate_limits(self) -> Dict[str, Any]:
        """
        Get rate limit information.

        Returns:
            Rate limit dictionary
        """
        # Google Gemini rate limits vary by tier
        # Free tier: 15 RPM, 1M TPM, 1500 RPD
        # Pay-as-you-go: Higher limits
        return {
            'input_tokens_per_minute': 1000000,  # 1M TPM for free tier
            'output_tokens_per_minute': None,
            'requests_per_minute': 15,  # Free tier limit
            'has_limits': True
        }
