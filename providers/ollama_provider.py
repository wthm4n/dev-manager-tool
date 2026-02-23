"""
providers/ollama_provider.py
-----------------------------
AI provider implementation for local Ollama instances.
Uses the Ollama HTTP API (no SDK dependency).
Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations

import time
from typing import Optional

import httpx

from config.logging_config import get_logger
from providers.base import AIProviderBase, GenerationResult

logger = get_logger(__name__)


class OllamaProvider(AIProviderBase):
    """
    Connects to a locally-running Ollama daemon and generates text
    using any model that has been pulled (e.g. llama3, mistral, codellama).

    The provider is deliberately thin — all prompt engineering lives in
    the services that call it.
    """

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
        )
        logger.info("OllamaProvider initialised", extra={"model": model, "url": base_url})

    # ── Interface properties ──────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "ollama"

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
        Call /api/generate (non-streaming mode) and return the response.
        Falls back gracefully on network errors.
        """
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        start_ts = time.monotonic()
        try:
            response = await self._client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            latency_ms = (time.monotonic() - start_ts) * 1000

            generated_text: str = data.get("response", "").strip()
            eval_count: Optional[int] = data.get("eval_count")
            prompt_eval_count: Optional[int] = data.get("prompt_eval_count")

            logger.debug(
                "Ollama generation complete",
                extra={
                    "model": self._model,
                    "latency_ms": round(latency_ms, 1),
                    "eval_count": eval_count,
                },
            )

            return GenerationResult(
                text=generated_text,
                success=True,
                provider=self.provider_name,
                model=self._model,
                prompt_tokens=prompt_eval_count,
                completion_tokens=eval_count,
                latency_ms=round(latency_ms, 1),
            )

        except httpx.HTTPStatusError as exc:
            error = f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("Ollama HTTP error", extra={"error": error})
            return GenerationResult(
                text="",
                success=False,
                provider=self.provider_name,
                model=self._model,
                error=error,
                latency_ms=(time.monotonic() - start_ts) * 1000,
            )

        except httpx.RequestError as exc:
            error = f"Ollama connection error: {type(exc).__name__}: {exc}"
            logger.error("Ollama request error", extra={"error": error})
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
        Ping /api/tags — if Ollama is up it returns the list of local models.
        """
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Ollama health check failed", extra={"error": str(exc)})
            return False

    # ── Cleanup ───────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on app shutdown."""
        await self._client.aclose()
