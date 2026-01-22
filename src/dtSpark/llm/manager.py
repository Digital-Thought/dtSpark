"""
LLM Manager for handling multiple LLM providers.

This module manages:
- Initialisation of available LLM providers
- Model selection across providers
- Routing requests to the appropriate provider
"""

import logging
from typing import List, Dict, Optional, Any
from dtSpark.llm.base import LLMService


class LLMManager:
    """Manages multiple LLM service providers."""

    def __init__(self):
        """Initialise the LLM manager."""
        self.providers: Dict[str, LLMService] = {}
        self.active_provider: Optional[str] = None
        self.active_service: Optional[LLMService] = None

    def register_provider(self, provider: LLMService):
        """
        Register an LLM provider.

        Args:
            provider: LLMService implementation to register
        """
        provider_name = provider.get_provider_name()
        self.providers[provider_name] = provider
        logging.info(f"Registered LLM provider: {provider_name}")

        # Set as active if it's the first provider
        if not self.active_provider:
            self.active_provider = provider_name
            self.active_service = provider

    def list_all_models(self) -> List[Dict[str, Any]]:
        """
        List all models from all registered providers.

        Returns:
            Combined list of models from all providers
        """
        all_models = []

        for provider_name, provider in self.providers.items():
            try:
                models = provider.list_available_models()
                # Ensure each model has provider info
                for model in models:
                    if 'provider' not in model:
                        model['provider'] = provider_name
                all_models.extend(models)
            except Exception as e:
                logging.error(f"Failed to list models from {provider_name}: {e}")

        return all_models

    def set_model(self, model_id: str, provider_name: Optional[str] = None):
        """
        Set the active model.

        Args:
            model_id: Model identifier
            provider_name: Optional provider name. If not specified, searches all providers.
        """
        if provider_name:
            # Set model on specific provider
            if provider_name not in self.providers:
                raise ValueError(f"Provider {provider_name} not registered")

            provider = self.providers[provider_name]
            provider.set_model(model_id)
            self.active_provider = provider_name
            self.active_service = provider
            logging.info(f"Active provider set to: {provider_name}")
        else:
            # Search for model across all providers
            for prov_name, provider in self.providers.items():
                models = provider.list_available_models()
                if any(m['id'] == model_id for m in models):
                    provider.set_model(model_id)
                    self.active_provider = prov_name
                    self.active_service = provider
                    logging.info(f"Model {model_id} found on provider: {prov_name}")
                    return

            raise ValueError(f"Model {model_id} not found on any provider")

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
        Invoke the active model.

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
        if not self.active_service:
            return {
                'error': True,
                'error_code': 'NoProviderActive',
                'error_message': 'No LLM provider is active',
                'error_type': 'ConfigurationError'
            }

        return self.active_service.invoke_model(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            system=system,
            max_retries=max_retries
        )

    def get_active_provider(self) -> Optional[str]:
        """Get the name of the active provider."""
        return self.active_provider

    def get_active_service(self) -> Optional[LLMService]:
        """Get the active LLM service."""
        return self.active_service

    def count_tokens(self, text: str) -> int:
        """
        Count tokens using the active provider's tokeniser.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        if self.active_service:
            return self.active_service.count_tokens(text)
        # Fallback estimation
        return len(text) // 4

    def get_rate_limits(self) -> dict:
        """
        Get rate limit information for the active provider.

        Returns:
            Dictionary with rate limit information:
            {
                'input_tokens_per_minute': int or None
                'output_tokens_per_minute': int or None
                'requests_per_minute': int or None
                'has_limits': bool
            }
        """
        if self.active_service:
            return self.active_service.get_rate_limits()
        # Default: no limits
        return {
            'input_tokens_per_minute': None,
            'output_tokens_per_minute': None,
            'requests_per_minute': None,
            'has_limits': False
        }
