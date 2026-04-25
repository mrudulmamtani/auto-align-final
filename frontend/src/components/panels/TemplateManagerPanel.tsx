"use client";

/**
 * TemplateManagerPanel
 *
 * Org-template management and document conversion — migrated from AutoAlign.
 * Features:
 *  - Upload org template (logo, colors, DOCX template)
 *  - List and manage saved org templates
 *  - Convert any policy/standard to an org template with one click
 *  - Download converted DOCX
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { clsx } from "clsx";
import {
  fetchTemplates,
  fetchAutoAlignDocuments,
  uploadTemplate,
  deleteTemplate,
  convertDocument,
  getConvertedDocxUrl,
  getLogoUrl,
  type OrgTemplate,
  type AutoAlignDoc,
  type ConvertResult,
} from "@/lib/autoalignApi";

// ── Helpers ────────────────────────────────────────────────────────────────

function Spinner() {
  return <span className="inline-block w-3 h-3 border-2 border-pwc-orange border-t-transparent rounded-full animate-spin" />;
}

function ColorSwatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block w-3 h-3 rounded border border-pwc-border shrink-0"
      style={{ background: color }}
    />
  );
}

// ── Upload form ────────────────────────────────────────────────────────────

function UploadTemplateForm({ onSuccess }: { onSuccess: (t: OrgTemplate) => void }) {
  const [orgName, setOrgName]     = useState("");
  const [orgId, setOrgId]         = useState("");
  const [primaryColor, setPrimary] = useState("#1F497D");
  const [secondaryColor, setSecondary] = useState("#4472C4");
  const [fontFamily, setFont]     = useState("Calibri");
  const [headerRight, setHeader]  = useState("CONFIDENTIAL");
  const [logoFile, setLogo]       = useState<File | null>(null);
  const [templateFile, setTemplate] = useState<File | null>(null);
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const logoRef   = useRef<HTMLInputElement>(null);
  const docxRef   = useRef<HTMLInputElement>(null);

  const autoId = orgName.toLowerCase().replace(/[^\w]/g, "-").replace(/-+/g, "-").slice(0, 24);

  const handleSubmit = useCallback(async () => {
    if (!orgName.trim()) { setError("Organisation name required"); return; }
    setError(null);
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("org_name",        orgName.trim());
      fd.append("org_id",          (orgId.trim() || autoId) || "org");
      fd.append("primary_color",   primaryColor);
      fd.append("secondary_color", secondaryColor);
      fd.append("font_family",     fontFamily);
      fd.append("header_right",    headerRight);
      fd.append("footer_center",   "Page {page} of {total}");
      if (logoFile)    fd.append("logo",          logoFile,    logoFile.name);
      if (templateFile) fd.append("template_docx", templateFile, templateFile.name);

      const res = await uploadTemplate(fd);
      onSuccess({
        org_id: res.org_id,
        org_name: orgName.trim(),
        template_id: res.template_id,
        primary_color: primaryColor,
        has_logo: !!logoFile,
        created_at: new Date().toISOString(),
      });
      setOrgName(""); setOrgId(""); setLogo(null); setTemplate(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setSaving(false);
    }
  }, [orgName, orgId, primaryColor, secondaryColor, fontFamily, headerRight, logoFile, templateFile, autoId, onSuccess]);

  return (
    <div className="p-4 space-y-3">
      <div className="text-[10px] font-bold text-pwc-text mb-2">New Organisation Template</div>

      {/* Name + ID */}
      <div className="space-y-2">
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Organisation Name *</label>
          <input
            value={orgName}
            onChange={e => setOrgName(e.target.value)}
            placeholder="e.g. Acme Corp"
            className="w-full px-2 py-1 text-[10px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
          />
        </div>
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Short ID</label>
          <input
            value={orgId || autoId}
            onChange={e => setOrgId(e.target.value)}
            placeholder={autoId || "acme-corp"}
            className="w-full px-2 py-1 text-[10px] border border-pwc-border rounded bg-pwc-bg text-pwc-text-dim focus:border-pwc-orange outline-none font-mono"
          />
        </div>
      </div>

      {/* Colors */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Primary Color</label>
          <div className="flex items-center gap-1.5">
            <input type="color" value={primaryColor} onChange={e => setPrimary(e.target.value)}
              className="w-8 h-6 border border-pwc-border rounded cursor-pointer" />
            <span className="text-[9px] font-mono text-pwc-text-dim">{primaryColor}</span>
          </div>
        </div>
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Secondary Color</label>
          <div className="flex items-center gap-1.5">
            <input type="color" value={secondaryColor} onChange={e => setSecondary(e.target.value)}
              className="w-8 h-6 border border-pwc-border rounded cursor-pointer" />
            <span className="text-[9px] font-mono text-pwc-text-dim">{secondaryColor}</span>
          </div>
        </div>
      </div>

      {/* Font */}
      <div>
        <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Font Family</label>
        <select value={fontFamily} onChange={e => setFont(e.target.value)}
          className="w-full px-2 py-1 text-[10px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none">
          {["Calibri", "Arial", "Times New Roman", "Georgia", "Helvetica", "Roboto"].map(f => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </div>

      {/* Header text */}
      <div>
        <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Header Right Text</label>
        <input value={headerRight} onChange={e => setHeader(e.target.value)}
          className="w-full px-2 py-1 text-[10px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none" />
      </div>

      {/* File uploads */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Logo (PNG/SVG)</label>
          <input ref={logoRef} type="file" accept="image/*" className="hidden"
            onChange={e => setLogo(e.target.files?.[0] ?? null)} />
          <button onClick={() => logoRef.current?.click()}
            className="w-full px-2 py-1 text-[9px] border border-dashed border-pwc-border rounded hover:border-pwc-orange transition-colors text-pwc-text-dim">
            {logoFile ? `✓ ${logoFile.name}` : "Browse…"}
          </button>
        </div>
        <div>
          <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Template DOCX</label>
          <input ref={docxRef} type="file" accept=".docx" className="hidden"
            onChange={e => setTemplate(e.target.files?.[0] ?? null)} />
          <button onClick={() => docxRef.current?.click()}
            className="w-full px-2 py-1 text-[9px] border border-dashed border-pwc-border rounded hover:border-pwc-orange transition-colors text-pwc-text-dim">
            {templateFile ? `✓ ${templateFile.name}` : "Browse…"}
          </button>
        </div>
      </div>

      {error && <div className="text-[9px] text-red-500 font-bold">{error}</div>}

      <button
        onClick={handleSubmit}
        disabled={saving || !orgName.trim()}
        className="w-full px-3 py-1.5 text-[10px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
      >
        {saving ? <><Spinner /> Saving…</> : "Save Template"}
      </button>
    </div>
  );
}

// ── Convert panel ──────────────────────────────────────────────────────────

function ConvertPanel({ template, docs }: { template: OrgTemplate; docs: AutoAlignDoc[] }) {
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [converting, setConverting]       = useState(false);
  const [result, setResult]               = useState<ConvertResult | null>(null);
  const [error, setError]                 = useState<string | null>(null);

  const handleConvert = useCallback(async () => {
    if (!selectedDocId) return;
    setConverting(true);
    setError(null);
    setResult(null);
    try {
      const r = await convertDocument(selectedDocId, template.org_id);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Conversion failed");
    } finally {
      setConverting(false);
    }
  }, [selectedDocId, template.org_id]);

  return (
    <div className="p-4 space-y-3">
      <div className="text-[10px] font-bold text-pwc-text">Convert Document</div>
      <div className="text-[9px] text-pwc-text-dim">
        Apply <span className="font-bold text-pwc-orange">{template.org_name}</span> branding to a policy or standard.
      </div>

      <div>
        <label className="block text-[8px] font-bold text-pwc-text-dim mb-0.5 uppercase">Select Document</label>
        <select
          value={selectedDocId}
          onChange={e => { setSelectedDocId(e.target.value); setResult(null); }}
          className="w-full px-2 py-1 text-[10px] border border-pwc-border rounded bg-pwc-bg text-pwc-text focus:border-pwc-orange outline-none"
        >
          <option value="">— choose document —</option>
          {docs.map(d => (
            <option key={d.doc_id} value={d.doc_id}>
              {d.doc_id}: {d.title || d.doc_id} ({d.document_type})
            </option>
          ))}
        </select>
      </div>

      <button
        onClick={handleConvert}
        disabled={converting || !selectedDocId}
        className="w-full px-3 py-1.5 text-[10px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
      >
        {converting ? <><Spinner /> Converting…</> : "Convert to Template →"}
      </button>

      {error && <div className="text-[9px] text-red-500 font-bold">{error}</div>}

      {result && (
        <div className="border border-green-300 rounded-lg p-3 bg-green-50 space-y-2">
          <div className="text-[10px] font-bold text-green-700">Conversion Complete</div>
          <div className="text-[9px] text-green-600">{result.converted_docx}</div>
          <div className="text-[8px] text-pwc-text-dim">{result.control_locations} control location{result.control_locations !== 1 ? "s" : ""} mapped</div>
          <button
            onClick={() => window.open(getConvertedDocxUrl(result.converted_docx), "_blank")}
            className="flex items-center gap-1 px-2 py-1 text-[9px] font-bold bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
          >
            ↓ Download DOCX
          </button>
        </div>
      )}
    </div>
  );
}

// ── Template card ──────────────────────────────────────────────────────────

function TemplateCard({
  template,
  selected,
  onClick,
  onDelete,
}: {
  template: OrgTemplate;
  selected: boolean;
  onClick: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") onClick(); }}
      className={clsx(
        "w-full text-left px-3 py-2.5 border-b border-pwc-border/50 transition-colors cursor-pointer",
        selected ? "bg-orange-50 border-l-2 border-l-pwc-orange" : "hover:bg-pwc-surface-raised border-l-2 border-l-transparent"
      )}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <ColorSwatch color={template.primary_color} />
        <span className="text-[9px] font-bold text-pwc-text truncate flex-1">{template.org_name}</span>
        <button
          onClick={e => { e.stopPropagation(); onDelete(); }}
          className="text-[8px] text-pwc-text-muted hover:text-red-500 transition-colors shrink-0 px-1"
          title="Delete template"
        >
          ✕
        </button>
      </div>
      <div className="text-[8px] font-mono text-pwc-text-muted">{template.org_id}</div>
      {template.has_logo && (
        <div className="mt-1">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={getLogoUrl(template.org_id)}
            alt="logo"
            className="h-5 object-contain"
          />
        </div>
      )}
    </div>
  );
}

// ── Main Panel ─────────────────────────────────────────────────────────────

export default function TemplateManagerPanel() {
  const [templates, setTemplates]   = useState<OrgTemplate[]>([]);
  const [docs, setDocs]             = useState<AutoAlignDoc[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [{ templates: t }, { documents: d }] = await Promise.all([
        fetchTemplates(),
        fetchAutoAlignDocuments(),
      ]);
      setTemplates(t);
      setDocs(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cannot reach AutoAlign server");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDelete = useCallback(async (orgId: string) => {
    try {
      await deleteTemplate(orgId);
      setTemplates(prev => prev.filter(t => t.org_id !== orgId));
      if (selectedId === orgId) setSelectedId(null);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    }
  }, [selectedId]);

  const selectedTemplate = templates.find(t => t.org_id === selectedId) ?? null;

  return (
    <div className="flex w-full h-full overflow-hidden">

      {/* ── Left: template library ──────────────────────────────────── */}
      <div className="w-[220px] shrink-0 flex flex-col border-r border-pwc-border bg-pwc-surface overflow-hidden">
        <div className="px-3 py-2 border-b border-pwc-border shrink-0">
          <div className="text-[10px] font-bold text-pwc-text mb-1.5">Org Templates</div>
          <button
            onClick={() => { setShowUpload(true); setSelectedId(null); }}
            className="w-full px-2 py-1 text-[9px] font-bold bg-pwc-orange text-white rounded hover:bg-pwc-orange-hover transition-colors"
          >
            + New Template
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <div className="flex items-center gap-2 px-3 py-4 text-[9px] text-pwc-text-dim">
              <Spinner /> Loading…
            </div>
          )}
          {error && (
            <div className="px-3 py-3 text-[9px] text-red-500">
              {error}<br/>
              <span className="text-[8px] text-pwc-text-muted">Start: python run_converter.py</span>
            </div>
          )}
          {!loading && !error && templates.length === 0 && (
            <div className="px-3 py-4 text-[9px] text-pwc-text-muted">
              No templates yet. Create one to get started.
            </div>
          )}
          {!loading && !error && templates.map(t => (
            <TemplateCard
              key={t.org_id}
              template={t}
              selected={selectedId === t.org_id}
              onClick={() => { setSelectedId(t.org_id); setShowUpload(false); }}
              onDelete={() => handleDelete(t.org_id)}
            />
          ))}
        </div>

        {!loading && !error && (
          <div className="px-3 py-2 border-t border-pwc-border shrink-0 text-[8px] text-pwc-text-muted">
            {templates.length} template{templates.length !== 1 ? "s" : ""} · {docs.length} documents
          </div>
        )}
      </div>

      {/* ── Right: detail / form ─────────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {showUpload ? (
          <UploadTemplateForm
            onSuccess={t => {
              setTemplates(prev => [t, ...prev]);
              setSelectedId(t.org_id);
              setShowUpload(false);
            }}
          />
        ) : selectedTemplate ? (
          <div className="space-y-0">
            {/* Template header */}
            <div className="px-4 py-3 border-b border-pwc-border">
              <div className="flex items-center gap-2 mb-1">
                <ColorSwatch color={selectedTemplate.primary_color} />
                <span className="text-[12px] font-bold text-pwc-text">{selectedTemplate.org_name}</span>
              </div>
              <div className="text-[9px] font-mono text-pwc-text-muted mb-2">{selectedTemplate.org_id} · {selectedTemplate.template_id}</div>
              {selectedTemplate.has_logo && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={getLogoUrl(selectedTemplate.org_id)} alt="logo" className="h-8 object-contain" />
              )}
            </div>
            {/* Convert section */}
            <ConvertPanel template={selectedTemplate} docs={docs} />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 text-pwc-text-dim">
            <div className="text-[32px] mb-3 opacity-20">◫</div>
            <div className="text-[11px] font-semibold mb-1">Select a Template</div>
            <div className="text-[9px] leading-relaxed max-w-[220px]">
              Choose an org template from the list to convert policies and standards, or click <strong className="text-pwc-orange">+ New Template</strong> to create one.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
