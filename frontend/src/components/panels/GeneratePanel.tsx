"use client";

/**
 * GeneratePanel
 *
 * UI for generating cybersecurity policies and standards using the
 * AutoAlign Policy Factory (LLM-based generation with NCA/NIST controls).
 *
 * Features:
 *  - Select document type (policy / standard)
 *  - Choose a topic from the predefined catalogue or enter custom
 *  - Configure organisation profile
 *  - Submit → shows live job status with polling
 *  - On completion, redirects to Policy Library
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { clsx } from "clsx";
import {
  generateDocument,
  getGenerateJobStatus,
  listGenerateJobs,
  getTopics,
  type GenerateJob,
} from "@/lib/autoalignApi";

// ── Helpers ────────────────────────────────────────────────────────────────

function Spinner() {
  return (
    <span className="inline-block w-3 h-3 border-2 border-pwc-orange border-t-transparent rounded-full animate-spin" />
  );
}

function StatusDot({ status }: { status: GenerateJob["status"] }) {
  const cls = {
    queued:    "bg-yellow-400",
    running:   "bg-blue-400 animate-pulse",
    completed: "bg-green-500",
    failed:    "bg-red-500",
  }[status] ?? "bg-pwc-border";
  return <span className={clsx("inline-block w-2 h-2 rounded-full shrink-0", cls)} />;
}

function elapsed(start?: string, end?: string): string {
  if (!start) return "";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

// ── Job history card ───────────────────────────────────────────────────────

function JobCard({
  job,
  onViewDoc,
}: {
  job: GenerateJob;
  onViewDoc?: (docId: string) => void;
}) {
  const docId = (job.result as { doc_id?: string } | undefined)?.doc_id ?? job.doc_id ?? "";
  const title = (job.result as { title?: string } | undefined)?.title ?? job.topic;
  const qaPass = (job.result as { qa_passed?: boolean } | undefined)?.qa_passed;

  return (
    <div
      className={clsx(
        "px-3 py-2.5 border-b border-pwc-border/50 space-y-1",
        job.status === "running" ? "bg-blue-50/30" : ""
      )}
    >
      <div className="flex items-center gap-1.5">
        <StatusDot status={job.status} />
        <span className="text-[8px] font-mono font-bold text-pwc-orange">{job.job_id}</span>
        <span className={clsx(
          "text-[7px] font-bold uppercase px-1 rounded",
          job.doc_type === "policy" ? "bg-orange-100 text-pwc-orange" : "bg-blue-100 text-blue-700"
        )}>
          {job.doc_type}
        </span>
        <span className="ml-auto text-[7px] text-pwc-text-muted font-mono">
          {job.status === "running"
            ? elapsed(job.started_at)
            : job.status === "completed"
            ? elapsed(job.started_at, job.completed_at)
            : ""}
        </span>
      </div>

      <div className="text-[9px] text-pwc-text font-medium truncate">{title}</div>
      <div className="text-[8px] text-pwc-text-dim">{job.org_name}</div>

      {job.status === "running" && (
        <div className="flex items-center gap-1.5 text-[8px] text-blue-600">
          <Spinner /> Generating…
        </div>
      )}

      {job.status === "completed" && (
        <div className="flex items-center gap-2 flex-wrap">
          {qaPass !== undefined && (
            <span className={clsx(
              "text-[7px] font-bold px-1 py-0.5 rounded border",
              qaPass ? "bg-green-50 text-green-700 border-green-200" : "bg-red-50 text-red-600 border-red-200"
            )}>
              {qaPass ? "QA PASS" : "QA WARN"}
            </span>
          )}
          {docId && onViewDoc && (
            <button
              onClick={() => onViewDoc(docId)}
              className="text-[7px] font-bold text-pwc-orange underline underline-offset-2"
            >
              View in Policy Library →
            </button>
          )}
        </div>
      )}

      {job.status === "failed" && (
        <div className="text-[8px] text-red-500 truncate" title={job.error}>
          Error: {job.error?.slice(0, 80)}…
        </div>
      )}
    </div>
  );
}

// ── Generate form ──────────────────────────────────────────────────────────

interface TopicEntry { doc_id: string; topic: string; }

function GenerateForm({
  onJobStarted,
}: {
  onJobStarted: (jobId: string) => void;
}) {
  const [docType, setDocType] = useState<"policy" | "standard" | "procedure">("policy");
  const [selectedTopic, setSelectedTopic] = useState<TopicEntry | null>(null);
  const [customTopic, setCustomTopic] = useState("");
  const [customDocId, setCustomDocId] = useState("");
  const [orgName, setOrgName] = useState("");
  const [sector, setSector] = useState("Financial Services");
  const [hostingModel, setHostingModel] = useState("hybrid");
  const [jurisdiction, setJurisdiction] = useState("UAE");
  const [topics, setTopics] = useState<{ policies: TopicEntry[]; standards: TopicEntry[]; procedures: TopicEntry[] }>({
    policies: [], standards: [], procedures: [],
  });
  const [customization, setCustomization] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTopics().then(setTopics).catch(() => {});
  }, []);

  const topicList = docType === "policy" ? topics.policies : docType === "standard" ? topics.standards : topics.procedures;
  const effectiveTopic = selectedTopic?.topic || customTopic;
  const effectiveDocId = selectedTopic?.doc_id || customDocId || undefined;

  const handleSubmit = useCallback(async () => {
    if (!effectiveTopic.trim()) { setError("Topic is required"); return; }
    if (!orgName.trim()) { setError("Organisation name is required"); return; }
    setError(null);
    setSubmitting(true);
    try {
      const res = await generateDocument({
        doc_type: docType,
        topic: effectiveTopic.trim(),
        doc_id: effectiveDocId,
        scope: "All information assets and cybersecurity functions within the organisation",
        target_audience: "All staff, IT departments, and cybersecurity teams",
        version: "1.0",
        profile: {
          org_name: orgName.trim(),
          sector,
          hosting_model: hostingModel,
          jurisdiction,
          soc_model: "internal",
          data_classification: ["confidential", "restricted", "public"],
        },
        customization: customization.trim() || undefined,
      });
      onJobStarted(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation request failed");
    } finally {
      setSubmitting(false);
    }
  }, [docType, effectiveTopic, effectiveDocId, orgName, sector, hostingModel, jurisdiction, onJobStarted]);

  return (
    <div className="p-4 space-y-4">
      <div>
        <div className="text-[10px] font-bold text-pwc-text mb-0.5">New Document</div>
        <div className="text-[8px] text-pwc-text-dim">
          Generate a policy or standard using the AutoAlign AI factory (NCA ECC + NIST SP 800-53 controls).
        </div>
      </div>

      {/* Doc type */}
      <div className="flex gap-2">
        {(["policy", "standard", "procedure"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setDocType(t); setSelectedTopic(null); }}
            className={clsx(
              "flex-1 py-1.5 text-[9px] font-bold border rounded transition-colors capitalize",
              docType === t
                ? "bg-pwc-orange text-white border-pwc-orange"
                : "text-pwc-text-dim border-pwc-border hover:border-pwc-orange"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Topic selector */}
      <div>
        <label className="block text-[8px] font-bold text-pwc-text-dim mb-1 uppercase">
          Topic — select or type custom
        </label>
        <div className="max-h-[160px] overflow-y-auto border border-pwc-border rounded-lg mb-2 divide-y divide-pwc-border/50">
          {topicList.length === 0 && (
            <div className="px-3 py-2 text-[8px] text-pwc-text-muted">Loading topics…</div>
          )}
          {topicList.map((t) => (
            <button
              key={t.doc_id}
              onClick={() => { setSelectedTopic(t); setCustomTopic(""); }}
              className={clsx(
                "w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors",
                selectedTopic?.doc_id === t.doc_id
                  ? "bg-orange-50 border-l-2 border-l-pwc-orange"
                  : "hover:bg-pwc-surface-raised border-l-2 border-l-transparent"
              )}
            >
              <span className="text-[7px] font-mono font-bold text-pwc-orange w-[46px] shrink-0">{t.doc_id}</span>
              <span className="text-[8px] text-pwc-text">{t.topic}</span>
            </button>
          ))}
        </div>
        <input
          value={customTopic}
          onChange={(e) => { setCustomTopic(e.target.value); setSelectedTopic(null); }}
          placeholder="Or type a custom topic…"
          className="w-full px-2 py-1.5 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
        />
        {!selectedTopic && customTopic && (
          <input
            value={customDocId}
            onChange={(e) => setCustomDocId(e.target.value)}
            placeholder="Custom Doc ID (e.g. POL-99) — optional"
            className="w-full mt-1.5 px-2 py-1.5 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text font-mono focus:border-pwc-orange outline-none"
          />
        )}
      </div>

      {/* Org profile */}
      <div className="space-y-2">
        <div className="text-[8px] font-bold text-pwc-text-dim uppercase">Organisation Profile</div>
        <div>
          <label className="block text-[7px] font-bold text-pwc-text-muted mb-0.5">Name *</label>
          <input
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            placeholder="e.g. National Bank of Dubai"
            className="w-full px-2 py-1.5 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[7px] font-bold text-pwc-text-muted mb-0.5">Sector</label>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-full px-2 py-1 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
            >
              {["Financial Services", "Healthcare", "Government", "Telecommunications",
                "Energy & Utilities", "Retail", "Education", "Defence"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[7px] font-bold text-pwc-text-muted mb-0.5">Hosting</label>
            <select
              value={hostingModel}
              onChange={(e) => setHostingModel(e.target.value)}
              className="w-full px-2 py-1 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
            >
              {["cloud", "on-premise", "hybrid"].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-[7px] font-bold text-pwc-text-muted mb-0.5">Jurisdiction</label>
          <select
            value={jurisdiction}
            onChange={(e) => setJurisdiction(e.target.value)}
            className="w-full px-2 py-1 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
          >
            {["UAE", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman"].map((j) => (
              <option key={j} value={j}>{j}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Consultant Customization */}
      <div>
        <label className="block text-[8px] font-bold text-pwc-text-dim mb-1 uppercase">
          Consultant Customizations
          <span className="ml-1 normal-case font-normal text-pwc-text-muted">(optional)</span>
        </label>
        <textarea
          value={customization}
          onChange={(e) => setCustomization(e.target.value)}
          placeholder="e.g. Focus heavily on third-party risk management. Include specific references to SAMA framework. Add a section on cloud-native controls…"
          rows={5}
          className="w-full px-2 py-1.5 text-[9px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none resize-none leading-relaxed"
        />
        <div className="text-[7px] text-pwc-text-muted mt-0.5">
          These instructions are injected into every AI agent's prompt.
        </div>
      </div>

      {error && (
        <div className="text-[8px] text-red-500 font-bold border border-red-300 rounded px-2 py-1.5 bg-red-50">
          {error}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={submitting || !effectiveTopic.trim() || !orgName.trim()}
        className="w-full py-2 text-[10px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
      >
        {submitting ? <><Spinner /> Submitting…</> : "Generate Document →"}
      </button>

      <div className="text-[7px] text-pwc-text-muted leading-relaxed">
        Generation takes 3–10 minutes per document. The AI drafts each section, enforces NCA ECC control
        traceability, and runs QA gates. Results appear in the Policy Library tab when complete.
      </div>
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────

export default function GeneratePanel({
  onViewDoc,
}: {
  onViewDoc?: (docId: string) => void;
}) {
  const [jobs, setJobs] = useState<GenerateJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load job history on mount
  useEffect(() => {
    listGenerateJobs()
      .then(({ jobs: j }) => setJobs(j))
      .catch(() => {});
  }, []);

  // Poll active job
  useEffect(() => {
    if (!activeJobId) return;

    const poll = async () => {
      try {
        const job = await getGenerateJobStatus(activeJobId);
        setJobs((prev) => {
          const idx = prev.findIndex((j) => j.job_id === activeJobId);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = job;
            return next;
          }
          return [job, ...prev];
        });
        if (job.status === "completed" || job.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          setActiveJobId(null);
        }
      } catch (err: unknown) {
        // 404 = job lost (backend restarted) — mark failed and stop polling
        const status = (err as { status?: number })?.status;
        if (status === 404 || (err instanceof Error && err.message.includes("404"))) {
          setJobs((prev) => prev.map((j) =>
            j.job_id === activeJobId
              ? { ...j, status: "failed" as const, error: "Job lost — backend was restarted" }
              : j
          ));
          if (pollRef.current) clearInterval(pollRef.current);
          setActiveJobId(null);
        }
      }
    };

    poll();
    pollRef.current = setInterval(poll, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeJobId]);

  const handleJobStarted = useCallback((jobId: string) => {
    const newJob: GenerateJob = {
      job_id:    jobId,
      status:    "queued",
      doc_type:  "policy",
      topic:     "",
      org_name:  "",
      queued_at: new Date().toISOString(),
    };
    setJobs((prev) => [newJob, ...prev]);
    setActiveJobId(jobId);
  }, []);

  const runningJobs = jobs.filter((j) => j.status === "running" || j.status === "queued");

  return (
    <div className="flex w-full h-full overflow-hidden">

      {/* ── Left: form ───────────────────────────────────────────── */}
      <div className="w-[280px] shrink-0 flex flex-col border-r border-pwc-border bg-pwc-surface overflow-y-auto">
        <GenerateForm onJobStarted={handleJobStarted} />
      </div>

      {/* ── Right: job history ────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-pwc-border shrink-0">
          <div className="flex items-center gap-2">
            <div className="text-[10px] font-bold text-pwc-text">Generation Jobs</div>
            {runningJobs.length > 0 && (
              <div className="flex items-center gap-1 text-[8px] text-blue-600">
                <Spinner />
                <span>{runningJobs.length} active</span>
              </div>
            )}
            <span className="ml-auto text-[8px] text-pwc-text-muted">{jobs.length} total</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {jobs.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center px-8 text-pwc-text-dim">
              <div className="text-[32px] mb-3 opacity-20">◈</div>
              <div className="text-[11px] font-semibold mb-1">No Jobs Yet</div>
              <div className="text-[9px] leading-relaxed max-w-[220px]">
                Select a topic and organisation on the left to generate a policy or standard document.
              </div>
            </div>
          )}
          {jobs.map((job) => (
            <JobCard key={job.job_id} job={job} onViewDoc={onViewDoc} />
          ))}
        </div>

        {/* Pipeline legend */}
        <div className="px-3 py-2 border-t border-pwc-border bg-pwc-surface-raised shrink-0">
          <div className="text-[7px] text-pwc-text-dim space-y-0.5">
            <div className="font-bold text-pwc-text-dim uppercase mb-1">Generation Pipeline</div>
            {[
              ["Planner (o3)", "Decomposes topic into sections"],
              ["Retriever", "NCA primary + NIST supplementary (30/query)"],
              ["Reranker", "Cross-encoder top-20 per section"],
              ["Drafter (GPT-4o)", "Section-by-section with citation discipline"],
              ["QA Gates", "SHALL traceability + control coverage checks"],
              ["Renderer", "Outputs DOCX + traceability annex"],
            ].map(([step, desc]) => (
              <div key={step} className="flex gap-1.5">
                <span className="font-bold text-pwc-orange w-[100px] shrink-0">{step}</span>
                <span>{desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
