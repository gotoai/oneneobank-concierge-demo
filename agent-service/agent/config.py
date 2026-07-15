"""Runtime configuration for the concierge agent-service.

IMPORTANT: importing this module loads agent-service/.env into the environment. It
must be imported BEFORE torch/transformers, because huggingface_hub reads HF_HOME
once at import time — otherwise the model would re-download to the default cache.
`agent.llm` imports this module before importing torch, so that ordering holds.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load agent-service/.env (this file is agent-service/agent/config.py -> parents[1]).
try:
    from dotenv import load_dotenv

    _env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_env if _env.exists() else None)
except ImportError:  # python-dotenv not installed yet (e.g. syntax-only checks)
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Reduce CUDA fragmentation OOMs (must be set before torch initializes CUDA; this module
# is imported before torch in agent.llm). Harmless if already set by the user.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

MODEL_ID = os.environ.get("MODEL_ID", "google/gemma-4-12B-it")
HF_HOME = os.environ.get("HF_HOME", "")          # informational; already applied via .env
MAX_NEW_TOKENS = _int("MAX_NEW_TOKENS", 1024)
GEN_TEMPERATURE = _float("GEN_TEMPERATURE", 0.7)
GEN_TOP_P = _float("GEN_TOP_P", 0.95)

# Web-API bearer key. If set, /v1 endpoints require `Authorization: Bearer <key>`.
# If empty, auth is DISABLED (dev only) — the API logs a warning at startup.
GOTOAI_AGENT_API_KEY = os.environ.get("GOTOAI_AGENT_API_KEY", "")

# Web-API server (agent.api). Bind to 127.0.0.1 by default; put a reverse proxy or
# an explicit 0.0.0.0 in front only when you mean to expose it.
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = _int("API_PORT", 8000)
# Load the model at startup (so the first request is fast and /readyz is meaningful).
# Set API_EAGER_LOAD=0 to defer loading until the first request instead.
API_EAGER_LOAD = os.environ.get("API_EAGER_LOAD", "1").strip().lower() not in ("0", "false", "no", "")

# agent-service/ dir (config.py -> parents[1]); default home for local caches.
AGENT_SERVICE_DIR = Path(__file__).resolve().parents[1]

# Repo root (agent-service/agent/config.py -> parents[2]), for reading DATA/* and docs/*.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "DATA"
DOCS_DIR = REPO_ROOT / "docs"
