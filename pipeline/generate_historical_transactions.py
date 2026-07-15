#!/usr/bin/env python3
"""Generate recent historical bank-account transactions for each spotlight persona.

Reads the personas from ``docs/profiles/Personas.md`` (the source of truth) and, for
each, generates the 10 most recent transactions (deterministic per persona, so the
output is reproducible). Writes ``DATA/transactions.yaml``.

Each transaction has: date, description, category, type (credit/debit), amount (JPY,
signed), and the running account balance after it.

Usage:
    .venv/bin/python pipeline/generate_historical_transactions.py [--as-of YYYY-MM-DD] [--seed N] [--count N]

All values are illustrative. Amounts are in JPY.
"""
from __future__ import annotations

import argparse
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PERSONAS_MD = ROOT / "docs" / "profiles" / "Personas.md"
OUT = ROOT / "DATA" / "transactions.yaml"

DEFAULT_AS_OF = "2026-07-14"
DEFAULT_SEED = 20260714
DEFAULT_COUNT = 10

# --- persona parsing (spotlight blocks) --------------------------------------
_PERSONA_H = re.compile(
    r"^###\s+(S\d+)\s+—\s+([^（(]+)[（(]([^）)]+)[）)]", re.MULTILINE)
_AGE_GENDER = re.compile(r"年齢\s*/\s*性別:\*\*\s*(\d+)\s*/\s*(女性|男性)")
_JOB = re.compile(r"職業:\*\*\s*([^·\n]+)")
_INCOME = re.compile(r"年収(\d+)万")
_HOUSING = re.compile(r"住まい:\*\*\s*([^·\n]+)")

# Discretionary merchants: (description, category, min, max)
_MERCHANTS = [
    ("コンビニエンスストア", "shopping", 300, 2000),
    ("スーパーマーケット", "shopping", 1500, 7000),
    ("カフェ", "dining", 400, 1500),
    ("ドラッグストア", "shopping", 800, 5000),
    ("オンラインショップ", "shopping", 1500, 15000),
    ("交通系ICチャージ", "transport", 1000, 5000),
    ("レストラン", "dining", 2000, 9000),
    ("書店", "shopping", 800, 4000),
    ("コンビニ ATM 出金", "atm", 10000, 30000),
]


@dataclass
class Persona:
    id: str
    name: str
    job: str
    income_man: int
    housing: str  # rent | mortgage | owned | ""


def parse_personas(md_path: Path) -> list[Persona]:
    text = md_path.read_text(encoding="utf-8")
    heads = list(_PERSONA_H.finditer(text))
    out: list[Persona] = []
    for i, m in enumerate(heads):
        block = text[m.end():(heads[i + 1].start() if i + 1 < len(heads) else len(text))]
        job = _JOB.search(block)
        inc = _INCOME.search(block)
        house = _HOUSING.search(block)
        htext = house.group(1) if house else ""
        housing = ("rent" if "賃貸" in htext else
                   "mortgage" if "住宅ローン" in htext else
                   "owned" if "持家" in htext else "")
        out.append(Persona(
            id=m.group(1),
            name=m.group(2).strip(),
            job=job.group(1).strip() if job else "",
            income_man=int(inc.group(1)) if inc else 0,
            housing=housing,
        ))
    return out


# --- transaction generation --------------------------------------------------
def _round100(n: float) -> int:
    return int(round(n / 100.0)) * 100


def gen_transactions(p: Persona, as_of: date, seed: int, count: int) -> list[dict]:
    rng = random.Random(f"{seed}:{p.id}")
    monthly = _round100(p.income_man * 10000 / 12) if p.income_man else 250000

    # Backbone: recurring monthly items.
    templates: list[tuple[str, str, int]] = []
    income_label = "年金振込" if "年金" in p.job else "給与振込"
    templates.append((income_label, "income", +monthly))
    if p.housing == "rent":
        templates.append(("家賃 口座振替", "housing", -rng.randint(70000, 150000)))
    elif p.housing == "mortgage":
        templates.append(("住宅ローン返済", "loan", -rng.randint(80000, 160000)))
    templates.append(("電気料金", "utility", -rng.randint(3000, 12000)))
    templates.append(("携帯電話料金", "utility", -rng.randint(3000, 9000)))
    templates.append(("動画配信サービス", "subscription", -rng.randint(500, 2000)))

    # Fill with discretionary spending up to `count`.
    while len(templates) < count:
        desc, cat, lo, hi = rng.choice(_MERCHANTS)
        templates.append((desc, cat, -rng.randint(lo, hi)))
    templates = templates[:count]
    rng.shuffle(templates)

    # Assign unique recent dates; process oldest -> newest for the running balance.
    offsets = sorted(rng.sample(range(1, 45), count), reverse=True)  # largest = oldest
    balance = _round100(monthly * rng.uniform(1.5, 3.5)) + 50000  # opening balance
    rows: list[dict] = []
    for off, (desc, cat, amt) in zip(offsets, templates):
        balance += amt
        rows.append({
            "date": (as_of - timedelta(days=off)).isoformat(),
            "description": desc,
            "category": cat,
            "type": "credit" if amt > 0 else "debit",
            "amount": amt,
            "balance": balance,
        })
    rows.reverse()  # most recent first
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default=DEFAULT_AS_OF, help="reference date YYYY-MM-DD")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of)

    personas = parse_personas(PERSONAS_MD)
    transactions = {
        p.id: {
            "name": p.name,
            "transactions": gen_transactions(p, as_of, args.seed, args.count),
        }
        for p in personas
    }
    doc = {
        "generated": {
            "as_of": args.as_of,
            "seed": args.seed,
            "count_per_persona": args.count,
            "note": "Illustrative, deterministically generated. Amounts in JPY.",
        },
        "transactions": transactions,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"Wrote {OUT} — {len(personas)} personas × {args.count} transactions.")


if __name__ == "__main__":
    main()
