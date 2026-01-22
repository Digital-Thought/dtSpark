"""
Core application module.

This module provides the main application class, entry point,
and context compaction for intelligent conversation management.
"""

from .application import AWSBedrockCLI, version, agent_type, full_name, agent_name, main
from .context_compaction import ContextCompactor, get_provider_from_model_id

__all__ = ['AWSBedrockCLI', 'version', 'agent_type', 'full_name', 'agent_name', 'main',
           'ContextCompactor', 'get_provider_from_model_id']
