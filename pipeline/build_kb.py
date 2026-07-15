#!/usr/bin/env python3
"""Compile the customer Q&A knowledge base for the concierge agent.

Reads the authored Q&A example docs (the source of truth):

    docs/Q&A/CMP-*_QA_examples.md

and emits one machine-readable knowledge-base artifact per campaign:

    DATA/kb-<campaign-id>.yaml   (lower-cased id, e.g. kb-cmp-dep-2026q3-01.yaml)

Each doc pairs a campaign with ~30 documented customer questions and their
answers (である調, internal-knowledge style). The agent LLM consumes the YAML as
grounded, retrievable knowledge: the campaign premise plus the vetted Q&A pairs,
with the "logical-interpretation" items flagged so the model can hedge them.

The Markdown is the human-authored truth; this YAML is reproducible output
compiled from it, so it lives under DATA/ (git-ignored) and is rebuilt by
re-running this script.

Usage:
    .venv/bin/python pipeline/build_kb.py [--check]

    --check   parse and validate only; do not write (exit non-zero on ERROR).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
QA_DIR = ROOT / "docs" / "Q&A"
OUT = ROOT / "DATA"
GLOB = "CMP-*_QA_examples.md"

# `# CMP-DEP-2026Q3-01 — 顧客Q&A例（30問）`
TITLE = re.compile(r"^#\s+(CMP-[A-Z0-9-]+)\s+—\s+(.+?)\s*$", re.MULTILINE)
# `キャンペーン **CMP-DEP-2026Q3-01（口座開設・普通預金応援キャッシュバック）** に関する`
CAMPAIGN_NAME = re.compile(r"CMP-[A-Z0-9-]+[（(]([^）)]+)[）)]")
# `> **回答方針:** documented な記載と論理で回答する。…`
ANSWER_POLICY = re.compile(r"\*\*回答方針:\*\*\s*(.+?)(?=\n>\s*\n|\n>?\s*$|\n(?!>))", re.DOTALL)
# The `## キャンペーン要点（前提）` section body, up to the next `##`/`---`.
PREMISE = re.compile(r"^##\s+キャンペーン要点[^\n]*\n(.*?)(?=^##\s|^---\s*$)", re.DOTALL | re.MULTILINE)
# One Q&A item: `**Q1. question**\n answer …` until the next question / rule / heading.
QA_ITEM = re.compile(
    r"^\*\*Q(\d+)\.\s*(.+?)\*\*\n(.*?)(?=^\*\*Q\d+\.|^---\s*$|^##\s)",
    re.DOTALL | re.MULTILINE,
)
# `**論理的解釈を含む（…）:** Q2（…）, Q8（…）, Q14（…）, Q27（…）。` (may wrap over lines)
INTERPRETATION_LINE = re.compile(
    r"\*\*論理的解釈を含む[^\n]*?:\*\*\s*(.+?)(?=\n\s*\n|\n\s*[-*]\s|^##\s|\Z)",
    re.DOTALL | re.MULTILINE,
)
# `全30問` in the confidence summary; `（30問）` in the title.
COUNT_HINT = re.compile(r"全\s*(\d+)\s*問|[（(]\s*(\d+)\s*問\s*[）)]")


# --------------------------------------------------------------------------- #
# Block literal for readability: multi-line strings dump as `|` blocks.
# --------------------------------------------------------------------------- #
def _str_representer(dumper: yaml.Dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


yaml.add_representer(str, _str_representer, Dumper=yaml.SafeDumper)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _interpretation_ids(md: str) -> set[str]:
    """Q ids the doc flags as containing logical interpretation (should hedge)."""
    m = INTERPRETATION_LINE.search(md)
    if not m:
        return set()
    return {f"Q{n}" for n in re.findall(r"Q(\d+)", m.group(1))}


def parse_doc(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    """Parse one Q&A doc into a KB record plus a list of (level, message) issues."""
    md = path.read_text(encoding="utf-8")
    issues: list[tuple[str, str]] = []

    title = TITLE.search(md)
    if not title:
        issues.append(("ERROR", f"{path.name}: no `# CMP-… — …` title heading found"))
        return {}, issues
    campaign_id = title.group(1)

    name = CAMPAIGN_NAME.search(md)
    policy = ANSWER_POLICY.search(md)
    premise = PREMISE.search(md)
    interp = _interpretation_ids(md)

    qa: list[dict] = []
    for num, question, answer in QA_ITEM.findall(md):
        qid = f"Q{num}"
        item = {"id": qid, "question": question.strip(), "answer": answer.strip()}
        if qid in interp:
            item["interpretation"] = True
        qa.append(item)

    if not qa:
        issues.append(("ERROR", f"{campaign_id}: no Q&A items parsed"))

    ids = [int(i["id"][1:]) for i in qa]
    expected = list(range(1, len(qa) + 1))
    if ids != expected:
        issues.append(("WARN", f"{campaign_id}: Q ids not 1..N contiguous: {ids}"))

    hint = COUNT_HINT.search(md)
    if hint:
        want = int(next(g for g in hint.groups() if g))
        if want != len(qa):
            issues.append(("WARN", f"{campaign_id}: doc says {want} 問 but {len(qa)} parsed"))

    unknown = interp - {i["id"] for i in qa}
    if unknown:
        issues.append(("WARN", f"{campaign_id}: interpretation flags for missing Q: {sorted(unknown)}"))

    record = {
        "campaign_id": campaign_id,
        "campaign_name": name.group(1).strip() if name else None,
        "source": str(path.relative_to(ROOT)),
        "answer_policy": re.sub(r"\s*\n\s*>?\s*", " ", policy.group(1).strip()) if policy else None,
        "premise": premise.group(1).strip() if premise else None,
        "qa_count": len(qa),
        "qa": qa,
    }
    return record, issues


# --------------------------------------------------------------------------- #
def dump_yaml(path: Path, data: dict) -> None:
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    header = f"# Auto-generated by pipeline/build_kb.py from {data['source']} — do not edit by hand.\n"
    path.write_text(header + body, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="validate only, do not write")
    args = ap.parse_args()

    docs = sorted(QA_DIR.glob(GLOB))
    if not docs:
        print(f"No Q&A docs matching {QA_DIR}/{GLOB}", file=sys.stderr)
        sys.exit(1)

    records: list[dict] = []
    all_issues: list[tuple[str, str]] = []
    for path in docs:
        record, issues = parse_doc(path)
        all_issues.extend(issues)
        if record:
            records.append(record)

    for level, msg in all_issues:
        print(f"[{level}] {msg}", file=sys.stderr)

    if any(level == "ERROR" for level, _ in all_issues):
        n = sum(level == "ERROR" for level, _ in all_issues)
        print(f"\n{n} error(s) — not writing.", file=sys.stderr)
        sys.exit(1)

    total_qa = sum(r["qa_count"] for r in records)
    if args.check:
        print(f"check ok: {len(records)} KB doc(s), {total_qa} Q&A pairs; "
              f"{len(all_issues)} non-fatal note(s).")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for record in records:
        out = OUT / f"kb-{record['campaign_id'].lower()}.yaml"
        dump_yaml(out, record)
        written.append(out.name)
    print(f"Wrote {len(written)} KB file(s) to {OUT} ({total_qa} Q&A pairs): "
          f"{', '.join(written)}. {len(all_issues)} note(s).")


if __name__ == "__main__":
    main()
