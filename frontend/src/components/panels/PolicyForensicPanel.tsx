"use client";

/**
 * PolicyForensicPanel
 *
 * Forensic reader for AutoAlign-generated policy and standard DOCX files.
 * Shows:
 *  - Left: document library (policies + standards) with QA status
 *  - Right: forensic map reader — sections table, control citations table
 *  - "Open in Word" button to download/edit the DOCX
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { clsx } from "clsx";
import {
  fetchAutoAlignDocuments,
  fetchForensicMap,
  triggerExtraction,
  getSourceDocxUrl,
  getConvertedDocxUrl,
  getDocumentHtmlUrl,
  fetchComments,
  addComment,
  deleteComment,
  type AutoAlignDoc,
  type ForensicMap,
  type ControlLocation,
  type DocComment,
} from "@/lib/autoalignApi";

const COMMENT_COLORS = ["#d04a02", "#0070d1", "#107c10", "#8764b8", "#d13438"];

// ── Framework → standard name mapping ─────────────────────────────────────
// AutoAlign stores framework as "NCA_ECC"; ForensicPDFViewer uses "NCA ECC"
const FRAMEWORK_TO_STANDARD: Record<string, string> = {
  NCA_ECC:    "NCA ECC",
  NCA_OTC:    "NCA OTC",
  NCA_TCC:    "NCA TCC",
  NCA_CSCC:   "NCA CSCC",
  NCA_CCC:    "NCA CCC",
  NCA_DCC:    "NCA DCC",
  NCA_OSMACC: "NCA OSMACC",
  NCA_NCS:    "NCA NCS",
  UAE_IA:     "UAE IAS",
  UAE_IAS:    "UAE IAS",
  NIST_800_53:"NIST CSF",
  NIST_CSF:   "NIST CSF",
  ISO_27001:  "ISO 27001",
  GDPR:       "GDPR",
  PCI_DSS:    "PCI DSS",
  SOC_2:      "SOC 2",
};

// standardsEngine prefixes NCA control IDs with the framework short code
// e.g. "1-3-1" from AutoAlign → "ECC-1-3-1" in standardsEngine
const FRAMEWORK_TO_PREFIX: Record<string, string> = {
  NCA_ECC:    "ECC",
  NCA_OTC:    "OTC",
  NCA_TCC:    "TCC",
  NCA_CSCC:   "CSCC",
  NCA_CCC:    "CCC",
  NCA_DCC:    "DCC",
  NCA_OSMACC: "OSMACC",
  NCA_NCS:    "NCS",
};

function frameworkToStandard(framework: string): string {
  return FRAMEWORK_TO_STANDARD[framework]
    ?? FRAMEWORK_TO_STANDARD[framework.toUpperCase()]
    ?? framework.replace(/_/g, " ");
}

/** Convert AutoAlign bare control ID to standardsEngine prefixed format */
function toStdControlId(framework: string, controlId: string): string {
  const prefix = FRAMEWORK_TO_PREFIX[framework] ?? FRAMEWORK_TO_PREFIX[framework.toUpperCase()];
  if (prefix && !controlId.startsWith(prefix)) return `${prefix}-${controlId}`;
  return controlId;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function Badge({
  children,
  variant = "neutral",
}: {
  children: React.ReactNode;
  variant?: "pass" | "fail" | "policy" | "standard" | "neutral" | "orange";
}) {
  const cls = {
    pass:     "bg-green-100 text-green-700 border-green-200",
    fail:     "bg-red-100 text-red-700 border-red-200",
    policy:   "bg-orange-100 text-pwc-orange border-orange-200",
    standard: "bg-blue-100 text-blue-700 border-blue-200",
    neutral:  "bg-pwc-bg text-pwc-text-dim border-pwc-border",
    orange:   "bg-pwc-orange text-white border-pwc-orange",
  }[variant];
  return (
    <span className={clsx("inline-flex items-center px-1.5 py-0.5 text-[8px] font-bold border rounded uppercase tracking-wide", cls)}>
      {children}
    </span>
  );
}

function Spinner() {
  return (
    <span className="inline-block w-3 h-3 border-2 border-pwc-orange border-t-transparent rounded-full animate-spin" />
  );
}

// ── Section location table ─────────────────────────────────────────────────

function SectionsTable({ sections }: { sections: ForensicMap["section_locations"] }) {
  if (!sections.length) {
    return <div className="text-[10px] text-pwc-text-muted px-3 py-4">No sections extracted.</div>;
  }
  return (
    <table className="w-full text-[9px] border-collapse">
      <thead>
        <tr className="bg-pwc-surface-raised">
          <th className="text-left px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">§</th>
          <th className="text-left px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">Title</th>
          <th className="text-center px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">Src Pg</th>
          <th className="text-center px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">Conv Pg</th>
          <th className="text-center px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">Para</th>
          <th className="text-center px-2 py-1.5 font-bold text-pwc-text-dim border-b border-pwc-border">Lvl</th>
        </tr>
      </thead>
      <tbody>
        {sections.map((s, i) => (
          <tr key={i} className="hover:bg-pwc-surface-raised transition-colors">
            <td className="px-2 py-1 font-mono text-pwc-orange font-bold border-b border-pwc-border/50">{s.section_number}</td>
            <td className="px-2 py-1 text-pwc-text border-b border-pwc-border/50 max-w-[200px] truncate">{s.title}</td>
            <td className="px-2 py-1 text-center font-mono text-pwc-text border-b border-pwc-border/50">{s.page_number ?? "—"}</td>
            <td className="px-2 py-1 text-center font-mono text-pwc-text-dim border-b border-pwc-border/50">{s.converted_page_number ?? "—"}</td>
            <td className="px-2 py-1 text-center font-mono text-pwc-text-dim border-b border-pwc-border/50">{s.paragraph_index ?? "—"}</td>
            <td className="px-2 py-1 text-center text-pwc-text-muted border-b border-pwc-border/50">{s.heading_level}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Control location table ─────────────────────────────────────────────────

function ControlsTable({
  controls,
  onControlClick,
}: {
  controls: ControlLocation[];
  onControlClick?: (standardName: string, controlId: string) => void;
}) {
  if (!controls.length) {
    return <div className="text-[10px] text-pwc-text-muted px-3 py-4">No control citations extracted.</div>;
  }

  // Group by element_ref
  const grouped: Record<string, ControlLocation[]> = {};
  for (const c of controls) {
    if (!grouped[c.element_ref]) grouped[c.element_ref] = [];
    grouped[c.element_ref].push(c);
  }

  const confColor = (conf: number) =>
    conf >= 0.95 ? "text-green-600" : conf >= 0.75 ? "text-pwc-orange" : "text-red-500";

  return (
    <div className="space-y-0">
      {Object.entries(grouped).map(([elemRef, items]) => (
        <div key={elemRef}>
          <div className="flex items-center gap-2 px-3 py-1 bg-pwc-surface-raised border-b border-pwc-border sticky top-0">
            <span className="text-[8px] font-bold text-pwc-orange uppercase tracking-wide">{elemRef}</span>
            <span className="text-[7px] text-pwc-text-muted">{items.length} control{items.length !== 1 ? "s" : ""}</span>
            {onControlClick && (
              <span className="ml-auto text-[7px] text-pwc-text-muted italic">click ID → open in PDF reader</span>
            )}
          </div>
          <table className="w-full text-[9px] border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-1 font-bold text-pwc-text-dim w-[110px]">Control ID</th>
                <th className="text-left px-2 py-1 font-bold text-pwc-text-dim">Framework</th>
                <th className="text-center px-2 py-1 font-bold text-pwc-text-dim">Src Pg</th>
                <th className="text-center px-2 py-1 font-bold text-pwc-text-dim">Conv Pg</th>
                <th className="text-center px-2 py-1 font-bold text-pwc-text-dim">Para</th>
                <th className="text-center px-2 py-1 font-bold text-pwc-text-dim">Conf</th>
                <th className="text-left px-2 py-1 font-bold text-pwc-text-dim">Method</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c, i) => (
                <tr key={i} className="hover:bg-pwc-surface-raised border-b border-pwc-border/30 transition-colors">
                  <td className="px-3 py-1">
                    <button
                      onClick={() => onControlClick?.(frameworkToStandard(c.framework), toStdControlId(c.framework, c.control_id))}
                      className={clsx(
                        "font-mono font-bold text-pwc-text bg-orange-50 border border-orange-200 rounded px-1 text-left",
                        onControlClick && "hover:bg-pwc-orange hover:text-white hover:border-pwc-orange cursor-pointer transition-colors"
                      )}
                      title={`Open ${c.control_id} in PDF reader (${frameworkToStandard(c.framework)})`}
                    >
                      {c.control_id}
                    </button>
                  </td>
                  <td className="px-2 py-1 text-[8px] text-pwc-text-dim font-mono">
                    {frameworkToStandard(c.framework)}
                  </td>
                  <td className="px-2 py-1 text-center font-mono text-pwc-text">{c.page_number ?? "—"}</td>
                  <td className="px-2 py-1 text-center font-mono text-pwc-text-dim">{c.converted_page_number ?? "—"}</td>
                  <td className="px-2 py-1 text-center font-mono text-pwc-text-dim">{c.paragraph_index ?? "—"}</td>
                  <td className={clsx("px-2 py-1 text-center font-mono font-bold", confColor(c.extraction_confidence))}>
                    {Math.round(c.extraction_confidence * 100)}%
                  </td>
                  <td className="px-2 py-1 text-[7px] text-pwc-text-muted capitalize">{c.extraction_method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

// ── Document viewer with Word-style comments ───────────────────────────────
// Uses iframe + srcDoc for CSS isolation, postMessage for selection bridging.

function applyHighlights(html: string, comments: DocComment[]): string {
  let result = html;
  for (const c of comments) {
    if (!c.selected_text) continue;
    const esc   = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const color = c.color || "#d04a02";
    const mark  = (inner: string) =>
      `<mark style="background:${color}28;border-bottom:2px solid ${color};padding:0 1px;border-radius:2px" ` +
      `title="${c.comment.replace(/"/g, "&quot;")}">${inner}</mark>`;
    if (c.context_before) {
      result = result.replace(
        new RegExp(`(${esc(c.context_before)})(${esc(c.selected_text)})`),
        (_, before, sel) => before + mark(sel),
      );
    } else {
      let replaced = false;
      result = result.replace(new RegExp(esc(c.selected_text), "g"), (m) => {
        if (replaced) return m;
        replaced = true;
        return mark(m);
      });
    }
  }
  return result;
}

// Script injected into every srcdoc: detects selection and sends postMessage to parent.
const SELECTION_SCRIPT = `
<script>
(function(){
  document.addEventListener('mouseup', function() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      parent.postMessage({type:'sel-clear'}, '*'); return;
    }
    var text = sel.toString().trim();
    var range = sel.getRangeAt(0);
    var node  = range.startContainer;
    var full  = node.textContent || '';
    var s = range.startOffset, e = range.endOffset;
    parent.postMessage({
      type: 'sel',
      text: text,
      before: full.slice(Math.max(0, s - 20), s),
      after:  full.slice(e, e + 20)
    }, '*');
  });
})();
</script>`;

function DocumentCommentViewer({ doc }: { doc: AutoAlignDoc }) {
  const [rawHtml, setRawHtml]       = useState("");
  const [loading, setLoading]       = useState(true);
  const [comments, setComments]     = useState<DocComment[]>([]);
  const [pending, setPending]       = useState<{ text: string; before: string; after: string } | null>(null);
  const [commentText, setCommentText] = useState("");
  const [colorIdx, setColorIdx]     = useState(0);
  const [saving, setSaving]         = useState(false);

  // Fetch raw HTML once per doc
  useEffect(() => {
    setLoading(true);
    setRawHtml("");
    setPending(null);
    fetch(getDocumentHtmlUrl(doc.doc_id))
      .then((r) => r.text())
      .then(setRawHtml)
      .catch(() => setRawHtml("<p style='padding:16px;color:#888'>Failed to load document.</p>"))
      .finally(() => setLoading(false));
  }, [doc.doc_id]);

  // Fetch persisted comments
  useEffect(() => {
    fetchComments(doc.doc_id)
      .then(({ comments: c }) => setComments(c))
      .catch(() => {});
  }, [doc.doc_id]);

  // Build srcdoc: raw HTML + highlights + selection bridge script
  const srcdoc = useMemo(() => {
    if (!rawHtml) return "";
    const highlighted = applyHighlights(rawHtml, comments);
    // Inject before </body> — fall back to appending if </body> absent
    return highlighted.includes("</body>")
      ? highlighted.replace("</body>", SELECTION_SCRIPT + "</body>")
      : highlighted + SELECTION_SCRIPT;
  }, [rawHtml, comments]);

  // Listen for postMessage from iframe
  useEffect(() => {
    const handler = (ev: MessageEvent) => {
      if (ev.data?.type === "sel" && ev.data.text) {
        setPending({ text: ev.data.text, before: ev.data.before ?? "", after: ev.data.after ?? "" });
      } else if (ev.data?.type === "sel-clear") {
        setPending(null);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const handlePost = useCallback(async () => {
    if (!pending || !commentText.trim()) return;
    setSaving(true);
    try {
      const color = COMMENT_COLORS[colorIdx % COMMENT_COLORS.length];
      const nc = await addComment(doc.doc_id, {
        selected_text:  pending.text,
        context_before: pending.before,
        context_after:  pending.after,
        comment:        commentText.trim(),
        color,
      });
      setComments((prev) => [...prev, nc]);
      setCommentText("");
      setColorIdx((i) => i + 1);
      setPending(null);
    } catch { /* ignore */ } finally { setSaving(false); }
  }, [pending, commentText, colorIdx, doc.doc_id]);

  const handleDelete = useCallback(async (id: string) => {
    await deleteComment(doc.doc_id, id).catch(() => {});
    setComments((prev) => prev.filter((c) => c.id !== id));
  }, [doc.doc_id]);

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Document iframe (CSS-isolated) ─────────────────────────── */}
      <div className="flex-1 overflow-hidden relative">
        {loading && (
          <div className="flex items-center gap-2 p-6 text-[10px] text-pwc-text-dim absolute inset-0">
            <Spinner /> Loading document…
          </div>
        )}
        {srcdoc && (
          <iframe
            key={doc.doc_id}
            srcDoc={srcdoc}
            className="w-full h-full border-0"
            sandbox="allow-scripts"
            title={`${doc.doc_id} document`}
          />
        )}
      </div>

      {/* ── Comments sidebar ────────────────────────────────────────── */}
      <div className="w-52 shrink-0 border-l border-pwc-border bg-pwc-surface flex flex-col overflow-hidden">
        <div className="px-2.5 py-2 border-b border-pwc-border shrink-0">
          <div className="text-[9px] font-bold text-pwc-text">
            Comments{comments.length > 0 && <span className="text-pwc-orange ml-1">({comments.length})</span>}
          </div>
          <div className="text-[7px] text-pwc-text-muted mt-0.5">Select text in the document to annotate</div>
        </div>

        {/* Pending comment input — shown when user selects text */}
        {pending && (
          <div className="px-2.5 py-2 border-b border-pwc-border bg-orange-50 shrink-0">
            <div className="text-[8px] font-bold text-pwc-orange mb-1 uppercase tracking-wide">New Comment</div>
            <div className="text-[8px] text-pwc-text-muted italic mb-1.5 truncate">
              &ldquo;{pending.text.slice(0, 50)}{pending.text.length > 50 ? "…" : ""}&rdquo;
            </div>
            <textarea
              autoFocus
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handlePost(); }}
              placeholder="Your comment… (Ctrl+Enter to post)"
              rows={3}
              className="w-full px-2 py-1 text-[9px] border border-pwc-border rounded bg-white text-pwc-text focus:border-pwc-orange outline-none resize-none"
            />
            <div className="flex gap-1.5 mt-1.5 justify-end">
              <button
                onClick={() => { setPending(null); setCommentText(""); }}
                className="px-2 py-1 text-[8px] font-bold border border-pwc-border rounded text-pwc-text-dim hover:border-pwc-orange transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handlePost}
                disabled={!commentText.trim() || saving}
                className="px-2 py-1 text-[8px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors"
              >
                {saving ? "Saving…" : "Post"}
              </button>
            </div>
          </div>
        )}

        {/* Comment list */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {comments.length === 0 ? (
            <div className="px-3 py-6 text-[9px] text-pwc-text-muted text-center leading-relaxed">
              No comments yet.<br />Select any text to annotate.
            </div>
          ) : (
            comments.map((c) => (
              <div
                key={c.id}
                className="px-2.5 py-2 border-b border-pwc-border/50 group"
                style={{ borderLeft: `3px solid ${c.color || "#d04a02"}` }}
              >
                <div className="text-[8px] text-pwc-text-muted italic truncate mb-1">
                  &ldquo;{c.selected_text.slice(0, 40)}{c.selected_text.length > 40 ? "…" : ""}&rdquo;
                </div>
                <div className="text-[9px] text-pwc-text leading-snug break-words">{c.comment}</div>
                <div className="flex items-center justify-between mt-1.5">
                  <span className="text-[7px] text-pwc-text-muted">
                    {c.author} · {new Date(c.created_at).toLocaleDateString()}
                  </span>
                  <button
                    onClick={() => handleDelete(c.id)}
                    className="text-[8px] text-red-400 opacity-0 group-hover:opacity-100 hover:text-red-600 transition-opacity ml-1"
                    title="Delete comment"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// ── Document detail pane ───────────────────────────────────────────────────

type DetailTab = "document" | "sections" | "controls";

function DocDetail({
  doc,
  fmap,
  loading,
  error,
  onExtract,
  extracting,
  onControlClick,
}: {
  doc: AutoAlignDoc;
  fmap: ForensicMap | null;
  loading: boolean;
  error: string | null;
  onExtract: () => void;
  extracting: boolean;
  onControlClick?: (standardName: string, controlId: string) => void;
}) {
  const [tab, setTab] = useState<DetailTab>("document");

  const openDocx = () => window.open(getSourceDocxUrl(doc.doc_id), "_blank");
  const openConverted = () => {
    if (fmap?.converted_docx) {
      const filename = fmap.converted_docx.split(/[\\/]/).pop()!;
      window.open(getConvertedDocxUrl(filename), "_blank");
    }
  };
  const openTraceability = () => window.open(getSourceDocxUrl(doc.doc_id, "traceability"), "_blank");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Doc header */}
      <div className="px-3 py-2.5 border-b border-pwc-border shrink-0 space-y-2">
        <div className="flex items-start gap-2 flex-wrap">
          <Badge variant={doc.document_type === "policy" ? "policy" : doc.document_type === "standard" ? "standard" : "neutral"}>
            {doc.document_type}
          </Badge>
          <Badge variant="orange">{doc.doc_id}</Badge>
          <Badge variant={doc.qa_passed ? "pass" : "fail"}>
            {doc.qa_passed ? "QA PASS" : "QA FAIL"}
          </Badge>
          {fmap && (
            <Badge variant="neutral">
              {fmap.estimated_pages ?? "?"} pg · {fmap.total_paragraphs ?? "?"} para
            </Badge>
          )}
        </div>

        <div className="text-[11px] font-semibold text-pwc-text leading-tight">{doc.title || doc.doc_id}</div>

        <div className="flex items-center gap-2 text-[8px] text-pwc-text-dim flex-wrap">
          <span>v{doc.version}</span>
          <span className="text-pwc-border">·</span>
          <span>{doc.shall_count} SHALL</span>
          <span className="text-pwc-border">·</span>
          <span className={doc.traced_count === doc.shall_count ? "text-green-600 font-bold" : "text-red-500 font-bold"}>
            {doc.traced_count}/{doc.shall_count} traced
          </span>
          {fmap && (
            <>
              <span className="text-pwc-border">·</span>
              <span>{fmap.control_locations.length} citation{fmap.control_locations.length !== 1 ? "s" : ""}</span>
              <span className="text-pwc-border">·</span>
              <span>{fmap.section_locations.length} sections</span>
            </>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            onClick={openDocx}
            className="flex items-center gap-1 px-2 py-1 text-[8px] font-bold border border-pwc-border rounded hover:border-pwc-orange hover:text-pwc-orange transition-colors"
          >
            ↓ Open in Word
          </button>
          <button
            onClick={openTraceability}
            className="flex items-center gap-1 px-2 py-1 text-[8px] font-bold border border-pwc-border rounded hover:border-pwc-orange hover:text-pwc-orange transition-colors"
          >
            ↓ Traceability
          </button>
          {fmap?.converted_docx && (
            <button
              onClick={openConverted}
              className="flex items-center gap-1 px-2 py-1 text-[8px] font-bold border border-green-300 text-green-700 rounded hover:bg-green-50 transition-colors"
            >
              ↓ Converted DOCX
            </button>
          )}
          {!doc.has_forensic_map && (
            <button
              onClick={onExtract}
              disabled={extracting}
              className="flex items-center gap-1.5 px-2 py-1 text-[8px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors"
            >
              {extracting ? <><Spinner /> Extracting…</> : "⟲ Extract Forensics"}
            </button>
          )}
        </div>
      </div>

      {/* Loading / error / no map */}
      {loading && (
        <div className="flex items-center gap-2 px-3 py-6 text-[10px] text-pwc-text-dim">
          <Spinner /> Loading forensic map…
        </div>
      )}
      {error && !loading && (
        <div className="px-3 py-4 space-y-2">
          <div className="text-[9px] text-red-500 font-bold">{error}</div>
          <button
            onClick={onExtract}
            disabled={extracting}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[9px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors"
          >
            {extracting ? <><Spinner /> Extracting…</> : "⟲ Run Forensic Extraction"}
          </button>
        </div>
      )}

      {/* Tab bar — always show document tab, forensic tabs only when fmap exists */}
      {!loading && (
        <div className="flex items-center gap-0.5 px-3 py-1.5 border-b border-pwc-border bg-pwc-surface shrink-0">
          <button
            onClick={() => setTab("document")}
            className={clsx(
              "px-2.5 py-0.5 text-[9px] font-semibold rounded border transition-colors",
              tab === "document"
                ? "bg-pwc-orange text-white border-pwc-orange"
                : "text-pwc-text-dim border-transparent hover:border-pwc-border"
            )}
          >
            ☰ Document
          </button>
          {fmap && (["controls", "sections"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={clsx(
                "px-2.5 py-0.5 text-[9px] font-semibold rounded border transition-colors",
                tab === t
                  ? "bg-pwc-orange text-white border-pwc-orange"
                  : "text-pwc-text-dim border-transparent hover:border-pwc-border"
              )}
            >
              {t === "controls" ? `⊕ Controls (${fmap.control_locations.length})` : `§ Sections (${fmap.section_locations.length})`}
            </button>
          ))}
          {fmap && (
            <span className="ml-auto text-[8px] text-pwc-text-muted">
              {fmap.forensic_method} · {fmap.forensic_extracted_at ? new Date(fmap.forensic_extracted_at).toLocaleDateString() : "—"}
            </span>
          )}
        </div>
      )}

      {/* Tab content */}
      {!loading && (
        <div className="flex-1 overflow-hidden min-h-0">
          {tab === "document" && (
            <DocumentCommentViewer doc={doc} />
          )}
          {tab === "sections" && fmap && (
            <div className="overflow-y-auto h-full">
              <SectionsTable sections={fmap.section_locations} />
            </div>
          )}
          {tab === "controls" && fmap && (
            <div className="overflow-y-auto h-full">
              <ControlsTable
                controls={fmap.control_locations}
                onControlClick={onControlClick}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Document list item ─────────────────────────────────────────────────────

function DocListItem({
  doc,
  selected,
  onClick,
}: {
  doc: AutoAlignDoc;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left px-2.5 py-2 border-b border-pwc-border/50 transition-colors",
        selected ? "bg-orange-50 border-l-2 border-l-pwc-orange" : "hover:bg-pwc-surface-raised border-l-2 border-l-transparent"
      )}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="text-[8px] font-mono font-bold text-pwc-orange">{doc.doc_id}</span>
        <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", doc.qa_passed ? "bg-green-500" : "bg-red-400")} />
        {doc.has_forensic_map && (
          <span className="text-[7px] text-pwc-text-muted ml-auto">⊕ {doc.forensic_controls}</span>
        )}
      </div>
      <div className="text-[9px] text-pwc-text leading-tight truncate">{doc.title || "—"}</div>
    </button>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────

export default function PolicyForensicPanel({
  onCoverageChange,
  onControlClick,
}: {
  onCoverageChange?: (ids: Set<string>) => void;
  onControlClick?: (standardName: string, controlId: string) => void;
}) {
  const [docs, setDocs] = useState<AutoAlignDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fmap, setFmap] = useState<ForensicMap | null>(null);
  const [fmapLoading, setFmapLoading] = useState(false);
  const [fmapError, setFmapError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);

  const [filterType, setFilterType] = useState<"all" | "policy" | "standard" | "procedure">("all");

  // Load document list
  useEffect(() => {
    setDocsLoading(true);
    fetchAutoAlignDocuments()
      .then(({ documents }) => {
        setDocs(documents);

        // Build coverage set for KG highlight
        if (onCoverageChange) {
          const ids = new Set<string>();
          documents.forEach((d) => {
            // We'll load this lazily — just mark initially
          });
          void Promise.all(
            documents.filter((d) => d.has_forensic_map).map(async (d) => {
              try {
                const fm = await fetchForensicMap(d.doc_id);
                fm.control_locations.forEach((cl) => ids.add(cl.control_id));
              } catch { /* skip */ }
            })
          ).then(() => onCoverageChange(ids));
        }
      })
      .catch((e) => setDocsError(e.message))
      .finally(() => setDocsLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load forensic map when selection changes
  useEffect(() => {
    if (!selectedId) { setFmap(null); return; }
    setFmapLoading(true);
    setFmapError(null);
    setFmap(null);
    fetchForensicMap(selectedId)
      .then(setFmap)
      .catch((e) => setFmapError(e.message))
      .finally(() => setFmapLoading(false));
  }, [selectedId]);

  const handleExtract = useCallback(async () => {
    if (!selectedId) return;
    setExtracting(true);
    try {
      await triggerExtraction(selectedId);
      // Reload forensic map
      const fm = await fetchForensicMap(selectedId);
      setFmap(fm);
      setFmapError(null);
      // Update doc list
      const { documents } = await fetchAutoAlignDocuments();
      setDocs(documents);
    } catch (e) {
      setFmapError(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }, [selectedId]);

  const selectedDoc = docs.find((d) => d.doc_id === selectedId) ?? null;
  const policies   = docs.filter((d) => d.document_type === "policy");
  const standards  = docs.filter((d) => d.document_type === "standard");
  const procedures = docs.filter((d) => d.document_type === "procedure");
  const filtered   = filterType === "all" ? docs
    : filterType === "policy" ? policies
    : filterType === "standard" ? standards
    : procedures;

  return (
    <div className="flex w-full h-full overflow-hidden">

      {/* ── Left: document library ──────────────────────────────────── */}
      <div className="w-[200px] shrink-0 flex flex-col border-r border-pwc-border bg-pwc-surface overflow-hidden">
        {/* Header */}
        <div className="px-3 py-2 border-b border-pwc-border shrink-0">
          <div className="text-[10px] font-bold text-pwc-text mb-1.5">Policy Library</div>
          <div className="flex gap-1 flex-wrap">
            {([
              { key: "all",       label: `All (${docs.length})` },
              { key: "policy",    label: `POL (${policies.length})` },
              { key: "standard",  label: `STD (${standards.length})` },
              { key: "procedure", label: `PRC (${procedures.length})` },
            ] as { key: "all" | "policy" | "standard" | "procedure"; label: string }[]).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setFilterType(key)}
                className={clsx(
                  "px-1.5 py-0.5 text-[7px] font-bold border rounded uppercase transition-colors",
                  filterType === key
                    ? "bg-pwc-orange text-white border-pwc-orange"
                    : "text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {docsLoading && (
            <div className="flex items-center gap-2 px-3 py-4 text-[9px] text-pwc-text-dim">
              <Spinner /> Loading…
            </div>
          )}
          {docsError && (
            <div className="px-3 py-3 text-[9px] text-red-500">
              Cannot reach AutoAlign server.<br/>
              <span className="text-[8px] text-pwc-text-muted">Start with: python run_converter.py</span>
            </div>
          )}
          {!docsLoading && !docsError && filtered.map((doc) => (
            <DocListItem
              key={doc.doc_id}
              doc={doc}
              selected={selectedId === doc.doc_id}
              onClick={() => setSelectedId(doc.doc_id)}
            />
          ))}
          {!docsLoading && !docsError && filtered.length === 0 && (
            <div className="px-3 py-4 text-[9px] text-pwc-text-muted">No documents found.</div>
          )}
        </div>

        {/* Footer stats */}
        {!docsLoading && !docsError && (
          <div className="px-3 py-2 border-t border-pwc-border bg-pwc-surface-raised shrink-0">
            <div className="text-[8px] text-pwc-text-dim space-y-0.5">
              <div className="flex justify-between">
                <span>Policies</span>
                <span className="font-bold text-pwc-orange">{policies.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Standards</span>
                <span className="font-bold text-pwc-orange">{standards.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Procedures</span>
                <span className="font-bold text-pwc-orange">{procedures.length}</span>
              </div>
              <div className="flex justify-between">
                <span>With forensic map</span>
                <span className="font-bold text-green-600">{docs.filter((d) => d.has_forensic_map).length}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Right: detail / forensic reader ────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-hidden">
        {!selectedDoc ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 text-pwc-text-dim">
            <div className="text-[32px] mb-3 opacity-20">⊕</div>
            <div className="text-[11px] font-semibold mb-1">Select a Document</div>
            <div className="text-[9px] leading-relaxed max-w-[220px]">
              Choose a policy or standard from the library to view its forensic control map — page numbers, paragraph indices, and section locations.
            </div>
          </div>
        ) : (
          <DocDetail
            doc={selectedDoc}
            fmap={fmap}
            loading={fmapLoading}
            error={fmapError}
            onExtract={handleExtract}
            extracting={extracting}
            onControlClick={onControlClick}
          />
        )}
      </div>
    </div>
  );
}
