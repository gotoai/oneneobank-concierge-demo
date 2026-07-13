"""FastAPI app for the OneNeo Bank concierge demo — a mobile-style shell.

Initial scope: two tab pages rendered server-side.
  * ペルソナ    — the spotlight personas (avatar, name, type label).
  * キャンペーン — the campaigns (category, title, period, reward cap).

All content is parsed from the profile Markdown (the source of truth) via the data
layer. JSON endpoints mirror the same data for future JS use.
"""
from __future__ import annotations

import textwrap

import markdown as md
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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


@app.get("/ui/campaign/{campaign_id}", response_class=HTMLResponse)
async def ui_campaign_detail(request: Request, campaign_id: str) -> HTMLResponse:
    """Detail fragment for one campaign, rendered from its Markdown block (the SoT)."""
    c = data.campaign_by_id(campaign_id)
    if c is None:
        return HTMLResponse("<p class='error'>不明なキャンペーンです。</p>", status_code=404)
    # Dedent the 2-space-indented block so Markdown parses lists/tables correctly.
    body_html = md.markdown(textwrap.dedent(c["raw_md"]), extensions=["tables"])
    return templates.TemplateResponse(request, "_campaign_detail.html", {
        "c": c, "body_html": body_html,
    })


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
