"""Live web API for the OneNeo Bank concierge — vLLM gateway (FastAPI).

Same ``/v1/*`` contract as :mod:`agent.api` (it imports the shared models, auth, and
grounding from :mod:`agent.schemas`), so it is a drop-in replacement on the same port —
the web-app and its SSE parser do not change. What differs is the backend:

  * The model runs in a SEPARATE ``vllm serve`` process (see ``run_vllm_server.sh``).
    This gateway is a thin async client to it via :mod:`agent.vllm_adapter`.
  * There is NO GPU lock. vLLM continuously batches every in-flight request into one
    decode loop, so concurrent requests run in PARALLEL (the reason to use this backend).
  * The concierge has no tools, so — unlike a general agent gateway — this is just a
    grounded chat.completions call plus a streaming variant; no tool loop.

Two processes, started in this order:
    ./run_vllm_server.sh                 # process B: the model (vllm serve), port 8001
    python -m agent.api_vllm             # process A: this gateway, on API_PORT (8000)

Call it exactly like agent.api:
    curl -sS -X POST http://127.0.0.1:8000/v1/chat \
      -H "Authorization: Bearer $GOTOAI_AGENT_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"customer":"Aoi","campaign":"CMP-DEP-2026Q3-01","message":"..."}'
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from typing import Any

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
from .vllm_adapter import get_adapter


# --------------------------------------------------------------------------- lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.GOTOAI_AGENT_API_KEY:
        print("WARNING: GOTOAI_AGENT_API_KEY is empty — /v1 endpoints are UNAUTHENTICATED.",
              file=sys.stderr, flush=True)
    # Don't block startup on the backend — `vllm serve` may still be loading. Just report.
    ready = await get_adapter().is_ready()
    print(f"vLLM backend at {config.VLLM_BASE_URL} reachable: {ready} "
          f"(model {config.VLLM_MODEL_ID})", file=sys.stderr, flush=True)
    yield
    await get_adapter().aclose()


app = FastAPI(title="oneneobank-concierge agent-service (vLLM)", version="0.1.0",
              lifespan=lifespan)


# --------------------------------------------------------------------------- probes
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the gateway process is up (does not require the vLLM backend)."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness: the vLLM backend is reachable and can serve generations."""
    if not await get_adapter().is_ready():
        raise HTTPException(status_code=503,
                            detail=f"vLLM backend at {config.VLLM_BASE_URL} not reachable yet")
    return {"status": "ready", "model_id": config.VLLM_MODEL_ID}


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
    """Return the grounded system prompt for a customer + campaign (the CLI's /profile)."""
    return schemas.build_profile(req)


# --------------------------------------------------------------------------- endpoints
@app.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    """Grounded concierge reply, non-streaming. One chat.completions call to vLLM.

    No lock: concurrent requests are batched together by vLLM and run in parallel.
    """
    cust, ck = schemas.resolve_grounding(req.customer, req.campaign)
    language = concierge.normalize_language(req.language)
    system_prompt = concierge.build_system_prompt(cust, ck, language)
    history = [t.model_dump() for t in (req.history or [])]
    messages = concierge.build_messages_openai(system_prompt, history, req.message)

    try:
        answer = await get_adapter().chat(messages, max_new_tokens=req.max_new_tokens)
    except Exception as exc:  # backend down / model error — surface as 503 (retryable)
        raise HTTPException(status_code=503, detail=f"generation failed: {exc}") from exc

    return ChatResponse(
        message=answer.strip(), customer=cust.name, persona_id=cust.persona_id,
        campaign_id=ck.campaign_id, campaign_name=ck.campaign_name,
        language=language, model_id=config.VLLM_MODEL_ID,
    )


@app.post("/v1/chat/stream", dependencies=[Depends(require_auth)])
async def chat_stream_endpoint(req: ChatRequest) -> StreamingResponse:
    """Grounded concierge reply, Server-Sent Events — identical frames to agent.api.

    Events: ``data: {"delta": "..."}`` per chunk, a final ``event: done``, or
    ``event: error`` with a message. No lock — concurrent streams are batched by vLLM.
    """
    cust, ck = schemas.resolve_grounding(req.customer, req.campaign)
    system_prompt = concierge.build_system_prompt(cust, ck, req.language)
    history = [t.model_dump() for t in (req.history or [])]
    messages = concierge.build_messages_openai(system_prompt, history, req.message)

    async def _sse():
        try:
            async for piece in get_adapter().stream_chat(messages, max_new_tokens=req.max_new_tokens):
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 — surface to the client as an error event
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main() -> None:
    import uvicorn

    # The gateway is I/O-bound (it forwards to vLLM), so multiple workers are fine here —
    # but one is plenty since a single async worker handles many concurrent requests.
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, workers=1)


if __name__ == "__main__":
    main()
