"""
AutoAlign Policy Converter — integrated into Controls Intelligence Hub backend.

Routes:
  GET  /api/documents                — list all generated docs with metadata
  GET  /api/documents/{doc_id}       — doc detail + forensic map
  GET  /api/documents/{doc_id}/html  — render DOCX as HTML (mammoth)
  POST /api/forensics/extract        — trigger forensic extraction for one doc
  POST /api/forensics/extract-all    — extract all docs (background)
  GET  /api/forensics/{doc_id}       — get saved forensic map JSON
  POST /api/forensics/update         — update map from Office.js accurate page data

  GET  /api/templates                — list uploaded org templates
  POST /api/templates/upload         — upload org template DOCX + config
  GET  /api/templates/{org_id}/logo  — serve template logo
  DELETE /api/templates/{org_id}     — delete a template

  POST /api/convert                  — convert doc to org template
  GET  /api/download/source/{doc_id} — download source DOCX
  GET  /api/download/converted/{filename} — download converted DOCX
  GET  /api/download/forensic/{doc_id}    — download forensic map JSON

  GET  /api/converter/health         — health check
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

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.policy_converter.schemas import TemplateConfig, ForensicDocumentMap
from app.policy_converter.forensics import extract_forensic_map, find_artifacts, extract_all, update_from_officejs
from app.policy_converter.converter import convert_document, update_forensic_after_conversion

router = APIRouter()

# ── Paths (relative to backend/ root) ────────────────────────────────────────

_BACKEND_DIR     = Path(__file__).resolve().parent.parent.parent
POLICY_OUTPUT    = _BACKEND_DIR / "policy_output"
FORENSIC_MAPS    = _BACKEND_DIR / "forensic_maps"
ORG_TEMPLATES    = _BACKEND_DIR / "org_templates"
CONVERTED_OUTPUT = _BACKEND_DIR / "converted_output"

for _d in [POLICY_OUTPUT, FORENSIC_MAPS, ORG_TEMPLATES, CONVERTED_OUTPUT]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _template_dir(org_id: str) -> Path:
    return ORG_TEMPLATES / org_id


# ── Document listing ──────────────────────────────────────────────────────────

@router.get("/documents")
async def list_documents():
    results = _load_all_results()
    docs = []
    for r in sorted(results, key=lambda x: x.get("doc_id", "")):
        fmap = _load_forensic_map(r["doc_id"])
        docs.append({
            "doc_id":          r.get("doc_id"),
            "document_type":   r.get("document_type", "policy"),
            "title":           r.get("title", ""),
            "version":         r.get("version", "1.0"),
            "qa_passed":       r.get("qa_passed", False),
            "shall_count":     r.get("shall_count", 0),
            "traced_count":    r.get("traced_count", 0),
            "main_docx":       r.get("main_docx", ""),
            "has_forensic_map": fmap is not None,
            "forensic_controls": len(fmap.get("control_locations", [])) if fmap else 0,
            "has_conversion":  fmap.get("converted_docx") if fmap else None,
        })
    return {"documents": docs, "total": len(docs)}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    results = _load_all_results()
    r = next((x for x in results if x.get("doc_id") == doc_id), None)
    if not r:
        raise HTTPException(404, f"Document {doc_id} not found")
    fmap = _load_forensic_map(doc_id)
    return {"result": r, "forensic_map": fmap}


@router.get("/documents/{doc_id}/html", response_class=HTMLResponse)
async def render_document_html(doc_id: str):
    """Convert a policy/standard DOCX to HTML using mammoth."""
    docx_path = POLICY_OUTPUT / f"{doc_id}.docx"
    if not docx_path.exists():
        raise HTTPException(404, f"DOCX not found for {doc_id}")
    try:
        import mammoth  # noqa: PLC0415
        with open(docx_path, "rb") as f:
            result = mammoth.convert_to_html(
                f,
                style_map=(
                    "p[style-name='Heading 1'] => h2\n"
                    "p[style-name='Heading 2'] => h3\n"
                    "p[style-name='Heading 3'] => h4"
                ),
            )
        html_body = result.value
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


# ── Forensic extraction ───────────────────────────────────────────────────────

@router.post("/forensics/extract")
async def extract_forensics(body: dict):
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
        "doc_id":         doc_id,
        "sections":       len(fmap.section_locations),
        "controls":       len(fmap.control_locations),
        "estimated_pages": fmap.estimated_pages,
        "forensic_map":   fmap.model_dump(),
    }


@router.post("/forensics/extract-all")
async def extract_all_forensics(background_tasks: BackgroundTasks):
    def _run():
        maps = extract_all(str(POLICY_OUTPUT), str(FORENSIC_MAPS))
        print(f"[Converter] Extracted {len(maps)} forensic maps")

    background_tasks.add_task(_run)
    return {"message": "Forensic extraction started in background"}


@router.get("/forensics/{doc_id}")
async def get_forensic_map(doc_id: str):
    fmap = _load_forensic_map(doc_id)
    if not fmap:
        raise HTTPException(404, f"No forensic map for {doc_id}. Run extraction first.")
    return fmap


@router.post("/forensics/update")
async def update_forensics_from_officejs(body: dict):
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

@router.get("/templates")
async def list_templates():
    templates = []
    for p in ORG_TEMPLATES.iterdir():
        if p.is_dir():
            cfg_p = p / "config.json"
            if cfg_p.exists():
                with open(cfg_p) as f:
                    cfg = json.load(f)
                templates.append({
                    "org_id":        p.name,
                    "org_name":      cfg.get("org_name", p.name),
                    "template_id":   cfg.get("template_id", ""),
                    "primary_color": cfg.get("primary_color", "#1F497D"),
                    "has_logo": (p / cfg.get("logo_filename", "logo.png")).exists()
                        if cfg.get("logo_filename") else False,
                    "created_at": cfg.get("created_at", ""),
                })
    return {"templates": templates}


@router.post("/templates/upload")
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


@router.get("/templates/{org_id}/logo")
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


@router.delete("/templates/{org_id}")
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


@router.post("/convert")
async def convert_doc(req: ConvertRequest):
    fmap_dict = _load_forensic_map(req.doc_id)
    if not fmap_dict:
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

    out_docx = convert_document(
        fmap=fmap,
        cfg=cfg,
        output_dir=str(CONVERTED_OUTPUT),
        logo_path=logo_path,
        template_docx_path=template_docx_path,
    )

    fmap = update_forensic_after_conversion(fmap, out_docx, str(FORENSIC_MAPS))

    filename = Path(out_docx).name
    return {
        "doc_id":              req.doc_id,
        "org_id":              req.org_id,
        "converted_docx":      filename,
        "download_url":        f"/api/download/converted/{filename}",
        "control_locations":   len(fmap.control_locations),
        "forensic_map_updated": True,
    }


# ── File downloads ────────────────────────────────────────────────────────────

@router.get("/download/converted/{filename}")
async def download_converted(filename: str):
    p = CONVERTED_OUTPUT / filename
    if not p.exists():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(
        str(p),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.get("/download/source/{doc_id}")
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


@router.get("/download/forensic/{doc_id}")
async def download_forensic_json(doc_id: str):
    p = _forensic_map_path(doc_id)
    if not p.exists():
        raise HTTPException(404, f"No forensic map for {doc_id}")
    return FileResponse(str(p), media_type="application/json", filename=p.name)


# ── Document comments ─────────────────────────────────────────────────────────

def _comments_path(doc_id: str) -> Path:
    return FORENSIC_MAPS / f"{doc_id}_comments.json"


def _load_comments(doc_id: str) -> list[dict]:
    p = _comments_path(doc_id)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_comments(doc_id: str, comments: list[dict]) -> None:
    with open(_comments_path(doc_id), "w", encoding="utf-8") as f:
        json.dump(comments, f, indent=2)


@router.get("/documents/{doc_id}/comments")
async def get_document_comments(doc_id: str):
    return {"doc_id": doc_id, "comments": _load_comments(doc_id)}


@router.post("/documents/{doc_id}/comments")
async def add_document_comment(doc_id: str, body: dict):
    comments = _load_comments(doc_id)
    comment = {
        "id": str(uuid.uuid4())[:8],
        "selected_text": body.get("selected_text", ""),
        "context_before": body.get("context_before", ""),
        "context_after": body.get("context_after", ""),
        "comment": body.get("comment", ""),
        "author": body.get("author", "Consultant"),
        "color": body.get("color", "#d04a02"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    comments.append(comment)
    _save_comments(doc_id, comments)
    return comment


@router.delete("/documents/{doc_id}/comments/{comment_id}")
async def delete_document_comment(doc_id: str, comment_id: str):
    comments = _load_comments(doc_id)
    comments = [c for c in comments if c["id"] != comment_id]
    _save_comments(doc_id, comments)
    return {"deleted": comment_id}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/converter/health")
async def converter_health():
    results = _load_all_results()
    maps = list(FORENSIC_MAPS.glob("*_forensic_map.json"))
    converted = list(CONVERTED_OUTPUT.glob("*.docx"))
    templates = [d for d in ORG_TEMPLATES.iterdir() if d.is_dir()]
    return {
        "status":        "ok",
        "documents":     len(results),
        "forensic_maps": len(maps),
        "conversions":   len(converted),
        "templates":     len(templates),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }
