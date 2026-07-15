"""Thin internal Gemma 4 12B client (4-bit), mirroring the ichimaru agent-service.

This is the *internal* LLM layer — the concierge module calls it. Loads the model
once (lazily) and exposes `generate(messages)`, `generate_stream(messages)` and a
small `chat(user, system)` helper.

Message shape (Gemma multimodal chat template):
    {"role": "user", "content": [{"type": "text", "text": "..."}]}
"""
from __future__ import annotations

import sys
import warnings

from . import config  # loads .env (HF_HOME) BEFORE torch/transformers are imported

import torch  # noqa: E402  (must come after config so HF_HOME is set)
from transformers import (  # noqa: E402
    AutoModelForCausalLM,
    AutoProcessor,
    BitsAndBytesConfig,
)

# bitsandbytes triggers a harmless FutureWarning during generation; silence just that.
warnings.filterwarnings(
    "ignore", message=r".*_check_is_size will be removed.*", category=FutureWarning
)

Message = dict


def text_message(role: str, text: str) -> Message:
    """A single text-only chat message in Gemma's content-parts format."""
    return {"role": role, "content": [{"type": "text", "text": text}]}


class GemmaLLM:
    """Lazily-loaded Gemma 4 12B in 4-bit (nf4). ~5-6GB VRAM; fits 16GB comfortably."""

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or config.MODEL_ID
        self.processor = None
        self.model = None

    def load(self) -> "GemmaLLM":
        if self.model is not None:
            return self
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        # stderr, not stdout: the CLI's stdout carries the conversation.
        print(f"Loading {self.model_id} (4-bit)... first run downloads ~8GB into HF_HOME",
              file=sys.stderr, flush=True)
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id, quantization_config=quant, device_map="auto", dtype="auto",
        )
        self.model.eval()
        return self

    def generate(
        self,
        messages: list[Message],
        *,
        max_new_tokens: int | None = None,
        do_sample: bool = True,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate a reply string for `messages` (non-streaming)."""
        self.load()
        inputs = self.processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.model.device)
        prompt_len = inputs["input_ids"].shape[-1]

        gen_kwargs = dict(max_new_tokens=max_new_tokens or config.MAX_NEW_TOKENS,
                          do_sample=do_sample)
        if do_sample:  # only pass sampling params when sampling (avoids warnings)
            gen_kwargs["temperature"] = temperature if temperature is not None else config.GEN_TEMPERATURE
            gen_kwargs["top_p"] = top_p if top_p is not None else config.GEN_TOP_P

        with torch.inference_mode():
            out = self.model.generate(**inputs, **gen_kwargs)
        return self.processor.decode(
            out[0][prompt_len:], skip_special_tokens=True
        ).strip()

    def generate_stream(
        self,
        messages: list[Message],
        *,
        max_new_tokens: int | None = None,
        do_sample: bool = True,         # prose/chat — a little sampling reads better
        temperature: float | None = None,
        top_p: float | None = None,
    ):
        """Yield decoded text pieces as they are generated (for a live CLI reply).

        Uses transformers' TextIteratorStreamer: generation runs on a worker thread
        while this generator yields the tokens it emits.
        """
        import threading

        from transformers import TextIteratorStreamer

        self.load()
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(self.model.device)

        tok = getattr(self.processor, "tokenizer", None) or self.processor
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)

        gen_kwargs = dict(inputs, max_new_tokens=max_new_tokens or config.MAX_NEW_TOKENS,
                          do_sample=do_sample, streamer=streamer)
        if do_sample:
            gen_kwargs["temperature"] = temperature if temperature is not None else config.GEN_TEMPERATURE
            gen_kwargs["top_p"] = top_p if top_p is not None else config.GEN_TOP_P

        def _run() -> None:
            with torch.inference_mode():
                self.model.generate(**gen_kwargs)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        try:
            for piece in streamer:
                yield piece
        finally:
            thread.join()

    def chat(self, user: str, system: str | None = None, **kw) -> str:
        messages: list[Message] = []
        if system:
            messages.append(text_message("system", system))
        messages.append(text_message("user", user))
        return self.generate(messages, **kw)


_LLM: GemmaLLM | None = None


def get_llm() -> GemmaLLM:
    """Process-wide singleton so the model is loaded once and reused."""
    global _LLM
    if _LLM is None:
        _LLM = GemmaLLM().load()
    return _LLM
