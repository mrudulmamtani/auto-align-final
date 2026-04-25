const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE
  || process.env.NEXT_PUBLIC_API_BASE_URL
  || "http://localhost:8100"
).replace(/\/+$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

async function requestBlob(path: string, options?: RequestInit): Promise<{ blob: Blob; filename: string | null }> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  const disposition = res.headers.get("content-disposition");
  const filenameMatch = disposition?.match(/filename="(.+?)"/i);
  return { blob: await res.blob(), filename: filenameMatch?.[1] ?? null };
}

// ── ARR Types ─────────────────────────────────────────────────

export interface ArrRow {
  control_urn: string;
  control_name: string;
  standard: string;
  requirement: string;
  status: string;
  violation_count: number;
  risk_rating: string;
  last_event: string | null;
  objective?: string;
  associated_risks?: string;
  resolution_controls?: string;
}

// ── UCCF Types ────────────────────────────────────────────────

export interface UccfStandard {
  urn: string;
  name: string;
  short_name: string;
  version: string;
  domain_count: number;
  total_controls: number;
  domain_names: string[];
}

export interface UccfCommonControl {
  urn: string;
  control_id: string;
  name: string;
  text: string;
  domain_cluster: string;
  keywords: string[];
  standard_name: string;
  standard_urn: string;
  domain_name: string;
  standards_count: number;
  matches: Array<{
    urn: string;
    control_id: string;
    name: string;
    standard_urn: string;
    similarity: number;
    shared_kw: string[];
  }>;
}

export interface UccfMatrixPair {
  standard_a: string;
  standard_b: string;
  urn_a: string;
  urn_b: string;
  shared_count: number;
  avg_similarity: number;
  overlap_pct: number;
  total_a: number;
  total_b: number;
}

export interface UccfIngestResult {
  status: string;
  filename: string;
  standard_name: string;
  standard_urn: string;
  controls_parsed: number;
  domains_created: number;
  controls_created: number;
  semantic_links_created: number;
}

// ── ARR API ───────────────────────────────────────────────────

export function fetchArrWorksheet(): Promise<{ rows: ArrRow[] }> {
  return request("/api/arr");
}

export function uploadArrObjectives(file: File): Promise<{
  objectives: unknown[];
  risk_register: unknown[];
  total_objectives: number;
  total_risks: number;
}> {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${API_BASE}/api/arr/upload`, {
    method: "POST",
    body: form,
  }).then(async (res) => {
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${body}`);
    }
    return res.json();
  });
}

export function downloadRiskRegister(): Promise<{ blob: Blob; filename: string | null }> {
  return requestBlob("/api/arr/export/csv");
}

export function downloadRiskRegisterExcel(): Promise<{ blob: Blob; filename: string | null }> {
  return requestBlob("/api/arr/export/excel");
}

// ── UCCF API ──────────────────────────────────────────────────

export function uccfListStandards(): Promise<{ standards: UccfStandard[]; total: number }> {
  return request("/api/uccf/standards");
}

export function uccfCommonControls(
  minStandards = 2,
  domainCluster?: string,
): Promise<{ common_controls: UccfCommonControl[]; total: number }> {
  const params = new URLSearchParams({ min_standards: String(minStandards) });
  if (domainCluster) params.set("domain_cluster", domainCluster);
  return request(`/api/uccf/common-controls?${params}`);
}

export function uccfMatrix(): Promise<{
  matrix: UccfMatrixPair[];
  standards: { urn: string; name: string }[];
  total_pairs: number;
}> {
  return request("/api/uccf/matrix");
}

export async function uccfIngest(
  file: File,
  name?: string,
  description?: string,
): Promise<UccfIngestResult> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  if (description) form.append("description", description);
  const res = await fetch(`${API_BASE}/api/uccf/ingest`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`UCCF ingest ${res.status}: ${body}`);
  }
  return res.json();
}

export function uccfRemap(): Promise<{
  status: string;
  controls_processed: number;
  semantic_links_created: number;
}> {
  return request("/api/uccf/remap", { method: "POST" });
}
