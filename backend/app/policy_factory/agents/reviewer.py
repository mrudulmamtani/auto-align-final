"""
Compliance Review Agent — independent second-pass LLM that does NOT rewrite;
it produces structured findings against the draft.
Runs AFTER the deterministic validation gates have passed.
"""
import json
from .rate_limited_client import get_openai_client
from ..config import OPENAI_API_KEY, PLAN_MODEL
from ..models import DraftOutput, ControlBundle, ValidationReport, ValidationFinding

_SYSTEM = """\
You are the Compliance Reviewer for a cybersecurity governance document factory.
You do not rewrite the document. You produce structured findings only.

You must:
- Verify that every normative requirement (is_normative=true) cites at least one real chunk_id.
- Verify that cited control_ids in mapped_control_ids match those in the provided control bundles.
- Flag any contradictions (e.g., two requirements with conflicting retention periods).
- Flag missing topics required by the document_spec but absent from the draft.
- Do NOT create new requirements. Do NOT suggest rephrasing obligations.
"""

_REVIEW_SCHEMA = {
    "name": "ReviewOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "overall_assessment": {"type": "string", "enum": ["PASS", "FAIL"]},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "finding_id":     {"type": "string"},
                        "severity":       {"type": "string", "enum": ["FAIL", "WARN"]},
                        "check":          {"type": "string"},
                        "message":        {"type": "string"},
                        "affected_req_id":{"type": "string"},
                    },
                    "required": ["finding_id", "severity", "check", "message", "affected_req_id"],
                    "additionalProperties": False,
                }
            }
        },
        "required": ["overall_assessment", "findings"],
        "additionalProperties": False,
    }
}


class ReviewerAgent:
    def __init__(self):
        self._client = get_openai_client()

    def review(
        self,
        draft: DraftOutput,
        bundles: list[ControlBundle],
        validation_report: ValidationReport,
    ) -> tuple[bool, list[str]]:
        """Returns (passed, list_of_finding_messages_for_redrafter)."""
        print("[Reviewer] Running compliance review...")

        chunk_ids_in_packet = {b.chunk_id for b in bundles}
        # Send all bundles — only 3 small fields each, well within context limits
        bundle_summary = [
            {"chunk_id": b.chunk_id, "control_id": b.control_id, "title": b.title}
            for b in bundles
        ]

        draft_sections = [
            {
                "section_id": s.section_id,
                "title": s.title,
                "requirements": [
                    {
                        "req_id":             r.req_id,
                        "text":               r.text[:300],
                        "is_normative":       r.is_normative,
                        "citations":          r.citations,
                        "mapped_control_ids": r.mapped_control_ids,
                    }
                    for r in s.requirements
                ]
            }
            for s in draft.sections
        ]

        kwargs: dict = {
            "model":   PLAN_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps({
                    "draft_sections":    draft_sections,
                    "available_bundles": bundle_summary,
                    "validation_report": validation_report.model_dump(),
                })},
            ],
            "response_format": {"type": "json_schema", "json_schema": _REVIEW_SCHEMA},
        }
        if not PLAN_MODEL.startswith("o"):
            kwargs["temperature"] = 0.1
        resp = self._client.chat.completions.create(**kwargs)

        raw = json.loads(resp.choices[0].message.content)
        passed = raw["overall_assessment"] == "PASS"
        findings = [
            ValidationFinding(
                finding_id    = f["finding_id"],
                severity      = f["severity"],
                check         = f["check"],
                message       = f["message"],
                affected_req_id = f.get("affected_req_id") or None,
            )
            for f in raw["findings"]
        ]

        fail_msgs = [f"{f.severity}|{f.check}: {f.message}" for f in findings if f.severity == "FAIL"]
        warn_count = sum(1 for f in findings if f.severity == "WARN")
        print(f"[Reviewer] Result: {raw['overall_assessment']} | "
              f"{len(fail_msgs)} FAILs, {warn_count} WARNs")
        return passed, fail_msgs
