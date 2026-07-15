"""Live web API for the OneNeo Bank concierge — in-process transformers backend (FastAPI).

This is the web-API counterpart to :mod:`agent.cli`. Where the CLI resolves one
customer + campaign at startup and holds the grounding for a REPL session, the API
is stateless: each ``/v1/chat`` request names the customer and campaign, the server
rebuilds the grounded system prompt (cheap — the data layer is ``lru_cache``d) and
generates the reply. Conversation continuity is the caller's job, via ``history``.

The ``/v1/*`` contract (request/response models, auth, grounding) lives in
:mod:`agent.schemas` and is shared verbatim with the vLLM gateway (:mod:`agent.api_vllm`),
so the two backends are drop-in compatible.

Endpoints:
  * ``GET  /healthz``          liveness (process up; model need not be loaded)
  * ``GET  /readyz``           readiness (model loaded, can serve generations)
  * ``GET  /v1/customers``     list the spotlight customers (grounding available)
  * ``GET  /v1/campaigns``     list campaigns (which have an answerable Q&A KB)
  * ``POST /v1/profile``       the grounding system prompt (the CLI's /profile)
  * ``POST /v1/chat``          grounded concierge reply, non-streaming
  * ``POST /v1/chat/stream``   grounded concierge reply, Server-Sent Events

Operational model (why this file looks the way it does):
  * ONE model in ONE process. The Gemma model is a process-wide singleton in VRAM
    (agent.llm.get_llm). Run a SINGLE uvicorn worker — never --workers N, or you load
    N copies of the model. Scale by GPU/replica instead. (For request-level concurrency
    on one GPU, use the vLLM backend, agent.api_vllm, instead.)
  * Generation is blocking and GPU-bound. Each request runs generate() in a worker
    thread (so the event loop stays responsive) and holds a global lock so only ONE
    generation runs at a time; extra requests queue rather than thrash VRAM / OOM.

Run it (single worker):
    python -m agent.api                          # host/port from .env (API_HOST/API_PORT)
    uvicorn agent.api:app --host 127.0.0.1 --port 8000   # equivalent, explicit

Call it:
    curl -sS -X POST http://127.0.0.1:8000/v1/chat \
      -H "Authorization: Bearer $GOTOAI_AGENT_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"customer":"Aoi","campaign":"CMP-DEP-2026Q3-01","message":"..."}'
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from . import concierge, config, schemas
from .schemas import (
    CampaignsResponse,
    ChatRequest,
    ChatResponse,
    CustomersResponse,
    ProfileRequest,
    ProfileResponse,
    require_auth,
)

# Only one generation at a time — the GPU can serve a single generate() efficiently, and
# concurrent calls risk an OOM. Requests beyond the first queue on this lock.
_gpu_lock = asyncio.Lock()


def _load_llm():
    """Return the process-wide LLM singleton (loads the model on first call).

    Imported lazily so importing ``agent.api`` does NOT import torch — the app stays
    torch-free until a real generation is served.
    """
    from .llm import get_llm
    return get_llm()


def _model_ready() -> bool:
    """True once the model is loaded. Guarded/torch-free: returns False if the LLM layer
    isn't importable (torch absent) or the model simply hasn't loaded yet."""
    try:
        from . import llm as _llm
    except Exception:
        return False
    return _llm._LLM is not None and _llm._LLM.model is not None


# --------------------------------------------------------------------------- lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.GOTOAI_AGENT_API_KEY:
        print("WARNING: GOTOAI_AGENT_API_KEY is empty — /v1 endpoints are UNAUTHENTICATED.",
              file=sys.stderr, flush=True)
    if config.API_EAGER_LOAD:
        # Load the model up front (in a thread — it's slow and blocking) so the first real
        # request isn't paying the load cost and /readyz reflects reality.
        print("Eager-loading model at startup (API_EAGER_LOAD=1)...", file=sys.stderr, flush=True)
        await anyio.to_thread.run_sync(_load_llm)
    yield


app = FastAPI(title="oneneobank-concierge agent-service (transformers)", version="0.1.0",
              lifespan=lifespan)


# --------------------------------------------------------------------------- probes
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up (does not require the model to be loaded)."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness: the model is loaded and can serve generations."""
    if not _model_ready():
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return {"status": "ready", "model_id": config.MODEL_ID}


# --------------------------------------------------------------------------- metadata
@app.get("/v1/customers", response_model=CustomersResponse, dependencies=[Depends(require_auth)])
async def customers_endpoint() -> CustomersResponse:
    """List the spotlight customers the concierge can be grounded on. No generation."""
    return schemas.list_customers()


@app.get("/v1/campaigns", response_model=CampaignsResponse, dependencies=[Depends(require_auth)])
async def campaigns_endpoint() -> CampaignsResponse:
    """List campaigns and whether each has an answerable Q&A KB. No generation."""
    return schemas.list_campaigns()


@app.post("/v1/profile", response_model=ProfileResponse, dependencies=[Depends(require_auth)])
async def profile_endpoint(req: ProfileRequest) -> ProfileResponse:
    """Return the grounded system prompt for a customer + campaign (the CLI's /profile).

    Useful for inspecting exactly what the concierge is grounded on. No generation.
    """
    return schemas.build_profile(req)


# --------------------------------------------------------------------------- endpoints
@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    """Grounded concierge reply, non-streaming. One sampled generation on the GPU."""
    cust, ck = schemas.resolve_grounding(req.customer, req.campaign)
    language = concierge.normalize_language(req.language)
    system_prompt = concierge.build_system_prompt(cust, ck, language)
    history = [t.model_dump() for t in (req.history or [])]
    messages = concierge.build_messages(system_prompt, history, req.message)

    def _run() -> str:
        return _load_llm().generate(messages, max_new_tokens=req.max_new_tokens)

    async with _gpu_lock:
        try:
            answer = await anyio.to_thread.run_sync(_run)
        except Exception as exc:  # OOM, model errors — surface as 503 (retryable)
            raise HTTPException(status_code=503, detail=f"generation failed: {exc}") from exc

    return ChatResponse(
        message=answer.strip(), customer=cust.name, persona_id=cust.persona_id,
        campaign_id=ck.campaign_id, campaign_name=ck.campaign_name,
        language=language, model_id=config.MODEL_ID,
    )


@app.post("/v1/chat/stream", dependencies=[Depends(require_auth)])
async def chat_stream_endpoint(req: ChatRequest) -> StreamingResponse:
    """Grounded concierge reply, Server-Sent Events. Streams token deltas as they generate.

    Mirrors the CLI's live streaming reply. Events: ``data: {"delta": "..."}`` per chunk,
    a final ``event: done``, or ``event: error`` with a message. The GPU lock is held for
    the stream's duration, so concurrent chat requests queue (one generation at a time),
    consistent with the other endpoints.
    """
    cust, ck = schemas.resolve_grounding(req.customer, req.campaign)
    system_prompt = concierge.build_system_prompt(cust, ck, req.language)
    history = [t.model_dump() for t in (req.history or [])]
    messages = concierge.build_messages(system_prompt, history, req.message)

    async def _sse():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _worker() -> None:
            try:
                for piece in _load_llm().generate_stream(messages, max_new_tokens=req.max_new_tokens):
                    loop.call_soon_threadsafe(queue.put_nowait, ("delta", piece))
            except Exception as exc:  # noqa: BLE001 — surface to the client as an error event
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", _SENTINEL))

        async with _gpu_lock:
            await anyio.to_thread.run_sync(lambda: None)  # ensure loop is live
            threading.Thread(target=_worker, daemon=True).start()
            while True:
                kind, payload = await queue.get()
                if kind == "delta":
                    yield f"data: {json.dumps({'delta': payload}, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    yield f"event: error\ndata: {json.dumps({'error': payload}, ensure_ascii=False)}\n\n"
                    return
                else:  # done
                    yield "event: done\ndata: {}\n\n"
                    return

    return StreamingResponse(_sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main() -> None:
    import uvicorn

    # Single worker on purpose: one model per process (see module docstring).
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, workers=1)


if __name__ == "__main__":
    main()
