"""
app/llm/groq_client.py
───────────────────────
Groq implementation of LLMClient.
Uses the official groq Python SDK with async support.
Retries once on rate-limit / server errors before raising LLMError.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from groq import AsyncGroq, RateLimitError, APIStatusError

from app.core.config import get_settings
from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMMessage, LLMResponse

logger = get_logger(__name__)
settings = get_settings()

_MAX_RETRIES = 2
_RETRY_SLEEP = 2.0  # seconds between retries


class GroqClient(LLMClient):
    """
    Groq-backed LLM client.
    A single instance is constructed per request via dependency injection.
    The underlying AsyncGroq client is lightweight and stateless.
    """

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self._model = settings.GROQ_MODEL

    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        """
        Call the Groq chat completion API with retry logic.
        `response_format="json_object"` enables Groq's JSON mode (Llama 3.1+).
        """
        groq_messages = [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict = {
            "model": self._model,
            "messages": groq_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                usage = response.usage

                logger.info(
                    "llm_completion",
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    finish_reason=choice.finish_reason,
                )
                return LLMResponse(
                    content=choice.message.content or "",
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    finish_reason=choice.finish_reason or "stop",
                )

            except RateLimitError as exc:
                last_error = exc
                logger.warning("llm_rate_limit", attempt=attempt, model=self._model)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_SLEEP * attempt)

            except APIStatusError as exc:
                last_error = exc
                logger.error("llm_api_error", status=exc.status_code, attempt=attempt)
                if exc.status_code >= 500 and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_SLEEP * attempt)
                else:
                    break

            except Exception as exc:
                last_error = exc
                logger.error("llm_unexpected_error", error=str(exc))
                break

        raise LLMError(
            f"Groq API failed after {_MAX_RETRIES} attempts: {last_error}",
            details={"model": self._model},
        )
