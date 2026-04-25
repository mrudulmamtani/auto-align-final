"""
Control Enrichment Agent — adds implementation notes and evidence examples
to each retrieved control chunk. MUST NOT create new obligations; may only
add guidance on how to satisfy the existing control statement.
"""
import json
from .rate_limited_client import get_openai_client
from ..config import OPENAI_API_KEY, ENRICH_MODEL
from ..models import ControlChunk, ControlBundle, RetrievalPacket

_SYSTEM = """\
You are the Control Enrichment agent for a cybersecurity document factory.
You may add implementation guidance and evidence examples, but you MUST NOT create new obligations.
All output must be strictly grounded in the control statement provided — do not introduce requirements
that are not present in the source text.
"""

_ENRICH_SCHEMA = {
    "name": "EnrichmentBatch",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "bundles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id":             {"type": "string"},
                        "implementation_notes": {"type": "array", "items": {"type": "string"}},
                        "evidence_examples":    {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["chunk_id", "implementation_notes", "evidence_examples"],
                    "additionalProperties": False,
                }
            }
        },
        "required": ["bundles"],
        "additionalProperties": False,
    }
}


class EnrichmentAgent:
    def __init__(self):
        self._client = get_openai_client()

    def enrich(self, packet: RetrievalPacket) -> list[ControlBundle]:
        # Process in batches of 10 to stay within token limits
        bundles: list[ControlBundle] = []
        batch_size = 10
        chunks = packet.chunks

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            print(f"[Enricher] Enriching controls {i+1}–{min(i+batch_size, len(chunks))} / {len(chunks)}")
            bundles.extend(self._enrich_batch(batch))

        return bundles

    def _enrich_batch(self, chunks: list[ControlChunk]) -> list[ControlBundle]:
        controls_payload = [
            {"chunk_id": c.chunk_id, "control_id": c.control_id,
             "title": c.title, "statement": c.statement[:600]}
            for c in chunks
        ]
        user_msg = (
            "For each control below, provide up to 3 concise implementation_notes (bullets on how to satisfy the control) "
            "and up to 3 evidence_examples (audit artifacts that prove compliance). "
            "Do not add any SHALL/MUST/REQUIRED statements — guidance only.\n\n"
            + json.dumps(controls_payload, indent=2)
        )

        resp = self._client.chat.completions.create(
            model=ENRICH_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            response_format={"type": "json_schema", "json_schema": _ENRICH_SCHEMA},
            temperature=0.1,
        )
        raw = json.loads(resp.choices[0].message.content)

        # Map results back to ControlBundle objects using chunk index
        chunk_map = {c.chunk_id: c for c in chunks}
        result: list[ControlBundle] = []
        for b in raw["bundles"]:
            c = chunk_map.get(b["chunk_id"])
            if not c:
                continue
            result.append(ControlBundle(
                chunk_id             = c.chunk_id,
                control_id           = c.control_id,
                title                = c.title,
                statement            = c.statement,
                domain               = c.domain,
                framework            = c.framework,
                uae_ia_id            = c.uae_ia_id,
                nca_id               = c.nca_id,
                implementation_notes = b["implementation_notes"],
                evidence_examples    = b["evidence_examples"],
            ))

        # Pass through any chunks not returned by the LLM (shouldn't happen but defensive)
        enriched_ids = {b.chunk_id for b in result}
        for c in chunks:
            if c.chunk_id not in enriched_ids:
                result.append(ControlBundle(
                    chunk_id=c.chunk_id, control_id=c.control_id, title=c.title,
                    statement=c.statement, domain=c.domain, framework=c.framework,
                    uae_ia_id=c.uae_ia_id, nca_id=c.nca_id,
                    implementation_notes=[], evidence_examples=[],
                ))
        return result
