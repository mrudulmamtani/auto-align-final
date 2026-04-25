"""
Editorial Agent — improves clarity and consistency of the approved draft.
MUST preserve: requirement IDs, citations arrays, mapped_control_ids,
and all SHALL/MUST/REQUIRED/WILL language. It may only improve prose style.
"""
import json
from .rate_limited_client import get_openai_client
from ..config import OPENAI_API_KEY, DRAFT_MODEL
from ..models import DraftOutput, DraftSection, Requirement

_SYSTEM = """\
You are the Editorial agent for a cybersecurity governance document factory.
You may improve clarity, grammar, and formal tone — but you MUST preserve:
- All requirement IDs (req_id) exactly as given.
- All citations[] arrays exactly as given (do not add, remove, or change chunk_ids).
- All mapped_control_ids[] exactly as given.
- All normative language (SHALL, MUST, REQUIRED, WILL) — you may not soften or remove them.
- All section IDs and titles.
Do not add new requirements. Do not remove existing requirements.
Return the same JSON structure with only the "text" field of requirements improved.
"""

_EDIT_SCHEMA = {
    "name": "EditedDraft",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string"},
                        "title":      {"type": "string"},
                        "purpose":    {"type": "string"},
                        "requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "req_id":             {"type": "string"},
                                    "text":               {"type": "string"},
                                    "is_normative":       {"type": "boolean"},
                                    "citations":          {"type": "array", "items": {"type": "string"}},
                                    "mapped_control_ids": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["req_id", "text", "is_normative", "citations", "mapped_control_ids"],
                                "additionalProperties": False,
                            }
                        }
                    },
                    "required": ["section_id", "title", "purpose", "requirements"],
                    "additionalProperties": False,
                }
            }
        },
        "required": ["sections"],
        "additionalProperties": False,
    }
}


class EditorialAgent:
    def __init__(self):
        self._client = get_openai_client()

    def edit(self, draft: DraftOutput) -> DraftOutput:
        print("[Editor] Refining document prose...")

        sections_payload = [
            {
                "section_id": s.section_id,
                "title":      s.title,
                "purpose":    s.purpose,
                "requirements": [
                    {
                        "req_id":             r.req_id,
                        "text":               r.text,
                        "is_normative":       r.is_normative,
                        "citations":          r.citations,
                        "mapped_control_ids": r.mapped_control_ids,
                    }
                    for r in s.requirements
                ],
            }
            for s in draft.sections
        ]

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": (
                    "Improve the prose of the requirements below. "
                    "Preserve all IDs, citations, and normative language exactly.\n\n"
                    + json.dumps({"sections": sections_payload})
                )},
            ],
            response_format={"type": "json_schema", "json_schema": _EDIT_SCHEMA},
            temperature=0.2,
        )

        raw = json.loads(resp.choices[0].message.content)

        edited_sections = []
        for s_raw, s_orig in zip(raw["sections"], draft.sections):
            reqs = []
            for r_raw in s_raw["requirements"]:
                # Enforce preservation: IDs and citations are copied from original
                orig = next((r for r in s_orig.requirements if r.req_id == r_raw["req_id"]), None)
                reqs.append(Requirement(
                    req_id             = r_raw["req_id"],
                    text               = r_raw["text"],
                    is_normative       = orig.is_normative if orig else r_raw["is_normative"],
                    citations          = orig.citations if orig else r_raw["citations"],
                    mapped_control_ids = orig.mapped_control_ids if orig else r_raw["mapped_control_ids"],
                ))
            edited_sections.append(DraftSection(
                section_id   = s_raw["section_id"],
                title        = s_raw["title"],
                purpose      = s_raw["purpose"],
                requirements = reqs,
            ))

        print("[Editor] Editorial pass complete.")
        return draft.model_copy(update={"sections": edited_sections})
