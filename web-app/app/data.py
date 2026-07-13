"""In-memory data layer for the web-app.

Parses the authored profile Markdown (docs/profiles) into the small structures the
two tab pages need:

  * spotlight personas (S01..)  — id, name, type label, age/gender, generated avatar.
  * campaigns (CMP-..)          — id, title, category, description, period, reward cap.

The Markdown is the source of truth; this layer only reads it. Loaded once and cached.
"""
from __future__ import annotations

import hashlib
import random
import re
from datetime import date, timedelta
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
_ONENEO = re.compile(r"OneNeo:\*\*\s*([^·\n]+)")
_INCOME = re.compile(r"年収(\d+)万")
_PRODUCT_KEYS = ("普通預金", "定期預金", "カードローン", "デビット")

# --- campaign parsing --------------------------------------------------------
# ### CMP-DEP-2026Q3-01 — 口座開設・普通預金応援キャッシュバック
_CAMPAIGN_H = re.compile(r"^###\s+(CMP-[A-Z0-9-]+?)\s+—\s+(.+?)\s*$", re.MULTILINE)
_PERIOD = re.compile(r"対象期間:\*\*\s*([^\n]+)")
# A campaign block ends at the next h2/h3 heading or a horizontal rule.
_BLOCK_END = re.compile(r"^(?:#{2,3}\s|---\s*$)", re.MULTILINE)

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
        oneneo = _ONENEO.search(block)
        seg = oneneo.group(1) if oneneo else ""
        inc = _INCOME.search(block)
        out.append({
            "id": pid,
            "name": name,
            "type_label": type_label,
            "hard_case": (hard or "").strip() or None,
            "age": age,
            "gender": gender,
            "job": job.group(1).strip() if job else "",
            "products": [k for k in _PRODUCT_KEYS if k in seg],
            "income_man": int(inc.group(1)) if inc else 0,
            "emoji": _avatar_emoji(gender, age),
            "color": _avatar_color(pid),
        })
    return out


def persona_by_id(pid: str) -> dict | None:
    for p in get_data().personas:
        if p["id"] == pid:
            return p
    return None


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
    caps = _campaign_caps()
    out: list[dict] = []
    for m in _CAMPAIGN_H.finditer(text):
        cid, title = m.group(1), m.group(2).strip()
        be = _BLOCK_END.search(text, m.end())
        block = _block_after(text, m.end(), be.start() if be else len(text))
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
            "raw_md": block.strip("\n"),   # full block body, for the detail page
        })
    return out


def campaign_by_id(cid: str) -> dict | None:
    for c in get_data().campaigns:
        if c["id"] == cid:
            return c
    return None


# --- persona home screen -----------------------------------------------------
# Each persona's home screen (per the app mockup): banner (their top-recommended
# campaign), account balance, recent transactions, function icons, message history.
# All values are deterministically generated per persona so they're stable.

_MATRIX_CODE = re.compile(r"\*\*(C\d)\*\*\s*=\s*(CMP-[A-Z0-9-]+)")

FUNCTION_ICONS = [
    {"label": "振込", "emoji": "💸", "tab": "transfer"},
    {"label": "定期預金", "emoji": "🏦"},
    {"label": "カードローン", "emoji": "🤝"},
    {"label": "デビット", "emoji": "💳"},
    {"label": "利用明細", "emoji": "📄"},
    {"label": "キャンペーン", "emoji": "🎁", "tab": "campaign"},
    {"label": "ATM", "emoji": "🏧"},
    {"label": "設定", "emoji": "⚙️"},
]

_TX_POOL = [
    ("コンビニ", "🏪", 300, 1500), ("スーパー", "🛒", 1000, 6000),
    ("カフェ", "☕", 350, 1200), ("ドラッグストア", "💊", 800, 4000),
    ("ネット通販", "📦", 1500, 12000), ("交通ICチャージ", "🚃", 1000, 5000),
    ("レストラン", "🍽", 2000, 8000),
]


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest(), 16))


@lru_cache(maxsize=1)
def _matrix() -> tuple[dict[str, str], dict[str, dict]]:
    """(code->campaign_id, persona_id->{scores, top}) parsed from the matrix doc."""
    path = config.MATRIX_MD
    if not path.exists():
        return {}, {}
    text = path.read_text(encoding="utf-8")
    code_to_id = dict(_MATRIX_CODE.findall(text))
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        if not re.match(r"^\|\s*S\d+", line):
            continue
        cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        m = re.match(r"(S\d+)", cells[0])
        if not m:
            continue
        scores = {}
        for i, code in enumerate(("C1", "C2", "C3", "C4")):
            try:
                scores[code] = int(cells[1 + i])
            except (ValueError, IndexError):
                scores[code] = 0
        rows[m.group(1)] = {"scores": scores, "top": cells[5] if len(cells) > 5 else ""}
    return code_to_id, rows


def _gen_txns(rng: random.Random, p: dict, monthly: int) -> list[dict]:
    today = date.today()
    offsets = sorted(rng.sample(range(0, 13), 5))
    inc_label = "年金振込" if "年金" in p["job"] else "給与振込"
    plan = [
        (offsets[0], inc_label, "💴", +monthly),
        (offsets[1], "電気料金", "💡", -rng.randint(3000, 9000)),
    ]
    for off in offsets[2:]:
        label, emoji, lo, hi = rng.choice(_TX_POOL)
        plan.append((off, label, emoji, -rng.randint(lo, hi)))
    plan.sort(key=lambda t: t[0])  # smallest offset = most recent, first
    return [{
        "date": (today - timedelta(days=off)).strftime("%m/%d"),
        "label": label, "emoji": emoji, "amount": amt,
    } for off, label, emoji, amt in plan]


def _gen_messages(rng: random.Random, banner: dict | None, has_td: bool) -> list[dict]:
    today = date.today()
    items = [(1, "ご利用明細を更新しました。"),
             (2, "セキュリティのお知らせ：不審なSMS・フィッシングにご注意ください。"),
             (8, "アプリを最新バージョンに更新してください。")]
    if banner:
        items.append((0, f"【キャンペーン】{banner['title']}のご案内"))
    if has_td:
        items.append((5, "定期預金の満期が近づいています。ご確認ください。"))
    items.sort(key=lambda t: t[0])
    return [{"date": (today - timedelta(days=o)).strftime("%m/%d"), "text": t} for o, t in items]


def persona_home(pid: str) -> dict | None:
    p = persona_by_id(pid)
    if p is None:
        return None
    rng = _rng(pid)
    monthly = int(p["income_man"] * 10000 / 12) if p["income_man"] else 250000
    ordinary = int(rng.uniform(0.8, 4.0) * max(monthly, 120000) / 1000) * 1000
    has_td = "定期預金" in p["products"]
    time_deposit = rng.randint(10, 30) * 100000 if has_td else None

    code_to_id, rows = _matrix()
    row = rows.get(pid, {})
    banner = None
    if row.get("top") in code_to_id:
        c = campaign_by_id(code_to_id[row["top"]])
        if c:
            banner = {"id": c["id"], "title": c["title"], "category": c["category"], "icon": c["icon"]}
    scores = row.get("scores", {})
    rec_ids = [code_to_id[k] for k in sorted(scores, key=lambda k: -scores[k]) if k in code_to_id]
    recommended = [c for c in (campaign_by_id(i) for i in rec_ids) if c]

    return {
        "persona": p,
        "ordinary": ordinary,
        "time_deposit": time_deposit,
        "transactions": _gen_txns(rng, p, monthly),
        "messages": _gen_messages(rng, banner, has_td),
        "icons": FUNCTION_ICONS,
        "banner": banner,
        "recommended": recommended,
    }


class Data:
    def __init__(self) -> None:
        self.personas = parse_personas(config.PERSONAS_MD)
        self.campaigns = parse_campaigns(config.CAMPAIGNS_MD)


@lru_cache(maxsize=1)
def get_data() -> Data:
    return Data()
