"""Data layer for the concierge agent.

Loads the grounded knowledge the concierge needs, from the repo's compiled
artifacts (built by the pipeline; see ../Makefile) and the profile docs:

  * customers  — the spotlight personas (S01 Aoi … S17 Kaito): profile from
                 docs/profiles/Personas.md + recent transactions from
                 DATA/transactions.yaml, keyed by given name.
  * campaigns  — structured reward facts from DATA/campaigns.yaml.
  * products   — product facts from DATA/products.yaml.
  * kb         — the per-campaign customer Q&A knowledge base,
                 DATA/kb-<campaign-id>.yaml (built by pipeline/build_kb.py).

Everything is read-only. Missing artifacts raise a clear, actionable error
pointing at the `make` target that produces them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from . import config

# `### S01 — Aoi（初任給で貯蓄を始める）· *難ケース: 融資*`
_PERSONA_BLOCK = re.compile(
    r"^###\s+(S\d+)\s+—\s+([^（(\n]+?)\s*[（(]([^）)]*)[）)][^\n]*\n(.*?)(?=^###\s|^##\s|\Z)",
    re.DOTALL | re.MULTILINE,
)


def _load_yaml(name: str) -> dict:
    path = config.DATA_DIR / name
    if not path.exists():
        raise SystemExit(
            f"Missing data artifact: {path}\n"
            f"Build it from the repo root with `make {'kb' if name.startswith('kb-') else 'all'}`."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# --------------------------------------------------------------------------- #
# Customers (persona profile + transactions)
# --------------------------------------------------------------------------- #
@dataclass
class Customer:
    persona_id: str          # e.g. "S01"
    name: str                # e.g. "Aoi"
    scenario: str            # short parenthetical from the persona heading
    profile_md: str          # the persona's bullet block (Markdown), for grounding
    transactions: list[dict] = field(default_factory=list)  # recent tx, newest first
    as_of: str = ""          # transactions snapshot date


@lru_cache(maxsize=1)
def _personas() -> dict[str, dict]:
    """Parse the spotlight persona blocks from docs/profiles/Personas.md."""
    path = config.DOCS_DIR / "profiles" / "Personas.md"
    if not path.exists():
        raise SystemExit(f"Missing persona profiles: {path}")
    out: dict[str, dict] = {}
    for pid, name, scenario, body in _PERSONA_BLOCK.findall(path.read_text(encoding="utf-8")):
        out[pid] = {
            "id": pid,
            "name": name.strip(),
            "scenario": scenario.strip(),
            "profile_md": body.strip(),
        }
    return out


@lru_cache(maxsize=1)
def _transactions() -> tuple[dict[str, dict], str]:
    """DATA/transactions.yaml -> ({persona_id: {name, transactions}}, as_of)."""
    doc = _load_yaml("transactions.yaml")
    return doc.get("transactions", {}), doc.get("generated", {}).get("as_of", "")


@lru_cache(maxsize=1)
def customers() -> dict[str, Customer]:
    """All spotlight customers, keyed by lower-cased given name."""
    personas = _personas()
    tx_by_pid, as_of = _transactions()
    out: dict[str, Customer] = {}
    for pid, p in personas.items():
        tx = tx_by_pid.get(pid, {})
        out[p["name"].lower()] = Customer(
            persona_id=pid,
            name=p["name"],
            scenario=p["scenario"],
            profile_md=p["profile_md"],
            transactions=list(tx.get("transactions", [])),
            as_of=as_of,
        )
    return out


def find_customer(name: str) -> Customer | None:
    """Case-insensitive lookup by given name (e.g. 'Aoi', 'aoi')."""
    return customers().get(name.strip().lower())


def customer_names() -> list[str]:
    return [c.name for c in customers().values()]


# --------------------------------------------------------------------------- #
# Campaigns + product facts + knowledge base
# --------------------------------------------------------------------------- #
@dataclass
class CampaignKnowledge:
    campaign_id: str
    campaign_name: str
    facts: dict            # the structured campaign entry from campaigns.yaml
    kb: dict               # the Q&A knowledge base (premise, answer_policy, qa[])
    products: dict         # all product facts (small) — the answers reference these


@lru_cache(maxsize=1)
def _campaigns() -> dict[str, dict]:
    """DATA/campaigns.yaml -> {campaign_id: entry}."""
    doc = _load_yaml("campaigns.yaml")
    return {c["id"]: c for c in doc.get("campaigns", [])}


def campaign_ids() -> list[str]:
    return list(_campaigns())


def campaigns_with_kb() -> list[str]:
    """Campaign ids that have a compiled Q&A knowledge base (answerable ones)."""
    return [cid for cid in _campaigns()
            if (config.DATA_DIR / f"kb-{cid.lower()}.yaml").exists()]


def find_campaign(campaign_id: str) -> str | None:
    """Case-insensitive resolution of a campaign id to its canonical form."""
    wanted = campaign_id.strip().lower()
    for cid in _campaigns():
        if cid.lower() == wanted:
            return cid
    return None


def load_campaign(campaign_id: str) -> CampaignKnowledge:
    """Assemble the full grounding bundle for one campaign.

    Raises SystemExit (with guidance) if the campaign or its KB is missing.
    """
    cid = find_campaign(campaign_id)
    if cid is None:
        raise SystemExit(
            f"Unknown campaign {campaign_id!r}. Available: {', '.join(campaign_ids())}"
        )
    facts = _campaigns()[cid]
    kb = _load_yaml(f"kb-{cid.lower()}.yaml")
    return CampaignKnowledge(
        campaign_id=cid,
        campaign_name=kb.get("campaign_name") or cid,
        facts=facts,
        kb=kb,
        products=_load_yaml("products.yaml"),
    )
