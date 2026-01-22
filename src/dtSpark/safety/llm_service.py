"""
LLM service wrapper for prompt inspection.

Provides unified interface to multiple LLM providers (AWS Bedrock, Ollama, Anthropic Direct)
specifically for prompt inspection and security analysis tasks.


"""

import logging
from typing import Optional, Dict, List, Any


class InspectionLLMService:
    """
    LLM service wrapper for prompt inspection with multi-provider support.
    """

    def __init__(self, config: Dict, provider_manager: Optional[Any] = None):
        """
        Initialise inspection LLM service.

        Args:
            config: LLM inspection configuration
            provider_manager: Provider manager with access to all LLM providers
        """
        self.config = config
        self.provider_manager = provider_manager
        self.model_id = config.get('model')
        self.provider_name = config.get('provider')  # Optional: AWS Bedrock, Ollama, Anthropic Direct
        self.max_tokens = config.get('max_tokens', 500)

        # Determine which provider to use
        self.provider = None
        if provider_manager:
            self.provider = self._get_provider()

        if self.provider:
            logging.info(f"Inspection LLM service initialised: provider={self.provider_name}, model={self.model_id}")
        else:
            logging.warning("Inspection LLM service could not initialise provider")

    def _get_provider(self):
        """
        Get the configured LLM provider.

        Returns:
            Provider instance or None
        """
        try:
            # If specific provider requested, use that
            if self.provider_name:
                if self.provider_name.lower() == 'aws bedrock':
                    return self.provider_manager.get_bedrock_provider()
                elif self.provider_name.lower() == 'ollama':
                    return self.provider_manager.get_ollama_provider()
                elif self.provider_name.lower() == 'anthropic direct':
                    return self.provider_manager.get_anthropic_provider()

            # Otherwise, auto-detect based on model ID
            return self.provider_manager.get_provider_for_model(self.model_id)

        except Exception as e:
            logging.error(f"Failed to get LLM provider for inspection: {e}")
            return None

    def invoke_model(self, messages: List[Dict], max_tokens: Optional[int] = None,
                    temperature: float = 0.1) -> Optional[Dict]:
        """
        Invoke LLM for prompt analysis.

        Args:
            messages: List of message dicts with role and content
            max_tokens: Maximum tokens to generate (default from config)
            temperature: Temperature for generation (default 0.1 for consistency)

        Returns:
            Response dict with content, or None on failure
        """
        if not self.provider:
            logging.error("No LLM provider available for inspection")
            return None

        try:
            # Use configured max_tokens if not specified
            if max_tokens is None:
                max_tokens = self.max_tokens

            # Invoke via provider
            response = self.provider.invoke_model(
                model_id=self.model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=None  # No tools for inspection
            )

            return response

        except Exception as e:
            logging.error(f"Failed to invoke LLM for inspection: {e}")
            return None

    def is_available(self) -> bool:
        """
        Check if LLM service is available for inspection.

        Returns:
            True if provider and model are configured
        """
        return self.provider is not None and self.model_id is not None
