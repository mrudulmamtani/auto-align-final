Architecture Overview

  DocumentSpec + EntityProfile
           │
           ▼
  ┌─────────────────────────────────────────────────────┐
  │  ResearchCoordinator  [PARALLEL — ThreadPoolExecutor]│
  │                                                     │
  │  NCA retrieval × 3-5 queries ──┐                   │
  │  NIST retrieval × 3-5 queries ─┤→ rerank → enrich  │
  │  Domain extra queries ─────────┘                   │
  │                                                     │
  │  Fires all section groups concurrently:            │
  │    front_matter | phase_0..N | evidence            │
  └─────────────┬───────────────────────────────────────┘
                │ WorkflowResearch (per-section bundles)
                ▼
  ┌─────────────────────────────────────────────────────┐
  │            PROCEDURE SUPERVISOR                     │
  │                                                     │
  │  FrontMatterAgent    [LLM]  §1–6                   │
  │  PhaseAgent × N      [LLM]  §7.1, 7.2 … 7.N       │◄── one focused call per phase
  │  EvidenceAgent       [LLM]  §8–10                  │
  │  MetadataBuilder  [DETERM]  §11–15                 │◄── zero LLM
  │  CitationValidator [DETERM]  strip bad chunk_ids   │◄── zero LLM
  │  StructuralChecker [DETERM]  pre-QA issue scan     │◄── zero LLM
  │  SectionRepairAgent  [LLM]  targeted section fix   │◄── only failing section
  │  RelatedDocsBuilder [DETERM] build related_docs    │◄── zero LLM
  └─────────────────────────────────────────────────────┘
                │ ProcedureDraftOutput (identical interface)
                ▼
  ┌─────────────────────────────────────────────────────┐
  │  QAValidator  [DETERM]  7-gate schema validation   │
  │  DiagramGenerator [DETERM] swimlane + flowchart    │
  │  DOCX Renderer    [DETERM] Word document           │
  └─────────────────────────────────────────────────────┘