"""
Context limit resolver module for model-specific context window management.

This module provides functionality for resolving context window limits
based on model ID and provider, using configurable defaults for different
model families and providers.

The resolution follows this priority order:
1. Exact match in provider-specific configuration
2. Partial match (model ID contains pattern) in provider configuration
3. Provider default from configuration
4. Hardcoded defaults for known model families (Claude = 200K, etc.)
5. Global default (8192 tokens)
"""

import logging
from typing import Dict, Any, Optional


# Default context limits when no configuration is provided
DEFAULT_CONTEXT_LIMITS = {
    'context_window': 8192,
    'max_output': 4096
}

# Hardcoded defaults for known model families when config is missing
# These provide sensible fallbacks without requiring config
HARDCODED_MODEL_DEFAULTS = {
    'anthropic': {
        # All Claude models have 200K context window
        'claude': {'context_window': 200000, 'max_output': 32000},
        'default': {'context_window': 200000, 'max_output': 32000},
    },
    'aws_bedrock': {
        'claude': {'context_window': 200000, 'max_output': 32000},  # Claude on Bedrock
        'amazon.titan': {'context_window': 8192, 'max_output': 4096},
        'meta.llama': {'context_window': 128000, 'max_output': 4096},
        'mistral': {'context_window': 128000, 'max_output': 4096},
        'default': {'context_window': 8192, 'max_output': 4096},
    },
    'ollama': {
        'llama': {'context_window': 128000, 'max_output': 4096},
        'mistral': {'context_window': 32000, 'max_output': 4096},
        'codellama': {'context_window': 16000, 'max_output': 4096},
        'default': {'context_window': 8192, 'max_output': 4096},
    },
}


class ContextLimitResolver:
    """
    Resolves context window limits for models based on configuration.

    This class provides a flexible way to look up context window and
    max output token limits for any model based on its ID and provider.
    It supports both exact and partial matching of model IDs.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialise the context limit resolver.

        Args:
            config: Full configuration dictionary containing 'model_context_limits' section,
                   or a Settings object that uses dot notation for access.
                   If None or missing the section, uses hardcoded defaults.
        """
        self.limits_config = {}
        self._settings_obj = None

        if config:
            # Try standard dictionary access first
            if isinstance(config, dict):
                self.limits_config = config.get('model_context_limits', {})
            elif hasattr(config, 'get'):
                # Try to get as dict first (some Settings objects support this)
                limits = config.get('model_context_limits', None)
                if isinstance(limits, dict) and limits:
                    self.limits_config = limits
                else:
                    # Store Settings object for dot notation access
                    self._settings_obj = config
                    self.limits_config = self._build_limits_from_settings(config)

        logging.info(f"ContextLimitResolver initialised with {len(self.limits_config)} provider sections")
        if self.limits_config:
            for provider, models in self.limits_config.items():
                if isinstance(models, dict):
                    logging.info(f"  Provider '{provider}': {list(models.keys())}")

    def _build_limits_from_settings(self, settings) -> Dict[str, Any]:
        """
        Build limits config from a Settings object using dot notation.

        Args:
            settings: Settings object with dot notation access

        Returns:
            Dictionary with provider sections
        """
        limits_config = {}

        # Define known providers and model patterns to check
        providers = ['anthropic', 'aws_bedrock', 'ollama']
        known_models = {
            'anthropic': [
                'claude-opus-4', 'claude-sonnet-4', 'claude-opus-4.5', 'claude-sonnet-4.5',
                'claude-3-5-sonnet', 'claude-3-5-haiku', 'claude-3-opus', 'claude-3-sonnet',
                'claude-3-haiku', 'default'
            ],
            'aws_bedrock': [
                'amazon.titan-text-express', 'meta.llama3-1', 'mistral.mistral-large',
                'default'
            ],
            'ollama': [
                'llama3.2', 'mistral', 'codellama', 'default'
            ]
        }

        for provider in providers:
            provider_config = {}
            models = known_models.get(provider, ['default'])

            for model in models:
                context_key = f'model_context_limits.{provider}.{model}.context_window'
                output_key = f'model_context_limits.{provider}.{model}.max_output'

                context_window = settings.get(context_key, None)
                max_output = settings.get(output_key, None)

                logging.debug(f"Settings lookup: {context_key} = {context_window}")

                if context_window is not None and max_output is not None:
                    provider_config[model] = {
                        'context_window': int(context_window),
                        'max_output': int(max_output)
                    }
                    logging.info(f"Loaded model limits: {provider}.{model} = {context_window}/{max_output}")

            if provider_config:
                limits_config[provider] = provider_config

        # Also try global default
        global_context = settings.get('model_context_limits.default.context_window', None)
        global_output = settings.get('model_context_limits.default.max_output', None)
        if global_context is not None and global_output is not None:
            limits_config['default'] = {
                'context_window': int(global_context),
                'max_output': int(global_output)
            }

        return limits_config

    def get_context_limits(self, model_id: str, provider: str) -> Dict[str, int]:
        """
        Get context window and max output limits for a model.

        The resolution follows this priority order:
        1. Exact match in provider-specific configuration
        2. Partial match (model ID contains pattern) in provider configuration
        3. Provider default
        4. Global default

        Args:
            model_id: The model identifier (e.g., 'claude-3-5-sonnet-20241022')
            provider: Provider name. Supported values:
                     - 'anthropic' (for Anthropic Direct API)
                     - 'aws_bedrock' (for AWS Bedrock non-Claude models)
                     - 'ollama' (for Ollama models)
                     Note: Claude models on Bedrock should use 'anthropic' provider

        Returns:
            Dict with 'context_window' and 'max_output' keys (both integers)
        """
        if not model_id:
            logging.warning("Empty model_id provided, using global default")
            return self._get_global_default()

        model_id_lower = model_id.lower()
        provider_key = self._normalise_provider_key(provider, model_id_lower)

        # Get provider-specific limits section
        provider_limits = self.limits_config.get(provider_key, {})

        if provider_limits:
            # 1. Try exact match
            limits = self._try_exact_match(model_id_lower, provider_limits)
            if limits:
                logging.debug(f"Exact match found for {model_id} in {provider_key}")
                return limits

            # 2. Try partial match (model_id contains pattern)
            limits = self._try_partial_match(model_id_lower, provider_limits)
            if limits:
                logging.debug(f"Partial match found for {model_id} in {provider_key}")
                return limits

            # 3. Try provider default
            if 'default' in provider_limits:
                limits = self._extract_limits(provider_limits['default'])
                if limits:
                    logging.debug(f"Using provider default for {model_id} in {provider_key}")
                    return limits

        # 4. Try hardcoded defaults for known model families
        hardcoded = self._try_hardcoded_defaults(model_id_lower, provider_key)
        if hardcoded:
            logging.info(f"Using hardcoded defaults for {model_id} ({provider_key}): "
                        f"context_window={hardcoded['context_window']}, max_output={hardcoded['max_output']}")
            return hardcoded

        # 5. Fall back to global default
        logging.debug(f"Using global default for {model_id}")
        return self._get_global_default()

    def _normalise_provider_key(self, provider: str, model_id_lower: str) -> str:
        """
        Normalise provider key for configuration lookup.

        Detects if a Bedrock model is actually a Claude model and routes
        to the anthropic section for correct limits.

        Args:
            provider: Original provider string
            model_id_lower: Lowercase model ID

        Returns:
            Normalised provider key for config lookup
        """
        provider_lower = provider.lower() if provider else ''

        # Map common provider names to config keys
        provider_map = {
            'anthropic direct': 'anthropic',
            'anthropic_direct': 'anthropic',  # underscore variant
            'anthropic': 'anthropic',
            'aws bedrock': 'aws_bedrock',
            'aws_bedrock': 'aws_bedrock',
            'bedrock': 'aws_bedrock',
            'ollama': 'ollama',
        }

        normalised = provider_map.get(provider_lower, provider_lower)

        # Special case: Claude models on Bedrock should use anthropic limits
        if normalised == 'aws_bedrock' and self._is_claude_model(model_id_lower):
            logging.debug(f"Routing Claude model {model_id_lower} to anthropic limits")
            return 'anthropic'

        return normalised

    def _is_claude_model(self, model_id_lower: str) -> bool:
        """
        Check if a model ID refers to a Claude model.

        Args:
            model_id_lower: Lowercase model ID

        Returns:
            True if this is a Claude/Anthropic model
        """
        claude_patterns = [
            'claude',
            'anthropic',
        ]
        return any(pattern in model_id_lower for pattern in claude_patterns)

    def _try_exact_match(self, model_id_lower: str, provider_limits: Dict) -> Optional[Dict[str, int]]:
        """
        Try to find an exact match for the model ID.

        Args:
            model_id_lower: Lowercase model ID
            provider_limits: Provider-specific limits dictionary

        Returns:
            Limits dict if found, None otherwise
        """
        for pattern, limits in provider_limits.items():
            if pattern == 'default':
                continue
            if model_id_lower == pattern.lower():
                return self._extract_limits(limits)
        return None

    def _try_partial_match(self, model_id_lower: str, provider_limits: Dict) -> Optional[Dict[str, int]]:
        """
        Try to find a partial match where model_id contains the pattern.

        Uses longest match first to prefer more specific patterns.
        E.g., 'claude-3-5-sonnet' matches before 'claude-3'.

        Args:
            model_id_lower: Lowercase model ID
            provider_limits: Provider-specific limits dictionary

        Returns:
            Limits dict if found, None otherwise
        """
        # Sort patterns by length (longest first) for most specific match
        patterns = [(k, v) for k, v in provider_limits.items() if k != 'default']
        patterns.sort(key=lambda x: len(x[0]), reverse=True)

        for pattern, limits in patterns:
            pattern_lower = pattern.lower()
            # Check if pattern is contained in model_id
            if pattern_lower in model_id_lower:
                return self._extract_limits(limits)
        return None

    def _try_hardcoded_defaults(self, model_id_lower: str, provider: str) -> Optional[Dict[str, int]]:
        """
        Try to find hardcoded defaults for known model families.

        This provides sensible fallbacks when config isn't available.

        Args:
            model_id_lower: Lowercase model ID
            provider: Provider key (anthropic, aws_bedrock, ollama)

        Returns:
            Limits dict if found, None otherwise
        """
        provider_defaults = HARDCODED_MODEL_DEFAULTS.get(provider, {})
        if not provider_defaults:
            return None

        # Try to match model patterns (longest first)
        patterns = [(k, v) for k, v in provider_defaults.items() if k != 'default']
        patterns.sort(key=lambda x: len(x[0]), reverse=True)

        for pattern, limits in patterns:
            if pattern.lower() in model_id_lower:
                return limits.copy()

        # Try provider default
        if 'default' in provider_defaults:
            return provider_defaults['default'].copy()

        return None

    def _extract_limits(self, limits_data: Any) -> Optional[Dict[str, int]]:
        """
        Extract context_window and max_output from limits data.

        Args:
            limits_data: Can be a dict with context_window/max_output keys,
                        or a legacy format

        Returns:
            Dict with 'context_window' and 'max_output', or None if invalid
        """
        if isinstance(limits_data, dict):
            context_window = limits_data.get('context_window')
            max_output = limits_data.get('max_output')

            if context_window is not None and max_output is not None:
                return {
                    'context_window': int(context_window),
                    'max_output': int(max_output)
                }

        return None

    def _get_global_default(self) -> Dict[str, int]:
        """
        Get the global default context limits.

        Returns:
            Dict with 'context_window' and 'max_output'
        """
        # Try config global default first
        global_default = self.limits_config.get('default')
        if global_default:
            limits = self._extract_limits(global_default)
            if limits:
                return limits

        # Fall back to hardcoded default
        return DEFAULT_CONTEXT_LIMITS.copy()

    def get_context_window(self, model_id: str, provider: str) -> int:
        """
        Convenience method to get just the context window size.

        Args:
            model_id: The model identifier
            provider: Provider name

        Returns:
            Context window size in tokens
        """
        return self.get_context_limits(model_id, provider)['context_window']

    def get_max_output(self, model_id: str, provider: str) -> int:
        """
        Convenience method to get just the max output tokens.

        Args:
            model_id: The model identifier
            provider: Provider name

        Returns:
            Maximum output tokens
        """
        return self.get_context_limits(model_id, provider)['max_output']

    def calculate_compaction_threshold(self, model_id: str, provider: str,
                                        threshold_ratio: float = 0.7) -> int:
        """
        Calculate the token count at which compaction should be triggered.

        Args:
            model_id: The model identifier
            provider: Provider name
            threshold_ratio: Fraction of context window to trigger compaction (default 0.7)

        Returns:
            Token count threshold for compaction
        """
        context_window = self.get_context_window(model_id, provider)
        return int(context_window * threshold_ratio)

    def calculate_emergency_threshold(self, model_id: str, provider: str,
                                       emergency_ratio: float = 0.95) -> int:
        """
        Calculate the emergency token count at which compaction is forced.

        Args:
            model_id: The model identifier
            provider: Provider name
            emergency_ratio: Fraction of context window for emergency compaction (default 0.95)

        Returns:
            Token count threshold for emergency compaction
        """
        context_window = self.get_context_window(model_id, provider)
        return int(context_window * emergency_ratio)
