"""Shared HTTP surface for the concierge agent-service APIs.

Both backends expose an IDENTICAL ``/v1/*`` contract:
  * agent.api        — the in-process transformers backend (one model per process,
                       serialized on a GPU lock).
  * agent.api_vllm   — the vLLM gateway (model in a separate `vllm serve` process,
                       concurrency via vLLM continuous batching).

The request/response models, bearer auth, grounding resolution, and the
backend-agnostic (no-LLM) endpoint bodies live here so the two APIs stay byte-for-byte
compatible and cannot drift. This module is torch-free — it imports only the pure data
and concierge layers — so both APIs import cheaply.

Only the LLM-touching parts (chat / chat-stream) and readiness differ between backends;
those stay in each api module.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from . import concierge, config, data


# --------------------------------------------------------------------------- models
class ChatTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'.")
    text: str = ""


class ChatRequest(BaseModel):
    """One concierge turn, grounded on a named customer + campaign.

    ``history`` carries the prior turns (oldest first) so multi-turn context is
    preserved across stateless requests — the same shape the CLI keeps in memory.
    """
    customer: str = Field(..., min_length=1, description="Customer given name, e.g. Aoi.")
    campaign: str = Field(..., min_length=1, description="Campaign id, e.g. CMP-DEP-2026Q3-01.")
    message: str = Field(..., min_length=1, description="The customer's question.")
    history: list[ChatTurn] | None = Field(None, description="Prior turns (oldest first).")
    language: str = Field("ja", description="Reply language: 'ja' or 'en' (default 'ja').")
    max_new_tokens: int = Field(config.MAX_NEW_TOKENS, ge=1, le=8192)


class ChatResponse(BaseModel):
    message: str
    customer: str
    persona_id: str
    campaign_id: str
    campaign_name: str
    language: str
    model_id: str


class ProfileRequest(BaseModel):
    customer: str = Field(..., min_length=1, description="Customer given name, e.g. Aoi.")
    campaign: str = Field(..., min_length=1, description="Campaign id, e.g. CMP-DEP-2026Q3-01.")
    language: str = Field("ja", description="Reply language: 'ja' or 'en' (default 'ja').")


class ProfileResponse(BaseModel):
    system_prompt: str
    customer: str
    persona_id: str
    campaign_id: str
    campaign_name: str
    language: str
    qa_count: int


class CustomerInfo(BaseModel):
    name: str
    persona_id: str
    scenario: str


class CustomersResponse(BaseModel):
    customers: list[CustomerInfo]


class CampaignInfo(BaseModel):
    campaign_id: str
    has_kb: bool = Field(..., description="Whether a compiled Q&A KB exists (answerable).")


class CampaignsResponse(BaseModel):
    campaigns: list[CampaignInfo]


# --------------------------------------------------------------------------- auth
def require_auth(authorization: str | None = Header(None)) -> None:
    """Enforce `Authorization: Bearer <GOTOAI_AGENT_API_KEY>` when a key is configured."""
    key = config.GOTOAI_AGENT_API_KEY
    if not key:  # auth disabled (dev) — startup already warned
        return
    expected = f"Bearer {key}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


# --------------------------------------------------------------------------- grounding
def resolve_grounding(customer: str, campaign: str) -> tuple[data.Customer, data.CampaignKnowledge]:
    """Look up the customer + campaign, or raise 404 with the known options.

    The data layer raises SystemExit for a missing campaign/KB; translate that (and an
    unknown customer) into a clean 404 so a bad request never takes the process down.
    """
    cust = data.find_customer(customer)
    if cust is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown customer {customer!r}; known: {', '.join(data.customer_names())}",
        )
    if data.find_campaign(campaign) is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown campaign {campaign!r}; known: {', '.join(data.campaign_ids())}",
        )
    try:
        ck = data.load_campaign(campaign)
    except SystemExit as exc:  # campaign known but its Q&A KB isn't compiled yet
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return cust, ck


# ------------------------------------------------------------- backend-agnostic bodies
# The metadata + profile endpoints do no generation, so both backends share their
# bodies verbatim; each api module just registers the routes that call these.
def list_customers() -> CustomersResponse:
    """List the spotlight customers the concierge can be grounded on."""
    infos = [CustomerInfo(name=c.name, persona_id=c.persona_id, scenario=c.scenario)
             for c in data.customers().values()]
    return CustomersResponse(customers=infos)


def list_campaigns() -> CampaignsResponse:
    """List campaigns and whether each has an answerable Q&A KB."""
    with_kb = set(data.campaigns_with_kb())
    infos = [CampaignInfo(campaign_id=cid, has_kb=cid in with_kb) for cid in data.campaign_ids()]
    return CampaignsResponse(campaigns=infos)


def build_profile(req: ProfileRequest) -> ProfileResponse:
    """Return the grounded system prompt for a customer + campaign (the CLI's /profile)."""
    cust, ck = resolve_grounding(req.customer, req.campaign)
    language = concierge.normalize_language(req.language)
    system_prompt = concierge.build_system_prompt(cust, ck, language)
    return ProfileResponse(
        system_prompt=system_prompt, customer=cust.name, persona_id=cust.persona_id,
        campaign_id=ck.campaign_id, campaign_name=ck.campaign_name,
        language=language, qa_count=len(ck.kb.get("qa", [])),
    )
