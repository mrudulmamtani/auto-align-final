/**
 * AutoAlign Policy Converter — API Client
 *
 * Connects to the AutoAlign FastAPI server (default: http://localhost:8080).
 * Configure via NEXT_PUBLIC_AUTOALIGN_BASE env var.
 */

const AUTOALIGN_BASE = (
  process.env.NEXT_PUBLIC_AUTOALIGN_BASE ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:8100"
).replace(/\/+$/, "");

async function req_fn<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${AUTOALIGN_BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`AutoAlign ${res.status}: ${body}`);
  }
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface AutoAlignDoc {
  doc_id: string;
  document_type: "policy" | "standard" | "procedure";
  title: string;
  version: string;
  qa_passed: boolean;
  shall_count: number;
  traced_count: number;
  main_docx: string;
  has_forensic_map: boolean;
  forensic_controls: number;
  has_conversion: string | null;
}

export interface ControlLocation {
  control_id: string;
  framework: string;
  nca_id: string | null;
  element_ref: string;
  section: string;
  section_number: string;
  domain_title: string | null;
  page_number: number | null;
  paragraph_index: number | null;
  char_offset_start: number | null;
  char_offset_end: number | null;
  converted_page_number: number | null;
  converted_paragraph_index: number | null;
  extraction_method: "win32com" | "heuristic" | "officejs" | "manual";
  extraction_confidence: number;
}

export interface SectionLocation {
  section_number: string;
  title: string;
  page_number: number | null;
  paragraph_index: number | null;
  heading_level: number;
  converted_page_number: number | null;
}

export interface ForensicMap {
  doc_id: string;
  document_type: string;
  title: string;
  version: string;
  org_name: string;
  qa_passed: boolean;
  shall_count: number;
  traced_count: number;
  forensic_extracted_at: string | null;
  forensic_method: string;
  total_paragraphs: number | null;
  estimated_pages: number | null;
  section_locations: SectionLocation[];
  control_locations: ControlLocation[];
  converted_docx: string | null;
  converted_at: string | null;
}

// ── API calls ──────────────────────────────────────────────────────────────

export function fetchAutoAlignDocuments(): Promise<{ documents: AutoAlignDoc[]; total: number }> {
  return req_fn("/api/documents");
}

export function fetchForensicMap(docId: string): Promise<ForensicMap> {
  return req_fn(`/api/forensics/${docId}`);
}

export function triggerExtraction(docId: string): Promise<{
  doc_id: string;
  sections: number;
  controls: number;
  estimated_pages: number;
}> {
  return req_fn("/api/forensics/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId }),
  });
}

export function getSourceDocxUrl(docId: string, kind: "main" | "traceability" = "main"): string {
  return `${AUTOALIGN_BASE}/api/download/source/${docId}?kind=${kind}`;
}

export function getConvertedDocxUrl(filename: string): string {
  return `${AUTOALIGN_BASE}/api/download/converted/${filename}`;
}

export function getForensicJsonUrl(docId: string): string {
  return `${AUTOALIGN_BASE}/api/download/forensic/${docId}`;
}

export function getDocumentHtmlUrl(docId: string): string {
  return `${AUTOALIGN_BASE}/api/documents/${docId}/html`;
}

// ── Template types ──────────────────────────────────────────────────────────

export interface OrgTemplate {
  org_id: string;
  org_name: string;
  template_id: string;
  primary_color: string;
  has_logo: boolean;
  created_at: string;
}

export interface ConvertResult {
  doc_id: string;
  org_id: string;
  converted_docx: string;
  download_url: string;
  control_locations: number;
  forensic_map_updated: boolean;
}

// ── Template API ────────────────────────────────────────────────────────────

export function fetchTemplates(): Promise<{ templates: OrgTemplate[] }> {
  return req_fn("/api/templates");
}

export function deleteTemplate(orgId: string): Promise<{ deleted: string }> {
  return req_fn(`/api/templates/${orgId}`, { method: "DELETE" });
}

export function uploadTemplate(formData: FormData): Promise<{ org_id: string; org_name: string; template_id: string }> {
  return req_fn("/api/templates/upload", { method: "POST", body: formData });
}

export function convertDocument(docId: string, orgId: string): Promise<ConvertResult> {
  return req_fn("/api/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, org_id: orgId }),
  });
}

export function getLogoUrl(orgId: string): string {
  return `${AUTOALIGN_BASE}/api/templates/${orgId}/logo`;
}

// ── Generate API ─────────────────────────────────────────────────────────────

export interface EntityProfileIn {
  org_name: string;
  sector?: string;
  hosting_model?: string;
  soc_model?: string;
  data_classification?: string[];
  ot_presence?: boolean;
  critical_systems?: string[];
  jurisdiction?: string;
}

export interface GenerateRequest {
  doc_type: "policy" | "standard" | "procedure";
  topic: string;
  doc_id?: string;
  scope?: string;
  target_audience?: string;
  version?: string;
  profile?: EntityProfileIn;
  customization?: string;
}

// ── Document Comments API ─────────────────────────────────────────────────────

export interface DocComment {
  id: string;
  selected_text: string;
  context_before: string;
  context_after: string;
  comment: string;
  author: string;
  color: string;
  created_at: string;
}

export function fetchComments(docId: string): Promise<{ doc_id: string; comments: DocComment[] }> {
  return req_fn(`/api/documents/${docId}/comments`);
}

export function addComment(
  docId: string,
  body: { selected_text: string; context_before: string; context_after: string; comment: string; author?: string; color?: string }
): Promise<DocComment> {
  return req_fn(`/api/documents/${docId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteComment(docId: string, commentId: string): Promise<{ deleted: string }> {
  return req_fn(`/api/documents/${docId}/comments/${commentId}`, { method: "DELETE" });
}

export interface GenerateJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  doc_type: string;
  topic: string;
  doc_id?: string;
  org_name: string;
  queued_at: string;
  started_at?: string;
  completed_at?: string;
  result?: Record<string, unknown>;
  error?: string;
}

export function generateDocument(req: GenerateRequest): Promise<{ job_id: string; status: string; message: string }> {
  return req_fn("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export function getGenerateJobStatus(jobId: string): Promise<GenerateJob> {
  return req_fn(`/api/generate/status/${jobId}`);
}

export function listGenerateJobs(): Promise<{ jobs: GenerateJob[]; total: number }> {
  return req_fn("/api/generate/jobs");
}

export function getTopics(): Promise<{
  policies: { doc_id: string; topic: string }[];
  standards: { doc_id: string; topic: string }[];
  procedures: { doc_id: string; topic: string }[];
}> {
  return req_fn("/api/generate/topics");
}

// ── Document Library API ─────────────────────────────────────────────────────

export interface LibraryDocStatus {
  doc_id: string;
  status: "generated" | "generating" | "failed" | "not_generated";
  generated_at: string | null;
  docx_path: string | null;
  pdf_path: string | null;
  qa_passed: boolean | null;
  elapsed: number | null;
  stale: boolean;
  error?: string;
}

export interface LibraryDoc {
  id: string;
  type: "policy" | "standard" | "procedure";
  name_en: string;
  name_ar: string;
  wave: number;
  depends_on: string[];
  gen_status: LibraryDocStatus;
}

export interface LibraryWave {
  wave_key: string;
  wave_label: string;
  documents: LibraryDoc[];
}

export interface LibraryDocDetail extends LibraryDoc {
  gen_status: LibraryDocStatus;
  direct_dependencies: LibraryDoc[];
  all_dependencies: LibraryDoc[];
  direct_dependents: LibraryDoc[];
  all_dependents: LibraryDoc[];
  missing_deps: string[];
  can_generate: boolean;
}

export interface LibraryJob {
  job_id: string;
  doc_id: string;
  doc_name: string;
  doc_type: string;
  status: "queued" | "running" | "completed" | "failed" | "skipped";
  queued_at: string;
  started_at?: string;
  completed_at?: string;
  message?: string;
  error?: string;
  pdf_path?: string;
  result?: Record<string, unknown>;
}

export interface LibraryProfileIn {
  org_name?: string;
  sector?: string;
  hosting_model?: string;
  soc_model?: string;
  data_classification?: string[];
  ot_presence?: boolean;
  critical_systems?: string[];
  jurisdiction?: string;
}

export function fetchDocLibrary(): Promise<{
  waves: LibraryWave[];
  total: number;
  generated: number;
}> {
  return req_fn("/api/doc-library");
}

export function fetchDocDetail(docId: string): Promise<LibraryDocDetail> {
  return req_fn(`/api/doc-library/${docId}`);
}

export function generateLibraryDoc(
  docId: string,
  profile?: LibraryProfileIn,
  force = false
): Promise<{ job_id: string; doc_id: string; status: string; message: string }> {
  return req_fn(`/api/doc-library/${docId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: profile ?? {}, force }),
  });
}

export function generateDocChain(
  docIds: string[],
  profile?: LibraryProfileIn,
  includeDependencies = true
): Promise<{ jobs: { job_id: string; doc_id: string; doc_name: string }[]; total: number }> {
  return req_fn("/api/doc-library/chain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      doc_ids: docIds,
      profile: profile ?? {},
      include_dependencies: includeDependencies,
    }),
  });
}

export function fetchLibraryJob(jobId: string): Promise<LibraryJob> {
  return req_fn(`/api/doc-library/jobs/${jobId}`);
}

export function fetchLibraryJobs(): Promise<{ jobs: LibraryJob[]; total: number }> {
  return req_fn("/api/doc-library/jobs");
}

export function getDocPdfUrl(docId: string): string {
  return `${AUTOALIGN_BASE}/api/doc-library/${docId}/pdf`;
}

export function getDocDownloadUrl(docId: string): string {
  return `${AUTOALIGN_BASE}/api/doc-library/${docId}/download`;
}

/** Fetch all covered control IDs across all documents with forensic maps. */
export async function fetchCoveredControlIds(): Promise<Set<string>> {
  try {
    const { documents } = await fetchAutoAlignDocuments();
    const ids = new Set<string>();
    await Promise.all(
      documents
        .filter((d) => d.has_forensic_map)
        .map(async (d) => {
          try {
            const fmap = await fetchForensicMap(d.doc_id);
            for (const cl of fmap.control_locations) ids.add(cl.control_id);
          } catch {
            // skip unavailable maps
          }
        })
    );
    return ids;
  } catch {
    return new Set();
  }
}
