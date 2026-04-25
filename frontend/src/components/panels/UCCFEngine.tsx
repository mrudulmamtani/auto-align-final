"use client";

/**
 * UCCFEngine — Unified Common Controls Framework
 *
 * Visualises semantic overlap between UAE IAS, all NCA standards, and any
 * user-uploaded standard JSON.  Common controls between standards are shown
 * as shared nodes at the intersection of their standards in a D3 force graph,
 * creating the Venn-style "overlapping controls" the UCCF concept requires.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { clsx } from "clsx";
import {
  ALL_STANDARDS,
  SEMANTIC_LINKS,
  type NormalizedStandard,
  type NormalizedControl,
  type SemanticLink,
} from "@/lib/standardsEngine";
import {
  uccfIngest,
  uccfRemap,
  type UccfIngestResult,
} from "@/lib/api";

// ── Colour palette — one per standard ───────────────────────────────────────
const STD_COLORS: Record<string, string> = {
  "UAE IAS":   "#D04A02",
  "NCA OTC":   "#3B82F6",
  "NCA TCC":   "#8B5CF6",
  "NCA CSCC":  "#06B6D4",
  "NCA ECC":   "#10B981",
  "NCA CCC":   "#F97316",
  "NCA DCC":   "#EC4899",
  "NCA OSMACC":"#6366F1",
  "NCA NCS":   "#14B8A6",
  "ISO 27001": "#EF4444",
  "NIST CSF":  "#84CC16",
  "COSO ERM":  "#A78BFA",
  "SOC 2":     "#FB923C",
  "PCI DSS":   "#60A5FA",
  "GDPR":      "#F472B6",
};
const DEFAULT_COLOR = "#9A9A9A";
const DOMAIN_CLUSTERS = [
  "access_control","risk_management","incident_management","governance",
  "data_protection","network_security","operations_security","third_party",
  "physical_security","business_continuity","audit_compliance",
  "secure_development","cryptography","awareness_training",
];

// ── Initial standard selection (UAE IAS + all NCA) ───────────────────────────
const DEFAULT_SELECTED = new Set<string>([
  "UAE IAS","NCA OTC","NCA TCC","NCA CSCC","NCA ECC","NCA CCC","NCA DCC","NCA OSMACC","NCA NCS",
]);

type Tab = "graph" | "matrix" | "controls" | "upload";

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  type: "standard" | "domain" | "control";
  label: string;
  shortLabel: string;
  stdName: string;
  stdColor: string;
  domainId?: string;
  domainName?: string;
  controlId?: string;
  controlText?: string;
  keywords?: string[];
  linkedStdNames?: string[];
  matchCount?: number;
  isCommon?: boolean;
  r: number; // visual radius
}

interface GraphEdge {
  source: string;
  target: string;
  type: "governs" | "mapped_to" | "semantic";
  similarity?: number;
  sharedKeywords?: string[];
}

// ── Build D3 graph data from selected standards ──────────────────────────────
function buildGraphData(
  selectedNames: Set<string>,
  threshold: number,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const selected = ALL_STANDARDS.filter((s) => selectedNames.has(s.short_name) || selectedNames.has(s.standard_name));

  // Index semantic links by control key (stdName::controlId)
  const linksBySrc = new Map<string, SemanticLink[]>();
  for (const lk of SEMANTIC_LINKS) {
    if (!selectedNames.has(lk.sourceStandard) || !selectedNames.has(lk.targetStandard)) continue;
    if (lk.similarity < threshold) continue;
    const key = `${lk.sourceStandard}::${lk.sourceControlId}`;
    if (!linksBySrc.has(key)) linksBySrc.set(key, []);
    linksBySrc.get(key)!.push(lk);
    const key2 = `${lk.targetStandard}::${lk.targetControlId}`;
    if (!linksBySrc.has(key2)) linksBySrc.set(key2, []);
    linksBySrc.get(key2)!.push(lk);
  }

  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const nodeIds = new Set<string>();

  const addNode = (n: GraphNode) => {
    if (!nodeIds.has(n.id)) { nodes.push(n); nodeIds.add(n.id); }
  };

  for (const std of selected) {
    const col = STD_COLORS[std.short_name] ?? STD_COLORS[std.standard_name] ?? DEFAULT_COLOR;
    const stdId = `std::${std.standard_name}`;
    addNode({ id: stdId, type: "standard", label: std.standard_name, shortLabel: std.short_name,
              stdName: std.standard_name, stdColor: col, r: 20 });

    for (const dom of std.domains) {
      const domId = `dom::${std.standard_name}::${dom.id}`;
      addNode({ id: domId, type: "domain", label: dom.name, shortLabel: dom.id,
                stdName: std.standard_name, stdColor: col, domainId: dom.id,
                domainName: dom.name, r: 7 });
      edges.push({ source: stdId, target: domId, type: "governs" });

      for (const ctrl of dom.controls) {
        const ctrlKey = `${std.standard_name}::${ctrl.id}`;
        const matches = linksBySrc.get(ctrlKey) ?? [];
        if (matches.length === 0 && dom.controls.length > 3) continue; // only show common + small domains
        const linkedStds = matches.map((m) =>
          m.sourceStandard === std.standard_name ? m.targetStandard : m.sourceStandard
        );
        const ctrlId = `ctrl::${std.standard_name}::${ctrl.id}`;
        addNode({
          id: ctrlId, type: "control",
          label: ctrl.name || ctrl.id, shortLabel: ctrl.id,
          stdName: std.standard_name, stdColor: col,
          domainId: dom.id, domainName: dom.name,
          controlId: ctrl.id, controlText: ctrl.text,
          keywords: ctrl.keywords,
          linkedStdNames: [...new Set(linkedStds)],
          matchCount: matches.length,
          isCommon: matches.length > 0,
          r: matches.length > 0 ? 5 : 3,
        });
        edges.push({ source: domId, target: ctrlId, type: "mapped_to" });
      }
    }
  }

  // Semantic edges between control nodes
  const addedSemanticEdges = new Set<string>();
  for (const lk of SEMANTIC_LINKS) {
    if (!selectedNames.has(lk.sourceStandard) || !selectedNames.has(lk.targetStandard)) continue;
    if (lk.similarity < threshold) continue;
    const srcId = `ctrl::${lk.sourceStandard}::${lk.sourceControlId}`;
    const tgtId = `ctrl::${lk.targetStandard}::${lk.targetControlId}`;
    if (!nodeIds.has(srcId) || !nodeIds.has(tgtId)) continue;
    const edgeKey = [srcId, tgtId].sort().join("||");
    if (addedSemanticEdges.has(edgeKey)) continue;
    addedSemanticEdges.add(edgeKey);
    edges.push({ source: srcId, target: tgtId, type: "semantic",
                 similarity: lk.similarity, sharedKeywords: lk.sharedKeywords });
  }

  return { nodes, edges };
}

// ── Overlap matrix from SEMANTIC_LINKS ───────────────────────────────────────
function buildOverlapMatrix(selectedNames: Set<string>) {
  const selected = ALL_STANDARDS.filter((s) => selectedNames.has(s.short_name) || selectedNames.has(s.standard_name));
  const totalByStd = new Map(selected.map((s) => [s.standard_name, s.totalControls]));

  const shared = new Map<string, number>();
  for (const lk of SEMANTIC_LINKS) {
    if (!selectedNames.has(lk.sourceStandard) || !selectedNames.has(lk.targetStandard)) continue;
    const key = [lk.sourceStandard, lk.targetStandard].sort().join("||");
    shared.set(key, (shared.get(key) ?? 0) + 1);
  }

  const matrix: Array<{
    stdA: string; stdB: string;
    count: number; pct: number; colorA: string; colorB: string;
  }> = [];
  const stdNames = selected.map((s) => s.standard_name);
  for (let i = 0; i < stdNames.length; i++) {
    for (let j = i + 1; j < stdNames.length; j++) {
      const a = stdNames[i], b = stdNames[j];
      const key = [a, b].sort().join("||");
      const count = shared.get(key) ?? 0;
      const minTotal = Math.min(totalByStd.get(a) ?? 1, totalByStd.get(b) ?? 1);
      matrix.push({
        stdA: a, stdB: b, count,
        pct: Math.round((count / minTotal) * 100),
        colorA: STD_COLORS[a] ?? DEFAULT_COLOR,
        colorB: STD_COLORS[b] ?? DEFAULT_COLOR,
      });
    }
  }
  matrix.sort((a, b) => b.count - a.count);
  return { matrix, stdNames };
}

// ── Common controls list ──────────────────────────────────────────────────────
function buildCommonControls(selectedNames: Set<string>, threshold: number) {
  const ctrlLookup = new Map<string, { ctrl: NormalizedControl; domName: string; stdName: string }>();
  for (const s of ALL_STANDARDS) {
    for (const d of s.domains) {
      for (const c of d.controls) {
        ctrlLookup.set(`${s.standard_name}::${c.id}`, { ctrl: c, domName: d.name, stdName: s.standard_name });
      }
    }
  }

  const seen = new Set<string>();
  const common: Array<{
    key: string; ctrl: NormalizedControl; stdName: string; domName: string;
    mappedTo: Array<{ stdName: string; ctrlId: string; ctrlName: string; sim: number; keywords: string[] }>;
  }> = [];

  for (const lk of SEMANTIC_LINKS) {
    if (!selectedNames.has(lk.sourceStandard) || !selectedNames.has(lk.targetStandard)) continue;
    if (lk.similarity < threshold) continue;

    const srcKey = `${lk.sourceStandard}::${lk.sourceControlId}`;
    if (!seen.has(srcKey)) {
      seen.add(srcKey);
      const info = ctrlLookup.get(srcKey);
      if (info) {
        const mappedTo = SEMANTIC_LINKS
          .filter((l) => l.sourceStandard === lk.sourceStandard && l.sourceControlId === lk.sourceControlId && selectedNames.has(l.targetStandard) && l.similarity >= threshold)
          .map((l) => {
            const ti = ctrlLookup.get(`${l.targetStandard}::${l.targetControlId}`);
            return { stdName: l.targetStandard, ctrlId: l.targetControlId,
                     ctrlName: ti?.ctrl.name ?? l.targetControlId,
                     sim: l.similarity, keywords: l.sharedKeywords };
          });
        if (mappedTo.length > 0)
          common.push({ key: srcKey, ctrl: info.ctrl, stdName: info.stdName, domName: info.domName, mappedTo });
      }
    }
  }
  common.sort((a, b) => b.mappedTo.length - a.mappedTo.length);
  return common;
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════
export default function UCCFEngine() {
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphEdge> | null>(null);

  const [selectedStds, setSelectedStds] = useState<Set<string>>(DEFAULT_SELECTED);
  const [activeTab, setActiveTab] = useState<Tab>("graph");
  const [threshold, setThreshold] = useState(0.12);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [domainFilter, setDomainFilter] = useState<string>("all");

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UccfIngestResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Computed data ────────────────────────────────────────────────────────
  const graphData = useMemo(() => buildGraphData(selectedStds, threshold), [selectedStds, threshold]);
  const { matrix, stdNames: matrixStdNames } = useMemo(() => buildOverlapMatrix(selectedStds), [selectedStds]);
  const commonControls = useMemo(() => buildCommonControls(selectedStds, threshold), [selectedStds, threshold]);

  const stats = useMemo(() => {
    const stdCount = selectedStds.size;
    const commonCount = commonControls.length;
    const totalControls = ALL_STANDARDS
      .filter((s) => selectedStds.has(s.short_name) || selectedStds.has(s.standard_name))
      .reduce((acc, s) => acc + s.totalControls, 0);
    const semanticPairs = matrix.reduce((acc, m) => acc + m.count, 0);
    return { stdCount, commonCount, totalControls, semanticPairs };
  }, [selectedStds, commonControls, matrix]);

  // ── D3 Force Graph ────────────────────────────────────────────────────────
  const renderGraph = useCallback(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = svgRef.current.clientWidth || 600;
    const H = svgRef.current.clientHeight || 400;
    svg.attr("viewBox", `0 0 ${W} ${H}`);

    const { nodes, edges } = graphData;
    if (nodes.length === 0) return;

    // Defs: arrow marker
    const defs = svg.append("defs");
    defs.append("marker")
      .attr("id", "arrow").attr("viewBox", "0 -3 6 6").attr("refX", 10).attr("refY", 0)
      .attr("markerWidth", 4).attr("markerHeight", 4).attr("orient", "auto")
      .append("path").attr("d", "M0,-3L6,0L0,3").attr("fill", "#555555");

    const root = svg.append("g").attr("class", "root");
    svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 4]).on("zoom", (e) => {
      root.attr("transform", e.transform);
    }) as never);

    // Pin standard nodes in a circle
    const stdNodes = nodes.filter((n) => n.type === "standard");
    const R = Math.min(W, H) * 0.32;
    stdNodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / stdNodes.length - Math.PI / 2;
      n.fx = W / 2 + R * Math.cos(angle);
      n.fy = H / 2 + R * Math.sin(angle);
      n.x = n.fx;
      n.y = n.fy;
    });

    // Build edge map for force
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const simEdges = edges.map((e) => ({
      ...e,
      source: nodeById.get(e.source as string) ?? e.source,
      target: nodeById.get(e.target as string) ?? e.target,
    }));

    // Simulation
    const sim = d3.forceSimulation<GraphNode>(nodes)
      .force("link", d3.forceLink<GraphNode, typeof simEdges[0]>(simEdges)
        .id((d) => d.id)
        .distance((e) => {
          if (e.type === "governs") return 60;
          if (e.type === "mapped_to") return 30;
          return 20; // semantic — pull matching controls together
        })
        .strength((e) => {
          if (e.type === "semantic") return 0.5;
          if (e.type === "governs") return 0.4;
          return 0.6;
        })
      )
      .force("charge", d3.forceManyBody().strength((d) => {
        if ((d as GraphNode).type === "standard") return 0;
        if ((d as GraphNode).type === "domain") return -60;
        return (d as GraphNode).isCommon ? -25 : -15;
      }))
      .force("collision", d3.forceCollide<GraphNode>().radius((d) => d.r + 2))
      .alphaDecay(0.03);

    simulationRef.current = sim;

    // Semantic edges (drawn first, behind everything)
    const semanticEdges = simEdges.filter((e) => e.type === "semantic");
    const linkEl = root.append("g").attr("class", "semantic-links")
      .selectAll("line").data(semanticEdges).join("line")
      .attr("stroke", (e) => {
        const s = e.source as GraphNode;
        return STD_COLORS[s.stdName] ?? DEFAULT_COLOR;
      })
      .attr("stroke-opacity", 0.35)
      .attr("stroke-width", (e) => Math.max(0.5, (e.similarity ?? 0) * 2))
      .attr("stroke-dasharray", "3,3");

    // Structural edges
    const structEdges = simEdges.filter((e) => e.type !== "semantic");
    const structEl = root.append("g").attr("class", "struct-links")
      .selectAll("line").data(structEdges).join("line")
      .attr("stroke", "#2E2E2E").attr("stroke-opacity", 0.2).attr("stroke-width", 0.5);

    // Node groups
    const nodeEl = root.append("g").attr("class", "nodes")
      .selectAll("g").data(nodes).join("g")
      .style("cursor", "pointer")
      .call((selection) => {
        const drag = d3.drag<SVGGElement, GraphNode>()
          .on("start", (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d) => {
            if (!event.active) sim.alphaTarget(0);
            if (d.type !== "standard") { d.fx = null; d.fy = null; }
          });
        drag(selection as never);
      })
      .on("click", (_event, d) => setSelectedNode((prev) => prev?.id === d.id ? null : d));

    // Standard nodes — large labelled circles
    nodeEl.filter((d) => d.type === "standard").append("circle")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => d.stdColor + "22")
      .attr("stroke", (d) => d.stdColor)
      .attr("stroke-width", 2.5);

    nodeEl.filter((d) => d.type === "standard").append("text")
      .attr("text-anchor", "middle").attr("dy", "0.35em")
      .attr("fill", (d) => d.stdColor)
      .attr("font-size", "8px").attr("font-weight", "700")
      .attr("pointer-events", "none")
      .text((d) => d.shortLabel);

    // Domain nodes
    nodeEl.filter((d) => d.type === "domain").append("circle")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => d.stdColor + "44")
      .attr("stroke", (d) => d.stdColor)
      .attr("stroke-width", 1);

    // Control nodes — common controls are larger and brighter
    nodeEl.filter((d) => d.type === "control").append("circle")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => d.isCommon ? d.stdColor : d.stdColor + "55")
      .attr("stroke", (d) => d.isCommon ? "#fff" : "none")
      .attr("stroke-width", (d) => d.isCommon ? 0.8 : 0)
      .attr("opacity", (d) => d.isCommon ? 0.9 : 0.5);

    // Tooltip on hover
    nodeEl.append("title").text((d) => {
      if (d.type === "standard") return d.label;
      if (d.type === "domain") return `${d.stdName} › ${d.domainName}`;
      return `${d.stdName} › ${d.domainId} › ${d.controlId}\n${d.matchCount ? `${d.matchCount} cross-standard match(es)` : ""}`;
    });

    sim.on("tick", () => {
      linkEl
        .attr("x1", (e) => (e.source as GraphNode).x ?? 0)
        .attr("y1", (e) => (e.source as GraphNode).y ?? 0)
        .attr("x2", (e) => (e.target as GraphNode).x ?? 0)
        .attr("y2", (e) => (e.target as GraphNode).y ?? 0);
      structEl
        .attr("x1", (e) => (e.source as GraphNode).x ?? 0)
        .attr("y1", (e) => (e.source as GraphNode).y ?? 0)
        .attr("x2", (e) => (e.target as GraphNode).x ?? 0)
        .attr("y2", (e) => (e.target as GraphNode).y ?? 0);
      nodeEl.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });
  }, [graphData]);

  useEffect(() => {
    if (activeTab === "graph") {
      const t = setTimeout(renderGraph, 50);
      return () => clearTimeout(t);
    }
  }, [activeTab, renderGraph]);

  useEffect(() => {
    if (activeTab !== "graph") return;
    const obs = new ResizeObserver(() => renderGraph());
    if (svgRef.current?.parentElement) obs.observe(svgRef.current.parentElement);
    return () => obs.disconnect();
  }, [activeTab, renderGraph]);

  // ── Upload handlers ──────────────────────────────────────────────────────
  const handleFileUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      const result = await uccfIngest(file);
      setUploadResult(result);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  }, [handleFileUpload]);

  const handleRemap = useCallback(async () => {
    try {
      await uccfRemap();
    } catch { /* backend may be offline */ }
  }, []);

  // ── Toggle standard ──────────────────────────────────────────────────────
  const toggleStd = useCallback((name: string) => {
    setSelectedStds((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  // ── Standard groups for sidebar ──────────────────────────────────────────
  const stdGroups = useMemo(() => {
    const uae = ALL_STANDARDS.filter((s) => s.short_name.startsWith("UAE"));
    const nca = ALL_STANDARDS.filter((s) => s.short_name.startsWith("NCA"));
    const intl = ALL_STANDARDS.filter((s) => !s.short_name.startsWith("UAE") && !s.short_name.startsWith("NCA"));
    return [
      { label: "UAE Standards", stds: uae },
      { label: "NCA Standards", stds: nca },
      { label: "International", stds: intl },
    ];
  }, []);

  // ── Filtered common controls ─────────────────────────────────────────────
  const filteredControls = useMemo(() => {
    let list = commonControls;
    if (domainFilter !== "all") list = list.filter((c) => {
      const text = (c.ctrl.text ?? "").toLowerCase();
      return text.includes(domainFilter.replace(/_/g, " ").toLowerCase()) ||
             c.ctrl.keywords?.some((k) => domainFilter.includes(k));
    });
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter((c) =>
        (c.ctrl.name ?? "").toLowerCase().includes(q) ||
        (c.ctrl.id ?? "").toLowerCase().includes(q) ||
        (c.ctrl.text ?? "").toLowerCase().includes(q) ||
        (c.stdName ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [commonControls, domainFilter, searchQuery]);

  // suppress unused warning for matrixStdNames
  void matrixStdNames;

  // ════════════════════════════════════════════════════════════════════════════
  // Render
  // ════════════════════════════════════════════════════════════════════════════
  return (
    <div className="flex flex-col w-full h-full min-h-0 overflow-hidden">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-3 py-1.5 bg-pwc-surface border-b border-pwc-border shrink-0 flex-wrap">
        <span className="text-[9px] text-pwc-text-dim uppercase tracking-widest whitespace-nowrap">
          UCCF — Unified Common Controls Framework
        </span>
        <div className="flex gap-3 text-[9px] ml-2">
          <span className="text-pwc-orange font-bold">{stats.stdCount} Standards</span>
          <span className="text-pwc-text-dim">·</span>
          <span className="text-pwc-text-dim font-bold">{stats.commonCount} Common Controls</span>
          <span className="text-pwc-text-dim">·</span>
          <span className="text-pwc-text-dim">{stats.semanticPairs} Semantic Pairs</span>
          <span className="text-pwc-text-dim">·</span>
          <span className="text-pwc-text-dim">{stats.totalControls} Total Controls</span>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-[8px]">
          <span className="text-pwc-text-muted">Threshold:</span>
          <input
            type="range" min={0.08} max={0.5} step={0.01} value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="h-3 w-20"
          />
          <span className="text-pwc-text-dim w-8">{(threshold * 100).toFixed(0)}%</span>
        </div>
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* ── Left Sidebar — standard selection ──────────────────────────── */}
        <div className="w-52 shrink-0 border-r border-pwc-border flex flex-col overflow-hidden bg-pwc-surface">
          <div className="px-2 py-1.5 border-b border-pwc-border">
            <div className="text-[8px] text-pwc-text-dim uppercase tracking-wider">Standards</div>
          </div>
          <div className="flex-1 overflow-y-auto p-1.5 space-y-2">
            {stdGroups.map((group) => (
              <div key={group.label}>
                <div className="text-[7px] text-pwc-text-muted uppercase tracking-widest px-1 mb-0.5">{group.label}</div>
                {group.stds.map((s) => {
                  const name = s.short_name;
                  const active = selectedStds.has(name) || selectedStds.has(s.standard_name);
                  const color = STD_COLORS[name] ?? STD_COLORS[s.standard_name] ?? DEFAULT_COLOR;
                  return (
                    <button
                      key={s.urn}
                      onClick={() => toggleStd(name)}
                      className={clsx(
                        "w-full flex items-center gap-1.5 px-1.5 py-1 rounded text-left transition-all",
                        active ? "bg-pwc-bg" : "opacity-50 hover:opacity-70"
                      )}
                    >
                      <div
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: color, opacity: active ? 1 : 0.4 }}
                      />
                      <div className="min-w-0">
                        <div className={clsx("text-[9px] font-bold truncate", active ? "text-pwc-text" : "text-pwc-text-dim")}>
                          {name}
                        </div>
                        <div className="text-[7px] text-pwc-text-muted truncate">{s.totalControls} controls</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="p-2 border-t border-pwc-border space-y-1">
            <button
              onClick={() => setActiveTab("upload")}
              className="w-full px-2 py-1.5 text-[8px] bg-pwc-orange/10 border border-pwc-orange/30 text-pwc-orange rounded hover:bg-pwc-orange/20 transition-colors"
            >
              + Upload Standard JSON
            </button>
            <button
              onClick={handleRemap}
              className="w-full px-2 py-1 text-[8px] border border-pwc-border text-pwc-text-dim rounded hover:border-pwc-border-bright transition-colors"
            >
              Re-run Semantic Mapping
            </button>
          </div>
        </div>

        {/* ── Main area ────────────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">

          {/* Tabs */}
          <div className="flex gap-0.5 px-2 py-1 bg-pwc-surface border-b border-pwc-border shrink-0">
            {(["graph", "matrix", "controls", "upload"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setActiveTab(t)}
                className={clsx(
                  "px-2.5 py-0.5 text-[8px] rounded border transition-colors uppercase tracking-wider",
                  activeTab === t
                    ? "bg-pwc-orange text-white border-pwc-orange"
                    : "text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
                )}
              >
                {t === "graph" ? "UCCF Graph" : t === "matrix" ? "Overlap Matrix" : t === "controls" ? "Common Controls" : "Upload Standard"}
              </button>
            ))}
          </div>

          {/* ── GRAPH TAB ──────────────────────────────────────────────────── */}
          {activeTab === "graph" && (
            <div className="flex flex-1 min-h-0 relative overflow-hidden">
              <svg ref={svgRef} className="w-full h-full" style={{ background: "var(--pwc-bg)" }} />

              {/* Legend */}
              <div className="absolute bottom-2 left-2 bg-pwc-surface/90 border border-pwc-border rounded px-2 py-1.5 space-y-1">
                <div className="text-[7px] text-pwc-text-dim uppercase tracking-wider mb-1">Legend</div>
                <div className="flex items-center gap-1.5">
                  <div className="w-4 h-4 rounded-full border-2 border-pwc-orange bg-transparent" />
                  <span className="text-[7px] text-pwc-text-dim">Standard</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-pwc-orange/40 border border-pwc-orange" />
                  <span className="text-[7px] text-pwc-text-dim">Domain</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-pwc-orange" />
                  <span className="text-[7px] text-pwc-text-dim">Common control</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-6 h-0 border-t border-dashed border-pwc-orange" />
                  <span className="text-[7px] text-pwc-text-dim">Semantic match</span>
                </div>
              </div>

              {/* Selected node details */}
              {selectedNode && (
                <div className="absolute top-2 right-2 w-56 bg-pwc-surface/95 border border-pwc-border rounded p-2.5 space-y-1.5 text-[8px]">
                  <button
                    onClick={() => setSelectedNode(null)}
                    className="absolute top-1.5 right-1.5 text-pwc-text-muted hover:text-pwc-text text-[10px]"
                  >✕</button>
                  <div className="font-bold text-[9px] truncate pr-4"
                    style={{ color: STD_COLORS[selectedNode.stdName] ?? DEFAULT_COLOR }}>
                    {selectedNode.label}
                  </div>
                  <div className="text-pwc-text-dim truncate">{selectedNode.stdName}</div>
                  {selectedNode.type === "domain" && (
                    <div className="text-pwc-text-dim">{selectedNode.domainName}</div>
                  )}
                  {selectedNode.type === "control" && (
                    <>
                      <div className="text-pwc-text-dim">{selectedNode.domainName}</div>
                      <div className="text-pwc-text leading-relaxed line-clamp-3">{selectedNode.controlText}</div>
                      {(selectedNode.matchCount ?? 0) > 0 && (
                        <div className="text-pwc-orange font-bold">{selectedNode.matchCount} cross-standard match(es)</div>
                      )}
                      {(selectedNode.linkedStdNames ?? []).length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selectedNode.linkedStdNames!.map((n) => (
                            <span key={n} className="px-1 py-0.5 rounded text-[7px] font-bold"
                              style={{ backgroundColor: (STD_COLORS[n] ?? DEFAULT_COLOR) + "22",
                                       color: STD_COLORS[n] ?? DEFAULT_COLOR }}>
                              {n}
                            </span>
                          ))}
                        </div>
                      )}
                      {(selectedNode.keywords ?? []).length > 0 && (
                        <div className="text-pwc-text-muted text-[7px] mt-1">
                          Keywords: {selectedNode.keywords!.join(", ")}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── MATRIX TAB ─────────────────────────────────────────────────── */}
          {activeTab === "matrix" && (
            <div className="flex-1 overflow-auto p-3 min-h-0">
              <div className="text-[9px] text-pwc-text-dim mb-2">
                Cross-standard semantic overlap — count of controls matched between each pair.
                Percentage is relative to the smaller standard in the pair.
              </div>
              {matrix.length === 0 ? (
                <div className="text-[9px] text-pwc-text-muted text-center py-8">
                  No semantic matches found at current threshold ({(threshold * 100).toFixed(0)}%).
                  Try selecting more standards or lowering the threshold.
                </div>
              ) : (
                <div className="space-y-0.5">
                  {matrix.map((row) => (
                    <div key={`${row.stdA}||${row.stdB}`}
                      className="flex items-center gap-2 border border-pwc-border rounded px-2 py-1.5 bg-pwc-bg hover:border-pwc-border-bright transition-colors">
                      <div className="flex items-center gap-1 w-28 shrink-0 min-w-0">
                        <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: row.colorA }} />
                        <span className="text-[8px] font-bold text-pwc-text truncate">{row.stdA}</span>
                      </div>
                      <div className="text-[7px] text-pwc-text-muted shrink-0">↔</div>
                      <div className="flex items-center gap-1 w-28 shrink-0 min-w-0">
                        <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: row.colorB }} />
                        <span className="text-[8px] font-bold text-pwc-text truncate">{row.stdB}</span>
                      </div>
                      <div className="flex-1 h-1.5 bg-pwc-border rounded overflow-hidden">
                        <div
                          className="h-full rounded"
                          style={{
                            width: `${Math.min(100, row.pct)}%`,
                            background: `linear-gradient(90deg, ${row.colorA}, ${row.colorB})`,
                          }}
                        />
                      </div>
                      <span className="text-[8px] font-bold text-pwc-orange w-8 text-right shrink-0">{row.count}</span>
                      <span className="text-[8px] text-pwc-text-dim w-10 text-right shrink-0">{row.pct}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── COMMON CONTROLS TAB ──────────────────────────────────────────── */}
          {activeTab === "controls" && (
            <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
              {/* Filter bar */}
              <div className="flex items-center gap-2 px-2 py-1.5 border-b border-pwc-border shrink-0">
                <input
                  type="text"
                  placeholder="Search controls..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="flex-1 min-w-0 bg-pwc-bg border border-pwc-border rounded px-2 py-0.5 text-[9px] text-pwc-text placeholder-pwc-text-muted"
                />
                <select
                  value={domainFilter}
                  onChange={(e) => setDomainFilter(e.target.value)}
                  className="bg-pwc-bg border border-pwc-border rounded px-1.5 py-0.5 text-[8px] text-pwc-text-dim"
                >
                  <option value="all">All Domains</option>
                  {DOMAIN_CLUSTERS.map((d) => (
                    <option key={d} value={d}>{d.replace(/_/g, " ")}</option>
                  ))}
                </select>
                <span className="text-[8px] text-pwc-text-muted shrink-0">{filteredControls.length} controls</span>
              </div>
              {/* List */}
              <div className="flex-1 overflow-y-auto p-2 space-y-1.5 min-h-0">
                {filteredControls.length === 0 ? (
                  <div className="text-[9px] text-pwc-text-muted text-center py-8">
                    No common controls found. Try selecting more standards or lowering the threshold.
                  </div>
                ) : (
                  filteredControls.map((item) => (
                    <div key={item.key}
                      className="border border-pwc-border rounded p-2 bg-pwc-bg hover:border-pwc-border-bright transition-colors">
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <div className="min-w-0">
                          <span className="text-[8px] font-bold px-1 py-0.5 rounded mr-1.5"
                            style={{ backgroundColor: (STD_COLORS[item.stdName] ?? DEFAULT_COLOR) + "22",
                                     color: STD_COLORS[item.stdName] ?? DEFAULT_COLOR }}>
                            {item.stdName}
                          </span>
                          <span className="text-[9px] font-bold text-pwc-text">{item.ctrl.id}</span>
                        </div>
                        <span className="text-[8px] text-pwc-orange font-bold shrink-0">
                          {item.mappedTo.length} match{item.mappedTo.length !== 1 ? "es" : ""}
                        </span>
                      </div>
                      <div className="text-[9px] text-pwc-text font-medium truncate mb-0.5">{item.ctrl.name}</div>
                      <div className="text-[8px] text-pwc-text-dim line-clamp-2 mb-1.5">{item.ctrl.text}</div>
                      {/* Matched controls */}
                      <div className="flex flex-wrap gap-1">
                        {item.mappedTo.map((m) => (
                          <div key={`${m.stdName}::${m.ctrlId}`}
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded border text-[7px]"
                            style={{ borderColor: (STD_COLORS[m.stdName] ?? DEFAULT_COLOR) + "55",
                                     backgroundColor: (STD_COLORS[m.stdName] ?? DEFAULT_COLOR) + "11" }}>
                            <div className="w-1.5 h-1.5 rounded-full"
                              style={{ backgroundColor: STD_COLORS[m.stdName] ?? DEFAULT_COLOR }} />
                            <span className="font-bold truncate max-w-[80px]" style={{ color: STD_COLORS[m.stdName] ?? DEFAULT_COLOR }}>
                              {m.stdName}
                            </span>
                            <span className="text-pwc-text-dim truncate max-w-[48px]">{m.ctrlId}</span>
                            <span className="text-pwc-text-muted">{(m.sim * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                      </div>
                      {/* Shared keywords */}
                      {item.mappedTo[0]?.keywords?.length > 0 && (
                        <div className="flex flex-wrap gap-0.5 mt-1">
                          {item.mappedTo[0].keywords.map((k) => (
                            <span key={k} className="text-[6px] px-1 py-0.5 bg-pwc-surface rounded text-pwc-text-muted">{k}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ── UPLOAD TAB ─────────────────────────────────────────────────── */}
          {activeTab === "upload" && (
            <div className="flex-1 overflow-auto p-4 min-h-0">
              <div className="max-w-xl mx-auto space-y-4">
                <div>
                  <div className="text-[11px] font-bold text-pwc-text mb-1">Upload Standard JSON</div>
                  <div className="text-[9px] text-pwc-text-dim leading-relaxed">
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
                    "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all",
                    dragOver ? "border-pwc-orange bg-pwc-orange/5" : "border-pwc-border hover:border-pwc-border-bright",
                    uploading ? "opacity-60 pointer-events-none" : ""
                  )}
                >
                  <input ref={fileInputRef} type="file" accept=".json" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); }} />
                  <div className="text-[24px] mb-2">{uploading ? "..." : "+"}</div>
                  <div className="text-[10px] font-bold text-pwc-text mb-1">
                    {uploading ? "Ingesting standard..." : "Drop JSON here or click to browse"}
                  </div>
                  <div className="text-[8px] text-pwc-text-dim">Accepts .json files only</div>
                </div>

                {/* Result */}
                {uploadResult && (
                  <div className="border border-pwc-border rounded p-3 bg-pwc-bg space-y-1">
                    <div className="text-[10px] font-bold text-risk-low">Ingested Successfully</div>
                    <div className="text-[9px] text-pwc-text">{uploadResult.standard_name}</div>
                    <div className="grid grid-cols-2 gap-1 mt-2">
                      {[
                        ["Controls parsed", uploadResult.controls_parsed],
                        ["Domains created", uploadResult.domains_created],
                        ["Controls in KG", uploadResult.controls_created],
                        ["Semantic links", uploadResult.semantic_links_created],
                      ].map(([label, val]) => (
                        <div key={label as string} className="flex items-center justify-between border border-pwc-border/50 rounded px-1.5 py-1">
                          <span className="text-[8px] text-pwc-text-dim truncate">{label}</span>
                          <span className="text-[9px] font-bold text-pwc-orange">{val}</span>
                        </div>
                      ))}
                    </div>
                    <div className="text-[8px] text-pwc-text-muted mt-1 font-mono truncate">{uploadResult.standard_urn}</div>
                  </div>
                )}

                {uploadError && (
                  <div className="border border-red-500/30 rounded p-3 bg-red-500/5">
                    <div className="text-[9px] text-red-400 font-bold mb-1">Upload Error</div>
                    <div className="text-[8px] text-red-300/80">{uploadError}</div>
                  </div>
                )}

                {/* Format guide */}
                <div className="border border-pwc-border rounded p-3 space-y-2">
                  <div className="text-[9px] font-bold text-pwc-text">Supported JSON Formats</div>
                  <div className="space-y-2">
                    {[
                      {
                        name: "Normalized (recommended)",
                        sample: `{\n  "standard_name": "My Standard",\n  "short_name": "MS",\n  "version": "1.0",\n  "domains": [\n    {\n      "id": "AC", "name": "Access Control",\n      "controls": [\n        { "id": "AC-1", "name": "...", "text": "..." }\n      ]\n    }\n  ]\n}`,
                      },
                      {
                        name: "UAE IAS flat list",
                        sample: `[\n  {\n    "control_family_id": "1",\n    "control_family_name": "...",\n    "control_id": "1.1",\n    "control_statement": "..."\n  }\n]`,
                      },
                      {
                        name: "NCA flat list",
                        sample: `[\n  {\n    "framework_name": "NCA XXX",\n    "main_domain_id": "1",\n    "control_id": "1-1",\n    "control_statement": "..."\n  }\n]`,
                      },
                    ].map((fmt) => (
                      <div key={fmt.name}>
                        <div className="text-[8px] font-bold text-pwc-text-dim mb-0.5">{fmt.name}</div>
                        <pre className="text-[7px] text-pwc-text-muted bg-pwc-surface rounded p-2 overflow-x-auto whitespace-pre leading-relaxed">{fmt.sample}</pre>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>{/* end main area */}
      </div>{/* end flex row */}
    </div>
  );
}
