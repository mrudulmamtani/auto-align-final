"""
Deterministic validation gates — no LLM involved.
All checks are pure Python and produce pass/fail results before the reviewer LLM runs.

Hard gates (FAIL):
  1. Citation completeness: every normative requirement must have >=1 chunk_id
     that exists in the RetrievalPacket.
  2. Hallucination guard: no citations referencing chunk_ids not in the packet.
  3. Control ID integrity: mapped_control_ids must be non-empty for normative reqs
     that have citations.

Soft gates (WARN):
  4. Control coverage: fraction of retrieved chunk_ids actually cited in the draft.
"""
import re
from .models import DraftOutput, RetrievalPacket, ValidationReport, ValidationFinding

_NORMATIVE_PATTERN = re.compile(r"\b(SHALL|MUST|REQUIRED|WILL)\b", re.IGNORECASE)


def _is_normative(text: str) -> bool:
    return bool(_NORMATIVE_PATTERN.search(text))


def validate(draft: DraftOutput, packet: RetrievalPacket) -> ValidationReport:
    valid_chunk_ids = packet.chunk_id_set
    findings: list[ValidationFinding] = []
    fid = 1

    all_cited: set[str] = set()
    normative_total = 0
    normative_with_citation = 0

    for s in draft.sections:
        for r in s.requirements:
            text_normative = _is_normative(r.text)
            effective_normative = r.is_normative or text_normative

            if effective_normative:
                normative_total += 1

                # Gate 1: citation completeness
                if not r.citations:
                    findings.append(ValidationFinding(
                        finding_id      = f"F{fid:03d}",
                        severity        = "FAIL",
                        check           = "CITATION_COMPLETENESS",
                        message         = f"Normative requirement '{r.req_id}' has no citations.",
                        affected_req_id = r.req_id,
                    ))
                    fid += 1
                else:
                    normative_with_citation += 1

                # Gate 2: hallucination guard — cited IDs must exist in packet
                for cid in r.citations:
                    if cid not in valid_chunk_ids:
                        findings.append(ValidationFinding(
                            finding_id      = f"F{fid:03d}",
                            severity        = "FAIL",
                            check           = "HALLUCINATION",
                            message         = f"Req '{r.req_id}' cites chunk_id '{cid}' which is not in the RetrievalPacket.",
                            affected_req_id = r.req_id,
                        ))
                        fid += 1

                # Gate 3: mapped_control_ids must not be empty when citations exist
                if r.citations and not r.mapped_control_ids:
                    findings.append(ValidationFinding(
                        finding_id      = f"F{fid:03d}",
                        severity        = "FAIL",
                        check           = "CONTROL_ID_INTEGRITY",
                        message         = f"Req '{r.req_id}' has citations but empty mapped_control_ids.",
                        affected_req_id = r.req_id,
                    ))
                    fid += 1

            all_cited.update(r.citations)

    # Gate 4: coverage warning
    if valid_chunk_ids:
        uncovered = sorted(valid_chunk_ids - all_cited)
        coverage = len(all_cited & valid_chunk_ids) / len(valid_chunk_ids)
        if coverage < 0.40:
            findings.append(ValidationFinding(
                finding_id = f"F{fid:03d}",
                severity   = "WARN",
                check      = "CONTROL_COVERAGE",
                message    = f"Only {coverage:.0%} of retrieved controls are cited in the draft.",
            ))
            fid += 1
    else:
        uncovered = []
        coverage = 1.0

    citation_pct = (normative_with_citation / normative_total) if normative_total else 1.0
    hard_fails = [f for f in findings if f.severity == "FAIL"]
    passed = len(hard_fails) == 0

    print(f"[Validation] citation_coverage={citation_pct:.0%} "
          f"control_coverage={coverage:.0%} "
          f"FAILs={len(hard_fails)} WARNs={sum(1 for f in findings if f.severity=='WARN')}")

    return ValidationReport(
        passed                = passed,
        citation_coverage_pct = round(citation_pct, 4),
        control_coverage_pct  = round(coverage, 4),
        uncovered_chunk_ids   = uncovered,
        findings              = findings,
    )
