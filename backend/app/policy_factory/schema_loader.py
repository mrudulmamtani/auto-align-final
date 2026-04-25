"""
Schema Loader — loads the authoritative document schemas (policy.json, standard.json,
procedure.json) from the project root. These schemas override all historical golden
baseline templates and define the complete document contract.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# Project root: auto-align/  (4 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _schema_dir() -> Path:
    env = os.environ.get("SCHEMA_DIR")
    return Path(env) if env else _PROJECT_ROOT


@lru_cache(maxsize=3)
def load_schema(doc_type: str) -> dict:
    """Load and cache the authoritative JSON schema for a document type.

    Args:
        doc_type: "policy", "standard", or "procedure"

    Returns:
        Parsed schema dict

    Raises:
        ValueError: Unknown doc_type
        FileNotFoundError: Schema file not found
    """
    schema_map = {
        "policy":    "policy.json",
        "standard":  "standard.json",
        "procedure": "procedure.json",
    }
    filename = schema_map.get(doc_type.lower())
    if not filename:
        raise ValueError(
            f"Unknown doc_type '{doc_type}'. Expected: policy, standard, procedure."
        )
    path = _schema_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {path}\n"
            f"Set SCHEMA_DIR env var or place {filename} at project root."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def schema_as_prompt_text(doc_type: str) -> str:
    """Return condensed schema guidance for injection into LLM system prompts.

    Extracts the key structural rules — document_order, section_blueprints
    (function + top writing rules), content_balance_rules, global writing rules —
    into a compact text block that fits inside a system message.
    """
    schema = load_schema(doc_type)
    root_key = f"{doc_type}_document_schema"
    s = schema.get(root_key, schema)

    lines: list[str] = [
        "=" * 60,
        f"AUTHORITATIVE DOCUMENT SCHEMA — {s.get('document_family', doc_type.upper())}",
        f"Document Type : {s.get('document_type', doc_type)}",
        f"Language Mode : {s.get('language_mode', 'English')}",
        f"Purpose       : {s.get('purpose_of_family') or s.get('purpose', '')}",
        "=" * 60,
        "",
        "MANDATORY DOCUMENT ORDER:",
    ]
    for section in s.get("document_order", []):
        lines.append(f"  {section}")

    lines += ["", "SECTION BLUEPRINTS (key rules per section):"]
    for section, bp in s.get("section_blueprints", {}).items():
        if not isinstance(bp, dict):
            continue
        lines.append(f"  [{section}]")
        if "function" in bp:
            lines.append(f"    purpose: {bp['function']}")
        if "dominance_rule" in bp:
            lines.append(f"    DOMINANCE: {bp['dominance_rule']}")
        if "word_share_target" in bp:
            lines.append(f"    word_share: {bp['word_share_target']}")
        for rule in bp.get("writing_rules", [])[:4]:
            lines.append(f"    - {rule}")
        # Expose clause count expectations for policy_statement
        if "clause_model" in bp:
            cm = bp["clause_model"]
            cc = cm.get("expected_clause_count", {})
            lines.append(
                f"    clauses: min={cc.get('min','?')} typical={cc.get('typical','?')} max={cc.get('max','?')}"
            )
        # Expose expected term counts for definition sections
        if "expected_length" in bp:
            el = bp["expected_length"]
            lines.append(
                f"    terms: min={el.get('terms_min', el.get('min','?'))} max={el.get('terms_max', el.get('max','?'))}"
            )

    lines += ["", "CONTENT BALANCE RULES (word/page share targets):"]
    for k, v in s.get("content_balance_rules", {}).items():
        lines.append(f"  {k}: {v}")

    lines += ["", "VALIDATION RULES (all must pass before output):"]
    for rule in s.get("validation_rules", []):
        lines.append(f"  • {rule}")

    wr = s.get("writing_rules_global", {})
    if wr:
        lines += ["", "GLOBAL WRITING RULES:"]
        for rule in wr.get("do", []):
            lines.append(f"  DO     : {rule}")
        for rule in wr.get("do_not", []):
            lines.append(f"  DO NOT : {rule}")

    lines += ["", "OUTPUT CONTRACT (required output parts):"]
    for part in s.get("output_contract", {}).get("required_output_parts", []):
        lines.append(f"  ✓ {part}")

    return "\n".join(lines)
