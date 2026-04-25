"""
Visio Swimlane Renderer — converts SwimlaneJsonSpec → .vsdx bytes.

Uses the `vsdx` Python library (v0.6.x) for file management and shape insertion.
The Visio XML for each shape is generated deterministically from the JSON spec
and inserted into the page via vsdx's copy_shape() API.

Design system (matches matplotlib_renderer.py):
  Process nodes   : #2563EB (blue)   — rounded rectangle, white text
  Decision nodes  : #F59E0B (amber)  — diamond, dark text
  Start/End nodes : #10B981 (green)  — ellipse, white text
  Lane background : #F3F4F6 / #E5E7EB (alternating light gray)
  Label column    : #D1D5DB (medium gray)
  Phase headers   : #1D4ED8 (deep blue)
  Title bar       : #1E3A5F (deep navy)

Visio coordinate system:
  - Origin at bottom-left of page
  - Y increases upward
  - Units: inches (pre-computed by swimlane_json_serializer.py)

Pipeline:
  SwimlaneJsonSpec (dict)
    → _VisioPageBuilder        (creates shape XML elements)
    → vsdx.VisioFile.copy_shape (inserts into page with auto-renumbered IDs)
    → vsdx.VisioFile.save_vsdx (writes ZIP archive)
    → return bytes
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

import vsdx

from .swimlane_json_serializer import SwimlaneJsonSpec, build_spec
from .layout_engine import LayoutGrid

# ── Visio XML namespace ────────────────────────────────────────────────────────
_NS  = "http://schemas.microsoft.com/office/visio/2012/main"
_R   = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NSB = f"{{{_NS}}}"          # brace-wrapped for ET element tag lookups


# ── Color helpers ──────────────────────────────────────────────────────────────

def _rgb(r: int, g: int, b: int) -> int:
    """Convert RGB triplet to Visio color integer (R + G×256 + B×65536)."""
    return r + g * 256 + b * 65536


# Design system palette
_C = {
    "proc":       _rgb(37,  99,  235),   # #2563EB  blue
    "dec":        _rgb(245, 158, 11),    # #F59E0B  amber
    "start":      _rgb(16,  185, 129),   # #10B981  green
    "title":      _rgb(30,  58,  95),    # #1E3A5F  navy
    "hdr":        _rgb(29,  78,  216),   # #1D4ED8  blue
    "lane_even":  _rgb(243, 244, 246),   # #F3F4F6  light gray
    "lane_odd":   _rgb(229, 231, 235),   # #E5E7EB  slightly darker gray
    "label_bg":   _rgb(209, 213, 219),   # #D1D5DB  medium gray
    "white":      16777215,              # #FFFFFF
    "dark_text":  _rgb(31,  41,  55),    # #1F2937  near-black
    "conn":       _rgb(100, 116, 139),   # #64748B  slate
    "amber_text": _rgb(120, 53,  15),    # #78350F  dark amber text
}

_TEXT_DARK_TYPES = {"dec"}   # node types that use dark text


# ── Visio XML shape templates ──────────────────────────────────────────────────

def _cell(name: str, value: str, formula: str = "") -> str:
    f_attr = f' F="{formula}"' if formula else ""
    return f'<Cell xmlns="{_NS}" N="{name}" V="{value}"{f_attr}/>'


def _char_section(color: int, pt: float, bold: bool = False) -> str:
    size_in = round(pt / 72, 6)
    style   = "1" if bold else "0"
    return (
        f'<Section xmlns="{_NS}" N="Character">'
        f'<Row IX="0">'
        f'{_cell("Color", str(color))}'
        f'{_cell("Size", str(size_in), f"{pt}pt")}'
        f'{_cell("Style", style)}'
        f'</Row></Section>'
    )


def _para_section(halign: int = 1) -> str:
    """Paragraph section. halign: 0=left, 1=center, 2=right."""
    return (
        f'<Section xmlns="{_NS}" N="Paragraph">'
        f'<Row IX="0">'
        f'{_cell("HorzAlign", str(halign))}'
        f'</Row></Section>'
    )


def _textblock_section(valign: int = 1) -> str:
    """TextBlock vertical alignment: 0=top, 1=middle, 2=bottom."""
    return (
        f'<Section xmlns="{_NS}" N="TextBlock">'
        f'<Row IX="0">'
        f'{_cell("VerticalAlign", str(valign))}'
        f'</Row></Section>'
    )


def _rect_geometry() -> str:
    return (
        f'<Section xmlns="{_NS}" N="Geometry" IX="0">'
        f'<Row T="RelMoveTo" IX="1">{_cell("X","0")}{_cell("Y","0")}</Row>'
        f'<Row T="RelLineTo" IX="2">{_cell("X","1")}{_cell("Y","0")}</Row>'
        f'<Row T="RelLineTo" IX="3">{_cell("X","1")}{_cell("Y","1")}</Row>'
        f'<Row T="RelLineTo" IX="4">{_cell("X","0")}{_cell("Y","1")}</Row>'
        f'<Row T="RelLineTo" IX="5">{_cell("X","0")}{_cell("Y","0")}</Row>'
        f'</Section>'
    )


def _diamond_geometry() -> str:
    return (
        f'<Section xmlns="{_NS}" N="Geometry" IX="0">'
        f'<Row T="RelMoveTo" IX="1">{_cell("X","0.5")}{_cell("Y","0")}</Row>'
        f'<Row T="RelLineTo" IX="2">{_cell("X","1")}{_cell("Y","0.5")}</Row>'
        f'<Row T="RelLineTo" IX="3">{_cell("X","0.5")}{_cell("Y","1")}</Row>'
        f'<Row T="RelLineTo" IX="4">{_cell("X","0")}{_cell("Y","0.5")}</Row>'
        f'<Row T="RelLineTo" IX="5">{_cell("X","0.5")}{_cell("Y","0")}</Row>'
        f'</Section>'
    )


def _ellipse_geometry(w: float, h: float) -> str:
    """
    Ellipse using absolute local coordinates (shape origin = bottom-left).
    Visio 'Ellipse' row: X,Y = centre; A,B = right point; C,D = top point.
    """
    cx, cy = w / 2, h / 2
    return (
        f'<Section xmlns="{_NS}" N="Geometry" IX="0">'
        f'<Row T="Ellipse" IX="1">'
        f'{_cell("X", str(round(cx,4)), "Width*0.5")}'
        f'{_cell("Y", str(round(cy,4)), "Height*0.5")}'
        f'{_cell("A", str(round(w, 4)), "Width")}'
        f'{_cell("B", str(round(cy,4)), "Height*0.5")}'
        f'{_cell("C", str(round(cx,4)), "Width*0.5")}'
        f'{_cell("D", str(round(h, 4)), "Height")}'
        f'</Row></Section>'
    )


# ── Shape XML builders ─────────────────────────────────────────────────────────

def _base_shape_xml(
    pin_x: float, pin_y: float,
    width: float, height: float,
    fill_color: int,
    line_color: int,
    line_weight: float,
    no_fill: bool = False,
) -> str:
    lw_str = str(round(line_weight, 5))
    nf_str = "1" if no_fill else "0"
    return (
        f'<Shape xmlns="{_NS}" ID="1" Type="Shape">'
        f'{_cell("PinX",       str(round(pin_x, 4)))}'
        f'{_cell("PinY",       str(round(pin_y, 4)))}'
        f'{_cell("Width",      str(round(width, 4)))}'
        f'{_cell("Height",     str(round(height, 4)))}'
        f'{_cell("LocPinX",   str(round(width/2, 4)), "Width*0.5")}'
        f'{_cell("LocPinY",   str(round(height/2, 4)), "Height*0.5")}'
        f'{_cell("Angle",      "0")}'
        f'{_cell("ObjType",    "1")}'
        f'{_cell("FillForegnd", str(fill_color))}'
        f'{_cell("FillBkgnd",   str(fill_color))}'
        f'{_cell("FillPattern", "1")}'
        f'{_cell("LineColor",   str(line_color))}'
        f'{_cell("LineWeight",  lw_str)}'
    )


def _make_rect_shape(
    cx: float, cy: float, w: float, h: float,
    fill_color: int,
    text: str = "",
    text_color: int = _C["white"],
    rounding: float = 0.0,
    font_pt: float = 11.0,
    bold: bool = False,
    line_color: int = _C["dark_text"],
    line_weight: float = 0.010,
    line_alpha: float = 0.25,      # visual hint: not enforced in vsdx XML but documented
) -> ET.Element:
    """Return an ET.Element for a filled rectangle (or rounded rectangle)."""
    xml_str = (
        _base_shape_xml(cx, cy, w, h, fill_color, line_color, line_weight)
        + (f'{_cell("Rounding", str(round(rounding, 4)))}' if rounding else "")
        + _rect_geometry()
        + _char_section(text_color, font_pt, bold)
        + _para_section(1)
        + _textblock_section(1)
        + (f'<Text xmlns="{_NS}">{_xml_escape(text)}</Text>' if text else "")
        + '</Shape>'
    )
    return ET.fromstring(xml_str)


def _make_ellipse_shape(
    cx: float, cy: float, w: float, h: float,
    fill_color: int,
    text: str = "",
    text_color: int = _C["white"],
    font_pt: float = 10.0,
) -> ET.Element:
    xml_str = (
        _base_shape_xml(cx, cy, w, h, fill_color, _C["dark_text"], 0.010)
        + _ellipse_geometry(w, h)
        + _char_section(text_color, font_pt, bold=True)
        + _para_section(1)
        + _textblock_section(1)
        + (f'<Text xmlns="{_NS}">{_xml_escape(text)}</Text>' if text else "")
        + '</Shape>'
    )
    return ET.fromstring(xml_str)


def _make_diamond_shape(
    cx: float, cy: float, w: float, h: float,
    fill_color: int,
    text: str = "",
    text_color: int = _C["dark_text"],
    font_pt: float = 10.0,
) -> ET.Element:
    xml_str = (
        _base_shape_xml(cx, cy, w, h, fill_color, _C["dark_text"], 0.010)
        + _diamond_geometry()
        + _char_section(text_color, font_pt, bold=True)
        + _para_section(1)
        + _textblock_section(1)
        + (f'<Text xmlns="{_NS}">{_xml_escape(text)}</Text>' if text else "")
        + '</Shape>'
    )
    return ET.fromstring(xml_str)


def _make_connector(
    bx: float, by: float,
    ex: float, ey: float,
    label: str = "",
    line_color: int = _C["conn"],
    line_weight: float = 0.012,
) -> ET.Element:
    """
    1-D connector shape (straight arrow).
    BeginX/BeginY = source point, EndX/EndY = target point.
    """
    lw = str(round(line_weight, 5))
    xml_str = (
        f'<Shape xmlns="{_NS}" ID="1" Type="Shape">'
        f'{_cell("BeginX",     str(round(bx, 4)))}'
        f'{_cell("BeginY",     str(round(by, 4)))}'
        f'{_cell("EndX",       str(round(ex, 4)))}'
        f'{_cell("EndY",       str(round(ey, 4)))}'
        f'{_cell("ObjType",    "2")}'
        f'{_cell("EndArrow",   "4")}'
        f'{_cell("EndArrowSize","2")}'
        f'{_cell("LineWeight", lw)}'
        f'{_cell("LineColor",  str(line_color))}'
        f'{_cell("FillPattern","0")}'
        + _char_section(_C["dark_text"], 8.0, bold=False)
        + _para_section(1)
        + (f'<Text xmlns="{_NS}">{_xml_escape(label)}</Text>' if label else "")
        + '</Shape>'
    )
    return ET.fromstring(xml_str)


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ── Blank .vsdx template generator ────────────────────────────────────────────

def _blank_vsdx_bytes(page_w: float, page_h: float, title: str = "Swimlane") -> bytes:
    """
    Generate a minimal blank .vsdx file as in-memory bytes.
    Page dimensions in inches. Landscape orientation.
    """
    safe_title = _xml_escape(title)[:60]

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml"  ContentType="application/xml"/>'
        '<Override PartName="/visio/document.xml"       ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
        '<Override PartName="/visio/pages/pages.xml"    ContentType="application/vnd.ms-visio.pages+xml"/>'
        '<Override PartName="/visio/pages/page1.xml"    ContentType="application/vnd.ms-visio.page+xml"/>'
        '</Types>'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.microsoft.com/visio/2010/relationships/document"'
        ' Target="visio/document.xml"/>'
        '</Relationships>'
    )

    document_xml = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<VisioDocument xmlns="{_NS}"'
        f' xmlns:r="{_R}"'
        f' xml:space="preserve">'
        f'<DocumentSettings TopPage="0"'
        f' DefaultTextStyle="0" DefaultLineStyle="0"'
        f' DefaultFillStyle="0" DefaultGuideStyle="0"/>'
        f'</VisioDocument>'
    )

    document_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.microsoft.com/visio/2010/relationships/pages"'
        ' Target="pages/pages.xml"/>'
        '</Relationships>'
    )

    pw = round(page_w, 6)
    ph = round(page_h, 6)
    vcx = round(page_w / 2, 6)
    vcy = round(page_h / 2, 6)

    pages_xml = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<Pages xmlns="{_NS}" xmlns:r="{_R}" xml:space="preserve">'
        f'<Page ID="0" NameU="{safe_title}" Name="{safe_title}"'
        f' ViewScale="1" ViewCenterX="{vcx}" ViewCenterY="{vcy}">'
        f'<PageSheet LineStyle="0" FillStyle="0" TextStyle="0">'
        f'<Cell N="PageWidth"           V="{pw}"/>'
        f'<Cell N="PageHeight"          V="{ph}"/>'
        f'<Cell N="ShdwOffsetX"         V="0.1181"/>'
        f'<Cell N="ShdwOffsetY"         V="-0.1181"/>'
        f'<Cell N="PageScale"           V="1" U="IN"/>'
        f'<Cell N="DrawingScale"        V="1" U="IN"/>'
        f'<Cell N="DrawingSizeType"     V="0"/>'
        f'<Cell N="DrawingScaleType"    V="0"/>'
        f'<Cell N="InhibitSnap"         V="0"/>'
        f'<Cell N="PrintPageOrientation" V="2"/>'
        f'</PageSheet>'
        f'<Rel r:id="rId1"/>'
        f'</Page></Pages>'
    )

    pages_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.microsoft.com/visio/2010/relationships/page"'
        ' Target="page1.xml"/>'
        '</Relationships>'
    )

    page1_xml = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<PageContents xmlns="{_NS}" xmlns:r="{_R}" xml:space="preserve">'
        f'<Shapes/>'
        f'</PageContents>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",              content_types)
        zf.writestr("_rels/.rels",                       root_rels)
        zf.writestr("visio/document.xml",                document_xml)
        zf.writestr("visio/_rels/document.xml.rels",     document_rels)
        zf.writestr("visio/pages/pages.xml",             pages_xml)
        zf.writestr("visio/pages/_rels/pages.xml.rels",  pages_rels)
        zf.writestr("visio/pages/page1.xml",             page1_xml)
    return buf.getvalue()


# ── Node routing helpers ───────────────────────────────────────────────────────

def _node_lookup(spec_dict: dict) -> dict[str, dict]:
    """Build a lookup: node_id → node dict."""
    return {n["id"]: n for n in spec_dict.get("nodes", [])}


def _connector_endpoints(
    src: dict, dst: dict
) -> tuple[float, float, float, float]:
    """
    Compute (bx, by, ex, ey) for a connector in Visio coordinates.

    Routing rules (Visio Y increases upward):
      - Same X (same phase column): vertical arrow, bottom → top or top → bottom
      - Different X: horizontal stair-step using right-exit / top-enter heuristic
    """
    scx, scy = src["cx_in"], src["cy_in"]
    shh = src["h_in"] / 2
    dcx, dcy = dst["cx_in"], dst["cy_in"]
    dhh = dst["h_in"] / 2

    src_bottom = scy - shh
    src_top    = scy + shh
    dst_bottom = dcy - dhh
    dst_top    = dcy + dhh

    same_col = abs(scx - dcx) < 0.05

    if same_col:
        # Vertical connector: exit bottom if source is above destination
        if scy > dcy:
            return scx, src_bottom, dcx, dst_top
        else:
            return scx, src_top, dcx, dst_bottom
    else:
        # Horizontal: exit right side of source, enter top/bottom of destination
        src_right = scx + src["w_in"] / 2
        if scy >= dcy:
            return src_right, scy, dcx, dst_top
        else:
            return src_right, scy, dcx, dst_bottom


# ── Main renderer ──────────────────────────────────────────────────────────────

class VisioSwimlaneRenderer:
    """
    Converts a SwimlaneJsonSpec (dict or object) into a .vsdx file (bytes).

    Usage:
        renderer = VisioSwimlaneRenderer()
        vsdx_bytes = renderer.render(spec.to_dict())
    """

    def render(self, spec_dict: dict) -> bytes:
        """
        Build and return .vsdx bytes for a swimlane spec dict.

        Parameters
        ----------
        spec_dict:
            Output of SwimlaneJsonSpec.to_dict() — all positions pre-converted
            to Visio coordinate space (inches, origin bottom-left, Y up).

        Returns
        -------
        bytes
            Raw bytes of the .vsdx ZIP archive.
        """
        pw = spec_dict["page_w_in"]
        ph = spec_dict["page_h_in"]
        title = spec_dict.get("title", "Swimlane")

        # ── Write blank template to a temp file ────────────────────────────────
        template_bytes = _blank_vsdx_bytes(pw, ph, title)
        tmp = tempfile.NamedTemporaryFile(suffix=".vsdx", delete=False)
        try:
            tmp.write(template_bytes)
            tmp.flush()
            tmp.close()

            vis = vsdx.VisioFile(tmp.name)
            page = vis.pages[0]

            self._populate_page(vis, page, spec_dict)

            out_path = tmp.name.replace(".vsdx", "_out.vsdx")
            vis.save_vsdx(out_path)

            with open(out_path, "rb") as f:
                result = f.read()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            try:
                os.unlink(out_path)
            except (OSError, UnboundLocalError):
                pass

        return result

    # ── Internal: populate page with shapes ───────────────────────────────────

    def _populate_page(
        self,
        vis: vsdx.VisioFile,
        page: vsdx.Page,
        spec: dict,
    ) -> None:
        """Insert all shapes onto the Visio page."""
        # Insertion order matters for Z-order (later = on top).
        # 1. Lane backgrounds (bottom layer)
        self._add_lanes(vis, page, spec)
        # 2. Phase column separators and headers
        self._add_phase_headers(vis, page, spec)
        # 3. Title bar
        self._add_title_bar(vis, page, spec)
        # 4. Connectors (under nodes)
        node_map = self._add_connectors(vis, page, spec)
        # 5. Nodes (top layer)
        self._add_nodes(vis, page, spec)

    def _insert(self, vis: vsdx.VisioFile, page: vsdx.Page, elem: ET.Element) -> ET.Element:
        """Insert a shape element into the page and return the inserted element."""
        return vis.copy_shape(elem, page)

    # ── Lane backgrounds ──────────────────────────────────────────────────────

    def _add_lanes(self, vis, page, spec: dict) -> None:
        lanes = spec.get("lanes", [])
        for i, lane in enumerate(lanes):
            bg_color = _C["lane_even"] if i % 2 == 0 else _C["lane_odd"]
            bg = lane["bg_rect"]
            # Background fill
            self._insert(vis, page, _make_rect_shape(
                cx=bg["cx_in"], cy=bg["cy_in"],
                w=bg["w_in"], h=bg["h_in"],
                fill_color=bg_color,
                text="",
                line_color=_C["dark_text"], line_weight=0.007,
            ))
            # Label column
            lbl = lane["label_rect"]
            self._insert(vis, page, _make_rect_shape(
                cx=lbl["cx_in"], cy=lbl["cy_in"],
                w=lbl["w_in"], h=lbl["h_in"],
                fill_color=_C["label_bg"],
                text=lane["label"],
                text_color=_C["dark_text"],
                font_pt=10.0, bold=True,
                line_color=_C["dark_text"], line_weight=0.007,
            ))

    # ── Phase column headers ──────────────────────────────────────────────────

    def _add_phase_headers(self, vis, page, spec: dict) -> None:
        # Label column header (blank placeholder above lane labels)
        lanes = spec.get("lanes", [])
        phase_headers = spec.get("phase_headers", [])
        if not phase_headers:
            return

        ph = phase_headers[0]
        # blank label-column header cell above lane labels
        self._insert(vis, page, _make_rect_shape(
            cx=spec["page_w_in"] * 0.5 * (1.80 / spec["page_w_in"]),
            cy=ph["cy_in"],
            w=1.80,
            h=ph["h_in"],
            fill_color=_C["label_bg"],
            text="",
            line_color=_C["dark_text"], line_weight=0.007,
        ))

        for hdr in phase_headers:
            self._insert(vis, page, _make_rect_shape(
                cx=hdr["cx_in"], cy=hdr["cy_in"],
                w=hdr["w_in"], h=hdr["h_in"],
                fill_color=_C["hdr"],
                text=hdr["label"],
                text_color=_C["white"],
                font_pt=10.0, bold=True,
                line_color=_C["dark_text"], line_weight=0.007,
            ))

    # ── Title bar ─────────────────────────────────────────────────────────────

    def _add_title_bar(self, vis, page, spec: dict) -> None:
        tb = spec["title_bar"]
        title = tb["label"]
        part_no     = spec.get("part_no", 1)
        total_parts = spec.get("total_parts", 1)
        if total_parts > 1:
            title = f"{title}  (Part {part_no} of {total_parts})"
        self._insert(vis, page, _make_rect_shape(
            cx=tb["cx_in"], cy=tb["cy_in"],
            w=tb["w_in"], h=tb["h_in"],
            fill_color=_C["title"],
            text=title,
            text_color=_C["white"],
            font_pt=12.0, bold=True,
            line_color=_C["dark_text"], line_weight=0.007,
        ))

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def _add_nodes(self, vis, page, spec: dict) -> None:
        for node in spec.get("nodes", []):
            self._insert(vis, page, self._make_node_shape(node))

    def _make_node_shape(self, node: dict) -> ET.Element:
        cx, cy = node["cx_in"], node["cy_in"]
        w,  h  = node["w_in"],  node["h_in"]
        label  = node["label"]
        ntype  = node["node_type"]

        if ntype in ("start", "end"):
            return _make_ellipse_shape(
                cx, cy, w, h,
                fill_color=_C["start"],
                text=label,
                text_color=_C["white"],
                font_pt=10.0,
            )
        if ntype == "decision":
            return _make_diamond_shape(
                cx, cy, w, h,
                fill_color=_C["dec"],
                text=label,
                text_color=_C["amber_text"],
                font_pt=9.0,
            )
        # default: process (rounded rectangle)
        return _make_rect_shape(
            cx, cy, w, h,
            fill_color=_C["proc"],
            text=label,
            text_color=_C["white"],
            rounding=0.07,
            font_pt=10.0, bold=True,
        )

    # ── Connectors ────────────────────────────────────────────────────────────

    def _add_connectors(self, vis, page, spec: dict) -> None:
        node_lkp = _node_lookup(spec)
        for edge in spec.get("edges", []):
            src = node_lkp.get(edge["from_id"])
            dst = node_lkp.get(edge["to_id"])
            if src is None or dst is None:
                continue
            bx, by, ex, ey = _connector_endpoints(src, dst)
            condition = edge.get("condition", "")
            self._insert(vis, page, _make_connector(
                bx, by, ex, ey,
                label=condition,
            ))


# ── Public top-level helper ────────────────────────────────────────────────────

def render_grid_to_vsdx(grid: LayoutGrid) -> tuple[bytes, dict]:
    """
    Convenience wrapper: LayoutGrid → (.vsdx bytes, JSON spec dict).

    Returns both the .vsdx bytes and the intermediate JSON spec so callers
    can also save the JSON for inspection or debugging.
    """
    from .swimlane_json_serializer import build_spec
    json_spec  = build_spec(grid)
    spec_dict  = json_spec.to_dict()
    renderer   = VisioSwimlaneRenderer()
    vsdx_bytes = renderer.render(spec_dict)
    return vsdx_bytes, spec_dict
