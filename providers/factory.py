"""
providers/factory.py
--------------------
Factory function that constructs the correct AIProviderBase implementation
based on application settings. Services never instantiate providers directly.
"""

from __future__ import annotations

from config.settings import AIProvider, Settings
from providers.base import AIProviderBase
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider


def build_ai_provider(settings: Settings) -> AIProviderBase:
    """
    Instantiate and return the configured AI provider.

    Called once at application startup and stored in app.state
    for injection into services.

    Raises:
        ValueError: If an unknown provider is specified.
    """
    if settings.ai_provider == AIProvider.OLLAMA:
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )

    if settings.ai_provider == AIProvider.OPENAI:
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )

    raise ValueError(f"Unknown AI provider: {settings.ai_provider}")
