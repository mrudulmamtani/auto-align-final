"use client";

import { useState, useCallback, useRef } from "react";
import { clsx } from "clsx";
import dynamic from "next/dynamic";
import { uccfIngest, type UccfIngestResult } from "@/lib/api";
import { ALL_STANDARDS } from "@/lib/standardsEngine";
import { LinkGroupProvider } from "@/contexts/LinkGroupContext";
import type { ForensicModalState } from "@/components/panels/ForensicPDFViewer";

// Lazy-load heavy D3 panels to avoid SSR issues
const RMapGraph   = dynamic(() => import("@/components/panels/RMapGraph"),   { ssr: false });
const UCCFEngine  = dynamic(() => import("@/components/panels/UCCFEngine"),  { ssr: false });
const ArrWorksheet = dynamic(() => import("@/components/panels/ArrWorksheet"), { ssr: false });
const ForensicPDFViewer = dynamic(() => import("@/components/panels/ForensicPDFViewer"), { ssr: false });
const PolicyForensicPanel = dynamic(() => import("@/components/panels/PolicyForensicPanel"), { ssr: false });
const TemplateManagerPanel = dynamic(() => import("@/components/panels/TemplateManagerPanel"), { ssr: false });
const GeneratePanel = dynamic(() => import("@/components/panels/GeneratePanel"), { ssr: false });
const OrchestratePanel = dynamic(() => import("@/components/panels/OrchestratePanel"), { ssr: false });
const DocumentLibraryPanel = dynamic(() => import("@/components/panels/DocumentLibraryPanel"), { ssr: false });

type TabKey = "kg" | "uccf" | "risk" | "documents" | "generate" | "orchestrate" | "templates" | "upload";

interface TabDef {
  key: TabKey;
  label: string;
}

const TABS: TabDef[] = [
  { key: "kg",          label: "Knowledge Graph" },
  { key: "uccf",        label: "UCCF Overlap" },
  { key: "risk",        label: "Risk Register" },
  { key: "documents",   label: "Documents" },
  { key: "generate",    label: "Generate" },
  { key: "orchestrate", label: "Orchestrate" },
  { key: "templates",   label: "Templates" },
  { key: "upload",      label: "Upload Standard" },
];

// ── Upload Standard Panel ──────────────────────────────────────────────────

function UploadStandardPanel() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UccfIngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(async (file: File) => {
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await uccfIngest(file);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  return (
    <div className="flex-1 overflow-auto p-6 min-h-0">
      <div className="max-w-2xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="text-[13px] font-bold text-pwc-text mb-1">Upload Standard JSON</div>
          <div className="text-[10px] text-pwc-text-dim leading-relaxed">
            Upload any cybersecurity or compliance standard as a JSON file.
            The engine auto-detects the format, ingests it into the Knowledge Graph,
            and runs semantic matching against all existing standards.
          </div>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            "border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all",
            dragOver ? "border-pwc-orange bg-pwc-orange/5" : "border-pwc-border hover:border-pwc-border-bright",
            uploading ? "opacity-60 pointer-events-none" : ""
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
          />
          <div className="text-[40px] mb-3 text-pwc-orange font-bold select-none">
            {uploading ? "..." : "+"}
          </div>
          <div className="text-[12px] font-bold text-pwc-text mb-1">
            {uploading ? "Ingesting standard..." : "Drop JSON file here or click to browse"}
          </div>
          <div className="text-[10px] text-pwc-text-dim">Accepts .json files only</div>
        </div>

        {/* Result */}
        {result && (
          <div className="border border-pwc-border rounded-lg p-4 bg-pwc-surface space-y-3">
            <div className="text-[11px] font-bold text-risk-low">Standard Ingested Successfully</div>
            <div className="text-[10px] text-pwc-text font-medium">{result.standard_name}</div>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["Controls parsed", result.controls_parsed],
                ["Domains created", result.domains_created],
                ["Controls in KG",  result.controls_created],
                ["Semantic links",  result.semantic_links_created],
              ].map(([label, val]) => (
                <div key={label as string} className="flex items-center justify-between border border-pwc-border/50 rounded px-2.5 py-2">
                  <span className="text-[9px] text-pwc-text-dim">{label}</span>
                  <span className="text-[11px] font-bold text-pwc-orange">{val}</span>
                </div>
              ))}
            </div>
            <div className="text-[9px] text-pwc-text-muted font-mono truncate">{result.standard_urn}</div>
          </div>
        )}

        {error && (
          <div className="border border-red-500/30 rounded-lg p-4 bg-red-500/5">
            <div className="text-[10px] text-red-400 font-bold mb-1">Upload Error</div>
            <div className="text-[9px] text-red-300/80">{error}</div>
          </div>
        )}

        {/* Format Guide */}
        <div className="border border-pwc-border rounded-lg p-4 space-y-3">
          <div className="text-[10px] font-bold text-pwc-text">Supported JSON Formats</div>
          <div className="space-y-3">
            {[
              {
                name: "Normalized (recommended)",
                sample: `{
  "standard_name": "My Standard",
  "short_name": "MS",
  "version": "1.0",
  "domains": [
    {
      "id": "AC",
      "name": "Access Control",
      "controls": [
        { "id": "AC-1", "name": "...", "text": "..." }
      ]
    }
  ]
}`,
              },
              {
                name: "UAE IAS flat list",
                sample: `[
  {
    "control_family_id": "1",
    "control_family_name": "...",
    "control_id": "1.1",
    "control_statement": "..."
  }
]`,
              },
              {
                name: "NCA flat list",
                sample: `[
  {
    "framework_name": "NCA XXX",
    "main_domain_id": "1",
    "control_id": "1-1",
    "control_statement": "..."
  }
]`,
              },
            ].map((fmt) => (
              <div key={fmt.name}>
                <div className="text-[9px] font-bold text-pwc-text-dim mb-1">{fmt.name}</div>
                <pre className="text-[8px] text-pwc-text-muted bg-pwc-bg rounded-lg p-3 overflow-x-auto whitespace-pre leading-relaxed border border-pwc-border">
                  {fmt.sample}
                </pre>
              </div>
            ))}
          </div>
        </div>

        {/* Currently loaded standards */}
        <div className="border border-pwc-border rounded-lg p-4">
          <div className="text-[10px] font-bold text-pwc-text mb-3">Currently Loaded Standards ({ALL_STANDARDS.length})</div>
          <div className="grid grid-cols-3 gap-1.5">
            {ALL_STANDARDS.map((s) => (
              <div key={s.urn} className="flex items-center gap-1.5 px-2 py-1 bg-pwc-bg rounded border border-pwc-border/50">
                <div className="w-1.5 h-1.5 rounded-full bg-pwc-orange shrink-0" />
                <span className="text-[8px] text-pwc-text truncate">{s.short_name}</span>
                <span className="text-[7px] text-pwc-text-muted ml-auto shrink-0">{s.totalControls}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Shell ─────────────────────────────────────────────────────────────

type DocSubTab = "library" | "forensic";

export default function KGShell() {
  const [activeTab, setActiveTab] = useState<TabKey>("kg");
  const [docSubTab, setDocSubTab] = useState<DocSubTab>("library");
  const [pendingPdf, setPendingPdf] = useState<ForensicModalState | null>(null);
  const [coveredControlIds, setCoveredControlIds] = useState<Set<string>>(new Set());

  // When a generation job completes, switch to Documents > Forensic Analysis
  const handleViewGeneratedDoc = useCallback((_docId: string) => {
    setActiveTab("documents");
    setDocSubTab("forensic");
  }, []);

  // Control click from KG / UCCF → highlight in forensic reader (no tab switch)
  const handleControlClick = useCallback((standardName: string, controlId: string) => {
    setPendingPdf({ standardName, controlId });
  }, []);

  // Open a generated document PDF in the forensic reader
  const handleViewDocPdf = useCallback((docId: string) => {
    const base = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8100";
    setPendingPdf({
      standardName: docId,
      controlId: docId,
      pdfUrl: `${base}/api/doc-library/${docId}/pdf`,
      controlText: docId,
    });
  }, []);

  return (
    <LinkGroupProvider>
      <div className="flex flex-col w-full h-screen overflow-hidden bg-pwc-bg text-pwc-text">

        {/* ── Header ───────────────────────────────────────────────────── */}
        <header className="flex items-center justify-between px-4 py-2 bg-pwc-surface border-b border-pwc-border shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-pwc-orange font-bold text-[11px] tracking-wider">◆</span>
            <span className="text-[13px] font-bold text-pwc-text tracking-wide">Controls Intelligence Hub</span>
          </div>
          <div className="text-[14px] font-bold tracking-widest" style={{ color: "#D04A02" }}>
            PwC
          </div>
        </header>

        {/* ── Body: left tabs + right forensic panel ────────────────────── */}
        <div className="flex flex-1 min-h-0 overflow-hidden">

          {/* ── Left pane ───────────────────────────────────────────────── */}
          <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

            {/* Tab bar */}
            <nav className="flex items-center gap-0.5 px-3 py-1.5 bg-pwc-surface border-b border-pwc-border shrink-0">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={clsx(
                    "px-3 py-1 text-[10px] font-semibold rounded border transition-all duration-150",
                    activeTab === tab.key
                      ? "bg-pwc-orange text-white border-pwc-orange shadow-sm"
                      : "text-pwc-text-dim border-transparent hover:border-pwc-border hover:text-pwc-text"
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            {/* Tab content */}
            <main className="flex-1 min-h-0 overflow-hidden">
              {activeTab === "kg" && (
                <div className="w-full h-full flex flex-col">
                  <RMapGraph onControlClick={handleControlClick} coveredControlIds={coveredControlIds} />
                </div>
              )}
              {activeTab === "uccf" && (
                <div className="w-full h-full flex flex-col">
                  <UCCFEngine />
                </div>
              )}
              {activeTab === "risk" && (
                <div className="w-full h-full flex flex-col">
                  <ArrWorksheet />
                </div>
              )}
              {activeTab === "documents" && (
                <div className="w-full h-full flex flex-col overflow-hidden">
                  {/* Sub-tab bar */}
                  <div className="flex items-center gap-0.5 px-3 py-1.5 bg-pwc-surface border-b border-pwc-border shrink-0">
                    {([
                      { key: "library",  label: "Library" },
                      { key: "forensic", label: "Forensic Analysis" },
                    ] as { key: DocSubTab; label: string }[]).map((st) => (
                      <button
                        key={st.key}
                        onClick={() => setDocSubTab(st.key)}
                        className={clsx(
                          "px-3 py-0.5 text-[9px] font-semibold rounded border transition-all duration-150",
                          docSubTab === st.key
                            ? "bg-pwc-orange text-white border-pwc-orange"
                            : "text-pwc-text-dim border-transparent hover:border-pwc-border hover:text-pwc-text"
                        )}
                      >
                        {st.label}
                      </button>
                    ))}
                  </div>
                  {/* Sub-tab content */}
                  <div className="flex-1 min-h-0 overflow-hidden">
                    {docSubTab === "library" && (
                      <DocumentLibraryPanel onViewPdf={handleViewDocPdf} />
                    )}
                    {docSubTab === "forensic" && (
                      <PolicyForensicPanel
                        onCoverageChange={setCoveredControlIds}
                        onControlClick={handleControlClick}
                      />
                    )}
                  </div>
                </div>
              )}
              {activeTab === "generate" && (
                <div className="w-full h-full flex flex-col overflow-hidden">
                  <GeneratePanel onViewDoc={handleViewGeneratedDoc} />
                </div>
              )}
              {activeTab === "orchestrate" && (
                <div className="w-full h-full flex flex-col overflow-hidden">
                  <OrchestratePanel />
                </div>
              )}
              {activeTab === "templates" && (
                <div className="w-full h-full flex flex-col overflow-hidden">
                  <TemplateManagerPanel />
                </div>
              )}
              {activeTab === "upload" && (
                <div className="w-full h-full flex flex-col overflow-hidden">
                  <UploadStandardPanel />
                </div>
              )}
            </main>
          </div>

          {/* ── Right pane: Forensic Reader (always visible) ─────────────── */}
          <div className="w-[420px] shrink-0 flex flex-col overflow-hidden border-l border-pwc-border">
            <ForensicPDFViewer
              initialControl={pendingPdf}
              onClearInitial={() => setPendingPdf(null)}
            />
          </div>

        </div>
      </div>
    </LinkGroupProvider>
  );
}
