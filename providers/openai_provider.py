"""
providers/openai_provider.py
-----------------------------
AI provider for OpenAI-compatible APIs.
Works with OpenAI, Azure OpenAI, Together.ai, Groq, Anyscale, etc.
The base_url is configurable, so you can point it at any compatible endpoint.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from config.logging_config import get_logger
from providers.base import AIProviderBase, GenerationResult

logger = get_logger(__name__)


class OpenAIProvider(AIProviderBase):
    """
    Calls the /chat/completions endpoint of any OpenAI-compatible API.

    Authentication is handled via the Authorization header using the
    OPENAI_API_KEY environment variable. For local endpoints (e.g. LM Studio)
    you can set a dummy key like 'local'.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when using the OpenAI provider. "
                "For local endpoints use any non-empty placeholder."
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )
        logger.info(
            "OpenAIProvider initialised",
            extra={"model": model, "base_url": base_url},
        )

    # ── Interface properties ──────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    # ── Core generation ──────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> GenerationResult:
        """
        Call /chat/completions and return the first choice's message content.
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        start_ts = time.monotonic()
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            latency_ms = (time.monotonic() - start_ts) * 1000

            choice = data["choices"][0]
            generated_text: str = choice["message"]["content"].strip()
            usage: Dict[str, int] = data.get("usage", {})

            logger.debug(
                "OpenAI generation complete",
                extra={
                    "model": self._model,
                    "latency_ms": round(latency_ms, 1),
                    "usage": usage,
                },
            )

            return GenerationResult(
                text=generated_text,
                success=True,
                provider=self.provider_name,
                model=self._model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                latency_ms=round(latency_ms, 1),
            )

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:500]
            error = f"OpenAI HTTP {exc.response.status_code}: {error_body}"
            logger.error("OpenAI HTTP error", extra={"error": error})
            return GenerationResult(
                text="",
                success=False,
                provider=self.provider_name,
                model=self._model,
                error=error,
                latency_ms=(time.monotonic() - start_ts) * 1000,
            )

        except (httpx.RequestError, KeyError, IndexError) as exc:
            error = f"OpenAI provider error: {type(exc).__name__}: {exc}"
            logger.error("OpenAI provider error", extra={"error": error})
            return GenerationResult(
                text="",
                success=False,
                provider=self.provider_name,
                model=self._model,
                error=error,
                latency_ms=(time.monotonic() - start_ts) * 1000,
            )

    # ── Health check ──────────────────────────────────────────

    async def health_check(self) -> bool:
        """
        Verify the API is reachable by listing models.
        For self-hosted endpoints that don't support /models, this may fail —
        override if needed.
        """
        try:
            resp = await self._client.get("/models", timeout=10.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("OpenAI health check failed", extra={"error": str(exc)})
            return False

    # ── Cleanup ───────────────────────────────────────────────

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()
