"use client";

/**
 * OrchestratePanel — Ministry Document Wave Orchestrator UI
 *
 * Shows all 110 documents organised by wave with live status tracking.
 * Allows starting full-suite or per-document generation with dependency
 * context injection via the backend orchestrator.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { clsx } from "clsx";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8100";

// ── API helpers ────────────────────────────────────────────────────────────────

async function apiPost(path: string, body: unknown) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiGet(path: string) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────────────────────

interface DocEntry {
  id: string;
  type: "policy" | "standard" | "procedure";
  name_en: string;
  name_ar: string;
  wave: number;
  depends_on: string[];
}

interface OrchestratorStatus {
  status: "idle" | "running" | "completed" | "failed" | "paused";
  current_doc: string | null;
  current_wave: number;
  total_docs: number;
  completed_count: number;
  failed_count: number;
  completed_docs: string[];
  failed_docs: string[];
  skipped_docs: string[];
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  recent_log: Array<{ ts: string; level: string; doc_id: string; msg: string }>;
}

interface GeneratedDoc {
  doc_id: string;
  title_ar?: string;
  title_en?: string;
  doc_type?: string;
  version?: string;
  docx_path?: string;
}

const WAVE_LABELS: Record<string, string> = {
  wave_1_policies_foundation:    "Wave 1 — Foundation Policies",
  wave_2_core_standards:         "Wave 2 — Core Standards",
  wave_3_high_impact_procedures: "Wave 3 — High-Impact Procedures",
  wave_4_remaining_policies:     "Wave 4 — Remaining Policies",
  wave_5_remaining_standards:    "Wave 5 — Remaining Standards",
  wave_6_remaining_procedures:   "Wave 6 — Remaining Procedures",
};

const DOC_TYPE_COLOR: Record<string, string> = {
  policy:    "text-blue-400 bg-blue-500/10 border-blue-500/30",
  standard:  "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  procedure: "text-amber-400 bg-amber-500/10 border-amber-500/30",
};

const DOC_TYPE_LABEL: Record<string, string> = {
  policy:    "POL",
  standard:  "STD",
  procedure: "PRC",
};

function StatusBadge({ status }: { status: OrchestratorStatus["status"] }) {
  const cfg = {
    idle:      { cls: "text-pwc-text-dim bg-pwc-surface border-pwc-border", dot: "bg-gray-500" },
    running:   { cls: "text-blue-300 bg-blue-900/30 border-blue-500/40", dot: "bg-blue-400 animate-pulse" },
    completed: { cls: "text-emerald-300 bg-emerald-900/20 border-emerald-500/30", dot: "bg-emerald-400" },
    failed:    { cls: "text-red-400 bg-red-900/20 border-red-500/30", dot: "bg-red-400" },
    paused:    { cls: "text-amber-400 bg-amber-900/20 border-amber-500/30", dot: "bg-amber-400" },
  }[status] ?? { cls: "text-pwc-text-dim", dot: "bg-gray-500" };

  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[9px] font-bold", cfg.cls)}>
      <span className={clsx("w-1.5 h-1.5 rounded-full", cfg.dot)} />
      {status.toUpperCase()}
    </span>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function OrchestratePanel() {
  const [catalog, setCatalog] = useState<{ generation_order: Record<string, string[]>; documents: DocEntry[] } | null>(null);
  const [status, setStatus] = useState<OrchestratorStatus | null>(null);
  const [generatedDocs, setGeneratedDocs] = useState<GeneratedDoc[]>([]);
  const [orgName, setOrgName] = useState("الوزارة");
  const [skipExisting, setSkipExisting] = useState(true);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [singleGenDoc, setSingleGenDoc] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<"catalog" | "status" | "generated">("catalog");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load catalog ────────────────────────────────────────────────────────────
  useEffect(() => {
    apiGet("/api/orchestrate/catalog")
      .then(setCatalog)
      .catch(() => setError("Failed to load catalog"));
    apiGet("/api/orchestrate/status")
      .then(setStatus)
      .catch(() => {});
    loadGenerated();
  }, []);

  const loadGenerated = useCallback(() => {
    apiGet("/api/orchestrate/generated")
      .then((d) => setGeneratedDocs(d.documents ?? []))
      .catch(() => {});
  }, []);

  // ── Live polling when running ───────────────────────────────────────────────
  useEffect(() => {
    if (status?.status === "running") {
      pollRef.current = setInterval(() => {
        apiGet("/api/orchestrate/status").then(setStatus).catch(() => {});
      }, 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
      if (status?.status === "completed") loadGenerated();
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status?.status, loadGenerated]);

  // ── Actions ─────────────────────────────────────────────────────────────────
  const startOrchestration = useCallback(async (docIds?: string[]) => {
    setError(null);
    try {
      await apiPost("/api/orchestrate/start", {
        doc_ids: docIds && docIds.length > 0 ? docIds : null,
        org_name: orgName,
        skip_existing: skipExisting,
      });
      const s = await apiGet("/api/orchestrate/status");
      setStatus(s);
      setActiveSection("status");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start");
    }
  }, [orgName, skipExisting]);

  const stopOrchestration = useCallback(async () => {
    try {
      await apiPost("/api/orchestrate/stop", {});
      const s = await apiGet("/api/orchestrate/status");
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop");
    }
  }, []);

  const generateSingle = useCallback(async (docId: string) => {
    setSingleGenDoc(docId);
    setError(null);
    try {
      await apiPost(`/api/orchestrate/generate/${docId}`, { org_name: orgName });
      await loadGenerated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setSingleGenDoc(null);
    }
  }, [orgName, loadGenerated]);

  const refreshStatus = useCallback(async () => {
    const s = await apiGet("/api/orchestrate/status").catch(() => null);
    if (s) setStatus(s);
  }, []);

  // ── Catalog helpers ─────────────────────────────────────────────────────────
  const docIndex = catalog
    ? Object.fromEntries(catalog.documents.map((d) => [d.id, d]))
    : {};

  const generatedSet = new Set(generatedDocs.map((d) => d.doc_id));

  const toggleDoc = (id: string) => {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const waves = catalog
    ? Object.entries(catalog.generation_order)
    : [];

  const totalDocs = catalog?.documents.length ?? 0;
  const generatedCount = generatedDocs.length;

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full min-h-0 overflow-hidden">

      {/* ── Left sidebar: controls + stats ───────────────────────────────── */}
      <aside className="w-72 shrink-0 flex flex-col border-r border-pwc-border overflow-y-auto">
        <div className="p-4 border-b border-pwc-border">
          <div className="text-[12px] font-bold text-pwc-text mb-0.5">Ministry Document Orchestrator</div>
          <div className="text-[9px] text-pwc-text-dim">Wave-based generation of 110 Arabic cybersecurity documents</div>
        </div>

        {/* Status card */}
        <div className="p-3 border-b border-pwc-border space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[9px] font-bold text-pwc-text-dim uppercase tracking-wider">Orchestrator</div>
            {status && <StatusBadge status={status.status} />}
          </div>

          {status && status.status !== "idle" && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-[9px]">
                <span className="text-pwc-text-dim">Progress</span>
                <span className="text-pwc-text font-bold">
                  {status.completed_count} / {status.total_docs}
                </span>
              </div>
              <div className="h-1.5 bg-pwc-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 transition-all duration-500"
                  style={{ width: `${status.total_docs ? (status.completed_count / status.total_docs) * 100 : 0}%` }}
                />
              </div>
              {status.failed_count > 0 && (
                <div className="text-[9px] text-red-400">
                  {status.failed_count} failed
                </div>
              )}
              {status.current_doc && (
                <div className="text-[9px] text-blue-400 font-mono truncate">
                  ↻ {status.current_doc}
                </div>
              )}
            </div>
          )}

          {/* Corpus stats */}
          <div className="grid grid-cols-2 gap-1.5 mt-1">
            {[
              ["Catalog", totalDocs],
              ["Generated", generatedCount],
            ].map(([label, val]) => (
              <div key={label as string} className="flex flex-col items-center py-2 bg-pwc-bg rounded border border-pwc-border">
                <span className="text-[14px] font-bold text-pwc-orange">{val}</span>
                <span className="text-[8px] text-pwc-text-dim">{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Settings */}
        <div className="p-3 border-b border-pwc-border space-y-2">
          <div className="text-[9px] font-bold text-pwc-text-dim uppercase tracking-wider">Settings</div>
          <div>
            <label className="text-[9px] text-pwc-text-dim block mb-1">Organisation (Arabic)</label>
            <input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              className="w-full bg-pwc-bg border border-pwc-border rounded px-2 py-1.5 text-[10px] text-pwc-text font-arabic text-right"
              dir="rtl"
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={skipExisting}
              onChange={(e) => setSkipExisting(e.target.checked)}
              className="accent-pwc-orange"
            />
            <span className="text-[9px] text-pwc-text">Skip already generated</span>
          </label>
        </div>

        {/* Actions */}
        <div className="p-3 space-y-2">
          <div className="text-[9px] font-bold text-pwc-text-dim uppercase tracking-wider">Actions</div>

          {status?.status !== "running" ? (
            <>
              <button
                onClick={() => startOrchestration()}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold rounded transition-colors"
              >
                Start All 110 Docs
              </button>
              {selectedDocs.size > 0 && (
                <button
                  onClick={() => startOrchestration([...selectedDocs])}
                  className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white text-[10px] font-bold rounded transition-colors"
                >
                  Generate Selected ({selectedDocs.size})
                </button>
              )}
            </>
          ) : (
            <button
              onClick={stopOrchestration}
              className="w-full py-2 bg-red-600 hover:bg-red-500 text-white text-[10px] font-bold rounded transition-colors"
            >
              Stop Orchestration
            </button>
          )}

          <button
            onClick={refreshStatus}
            className="w-full py-1.5 bg-pwc-surface border border-pwc-border hover:border-pwc-border-bright text-pwc-text-dim text-[9px] rounded transition-colors"
          >
            Refresh Status
          </button>
        </div>

        {/* Section switcher */}
        <div className="p-3 border-t border-pwc-border mt-auto space-y-1">
          {(["catalog", "status", "generated"] as const).map((sec) => (
            <button
              key={sec}
              onClick={() => setActiveSection(sec)}
              className={clsx(
                "w-full text-left px-2 py-1.5 rounded text-[9px] font-semibold transition-colors",
                activeSection === sec
                  ? "bg-pwc-orange/20 text-pwc-orange border border-pwc-orange/30"
                  : "text-pwc-text-dim hover:text-pwc-text"
              )}
            >
              {sec === "catalog" ? "Document Catalog" : sec === "status" ? "Run Log" : "Generated Docs"}
            </button>
          ))}
        </div>
      </aside>

      {/* ── Main content area ─────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {error && (
          <div className="px-4 py-2 bg-red-900/20 border-b border-red-500/30">
            <span className="text-[9px] text-red-400 font-bold">Error: </span>
            <span className="text-[9px] text-red-300">{error}</span>
            <button onClick={() => setError(null)} className="ml-2 text-[9px] text-red-400 hover:text-red-200">✕</button>
          </div>
        )}

        {/* ── Catalog view ──────────────────────────────────────────────── */}
        {activeSection === "catalog" && (
          <div className="flex-1 overflow-y-auto p-4 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[12px] font-bold text-pwc-text">Document Catalog</div>
                <div className="text-[9px] text-pwc-text-dim mt-0.5">
                  110 documents across 6 waves — click rows to select for partial generation
                </div>
              </div>
              <div className="flex gap-2 text-[9px]">
                {[
                  { label: "Policy", cls: "text-blue-400" },
                  { label: "Standard", cls: "text-emerald-400" },
                  { label: "Procedure", cls: "text-amber-400" },
                ].map(({ label, cls }) => (
                  <span key={label} className={clsx("flex items-center gap-1", cls)}>
                    <span className="w-2 h-2 rounded-sm bg-current opacity-60" />
                    {label}
                  </span>
                ))}
              </div>
            </div>

            {waves.map(([waveKey, docIds]) => (
              <div key={waveKey} className="space-y-1">
                <div className="flex items-center gap-2 mb-2">
                  <div className="text-[10px] font-bold text-pwc-text">
                    {WAVE_LABELS[waveKey] ?? waveKey}
                  </div>
                  <div className="h-px flex-1 bg-pwc-border" />
                  <div className="text-[8px] text-pwc-text-dim">{docIds.length} docs</div>
                </div>

                <div className="grid grid-cols-1 gap-0.5">
                  {docIds.map((docId) => {
                    const doc = docIndex[docId];
                    if (!doc) return null;
                    const isGenerated = generatedSet.has(docId);
                    const isSelected = selectedDocs.has(docId);
                    const isGenerating = singleGenDoc === docId;
                    const isRunning = status?.current_doc === docId;

                    return (
                      <div
                        key={docId}
                        onClick={() => toggleDoc(docId)}
                        className={clsx(
                          "flex items-center gap-2 px-3 py-2 rounded border cursor-pointer transition-all",
                          isSelected
                            ? "bg-pwc-orange/10 border-pwc-orange/40"
                            : isGenerated
                            ? "bg-emerald-900/5 border-emerald-500/20 hover:border-emerald-500/40"
                            : "bg-pwc-surface border-pwc-border hover:border-pwc-border-bright"
                        )}
                      >
                        {/* Selection checkbox */}
                        <div className={clsx(
                          "w-3 h-3 rounded border shrink-0 flex items-center justify-center",
                          isSelected ? "bg-pwc-orange border-pwc-orange" : "border-pwc-border"
                        )}>
                          {isSelected && <span className="text-white text-[7px] font-bold">✓</span>}
                        </div>

                        {/* Doc ID */}
                        <span className="text-[9px] font-mono text-pwc-text-dim w-14 shrink-0">{docId}</span>

                        {/* Type badge */}
                        <span className={clsx(
                          "text-[7px] font-bold px-1.5 py-0.5 rounded border shrink-0",
                          DOC_TYPE_COLOR[doc.type]
                        )}>
                          {DOC_TYPE_LABEL[doc.type]}
                        </span>

                        {/* Name */}
                        <div className="flex-1 min-w-0">
                          <div className="text-[10px] text-pwc-text truncate">{doc.name_en}</div>
                          <div className="text-[8px] text-pwc-text-dim truncate font-arabic" dir="rtl">
                            {doc.name_ar}
                          </div>
                        </div>

                        {/* Dependencies */}
                        {doc.depends_on.length > 0 && (
                          <div className="shrink-0 text-[7px] text-pwc-text-muted max-w-[80px] truncate">
                            ← {doc.depends_on.join(", ")}
                          </div>
                        )}

                        {/* Status indicators */}
                        <div className="shrink-0 flex items-center gap-1">
                          {isRunning && (
                            <span className="text-[8px] text-blue-400 animate-pulse">↻</span>
                          )}
                          {isGenerating && (
                            <span className="text-[8px] text-amber-400 animate-pulse">...</span>
                          )}
                          {isGenerated && !isRunning && (
                            <span className="text-[8px] text-emerald-400">✓</span>
                          )}
                          {status?.failed_docs.includes(docId) && (
                            <span className="text-[8px] text-red-400">✗</span>
                          )}
                        </div>

                        {/* Single generate button */}
                        <button
                          onClick={(e) => { e.stopPropagation(); generateSingle(docId); }}
                          disabled={isGenerating || status?.status === "running"}
                          className={clsx(
                            "shrink-0 px-1.5 py-0.5 rounded text-[8px] border transition-colors",
                            isGenerating
                              ? "text-amber-400 border-amber-500/30 cursor-wait"
                              : "text-pwc-text-dim border-pwc-border hover:text-pwc-text hover:border-pwc-border-bright"
                          )}
                        >
                          {isGenerating ? "..." : "↺"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Status / Log view ─────────────────────────────────────────── */}
        {activeSection === "status" && (
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <div className="text-[12px] font-bold text-pwc-text">Run Log</div>

            {status ? (
              <div className="space-y-3">
                <div className="grid grid-cols-4 gap-2">
                  {[
                    { label: "Status", val: status.status.toUpperCase() },
                    { label: "Wave", val: status.current_wave || "-" },
                    { label: "Completed", val: status.completed_count },
                    { label: "Failed", val: status.failed_count },
                  ].map(({ label, val }) => (
                    <div key={label} className="bg-pwc-surface border border-pwc-border rounded p-2 text-center">
                      <div className="text-[14px] font-bold text-pwc-orange">{val}</div>
                      <div className="text-[8px] text-pwc-text-dim">{label}</div>
                    </div>
                  ))}
                </div>

                {status.current_doc && (
                  <div className="bg-blue-900/20 border border-blue-500/30 rounded p-3">
                    <div className="text-[9px] font-bold text-blue-300 mb-1">Currently Generating</div>
                    <div className="text-[11px] text-blue-200 font-mono">{status.current_doc}</div>
                    {docIndex[status.current_doc] && (
                      <div className="text-[9px] text-blue-300/70 mt-0.5">
                        {docIndex[status.current_doc].name_en}
                      </div>
                    )}
                  </div>
                )}

                {status.failed_docs.length > 0 && (
                  <div className="bg-red-900/10 border border-red-500/20 rounded p-3">
                    <div className="text-[9px] font-bold text-red-400 mb-2">Failed Documents</div>
                    <div className="space-y-0.5">
                      {status.failed_docs.map((id) => (
                        <div key={id} className="text-[9px] font-mono text-red-300">{id}</div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Log entries */}
                <div className="space-y-0.5">
                  <div className="text-[9px] font-bold text-pwc-text-dim mb-2">Recent Events</div>
                  {[...status.recent_log].reverse().map((entry, i) => (
                    <div
                      key={i}
                      className={clsx(
                        "flex items-start gap-2 px-2 py-1 rounded text-[9px] font-mono",
                        entry.level === "ERROR" ? "bg-red-900/10 text-red-300" :
                        entry.level === "OK"    ? "bg-emerald-900/10 text-emerald-300" :
                        entry.level === "SKIP"  ? "bg-pwc-surface text-pwc-text-muted" :
                        "bg-pwc-surface text-pwc-text-dim"
                      )}
                    >
                      <span className="shrink-0 opacity-60">{entry.ts.slice(11, 19)}</span>
                      <span className={clsx(
                        "shrink-0 w-10 font-bold",
                        entry.level === "ERROR" ? "text-red-400" :
                        entry.level === "OK"    ? "text-emerald-400" :
                        "text-pwc-text-dim"
                      )}>
                        {entry.level}
                      </span>
                      {entry.doc_id && (
                        <span className="shrink-0 text-pwc-orange">{entry.doc_id}</span>
                      )}
                      <span className="flex-1 break-all">{entry.msg}</span>
                    </div>
                  ))}
                  {status.recent_log.length === 0 && (
                    <div className="text-[9px] text-pwc-text-muted py-4 text-center">
                      No log entries yet
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-[9px] text-pwc-text-dim py-8 text-center">Loading status...</div>
            )}
          </div>
        )}

        {/* ── Generated docs view ───────────────────────────────────────── */}
        {activeSection === "generated" && (
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[12px] font-bold text-pwc-text">
                Generated Documents ({generatedDocs.length})
              </div>
              <button
                onClick={loadGenerated}
                className="px-2 py-1 text-[9px] text-pwc-text-dim border border-pwc-border rounded hover:border-pwc-border-bright"
              >
                Refresh
              </button>
            </div>

            {generatedDocs.length === 0 ? (
              <div className="text-[9px] text-pwc-text-muted py-12 text-center">
                No documents generated yet. Start the orchestrator to begin.
              </div>
            ) : (
              <div className="space-y-1">
                {generatedDocs.map((doc) => (
                  <div
                    key={doc.doc_id}
                    className="flex items-center gap-3 px-3 py-2.5 bg-pwc-surface border border-pwc-border rounded hover:border-pwc-border-bright transition-colors"
                  >
                    <span className={clsx(
                      "text-[7px] font-bold px-1.5 py-0.5 rounded border shrink-0",
                      DOC_TYPE_COLOR[doc.doc_type ?? "policy"]
                    )}>
                      {DOC_TYPE_LABEL[doc.doc_type ?? "policy"]}
                    </span>

                    <span className="text-[9px] font-mono text-pwc-text-dim w-14 shrink-0">{doc.doc_id}</span>

                    <div className="flex-1 min-w-0">
                      {doc.title_ar && (
                        <div className="text-[10px] text-pwc-text truncate font-arabic text-right" dir="rtl">
                          {doc.title_ar}
                        </div>
                      )}
                      {doc.title_en && (
                        <div className="text-[9px] text-pwc-text-dim truncate">{doc.title_en}</div>
                      )}
                    </div>

                    <span className="text-[8px] text-pwc-text-muted shrink-0">v{doc.version ?? "1.0"}</span>

                    <a
                      href={`${BASE}/api/orchestrate/download/${doc.doc_id}`}
                      download={`${doc.doc_id}.docx`}
                      className="shrink-0 px-2 py-1 text-[8px] text-emerald-400 border border-emerald-500/30 rounded hover:bg-emerald-900/20 transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      ↓ DOCX
                    </a>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
