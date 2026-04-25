"use client";

import { useEffect, useState, useCallback, useRef, type ChangeEvent } from "react";
import { clsx } from "clsx";
import { fetchArrWorksheet, uploadArrObjectives, downloadRiskRegister, downloadRiskRegisterExcel, type ArrRow } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { getAllControls } from "@/lib/standardsEngine";

// Derive a risk name from the control's domain/requirement
function deriveRiskName(domain: string | null | undefined): string {
  if (!domain) return "Operational Risk";
  const d = domain.toLowerCase();
  if (d.includes("access") || d.includes("identity") || d.includes("authentication")) return "Unauthorized Access";
  if (d.includes("segregation") || d.includes("sod") || d.includes("separation")) return "SoD Violation";
  if (d.includes("data") && (d.includes("protect") || d.includes("privacy") || d.includes("loss"))) return "Data Breach";
  if (d.includes("vendor") || d.includes("third party") || d.includes("supplier")) return "Third-Party Risk";
  if (d.includes("incident") || d.includes("detection") || d.includes("response")) return "Undetected Incident";
  if (d.includes("compliance") || d.includes("regulat") || d.includes("audit")) return "Regulatory Non-Compliance";
  if (d.includes("continuity") || d.includes("resilience") || d.includes("recovery")) return "Business Disruption";
  if (d.includes("cloud") || d.includes("infrastructure")) return "Cloud Security Risk";
  if (d.includes("cyber") || d.includes("threat") || d.includes("vulnerability")) return "Cyber Threat";
  if (d.includes("fraud") || d.includes("financial")) return "Fraud Risk";
  if (d.includes("change") || d.includes("patch") || d.includes("config")) return "Misconfiguration Risk";
  if (d.includes("physical") || d.includes("facilities")) return "Physical Security Risk";
  return `${domain} Risk`;
}

// Generate realistic risk rows from real standards data
function buildDemoRows(): ArrRow[] {
  const allCtrls = getAllControls();
  const statuses: ArrRow["status"][] = ["PASSING", "WARNING", "FAILING", "OVERDUE"];
  const ratings: ArrRow["risk_rating"][] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

  // Deterministic pseudo-random based on control index
  const hash = (s: string) => {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  };

  // Sample controls spread across all standards (take every Nth to get ~40-50 rows)
  const step = Math.max(1, Math.floor(allCtrls.length / 45));
  const sampled = allCtrls.filter((_, i) => i % step === 0);

  return sampled.map((ctrl) => {
    const h = hash(ctrl.id);
    const statusIdx = h % 4;
    const status = statuses[statusIdx];
    const ratingIdx = status === "FAILING" ? 3 : status === "OVERDUE" ? 2 : status === "WARNING" ? 1 : 0;
    const rating = ratings[ratingIdx];
    const violations = status === "PASSING" ? (h % 3 === 0 ? 0 : 1) : status === "WARNING" ? 2 + (h % 5) : status === "OVERDUE" ? 4 + (h % 8) : 8 + (h % 15);
    const dayOffset = (h % 30) + 1;
    const lastEvent = status === "PASSING" && violations === 0 ? null : `2025-01-${String(Math.min(dayOffset, 28)).padStart(2, "0")}T${String(8 + (h % 14)).padStart(2, "0")}:${String(h % 60).padStart(2, "0")}:00Z`;

    return {
      control_urn: `urn:pwc:ctrl:${(ctrl.id ?? "unknown").toLowerCase().replace(/[^a-z0-9]/g, "-")}`,
      control_name: ctrl.name ?? ctrl.id ?? "Unnamed Control",
      standard: ctrl.standardName ?? "Unknown",
      requirement: ctrl.domainName ?? "",
      status,
      violation_count: violations,
      risk_rating: rating,
      last_event: lastEvent,
      associated_risks: deriveRiskName(ctrl.domainName),
    };
  });
}

const DEMO_ROWS: ArrRow[] = buildDemoRows();

export default function ArrWorksheet() {
  const [rows, setRows] = useState<ArrRow[]>(DEMO_ROWS);
  const [sortField, setSortField] = useState<keyof ArrRow>("violation_count");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(false);
  const [filterStandard, setFilterStandard] = useState<string>("all");
  const [uploadStatus, setUploadStatus] = useState<string>("");
  const [selectedUrn, setSelectedUrn] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchArrWorksheet();
      if (data.rows.length > 0) setRows(data.rows);
    } catch {
      // Keep demo data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filtered = filterStandard === "all"
    ? rows
    : rows.filter((r) => r.standard === filterStandard);

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortField];
    const bv = b[sortField];
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") {
      return sortDir === "asc" ? av - bv : bv - av;
    }
    return sortDir === "asc"
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  });

  const handleSort = (field: keyof ArrRow) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const handleRowClick = (row: ArrRow) => {
    setSelectedUrn((prev) => prev === row.control_urn ? null : row.control_urn);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadStatus("Uploading objectives and generating risk register...");
    try {
      const res = await uploadArrObjectives(file);
      setUploadStatus(`Uploaded ${res.total_objectives} objectives | ${res.total_risks} risks generated — risk register updated`);
      setFilterStandard("all"); // Reset filter so uploaded rows are visible
      // Set rows directly from upload response for immediate feedback
      if (Array.isArray(res.risk_register) && res.risk_register.length > 0) {
        setRows(res.risk_register as ArrRow[]);
      } else {
        // Fallback: re-fetch from backend (Redis-cached)
        await loadData();
      }
    } catch {
      setUploadStatus("Upload failed. Use CSV or XLSX with columns: title, priority, owner, BU.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleExport = async () => {
    setUploadStatus("Exporting risk register...");
    try {
      const { blob, filename } = await downloadRiskRegister();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename ?? "PwC_Risk_Register.csv";
      anchor.click();
      URL.revokeObjectURL(url);
      setUploadStatus(`Downloaded ${filename ?? "risk register"}`);
    } catch {
      setUploadStatus("Export failed.");
    }
  };

  const handleExportExcel = async () => {
    setUploadStatus("Exporting risk register (Excel)...");
    try {
      const { blob, filename } = await downloadRiskRegisterExcel();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename ?? "PwC_Risk_Register.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
      setUploadStatus(`Downloaded ${filename ?? "risk register excel"}`);
    } catch {
      setUploadStatus("Excel export failed.");
    }
  };

  const statusColors: Record<string, string> = {
    FAILING: "text-risk-critical",
    OVERDUE: "text-risk-high",
    WARNING: "text-risk-medium",
    PASSING: "text-risk-low",
  };

  const standards = ["all", ...Array.from(new Set(rows.map((r) => r.standard)))];

  const summary = {
    total: filtered.length,
    critical: filtered.filter((r) => r.risk_rating === "CRITICAL").length,
    high: filtered.filter((r) => r.risk_rating === "HIGH").length,
    failing: filtered.filter((r) => r.status === "FAILING").length,
  };

  const ColHeader = ({ field, label, w }: { field: keyof ArrRow; label: string; w: string }) => (
    <th
      className={clsx(
        "px-1.5 py-1 text-left text-[9px] font-bold uppercase tracking-wider cursor-pointer select-none",
        "text-pwc-text-dim hover:text-pwc-orange border-b border-pwc-border",
        w
      )}
      onClick={() => handleSort(field)}
    >
      {label}
      {sortField === field && (
        <span className="ml-0.5 text-pwc-orange">{sortDir === "asc" ? "\u25b2" : "\u25bc"}</span>
      )}
    </th>
  );

  return (
    <div className="flex flex-col w-full h-full">
      {/* Filter & Summary Bar */}
      <div className="flex items-center gap-2 px-2 py-1 bg-pwc-surface border-b border-pwc-border shrink-0 flex-wrap">
        <span className="text-[9px] text-pwc-text-dim">FILTER:</span>
        {standards.map((std) => (
          <button
            key={std}
            onClick={() => setFilterStandard(std)}
            className={clsx(
              "px-1.5 py-0.5 text-[8px] border rounded transition-colors",
              filterStandard === std
                ? "text-white bg-pwc-orange border-pwc-orange"
                : "text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
            )}
          >
            {std === "all" ? "ALL" : std}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-2 text-[8px]">
          <span className="text-pwc-text-muted">{summary.total} risks</span>
          {summary.critical > 0 && <span className="text-risk-critical font-bold">{summary.critical} CRIT</span>}
          {summary.high > 0 && <span className="text-risk-high font-bold">{summary.high} HIGH</span>}
          {summary.failing > 0 && <span className="text-risk-critical">{summary.failing} FAILING</span>}
        </span>
        <div className="flex items-center gap-1">
          <input ref={fileInputRef} type="file" accept=".csv,.xlsx" onChange={handleFileChange} className="hidden" />
          <button
            onClick={handleUploadClick}
            className="px-1.5 py-0.5 text-[8px] border rounded text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
          >
            Upload Objectives
          </button>
          <button
            onClick={handleExport}
            className="px-1.5 py-0.5 text-[8px] border rounded text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
          >
            Export CSV
          </button>
          <button
            onClick={handleExportExcel}
            className="px-1.5 py-0.5 text-[8px] border rounded text-pwc-text-dim border-pwc-border hover:border-pwc-border-bright"
          >
            Export Excel
          </button>
        </div>
      </div>
      {uploadStatus && (
        <div className="px-2 py-1 text-[8px] text-pwc-text-dim border-b border-pwc-border bg-pwc-bg">
          {uploadStatus}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-[11px] border-collapse">
          <thead className="sticky top-0 bg-pwc-surface z-10">
            <tr>
              <ColHeader field="associated_risks" label="Risk" w="w-[20%]" />
              <ColHeader field="risk_rating" label="Rating" w="w-[8%]" />
              <ColHeader field="status" label="Status" w="w-[9%]" />
              <ColHeader field="violation_count" label="Violations" w="w-[8%]" />
              <ColHeader field="control_name" label="Associated Control" w="w-[20%]" />
              <ColHeader field="standard" label="Std" w="w-[9%]" />
              <ColHeader field="requirement" label="Requirement" w="w-[14%]" />
              <ColHeader field="last_event" label="Last Event" w="w-[12%]" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.control_urn}
                className={clsx(
                  "border-b border-pwc-border/50 cursor-pointer transition-colors",
                  selectedUrn === row.control_urn
                    ? "bg-pwc-orange/10"
                    : "hover:bg-pwc-surface/50"
                )}
                onClick={() => handleRowClick(row)}
              >
                <td className="px-1.5 py-1 text-pwc-text font-medium truncate">
                  {row.associated_risks ?? deriveRiskName(row.requirement)}
                </td>
                <td className="px-1.5 py-1">
                  <StatusBadge rating={row.risk_rating} />
                </td>
                <td className={clsx("px-1.5 py-1 font-bold text-[10px]", statusColors[row.status] ?? "text-pwc-text-dim")}>
                  {row.status}
                </td>
                <td className="px-1.5 py-1 text-right tabular-nums">
                  <span className={row.violation_count > 0 ? "text-risk-critical" : "text-pwc-text-dim"}>
                    {row.violation_count}
                  </span>
                </td>
                <td className="px-1.5 py-1 text-pwc-text-dim truncate text-[10px]">{row.control_name}</td>
                <td className="px-1.5 py-1 text-pwc-text-dim truncate text-[10px]">{row.standard}</td>
                <td className="px-1.5 py-1 text-pwc-text-dim truncate text-[10px]">{row.requirement}</td>
                <td className="px-1.5 py-1 text-pwc-text-muted tabular-nums text-[10px]" suppressHydrationWarning>
                  {row.last_event ? new Date(row.last_event).toLocaleString() : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && (
          <div className="text-center py-2 text-[10px] text-pwc-text-muted">
            Loading worksheet...
          </div>
        )}
      </div>
    </div>
  );
}
