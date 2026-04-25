"""
Deterministic Sub-Tools — pure Python, zero LLM calls.

These tools handle all parts of document generation that do NOT require
language model reasoning:

  • MetadataBuilder     — computes doc_id, dates, owner, classification
  • CitationValidator   — checks chunk_ids exist in the provided bundles
  • StructuralChecker   — validates field presence and minimum counts
  • BundleFilter        — filters/ranks bundles for a specific section topic
  • RelatedDocsBuilder  — builds related_documents list from doc_id patterns
  • WordCounter         — counts words in text fields
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# ── MetadataBuilder ───────────────────────────────────────────────────────────

class MetadataBuilder:
    """Deterministically fills metadata fields common to all document types."""

    @staticmethod
    def build_procedure(
        doc_id: str,
        topic: str,
        org_name: str,
        version: str = "1.0",
    ) -> dict[str, str]:
        """Return metadata dict for a ProcedureDraftOutput."""
        return {
            "doc_id":           doc_id,
            "title_en":         f"{org_name} — {topic} Procedure",
            "version":          version,
            "effective_date":   datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner":            "Chief Information Security Officer",
            "classification":   "Internal — Restricted",
            "parent_policy_id": _infer_parent_policy(doc_id),
            "parent_standard_id": _infer_parent_standard(doc_id),
        }

    @staticmethod
    def build_policy(
        doc_id: str,
        topic: str,
        org_name: str,
        version: str = "1.0",
    ) -> dict[str, str]:
        return {
            "doc_id":         doc_id,
            "title_en":       f"{org_name} — {topic} Policy",
            "version":        version,
            "effective_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner":          "Chief Information Security Officer",
            "classification": "Internal",
        }

    @staticmethod
    def build_standard(
        doc_id: str,
        topic: str,
        org_name: str,
        version: str = "1.0",
    ) -> dict[str, str]:
        return {
            "doc_id":         doc_id,
            "title_en":       f"{org_name} — {topic} Standard",
            "version":        version,
            "effective_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner":          "Chief Information Security Officer",
            "classification": "Internal",
        }


def _infer_parent_policy(doc_id: str) -> str:
    """Infer parent policy ID from procedure/standard doc_id."""
    if doc_id.startswith("PRC-"):
        n = re.search(r"\d+", doc_id)
        return f"POL-{n.group().zfill(2)}" if n else "POL-01"
    return "POL-01"


def _infer_parent_standard(doc_id: str) -> str:
    """Infer parent standard ID from procedure doc_id."""
    if doc_id.startswith("PRC-"):
        n = re.search(r"\d+", doc_id)
        return f"STD-{n.group().zfill(2)}" if n else "STD-01"
    return "STD-01"


# ── RelatedDocsBuilder ────────────────────────────────────────────────────────

class RelatedDocsBuilder:
    """Builds related_documents list deterministically from doc_id patterns."""

    @staticmethod
    def build(doc_id: str, topic: str) -> list[dict[str, str]]:
        docs = []
        # Parent policy
        parent_pol = _infer_parent_policy(doc_id)
        docs.append({"doc_ref": parent_pol, "title": f"Cybersecurity {topic} Policy",    "relationship": "parent_policy"})
        # Parent standard
        if doc_id.startswith("PRC-"):
            parent_std = _infer_parent_standard(doc_id)
            docs.append({"doc_ref": parent_std, "title": f"Cybersecurity {topic} Standard", "relationship": "parent_standard"})
        # NCA ECC reference
        docs.append({"doc_ref": "NCA-ECC-2020", "title": "NCA Essential Cybersecurity Controls (ECC)", "relationship": "regulatory_framework"})
        # NIST reference
        docs.append({"doc_ref": "NIST-SP-800-53r5", "title": "NIST SP 800-53 Rev 5", "relationship": "supplementary_framework"})
        # ISO reference
        docs.append({"doc_ref": "ISO-27001-2022", "title": "ISO/IEC 27001:2022", "relationship": "complementary_standard"})
        return docs


# ── CitationValidator ─────────────────────────────────────────────────────────

class CitationValidator:
    """
    Deterministic citation validator.
    Checks that every chunk_id cited in a step exists in the provided bundles.
    """

    def validate(
        self,
        steps: list[dict],   # list of step dicts with "citations" field
        bundle_ids: set[str],
    ) -> list[dict]:
        """
        Returns list of steps with invalid citations removed.
        Also logs invalid chunk_ids found.
        """
        cleaned = []
        for step in steps:
            citations = step.get("citations", [])
            valid = [c for c in citations if c in bundle_ids]
            invalid = [c for c in citations if c not in bundle_ids]
            if invalid:
                print(f"[CitationValidator] Removed {len(invalid)} invalid chunk_ids: {invalid[:3]}")
            cleaned.append({**step, "citations": valid})
        return cleaned

    def validate_draft(self, draft_dict: dict, bundle_ids: set[str]) -> dict:
        """Validate and clean citations in a full draft dict."""
        phases = draft_dict.get("phases", [])
        cleaned_phases = []
        for phase in phases:
            cleaned_steps = self.validate(phase.get("steps", []), bundle_ids)
            cleaned_phases.append({**phase, "steps": cleaned_steps})
        return {**draft_dict, "phases": cleaned_phases}


# ── StructuralChecker ─────────────────────────────────────────────────────────

class StructuralChecker:
    """
    Deterministic structural validation.
    Returns list of (field, issue) tuples — no LLM required.
    """

    def check_procedure(self, draft_dict: dict) -> list[str]:
        """Return list of structural issues in a procedure draft dict."""
        issues = []
        phases = draft_dict.get("phases", [])
        roles  = draft_dict.get("roles_responsibilities", [])
        checks = draft_dict.get("verification_checks", [])
        evidence = draft_dict.get("evidence_collection", [])

        if len(roles) < 3:
            issues.append(f"ROLES: only {len(roles)} roles (min 3)")
        if len(phases) < 2:
            issues.append(f"PHASES: only {len(phases)} phases (min 2)")

        total_steps = sum(len(p.get("steps", [])) for p in phases)
        if total_steps < 15:
            issues.append(f"STEPS: only {total_steps} steps (min 15)")

        if len(checks) < 3:
            issues.append(f"VERIFICATION_CHECKS: only {len(checks)} (min 3)")
        if len(evidence) < 2:
            issues.append(f"EVIDENCE_COLLECTION: only {len(evidence)} (min 2)")

        for i, phase in enumerate(phases):
            for j, step in enumerate(phase.get("steps", [])):
                if not step.get("actor"):
                    issues.append(f"phase[{i}].step[{j}]: missing actor")
                if len(step.get("action", "")) < 50:
                    issues.append(f"phase[{i}].step[{j}]: action too short (<50 chars)")
                if len(step.get("expected_output", "")) < 30:
                    issues.append(f"phase[{i}].step[{j}]: expected_output too short (<30 chars)")

        return issues

    def check_policy(self, draft_dict: dict) -> list[str]:
        issues = []
        elements   = draft_dict.get("policy_elements", [])
        subprograms = draft_dict.get("policy_subprograms", [])
        roles       = draft_dict.get("roles_responsibilities", [])

        if len(elements) < 5:
            issues.append(f"POLICY_ELEMENTS: only {len(elements)} (min 5)")
        if len(subprograms) < 10:
            issues.append(f"SUBPROGRAMS: only {len(subprograms)} (min 10)")
        if not roles:
            issues.append("ROLES_RESPONSIBILITIES: missing")

        for i, el in enumerate(elements):
            stmt = el.get("statement_en", "")
            if "shall" not in stmt.lower():
                issues.append(f"element[{i}]: no 'shall' in statement")
        return issues

    def check_standard(self, draft_dict: dict) -> list[str]:
        issues = []
        domains  = draft_dict.get("domain_clusters", [])
        defs     = draft_dict.get("definitions", [])
        roles    = draft_dict.get("roles_responsibilities", [])

        if len(domains) < 3:
            issues.append(f"DOMAIN_CLUSTERS: only {len(domains)} (min 3)")
        if len(defs) < 5:
            issues.append(f"DEFINITIONS: only {len(defs)} (min 5)")
        if len(roles) < 3:
            issues.append(f"ROLES: only {len(roles)} (min 3)")

        for i, dom in enumerate(domains):
            reqs = dom.get("requirements", [])
            if len(reqs) < 3:
                issues.append(f"domain[{i}]: only {len(reqs)} requirements (min 3)")
        return issues


# ── BundleFilter ──────────────────────────────────────────────────────────────

class BundleFilter:
    """
    Filters and ranks a bundle list to the most relevant subset for a section topic.
    Deterministic — uses keyword overlap scoring, no embeddings.
    """

    def filter_for_section(
        self,
        bundles: list,        # list[ControlBundle]
        section_keywords: list[str],
        top_k: int = 20,
    ) -> list:
        """Return top_k most keyword-relevant bundles for the given section."""
        if not bundles or not section_keywords:
            return bundles[:top_k]

        kw_lower = [k.lower() for k in section_keywords]

        def score(b) -> int:
            text = f"{b.title} {b.statement} {b.domain}".lower()
            return sum(1 for kw in kw_lower if kw in text)

        scored = sorted(bundles, key=score, reverse=True)
        return scored[:top_k]


# ── WordCounter ───────────────────────────────────────────────────────────────

class WordCounter:
    """Counts words in text fields — deterministic quality gating."""

    @staticmethod
    def count(text: str) -> int:
        if not text:
            return 0
        return len(text.split())

    @classmethod
    def check_field(cls, text: str, field_name: str, min_words: int) -> str | None:
        """Return issue string if word count is below minimum, else None."""
        wc = cls.count(text)
        if wc < min_words:
            return f"{field_name}: {wc} words (min {min_words})"
        return None
