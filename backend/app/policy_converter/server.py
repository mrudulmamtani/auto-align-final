"""
AutoAlign Policy Converter Platform — FastAPI REST Server.

Routes:
  GET  /                         — serve the SPA
  GET  /addin/taskpane.html      — Office.js Add-in task pane
  GET  /addin/taskpane.js        — Office.js Add-in logic

  GET  /api/documents            — list all generated docs with metadata
  GET  /api/documents/{doc_id}   — doc detail + forensic map (if extracted)
  POST /api/forensics/extract    — trigger forensic extraction for a doc
  POST /api/forensics/extract-all— extract all docs
  GET  /api/forensics/{doc_id}   — get saved forensic map JSON
  POST /api/forensics/update     — update map from Office.js accurate page data

  GET  /api/templates            — list uploaded org templates
  POST /api/templates/upload     — upload org template DOCX + config
  DELETE /api/templates/{org_id} — delete a template

  POST /api/convert              — convert doc to org template; returns DOCX
  GET  /api/download/{filename}  — download a file from output directories
"""
import glob
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse, JSONResponse, HTMLResponse, StreamingResponse
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .schemas import TemplateConfig, ForensicDocumentMap
from .forensics import extract_forensic_map, find_artifacts, extract_all, update_from_officejs
from .converter import convert_document, update_forensic_after_conversion

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent.parent
POLICY_OUTPUT    = BASE_DIR / "policy_output"
FORENSIC_MAPS    = BASE_DIR / "forensic_maps"
ORG_TEMPLATES    = BASE_DIR / "org_templates"
CONVERTED_OUTPUT = BASE_DIR / "converted_output"
UI_DIR           = BASE_DIR / "converter_ui"
ADDIN_DIR        = BASE_DIR / "addin"

for d in [FORENSIC_MAPS, ORG_TEMPLATES, CONVERTED_OUTPUT]:
    d.mkdir(exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AutoAlign Policy Converter",
    description="Dynamic policy template conversion platform with forensic reader",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SPA + Add-in serving ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_spa():
    index = UI_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>UI not found</h1>", status_code=404)


@app.get("/addin/taskpane.html", response_class=HTMLResponse)
async def serve_addin_html():
    p = ADDIN_DIR / "taskpane.html"
    if p.exists():
        return HTMLResponse(content=p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Add-in not built</h1>", status_code=404)


@app.get("/addin/taskpane.js")
async def serve_addin_js():
    p = ADDIN_DIR / "taskpane.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript")
    raise HTTPException(404, "Add-in JS not found")


@app.get("/addin/manifest.xml")
async def serve_manifest():
    p = ADDIN_DIR / "manifest.xml"
    if p.exists():
        return FileResponse(str(p), media_type="application/xml")
    raise HTTPException(404, "manifest.xml not found")


# ── Document listing ──────────────────────────────────────────────────────────

def _load_all_results() -> list[dict]:
    """Load all *_0_result.json files, deduplicated by doc_id (latest wins)."""
    seen: dict[str, dict] = {}
    for rp in sorted(glob.glob(str(POLICY_OUTPUT / "*_0_result.json"))):
        try:
            with open(rp) as f:
                d = json.load(f)
            did = d.get("doc_id")
            if did:
                d["_result_path"] = rp
                seen[did] = d
        except Exception:
            pass
    return list(seen.values())


def _forensic_map_path(doc_id: str) -> Path:
    return FORENSIC_MAPS / f"{doc_id}_forensic_map.json"


def _load_forensic_map(doc_id: str) -> Optional[dict]:
    p = _forensic_map_path(doc_id)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


@app.get("/api/documents")
async def list_documents():
    results = _load_all_results()
    docs = []
    for r in sorted(results, key=lambda x: x.get("doc_id", "")):
        fmap = _load_forensic_map(r["doc_id"])
        docs.append({
            "doc_id": r.get("doc_id"),
            "document_type": r.get("document_type", "policy"),
            "title": r.get("title", ""),
            "version": r.get("version", "1.0"),
            "qa_passed": r.get("qa_passed", False),
            "shall_count": r.get("shall_count", 0),
            "traced_count": r.get("traced_count", 0),
            "main_docx": r.get("main_docx", ""),
            "has_forensic_map": fmap is not None,
            "forensic_controls": len(fmap.get("control_locations", [])) if fmap else 0,
            "has_conversion": fmap.get("converted_docx") if fmap else None,
        })
    return {"documents": docs, "total": len(docs)}


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    results = _load_all_results()
    r = next((x for x in results if x.get("doc_id") == doc_id), None)
    if not r:
        raise HTTPException(404, f"Document {doc_id} not found")
    fmap = _load_forensic_map(doc_id)
    return {"result": r, "forensic_map": fmap}


# ── Forensic extraction ───────────────────────────────────────────────────────

@app.post("/api/forensics/extract")
async def extract_forensics(body: dict):
    """Trigger forensic extraction for one document."""
    doc_id = body.get("doc_id")
    if not doc_id:
        raise HTTPException(400, "doc_id required")
    try:
        arts = find_artifacts(str(POLICY_OUTPUT), doc_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    if not arts.get("draft_json"):
        raise HTTPException(404, f"No draft JSON found for {doc_id}")

    fmap = extract_forensic_map(
        doc_id=doc_id,
        docx_path=arts["main_docx"],
        result_json_path=arts["result_json"],
        bundles_json_path=arts["bundles_json"],
        draft_json_path=arts["draft_json"],
        traceability_docx_path=arts["traceability_docx"],
        output_dir=str(FORENSIC_MAPS),
    )
    return {
        "doc_id": doc_id,
        "sections": len(fmap.section_locations),
        "controls": len(fmap.control_locations),
        "estimated_pages": fmap.estimated_pages,
        "forensic_map": fmap.model_dump(),
    }


@app.post("/api/forensics/extract-all")
async def extract_all_forensics(background_tasks: BackgroundTasks):
    """Trigger background forensic extraction for all documents."""
    def _run():
        maps = extract_all(str(POLICY_OUTPUT), str(FORENSIC_MAPS))
        print(f"[Server] Extracted {len(maps)} forensic maps")

    background_tasks.add_task(_run)
    return {"message": "Forensic extraction started in background"}


@app.get("/api/forensics/{doc_id}")
async def get_forensic_map(doc_id: str):
    fmap = _load_forensic_map(doc_id)
    if not fmap:
        raise HTTPException(404, f"No forensic map found for {doc_id}. Run extraction first.")
    return fmap


@app.post("/api/forensics/update")
async def update_forensics_from_officejs(body: dict):
    """
    Receive accurate page numbers from the Office.js add-in and update
    the stored forensic map.

    Body: { "doc_id": "POL-01", "control_locations": [...], "section_locations": [...] }
    """
    doc_id = body.get("doc_id")
    if not doc_id:
        raise HTTPException(400, "doc_id required")

    fmap_dict = _load_forensic_map(doc_id)
    if not fmap_dict:
        raise HTTPException(404, f"No forensic map for {doc_id}")

    fmap = ForensicDocumentMap(**fmap_dict)
    fmap = update_from_officejs(fmap, body, str(FORENSIC_MAPS))
    return {"doc_id": doc_id, "updated_controls": len(fmap.control_locations)}


# ── Template management ───────────────────────────────────────────────────────

def _template_dir(org_id: str) -> Path:
    return ORG_TEMPLATES / org_id


@app.get("/api/templates")
async def list_templates():
    templates = []
    for p in ORG_TEMPLATES.iterdir():
        if p.is_dir():
            cfg_p = p / "config.json"
            if cfg_p.exists():
                with open(cfg_p) as f:
                    cfg = json.load(f)
                templates.append({
                    "org_id": p.name,
                    "org_name": cfg.get("org_name", p.name),
                    "template_id": cfg.get("template_id", ""),
                    "primary_color": cfg.get("primary_color", "#1F497D"),
                    "has_logo": (p / cfg.get("logo_filename", "logo.png")).exists()
                    if cfg.get("logo_filename") else False,
                    "created_at": cfg.get("created_at", ""),
                })
    return {"templates": templates}


@app.post("/api/templates/upload")
async def upload_template(
    org_name: str = Form(...),
    org_id: str = Form(...),
    primary_color: str = Form("#1F497D"),
    secondary_color: str = Form("#4472C4"),
    font_family: str = Form("Calibri"),
    header_right: str = Form("CONFIDENTIAL"),
    footer_center: str = Form("Page {page} of {total}"),
    footer_right: str = Form(""),
    logo: Optional[UploadFile] = File(None),
    template_docx: Optional[UploadFile] = File(None),
):
    org_id = re.sub(r"[^\w\-]", "-", org_id.lower())[:40]
    tdir = _template_dir(org_id)
    tdir.mkdir(exist_ok=True)

    logo_filename = None
    if logo and logo.filename:
        ext = Path(logo.filename).suffix or ".png"
        logo_filename = f"logo{ext}"
        content = await logo.read()
        with open(tdir / logo_filename, "wb") as f:
            f.write(content)

    template_docx_filename = None
    if template_docx and template_docx.filename:
        template_docx_filename = "template.docx"
        content = await template_docx.read()
        with open(tdir / template_docx_filename, "wb") as f:
            f.write(content)

    cfg = TemplateConfig(
        org_name=org_name,
        org_id=org_id,
        template_id=str(uuid.uuid4())[:8],
        logo_filename=logo_filename,
        primary_color=primary_color,
        secondary_color=secondary_color,
        font_family=font_family,
        header_right=header_right,
        footer_center=footer_center,
        footer_right=footer_right,
    )

    with open(tdir / "config.json", "w") as f:
        json.dump(cfg.model_dump(), f, indent=2)

    return {"org_id": org_id, "org_name": org_name, "template_id": cfg.template_id}


@app.get("/api/templates/{org_id}/logo")
async def get_template_logo(org_id: str):
    tdir = _template_dir(org_id)
    cfg_path = tdir / "config.json"
    if not cfg_path.exists():
        raise HTTPException(404, f"Template {org_id} not found")
    with open(cfg_path) as f:
        cfg = json.load(f)
    logo_fn = cfg.get("logo_filename")
    if not logo_fn:
        raise HTTPException(404, "No logo for this template")
    lp = tdir / logo_fn
    if not lp.exists():
        raise HTTPException(404, "Logo file not found")
    ext = lp.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "svg": "image/svg+xml"}.get(ext.lstrip("."), "image/png")
    return FileResponse(str(lp), media_type=mime)


@app.delete("/api/templates/{org_id}")
async def delete_template(org_id: str):
    tdir = _template_dir(org_id)
    if not tdir.exists():
        raise HTTPException(404, f"Template {org_id} not found")
    shutil.rmtree(tdir)
    return {"deleted": org_id}


# ── Conversion ────────────────────────────────────────────────────────────────

class ConvertRequest(BaseModel):
    doc_id: str
    org_id: str


@app.post("/api/convert")
async def convert_doc(req: ConvertRequest):
    """Convert a policy/standard to an org template."""
    # Load forensic map
    fmap_dict = _load_forensic_map(req.doc_id)
    if not fmap_dict:
        # Auto-extract first
        try:
            arts = find_artifacts(str(POLICY_OUTPUT), req.doc_id)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        fmap = extract_forensic_map(
            doc_id=req.doc_id,
            docx_path=arts["main_docx"],
            result_json_path=arts["result_json"],
            bundles_json_path=arts["bundles_json"],
            draft_json_path=arts["draft_json"],
            traceability_docx_path=arts["traceability_docx"],
            output_dir=str(FORENSIC_MAPS),
        )
    else:
        fmap = ForensicDocumentMap(**fmap_dict)

    # Load template config
    tdir = _template_dir(req.org_id)
    cfg_path = tdir / "config.json"
    if not cfg_path.exists():
        raise HTTPException(404, f"Template {req.org_id} not found")
    with open(cfg_path) as f:
        cfg = TemplateConfig(**json.load(f))

    logo_path = None
    if cfg.logo_filename:
        lp = tdir / cfg.logo_filename
        if lp.exists():
            logo_path = str(lp)

    template_docx_path = None
    tp = tdir / "template.docx"
    if tp.exists():
        template_docx_path = str(tp)

    # Convert
    out_docx = convert_document(
        fmap=fmap,
        cfg=cfg,
        output_dir=str(CONVERTED_OUTPUT),
        logo_path=logo_path,
        template_docx_path=template_docx_path,
    )

    # Update forensic map with converted page numbers
    fmap = update_forensic_after_conversion(fmap, out_docx, str(FORENSIC_MAPS))

    filename = Path(out_docx).name
    return {
        "doc_id": req.doc_id,
        "org_id": req.org_id,
        "converted_docx": filename,
        "download_url": f"/api/download/converted/{filename}",
        "control_locations": len(fmap.control_locations),
        "forensic_map_updated": True,
    }


# ── File downloads ────────────────────────────────────────────────────────────

@app.get("/api/download/converted/{filename}")
async def download_converted(filename: str):
    p = CONVERTED_OUTPUT / filename
    if not p.exists():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(
        str(p),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@app.get("/api/download/source/{doc_id}")
async def download_source(doc_id: str, kind: str = "main"):
    suffix = "_traceability.docx" if kind == "traceability" else ".docx"
    p = POLICY_OUTPUT / f"{doc_id}{suffix}"
    if not p.exists():
        raise HTTPException(404, f"DOCX not found for {doc_id}")
    return FileResponse(
        str(p),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=p.name,
    )


@app.get("/api/download/forensic/{doc_id}")
async def download_forensic_json(doc_id: str):
    p = _forensic_map_path(doc_id)
    if not p.exists():
        raise HTTPException(404, f"No forensic map for {doc_id}")
    return FileResponse(str(p), media_type="application/json", filename=p.name)


@app.get("/api/documents/{doc_id}/html", response_class=HTMLResponse)
async def render_document_html(doc_id: str):
    """Convert a policy/standard DOCX to HTML using mammoth for inline viewing."""
    docx_path = POLICY_OUTPUT / f"{doc_id}.docx"
    if not docx_path.exists():
        raise HTTPException(404, f"DOCX not found for {doc_id}")
    try:
        import mammoth
        with open(docx_path, "rb") as f:
            result = mammoth.convert_to_html(f, style_map="p[style-name='Heading 1'] => h2\np[style-name='Heading 2'] => h3\np[style-name='Heading 3'] => h4")
        html_body = result.value
        # Wrap in minimal styled page
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: 'Segoe UI', Calibri, Arial, sans-serif; font-size: 11px; line-height: 1.6;
          color: #1a1a1a; background: #fff; padding: 24px 32px; max-width: 860px; margin: 0 auto; }}
  h1, h2 {{ color: #d04a02; border-bottom: 1px solid #f0e0d8; padding-bottom: 4px; margin-top: 20px; }}
  h3 {{ color: #d04a02; margin-top: 16px; }}
  h4 {{ color: #555; margin-top: 12px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10px; }}
  td, th {{ border: 1px solid #ddd; padding: 5px 8px; vertical-align: top; }}
  th {{ background: #fef3ee; font-weight: 600; color: #d04a02; }}
  p {{ margin: 6px 0; }}
  strong {{ color: #d04a02; }}
  ul, ol {{ padding-left: 20px; margin: 6px 0; }}
  li {{ margin: 2px 0; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
        return HTMLResponse(content=html)
    except ImportError:
        raise HTTPException(500, "mammoth not installed. Run: pip install mammoth")
    except Exception as e:
        raise HTTPException(500, f"Conversion failed: {e}")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    results = _load_all_results()
    maps = list(FORENSIC_MAPS.glob("*_forensic_map.json"))
    converted = list(CONVERTED_OUTPUT.glob("*.docx"))
    templates = [d for d in ORG_TEMPLATES.iterdir() if d.is_dir()]
    return {
        "status": "ok",
        "documents": len(results),
        "forensic_maps": len(maps),
        "conversions": len(converted),
        "templates": len(templates),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
