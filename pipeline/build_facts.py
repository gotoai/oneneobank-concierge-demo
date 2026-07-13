#!/usr/bin/env python3
"""Build the agent's structured data from the profile Markdown (the source of truth).

Reads the ```yaml facts``` blocks embedded in docs/profiles/**.md and emits:

- DATA/products.yaml   — deposit / card-loan / debit facts for the simulation tools.
- DATA/campaigns.yaml  — the campaigns with their reward-rule schema.

The authored configuration lives in the ```yaml facts``` blocks in the MD (committed);
these YAMLs are reproducible output compiled from them, so they live under DATA/
(git-ignored) and are rebuilt by re-running this script.

It also **validates drift**: structural sanity checks on the facts, plus spot-checks
that compare the facts blocks against the human-readable prose/tables in the same
docs, so an edit to one that isn't mirrored in the other is caught.

Usage:
    .venv/bin/python pipeline/build_facts.py [--check]

    --check   validate only; do not write (exit non-zero if any ERROR).

The facts blocks are the machine-readable truth; the surrounding prose is for humans.
Keep them in sync — this tool tells you when they drift.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "docs" / "profiles"
OUT = ROOT / "DATA"

# Match a fenced block whose info string contains the word "facts", capture its body.
FACTS_BLOCK = re.compile(r"^```[^\n]*\bfacts\b[^\n]*\n(.*?)\n```", re.DOTALL | re.MULTILINE)

REWARD_TYPES = {"flat_per_condition", "per_unit_capped", "tiered_replace"}


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def extract_facts(md_text: str) -> list[dict]:
    """Parse every ```yaml facts``` block in a Markdown string."""
    out = []
    for body in FACTS_BLOCK.findall(md_text):
        data = yaml.safe_load(body)
        if isinstance(data, dict):
            out.append(data)
    return out


def collect() -> tuple[dict, list, list[str]]:
    """Walk the profile docs, returning (products, campaigns, source-file list)."""
    products: dict = {}
    campaigns: list = []
    sources: list[str] = []
    for md in sorted(PROFILES.rglob("*.md")):
        blocks = extract_facts(md.read_text(encoding="utf-8"))
        if blocks:
            sources.append(str(md.relative_to(ROOT)))
        for block in blocks:
            if "product" in block:
                name = block.pop("product")
                products[name] = block
            if "campaigns" in block:
                campaigns.extend(block["campaigns"])
    return products, campaigns, sources


# --------------------------------------------------------------------------- #
# Validation — structural
# --------------------------------------------------------------------------- #
def validate_structure(products: dict, campaigns: list) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    def err(m):
        issues.append(("ERROR", m))

    def warn(m):
        issues.append(("WARN", m))

    # --- deposits ---
    dep = products.get("deposits")
    if not dep:
        err("products.deposits missing")
    else:
        td = dep.get("time_deposit", {})
        terms = set(td.get("term_months", []))
        rates = set(td.get("rate_by_term", {}))
        if terms != rates:
            err(f"deposits.time_deposit term_months {sorted(terms)} != rate_by_term keys {sorted(rates)}")
        if "tax_rate" not in dep:
            err("deposits.tax_rate missing")

    # --- card_loan ---
    loan = products.get("card_loan")
    if not loan:
        err("products.card_loan missing")
    else:
        tiers = loan.get("rate_tiers", [])
        ups = [t["up_to_jpy"] for t in tiers]
        rts = [t["rate"] for t in tiers]
        if ups != sorted(ups):
            err(f"card_loan.rate_tiers up_to_jpy not ascending: {ups}")
        if rts != sorted(rts, reverse=True):
            warn(f"card_loan.rate_tiers rate not non-increasing (larger loan should be cheaper): {rts}")
        if tiers and tiers[-1]["up_to_jpy"] != loan.get("limit_max_jpy"):
            err(f"card_loan.limit_max_jpy {loan.get('limit_max_jpy')} != top tier {tiers[-1]['up_to_jpy']}")

    # --- debit_card ---
    deb = products.get("debit_card")
    if not deb:
        err("products.debit_card missing")
    else:
        for k in ("cashback_rate", "fx_fee_rate"):
            if k not in deb:
                err(f"debit_card.{k} missing")

    # --- campaigns ---
    seen = set()
    for c in campaigns:
        cid = c.get("id", "<no-id>")
        if cid in seen:
            err(f"duplicate campaign id {cid}")
        seen.add(cid)
        p = c.get("period", {})
        if p.get("from") and p.get("to") and str(p["from"]) > str(p["to"]):
            err(f"{cid}: period from > to")
        r = c.get("reward", {})
        rtype = r.get("type")
        if rtype not in REWARD_TYPES:
            err(f"{cid}: reward.type '{rtype}' not in {sorted(REWARD_TYPES)}")
        if rtype == "flat_per_condition":
            total = sum(cond["amount"] for cond in r.get("conditions", []))
            if "cap" in r and total != r["cap"]:
                warn(f"{cid}: sum of condition amounts {total} != cap {r['cap']}")
        if rtype == "per_unit_capped":
            if r.get("amount_per_unit") and r.get("cap", 0) % r["amount_per_unit"]:
                warn(f"{cid}: cap {r['cap']} not a multiple of amount_per_unit {r['amount_per_unit']}")
        if rtype == "tiered_replace":
            th = [t["spend_ge_jpy"] for t in r.get("tiers", [])]
            am = [t["amount"] for t in r.get("tiers", [])]
            if th != sorted(th) or am != sorted(am):
                warn(f"{cid}: tiered_replace tiers not ascending (threshold/amount): {th}/{am}")
    return issues


# --------------------------------------------------------------------------- #
# Validation — prose spot-checks (facts block vs. the human text in the doc)
# --------------------------------------------------------------------------- #
def read(md_rel: str) -> str:
    return (PROFILES / md_rel).read_text(encoding="utf-8")


def validate_prose(products: dict, campaigns: list) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    def drift(m):
        issues.append(("DRIFT", m))

    # Deposits: 定期 table + 普通 rate
    dtxt = read("products/Deposits.md")
    td = products["deposits"]["time_deposit"]["rate_by_term"]
    for n, unit, pct in re.findall(r"\|\s*(\d+)(か月|年)\s*\|\s*年([\d.]+)%\s*\|", dtxt):
        months = int(n) * (12 if unit == "年" else 1)
        want = round(float(pct) / 100, 6)
        if months in td and round(td[months], 6) != want:
            drift(f"Deposits.md 定期 {n}{unit}: prose {want} != facts {td[months]}")
    m = re.search(r"適用金利:\s*年([\d.]+)%", dtxt)
    if m and round(float(m.group(1)) / 100, 6) != round(products["deposits"]["ordinary"]["interest_rate"], 6):
        drift(f"Deposits.md 普通 rate prose {m.group(1)}% != facts {products['deposits']['ordinary']['interest_rate']}")

    # Lending: rate bullets
    ltxt = read("products/Lending.md")
    tiers = {t["up_to_jpy"]: t["rate"] for t in products["card_loan"]["rate_tiers"]}
    for _lo, hi, pct in re.findall(r"(\d+)万円[~〜](\d+)万円:\s*年([\d.]+)%", ltxt):
        up = int(hi) * 10000
        want = round(float(pct) / 100, 6)
        if up in tiers and round(tiers[up], 6) != want:
            drift(f"Lending.md tier ~{hi}万円: prose {want} != facts {tiers[up]}")

    # Debit: cashback + fx
    btxt = read("products/Debit-card.md")
    deb = products["debit_card"]
    m = re.search(r"還元率\s*([\d.]+)%", btxt)
    if m and round(float(m.group(1)) / 100, 6) != round(deb["cashback_rate"], 6):
        drift(f"Debit-card.md 還元率 prose {m.group(1)}% != facts {deb['cashback_rate']}")
    m = re.search(r"海外事務処理手数料:\s*利用金額に対して\s*([\d.]+)%", btxt)
    if m and round(float(m.group(1)) / 100, 6) != round(deb["fx_fee_rate"], 6):
        drift(f"Debit-card.md 海外手数料 prose {m.group(1)}% != facts {deb['fx_fee_rate']}")

    # Campaigns: caps appear in prose, and the debit base-cashback mention matches the product
    ctxt = read("Campaigns.md")
    for c in campaigns:
        cap = c.get("reward", {}).get("cap")
        if cap and f"{cap:,}円" not in ctxt:
            drift(f"{c['id']}: cap {cap:,}円 not found verbatim in Campaigns.md prose")
    m = re.search(r"通常のポイント還元（([\d.]+)%）", ctxt)
    if m and round(float(m.group(1)) / 100, 6) != round(deb["cashback_rate"], 6):
        drift(f"Campaigns.md base-cashback prose {m.group(1)}% != debit facts {deb['cashback_rate']} "
              "(update the campaign prose to match the product doc)")
    return issues


# --------------------------------------------------------------------------- #
def dump_yaml(path: Path, data) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="validate only, do not write")
    args = ap.parse_args()

    products, campaigns, sources = collect()
    issues = validate_structure(products, campaigns) + validate_prose(products, campaigns)

    for level, msg in issues:
        print(f"[{level}] {msg}", file=sys.stderr)

    errors = [i for i in issues if i[0] == "ERROR"]
    if errors:
        print(f"\n{len(errors)} error(s) — not writing.", file=sys.stderr)
        sys.exit(1)

    if args.check:
        print(f"check ok: {len(products)} products, {len(campaigns)} campaigns "
              f"from {len(sources)} docs; {len(issues)} non-fatal note(s).")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    dump_yaml(OUT / "products.yaml", products)
    dump_yaml(OUT / "campaigns.yaml", {"campaigns": campaigns})
    print(f"Wrote {OUT}/products.yaml ({len(products)} products) and "
          f"campaigns.yaml ({len(campaigns)} campaigns). {len(issues)} note(s).")


if __name__ == "__main__":
    main()
