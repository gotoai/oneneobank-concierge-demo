"""Configuration for the OneNeo Bank concierge web-app.

Loads ``web-app/.env`` and resolves the paths the app reads. Deliberately tiny and
import-safe so tests can import it cheaply.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# web-app/ (this file is app/config.py -> parents[1] is web-app/)
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# Repo root = oneneobank-concierge-demo/ (web-app/ sibling of docs/, DATA/).
REPO_ROOT = BASE_DIR.parent


def _path(env: str, default: Path) -> Path:
    val = os.getenv(env)
    return Path(val).expanduser().resolve() if val else default


# Authored source of truth: the profile Markdown.
PROFILES_DIR: Path = _path("PROFILES_DIR", (REPO_ROOT / "docs" / "profiles").resolve())
PERSONAS_MD = PROFILES_DIR / "Personas.md"
CAMPAIGNS_MD = PROFILES_DIR / "Campaigns.md"
MATRIX_MD = PROFILES_DIR / "Persona-campaign-matrix.md"

# Compiled facts (reproducible; produced by `make facts`). Optional — the app still
# runs without it, just without reward summaries.
DATA_DIR: Path = _path("DATA_DIR", (REPO_ROOT / "DATA").resolve())
CAMPAIGNS_YAML = DATA_DIR / "campaigns.yaml"
TRANSACTIONS_YAML = DATA_DIR / "transactions.yaml"

# This app's bind address (0.0.0.0 so other machines on the LAN can reach it).
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("WEB_PORT", "8090"))

UI_LANGUAGE: str = os.getenv("UI_LANGUAGE", "ja")

# The agent-service web API (agent.api) that answers concierge chat. The web-app
# proxies chat requests to it server-side, so the bearer key never reaches the
# browser and there is no cross-origin call from the page. If the key is empty the
# agent-service runs unauthenticated (dev) and no Authorization header is sent.
AGENT_API_URL: str = os.getenv("AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/")
GOTOAI_AGENT_API_KEY: str = os.getenv("GOTOAI_AGENT_API_KEY", "")
# Upper bound for a single concierge generation (seconds); a 12B reply can be slow.
AGENT_TIMEOUT: float = float(os.getenv("AGENT_TIMEOUT", "120"))
