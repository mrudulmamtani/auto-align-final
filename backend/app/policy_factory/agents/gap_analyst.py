"""
Gap Analysis Agent — Agent 2 in the document generation workflow.

Compares NCA control requirements against available implementation detail
and enriches each bundle with operational guidance drawn from NIST SP 800-53
supplementary controls.

Workflow position:
  Retrieve → Enrich → Gap Analysis → Procedure Draft

For each NCA ControlBundle this agent:
  1. Assesses whether the control statement provides sufficient implementation
     and validation detail for writing a procedure.
  2. Searches the available NIST bundles for matching supplementary guidance.
  3. Produces an AugmentedControlContext with enriched implementation steps
     and validation guidance.

The augmented output is passed directly to draft_procedure() so the LLM
drafting agent has both the authoritative NCA control text AND pre-analyzed
operational steps, reducing hallucination and improving procedure depth.
"""
import json
from .rate_limited_client import get_openai_client

from ..config import OPENAI_API_KEY, ENRICH_MODEL
from ..models import ControlBundle, AugmentedControlContext


_GAP_SCHEMA = {
    "name": "GapAnalysisOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "augmented_contexts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "control_id":               {"type": "string"},
                        "chunk_id":                 {"type": "string"},
                        "enriched_description":     {"type": "string"},
                        "implementation_guidance":  {"type": "array", "items": {"type": "string"}},
                        "validation_guidance":      {"type": "array", "items": {"type": "string"}},
                        "gap_detected":             {"type": "boolean"},
                        "gap_type":                 {"type": "string"},
                        "nist_supplement":          {"type": "string"},
                    },
                    "required": [
                        "control_id", "chunk_id", "enriched_description",
                        "implementation_guidance", "validation_guidance",
                        "gap_detected", "gap_type", "nist_supplement",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["augmented_contexts"],
        "additionalProperties": False,
    },
}


class GapAnalysisAgent:
    """
    Agent 2: Gap Analysis Agent.

    Processes ControlBundles retrieved for a procedure to detect missing
    operational context and produce enriched implementation + validation guidance.
    NCA bundles are analyzed for gaps; NIST bundles are used as the gap-filling
    source. All NIST bundles are passed through as-is.
    """

    def __init__(self):
        self._client = get_openai_client()

    def analyze(
        self,
        bundles: list[ControlBundle],
        topic: str,
        doc_type: str = "procedure",
        existing_document: str | None = None,
    ) -> list[AugmentedControlContext]:
        """
        Run gap analysis on all control bundles.

        Returns a list of AugmentedControlContext objects — one per bundle —
        with enriched implementation_guidance and validation_guidance.
        NCA bundles are analyzed for gaps; NIST bundles are passed through.
        """
        print(f"[GapAnalyst] Analyzing {len(bundles)} bundles for: {topic}")

        nca_bundles  = [b for b in bundles if b.framework.upper().startswith("NCA")]
        nist_bundles = [b for b in bundles if b.framework == "NIST_80053"]

        print(f"[GapAnalyst] {len(nca_bundles)} NCA + {len(nist_bundles)} NIST bundles.")

        # Group NIST by domain for targeted gap-filling
        nist_by_domain: dict[str, list[ControlBundle]] = {}
        for b in nist_bundles:
            nist_by_domain.setdefault(b.domain, []).append(b)

        # Process NCA bundles in batches of 20 to manage context window
        all_contexts: list[AugmentedControlContext] = []
        batch_size = 20
        for i in range(0, len(nca_bundles), batch_size):
            batch = nca_bundles[i: i + batch_size]
            contexts = self._analyze_batch(batch, nist_by_domain, topic, doc_type, existing_document)
            all_contexts.extend(contexts)
            print(f"[GapAnalyst] Batch {i // batch_size + 1}: "
                  f"{len(contexts)} contexts produced.")

        # NIST bundles pass through — they ARE the supplementary source
        for b in nist_bundles:
            all_contexts.append(AugmentedControlContext(
                control_id              = b.control_id,
                chunk_id                = b.chunk_id,
                enriched_description    = b.statement,
                implementation_guidance = b.implementation_notes,
                validation_guidance     = b.evidence_examples,
                gap_detected            = False,
                gap_type                = "none",
                nist_supplement         = "",
            ))

        gaps = sum(1 for c in all_contexts if c.gap_detected)
        print(f"[GapAnalyst] Complete: {len(all_contexts)} contexts, {gaps} gaps detected.")
        return all_contexts

    # ── Private ───────────────────────────────────────────────────────────────

    def _analyze_batch(
        self,
        nca_bundles: list[ControlBundle],
        nist_by_domain: dict[str, list[ControlBundle]],
        topic: str,
        doc_type: str,
        existing_document: str | None = None,
    ) -> list[AugmentedControlContext]:
        """Analyze a batch of NCA bundles and return augmented contexts."""
        # Collect relevant NIST supplements for domains present in this batch
        domains = {b.domain for b in nca_bundles}
        nist_supplements: list[ControlBundle] = []
        for domain in domains:
            nist_supplements.extend(nist_by_domain.get(domain, [])[:3])

        bundle_data = [
            {
                "chunk_id":   b.chunk_id,
                "control_id": b.control_id,
                "framework":  b.framework,
                "title":      b.title,
                "statement":  b.statement[:400],
                "domain":     b.domain,
                "impl_notes": b.implementation_notes,
                "evidence":   b.evidence_examples,
            }
            for b in nca_bundles
        ]

        nist_data = [
            {
                "chunk_id":   b.chunk_id,
                "control_id": b.control_id,
                "title":      b.title,
                "statement":  b.statement[:300],
                "domain":     b.domain,
            }
            for b in nist_supplements[:15]
        ]

        existing_doc_note = ""
        if existing_document:
            existing_doc_note = (
                "\nYou are performing a TRUE gap analysis comparing the existing document "
                "against required controls. Identify what is present, what is missing, "
                "and what is inadequate."
            )

        system_msg = f"""\
You are a cybersecurity GRC gap analysis specialist supporting the generation of
operational {doc_type} documents for the topic: {topic}.{existing_doc_note}

Your task: analyze each NCA control bundle and determine whether it provides
sufficient implementation and validation detail for an operational procedure.

For EACH NCA control:
1. Read the control statement and any existing implementation notes.
2. Assess whether it lacks:
   - Concrete implementation steps (gap_type: "implementation")
   - Configuration baselines or technical parameters (gap_type: "configuration")
   - Verification methods or test procedures (gap_type: "validation")
   - Nothing — control is fully operational (gap_type: "none")
3. If a gap exists, check the NIST supplementary controls for relevant detail.
4. Produce enriched implementation_guidance: 3–5 concrete, actionable steps.
5. Produce validation_guidance: 2–4 specific tests or evidence checks.

RULES:
- implementation_guidance must be operational (imperative voice, e.g. "Configure X to Y")
- validation_guidance must describe specific observable tests or evidence artifacts
- nist_supplement: cite the NIST control_id and brief title that fills the gap;
  use empty string "" if no gap was detected
- gap_type must be exactly one of: "implementation", "configuration", "validation", "none"
"""

        user_payload = {
            "topic":                     topic,
            "doc_type":                  doc_type,
            "nca_bundles":               bundle_data,
            "nist_supplements_available": nist_data,
        }
        if existing_document:
            user_payload["existing_document_excerpt"] = existing_document[:3000]

        resp = self._client.chat.completions.create(
            model=ENRICH_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": (
                    "Analyze each NCA bundle. Detect gaps and enrich with NIST where needed. "
                    "Return one augmented_context per NCA bundle in the same order."
                )},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _GAP_SCHEMA},
            temperature=0.2,
        )

        raw = json.loads(resp.choices[0].message.content)
        contexts: list[AugmentedControlContext] = []
        for c in raw["augmented_contexts"]:
            try:
                contexts.append(AugmentedControlContext(
                    control_id              = c["control_id"],
                    chunk_id                = c["chunk_id"],
                    enriched_description    = c["enriched_description"],
                    implementation_guidance = c["implementation_guidance"],
                    validation_guidance     = c["validation_guidance"],
                    gap_detected            = c["gap_detected"],
                    gap_type                = c["gap_type"],
                    nist_supplement         = c["nist_supplement"],
                ))
            except Exception as exc:
                print(f"[GapAnalyst] Warning: Could not parse context for "
                      f"'{c.get('control_id', '?')}': {exc}")
        return contexts
