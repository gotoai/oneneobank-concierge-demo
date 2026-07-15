"""Adapter from the concierge's calling convention to the vLLM server's OpenAI API.

This is the vLLM counterpart of :mod:`agent.llm` (the in-process transformers client).
The difference: the model does NOT live in this process. It runs in a separate
``vllm serve`` process (see ``run_vllm_server.sh``); this module is a thin *async*
client to that process's OpenAI-compatible API — hence "adapter": it adapts the OpenAI
API to the same ``chat`` / ``stream_chat`` shape the gateway uses.

Concurrency: vLLM continuously batches every in-flight request into one decode loop, so
many ``chat``/``stream_chat`` calls run in parallel. There is deliberately NO lock here
(unlike agent.api's GPU lock) — parallelism is the whole point of this backend.

Message shape: OpenAI chat messages, ``{"role": ..., "content": <str>}`` — build them
with :func:`agent.concierge.build_messages_openai`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from . import config

Message = dict


class VLLMAdapter:
    """Thin async wrapper over an ``AsyncOpenAI`` client pointed at ``vllm serve``."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model_id: str | None = None):
        self.model_id = model_id or config.VLLM_MODEL_ID
        self._client = AsyncOpenAI(
            base_url=base_url or config.VLLM_BASE_URL,
            api_key=api_key or config.VLLM_API_KEY,
        )

    async def chat(self, messages: list[Message], *, max_new_tokens: int | None = None,
                   temperature: float | None = None, top_p: float | None = None) -> str:
        """Non-streaming grounded reply. One OpenAI chat.completions call to vLLM."""
        resp = await self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_tokens=max_new_tokens or config.MAX_NEW_TOKENS,
            temperature=temperature if temperature is not None else config.GEN_TEMPERATURE,
            top_p=top_p if top_p is not None else config.GEN_TOP_P,
        )
        return (resp.choices[0].message.content or "").strip()

    async def stream_chat(self, messages: list[Message], *, max_new_tokens: int | None = None,
                          temperature: float | None = None,
                          top_p: float | None = None) -> AsyncIterator[str]:
        """Yield decoded text pieces as vLLM generates them (OpenAI streaming deltas)."""
        stream = await self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            stream=True,
            max_tokens=max_new_tokens or config.MAX_NEW_TOKENS,
            temperature=temperature if temperature is not None else config.GEN_TEMPERATURE,
            top_p=top_p if top_p is not None else config.GEN_TOP_P,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content
            if piece:
                yield piece

    async def is_ready(self) -> bool:
        """True if the vLLM backend answers a models.list() (i.e. it's up and loaded)."""
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.close()


_ADAPTER: VLLMAdapter | None = None


def get_adapter() -> VLLMAdapter:
    """Process-wide singleton adapter (one OpenAI client, reused across requests)."""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = VLLMAdapter()
    return _ADAPTER
