"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import * as d3 from "d3";
import { clsx } from "clsx";
import { ALL_STANDARDS, SEMANTIC_LINKS, toLegacyFormat } from "@/lib/standardsEngine";

interface StandardControl {
  id: string;
  text: string;
  obligation: string;
  pdf_ref: { page: number; coordinates: number[] };
}

interface StandardDomain {
  id: string;
  name: string;
  controls: StandardControl[];
}

interface StandardData {
  standard_name: string;
  version: string;
  urn: string;
  domains: StandardDomain[];
}

interface TreeNode {
  name: string;
  id: string;
  urn: string;
  type: "standard" | "domain" | "control";
  obligation?: string;
  children?: TreeNode[];
}

interface ForceNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  urn: string;
  type: "standard" | "domain" | "control";
  obligation?: string;
  standard?: string;
}

interface ForceLink extends d3.SimulationLinkDatum<ForceNode> {
  type: string;
}

type LayoutMode = "tree" | "force" | "radial";

function buildTree(data: StandardData): TreeNode {
  return {
    name: data.standard_name,
    id: data.urn,
    urn: data.urn,
    type: "standard",
    children: data.domains.map((domain) => ({
      name: domain.name,
      id: `${data.urn}:${domain.id}`,
      urn: `${data.urn}:${domain.id}`,
      type: "domain" as const,
      children: domain.controls.map((ctrl) => ({
        name: ctrl.id,
        id: ctrl.id,
        urn: `urn:pwc:ctrl:${(ctrl.id ?? "").toLowerCase().replace(/[^a-z0-9]/g, "-")}`,
        type: "control" as const,
        obligation: ctrl.obligation,
      })),
    })),
  };
}

function buildForceData(datasets: StandardData[]): { nodes: ForceNode[]; links: ForceLink[] } {
  const nodes: ForceNode[] = [];
  const links: ForceLink[] = [];
  const nodeIds = new Set<string>();

  for (const data of datasets) {
    const stdId = data.urn;
    nodes.push({ id: stdId, name: data.standard_name, urn: stdId, type: "standard", standard: data.standard_name });
    nodeIds.add(stdId);

    for (const domain of data.domains) {
      const domId = `${stdId}:${domain.id}`;
      nodes.push({ id: domId, name: domain.name, urn: domId, type: "domain", standard: data.standard_name });
      links.push({ source: stdId, target: domId, type: "GOVERNS" });
      nodeIds.add(domId);

      for (const ctrl of domain.controls) {
        const ctrlId = `${data.standard_name}:${ctrl.id}`;
        nodes.push({
          id: ctrlId, name: ctrl.id, urn: `urn:pwc:ctrl:${(ctrl.id ?? "").toLowerCase().replace(/[^a-z0-9]/g, "-")}`,
          type: "control", obligation: ctrl.obligation, standard: data.standard_name,
        });
        links.push({ source: domId, target: ctrlId, type: "MAPPED_TO" });
        nodeIds.add(ctrlId);
      }
    }
  }

  // Add cross-standard semantic links if multiple standards active
  if (datasets.length > 1) {
    const activeNames = new Set(datasets.map((d) => d.standard_name));
    for (const sl of SEMANTIC_LINKS) {
      if (activeNames.has(sl.sourceStandard) && activeNames.has(sl.targetStandard) && sl.similarity >= 0.15) {
        const srcId = `${sl.sourceStandard}:${sl.sourceControlId}`;
        const tgtId = `${sl.targetStandard}:${sl.targetControlId}`;
        if (nodeIds.has(srcId) && nodeIds.has(tgtId)) {
          links.push({ source: srcId, target: tgtId, type: "SEMANTIC" });
        }
      }
    }
  }

  return { nodes, links };
}

const TYPE_COLORS: Record<string, string> = {
  standard: "#D04A02",
  domain:   "#EB6524",
  control:  "#9A9A9A",
};

const STANDARD_COLORS: Record<string, string> = {
  "UAE IAS":   "#D04A02",
  "NCA OTC":   "#EB6524",
  "NCA TCC":   "#F59E0B",
  "NCA CSCC":  "#047857",
};

const TYPE_RADIUS: Record<string, number> = {
  standard: 12,
  domain: 8,
  control: 5,
};

interface RMapGraphProps {
  standards?: string[];
  onControlClick?: (standardName: string, controlId: string) => void;
  coveredControlIds?: Set<string>;
}

// Pre-compute legacy format data from standardsEngine
const LEGACY_DATASETS: StandardData[] = ALL_STANDARDS.map((s) => toLegacyFormat(s) as StandardData);

export default function RMapGraph({ standards: externalStandards, onControlClick, coveredControlIds }: RMapGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const coveredRef = useRef<Set<string>>(coveredControlIds ?? new Set());
  const [activeStandards, setActiveStandards] = useState<Set<string>>(
    new Set(externalStandards ?? ["UAE IAS"])
  );
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("tree");

  // Update when external standards change
  useEffect(() => {
    if (externalStandards) {
      setActiveStandards(new Set(externalStandards));
    }
  }, [externalStandards]);

  // Sync covered control IDs ref — triggers re-render via render() in next effect
  useEffect(() => {
    coveredRef.current = coveredControlIds ?? new Set();
  }, [coveredControlIds]);

  const toggleStandard = (name: string) => {
    setActiveStandards((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        if (next.size > 1) next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const getActiveDatasets = useCallback((): StandardData[] => {
    return LEGACY_DATASETS.filter((d) => activeStandards.has(d.standard_name));
  }, [activeStandards]);

  const handleNodeClick = useCallback((standardName: string, controlId: string) => {
    onControlClick?.(standardName, controlId);
  }, [onControlClick]);

  const renderTree = useCallback(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    const container = svgRef.current?.parentElement;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;
    const margin = { top: 24, right: 40, bottom: 24, left: 100 };

    svg.attr("viewBox", `0 0 ${width} ${height}`);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const datasets = getActiveDatasets();
    if (datasets.length === 0) return;

    // Merge into single root if multiple standards
    const root = datasets.length === 1
      ? d3.hierarchy(buildTree(datasets[0]))
      : d3.hierarchy<TreeNode>({
          name: "Standards",
          id: "root",
          urn: "root",
          type: "standard",
          children: datasets.map((d) => buildTree(d)),
        });

    const treeLayout = d3.tree<TreeNode>()
      .size([height - margin.top - margin.bottom, width - margin.left - margin.right - 60]);
    treeLayout(root);

    // Links
    g.selectAll<SVGPathElement, d3.HierarchyPointLink<TreeNode>>("path.link")
      .data(root.links())
      .join("path")
      .attr("class", "link")
      .attr("fill", "none")
      .attr("stroke", (d) => {
        const target = d.target.data;
        if (target.type === "control" && target.obligation === "must") return "#D04A02";
        if (target.type === "control") return "#BDBDBD";
        return "#E0E0E0";
      })
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", (d) => {
        const target = d.target.data;
        if (target.type === "control" && target.obligation !== "must") return "4,3";
        return "none";
      })
      .attr("d", (d) => {
        return `M${d.source.y},${d.source.x}
                C${(d.source.y! + d.target.y!) / 2},${d.source.x}
                 ${(d.source.y! + d.target.y!) / 2},${d.target.x}
                 ${d.target.y},${d.target.x}`;
      });

    // Nodes
    const nodeG = g
      .selectAll<SVGGElement, d3.HierarchyPointNode<TreeNode>>("g.node")
      .data(root.descendants())
      .join("g")
      .attr("class", "node")
      .attr("transform", (d) => `translate(${d.y},${d.x})`)
      .attr("cursor", "pointer");

    nodeG.append("circle")
      .attr("r", (d) => (d.data.type === "standard" ? 10 : d.data.type === "domain" ? 7 : 5))
      .attr("fill", (d) => {
        if (d.data.type === "standard") return "#D04A02";
        if (d.data.type === "domain") return "#FFFFFF";
        return "#F5F5F5";
      })
      .attr("stroke", (d) => {
        if (d.data.type === "control" && coveredRef.current.has(d.data.name)) return "#16A34A";
        return TYPE_COLORS[d.data.type] ?? "#BDBDBD";
      })
      .attr("stroke-width", (d) => d.data.type === "control" && coveredRef.current.has(d.data.name) ? 2.5 : 2);

    // Outer ring for policy-covered controls
    nodeG.filter((d) => d.data.type === "control" && coveredRef.current.has(d.data.name))
      .append("circle")
      .attr("r", 8)
      .attr("fill", "none")
      .attr("stroke", "#16A34A")
      .attr("stroke-width", 1)
      .attr("stroke-dasharray", "3,2")
      .attr("opacity", 0.6);

    nodeG.append("text")
      .attr("dy", "0.31em")
      .attr("x", (d) => (d.children ? -14 : 10))
      .attr("text-anchor", (d) => (d.children ? "end" : "start"))
      .attr("fill", (d) => d.data.type === "standard" ? "#1A1A1A" : d.data.type === "domain" ? "#D04A02" : "#555555")
      .attr("font-size", (d) => (d.data.type === "standard" ? "11px" : "9px"))
      .attr("font-weight", (d) => (d.data.type === "standard" ? "600" : "400"))
      .text((d) => d.data.name);

    nodeG.on("click", (_, d) => {
      if (d.data.type === "control") {
        const std = d.ancestors().find((a) => a.data.type === "standard");
        handleNodeClick(std?.data.name ?? "", d.data.name);
      }
    });
  }, [getActiveDatasets, handleNodeClick]);

  const renderForce = useCallback(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    const container = svgRef.current?.parentElement;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const g = svg.append("g");

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom as unknown as (selection: d3.Selection<SVGSVGElement | null, unknown, null, undefined>) => void);

    const datasets = getActiveDatasets();
    const { nodes, links } = buildForceData(datasets);

    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink<ForceNode, ForceLink>(links).id((d) => d.id).distance((d) => {
        const target = d.target as ForceNode;
        return target.type === "control" ? 40 : target.type === "domain" ? 70 : 100;
      }))
      .force("charge", d3.forceManyBody().strength((d) => {
        const n = d as ForceNode;
        return n.type === "standard" ? -300 : n.type === "domain" ? -150 : -60;
      }))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius((d) => (TYPE_RADIUS[(d as ForceNode).type] ?? 5) + 4));

    // Links
    const link = g.selectAll<SVGLineElement, ForceLink>("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => {
        if (d.type === "SEMANTIC") return "#D04A02";
        const target = d.target as ForceNode;
        if (target.obligation === "must") return "#EB6524";
        return "#E0E0E0";
      })
      .attr("stroke-width", (d) => d.type === "SEMANTIC" ? 1.5 : 1)
      .attr("stroke-dasharray", (d) => {
        if (d.type === "SEMANTIC") return "5,3";
        const target = d.target as ForceNode;
        if (target.type === "control" && target.obligation !== "must") return "3,3";
        return "none";
      })
      .attr("stroke-opacity", (d) => d.type === "SEMANTIC" ? 0.6 : 1);

    // Nodes
    const node = g.selectAll<SVGCircleElement, ForceNode>("circle")
      .data(nodes)
      .join("circle")
      .attr("r", (d) => TYPE_RADIUS[d.type] ?? 5)
      .attr("fill", (d) => d.type === "standard" ? (STANDARD_COLORS[d.standard!] ?? "#D04A02") : "#FFFFFF")
      .attr("stroke", (d) => {
        if (d.type === "control" && coveredRef.current.has(d.name)) return "#16A34A";
        if (d.type === "standard") return STANDARD_COLORS[d.standard!] ?? "#D04A02";
        return TYPE_COLORS[d.type] ?? "#BDBDBD";
      })
      .attr("stroke-width", (d) => d.type === "control" && coveredRef.current.has(d.name) ? 2.5 : 2)
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGCircleElement, ForceNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null; d.fy = null;
          })
      );

    // Labels (only for standards and domains)
    const labels = g.selectAll<SVGTextElement, ForceNode>("text")
      .data(nodes.filter((n) => n.type !== "control"))
      .join("text")
      .text((d) => d.name)
      .attr("font-size", (d) => (d.type === "standard" ? "10px" : "8px"))
      .attr("font-weight", (d) => (d.type === "standard" ? "600" : "400"))
      .attr("fill", (d) => d.type === "standard" ? "#1A1A1A" : "#D04A02")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => (d.type === "standard" ? -16 : -12))
      .attr("pointer-events", "none");

    node.append("title").text((d) => `${d.type}: ${d.name}\n${d.urn}`);

    node.on("click", (event, d) => {
      event.stopPropagation();
      if (d.type === "control") handleNodeClick(d.standard ?? "", d.name);
    });

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as ForceNode).x!)
        .attr("y1", (d) => (d.source as ForceNode).y!)
        .attr("x2", (d) => (d.target as ForceNode).x!)
        .attr("y2", (d) => (d.target as ForceNode).y!);
      node.attr("cx", (d) => d.x!).attr("cy", (d) => d.y!);
      labels.attr("x", (d) => d.x!).attr("y", (d) => d.y!);
    });
  }, [getActiveDatasets, handleNodeClick]);

  const renderRadial = useCallback(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    const container = svgRef.current?.parentElement;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) / 2 - 40;

    svg.attr("viewBox", `0 0 ${width} ${height}`);
    const g = svg.append("g").attr("transform", `translate(${cx},${cy})`);

    const datasets = getActiveDatasets();
    const root = datasets.length === 1
      ? d3.hierarchy(buildTree(datasets[0]))
      : d3.hierarchy<TreeNode>({
          name: "Standards",
          id: "root",
          urn: "root",
          type: "standard",
          children: datasets.map((d) => buildTree(d)),
        });

    const radialLayout = d3.tree<TreeNode>()
      .size([2 * Math.PI, radius])
      .separation((a, b) => (a.parent === b.parent ? 1 : 2) / a.depth);

    radialLayout(root);

    // Links
    g.selectAll<SVGPathElement, d3.HierarchyPointLink<TreeNode>>("path.link")
      .data(root.links())
      .join("path")
      .attr("class", "link")
      .attr("fill", "none")
      .attr("stroke", (d) => {
        const target = d.target.data;
        if (target.type === "control" && target.obligation === "must") return "#D04A02";
        return "#2E2E2E";
      })
      .attr("stroke-width", 1)
      .attr("d", d3.linkRadial<d3.HierarchyPointLink<TreeNode>, d3.HierarchyPointNode<TreeNode>>()
        .angle((d) => d.x)
        .radius((d) => d.y) as unknown as string);

    // Nodes
    const nodeG = g
      .selectAll<SVGGElement, d3.HierarchyPointNode<TreeNode>>("g.node")
      .data(root.descendants())
      .join("g")
      .attr("class", "node")
      .attr("transform", (d) => `rotate(${((d.x ?? 0) * 180) / Math.PI - 90}) translate(${d.y ?? 0},0)`)
      .attr("cursor", "pointer");

    nodeG.append("circle")
      .attr("r", (d) => (d.data.type === "standard" ? 8 : d.data.type === "domain" ? 5 : 3))
      .attr("fill", (d) => d.data.type === "standard" ? "#D04A02" : "#FFFFFF")
      .attr("stroke", (d) => TYPE_COLORS[d.data.type] ?? "#BDBDBD")
      .attr("stroke-width", 1.5);

    nodeG.append("text")
      .attr("dy", "0.31em")
      .attr("x", (d) => ((d.x ?? 0) < Math.PI === !d.children ? 8 : -8))
      .attr("text-anchor", (d) => ((d.x ?? 0) < Math.PI === !d.children ? "start" : "end"))
      .attr("transform", (d) => ((d.x ?? 0) >= Math.PI ? "rotate(180)" : null))
      .attr("fill", (d) => d.data.type === "standard" ? "#1A1A1A" : d.data.type === "domain" ? "#D04A02" : "#555555")
      .attr("font-size", (d) => (d.data.type === "standard" ? "10px" : "8px"))
      .attr("font-weight", (d) => (d.data.type === "standard" ? "600" : "400"))
      .text((d) => d.data.name);

    nodeG.on("click", (_, d) => {
      if (d.data.type === "control") {
        const std = d.ancestors().find((a) => a.data.type === "standard");
        handleNodeClick(std?.data.name ?? "", d.data.name);
      }
    });
  }, [getActiveDatasets, handleNodeClick]);

  const render = useCallback(() => {
    switch (layoutMode) {
      case "tree": renderTree(); break;
      case "force": renderForce(); break;
      case "radial": renderRadial(); break;
    }
  }, [layoutMode, renderTree, renderForce, renderRadial]);

  useEffect(() => {
    render();
    const resizeObserver = new ResizeObserver(() => render());
    if (svgRef.current?.parentElement) {
      resizeObserver.observe(svgRef.current.parentElement);
    }
    return () => resizeObserver.disconnect();
  }, [render]);

  const allStandards = ALL_STANDARDS.map((s) => ({ key: s.standard_name, label: s.short_name }));

  return (
    <div className="flex flex-col w-full h-full">
      <div className="flex items-center gap-2 px-2 py-1 bg-pwc-surface border-b border-pwc-border shrink-0 flex-wrap">
        {/* Standard selectors */}
        <span className="text-[9px] text-pwc-text-dim">STD:</span>
        {allStandards.map((std) => (
          <button
            key={std.key}
            onClick={() => toggleStandard(std.key)}
            className={clsx(
              "px-2 py-0.5 text-[9px] border rounded transition-colors",
              activeStandards.has(std.key)
                ? "text-white bg-pwc-orange border-pwc-orange"
                : "text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
            )}
          >
            {std.label}
          </button>
        ))}

        <span className="text-pwc-border mx-1">|</span>

        {/* Layout selectors */}
        <span className="text-[9px] text-pwc-text-dim">LAYOUT:</span>
        {(["tree", "force", "radial"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setLayoutMode(mode)}
            className={clsx(
              "px-2 py-0.5 text-[9px] border rounded transition-colors capitalize",
              layoutMode === mode
                ? "text-white bg-pwc-orange border-pwc-orange"
                : "text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
            )}
          >
            {mode}
          </button>
        ))}

        <span className="ml-auto flex items-center gap-2 text-[8px] text-pwc-text-muted">
          Click node to trace &middot; Solid=MUST Dashed=SHALL &middot; <span className="text-pwc-orange">Orange=Semantic</span>
          {coveredControlIds && coveredControlIds.size > 0 && (
            <span className="flex items-center gap-1 text-green-700 font-semibold">
              <svg width="10" height="10" viewBox="0 0 10 10">
                <circle cx="5" cy="5" r="3.5" fill="none" stroke="#16A34A" strokeWidth="1.5" strokeDasharray="3,2" />
              </svg>
              Green ring = in generated policy ({coveredControlIds.size})
            </span>
          )}
        </span>
      </div>
      <div className="flex-1 min-h-0" style={{ background: "var(--pwc-bg)" }}>
        <svg ref={svgRef} className="w-full h-full" />
      </div>
    </div>
  );
}
