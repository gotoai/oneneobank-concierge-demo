"""Interactive CLI for the OneNeo Bank concierge agent.

Plays the OneNeo Bank AI concierge and answers a named customer's questions about
one campaign, grounded in the compiled knowledge under DATA/ (see agent.data).

Run from agent-service/ (model + .env/HF_HOME come from agent.config / agent.llm):

    .venv/bin/python -m agent.cli                         # prompts for customer + campaign
    .venv/bin/python -m agent.cli Aoi CMP-DEP-2026Q3-01   # positional args
    .venv/bin/python -m agent.cli --customer Aoi --campaign CMP-DEP-2026Q3-01

Both the customer name and campaign id may be given as positional args or via the
--customer / --campaign flags; anything omitted is asked interactively at startup.

Chat commands:  /profile  show the grounding profile   ·   /reset  clear history
                /exit (or Ctrl-D)  quit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_AGENT_SERVICE = Path(__file__).resolve().parents[1]
if str(_AGENT_SERVICE) not in sys.path:
    sys.path.insert(0, str(_AGENT_SERVICE))

from agent import concierge, config, data      # noqa: E402


# --------------------------------------------------------------------------- #
# Startup resolution of customer + campaign (args, else interactive prompt)
# --------------------------------------------------------------------------- #
def _prompt(label: str, choices: list[str]) -> str:
    """Ask the user to pick from `choices` (accepts the value or a 1-based index)."""
    if not sys.stdin.isatty():
        raise SystemExit(f"No {label} given and stdin is not a TTY. Pass it as an argument.")
    print(f"\nAvailable {label}s:", file=sys.stderr)
    for i, c in enumerate(choices, 1):
        print(f"  {i:2}. {c}", file=sys.stderr)
    while True:
        raw = input(f"Choose {label} (name or number): ").strip()
        if not raw:
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        return raw  # let the resolver validate a typed value (case-insensitive)


def _resolve_customer(name: str | None) -> data.Customer:
    while True:
        if not name:
            name = _prompt("customer", data.customer_names())
        cust = data.find_customer(name)
        if cust:
            return cust
        print(f"Unknown customer {name!r}. Known: {', '.join(data.customer_names())}",
              file=sys.stderr)
        name = None


def _resolve_campaign(campaign_id: str | None) -> data.CampaignKnowledge:
    while True:
        if not campaign_id:
            campaign_id = _prompt("campaign", data.campaigns_with_kb() or data.campaign_ids())
        cid = data.find_campaign(campaign_id)
        if cid:
            return data.load_campaign(cid)
        print(f"Unknown campaign {campaign_id!r}. Known: {', '.join(data.campaign_ids())}",
              file=sys.stderr)
        campaign_id = None


# --------------------------------------------------------------------------- #
# REPL
# --------------------------------------------------------------------------- #
def _run_repl(customer: data.Customer, ck: data.CampaignKnowledge) -> int:
    from agent.llm import get_llm  # deferred: importing loads torch/transformers

    system_prompt = concierge.build_system_prompt(customer, ck)

    print(f"Loading {config.MODEL_ID} (4-bit) ... this takes a moment.", file=sys.stderr, flush=True)
    llm = get_llm()

    qa_n = len(ck.kb.get("qa", []))
    print(f"\nOneNeo concierge ready — お客さま: {customer.name}（{customer.persona_id}） / "
          f"キャンペーン: {ck.campaign_id}（{ck.campaign_name}）")
    print(f"Grounded on {qa_n} vetted Q&A + product/campaign facts. "
          f"Ask in Japanese. Commands: /profile, /reset, /exit.\n")

    history: list[dict] = []
    while True:
        try:
            user_input = input(f"{customer.name}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_input:
            continue
        if user_input == "/exit":
            print("Bye.")
            break
        if user_input == "/reset":
            history = []
            print("(conversation cleared)\n")
            continue
        if user_input == "/profile":
            print("\n" + system_prompt + "\n")
            continue

        print("\nConcierge> ", end="", flush=True)
        pieces: list[str] = []
        for piece in llm.generate_stream(concierge.build_messages(system_prompt, history, user_input)):
            pieces.append(piece)
            print(piece, end="", flush=True)
        answer = "".join(pieces).strip()
        print("\n")
        history.append({"role": "user", "text": user_input})
        history.append({"role": "assistant", "text": answer})

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("customer", nargs="?", default=None,
                    help="customer given name, e.g. Aoi (asked interactively if omitted)")
    ap.add_argument("campaign", nargs="?", default=None,
                    help="campaign id, e.g. CMP-DEP-2026Q3-01 (asked interactively if omitted)")
    ap.add_argument("--customer", dest="customer_flag", default=None, help="customer given name")
    ap.add_argument("--campaign", dest="campaign_flag", default=None, help="campaign id")
    args = ap.parse_args()

    customer = _resolve_customer(args.customer_flag or args.customer)
    ck = _resolve_campaign(args.campaign_flag or args.campaign)
    return _run_repl(customer, ck)


if __name__ == "__main__":
    sys.exit(main())
