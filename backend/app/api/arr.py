"""ARR — Audit Risk Register API.

Provides endpoints to:
- Fetch the risk worksheet (Redis-cached or empty fallback)
- Upload CSV/XLSX objectives and generate risk register rows
- Export risk register as CSV or Excel

No Neo4j dependency — pure Redis + in-memory.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.services.database import get_redis

router = APIRouter()

REDIS_KEY = "pwc:risk_register_upload"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _parse_csv_rows(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def _parse_xlsx_rows(content: bytes) -> list[dict]:
    try:
        zipfile.ZipFile(io.BytesIO(content)).close()
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid XLSX file — ensure the file is a valid Excel workbook.")

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared_strings: list[str] = []
        try:
            with zf.open("xl/sharedStrings.xml") as fh:
                root = ElementTree.fromstring(fh.read())
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            for si in root.findall(f".//{ns}si"):
                texts = [t.text or "" for t in si.findall(f".//{ns}t")]
                shared_strings.append("".join(texts))
        except KeyError:
            shared_strings = []

        with zf.open("xl/worksheets/sheet1.xml") as fh:
            sheet = ElementTree.fromstring(fh.read())

        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        rows: list[list[str]] = []
        for row in sheet.findall(f".//{ns}row"):
            values: dict[int, str] = {}
            for c in row.findall(f"{ns}c"):
                r_attr = c.attrib.get("r", "")
                m = re.match(r"([A-Z]+)", r_attr)
                if not m:
                    continue
                col = 0
                for ch in m.group(1):
                    col = col * 26 + (ord(ch) - 64)
                v = c.find(f"{ns}v")
                if v is None or v.text is None:
                    continue
                val = v.text
                if c.attrib.get("t") == "s":
                    idx = int(val)
                    val = shared_strings[idx] if idx < len(shared_strings) else ""
                values[col] = val
            if values:
                max_col = max(values.keys())
                row_vals = [values.get(i + 1, "") for i in range(max_col)]
                rows.append(row_vals)

        if not rows:
            return []

        header = rows[0]
        data_rows = rows[1:]
        results = []
        for r in data_rows:
            row_dict = {}
            for i, h in enumerate(header):
                key = h if isinstance(h, str) else ""
                row_dict[key] = r[i] if i < len(r) else ""
            results.append(row_dict)
        return results


def _map_objective_rows(rows: list[dict]) -> list[dict]:
    mapped = []
    for row in rows:
        normalized = {
            _normalize_header(k or ""): (v or "").strip() if isinstance(v, str) else v
            for k, v in row.items()
        }
        title = (
            normalized.get("objective")
            or normalized.get("title")
            or normalized.get("name")
            or normalized.get("objectivetitle")
        )
        if not title:
            continue
        priority = normalized.get("priority") or normalized.get("prio") or "medium"
        owner = normalized.get("owner") or normalized.get("riskowner") or normalized.get("lead") or "Unassigned"
        bu = normalized.get("bu") or normalized.get("businessunit") or normalized.get("business_unit") or "Unknown"
        sub = (
            normalized.get("subobjective")
            or normalized.get("subobj")
            or normalized.get("sub")
            or normalized.get("subobjectives")
            or ""
        )
        mapped.append({
            "title": title,
            "priority": str(priority).strip().lower(),
            "owner": owner,
            "business_unit": bu,
            "sub_objective": sub.strip() if isinstance(sub, str) else "",
        })
    return mapped


def _domain_from(text: str) -> str:
    """Map a text string to a control domain category via keyword matching."""
    if not text:
        return ""
    t = text.lower()
    if any(k in t for k in ("access", "identity", "auth", "login", "mfa", "sso")):
        return "Access Control & Identity Management"
    if any(k in t for k in ("data", "privacy", "classification", "dlp", "pii")):
        return "Data Protection & Privacy"
    if any(k in t for k in ("vendor", "third", "supplier", "outsourc")):
        return "Third-Party & Vendor Risk"
    if any(k in t for k in ("incident", "breach", "response", "detect", "siem", "soc")):
        return "Incident Detection & Response"
    if any(k in t for k in ("continuity", "disaster", "recovery", "resilience", "rto", "rpo")):
        return "Business Continuity & Resilience"
    if any(k in t for k in ("cloud", "infra", "network", "server", "firewall", "vpn")):
        return "Cloud & Infrastructure Security"
    if any(k in t for k in ("compliance", "regulat", "audit", "governance", "policy")):
        return "Compliance & Governance"
    if any(k in t for k in ("fraud", "financial", "payment", "transact", "aml")):
        return "Financial Risk & Fraud"
    if any(k in t for k in ("change", "patch", "config", "deploy", "release", "cicd")):
        return "Change & Configuration Management"
    return ""


def _generate_hypotheses(objectives: list[dict]) -> list[dict]:
    """Generate ArrRow-compatible risk register rows from parsed objectives."""
    rows = []
    now = datetime.utcnow().isoformat() + "Z"
    for idx, obj in enumerate(objectives, start=1):
        priority = (obj.get("priority") or "medium").lower()
        title = obj.get("title") or "Objective"
        bu = obj.get("business_unit") or "Unknown"
        owner = obj.get("owner") or "Unassigned"

        if priority == "critical":
            status = "FAILING"
            violation_count = 12
            risk_rating = "CRITICAL"
        elif priority == "high":
            status = "FAILING"
            violation_count = 8
            risk_rating = "HIGH"
        elif priority == "medium":
            status = "WARNING"
            violation_count = 3
            risk_rating = "MEDIUM"
        else:  # low or unrecognised
            status = "PASSING"
            violation_count = 0
            risk_rating = "LOW"

        sub = obj.get("sub_objective") or ""
        control_urn = f"urn:pwc:ctrl:obj-{idx:04d}"

        req = _domain_from(sub) or _domain_from(title) or f"{bu} — Operational Risk"

        if sub:
            control_name = sub[:80]
        else:
            control_name = f"Control: {title[:60]}"

        rows.append({
            "control_urn": control_urn,
            "control_name": control_name,
            "standard": "Uploaded Objectives",
            "requirement": req,
            "status": status,
            "violation_count": violation_count,
            "risk_rating": risk_rating,
            "last_event": now if violation_count > 0 else None,
            "associated_risks": title,
            "objective": sub or None,
            "owner": owner,
            "business_unit": bu,
        })
    return rows


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def arr_worksheet():
    """Fetch the risk worksheet. Returns cached data if available, else empty."""
    try:
        r = await get_redis()
        cached = await r.get(REDIS_KEY)
        if cached:
            payload = json.loads(cached)
            rows = payload.get("risk_register", [])
            if rows:
                return {"rows": rows, "total": len(rows)}
    except Exception:
        pass

    return {"rows": [], "total": 0}


@router.post("/upload")
async def upload_arr_objectives(file: UploadFile = File(...)):
    """Upload objectives (CSV/XLSX), generate risk hypotheses, and cache risk register."""
    filename = file.filename or ""
    content = await file.read()

    if filename.lower().endswith(".csv"):
        rows = _parse_csv_rows(content)
    elif filename.lower().endswith(".xlsx"):
        rows = _parse_xlsx_rows(content)
    else:
        raise HTTPException(400, "Only .csv or .xlsx files are accepted")

    objectives = _map_objective_rows(rows)
    if not objectives:
        raise HTTPException(
            400,
            "No objective rows found. Ensure columns: title, priority, owner, BU."
        )

    risks = _generate_hypotheses(objectives)

    try:
        r = await get_redis()
        payload = {
            "objectives": objectives,
            "risk_register": risks,
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        await r.setex(REDIS_KEY, 604800, json.dumps(payload))
    except Exception:
        pass  # Redis may be unavailable; still return data

    return {
        "objectives": objectives,
        "risk_register": risks,
        "total_objectives": len(objectives),
        "total_risks": len(risks),
    }


@router.get("/export/csv")
async def export_csv():
    """Export the cached risk register as a CSV file."""
    rows: list[dict] = []
    try:
        r = await get_redis()
        cached = await r.get(REDIS_KEY)
        if cached:
            payload = json.loads(cached)
            rows = payload.get("risk_register", [])
    except Exception:
        pass

    output = io.StringIO()
    fieldnames = [
        "control_urn", "control_name", "standard", "requirement",
        "status", "violation_count", "risk_rating", "last_event",
        "associated_risks", "owner", "business_unit",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"PwC_Risk_Register_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/excel")
async def export_excel():
    """Export the cached risk register as a minimal XLSX file."""
    rows: list[dict] = []
    try:
        r = await get_redis()
        cached = await r.get(REDIS_KEY)
        if cached:
            payload = json.loads(cached)
            rows = payload.get("risk_register", [])
    except Exception:
        pass

    # Build a minimal XLSX manually (no openpyxl dependency)
    fieldnames = [
        "control_urn", "control_name", "standard", "requirement",
        "status", "violation_count", "risk_rating", "last_event",
        "associated_risks", "owner", "business_unit",
    ]

    def _xml_escape(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    shared: list[str] = []
    shared_index: dict[str, int] = {}

    def _str_idx(val: str) -> int:
        if val not in shared_index:
            shared_index[val] = len(shared)
            shared.append(val)
        return shared_index[val]

    # Build rows data
    data_rows: list[list[tuple[str, str]]] = []  # list of rows, each cell is (type, value)
    header_row: list[tuple[str, str]] = [("s", str(_str_idx(f))) for f in fieldnames]
    data_rows.append(header_row)

    for row in rows:
        cells = []
        for f in fieldnames:
            val = row.get(f)
            if val is None:
                val = ""
            if isinstance(val, (int, float)):
                cells.append(("n", str(val)))
            else:
                cells.append(("s", str(_str_idx(str(val)))))
        data_rows.append(cells)

    # Build sheet XML
    sheet_rows_xml = ""
    for r_idx, row in enumerate(data_rows, start=1):
        cells_xml = ""
        for c_idx, (cell_type, cell_val) in enumerate(row, start=1):
            col_letter = chr(64 + c_idx) if c_idx <= 26 else "A" + chr(64 + c_idx - 26)
            ref = f"{col_letter}{r_idx}"
            if cell_type == "n":
                cells_xml += f'<c r="{ref}"><v>{cell_val}</v></c>'
            else:
                cells_xml += f'<c r="{ref}" t="s"><v>{cell_val}</v></c>'
        sheet_rows_xml += f"<row r=\"{r_idx}\">{cells_xml}</row>"

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{sheet_rows_xml}</sheetData>"
        "</worksheet>"
    )

    # Build shared strings XML
    ss_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared)}" uniqueCount="{len(shared)}">'
    )
    for s in shared:
        ss_xml += f"<si><t>{_xml_escape(s)}</t></si>"
    ss_xml += "</sst>"

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets><sheet name=\"Risk Register\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/sharedStrings.xml", ss_xml)

    buf.seek(0)
    filename = f"PwC_Risk_Register_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
