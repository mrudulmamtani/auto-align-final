"""
Drafting Agent — the highest-power LLM use in the pipeline.
Generates schema-locked JSON where EVERY normative statement (SHALL/MUST/REQUIRED)
carries at least one citation chunk_id from the RetrievalPacket.
This is the core anti-hallucination gate: the model cannot invent requirements
without grounding them in a retrieved control.
"""
import json
from .rate_limited_client import get_openai_client
from ..config import OPENAI_API_KEY, DRAFT_MODEL, DRAFT_MODEL_POLICY
from ..schema_loader import schema_as_prompt_text
from ..models import (
    EntityProfile, DocumentSpec, DocumentPlan, SectionBlueprint,
    ControlBundle, RetrievalPacket, DraftOutput, DraftSection, Requirement,
    PolicyDraftOutput, PolicyElement, Subprogram, RolesResponsibilities, TraceEntry,
    SUBPROGRAM_CATALOG,
    StandardDraftOutput, StandardDefinition, StandardRequirement, StandardDomain,
    StandardRoleItem, STANDARD_TOC, EXCEPTIONS_CLAUSE,
    ProcedureDraftOutput, ProcedureRoleItem, ProcedureStep, ProcedurePhase,
    ProcedureVerificationCheck, AugmentedControlContext, PROCEDURE_TOC,
)

_SYSTEM = """\
You draft cybersecurity {doc_type} content for {org_name}.

HARD RULES — violating any rule makes the document unacceptable:
1) Every statement containing SHALL, MUST, REQUIRED, or WILL must include at least one
   citation chunk_id drawn from the provided RetrievalPacket. No citation = no normative statement.
2) Do not invent control requirements not present in the RetrievalPacket chunks.
3) mapped_control_ids must be derived from the control_id field of cited chunks only.
4) req_id values must be unique within the document (format: S<section_num>-R<req_num>, e.g. S1-R1).
5) is_normative must be true if and only if the text contains SHALL, MUST, REQUIRED, or WILL.
6) citations[] must never be empty for normative requirements.
7) Non-normative statements (guidance, rationale) may have empty citations[].
"""

_DEVELOPER = """\
Using the DocumentPlan and ControlBundles below, draft the full {doc_type}.
Each section must contain 3–8 requirements.
Normative requirements (SHALL/MUST) must cite chunk_ids from the bundle.
Non-normative guidance lines should be marked is_normative: false.
"""

# Schema enforced by OpenAI structured outputs
_DRAFT_SCHEMA = {
    "name": "DraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id":       {"type": "string"},
            "doc_type":     {"type": "string"},
            "topic":        {"type": "string"},
            "org_name":     {"type": "string"},
            "version":      {"type": "string"},
            "generated_at": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_id":   {"type": "string"},
                        "title":        {"type": "string"},
                        "purpose":      {"type": "string"},
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
        "required": ["doc_id", "doc_type", "topic", "org_name", "version", "generated_at", "sections"],
        "additionalProperties": False,
    }
}


# Schema for single-section drafting — tighter context, less hallucination risk
_SECTION_SCHEMA = {
    "name": "DraftSection",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "section_id":   {"type": "string"},
            "title":        {"type": "string"},
            "purpose":      {"type": "string"},
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
            },
        },
        "required": ["section_id", "title", "purpose", "requirements"],
        "additionalProperties": False,
    }
}


def _bundle_summary(bundles: list[ControlBundle]) -> list[dict]:
    return [
        {
            "chunk_id":    b.chunk_id,
            "control_id":  b.control_id,
            "title":       b.title,
            "statement":   b.statement[:400],
            "uae_ia_id":   b.uae_ia_id,
            "impl_notes":  b.implementation_notes,
        }
        for b in bundles
    ]


class DraftingAgent:
    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        plan: DocumentPlan,
        bundles: list[ControlBundle],
        reviewer_findings: list[str] | None = None,
    ) -> DraftOutput:
        print(f"[Drafter] Drafting {spec.doc_type} on '{spec.topic}' with {len(bundles)} control bundles...")

        system_msg = _SYSTEM.format(doc_type=spec.doc_type, org_name=profile.org_name)
        developer_msg = _DEVELOPER.format(doc_type=spec.doc_type)

        user_payload: dict = {
            "entity_profile":  profile.model_dump(),
            "document_spec":   spec.model_dump(),
            "document_plan":   {
                "executive_summary": plan.executive_summary,
                "sections":          [s.model_dump() for s in plan.sections],
            },
            "control_bundles": _bundle_summary(bundles),
        }
        if reviewer_findings:
            user_payload["reviewer_findings_to_fix"] = reviewer_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": developer_msg},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _DRAFT_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)
        sections = []
        for s in raw["sections"]:
            reqs = []
            for r in s["requirements"]:
                reqs.append(Requirement(
                    req_id             = r["req_id"],
                    text               = r["text"],
                    is_normative       = r["is_normative"],
                    citations          = r["citations"],
                    mapped_control_ids = r["mapped_control_ids"],
                ))
            sections.append(DraftSection(
                section_id   = s["section_id"],
                title        = s["title"],
                purpose      = s["purpose"],
                requirements = reqs,
            ))

        draft = DraftOutput(
            doc_id       = raw.get("doc_id", f"DOC-{spec.doc_type[:3].upper()}-001"),
            doc_type     = raw["doc_type"],
            topic        = raw["topic"],
            org_name     = raw["org_name"],
            version      = raw.get("version", spec.version),
            generated_at = raw.get("generated_at", ""),
            sections     = sections,
        )
        norm_count = sum(1 for r in draft.all_requirements if r.is_normative)
        print(f"[Drafter] Draft complete: {len(sections)} sections, "
              f"{len(draft.all_requirements)} requirements ({norm_count} normative).")
        return draft

    def draft_section(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        blueprint: SectionBlueprint,
        bundles: list[ControlBundle],
        section_num: int,
        reviewer_findings: list[str] | None = None,
    ) -> DraftSection:
        """
        Draft a single section in isolation.
        Smaller context → tighter citation discipline → fewer cross-section hallucinations.
        req_ids are formatted S<section_num>-R<n> (e.g. S3-R1).
        """
        print(f"[Drafter] Drafting section {section_num}: '{blueprint.title}' "
              f"with {len(bundles)} bundles...")

        system_msg = _SYSTEM.format(doc_type=spec.doc_type, org_name=profile.org_name)

        user_payload: dict = {
            "section_blueprint": blueprint.model_dump(),
            "section_number":    section_num,
            "req_id_format":     f"S{section_num}-R<n>  (e.g. S{section_num}-R1, S{section_num}-R2)",
            "doc_type":          spec.doc_type,
            "topic":             spec.topic,
            "target_audience":   spec.target_audience,
            "control_bundles":   _bundle_summary(bundles),
        }
        if reviewer_findings:
            user_payload["reviewer_findings_to_fix"] = reviewer_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": (
                    f"Draft ONLY the section described in section_blueprint. "
                    f"Every normative requirement must cite chunk_ids from control_bundles. "
                    f"Produce 3–8 requirements for this section."
                )},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _SECTION_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)
        reqs = [
            Requirement(
                req_id             = r["req_id"],
                text               = r["text"],
                is_normative       = r["is_normative"],
                citations          = r["citations"],
                mapped_control_ids = r["mapped_control_ids"],
            )
            for r in raw["requirements"]
        ]
        section = DraftSection(
            section_id   = raw["section_id"],
            title        = raw["title"],
            purpose      = raw["purpose"],
            requirements = reqs,
        )
        norm = sum(1 for r in reqs if r.is_normative)
        print(f"[Drafter] Section {section_num} complete: {len(reqs)} reqs ({norm} normative).")
        return section

    def draft_policy(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> PolicyDraftOutput:
        """
        Draft a complete Golden Policy Baseline document (POL-*).
        Enforces: exact TOC, elements 1/2/3, 34 subprograms, 7 role groups,
        exactly 3 compliance clauses, exceptions blocking clause, closing note.
        All 'shall' statements must carry trace entries from the provided bundles.
        Uses DRAFT_MODEL_POLICY (gpt-4.5) for highest quality.
        """
        print(f"[Drafter] Drafting Golden Policy {doc_id} with {len(bundles)} bundles "
              f"using {DRAFT_MODEL_POLICY}...")

        bundle_lookup = {b.control_id: b.chunk_id for b in bundles}
        bundle_list = [
            {
                "chunk_id":   b.chunk_id,
                "control_id": b.control_id,
                "framework":  b.framework,
                "title":      b.title,
                "statement":  b.statement[:500],
                "rerank_score": round(b.rerank_score, 4) if b.rerank_score is not None else None,
            }
            for b in bundles
        ]

        catalog_prompt = "\n".join(
            f"  {sub_no}: {name}" for sub_no, name in SUBPROGRAM_CATALOG
        )

        _policy_schema_text = schema_as_prompt_text("policy")

        system_msg = f"""\
You are the Senior Policy Author for {profile.org_name} ({profile.sector}, {profile.jurisdiction}).
You are a SCHEMA-DRIVEN COMPILER. You do not behave as a creative writing model.
You build documents using the authoritative schema below as your only structural authority.

{_policy_schema_text}

COMPILER WORKFLOW (mandatory):
1. Load schema → identify document_order and section_blueprints
2. Construct internal AST: Cover → TOC → DocInfo → Definitions → Objective → Scope →
   PolicyStatement → Roles → RelatedDocs → EffectiveDate → PolicyReview → Approval → VersionControl
3. Generate text for each section from schema blueprint rules
4. Validate Section 4 (policy_statement) is the dominant section (40–55% of content)
5. Output compliant JSON

FRAMEWORK HIERARCHY (MANDATORY):
NCA controls (framework starting with NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC,
NCA_OSMACC, NCA_NCS) are the PRIMARY and AUTHORITATIVE basis for this policy.
NIST SP 800-53 controls (framework=NIST_80053) are SUPPLEMENTARY only — cite them
ONLY when no NCA control adequately covers the requirement.
EVERY 'shall' statement MUST have at least one NCA_ trace entry. NIST may be added as
a secondary entry but cannot replace NCA.

ABSOLUTE RULES:
1. EVERY 'shall' statement in policy_elements MUST include at least one trace entry with
   framework starting 'NCA_', using a real control_id from the provided control_bundles.
   No fabricated IDs. NIST may appear as a secondary trace alongside NCA.
2. source_ref in each trace entry MUST be the chunk_id of the cited bundle.
3. objectives_en MUST mention Confidentiality, Integrity, and Availability and reference
   NCA ECC (e.g. ECC 1-3-1) as the regulatory basis.
4. scope_applicability_en MUST state this policy applies to all assets and all personnel,
   and that it drives all cyber policies/procedures/standards and feeds HR, vendor management,
   project management, and change management processes.
5. policy_elements MUST include elements 1, 2, and 3 exactly as specified below.
6. policy_subprograms MUST include ALL 34 items (2-1 through 2-34) from the catalog below.
   Generate a concise objective_en for each. Suggest relevant document references.
7. compliance_clauses MUST be exactly 3 items:
   (1) cybersecurity ensures continuous compliance monitoring
   (2) all staff must comply with this policy
   (3) violations may lead to disciplinary/legal action
8. exceptions_en MUST state no bypass is permitted without prior official authorization
   from the Cybersecurity function or the Cyber Supervisory Committee.
9. closing_note_en MUST state that all policies and standards are approved and in force.

TARGET DOCUMENT LENGTH: 5–8 Word pages when rendered.
To meet this target, write with the following content depth:
- objectives_en: 250+ words covering governance philosophy, CIA triad, NCA ECC regulatory basis, and strategic security intent.
- scope_applicability_en: 200+ words specifying all personnel categories (employees, contractors, consultants, third-parties, visitors), all asset types, and all downstream documents this policy drives (standards, procedures, guidelines, awareness programs).
- Each policy_element statement_en: 150+ words — elaborate on the intent, accountable party, and how the element is operationalised.
- Each subprogram objective_en: 40+ words explaining what the sub-policy governs and its importance to the overall program.
- roles_responsibilities: Each of the 7 role groups must list 4–6 specific, distinct responsibilities.
- compliance_clauses: Each of the 3 clauses should be a full sentence of 30+ words.
- exceptions_en: 100+ words covering the formal exception request process.

REQUIRED ELEMENT CONTENT:
Element 1: The Cybersecurity function shall define, document, and maintain cybersecurity
requirements, policies, and programs based on risk assessment, approved by the Authority
or Authorized Official (or delegate), and communicated to all relevant parties.
Element 2: The Cybersecurity function shall develop and implement the cybersecurity policy
suite comprising the 34 sub-programs listed below.
Element 3: The Cybersecurity function shall have the right to access information systems
and collect evidence to verify compliance with this policy and all related sub-policies.

SUBPROGRAM CATALOG (use these exact sub_no and name_en values):
{catalog_prompt}
"""

        user_payload: dict = {
            "doc_id":          doc_id,
            "org_name":        profile.org_name,
            "sector":          profile.sector,
            "jurisdiction":    profile.jurisdiction,
            "doc_type":        spec.doc_type,
            "topic":           spec.topic,
            "version":         spec.version,
            "control_bundles": bundle_list,
        }
        if qa_findings:
            user_payload["qa_findings_to_fix"] = qa_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL_POLICY,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": (
                    "Compile the complete Policy document following the authoritative schema. "
                    "Trace every 'shall' to real NCA control_ids from control_bundles. "
                    "Include ALL 34 subprograms. Section 4 must be the dominant section. "
                    "Output valid JSON matching the schema."
                )},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _POLICY_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)

        # Parse policy elements
        elements = [
            PolicyElement(
                element_no   = e["element_no"],
                statement_en = e["statement_en"],
                trace        = [TraceEntry(**t) for t in e["trace"]],
            )
            for e in raw["policy_elements"]
        ]

        subprograms = [
            Subprogram(
                sub_no      = s["sub_no"],
                name_en     = s["name_en"],
                objective_en = s["objective_en"],
                references  = s.get("references", []),
            )
            for s in raw["policy_subprograms"]
        ]

        rr_raw = raw["roles_responsibilities"]
        roles = RolesResponsibilities(
            authority_owner_delegates = rr_raw["authority_owner_delegates"],
            legal                     = rr_raw["legal"],
            internal_audit            = rr_raw["internal_audit"],
            HR                        = rr_raw["HR"],
            cybersecurity             = rr_raw["cybersecurity"],
            other_departments         = rr_raw["other_departments"],
            all_staff                 = rr_raw["all_staff"],
        )

        draft = PolicyDraftOutput(
            doc_id                 = raw.get("doc_id", doc_id),
            title_en               = raw["title_en"],
            version                = raw.get("version", spec.version),
            effective_date         = raw.get("effective_date", "TBD"),
            owner                  = raw.get("owner", "Chief Information Security Officer"),
            classification         = raw.get("classification", "Internal"),
            objectives_en          = raw["objectives_en"],
            scope_applicability_en = raw["scope_applicability_en"],
            policy_elements        = elements,
            policy_subprograms     = subprograms,
            roles_responsibilities = roles,
            compliance_clauses     = raw["compliance_clauses"],
            exceptions_en          = raw["exceptions_en"],
            closing_note_en        = raw["closing_note_en"],
        )

        print(f"[Drafter] Policy draft complete: {len(elements)} elements, "
              f"{len(subprograms)} subprograms.")
        return draft


    def draft_standard(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> StandardDraftOutput:
        """
        Draft a complete Golden Standard Baseline document (STD-*).
        Enforces: exact 6-section TOC, min 5 definitions, CIA objectives, scope + exceptions clause,
        min 3 domains each with objective/risks/requirements, 3-item roles,
        3-trigger review, exactly 3 compliance clauses, closing note.
        All 'shall' statements must carry NCA trace entries from the provided bundles.
        Uses DRAFT_MODEL_POLICY for highest quality.
        """
        print(f"[Drafter] Drafting Golden Standard {doc_id} with {len(bundles)} bundles "
              f"using {DRAFT_MODEL_POLICY}...")

        bundle_list = [
            {
                "chunk_id":     b.chunk_id,
                "control_id":   b.control_id,
                "framework":    b.framework,
                "title":        b.title,
                "statement":    b.statement[:500],
                "rerank_score": round(b.rerank_score, 4) if b.rerank_score is not None else None,
            }
            for b in bundles
        ]

        _standard_schema_text = schema_as_prompt_text("standard")

        system_msg = f"""\
You are the Senior Standards Author for {profile.org_name} ({profile.sector}, {profile.jurisdiction}).
You are a SCHEMA-DRIVEN COMPILER. You do not behave as a creative writing model.
You build documents using the authoritative schema below as your only structural authority.

{_standard_schema_text}

COMPILER WORKFLOW (mandatory):
1. Load schema → identify document_order and section_blueprints
2. Construct internal AST: Cover → Notice → DocInfo → TOC → Definitions → Objective →
   Scope → Standards(4.1..4.N) → Exceptions → Roles → UpdateReview → Compliance
3. Section 4 (standards) must represent 45–60% of total document content
4. Each Section 4 cluster: title + objective + potential_risks + numbered requirements
5. Output compliant JSON

FRAMEWORK HIERARCHY (MANDATORY):
NCA controls (framework NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC, NCA_OSMACC, NCA_NCS)
are the PRIMARY and AUTHORITATIVE basis from which this standard is abstracted.
NIST SP 800-53 (framework NIST_80053) is SUPPLEMENTARY — cite only where NCA needs depth.
EVERY 'shall' MUST have at least one NCA_ trace entry. NIST may supplement but not replace.

ABSOLUTE RULES:
1. EVERY 'shall' statement in domain requirements MUST include at least one trace entry with
   framework starting 'NCA_', using a real control_id from the provided control_bundles.
   No fabricated control IDs. source_ref MUST be the chunk_id of the cited bundle.
   NIST may appear as an additional trace entry alongside NCA.
2. objectives_en MUST mention Confidentiality, Integrity, and Availability AND reference
   NCA ECC (e.g. ECC 1-3-1) as the primary regulatory basis.
3. scope_en MUST state applicability to all employees/contractors/service providers/consultants/visitors
   AND all information/technology assets/systems AND include this EXACT exceptions clause:
   "{EXCEPTIONS_CLAUSE}"
4. domains MUST have at least 5 domain blocks. Each domain MUST have:
   - objective_en: 120+ words describing the domain's purpose and security intent.
   - potential_risks_en: 120+ words covering 3–5 distinct risk scenarios with impact descriptions.
   - requirements: at least 5, req_id as "N.M" (e.g. "1.1", "1.2"), 'shall' language.
5. definitions MUST have at least 8 terms relevant to the standard topic, each description 50+ words.
6. roles_responsibilities MUST be exactly 3 items:
   item_no "1-" = Document Sponsor/Owner
   item_no "2-" = Review and Update Owner
   item_no "3-" = Implementation Owner (IT/OT/etc.)
7. review_update_en MUST mention all 3 triggers:
   - major technology changes
   - changes in policies/procedures
   - regulatory/legislative changes
8. compliance_en MUST be exactly 3 clauses:
   (1) cybersecurity ensures continuous compliance monitoring
   (2) all staff must comply with this standard
   (3) violations may lead to disciplinary/legal action
9. closing_note_en MUST state that only the latest approved standards are official and applicable.

TARGET DOCUMENT LENGTH: 10–13 Word pages when rendered.
To meet this target, write with the following content depth:
- objectives_en: 200+ words covering CIA triad, regulatory basis, and the specific security domain this standard governs.
- scope_en: 200+ words specifying applicability to all personnel, all asset types, and including the exceptions clause.
- Each domain objective_en: 120+ words.
- Each domain potential_risks_en: 120+ words covering 3–5 distinct risk scenarios.
- Each domain must have 5–8 requirements, each a full sentence with 'shall' language.
- definitions: 8+ terms, each description 50+ words.
- roles_responsibilities text_en: Each of the 3 role items 100+ words listing specific accountabilities.
- review_update_en: 150+ words covering all 3 triggers and the review process.
- Each compliance_en clause: 50+ words.
- closing_note_en: 80+ words.

DOCUMENT ORDER (from schema — must match exactly):
1. abbreviations_and_definitions
2. objective
3. scope_of_work_and_applicability
4. standards (Section 4.1 ... 4.N domain clusters — DOMINANT section)
5. exceptions
6. roles_and_responsibilities
7. update_and_review
8. compliance_with_the_standard

Generate domain blocks tailored to the standard topic: {spec.topic}.
"""

        user_payload: dict = {
            "doc_id":          doc_id,
            "org_name":        profile.org_name,
            "sector":          profile.sector,
            "jurisdiction":    profile.jurisdiction,
            "topic":           spec.topic,
            "version":         spec.version,
            "control_bundles": bundle_list,
        }
        if qa_findings:
            user_payload["qa_findings_to_fix"] = qa_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL_POLICY,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": (
                    "Compile the complete Standard document following the authoritative schema. "
                    "Trace every 'shall' to real NCA control_ids from control_bundles. "
                    "Section 4 must be 45-60% of content. Include min 3 domain clusters, "
                    "min 6 definitions. Output valid JSON."
                )},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _STANDARD_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)

        definitions = [
            StandardDefinition(term_en=d["term_en"], description_en=d["description_en"])
            for d in raw["definitions"]
        ]

        domains = []
        for dom in raw["domains"]:
            reqs = [
                StandardRequirement(
                    req_id       = r["req_id"],
                    statement_en = r["statement_en"],
                    placeholders = r.get("placeholders", []),
                    trace        = [TraceEntry(**t) for t in r["trace"]],
                )
                for r in dom["requirements"]
            ]
            domains.append(StandardDomain(
                domain_number      = dom["domain_number"],
                title_en           = dom["title_en"],
                objective_en       = dom["objective_en"],
                potential_risks_en = dom["potential_risks_en"],
                requirements       = reqs,
            ))

        roles = [
            StandardRoleItem(item_no=r["item_no"], text_en=r["text_en"])
            for r in raw["roles_responsibilities"]
        ]

        draft = StandardDraftOutput(
            doc_id            = raw.get("doc_id", doc_id),
            title_en          = raw["title_en"],
            version           = raw.get("version", spec.version),
            effective_date    = raw.get("effective_date", "TBD"),
            owner             = raw.get("owner", "Chief Information Security Officer"),
            classification    = raw.get("classification", "Internal"),
            definitions       = definitions,
            objectives_en     = raw["objectives_en"],
            scope_en          = raw["scope_en"],
            domains           = domains,
            roles_responsibilities = roles,
            review_update_en  = raw["review_update_en"],
            compliance_en     = raw["compliance_en"],
            closing_note_en   = raw["closing_note_en"],
        )

        total_reqs = sum(len(d.requirements) for d in domains)
        shall_n    = sum(
            1 for d in domains for r in d.requirements
            if "shall" in r.statement_en.lower()
        )
        print(f"[Drafter] Standard draft complete: {len(domains)} domains, "
              f"{total_reqs} requirements ({shall_n} shall).")
        return draft


    def draft_procedure(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        augmented_contexts: list[AugmentedControlContext],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> ProcedureDraftOutput:
        """
        Draft a complete Golden Procedure Baseline document (PRC-*).

        Enforces: 9-section TOC, 3+ roles, 3+ prerequisites, 2+ phases,
        5+ steps, 3+ verification checks, 2+ evidence artifacts,
        swimlane diagram (Mermaid LR), flowchart diagram (Mermaid TD).

        Steps must cite chunk_ids from the provided bundles.
        Augmented contexts from the Gap Analysis Agent supply enriched
        implementation and validation guidance for each control.
        Uses DRAFT_MODEL_POLICY for highest quality output.
        """
        print(f"[Drafter] Drafting Golden Procedure {doc_id} with {len(bundles)} bundles, "
              f"{len(augmented_contexts)} augmented contexts using {DRAFT_MODEL_POLICY}...")

        bundle_list = [
            {
                "chunk_id":     b.chunk_id,
                "control_id":   b.control_id,
                "framework":    b.framework,
                "title":        b.title,
                "statement":    b.statement[:400],
                "rerank_score": round(b.rerank_score, 4) if b.rerank_score is not None else None,
            }
            for b in bundles
        ]

        # Augmented guidance from Gap Analysis Agent — keyed by control_id
        aug_list = [
            {
                "control_id":              a.control_id,
                "chunk_id":                a.chunk_id,
                "implementation_guidance": a.implementation_guidance,
                "validation_guidance":     a.validation_guidance,
                "gap_detected":            a.gap_detected,
                "gap_type":                a.gap_type,
                "nist_supplement":         a.nist_supplement,
            }
            for a in augmented_contexts
            if a.implementation_guidance  # only include where guidance was produced
        ][:30]  # cap to manage context window

        toc_str = "\n".join(f"  {i}. {h}" for i, h in enumerate(PROCEDURE_TOC, start=1))

        _procedure_schema_text = schema_as_prompt_text("procedure")

        system_msg = f"""\
You are the Senior Procedure Author for {profile.org_name} ({profile.sector}, {profile.jurisdiction}).
You are a SCHEMA-DRIVEN COMPILER. You do not behave as a creative writing model.
You build documents using the authoritative schema below as your only structural authority.
These procedures are written at the level expected from Big4 cybersecurity consultants
preparing documentation for regulatory compliance audits.

{_procedure_schema_text}

COMPILER WORKFLOW (mandatory):
1. Load schema → identify document_order and section_blueprints
2. Construct internal AST: Cover → TOC → DocInfo → Definitions → Objective → Scope →
   Roles → Overview → Triggers/Prerequisites → DetailedSteps(7.1..7.N phases) →
   DecisionPoints → OutputsRecords → TimeControls → RelatedDocs → EffectiveDate →
   ProcedureReview → Approval → VersionControl
3. Section 7 (detailed_procedure_steps) must represent 40–60% of total document content
4. Each phase: title + objective + entry_condition + responsible_role + steps + evidence + handoff
5. Each step: actor + action + system_or_form + expected_output + evidence + timing + next_step
6. Swimlane diagram (flowchart LR) + Flowchart diagram (flowchart TD) — BOTH MANDATORY
7. Output compliant JSON

FRAMEWORK HIERARCHY (MANDATORY):
NCA controls (NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC, NCA_OSMACC, NCA_NCS) are
PRIMARY and AUTHORITATIVE. NIST SP 800-53 (NIST_80053) is SUPPLEMENTARY only.
Every step citing a control MUST use real chunk_ids from the provided control_bundles.
Do NOT fabricate chunk_ids or control_ids.

ABSOLUTE RULES:
1. roles_responsibilities: MINIMUM 3 roles, each with at least 2 responsibilities.
   Include: (a) Security/Cybersecurity Team, (b) IT Operations / System Administrators,
   (c) System/Asset Owners. Add additional roles as appropriate.
2. prerequisites: MINIMUM 3 items — access permissions, system states, tool availability.
3. tools_required: MINIMUM 1 tool. Include specific tool names and versions where known.
4. phases: MINIMUM 4 phases. Required structure:
   Phase 1 — Preparation (setup, access verification, environment checks, tool staging)
   Phase 2 — Implementation (core technical steps with commands/configs)
   Phase 3 — Verification & Testing (testing, validation, evidence capture)
   Phase 4 — Documentation & Closure (reporting, sign-off, handover)
   Add Phase 5 (Ongoing Maintenance / Monitoring) where operationally relevant.
5. steps: MINIMUM 15 total steps across all phases. Each step must have:
   - actor: the specific role performing this step
   - action: 60+ words — detailed imperative instruction with exact command syntax, parameters, and context
   - expected_output: 40+ words — observable, measurable, verifiable result with specific values or states
   - code_block: actual CLI command, config snippet, or script; use "" only if truly no command applies
   - citations: chunk_ids from the provided control_bundles that ground this step;
     use [] only for purely administrative steps with no direct control linkage
6. verification_checks: MINIMUM 6 checks. Each must have:
   - description: 50+ words specifying exactly what is being verified and why
   - evidence_artifact: the specific file path, log entry, screenshot, or report that proves compliance
7. evidence_collection: MINIMUM 4 artifacts — list specific log paths, report names,
   configuration export filenames, screenshot descriptions, or ticket references.
8. exception_handling_en: Substantive paragraph of 300+ words covering escalation paths,
   risk acceptance process, rollback procedures, and communication requirements.
9. swimlane_diagram: Valid Mermaid (flowchart LR). Show ALL defined roles as subgraphs.
   Each step node placed inside the responsible actor's subgraph. Steps connected by arrows.
   CRITICAL MERMAID SYNTAX: node IDs alphanumeric+underscore only, labels in double quotes.
   Example:
     flowchart LR
       subgraph SecTeam["Security Team"]
         S1["1. Review requirements"]
         S4["4. Validate results"]
       end
       subgraph ITOps["IT Operations"]
         S2["2. Configure system"]
         S3["3. Run verification"]
       end
       S1 --> S2 --> S3 --> S4
10. flowchart_diagram: Valid Mermaid (flowchart TD). Show full operational logic with
    decision diamonds. Include Start, decision branches, remediation paths, and End.
    CRITICAL MERMAID SYNTAX: decision nodes use curly braces — D1{{Decision?}},
    terminals use round brackets — T1([Start]).
    Example:
      flowchart TD
        Start([Start]) --> CheckAccess{{Access verified?}}
        CheckAccess -->|Yes| Configure["Configure control"]
        CheckAccess -->|No| RequestAccess["Request access"]
        RequestAccess --> CheckAccess
        Configure --> Test{{Test passed?}}
        Test -->|Yes| CollectEvidence["Collect evidence artifacts"]
        Test -->|No| Remediate["Remediate and retest"]
        Remediate --> Test
        CollectEvidence --> End([Procedure Complete])
11. parent_policy_id: reference the parent governance policy (e.g. "POL-01")
12. parent_standard_id: reference the parent technical standard (e.g. "STD-{doc_id[4:]}")

TARGET DOCUMENT LENGTH: 17–20 Word pages when rendered.
To meet this target, write with the following MINIMUM content depth per field:
- objective_en: 250+ words — purpose, regulatory basis (NCA ECC), operational context, CIA triad relevance.
- scope_en: 200+ words — all in-scope systems, asset categories, personnel roles, environments, exclusions.
- roles_responsibilities: Each role 5–7 specific, distinct responsibilities written as full sentences.
- phases: 4–5 phases; each phase_intro 150+ words describing the phase's purpose, inputs, outputs, risks.
  Each phase should have 3–5 steps.
- phase_intro: MANDATORY for every phase — 150+ words contextualising the phase, its inputs, expected outputs, key risks, and how it connects to the previous and next phase.
- Each step action: 100+ words — detailed imperative with exact command syntax, parameter values, expected system state, and security rationale.
- Each step expected_output: 70+ words — measurable, observable result with specific values, log entries, or configuration states to confirm success.
- verification_checks: 8+ checks; each description 100+ words specifying what is verified, why it matters, and how to interpret the evidence artifact.
- evidence_collection: 5+ artifacts — each a full sentence describing the artifact type, file path or location, retention period, and its compliance significance.
- exception_handling_en: 500+ words — escalation matrix, risk acceptance workflow, rollback steps, communication plan, and lessons-learned process.

DOCUMENT ORDER (from schema — mandatory section sequence):
1. definitions_and_abbreviations
2. procedure_objective
3. scope_and_applicability
4. roles_and_responsibilities (table: Role | Responsibility)
5. procedure_overview
6. triggers_prerequisites_inputs_and_tools
7. detailed_procedure_steps  ← DOMINANT section (40-60% of content)
8. decision_points_exceptions_and_escalations
9. outputs_records_evidence_and_forms
10. time_controls_service_levels_and_control_checkpoints
11. related_documents
12. effective_date
13. procedure_review
14. review_and_approval
15. version_control
Appendices: swimlane diagram, RACI matrix, decision trees

Generate a procedure tailored to the topic: {spec.topic}
Sector: {profile.sector} | Jurisdiction: {profile.jurisdiction}
Include technically accurate CLI commands and configuration examples where applicable.
The augmented_guidance field in the user payload provides enriched implementation
steps derived from gap analysis — use this to ensure operational depth.
"""

        user_payload: dict = {
            "doc_id":            doc_id,
            "org_name":          profile.org_name,
            "sector":            profile.sector,
            "jurisdiction":      profile.jurisdiction,
            "topic":             spec.topic,
            "version":           spec.version,
            "control_bundles":   bundle_list,
            "augmented_guidance": aug_list,
        }
        if qa_findings:
            user_payload["qa_findings_to_fix"] = qa_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL_POLICY,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": (
                    "Compile the complete Procedure document following the authoritative schema. "
                    "Section 7 (detailed steps) must be 40-60% of total content. "
                    "Ground steps in chunk_ids from control_bundles. "
                    "Use augmented_guidance for implementation depth. "
                    "Both Mermaid diagrams (flowchart LR swimlane + flowchart TD) are MANDATORY. "
                    "Output valid JSON."
                )},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _PROCEDURE_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)

        roles = [
            ProcedureRoleItem(
                role_title       = r["role_title"],
                responsibilities = r["responsibilities"],
            )
            for r in raw["roles_responsibilities"]
        ]

        phases = []
        for ph in raw["phases"]:
            steps = [
                ProcedureStep(
                    step_no         = s["step_no"],
                    phase           = s["phase"],
                    actor           = s["actor"],
                    action          = s["action"],
                    expected_output = s["expected_output"],
                    code_block      = s.get("code_block", ""),
                    citations       = s.get("citations", []),
                )
                for s in ph["steps"]
            ]
            phases.append(ProcedurePhase(
                phase_name=ph["phase_name"],
                phase_intro=ph.get("phase_intro", ""),
                steps=steps,
            ))

        verifications = [
            ProcedureVerificationCheck(
                check_id          = v["check_id"],
                description       = v["description"],
                method            = v["method"],
                expected_result   = v["expected_result"],
                evidence_artifact = v["evidence_artifact"],
            )
            for v in raw["verification_checks"]
        ]

        draft = ProcedureDraftOutput(
            doc_id               = raw.get("doc_id", doc_id),
            title_en             = raw["title_en"],
            version              = raw.get("version", spec.version),
            effective_date       = raw.get("effective_date", "TBD"),
            owner                = raw.get("owner", "Chief Information Security Officer"),
            classification       = raw.get("classification", "Internal"),
            parent_policy_id     = raw.get("parent_policy_id", "POL-01"),
            parent_standard_id   = raw.get("parent_standard_id", "STD-01"),
            objective_en         = raw["objective_en"],
            scope_en             = raw["scope_en"],
            roles_responsibilities = roles,
            prerequisites        = raw["prerequisites"],
            tools_required       = raw["tools_required"],
            phases               = phases,
            verification_checks  = verifications,
            evidence_collection  = raw["evidence_collection"],
            exception_handling_en = raw["exception_handling_en"],
            swimlane_diagram     = raw["swimlane_diagram"],
            flowchart_diagram    = raw["flowchart_diagram"],
        )

        total_steps = sum(len(ph.steps) for ph in phases)
        print(f"[Drafter] Procedure draft complete: {len(phases)} phases, "
              f"{total_steps} steps, {len(verifications)} verification checks.")
        return draft


# ── Golden Policy JSON Schema (strict, enforced by OpenAI Structured Outputs) ─

_TRACE_ENTRY = {
    "type": "object",
    "properties": {
        "framework":  {"type": "string"},
        "control_id": {"type": "string"},
        "source_ref": {"type": "string"},
    },
    "required": ["framework", "control_id", "source_ref"],
    "additionalProperties": False,
}

_POLICY_SCHEMA = {
    "name": "PolicyDraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id":         {"type": "string"},
            "title_en":       {"type": "string"},
            "version":        {"type": "string"},
            "effective_date": {"type": "string"},
            "owner":          {"type": "string"},
            "classification": {"type": "string"},
            "objectives_en":          {"type": "string"},
            "scope_applicability_en": {"type": "string"},
            "policy_elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_no":   {"type": "string"},
                        "statement_en": {"type": "string"},
                        "trace": {"type": "array", "items": _TRACE_ENTRY},
                    },
                    "required": ["element_no", "statement_en", "trace"],
                    "additionalProperties": False,
                }
            },
            "policy_subprograms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sub_no":       {"type": "string"},
                        "name_en":      {"type": "string"},
                        "objective_en": {"type": "string"},
                        "references":   {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["sub_no", "name_en", "objective_en", "references"],
                    "additionalProperties": False,
                }
            },
            "roles_responsibilities": {
                "type": "object",
                "properties": {
                    "authority_owner_delegates": {"type": "array", "items": {"type": "string"}},
                    "legal":                     {"type": "array", "items": {"type": "string"}},
                    "internal_audit":            {"type": "array", "items": {"type": "string"}},
                    "HR":                        {"type": "array", "items": {"type": "string"}},
                    "cybersecurity":             {"type": "array", "items": {"type": "string"}},
                    "other_departments":         {"type": "array", "items": {"type": "string"}},
                    "all_staff":                 {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "authority_owner_delegates", "legal", "internal_audit",
                    "HR", "cybersecurity", "other_departments", "all_staff"
                ],
                "additionalProperties": False,
            },
            "compliance_clauses": {"type": "array", "items": {"type": "string"}},
            "exceptions_en":      {"type": "string"},
            "closing_note_en":    {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "objectives_en", "scope_applicability_en", "policy_elements",
            "policy_subprograms", "roles_responsibilities",
            "compliance_clauses", "exceptions_en", "closing_note_en",
        ],
        "additionalProperties": False,
    }
}


# ── Golden Standard JSON Schema (strict, enforced by OpenAI Structured Outputs) ─

_STANDARD_SCHEMA = {
    "name": "StandardDraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id":         {"type": "string"},
            "title_en":       {"type": "string"},
            "version":        {"type": "string"},
            "effective_date": {"type": "string"},
            "owner":          {"type": "string"},
            "classification": {"type": "string"},
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term_en":        {"type": "string"},
                        "description_en": {"type": "string"},
                    },
                    "required": ["term_en", "description_en"],
                    "additionalProperties": False,
                }
            },
            "objectives_en": {"type": "string"},
            "scope_en":      {"type": "string"},
            "domains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain_number":      {"type": "integer"},
                        "title_en":           {"type": "string"},
                        "objective_en":       {"type": "string"},
                        "potential_risks_en": {"type": "string"},
                        "requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "req_id":       {"type": "string"},
                                    "statement_en": {"type": "string"},
                                    "placeholders": {"type": "array", "items": {"type": "string"}},
                                    "trace": {"type": "array", "items": _TRACE_ENTRY},
                                },
                                "required": ["req_id", "statement_en", "placeholders", "trace"],
                                "additionalProperties": False,
                            }
                        },
                    },
                    "required": ["domain_number", "title_en", "objective_en", "potential_risks_en", "requirements"],
                    "additionalProperties": False,
                }
            },
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_no": {"type": "string"},
                        "text_en": {"type": "string"},
                    },
                    "required": ["item_no", "text_en"],
                    "additionalProperties": False,
                }
            },
            "review_update_en": {"type": "string"},
            "compliance_en":    {"type": "array", "items": {"type": "string"}},
            "closing_note_en":  {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "definitions", "objectives_en", "scope_en", "domains",
            "roles_responsibilities", "review_update_en", "compliance_en", "closing_note_en",
        ],
        "additionalProperties": False,
    }
}


# ── Golden Procedure JSON Schema (strict, enforced by OpenAI Structured Outputs) ─

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "step_no":         {"type": "string"},
        "phase":           {"type": "string"},
        "actor":           {"type": "string"},
        "action":          {"type": "string"},
        "expected_output": {"type": "string"},
        "code_block":      {"type": "string"},
        "citations":       {"type": "array", "items": {"type": "string"}},
    },
    "required": ["step_no", "phase", "actor", "action", "expected_output",
                 "code_block", "citations"],
    "additionalProperties": False,
}

_PROCEDURE_SCHEMA = {
    "name": "ProcedureDraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id":             {"type": "string"},
            "title_en":           {"type": "string"},
            "version":            {"type": "string"},
            "effective_date":     {"type": "string"},
            "owner":              {"type": "string"},
            "classification":     {"type": "string"},
            "parent_policy_id":   {"type": "string"},
            "parent_standard_id": {"type": "string"},
            "objective_en":       {"type": "string"},
            "scope_en":           {"type": "string"},
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role_title":       {"type": "string"},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role_title", "responsibilities"],
                    "additionalProperties": False,
                },
            },
            "prerequisites":  {"type": "array", "items": {"type": "string"}},
            "tools_required": {"type": "array", "items": {"type": "string"}},
            "phases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phase_name":  {"type": "string"},
                        "phase_intro": {"type": "string"},
                        "steps":       {"type": "array", "items": _STEP_SCHEMA},
                    },
                    "required": ["phase_name", "phase_intro", "steps"],
                    "additionalProperties": False,
                },
            },
            "verification_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "check_id":          {"type": "string"},
                        "description":       {"type": "string"},
                        "method":            {"type": "string"},
                        "expected_result":   {"type": "string"},
                        "evidence_artifact": {"type": "string"},
                    },
                    "required": ["check_id", "description", "method",
                                 "expected_result", "evidence_artifact"],
                    "additionalProperties": False,
                },
            },
            "evidence_collection":   {"type": "array", "items": {"type": "string"}},
            "exception_handling_en": {"type": "string"},
            "swimlane_diagram":      {"type": "string"},
            "flowchart_diagram":     {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "parent_policy_id", "parent_standard_id", "objective_en", "scope_en",
            "roles_responsibilities", "prerequisites", "tools_required",
            "phases", "verification_checks", "evidence_collection",
            "exception_handling_en", "swimlane_diagram", "flowchart_diagram",
        ],
        "additionalProperties": False,
    },
}
