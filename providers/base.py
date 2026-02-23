"""
providers/base.py
-----------------
Abstract interface that every AI provider must implement.
Business logic never imports a concrete provider directly —
it always depends on this interface (Dependency Inversion Principle).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GenerationResult:
    """
    Structured return value from any AI generation call.
    Consumers should always check `success` before using `text`.
    """

    text: str
    success: bool
    provider: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class AIProviderBase(ABC):
    """
    Contract that OllamaProvider and OpenAIProvider both satisfy.
    Add new providers (Anthropic, Gemini, etc.) by subclassing this.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier, e.g. 'ollama' or 'openai'."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Currently configured model name."""
        ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> GenerationResult:
        """
        Generate text from a prompt.

        Args:
            prompt:        User-facing prompt text.
            system_prompt: Optional system-level instruction.
            max_tokens:    Upper bound on generated tokens.
            temperature:   Sampling temperature (0 = deterministic).

        Returns:
            GenerationResult with text and metadata.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable and responsive."""
        ...
