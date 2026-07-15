"""Concierge logic: turn a customer + campaign into a grounded chat.

The agent plays the OneNeo Bank AI concierge and answers one named customer's
questions about one campaign. All grounding — who the customer is, the campaign
rules, the vetted Q&A knowledge base, and the product facts — is assembled here
into the system message; the LLM (agent.llm) only generates the reply.

Design notes:
- Answers are grounded strictly in the provided knowledge. The KB is authored in
  である調 (internal style); the concierge re-voices it politely (ですます調) to the
  customer, and personalises using the customer's profile / recent transactions.
- The KB flags some answers as ``interpretation: true`` (documented logic, not
  explicit wording); the concierge hedges those.
- When something is not documented, the concierge follows the KB's answer policy:
  say it cannot answer with certainty rather than inventing — never fabricate rates,
  amounts, dates, or eligibility.
"""
from __future__ import annotations

import yaml

from .data import Customer, CampaignKnowledge

# Show at most this many recent transactions in the grounding context.
_MAX_TX = 8


def text_message(role: str, text: str) -> dict:
    """A single text-only chat message in Gemma's content-parts format.

    Defined here (not imported from agent.llm) so this module stays torch-free.
    """
    return {"role": role, "content": [{"type": "text", "text": text}]}

# Output-language directives. The grounded knowledge below is authored in Japanese
# regardless of language; only the reply language changes. `ja` keeps the original
# polite ですます調 behaviour; `en` instructs a faithful English translation.
DEFAULT_LANGUAGE = "ja"
_LANG_STYLE = {
    "ja": {
        "style_intro": "回答は必ず日本語の丁寧な「ですます調」で行います。",
        "revoice": (
            "ナレッジは内部用に「である調」で書かれています。内容は変えずに、丁寧な"
            "「ですます調」に言い換えてお客さまに伝えます。"
        ),
    },
    "en": {
        "style_intro": (
            "Always reply in natural, polite English, even though all the knowledge "
            "below is written in Japanese. （回答は必ず英語で行います。）"
        ),
        "revoice": (
            "The knowledge below is authored in Japanese for internal use. Translate it "
            "faithfully into polite English for the customer, WITHOUT changing any facts "
            "(amounts, rates, dates, eligibility, or proper nouns). Keep official product "
            "and campaign names accurate; you may add the original Japanese in parentheses "
            "when it helps."
        ),
    },
}


def normalize_language(language: str | None) -> str:
    """Map an incoming language code to a supported one ('ja' or 'en'); default 'ja'."""
    code = (language or "").strip().lower()
    return code if code in _LANG_STYLE else DEFAULT_LANGUAGE


SYSTEM_TEMPLATE = """\
あなたは「OneNeo Bank」のAIコンシェルジュです。モバイルアプリ上で、お客さま
**{customer_name} さま** の質問に対応します。{style_intro}
対象キャンペーンは **{campaign_id}（{campaign_name}）** です。

# 役割と話し方
- OneNeo Bank のコンシェルジュとして、{customer_name} さま本人に向けて回答します。
- 簡潔で、親しみやすく、正確に。長すぎる説明は避け、必要なら箇条書きを使います。
- お客さまのプロフィールや最近の取引が関係する場合は、それを踏まえて具体的に案内します。

# 回答の根拠（厳守）
- 回答は必ず下記「ナレッジ」の記載のみを根拠にします。金額・料率・期日・対象条件を
  自分で創作しないでください。
- {revoice_directive}
- Q&A で `interpretation: true` が付く項目は、明文化されていない論理的な解釈です。
  「規定上明記はありませんが」等の一言を添えて丁寧に扱ってください。
- ナレッジに根拠が無い、または確信を持って答えられない質問には、推測で答えず
  「申し訳ございません、その点は確認のうえ改めてご案内します」と正直に伝えます
  （＝社内での文書追記が必要な事項）。
- 融資の可否・税務・法務など断定を避けるべき事項は、ナレッジの範囲で説明し、
  必要に応じて公式窓口・所轄先の確認を案内します。

# ナレッジ
## お客さまプロフィール（{customer_name} さま / {persona_id}）
{customer_profile}

## 最近のお取引（as of {as_of}）
{customer_tx}

## キャンペーンの構造化ルール（campaigns.yaml）
{campaign_facts}

## キャンペーンQ&Aナレッジ（{campaign_id}）
{campaign_kb}

## 商品情報（products.yaml）
{product_facts}
"""


def _yaml(obj) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=100).rstrip()


def _yen(value, signed: bool = False) -> str:
    """Format a JPY amount with thousands separators; degrade gracefully."""
    if not isinstance(value, (int, float)):
        return str(value)
    return f"{value:+,}" if signed else f"{value:,}"


def _format_transactions(customer: Customer) -> str:
    if not customer.transactions:
        return "（取引履歴なし）"
    lines = []
    for t in customer.transactions[:_MAX_TX]:
        lines.append(
            f"- {t.get('date','')}  {t.get('description','')}"
            f"（{t.get('category','')}/{t.get('type','')}）  {_yen(t.get('amount', 0), signed=True)}円"
            f"  残高 {_yen(t.get('balance', ''))}円"
        )
    return "\n".join(lines)


def build_system_prompt(
    customer: Customer, ck: CampaignKnowledge, language: str = DEFAULT_LANGUAGE,
) -> str:
    """Assemble the grounded system message for this customer + campaign.

    `language` ('ja' or 'en') selects the reply language; the grounded knowledge is
    Japanese either way (see `_LANG_STYLE`). Unknown codes fall back to Japanese.
    """
    style = _LANG_STYLE[normalize_language(language)]
    kb_for_prompt = {
        "answer_policy": ck.kb.get("answer_policy"),
        "premise": ck.kb.get("premise"),
        "qa": ck.kb.get("qa", []),
    }
    return SYSTEM_TEMPLATE.format(
        customer_name=customer.name,
        persona_id=customer.persona_id,
        campaign_id=ck.campaign_id,
        campaign_name=ck.campaign_name,
        style_intro=style["style_intro"],
        revoice_directive=style["revoice"],
        customer_profile=customer.profile_md or "（プロフィール情報なし）",
        customer_tx=_format_transactions(customer),
        as_of=customer.as_of or "—",
        campaign_facts=_yaml(ck.facts),
        campaign_kb=_yaml(kb_for_prompt),
        product_facts=_yaml(ck.products),
    )


def build_messages(system_prompt: str, history: list[dict], user_input: str) -> list[dict]:
    """system + prior turns + the new user question, in Gemma content-parts format."""
    messages = [text_message("system", system_prompt)]
    for turn in history:
        messages.append(text_message(turn["role"], turn["text"]))
    messages.append(text_message("user", user_input))
    return messages
