"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { clsx } from "clsx";
import { getAllControls, getLinkedControls } from "@/lib/standardsEngine";

// ── pdfjs via webpackIgnore ────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _pdfjsLib: any = null;
async function getPdfJs() {
  if (_pdfjsLib) return _pdfjsLib;
  // @ts-ignore
  const lib = await import(/* webpackIgnore: true */ "/pdf.mjs");
  lib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
  _pdfjsLib = lib;
  return lib;
}

const RENDER_SCALE = 1.5;

const FILE_MAP: Record<string, string> = {
  "UAE IAS":    "/assets/docs/uae_ias.pdf",
  "NCA OTC":    "/assets/docs/nca_otc.pdf",
  "NCA TCC":    "/assets/docs/nca_tcc.pdf",
  "NCA CSCC":   "/assets/docs/nca_cscc.pdf",
  "NCA ECC":    "/assets/docs/nca_ecc.pdf",
  "NCA CCC":    "/assets/docs/nca_ccc.pdf",
  "NCA DCC":    "/assets/docs/nca_dcc.pdf",
  "NCA OSMACC": "/assets/docs/nca_osmacc.pdf",
  "NCA NCS":    "/assets/docs/nca_ncs.pdf",
  "GDPR":       "/assets/docs/gdpr.pdf",
  "NIST CSF":   "/assets/docs/nist_csf.pdf",
  "PCI DSS":    "/assets/docs/pci_dss.pdf",
};

// ── Types ──────────────────────────────────────────────────────────────────
interface ControlEntry {
  standardName: string;
  domainName: string;
  controlId: string;
  text: string;
  obligation: string;
  page: number;
  filePath: string;
}

function buildControls(): ControlEntry[] {
  return getAllControls().map((c) => ({
    standardName: c.standardName,
    domainName: c.domainName,
    controlId: c.id,
    text: c.text,
    obligation: c.obligation,
    page: c.pdf_ref.page,
    filePath: FILE_MAP[c.standardName] ?? "",
  }));
}

/** Build a synthetic ControlEntry for a generated document opened by URL. */
function makeGeneratedDocEntry(state: ForensicModalState): ControlEntry {
  return {
    standardName: state.standardName,
    domainName: "",
    controlId: state.controlId,
    text: state.controlText ?? state.controlId,
    obligation: "shall",
    page: 1,
    filePath: state.pdfUrl!,
  };
}

// ── Text-based bbox finder ─────────────────────────────────────────────────
interface CssBbox {
  left: string;
  top: string;
  width: string;
  height: string;
  scrollFraction: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function locateControlInPage(pdfDoc: any, pageNumber: number, controlId: string, controlText: string): Promise<CssBbox | null> {
  try {
    const page = await pdfDoc.getPage(pageNumber);
    const viewport = page.getViewport({ scale: RENDER_SCALE });
    const { items } = await page.getTextContent();

    let full = "", fullNS = "", fullAZ = "";
    const charMap: number[] = [], nsMap: number[] = [], azMap: number[] = [];

    for (let i = 0; i < items.length; i++) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const it0 = items[i] as any;
      if (typeof it0.str !== "string") continue;
      for (const ch of (it0.str as string)) {
        charMap.push(i); full += ch;
        if (ch.trim())            { nsMap.push(i); fullNS += ch; }
        if (/[a-z0-9]/i.test(ch)) { azMap.push(i); fullAZ += ch; }
      }
      charMap.push(i); full += " ";
    }

    const buildBbox = (covered: Set<number>): CssBbox | null => {
      if (!covered.size) return null;
      const rects: { x: number; y: number; w: number; h: number }[] = [];
      for (const i of covered) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const it = items[i] as any;
        if (typeof it.str !== "string" || !Array.isArray(it.transform)) continue;
        const [, , , d, e, f] = it.transform as number[];
        const cx = e * RENDER_SCALE;
        const cy = viewport.height - f * RENDER_SCALE;
        const fh = Math.max(Math.abs(d) * RENDER_SCALE, 8);
        const w  = Math.max((it.width ?? 0) * RENDER_SCALE, 6);
        rects.push({ x: cx, y: cy - fh, w, h: fh });
      }
      if (!rects.length) return null;
      const x1 = Math.max(0,              Math.min(...rects.map((r) => r.x)));
      const y1 = Math.max(0,              Math.min(...rects.map((r) => r.y)));
      const x2 = Math.min(viewport.width,  Math.max(...rects.map((r) => r.x + r.w)));
      const y2 = Math.min(viewport.height, Math.max(...rects.map((r) => r.y + r.h)));
      if (x2 <= x1 || y2 <= y1) return null;
      const PAD_X = 6, PAD_Y = 3;
      const px1 = Math.max(0,              x1 - PAD_X);
      const py1 = Math.max(0,              y1 - PAD_Y);
      const px2 = Math.min(viewport.width,  x2 + PAD_X);
      const py2 = Math.min(viewport.height, y2 + PAD_Y);
      return {
        left:           `${(px1 / viewport.width)  * 100}%`,
        top:            `${(py1 / viewport.height) * 100}%`,
        width:          `${((px2 - px1) / viewport.width)  * 100}%`,
        height:         `${((py2 - py1) / viewport.height) * 100}%`,
        scrollFraction: py1 / viewport.height,
      };
    };

    const find = (haystack: string, needle: string, map: number[]): Set<number> | null => {
      if (!needle) return null;
      const idx = haystack.toLowerCase().indexOf(needle.toLowerCase());
      if (idx === -1) return null;
      const covered = new Set<number>();
      for (let p = idx; p < Math.min(idx + needle.length, map.length); p++) covered.add(map[p]);
      return covered.size ? covered : null;
    };

    const rawId = controlId.replace(/^(OTC|TCC|CSCC|ECC|CCC|DCC|OSMACC|NCS|GDPR)[- ]/i, "");

    const r1 = find(full, controlId, charMap);
    if (r1) return buildBbox(r1);

    if (rawId !== controlId) {
      const r2 = find(full, rawId, charMap);
      if (r2) return buildBbox(r2);
      const r2ns = find(fullNS, rawId.replace(/\s/g, ""), nsMap);
      if (r2ns) return buildBbox(r2ns);
    }

    const idAZ  = controlId.replace(/[^a-z0-9]/gi, "");
    const rawAZ = rawId.replace(/[^a-z0-9]/gi, "");
    if (rawAZ.length >= 2) {
      const r3 = find(fullAZ, rawAZ, azMap) ?? find(fullAZ, idAZ, azMap);
      if (r3) return buildBbox(r3);
    }

    const normalText = controlText.trim().replace(/\s+/g, " ");
    for (const len of [60, 40, 25, 15]) {
      const snippet = normalText.slice(0, len).trimEnd();
      if (snippet.length < 8) continue;
      const r4 = find(full, snippet, charMap);
      if (r4) return buildBbox(r4);
      const snippetNS = snippet.replace(/\s/g, "");
      if (snippetNS.length >= 6) {
        const r4ns = find(fullNS, snippetNS, nsMap);
        if (r4ns) return buildBbox(r4ns);
      }
    }

    return null;
  } catch {
    return null;
  }
}

// ── Single-page PDF canvas ─────────────────────────────────────────────────
interface PdfCanvasProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pdfDoc: any;
  pageNumber: number;
  bbox: CssBbox | null;
  highlightRef: React.RefObject<HTMLDivElement | null>;
}

function PdfCanvas({ pdfDoc, pageNumber, bbox, highlightRef }: PdfCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [aspect, setAspect] = useState("141.4%");
  const [error, setError]   = useState<string | null>(null);

  useEffect(() => {
    if (!canvasRef.current || !pdfDoc) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await pdfDoc.getPage(pageNumber);
        if (cancelled) return;
        const vp = page.getViewport({ scale: RENDER_SCALE });
        const canvas = canvasRef.current!;
        canvas.width  = vp.width;
        canvas.height = vp.height;
        const ctx = canvas.getContext("2d")!;
        ctx.clearRect(0, 0, vp.width, vp.height);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        if (!cancelled) setAspect(`${(vp.height / vp.width) * 100}%`);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [pdfDoc, pageNumber]);

  return (
    <div className="relative w-full bg-white rounded shadow-xl overflow-hidden"
      style={{ paddingBottom: aspect }}>
      <div className="absolute inset-0">
        <canvas ref={canvasRef} className="w-full h-full object-contain" />
        {bbox && (
          <div
            ref={highlightRef}
            className="absolute pointer-events-none"
            style={{
              left:   bbox.left,
              top:    bbox.top,
              width:  bbox.width,
              height: bbox.height,
              backgroundColor: "rgba(253, 224, 71, 0.50)",
              border: "2px solid rgb(234, 179, 8)",
              borderRadius: "2px",
              boxShadow: "0 0 0 3px rgba(234,179,8,0.15)",
            }}
          />
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/90">
            <span className="text-[9px] font-mono text-red-500 text-center px-4">{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Exported types ─────────────────────────────────────────────────────────
export interface ForensicModalState {
  standardName: string;
  controlId: string;
  /** When set, load this URL directly instead of looking up FILE_MAP */
  pdfUrl?: string;
  /** Text to search/highlight (defaults to controlId if not set) */
  controlText?: string;
}

interface ForensicPDFViewerProps {
  initialControl?: ForensicModalState | null;
  onClearInitial?: () => void;
}

// ── Main inline panel ──────────────────────────────────────────────────────
export default function ForensicPDFViewer({ initialControl, onClearInitial }: ForensicPDFViewerProps) {
  const allControls = useMemo(() => buildControls(), []);

  const [ctrl, setCtrl]       = useState<ControlEntry | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pdfDoc, setPdfDoc]   = useState<any>(null);
  const [totalPages, setTotal] = useState(0);
  const [page, setPage]        = useState(1);
  const [loading, setLoading]  = useState(false);
  const [loadErr, setLoadErr]  = useState<string | null>(null);
  const [bbox, setBbox]        = useState<CssBbox | null>(null);
  const [bboxSearching, setBboxSearching] = useState(false);

  const highlightRef = useRef<HTMLDivElement>(null);

  const linkedControls = useMemo(
    () => (ctrl ? getLinkedControls(ctrl.controlId) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ctrl?.controlId]
  );

  // ── Load PDF when control's file changes ─────────────────────────────────
  useEffect(() => {
    if (!ctrl) { setPdfDoc(null); setLoadErr(null); return; }
    if (!ctrl.filePath) {
      setPdfDoc(null);
      setLoadErr("No PDF available for this standard.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true); setLoadErr(null); setPdfDoc(null); setBbox(null);
    (async () => {
      try {
        const pdfjs = await getPdfJs();
        const doc   = await pdfjs.getDocument(ctrl.filePath).promise;
        if (cancelled) return;
        setTotal(doc.numPages);
        setPdfDoc(doc);
        setPage(ctrl.page);
      } catch (e) {
        if (!cancelled) setLoadErr(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [ctrl?.filePath]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update page when control changes ─────────────────────────────────────
  useEffect(() => {
    if (ctrl) { setPage(ctrl.page); setBbox(null); }
  }, [ctrl?.controlId, ctrl?.page]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Locate highlight bbox ─────────────────────────────────────────────────
  useEffect(() => {
    if (!pdfDoc || loading || !ctrl) return;
    let cancelled = false;
    setBbox(null); setBboxSearching(true);
    (async () => {
      const found = await locateControlInPage(pdfDoc, page, ctrl.controlId, ctrl.text);
      if (!cancelled) { setBbox(found); setBboxSearching(false); }
    })();
    return () => { cancelled = true; };
  }, [pdfDoc, page, ctrl?.controlId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-scroll to highlight ──────────────────────────────────────────────
  useEffect(() => {
    const hl = highlightRef.current;
    if (!hl || !bbox) return;
    requestAnimationFrame(() => hl.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [bbox]);

  // ── Open from KG click or generated doc ──────────────────────────────────
  useEffect(() => {
    if (!initialControl) return;
    if (initialControl.pdfUrl) {
      // Generated document mode: load PDF by URL
      setCtrl(makeGeneratedDocEntry(initialControl));
    } else {
      const found =
        allControls.find(
          (c) => c.controlId === initialControl.controlId && c.standardName === initialControl.standardName
        ) ?? allControls.find((c) => c.controlId === initialControl.controlId);
      if (found) setCtrl(found);
    }
    onClearInitial?.();
  }, [initialControl]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Keyboard navigation ───────────────────────────────────────────────────
  useEffect(() => {
    if (!ctrl) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft")  setPage((p) => Math.max(1, p - 1));
      if (e.key === "ArrowRight") setPage((p) => Math.min(totalPages, p + 1));
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [ctrl, totalPages]);

  const goPrev = useCallback(() => setPage((p) => Math.max(1, p - 1)), []);
  const goNext = useCallback(() => setPage((p) => Math.min(totalPages, p + 1)), [totalPages]);

  const handleNavigate = useCallback((target: ControlEntry) => setCtrl(target), []);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col w-full h-full bg-pwc-bg border-l border-pwc-border overflow-hidden">

      {/* ── Header bar ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 shrink-0 bg-pwc-surface border-b border-pwc-border">
        <svg className="w-3.5 h-3.5 shrink-0 text-pwc-orange" fill="none" viewBox="0 0 24 24"
          stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
        <span className="text-[10px] font-bold font-mono tracking-wider text-pwc-orange shrink-0">
          FORENSIC READER
        </span>

        {ctrl ? (
          <>
            <span className="text-pwc-border mx-0.5 shrink-0">·</span>
            <div className="flex items-center gap-1 text-[9px] font-mono flex-1 min-w-0 overflow-hidden">
              <span className="text-pwc-orange font-bold shrink-0">{ctrl.standardName}</span>
              <span className="text-pwc-border shrink-0">›</span>
              <span className="text-pwc-text font-bold shrink-0">{ctrl.controlId}</span>
              <span className={clsx(
                "text-[8px] font-mono uppercase shrink-0 ml-1",
                ctrl.obligation === "must" ? "text-red-500" : "text-amber-600"
              )}>{ctrl.obligation}</span>
            </div>

            {/* Bbox status */}
            <div className="shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded border border-pwc-border">
              {bboxSearching ? (
                <div className="w-2 h-2 rounded-full border border-pwc-orange border-t-transparent animate-spin" />
              ) : bbox ? (
                <span className="inline-block w-2 h-2 rounded-sm"
                  style={{ background: "rgb(253,224,71)", border: "1px solid rgb(234,179,8)" }} />
              ) : (
                <span className="inline-block w-2 h-2 rounded-full bg-pwc-border" />
              )}
              <span className="text-[8px] font-mono text-pwc-text-dim">
                {bboxSearching ? "…" : bbox ? `p.${page}` : `p.${page}`}
              </span>
            </div>

            {/* Page navigation */}
            <div className="flex items-center gap-0.5 shrink-0">
              <button onClick={goPrev} disabled={page <= 1}
                className="w-5 h-5 flex items-center justify-center rounded hover:bg-pwc-border/40 disabled:opacity-30 transition-colors">
                <svg className="w-3 h-3 text-pwc-text-dim" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
                </svg>
              </button>
              <span className="text-[8px] font-mono text-pwc-text-dim min-w-[42px] text-center">
                {page} / {totalPages || "…"}
              </span>
              <button onClick={goNext} disabled={page >= totalPages}
                className="w-5 h-5 flex items-center justify-center rounded hover:bg-pwc-border/40 disabled:opacity-30 transition-colors">
                <svg className="w-3 h-3 text-pwc-text-dim" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </button>
            </div>
          </>
        ) : (
          <span className="text-[9px] font-mono text-pwc-text-muted ml-1">No control selected</span>
        )}
      </div>

      {/* ── Empty state ─────────────────────────────────────────────── */}
      {!ctrl && (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6">
          <svg className="w-10 h-10 text-pwc-border" fill="none" viewBox="0 0 24 24"
            stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <div className="text-center space-y-1">
            <p className="text-[10px] font-mono font-semibold text-pwc-text-dim">
              No control selected
            </p>
            <p className="text-[9px] font-mono text-pwc-text-muted leading-relaxed">
              Click a control node in the<br />Knowledge Graph or UCCF Overlap<br />to open its source PDF here
            </p>
          </div>
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-pwc-border bg-pwc-surface-raised">
            <span className="inline-block w-2 h-2 rounded-full bg-pwc-orange/60" />
            <span className="text-[8px] font-mono text-pwc-text-muted">Trace-to-source · Yellow highlight</span>
          </div>
        </div>
      )}

      {/* ── Control loaded ──────────────────────────────────────────── */}
      {ctrl && (
        <>
          {/* Control text strip */}
          <div className="px-3 py-1.5 shrink-0 border-b border-pwc-border/60 bg-pwc-bg">
            <p className="text-[8.5px] font-mono text-pwc-text-dim leading-relaxed line-clamp-2">
              {ctrl.text}
            </p>
          </div>

          {/* Scrollable PDF area */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col items-center min-h-0 p-3 gap-3 bg-[#e8e8e8]">
            {loading ? (
              <div className="flex flex-col items-center gap-3 mt-20">
                <div className="w-5 h-5 rounded-full border-2 border-pwc-orange border-t-transparent animate-spin" />
                <span className="text-[9px] font-mono text-pwc-text-muted">Loading PDF…</span>
              </div>
            ) : loadErr ? (
              <div className="flex flex-col items-center gap-2 mt-20 px-4 text-center">
                <span className="text-[9px] font-mono text-red-500">Failed to load PDF</span>
                <span className="text-[8px] font-mono text-pwc-text-muted break-all">{loadErr}</span>
              </div>
            ) : pdfDoc ? (
              <div className="w-full">
                <PdfCanvas
                  pdfDoc={pdfDoc}
                  pageNumber={page}
                  bbox={bbox}
                  highlightRef={highlightRef}
                />
              </div>
            ) : null}
          </div>

          {/* Cross-standard links footer */}
          {linkedControls.length > 0 && (
            <div className="shrink-0 px-3 py-1.5 bg-pwc-surface-raised border-t border-pwc-border">
              <div className="flex items-center gap-1.5 overflow-x-auto">
                <span className="text-[7.5px] font-mono uppercase tracking-wider shrink-0 text-pwc-text-muted">
                  Cross-Links:
                </span>
                {linkedControls.slice(0, 6).map((lc) => {
                  const target = allControls.find((c) => c.controlId === lc.control.id);
                  return (
                    <button
                      key={`${lc.standard}-${lc.control.id}`}
                      onClick={() => target && handleNavigate(target)}
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded font-mono transition-colors border border-pwc-border hover:border-pwc-orange/60 hover:bg-pwc-orange/5 shrink-0"
                    >
                      <span className="text-[7.5px] text-pwc-orange">{lc.standard}</span>
                      <span className="text-[7.5px] text-pwc-text-dim">{lc.control.id}</span>
                      <span className="text-[7px] text-pwc-text-muted">{Math.round(lc.similarity * 100)}%</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
