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

# Compiled facts (reproducible; produced by `make facts`). Optional — the app still
# runs without it, just without reward summaries.
DATA_DIR: Path = _path("DATA_DIR", (REPO_ROOT / "DATA").resolve())
CAMPAIGNS_YAML = DATA_DIR / "campaigns.yaml"

# This app's bind address (0.0.0.0 so other machines on the LAN can reach it).
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("WEB_PORT", "8090"))

UI_LANGUAGE: str = os.getenv("UI_LANGUAGE", "ja")
