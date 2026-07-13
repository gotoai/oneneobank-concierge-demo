#!/usr/bin/env python3
"""Generate a synthetic OneNeo Bank customer population (personas).

Samples a Japan-realistic customer population from the dimension taxonomy
documented in ``docs/profiles/Personas.md`` and writes two artifacts:

- ``docs/profiles/personas/personas.json``  — machine-readable source of truth.
- ``docs/profiles/personas/personas-catalog.md`` — human-readable structured blocks.

The generator is seeded, so output is reproducible. Tune the weights below to
reshape the population; re-run to regenerate.

Usage:
    .venv/bin/python pipeline/generate_personas.py [--count N] [--seed S]

All figures are illustrative. Income is annual, in JPY.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

SEED = 20260713
DOCS = Path(__file__).resolve().parent.parent / "docs" / "profiles" / "personas"


# --------------------------------------------------------------------------- #
# Weighted sampling helper
# --------------------------------------------------------------------------- #
def pick(rng: random.Random, choices: dict[str, float]) -> str:
    """Weighted choice from a {value: weight} mapping."""
    items = list(choices.items())
    return rng.choices([k for k, _ in items], weights=[w for _, w in items])[0]


# --------------------------------------------------------------------------- #
# Dimension taxonomy (Japan-realistic, neobank-skewed weights)
# --------------------------------------------------------------------------- #
AGE_BANDS = {"18-27": 22, "28-37": 28, "38-47": 24, "48-59": 16, "60+": 10}
GENDER = {"female": 50, "male": 50}

# Employment weights conditioned on age band.
EMPLOYMENT_BY_AGE = {
    "18-27": {"student": 18, "seishain": 40, "keiyaku": 10, "haken": 8,
              "part_time": 14, "freelance": 6, "civil_servant": 4, "unemployed": 0},
    "28-37": {"seishain": 52, "keiyaku": 9, "haken": 7, "part_time": 9,
              "freelance": 9, "business_owner": 4, "civil_servant": 8,
              "unemployed": 2, "student": 0},
    "38-47": {"seishain": 50, "keiyaku": 8, "haken": 5, "part_time": 12,
              "freelance": 9, "business_owner": 6, "civil_servant": 8,
              "unemployed": 2},
    "48-59": {"seishain": 46, "keiyaku": 8, "haken": 4, "part_time": 14,
              "freelance": 8, "business_owner": 7, "civil_servant": 9,
              "unemployed": 4},
    "60+": {"pensioner": 46, "reemployed": 22, "part_time": 10, "freelance": 6,
            "business_owner": 6, "seishain": 6, "unemployed": 4},
}

EMPLOYMENT_LABEL = {
    "seishain": "Permanent employee (正社員)",
    "keiyaku": "Contract employee (契約社員)",
    "haken": "Dispatch worker (派遣社員)",
    "part_time": "Part-time (パート/アルバイト)",
    "freelance": "Freelance / self-employed (個人事業主)",
    "business_owner": "Business owner (経営者)",
    "civil_servant": "Civil servant (公務員)",
    "student": "Student (学生)",
    "pensioner": "Pensioner / retired (年金受給者)",
    "reemployed": "Re-employed senior (再雇用)",
    "unemployed": "Not currently employed (無職)",
}

# Annual income range (JPY, in units of 10k) conditioned on employment type.
INCOME_RANGE_MAN = {
    "student": (0, 120),
    "part_time": (80, 200),
    "haken": (250, 400),
    "keiyaku": (280, 460),
    "seishain": (320, 900),
    "civil_servant": (350, 700),
    "freelance": (150, 850),
    "business_owner": (500, 2000),
    "reemployed": (200, 420),
    "pensioner": (90, 300),
    "unemployed": (0, 60),
}

STABILITY_BY_EMPLOYMENT = {
    "seishain": "steady", "civil_servant": "steady", "keiyaku": "steady",
    "haken": "variable", "part_time": "variable", "reemployed": "steady",
    "freelance": "variable", "business_owner": "variable",
    "pensioner": "steady", "student": "variable", "unemployed": "variable",
}

REGION = {"tokyo_23ku": 34, "greater_tokyo": 30, "other_urban": 22, "regional": 14}

# Marital status conditioned on age band.
MARITAL_BY_AGE = {
    "18-27": {"single": 82, "married": 16, "divorced": 2, "widowed": 0},
    "28-37": {"single": 46, "married": 48, "divorced": 6, "widowed": 0},
    "38-47": {"single": 28, "married": 60, "divorced": 11, "widowed": 1},
    "48-59": {"single": 20, "married": 63, "divorced": 14, "widowed": 3},
    "60+": {"single": 12, "married": 62, "divorced": 12, "widowed": 14},
}

DIGITAL_LITERACY_BY_AGE = {
    "18-27": {"high": 78, "medium": 20, "low": 2},
    "28-37": {"high": 66, "medium": 30, "low": 4},
    "38-47": {"high": 48, "medium": 42, "low": 10},
    "48-59": {"high": 28, "medium": 48, "low": 24},
    "60+": {"high": 12, "medium": 40, "low": 48},
}

ATTITUDE = {"satisfied": 55, "neutral": 33, "frustrated": 12}
LANGUAGE = {"ja": 94, "en_needed": 6}

PRODUCT_POOL = ["ordinary", "time_deposit", "card_loan", "debit_active"]

LIFE_EVENTS_BY_AGE = {
    "18-27": ["starting_first_job", "saving_regularly", "moving",
              "travelling_abroad", "changing_jobs", "getting_married", "none_stable"],
    "28-37": ["getting_married", "having_a_child", "buying_a_home", "childcare_costs",
              "saving_regularly", "changing_jobs", "travelling_abroad",
              "starting_a_business", "none_stable"],
    "38-47": ["childcare_costs", "education_savings", "buying_a_home", "changing_jobs",
              "starting_a_business", "saving_regularly", "travelling_abroad", "none_stable"],
    "48-59": ["education_savings", "retirement_planning", "saving_regularly",
              "changing_jobs", "buying_a_home", "none_stable"],
    "60+": ["living_on_pension", "retirement_planning", "travelling_abroad", "none_stable"],
}


# --------------------------------------------------------------------------- #
# Persona record
# --------------------------------------------------------------------------- #
@dataclass
class Persona:
    id: str
    age_band: str
    gender: str
    employment: str
    income_man_jpy: int
    marital_status: str
    children: list[int]
    housing: str
    car: str
    region: str
    products_held: list[str]
    primary_or_secondary: str
    tenure_months: int
    income_stability: str
    other_debt: str
    savings_buffer: str
    digital_literacy: str
    attitude: str
    language: str
    life_event: str
    signature_scenario: str = ""


def sample_children(rng: random.Random, age_band: str, marital: str) -> list[int]:
    if marital == "single" or age_band == "18-27":
        return [] if rng.random() > 0.05 else [rng.randint(0, 2)]
    prob_kids = {"28-37": 0.5, "38-47": 0.72, "48-59": 0.7, "60+": 0.75}.get(age_band, 0.4)
    if rng.random() > prob_kids:
        return []
    n = rng.choices([1, 2, 3], weights=[48, 42, 10])[0]
    # Child ages plausible for the parent's age band.
    max_age = {"28-37": 8, "38-47": 18, "48-59": 28, "60+": 40}.get(age_band, 10)
    return sorted(rng.randint(0, max_age) for _ in range(n))


def sample_housing(rng: random.Random, age_band: str, income_man: int) -> str:
    if age_band in ("18-27",) or income_man < 300:
        return pick(rng, {"rent": 88, "owned_mortgage": 8, "owned_paid": 4})
    if age_band in ("28-37",):
        return pick(rng, {"rent": 58, "owned_mortgage": 38, "owned_paid": 4})
    if age_band in ("38-47",):
        return pick(rng, {"rent": 40, "owned_mortgage": 52, "owned_paid": 8})
    if age_band in ("48-59",):
        return pick(rng, {"rent": 32, "owned_mortgage": 46, "owned_paid": 22})
    return pick(rng, {"rent": 26, "owned_mortgage": 16, "owned_paid": 58})


def sample_car(rng: random.Random, region: str) -> str:
    weights = {
        "tokyo_23ku": {"none": 78, "has_car": 22},
        "greater_tokyo": {"none": 52, "has_car": 48},
        "other_urban": {"none": 40, "has_car": 60},
        "regional": {"none": 18, "has_car": 82},
    }[region]
    return pick(rng, weights)


def sample_products(rng: random.Random, tenure: int, life_event: str) -> list[str]:
    held = ["ordinary"]  # everyone has the default account
    if rng.random() < 0.7:
        held.append("debit_active")
    if tenure >= 6 and rng.random() < 0.45:
        held.append("time_deposit")
    loan_bias = 0.35 if life_event in ("childcare_costs", "moving", "buying_a_home",
                                        "starting_a_business", "changing_jobs") else 0.12
    if rng.random() < loan_bias:
        held.append("card_loan")
    return held


def assign_scenario(p: Persona) -> str:
    """Map a persona to a signature concierge scenario (priority-ordered)."""
    if p.language == "en_needed":
        return ("English-language support: understand Japanese banking terms "
                "(振込, 定期預金) and complete tasks with limited Japanese.")
    if p.digital_literacy == "low" and p.age_band == "60+":
        return ("Step-by-step help navigating the app: checking balance, and "
                "reassurance about a message they fear is a scam (security).")
    if p.attitude == "frustrated":
        return ("Frustrated about an unresolved issue; wants fast resolution or "
                "escalation to a human agent — tests handoff and tone.")
    if "card_loan" in p.products_held or p.life_event in (
            "starting_a_business", "moving", "buying_a_home"):
        return ("Card loan questions: limit, interest, and eligibility — concierge "
                "explains terms but defers the decision to the screening flow.")
    if p.life_event == "travelling_abroad" or (
            "debit_active" in p.products_held and p.region == "tokyo_23ku"
            and p.age_band in ("18-27", "28-37")):
        return ("Debit card abroad: foreign-currency handling, overseas fees, and "
                "reward points on travel spending.")
    if p.life_event in ("getting_married", "having_a_child", "education_savings",
                        "saving_regularly", "childcare_costs"):
        return ("Savings goal: opening a time deposit and setting up regular "
                "auto-saving toward a life event.")
    if p.life_event in ("retirement_planning", "living_on_pension") or p.employment in (
            "pensioner", "reemployed"):
        return ("Retirement/pension: receiving pension into the account and placing "
                "a lump sum into a time deposit.")
    if p.tenure_months <= 3:
        return ("Onboarding: finishing account setup, eKYC/本人確認 questions, and "
                "how to use the debit card.")
    return ("Everyday FAQ: fees, transfers (振込), and how debit reward points "
            "work.")


def make_persona(rng: random.Random, idx: int) -> Persona:
    age = pick(rng, AGE_BANDS)
    gender = pick(rng, GENDER)
    employment = pick(rng, EMPLOYMENT_BY_AGE[age])
    lo, hi = INCOME_RANGE_MAN[employment]
    income = rng.randint(lo, hi)
    marital = pick(rng, MARITAL_BY_AGE[age])
    children = sample_children(rng, age, marital)
    housing = sample_housing(rng, age, income)
    region = pick(rng, REGION)
    car = sample_car(rng, region)
    tenure = rng.choices([2, 8, 18, 30], weights=[24, 30, 26, 20])[0] + rng.randint(0, 5)
    life_event = rng.choice(LIFE_EVENTS_BY_AGE[age])
    products = sample_products(rng, tenure, life_event)

    # Mortgage debt only when the persona actually holds a mortgaged home.
    if housing == "owned_mortgage":
        other_debt = "mortgage"
    else:
        other_debt = pick(rng, {"none": 62, "credit_card_revolving": 22,
                                "auto_or_other_loan": 16})
    savings = pick(rng, {"thin": 34, "moderate": 44, "healthy": 22})
    primary = pick(rng, {"secondary": 58, "primary": 42})  # neobanks skew secondary

    p = Persona(
        id=f"P{idx:03d}",
        age_band=age,
        gender=gender,
        employment=EMPLOYMENT_LABEL[employment],
        income_man_jpy=income,
        marital_status=marital,
        children=children,
        housing=housing,
        car=car,
        region=region,
        products_held=products,
        primary_or_secondary=primary,
        tenure_months=tenure,
        income_stability=STABILITY_BY_EMPLOYMENT[employment],
        other_debt=other_debt,
        savings_buffer=savings,
        digital_literacy=pick(rng, DIGITAL_LITERACY_BY_AGE[age]),
        attitude=pick(rng, ATTITUDE),
        language=pick(rng, LANGUAGE),
        life_event=life_event,
    )
    p.signature_scenario = assign_scenario(p)
    return p


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
HOUSING_LABEL = {"rent": "Rented home", "owned_mortgage": "Owned home (mortgage)",
                 "owned_paid": "Owned home (paid off)"}
CAR_LABEL = {"none": "No car", "has_car": "Has a car"}
REGION_LABEL = {"tokyo_23ku": "Tokyo 23 wards", "greater_tokyo": "Greater Tokyo",
                "other_urban": "Other urban", "regional": "Regional"}


def children_str(children: list[int]) -> str:
    if not children:
        return "no children"
    return f"{len(children)} child(ren), ages {', '.join(map(str, children))}"


def render_block(p: Persona) -> str:
    income = f"¥{p.income_man_jpy * 10_000:,}/yr ({p.income_man_jpy}万)"
    products = ", ".join(p.products_held)
    return (
        f"### {p.id}\n"
        f"- **Age / Gender:** {p.age_band} / {p.gender}\n"
        f"- **Employment / Income:** {p.employment} — {income} ({p.income_stability})\n"
        f"- **Household:** {p.marital_status}, {children_str(p.children)}\n"
        f"- **Home / Car / Region:** {HOUSING_LABEL[p.housing]} / "
        f"{CAR_LABEL[p.car]} / {REGION_LABEL[p.region]}\n"
        f"- **OneNeo relationship:** {products}; {p.primary_or_secondary} bank; "
        f"tenure {p.tenure_months} mo\n"
        f"- **Finances:** debt: {p.other_debt}; buffer: {p.savings_buffer}\n"
        f"- **Digital literacy / Attitude / Language:** {p.digital_literacy} / "
        f"{p.attitude} / {p.language}\n"
        f"- **Life event:** {p.life_event}\n"
        f"- **Signature concierge scenario:** {p.signature_scenario}\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    personas = [make_persona(rng, i) for i in range(1, args.count + 1)]

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "personas.json").write_text(
        json.dumps([asdict(p) for p in personas], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    header = (
        "## OneNeo Bank — Generated Persona Catalog\n\n"
        f"> Auto-generated by `pipeline/generate_personas.py` "
        f"(seed {args.seed}, {args.count} personas). **Do not edit by hand** — "
        "re-run the generator to change. Design & taxonomy: "
        "[Personas](../Personas.md).\n\n"
    )
    blocks = "\n".join(render_block(p) for p in personas)
    (DOCS / "personas-catalog.md").write_text(header + blocks, encoding="utf-8")

    print(f"Wrote {len(personas)} personas to {DOCS}/personas.json and personas-catalog.md")


if __name__ == "__main__":
    main()
