"""In-memory data layer for the web-app.

Parses the authored profile Markdown (docs/profiles) into the small structures the
two tab pages need:

  * spotlight personas (S01..)  — id, name, type label, age/gender, generated avatar.
  * campaigns (CMP-..)          — id, title, category, description, period, reward cap.

The Markdown is the source of truth; this layer only reads it. Loaded once and cached.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from . import config

# --- persona parsing ---------------------------------------------------------
# ### S01 — Aoi（初任給で貯蓄を始める）            [· *難ケース: 融資*]
_PERSONA_H = re.compile(
    r"^###\s+(S\d+)\s+—\s+([^（(]+)[（(]([^）)]+)[）)]"
    r"(?:\s*·\s*\*([^*]+)\*)?\s*$",
    re.MULTILINE,
)
_AGE_GENDER = re.compile(r"年齢\s*/\s*性別:\*\*\s*(\d+)\s*/\s*(女性|男性)")
_JOB = re.compile(r"職業:\*\*\s*([^·\n]+)")

# --- campaign parsing --------------------------------------------------------
# ### CMP-DEP-2026Q3-01 — 口座開設・普通預金応援キャッシュバック
_CAMPAIGN_H = re.compile(r"^###\s+(CMP-[A-Z0-9-]+?)\s+—\s+(.+?)\s*$", re.MULTILINE)
_PERIOD = re.compile(r"対象期間:\*\*\s*([^\n]+)")

_CATEGORY = {
    "DEP": ("預金", "💰"),
    "LOAN": ("カードローン", "🤝"),
    "DEBIT": ("デビットカード", "💳"),
}


def _avatar_color(seed: str) -> str:
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 360
    return f"hsl({h}, 60%, 52%)"


def _avatar_emoji(gender: str, age: int) -> str:
    if age >= 60:
        return "👵" if gender == "女性" else "👴"
    return "👩" if gender == "女性" else "👨"


def _block_after(text: str, start: int, end: int) -> str:
    return text[start:end]


def parse_personas(md_path: Path) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    matches = list(_PERSONA_H.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(matches):
        pid, name, type_label, hard = m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4)
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _block_after(text, m.end(), block_end)
        ag = _AGE_GENDER.search(block)
        age = int(ag.group(1)) if ag else 0
        gender = ag.group(2) if ag else ""
        job = _JOB.search(block)
        out.append({
            "id": pid,
            "name": name,
            "type_label": type_label,
            "hard_case": (hard or "").strip() or None,
            "age": age,
            "gender": gender,
            "job": job.group(1).strip() if job else "",
            "emoji": _avatar_emoji(gender, age),
            "color": _avatar_color(pid),
        })
    return out


@lru_cache(maxsize=1)
def _campaign_caps() -> dict[str, int]:
    """id -> reward cap (JPY), from the compiled DATA/campaigns.yaml if present."""
    if not config.CAMPAIGNS_YAML.exists():
        return {}
    import yaml
    doc = yaml.safe_load(config.CAMPAIGNS_YAML.read_text(encoding="utf-8")) or {}
    caps: dict[str, int] = {}
    for c in doc.get("campaigns", []):
        cap = (c.get("reward") or {}).get("cap")
        if isinstance(cap, int):
            caps[c["id"]] = cap
    return caps


def parse_campaigns(md_path: Path) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    matches = list(_CAMPAIGN_H.finditer(text))
    caps = _campaign_caps()
    out: list[dict] = []
    for i, m in enumerate(matches):
        cid, title = m.group(1), m.group(2).strip()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _block_after(text, m.end(), block_end)
        # First non-empty, non-bullet line under the heading = the description.
        desc = ""
        for line in block.splitlines():
            s = line.strip()
            if s and not s.startswith(("-", ">", "|", "```", "<!--")):
                desc = s
                break
        period = _PERIOD.search(block)
        prefix = cid.split("-")[1] if "-" in cid else ""
        cat_label, icon = _CATEGORY.get(prefix, ("キャンペーン", "🎁"))
        out.append({
            "id": cid,
            "title": title,
            "category": cat_label,
            "icon": icon,
            "description": desc,
            "period": period.group(1).strip() if period else "",
            "cap": caps.get(cid),
        })
    return out


class Data:
    def __init__(self) -> None:
        self.personas = parse_personas(config.PERSONAS_MD)
        self.campaigns = parse_campaigns(config.CAMPAIGNS_MD)


@lru_cache(maxsize=1)
def get_data() -> Data:
    return Data()
