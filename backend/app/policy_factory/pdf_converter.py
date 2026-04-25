"""
DOCX → PDF converter.

Tries docx2pdf first (Windows/Mac, requires Microsoft Word).
Falls back to LibreOffice headless if available.
Returns the PDF path on success, None on failure.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def convert_docx_to_pdf(docx_path: str, output_dir: str | None = None) -> str | None:
    """
    Convert a DOCX file to PDF.
    Returns the PDF path on success, or None if conversion fails.
    """
    if not os.path.exists(docx_path):
        return None

    if output_dir is None:
        output_dir = str(Path(docx_path).parent)

    pdf_path = os.path.join(output_dir, Path(docx_path).stem + ".pdf")

    # Already up-to-date
    if os.path.exists(pdf_path) and os.path.getmtime(pdf_path) >= os.path.getmtime(docx_path):
        return pdf_path

    # ── Try docx2pdf (Windows/Mac with Word installed) ─────────────────────
    try:
        from docx2pdf import convert  # type: ignore
        convert(docx_path, pdf_path)
        if os.path.exists(pdf_path):
            return pdf_path
    except Exception:
        pass

    # ── Try LibreOffice headless ──────────────────────────────────────────
    for soffice in ("soffice", "libreoffice"):
        try:
            result = subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", output_dir, docx_path],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0 and os.path.exists(pdf_path):
                return pdf_path
        except Exception:
            pass

    return None
