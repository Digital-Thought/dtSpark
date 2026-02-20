"""
LLM service providers module.

This module provides abstraction for different LLM providers,
allowing the application to work with AWS Bedrock, Ollama, Anthropic Direct API,
Google Gemini, and potentially other providers through a common interface.

Also includes context limit resolution for model-specific token limits.
"""

from .base import LLMService
from .manager import LLMManager
from .ollama import OllamaService
from .anthropic_direct import AnthropicService
from .context_limits import ContextLimitResolver

# Google Gemini is optional (requires google-genai package)
try:
    from .google_gemini import GoogleGeminiService
    _GEMINI_AVAILABLE = True
except ImportError:
    GoogleGeminiService = None
    _GEMINI_AVAILABLE = False

__all__ = [
    'LLMService',
    'LLMManager',
    'OllamaService',
    'AnthropicService',
    'ContextLimitResolver',
    'GoogleGeminiService',
]
