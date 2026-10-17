"""
app/llm/base.py
────────────────
Abstract LLMClient — Strategy pattern.
Swap the implementation (Groq → OpenAI → local) without touching any service.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LLMMessage:
    """Single message in a chat conversation."""
    role: str          # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Structured response from the LLM."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"


class LLMClient(ABC):
    """
    Abstract base for all LLM backends.
    Every concrete implementation must handle:
    - Retries on transient errors
    - Logging of token usage
    """

    @abstractmethod
    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[str] = None,  # "json_object" if supported
    ) -> LLMResponse:
        """
        Send a chat completion request and return the structured response.
        Raises LLMError on unrecoverable failures.
        """
        ...

    @abstractmethod
    def model_name(self) -> str:
        """Return the canonical model name for audit logging."""
        ...
