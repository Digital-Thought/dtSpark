"""
Bedrock service module for interacting with AWS Bedrock models.

This module provides functionality for:
- Listing available Bedrock foundation models
- Invoking models for chat completions
- Handling model-specific message formatting
"""

import json
import logging
from typing import List, Dict, Optional, Any
from botocore.exceptions import ClientError
import tiktoken

from dtSpark.llm.base import LLMService


class BedrockService(LLMService):
    """Manages interactions with AWS Bedrock foundation models."""

    def __init__(self, bedrock_client, bedrock_runtime_client):
        """
        Initialise the Bedrock service.

        Args:
            bedrock_client: Boto3 Bedrock client for control plane operations
            bedrock_runtime_client: Boto3 Bedrock Runtime client for inference
        """
        self.bedrock_client = bedrock_client
        self.bedrock_runtime_client = bedrock_runtime_client
        self.current_model_id = None
        self.is_inference_profile = False
        self.model_identifier = None

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "AWS Bedrock"

    def get_access_info(self) -> str:
        """Get access information."""
        return "AWS Bedrock"

    def supports_streaming(self) -> bool:
        """Check if streaming is supported."""
        return False  # Not currently implemented

    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List all available Bedrock inference profiles.

        Note: Only inference profiles are shown as they are the recommended
        and supported way to invoke models, especially newer models like Claude Sonnet 4.

        Returns:
            List of inference profile dictionaries with id, name, and provider information
        """
        models = []

        try:
            response = self.bedrock_client.list_inference_profiles()

            for profile in response.get('inferenceProfileSummaries', []):
                if profile.get('status') != 'ACTIVE':
                    continue

                profile_models = profile.get('models', [])
                model_id = profile_models[0].get('modelArn', '').split('/')[-1] if profile_models else 'unknown'

                if self._should_skip_profile(profile, model_id):
                    continue

                if not self._verify_model_access(profile, profile_models):
                    continue

                model_maker = self._detect_model_maker(model_id, profile['inferenceProfileName'])

                models.append({
                    'id': profile['inferenceProfileArn'],
                    'name': profile['inferenceProfileName'],
                    'model_maker': model_maker,
                    'access_info': self.get_access_info(),
                    'input_modalities': ['TEXT'],
                    'output_modalities': ['TEXT'],
                    'response_streaming': True,
                    'type': 'profile'
                })

            logging.info(f"Found {len(models)} active inference profiles")

        except ClientError as e:
            logging.error(f"Failed to list inference profiles: {e}")
        except Exception as e:
            logging.error(f"Unexpected error listing inference profiles: {e}")

        models.sort(key=lambda x: (x.get('model_maker', 'Unknown'), x['name']))
        logging.info(f"Total available models: {len(models)}")
        return models

    @staticmethod
    def _should_skip_profile(profile: Dict[str, Any], model_id: str) -> bool:
        """Check whether an inference profile should be excluded from the model list."""
        profile_name_lower = profile['inferenceProfileName'].lower()
        model_id_lower = model_id.lower()

        if 'embed' in profile_name_lower or 'embed' in model_id_lower:
            logging.debug(f"Skipping embedding model: {profile['inferenceProfileName']}")
            return True

        if 'stable-diffusion' in profile_name_lower or 'stable-diffusion' in model_id_lower:
            logging.debug(f"Skipping image generation model: {profile['inferenceProfileName']}")
            return True

        return False

    def _verify_model_access(self, profile: Dict[str, Any], profile_models: List[Dict[str, Any]]) -> bool:
        """Verify that the underlying foundation model is accessible. Returns True if accessible."""
        _NO_ACCESS_CODES = {'AccessDeniedException', 'ValidationException', 'ResourceNotFoundException'}
        try:
            if not profile_models:
                return True
            foundation_model_arn = profile_models[0].get('modelArn', '')
            if not foundation_model_arn:
                return True
            foundation_model_id = foundation_model_arn.split('/')[-1]
            try:
                self.bedrock_client.get_foundation_model(modelIdentifier=foundation_model_id)
            except ClientError as model_error:
                error_code = model_error.response.get('Error', {}).get('Code', '')
                if error_code in _NO_ACCESS_CODES:
                    logging.debug(f"Skipping model without access: {profile['inferenceProfileName']} ({error_code})")
                    return False
                logging.debug(f"Could not verify access for {profile['inferenceProfileName']}: {error_code}")
        except Exception as verify_error:
            logging.debug(f"Error verifying model access for {profile['inferenceProfileName']}: {verify_error}")
            return False
        return True

    @staticmethod
    def _detect_model_maker(model_id: str, profile_name: str) -> str:
        """Determine the model maker from a model ID and profile name."""
        id_lower = model_id.lower()
        name_lower = profile_name.lower()
        maker_keywords = [
            ('Anthropic', ['anthropic', 'claude']),
            ('Amazon', ['amazon', 'titan']),
            ('Meta', ['meta', 'llama']),
            ('AI21', ['ai21', 'jamba']),
            ('Cohere', ['cohere']),
            ('Mistral', ['mistral']),
        ]
        for maker, keywords in maker_keywords:
            if any(kw in id_lower or kw in name_lower for kw in keywords):
                return maker
        return 'Unknown'

    def set_model(self, model_id: str):
        """
        Set the current model for chat operations.

        Args:
            model_id: The Bedrock model ID or inference profile ARN to use
        """
        self.current_model_id = model_id
        # Check if this is an inference profile ARN
        self.is_inference_profile = model_id.startswith('arn:aws:bedrock:')

        # Extract the actual model identifier for format detection
        if self.is_inference_profile:
            # Extract model ID from ARN like: arn:aws:bedrock:region:account:inference-profile/us.anthropic.claude-...
            parts = model_id.split('/')
            if len(parts) > 1:
                # Get the profile identifier (e.g., us.anthropic.claude-sonnet-4-...)
                self.model_identifier = parts[-1]
            else:
                self.model_identifier = model_id
        else:
            self.model_identifier = model_id

        logging.info(f"{'Inference profile' if self.is_inference_profile else 'Model'} set to: {model_id}")

    # Transient error codes that should be retried
    _TRANSIENT_ERRORS = {
        'ThrottlingException',
        'TooManyRequestsException',
        'ModelTimeoutException',
        'ServiceUnavailableException',
        'InternalServerError',
        'ModelNotReadyException',
        'ModelStreamErrorException',
    }

    def invoke_model(self, messages: List[Dict[str, str]], max_tokens: int = 4096,
                    temperature: float = 0.7, tools: Optional[List[Dict[str, Any]]] = None,
                    system: Optional[str] = None, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Invoke the current model or inference profile with a list of messages.
        Includes automatic retry logic for transient failures.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Model temperature (0.0 to 1.0)
            tools: Optional list of tool definitions for the model to use
            system: Optional system prompt/instructions for the model
            max_retries: Maximum number of retry attempts for transient failures

        Returns:
            Response dictionary with content and metadata, or error dictionary on failure
        """
        if not self.current_model_id:
            logging.error("No model selected. Please set a model first.")
            return {
                'error': True,
                'error_code': 'NoModelSelected',
                'error_message': 'No model selected. Please set a model first.',
                'error_type': 'ConfigurationError'
            }

        import time
        attempt = 0

        while attempt <= max_retries:
            if attempt > 1:
                logging.info(f"Retry attempt {attempt}/{max_retries} for model invocation")

            result = self._attempt_invocation(messages, max_tokens, temperature, tools, system, attempt, max_retries)
            if result.get('_retry'):
                wait_time = min(2 ** (attempt - 1), 30)
                time.sleep(wait_time)
                attempt += 1
                continue
            return result

        return {
            'error': True,
            'error_code': 'MaxRetriesExceeded',
            'error_message': f'Max retries ({max_retries}) exceeded',
            'error_type': 'RetryError',
            'retries_attempted': max_retries
        }

    def _attempt_invocation(self, messages, max_tokens, temperature, tools, system,
                           attempt, max_retries) -> Dict[str, Any]:
        """Execute a single model invocation attempt. Returns a _retry sentinel on transient failure."""
        model_label = 'inference profile' if self.is_inference_profile else 'model'
        try:
            request_body = self._format_request(messages, max_tokens, temperature, tools, system)
            logging.debug(f"Invoking {model_label}: {self.current_model_id}")
            logging.debug(f"Request body keys: {list(request_body.keys())}")
            if 'tools' in request_body:
                logging.debug(f"Tools count: {len(request_body['tools'])}")
            logging.debug(f"max_tokens is set to {max_tokens}")

            try:
                response = self.bedrock_runtime_client.invoke_model(
                    modelId=self.current_model_id,
                    contentType='application/json',
                    accept='application/json',
                    body=json.dumps(request_body)
                )
            except Exception as api_error:
                logging.error(f"Bedrock API error: {api_error}")
                logging.error(f"Request body: {json.dumps(request_body, indent=2)}")
                raise

            response_body = json.loads(response['body'].read())
            parsed_response = self._parse_response(response_body)
            logging.debug(f"{model_label} invoked successfully: {self.current_model_id}")
            return parsed_response

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logging.error(f"Bedrock API error - Code: {error_code}, Message: {error_message}")

            if error_code in self._TRANSIENT_ERRORS and attempt <= max_retries:
                wait_time = min(2 ** (attempt - 1), 30)
                logging.warning(f"Transient error {error_code}, retrying in {wait_time} seconds... "
                               f"(attempt {attempt}/{max_retries})")
                return {'_retry': True}

            return {
                'error': True,
                'error_code': error_code,
                'error_message': error_message,
                'error_type': 'ClientError',
                'retries_attempted': attempt - 1
            }

        except Exception as e:
            logging.error(f"Unexpected error invoking {model_label}: {e}")
            logging.error(f"Error type: {type(e).__name__}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return {
                'error': True,
                'error_code': type(e).__name__,
                'error_message': str(e),
                'error_type': 'Exception',
                'retries_attempted': 0
            }

    def _format_request(self, messages: List[Dict[str, str]], max_tokens: int,
                       temperature: float, tools: Optional[List[Dict[str, Any]]] = None,
                       system: Optional[str] = None) -> Dict[str, Any]:
        """
        Format the request body based on the model provider.

        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens to generate
            temperature: Model temperature
            tools: Optional list of tool definitions
            system: Optional system prompt/instructions

        Returns:
            Formatted request body dictionary
        """
        # Use model_identifier for provider detection (works for both direct models and profiles)
        model_id = self.model_identifier or self.current_model_id

        # Anthropic Claude models
        if 'anthropic.claude' in model_id or 'anthropic' in model_id.lower():
            request_body = {
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': max_tokens,
                'temperature': temperature,
                'messages': messages
            }

            # Add system prompt if provided (Claude supports system prompts)
            if system:
                request_body['system'] = system
                logging.debug(f"Added system prompt: {system[:50]}...")

            # Add tools if provided (Claude supports tools)
            if tools and len(tools) > 0:
                request_body['tools'] = tools
                logging.debug(f"Added {len(tools)} tools to request")

            return request_body

        # Amazon Titan models
        elif 'amazon.titan' in model_id or 'titan' in model_id.lower():
            # Titan uses a different format
            text_generation_config = {
                'maxTokenCount': max_tokens,
                'temperature': temperature,
                'topP': 0.9
            }

            # Combine messages into a single prompt for Titan
            prompt = self._messages_to_prompt(messages)

            return {
                'inputText': prompt,
                'textGenerationConfig': text_generation_config
            }

        # Meta Llama models
        elif 'meta.llama' in model_id or 'llama' in model_id.lower():
            prompt = self._messages_to_prompt(messages)
            return {
                'prompt': prompt,
                'max_gen_len': max_tokens,
                'temperature': temperature,
                'top_p': 0.9
            }

        # AI21 models
        elif 'ai21' in model_id:
            prompt = self._messages_to_prompt(messages)
            return {
                'prompt': prompt,
                'maxTokens': max_tokens,
                'temperature': temperature
            }

        # Cohere models
        elif 'cohere' in model_id:
            prompt = self._messages_to_prompt(messages)
            return {
                'prompt': prompt,
                'max_tokens': max_tokens,
                'temperature': temperature
            }

        # Default fallback to Anthropic format
        else:
            logging.warning(f"Unknown model provider for {model_id}, using default Anthropic format")
            return {
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': max_tokens,
                'temperature': temperature,
                'messages': messages
            }

    def _parse_response(self, response_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the model response based on the provider format.

        Args:
            response_body: Raw response body from the model

        Returns:
            Standardised response dictionary
        """
        model_id = self.model_identifier or self.current_model_id
        model_lower = model_id.lower()

        if 'anthropic.claude' in model_id or 'anthropic' in model_lower:
            return self._parse_anthropic_response(response_body)
        if 'amazon.titan' in model_id or 'titan' in model_lower:
            return self._parse_titan_response(response_body)
        if 'meta.llama' in model_id or 'llama' in model_lower:
            return self._parse_llama_response(response_body)
        if 'ai21' in model_id:
            return self._parse_ai21_response(response_body)
        if 'cohere' in model_id:
            return self._parse_cohere_response(response_body)

        return {'content': str(response_body), 'stop_reason': None, 'usage': {}}

    @staticmethod
    def _parse_anthropic_response(response_body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse an Anthropic Claude response."""
        content_blocks = response_body.get('content', [])
        parsed_content = []
        text_parts = []

        for block in content_blocks:
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
                parsed_content.append({'type': 'text', 'text': block.get('text', '')})
            elif block.get('type') == 'tool_use':
                parsed_content.append({
                    'type': 'tool_use',
                    'id': block.get('id'),
                    'name': block.get('name'),
                    'input': block.get('input', {})
                })

        return {
            'content': '\n'.join(text_parts) if text_parts else '',
            'content_blocks': parsed_content,
            'stop_reason': response_body.get('stop_reason'),
            'usage': response_body.get('usage', {})
        }

    @staticmethod
    def _parse_titan_response(response_body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse an Amazon Titan response."""
        results = response_body.get('results', [])
        return {
            'content': results[0].get('outputText', '') if results else '',
            'stop_reason': results[0].get('completionReason') if results else None,
            'usage': {
                'input_tokens': response_body.get('inputTextTokenCount', 0),
                'output_tokens': response_body.get('results', [{}])[0].get('tokenCount', 0)
            }
        }

    @staticmethod
    def _parse_llama_response(response_body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Meta Llama response."""
        return {
            'content': response_body.get('generation', ''),
            'stop_reason': response_body.get('stop_reason'),
            'usage': {
                'input_tokens': response_body.get('prompt_token_count', 0),
                'output_tokens': response_body.get('generation_token_count', 0)
            }
        }

    @staticmethod
    def _parse_ai21_response(response_body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse an AI21 response."""
        completions = response_body.get('completions', [])
        return {
            'content': completions[0].get('data', {}).get('text', '') if completions else '',
            'stop_reason': completions[0].get('finishReason', {}).get('reason') if completions else None,
            'usage': {}
        }

    @staticmethod
    def _parse_cohere_response(response_body: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Cohere response."""
        generations = response_body.get('generations', [])
        return {
            'content': generations[0].get('text', '') if generations else '',
            'stop_reason': generations[0].get('finish_reason') if generations else None,
            'usage': {}
        }

    def _messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Convert messages list to a single prompt string for models that don't support message format.

        Args:
            messages: List of message dictionaries

        Returns:
            Formatted prompt string
        """
        prompt_parts = []
        for msg in messages:
            role = msg['role'].capitalize()
            content = msg['content']
            prompt_parts.append(f"{role}: {content}")

        return '\n\n'.join(prompt_parts)

    def count_tokens(self, text: str, model_id: Optional[str] = None) -> int:
        """
        Estimate token count for text using tiktoken.

        Args:
            text: Text to count tokens for
            model_id: Optional model ID (uses current model if not specified)

        Returns:
            Estimated token count
        """
        try:
            # Use cl100k_base encoding (used by Claude and most modern models)
            encoding = tiktoken.get_encoding('cl100k_base')
            tokens = encoding.encode(text)
            return len(tokens)
        except Exception as e:
            logging.warning(f"Token counting failed: {e}, using character approximation")
            # Fallback to character-based approximation (roughly 4 chars per token)
            return len(text) // 4

    def count_message_tokens(self, messages: List[Dict[str, str]], model_id: Optional[str] = None) -> int:
        """
        Estimate token count for a list of messages.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model_id: Optional model ID (uses current model if not specified)

        Returns:
            Estimated total token count for all messages
        """
        total_tokens = 0
        for message in messages:
            total_tokens += 4  # Approximate overhead for role formatting
            total_tokens += self._count_content_tokens(message.get('content', ''), model_id)
        return total_tokens

    def _count_content_tokens(self, content, model_id: Optional[str] = None) -> int:
        """Count tokens for a single message content value (string or list of parts)."""
        if isinstance(content, str):
            return self.count_tokens(content, model_id)
        if not isinstance(content, list):
            return 0

        total = 0
        for part in content:
            if isinstance(part, str):
                total += self.count_tokens(part, model_id)
            elif isinstance(part, dict):
                if 'text' in part:
                    total += self.count_tokens(part['text'], model_id)
                elif 'image' in part or 'document' in part:
                    total += 1000  # Rough estimate for non-text content
        return total

    def get_current_model_id(self) -> Optional[str]:
        """
        Get the currently selected model ID.

        Returns:
            Current model ID or None
        """
        return self.current_model_id
