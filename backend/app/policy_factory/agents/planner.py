"""
Planner Agent — first agent in the pipeline.
Receives EntityProfile + DocumentSpec and produces a DocumentPlan:
structured section blueprint with retrieval queries per section.
Uses structured outputs (strict JSON) so the pipeline can rely on the schema.
"""
import json
from .rate_limited_client import get_openai_client
from ..config import OPENAI_API_KEY, PLAN_MODEL
from ..models import EntityProfile, DocumentSpec, DocumentPlan, SectionBlueprint

_SYSTEM = """\
You are the Planner for a cybersecurity governance document factory.
You must be precise and conservative — do not invent regulatory requirements.

Rules:
- Every section you define must have a clear security purpose grounded in the entity's sector and jurisdiction.
- Produce retrieval_queries that are specific enough to find the right controls (e.g. "access control account management privileged users" not just "access").
- required_control_ids must reference real NIST SP 800-53 Rev.5 or UAE IA control IDs only. Leave empty if unsure.
- Output ONLY the JSON object matching the schema. No prose, no markdown fences.
"""

_DEVELOPER = """\
Produce a DocumentPlan JSON object for the document described in the user message.
The plan must include 5–9 sections covering the topic comprehensively.
Each section needs 2–4 retrieval_queries that a vector-search retriever will use to fetch controls.
"""


def _build_user_msg(profile: EntityProfile, spec: DocumentSpec) -> str:
    return json.dumps({
        "entity_profile": profile.model_dump(),
        "document_spec":  spec.model_dump(),
    }, indent=2)


# JSON schema that OpenAI structured outputs will enforce
_PLAN_SCHEMA = {
    "name": "DocumentPlan",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_type":          {"type": "string"},
            "topic":             {"type": "string"},
            "org_name":          {"type": "string"},
            "executive_summary": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id":        {"type": "string"},
                        "title":             {"type": "string"},
                        "purpose":           {"type": "string"},
                        "control_domains":   {"type": "array", "items": {"type": "string"}},
                        "retrieval_queries": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["section_id", "title", "purpose", "control_domains", "retrieval_queries"],
                    "additionalProperties": False,
                }
            },
            "required_control_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["doc_type", "topic", "org_name", "executive_summary", "sections", "required_control_ids"],
        "additionalProperties": False,
    }
}


class PlannerAgent:
    def __init__(self):
        self._client = get_openai_client()

    def plan(self, profile: EntityProfile, spec: DocumentSpec) -> DocumentPlan:
        print(f"[Planner] Generating document plan with {PLAN_MODEL}...")
        # o-series reasoning models do not accept a temperature parameter
        kwargs: dict = {
            "model":           PLAN_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": _DEVELOPER},
                {"role": "user",   "content": _build_user_msg(profile, spec)},
            ],
            "response_format": {"type": "json_schema", "json_schema": _PLAN_SCHEMA},
        }
        if not PLAN_MODEL.startswith("o"):
            kwargs["temperature"] = 0.2
        resp = self._client.chat.completions.create(**kwargs)
        raw = json.loads(resp.choices[0].message.content)
        plan = DocumentPlan(
            doc_type              = raw["doc_type"],
            topic                 = raw["topic"],
            org_name              = raw["org_name"],
            executive_summary     = raw["executive_summary"],
            required_control_ids  = raw.get("required_control_ids", []),
            sections              = [SectionBlueprint(**s) for s in raw["sections"]],
        )
        print(f"[Planner] Plan complete: {len(plan.sections)} sections, "
              f"{len(plan.required_control_ids)} required controls.")
        return plan
