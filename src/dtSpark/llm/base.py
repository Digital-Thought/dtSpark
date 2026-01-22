"""
Abstract base class for LLM service providers.

This module defines the interface that all LLM providers must implement,
allowing the application to work with different LLM backends seamlessly.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any


class LLMService(ABC):
    """Abstract base class for LLM service providers."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the name of this LLM provider.

        Returns:
            Provider name (e.g., 'AWS Bedrock', 'Ollama')
        """
        pass

    @abstractmethod
    def get_access_info(self) -> str:
        """
        Get access information for this provider.

        Returns:
            Access information (e.g., 'AWS Bedrock', 'Ollama (http://localhost:11434)')
        """
        pass

    @abstractmethod
    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List all available models from this provider.

        Returns:
            List of model dictionaries with standard keys:
            - id: str - Unique model identifier
            - name: str - Display name
            - provider: str - Provider name
            - supports_tools: bool - Whether model supports tool calling
            - context_length: int - Maximum context window size
        """
        pass

    @abstractmethod
    def set_model(self, model_id: str):
        """
        Set the active model for this provider.

        Args:
            model_id: Model identifier to use
        """
        pass

    @abstractmethod
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
        Invoke the model with a conversation.

        Args:
            messages: Conversation messages in standard format
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            tools: Optional tool definitions
            system: Optional system prompt
            max_retries: Maximum retry attempts for transient failures

        Returns:
            Response dictionary with standard format:
            {
                'content': str or List - Response content
                'stop_reason': str - Why generation stopped
                'usage': {
                    'input_tokens': int,
                    'output_tokens': int
                },
                'tool_use': Optional[List] - Tool calls if any
            }

            Or error dictionary on failure:
            {
                'error': True,
                'error_code': str,
                'error_message': str,
                'error_type': str
            }
        """
        pass

    @abstractmethod
    def supports_streaming(self) -> bool:
        """
        Check if this provider supports streaming responses.

        Returns:
            True if streaming is supported
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using provider's tokeniser.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        pass

    def get_rate_limits(self) -> Dict[str, Any]:
        """
        Get rate limit information for this provider.

        Returns:
            Dictionary with rate limit information:
            {
                'input_tokens_per_minute': int or None - Max input tokens per minute
                'output_tokens_per_minute': int or None - Max output tokens per minute
                'requests_per_minute': int or None - Max requests per minute
                'has_limits': bool - Whether this provider has rate limits
            }

            Default implementation returns no limits (unlimited).
        """
        return {
            'input_tokens_per_minute': None,
            'output_tokens_per_minute': None,
            'requests_per_minute': None,
            'has_limits': False
        }
