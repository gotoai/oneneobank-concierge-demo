"""FastAPI app for the OneNeo Bank concierge demo — a mobile-style shell.

Initial scope: two tab pages rendered server-side.
  * ペルソナ    — the spotlight personas (avatar, name, type label).
  * キャンペーン — the campaigns (category, title, period, reward cap).

All content is parsed from the profile Markdown (the source of truth) via the data
layer. JSON endpoints mirror the same data for future JS use.
"""
from __future__ import annotations

import json
import textwrap

import httpx
import markdown as md
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import config, data

app = FastAPI(title="OneNeo Bank concierge web-app", version="0.1.0")

templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "app" / "static")), name="static")


def _d() -> data.Data:
    return data.get_data()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    d = _d()
    return templates.TemplateResponse(request, "index.html", {
        "personas": d.personas,
        "campaigns": d.campaigns,
        "ui_language": config.UI_LANGUAGE,
    })


def _campaign_body_html(c: dict) -> str:
    """Render a campaign's Markdown block to HTML (dedented so lists/tables parse)."""
    return md.markdown(textwrap.dedent(c["raw_md"]), extensions=["tables"])


@app.get("/ui/campaign/{campaign_id}", response_class=HTMLResponse)
async def ui_campaign_detail(request: Request, campaign_id: str) -> HTMLResponse:
    """Plain detail fragment (used from the directory tab)."""
    c = data.campaign_by_id(campaign_id)
    if c is None:
        return HTMLResponse("<p class='error'>不明なキャンペーンです。</p>", status_code=404)
    return templates.TemplateResponse(request, "_campaign_detail.html", {
        "c": c, "body_html": _campaign_body_html(c),
    })


@app.get("/ui/campaign/{campaign_id}/concierge", response_class=HTMLResponse)
async def ui_campaign_concierge(
    request: Request, campaign_id: str, persona_id: str | None = None,
) -> HTMLResponse:
    """Customer-facing split view: campaign detail on top, concierge chat below.

    Opened from a persona's home screen, so ``persona_id`` names the customer the
    chat is grounded on; it is threaded into the template and back to the chat
    endpoint, which proxies to the agent-service."""
    c = data.campaign_by_id(campaign_id)
    if c is None:
        return HTMLResponse("<p class='error'>不明なキャンペーンです。</p>", status_code=404)
    persona = data.persona_by_id(persona_id) if persona_id else None
    return templates.TemplateResponse(request, "_campaign_concierge.html", {
        "c": c, "body_html": _campaign_body_html(c), "persona": persona,
    })


class ConciergeChatRequest(BaseModel):
    """A concierge chat turn from the browser. ``history`` is the prior turns
    (oldest first), the same [{role, text}] shape the agent-service expects.
    ``language`` selects the reply language ('ja' or 'en')."""
    persona_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    history: list[dict] = Field(default_factory=list)
    language: str = Field("ja", description="Reply language: 'ja' or 'en'.")


def _sse_error(msg: str) -> bytes:
    """One Server-Sent-Events ``error`` frame, matching the agent-service framing."""
    return f"event: error\ndata: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n".encode()


@app.post("/ui/campaign/{campaign_id}/concierge/chat")
async def ui_campaign_concierge_chat(
    campaign_id: str, req: ConciergeChatRequest,
) -> StreamingResponse:
    """Proxy a concierge chat turn to the agent-service and stream the reply (SSE).

    The browser never talks to the agent-service directly: this maps persona_id ->
    customer given name, adds the bearer key server-side, and forwards the agent's
    ``/v1/chat/stream`` event stream through unchanged (delta / done / error frames).
    """
    c = data.campaign_by_id(campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="不明なキャンペーンです。")
    p = data.persona_by_id(req.persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail="不明なペルソナです。")

    payload = {
        "customer": p["name"],
        "campaign": campaign_id,
        "message": req.message,
        "language": req.language,
        "history": [{"role": h.get("role", ""), "text": h.get("text", "")}
                    for h in req.history],
    }
    headers = {}
    if config.GOTOAI_AGENT_API_KEY:
        headers["Authorization"] = f"Bearer {config.GOTOAI_AGENT_API_KEY}"
    url = f"{config.AGENT_API_URL}/v1/chat/stream"

    async def _relay():
        try:
            async with httpx.AsyncClient(timeout=config.AGENT_TIMEOUT) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        yield _sse_error(f"エージェント応答エラー ({resp.status_code}): {body[:300]}")
                        return
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.RequestError as exc:  # agent-service unreachable / timed out
            yield _sse_error(f"エージェントに接続できません: {exc}")

    return StreamingResponse(_relay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/ui/campaign/{campaign_id}/entry", response_class=HTMLResponse)
async def ui_campaign_entry(request: Request, campaign_id: str) -> HTMLResponse:
    """Campaign entry (エントリー) screen — the pre-registration form.

    Opened from the 「今すぐエントリー」 button in the concierge pane. UI-only for
    now (submitting does not persist anything)."""
    c = data.campaign_by_id(campaign_id)
    if c is None:
        return HTMLResponse("<p class='error'>不明なキャンペーンです。</p>", status_code=404)
    return templates.TemplateResponse(request, "_campaign_entry.html", {"c": c})


@app.get("/ui/persona/{persona_id}/home", response_class=HTMLResponse)
async def ui_persona_home(request: Request, persona_id: str) -> HTMLResponse:
    """The persona's mobile home screen (banner, balance, transactions, messages)."""
    home = data.persona_home(persona_id)
    if home is None:
        return HTMLResponse("<p class='error'>不明なペルソナです。</p>", status_code=404)
    return templates.TemplateResponse(request, "_persona_home.html", {"h": home})


@app.get("/api/personas")
async def api_personas() -> JSONResponse:
    return JSONResponse(_d().personas)


@app.get("/api/campaigns")
async def api_campaigns() -> JSONResponse:
    return JSONResponse(_d().campaigns)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "personas": len(_d().personas), "campaigns": len(_d().campaigns)}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT, workers=1)


if __name__ == "__main__":
    main()
