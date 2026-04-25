"use client";

/**
 * DocumentLibraryPanel
 *
 * Full 110-document governance catalog browser powered by docGenConstruct.json.
 *
 * Features:
 *  - All documents organized by wave, with live generation status
 *  - Click a document → detail panel: dependencies, dependents, actions
 *  - Generate a single document or a full dependency chain
 *  - Stale detection: warns when a dependency was regenerated after this doc
 *  - "View PDF" → opens generated PDF in the Forensic Reader panel
 *  - "Download DOCX" → downloads the generated DOCX
 *  - Org profile picker for generation context
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { clsx } from "clsx";
import {
  fetchDocLibrary,
  fetchDocDetail,
  generateLibraryDoc,
  generateDocChain,
  fetchLibraryJob,
  fetchLibraryJobs,
  getDocPdfUrl,
  getDocDownloadUrl,
  type LibraryDoc,
  type LibraryWave,
  type LibraryDocDetail,
  type LibraryJob,
  type LibraryProfileIn,
} from "@/lib/autoalignApi";

// ── Tiny helpers ─────────────────────────────────────────────────────────────

function Spinner({ size = 3 }: { size?: number }) {
  return (
    <span
      className={`inline-block w-${size} h-${size} border-2 border-pwc-orange border-t-transparent rounded-full animate-spin`}
    />
  );
}

function StatusBadge({ status, stale }: { status: string; stale?: boolean }) {
  if (stale) {
    return (
      <span className="px-1.5 py-0.5 text-[7px] font-bold rounded border border-amber-400 text-amber-600 bg-amber-50 uppercase">
        STALE
      </span>
    );
  }
  const map: Record<string, string> = {
    generated: "border-green-400 text-green-700 bg-green-50",
    generating: "border-blue-400 text-blue-600 bg-blue-50 animate-pulse",
    failed: "border-red-400 text-red-600 bg-red-50",
    not_generated: "border-pwc-border text-pwc-text-muted bg-transparent",
    queued: "border-yellow-400 text-yellow-700 bg-yellow-50",
    running: "border-blue-400 text-blue-600 bg-blue-50 animate-pulse",
    skipped: "border-pwc-border text-pwc-text-dim bg-transparent",
    completed: "border-green-400 text-green-700 bg-green-50",
  };
  const cls = map[status] ?? map["not_generated"];
  return (
    <span className={clsx("px-1.5 py-0.5 text-[7px] font-bold rounded border uppercase", cls)}>
      {status === "not_generated" ? "—" : status}
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  const map: Record<string, string> = {
    policy:    "bg-orange-100 text-pwc-orange",
    standard:  "bg-blue-100 text-blue-700",
    procedure: "bg-purple-100 text-purple-700",
  };
  return (
    <span className={clsx("px-1 py-0.5 text-[7px] font-bold rounded uppercase", map[type] ?? "bg-pwc-surface text-pwc-text-dim")}>
      {type.slice(0, 3)}
    </span>
  );
}

function elapsed(s?: string, e?: string) {
  if (!s) return "";
  const sec = Math.round((e ? new Date(e).getTime() : Date.now()) - new Date(s).getTime()) / 1000;
  return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
}

// ── Profile editor (inline, minimal) ─────────────────────────────────────────

const DEFAULT_PROFILE: LibraryProfileIn = {
  org_name: "Ministry of Digital Economy",
  sector: "Government",
  hosting_model: "hybrid",
  jurisdiction: "UAE",
};

function ProfileEditor({
  profile,
  onChange,
}: {
  profile: LibraryProfileIn;
  onChange: (p: LibraryProfileIn) => void;
}) {
  const field = (label: string, key: keyof LibraryProfileIn, placeholder?: string) => (
    <div key={key}>
      <label className="block text-[7px] font-bold text-pwc-text-muted mb-0.5 uppercase">{label}</label>
      <input
        className="w-full px-2 py-1 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
        value={(profile[key] as string) ?? ""}
        placeholder={placeholder}
        onChange={(e) => onChange({ ...profile, [key]: e.target.value })}
      />
    </div>
  );
  return (
    <div className="space-y-1.5">
      {field("Organisation", "org_name", "e.g. Ministry of Digital Economy")}
      <div className="grid grid-cols-2 gap-1.5">
        {field("Sector", "sector")}
        {field("Jurisdiction", "jurisdiction")}
      </div>
    </div>
  );
}

// ── Stale notification banner ─────────────────────────────────────────────────

function StaleBanner({
  staleCount,
  onDismiss,
}: {
  staleCount: number;
  onDismiss: () => void;
}) {
  if (staleCount === 0) return null;
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 border-b border-amber-300 text-amber-700 shrink-0">
      <span className="text-[9px] font-bold shrink-0">⚠</span>
      <span className="text-[9px] flex-1">
        {staleCount} document{staleCount > 1 ? "s" : ""} may be outdated — dependencies were regenerated.
      </span>
      <button
        onClick={onDismiss}
        className="text-[8px] underline shrink-0 hover:no-underline"
      >
        dismiss
      </button>
    </div>
  );
}

// ── Active jobs ticker ────────────────────────────────────────────────────────

function ActiveJobsTicker({ jobs, onRefresh }: { jobs: LibraryJob[]; onRefresh: () => void }) {
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  if (active.length === 0) return null;
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border-b border-blue-200 text-blue-700 shrink-0">
      <Spinner size={2} />
      <span className="text-[9px] flex-1 font-medium">
        {active.length} generation job{active.length > 1 ? "s" : ""} in progress
        {active[0] ? ` — ${active[0].doc_id}: ${active[0].doc_name}` : ""}
      </span>
      <button onClick={onRefresh} className="text-[8px] underline shrink-0">refresh</button>
    </div>
  );
}

// ── Document list ─────────────────────────────────────────────────────────────

function DocListItem({
  doc,
  selected,
  onClick,
}: {
  doc: LibraryDoc;
  selected: boolean;
  onClick: () => void;
}) {
  const st = doc.gen_status;
  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left px-3 py-1.5 flex items-center gap-2 border-l-2 transition-colors",
        selected
          ? "bg-orange-50 border-l-pwc-orange"
          : "hover:bg-pwc-surface-raised border-l-transparent",
      )}
    >
      <span className="text-[7px] font-mono font-bold text-pwc-orange w-[46px] shrink-0">
        {doc.id}
      </span>
      <TypeBadge type={doc.type} />
      <span className="text-[8px] text-pwc-text flex-1 min-w-0 truncate">{doc.name_en}</span>
      <StatusBadge status={st.status} stale={st.stale} />
    </button>
  );
}

// ── Document detail panel ─────────────────────────────────────────────────────

function DocDetailPanel({
  doc,
  jobs,
  profile,
  onGenerate,
  onGenerateChain,
  onViewPdf,
  onSelectDoc,
}: {
  doc: LibraryDocDetail;
  jobs: LibraryJob[];
  profile: LibraryProfileIn;
  onGenerate: (docId: string, force: boolean) => void;
  onGenerateChain: (docIds: string[]) => void;
  onViewPdf: (docId: string) => void;
  onSelectDoc: (docId: string) => void;
}) {
  const st = doc.gen_status;
  const activeJob = jobs.find((j) => j.doc_id === doc.id && (j.status === "running" || j.status === "queued"));

  const missingDeps = doc.missing_deps ?? [];
  const staleDownstream = doc.all_dependents?.filter((d) => d.gen_status?.stale) ?? [];

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
      {/* ── Header ── */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[7px] font-mono font-bold text-pwc-orange">{doc.id}</span>
          <TypeBadge type={doc.type} />
          <span className="text-[7px] text-pwc-text-muted">Wave {doc.wave}</span>
          <StatusBadge status={st.status} stale={st.stale} />
          {st.qa_passed !== null && (
            <span className={clsx(
              "text-[7px] font-bold px-1 py-0.5 rounded border",
              st.qa_passed ? "border-green-300 text-green-700 bg-green-50" : "border-red-300 text-red-600 bg-red-50"
            )}>
              {st.qa_passed ? "QA ✓" : "QA ✗"}
            </span>
          )}
        </div>
        <div className="text-[12px] font-bold text-pwc-text">{doc.name_en}</div>
        {doc.name_ar && (
          <div className="text-[10px] text-pwc-text-dim mt-0.5" dir="rtl">{doc.name_ar}</div>
        )}
        {st.generated_at && (
          <div className="text-[8px] text-pwc-text-muted mt-1">
            Generated: {new Date(st.generated_at).toLocaleString()}
            {st.elapsed ? ` (${Math.round(st.elapsed)}s)` : ""}
          </div>
        )}
        {st.stale && (
          <div className="mt-2 flex items-start gap-1.5 px-2 py-1.5 rounded bg-amber-50 border border-amber-300">
            <span className="text-amber-600 text-[9px] font-bold shrink-0">⚠ STALE</span>
            <span className="text-[8px] text-amber-700">
              One or more dependencies were regenerated after this document was last built.
              Regenerate to ensure consistency.
            </span>
          </div>
        )}
      </div>

      {/* ── Actions ── */}
      <div className="space-y-2">
        {activeJob ? (
          <div className="flex items-center gap-2 px-3 py-2 rounded border border-blue-300 bg-blue-50">
            <Spinner />
            <div className="flex-1">
              <div className="text-[9px] font-bold text-blue-700">{activeJob.status === "queued" ? "Queued" : "Generating…"}</div>
              <div className="text-[8px] text-blue-600">{elapsed(activeJob.started_at || activeJob.queued_at)}</div>
            </div>
          </div>
        ) : (
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => onGenerate(doc.id, false)}
              disabled={missingDeps.length > 0 && st.status !== "generated"}
              className="flex-1 py-1.5 text-[9px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-40 transition-colors"
            >
              {st.status === "generated" ? "Regenerate" : "Generate"}
            </button>
            {st.status === "generated" && (
              <button
                onClick={() => onViewPdf(doc.id)}
                className="flex-1 py-1.5 text-[9px] font-bold border border-pwc-orange text-pwc-orange rounded hover:bg-pwc-orange/5 transition-colors"
              >
                View PDF
              </button>
            )}
            {st.status === "generated" && (
              <a
                href={getDocDownloadUrl(doc.id)}
                download={`${doc.id}.docx`}
                className="flex-1 py-1.5 text-[9px] font-bold border border-pwc-border text-pwc-text-dim rounded hover:border-pwc-border-bright transition-colors text-center"
              >
                Download DOCX
              </a>
            )}
          </div>
        )}

        {/* Chain generation */}
        {missingDeps.length > 0 && (
          <div className="px-3 py-2 rounded border border-amber-300 bg-amber-50 space-y-1.5">
            <div className="text-[9px] font-bold text-amber-700">
              Missing {missingDeps.length} prerequisite{missingDeps.length > 1 ? "s" : ""}
            </div>
            <div className="text-[8px] text-amber-600">
              {missingDeps.join(", ")} must be generated first.
            </div>
            <button
              onClick={() => onGenerateChain([doc.id])}
              className="w-full py-1.5 text-[9px] font-bold bg-amber-600 text-white rounded hover:bg-amber-700 transition-colors"
            >
              Generate Full Chain ({missingDeps.length + 1} docs)
            </button>
          </div>
        )}

        {/* Downstream stale notification */}
        {staleDownstream.length > 0 && (
          <div className="px-3 py-2 rounded border border-amber-200 bg-amber-50/50 space-y-1.5">
            <div className="text-[9px] font-bold text-amber-700">
              {staleDownstream.length} downstream document{staleDownstream.length > 1 ? "s" : ""} affected
            </div>
            <div className="text-[8px] text-amber-600">
              {staleDownstream.map((d) => d.id).join(", ")} may be outdated.
            </div>
            <button
              onClick={() => onGenerateChain(staleDownstream.map((d) => d.id))}
              className="w-full py-1.5 text-[9px] font-bold border border-amber-400 text-amber-700 rounded hover:bg-amber-100 transition-colors"
            >
              Regenerate Affected Documents
            </button>
          </div>
        )}
      </div>

      {/* ── Dependencies ── */}
      {doc.direct_dependencies && doc.direct_dependencies.length > 0 && (
        <div>
          <div className="text-[9px] font-bold text-pwc-text-dim uppercase mb-1.5">
            Required By ({doc.direct_dependencies.length})
          </div>
          <div className="space-y-0.5">
            {doc.direct_dependencies.map((d) => (
              <button
                key={d.id}
                onClick={() => onSelectDoc(d.id)}
                className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-pwc-surface-raised text-left transition-colors"
              >
                <span className="text-[7px] font-mono font-bold text-pwc-orange w-[46px] shrink-0">{d.id}</span>
                <TypeBadge type={d.type} />
                <span className="text-[8px] text-pwc-text flex-1 truncate">{d.name_en}</span>
                <StatusBadge status={d.gen_status?.status ?? "not_generated"} stale={d.gen_status?.stale} />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Dependents ── */}
      {doc.direct_dependents && doc.direct_dependents.length > 0 && (
        <div>
          <div className="text-[9px] font-bold text-pwc-text-dim uppercase mb-1.5">
            Depends On This ({doc.direct_dependents.length})
          </div>
          <div className="space-y-0.5">
            {doc.direct_dependents.map((d) => (
              <button
                key={d.id}
                onClick={() => onSelectDoc(d.id)}
                className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-pwc-surface-raised text-left transition-colors"
              >
                <span className="text-[7px] font-mono font-bold text-pwc-orange w-[46px] shrink-0">{d.id}</span>
                <TypeBadge type={d.type} />
                <span className="text-[8px] text-pwc-text flex-1 truncate">{d.name_en}</span>
                <StatusBadge status={d.gen_status?.status ?? "not_generated"} stale={d.gen_status?.stale} />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Recent jobs log ───────────────────────────────────────────────────────────

function JobsLog({ jobs }: { jobs: LibraryJob[] }) {
  const recent = jobs.slice(0, 20);
  if (recent.length === 0) return null;
  return (
    <div className="border-t border-pwc-border shrink-0">
      <div className="px-3 py-1.5 text-[8px] font-bold text-pwc-text-dim uppercase">
        Recent Jobs ({recent.length})
      </div>
      <div className="max-h-[140px] overflow-y-auto">
        {recent.map((j) => (
          <div
            key={j.job_id}
            className="flex items-center gap-2 px-3 py-1 border-b border-pwc-border/40"
          >
            <StatusBadge status={j.status} />
            <span className="text-[7px] font-mono text-pwc-orange shrink-0">{j.doc_id}</span>
            <span className="text-[8px] text-pwc-text flex-1 truncate">{j.doc_name}</span>
            {j.error && (
              <span className="text-[7px] text-red-500 truncate max-w-[100px]" title={j.error}>
                {j.error.slice(0, 40)}
              </span>
            )}
            <span className="text-[7px] text-pwc-text-muted shrink-0 font-mono">
              {elapsed(j.started_at || j.queued_at, j.completed_at)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function DocumentLibraryPanel({
  onViewPdf,
}: {
  onViewPdf?: (docId: string) => void;
}) {
  const [waves, setWaves]           = useState<LibraryWave[]>([]);
  const [total, setTotal]           = useState(0);
  const [generated, setGenerated]   = useState(0);
  const [loading, setLoading]       = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail]         = useState<LibraryDocDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [jobs, setJobs]             = useState<LibraryJob[]>([]);
  const [staleDismissed, setStaleDismissed] = useState(false);
  const [profile, setProfile]       = useState<LibraryProfileIn>(DEFAULT_PROFILE);
  const [showProfile, setShowProfile] = useState(false);
  const [search, setSearch]         = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "policy" | "standard" | "procedure">("all");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Load library ──────────────────────────────────────────────────────────
  const loadLibrary = useCallback(async () => {
    try {
      const data = await fetchDocLibrary();
      setWaves(data.waves);
      setTotal(data.total);
      setGenerated(data.generated);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const data = await fetchLibraryJobs();
      setJobs(data.jobs);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadLibrary();
    loadJobs();
    pollRef.current = setInterval(() => {
      loadLibrary();
      loadJobs();
    }, 8000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadLibrary, loadJobs]);

  // ── Reload detail when jobs complete ─────────────────────────────────────
  useEffect(() => {
    const running = jobs.some((j) => j.status === "running" || j.status === "queued");
    if (!running && selectedId) {
      // Refresh detail on completion
      loadDetail(selectedId);
    }
  }, [jobs.map((j) => j.status).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Load detail ───────────────────────────────────────────────────────────
  const loadDetail = useCallback(async (docId: string) => {
    setDetailLoading(true);
    try {
      const d = await fetchDocDetail(docId);
      setDetail(d);
    } catch {
      // ignore
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleSelectDoc = useCallback((docId: string) => {
    setSelectedId(docId);
    loadDetail(docId);
  }, [loadDetail]);

  // ── Generate actions ──────────────────────────────────────────────────────
  const handleGenerate = useCallback(async (docId: string, force: boolean) => {
    try {
      const res = await generateLibraryDoc(docId, profile, force);
      setJobs((prev) => [{
        job_id: res.job_id,
        doc_id: docId,
        doc_name: res.message ?? docId,
        doc_type: detail?.type ?? "policy",
        status: "queued",
        queued_at: new Date().toISOString(),
      }, ...prev]);
    } catch (e) {
      alert(`Generation failed: ${e instanceof Error ? e.message : e}`);
    }
  }, [profile, detail]);

  const handleGenerateChain = useCallback(async (docIds: string[]) => {
    try {
      const res = await generateDocChain(docIds, profile, true);
      const newJobs = res.jobs.map((j) => ({
        ...j,
        doc_type: "policy",
        status: "queued" as const,
        queued_at: new Date().toISOString(),
      }));
      setJobs((prev) => [...newJobs, ...prev]);
    } catch (e) {
      alert(`Chain generation failed: ${e instanceof Error ? e.message : e}`);
    }
  }, [profile]);

  const handleViewPdf = useCallback((docId: string) => {
    onViewPdf?.(docId);
  }, [onViewPdf]);

  // ── Derived state ─────────────────────────────────────────────────────────
  const allDocs = waves.flatMap((w) => w.documents);
  const staleCount = staleDismissed ? 0 : allDocs.filter((d) => d.gen_status?.stale).length;

  const filteredWaves = waves.map((w) => ({
    ...w,
    documents: w.documents.filter((d) => {
      if (typeFilter !== "all" && d.type !== typeFilter) return false;
      if (search && !d.id.toLowerCase().includes(search.toLowerCase()) &&
          !d.name_en.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    }),
  })).filter((w) => w.documents.length > 0);

  const activeJobs = jobs.filter((j) => j.status === "running" || j.status === "queued");

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex w-full h-full overflow-hidden">

      {/* ── Left: Document list ──────────────────────────────────────────── */}
      <div className="w-[280px] shrink-0 flex flex-col border-r border-pwc-border overflow-hidden">

        {/* Header */}
        <div className="px-3 py-2 border-b border-pwc-border bg-pwc-surface shrink-0">
          <div className="flex items-center gap-2 mb-1.5">
            <div className="text-[10px] font-bold text-pwc-text flex-1">Document Catalog</div>
            {loading ? <Spinner /> : (
              <span className="text-[8px] text-pwc-text-muted font-mono">
                {generated}/{total}
              </span>
            )}
            <button
              onClick={() => setShowProfile((p) => !p)}
              className={clsx(
                "text-[8px] px-1.5 py-0.5 rounded border transition-colors",
                showProfile
                  ? "border-pwc-orange text-pwc-orange bg-pwc-orange/5"
                  : "border-pwc-border text-pwc-text-muted hover:border-pwc-orange"
              )}
              title="Edit organisation profile"
            >
              ⚙
            </button>
          </div>

          {/* Progress bar */}
          {total > 0 && (
            <div className="w-full h-1 bg-pwc-border rounded-full overflow-hidden mb-1.5">
              <div
                className="h-full bg-pwc-orange rounded-full transition-all"
                style={{ width: `${(generated / total) * 100}%` }}
              />
            </div>
          )}

          {/* Profile editor (collapsible) */}
          {showProfile && (
            <div className="mt-2 p-2 border border-pwc-border rounded bg-pwc-bg">
              <div className="text-[8px] font-bold text-pwc-text-dim mb-1.5 uppercase">Organisation Profile</div>
              <ProfileEditor profile={profile} onChange={setProfile} />
            </div>
          )}

          {/* Search + type filter */}
          <div className="flex gap-1 mt-1.5">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="flex-1 px-2 py-1 text-[8px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
            />
          </div>
          <div className="flex gap-0.5 mt-1">
            {(["all", "policy", "standard", "procedure"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={clsx(
                  "flex-1 py-0.5 text-[7px] font-bold rounded border transition-colors capitalize",
                  typeFilter === t
                    ? "bg-pwc-orange text-white border-pwc-orange"
                    : "border-pwc-border text-pwc-text-muted hover:border-pwc-orange"
                )}
              >
                {t === "all" ? "All" : t.slice(0, 3).toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* Doc list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <div className="flex justify-center items-center p-8">
              <Spinner size={4} />
            </div>
          )}
          {!loading && filteredWaves.map((wave) => (
            <div key={wave.wave_key}>
              <div className="px-3 py-1 text-[7px] font-bold text-pwc-text-muted uppercase tracking-wider bg-pwc-surface/50 border-b border-pwc-border/50 sticky top-0 z-10">
                {wave.wave_label}
              </div>
              {wave.documents.map((doc) => (
                <DocListItem
                  key={doc.id}
                  doc={doc}
                  selected={selectedId === doc.id}
                  onClick={() => handleSelectDoc(doc.id)}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: Detail + jobs ─────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">

        <StaleBanner staleCount={staleCount} onDismiss={() => setStaleDismissed(true)} />
        <ActiveJobsTicker jobs={activeJobs} onRefresh={() => { loadLibrary(); loadJobs(); }} />

        {/* Detail area */}
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          {!selectedId && (
            <div className="flex-1 flex flex-col items-center justify-center text-center px-8 gap-4">
              <div className="text-[32px] opacity-20">⊞</div>
              <div className="text-[11px] font-semibold text-pwc-text-dim">Select a Document</div>
              <div className="text-[9px] text-pwc-text-muted max-w-[260px] leading-relaxed">
                Click any document on the left to view its details, dependencies, and generation options.
              </div>
              <div className="flex gap-2 text-[8px] text-pwc-text-muted">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded bg-green-400" /> Generated
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded bg-amber-400" /> Stale
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded bg-pwc-border" /> Not generated
                </span>
              </div>
            </div>
          )}

          {selectedId && detailLoading && (
            <div className="flex-1 flex items-center justify-center">
              <Spinner size={5} />
            </div>
          )}

          {selectedId && detail && !detailLoading && (
            <DocDetailPanel
              doc={detail}
              jobs={jobs}
              profile={profile}
              onGenerate={handleGenerate}
              onGenerateChain={handleGenerateChain}
              onViewPdf={handleViewPdf}
              onSelectDoc={handleSelectDoc}
            />
          )}
        </div>

        {/* Jobs log at bottom */}
        <JobsLog jobs={jobs} />
      </div>
    </div>
  );
}
