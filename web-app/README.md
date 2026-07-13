# OneNeo Bank concierge — web-app

A mobile-style demo front-end for the OneNeo Bank concierge. Server-rendered with
**FastAPI + Jinja2** (vanilla CSS/JS, no build step), mirroring the reference stack.

## Tabs (initial scope)
- **ペルソナ** — the spotlight personas (S01–S17): generated avatar, name, type label,
  age/gender.
- **キャンペーン** — the campaigns (CMP-…): category, title, period, and reward cap.

All content is parsed from the authored Markdown in `../docs/profiles/`
(`Personas.md`, `Campaigns.md`) — the source of truth. Reward caps come from the
compiled `../DATA/campaigns.yaml` (run `make facts` at the repo root; optional).

## Run
```bash
cd web-app
make install         # creates .venv, installs requirements
make dev             # autoreload on http://localhost:8090
# or: make serve
```

Open http://localhost:8090 (best viewed narrow, like a phone).

## Layout
```
web-app/
  app/
    config.py     # paths + env (points at ../docs/profiles and ../DATA)
    data.py       # parses personas + campaigns from the Markdown
    main.py       # FastAPI: page + /api/personas + /api/campaigns + /healthz
    templates/index.html
    static/{styles.css,app.js}
  requirements.txt  Makefile  .env.example
```

The app owns no model and computes no numbers — it only reads and presents the
profile content.
