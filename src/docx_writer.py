"""
docx_writer.py — build a genuine, Word-openable .docx using only the stdlib.

A .docx is a ZIP of OpenXML parts. This module assembles the parts by hand so
the demo needs no python-docx. It supports the pieces an EMC report needs:
cover page with images, heading styles, body paragraphs, page breaks, richly
formatted tables (header fill, banded rows, borders, coloured PASS/FAIL text),
inline figures with captions, and a footer with a live "Page X of Y" field.
"""
from __future__ import annotations

import os
import zipfile
from xml.sax.saxutils import escape
from PIL import Image

EMU_PER_PX = 9525            # 1 px at 96 dpi
EMU_PER_INCH = 914400


def _hex(c: str) -> str:
    return c.lstrip("#").upper()


class DocxWriter:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.brand = cfg["brand"]
        self.fonts = cfg["fonts"]
        self.body_parts: list[str] = []
        self.media: dict[str, str] = {}          # rId -> source path
        self.media_names: dict[str, str] = {}     # rId -> media/filename
        self._rid = 0

    # -- relationships / media ------------------------------------------------
    def _add_image(self, path: str) -> tuple[str, int, int]:
        self._rid += 1
        rid = f"rId{100 + self._rid}"
        name = f"image{self._rid}{os.path.splitext(path)[1]}"
        self.media[rid] = path
        self.media_names[rid] = name
        with Image.open(path) as im:
            w, h = im.size
        return rid, w, h

    # -- low-level paragraph helpers -----------------------------------------
    def _run(self, text, bold=False, size=None, color=None, font=None):
        size = size or self.fonts["body_size"]
        font = font or self.fonts["body_family"]
        rpr = ["<w:rPr>"]
        rpr.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>')
        if bold:
            rpr.append("<w:b/>")
        rpr.append(f'<w:sz w:val="{int(size * 2)}"/>')
        if color:
            rpr.append(f'<w:color w:val="{_hex(color)}"/>')
        rpr.append("</w:rPr>")
        return (f"<w:r>{''.join(rpr)}"
                f'<w:t xml:space="preserve">{escape(str(text))}</w:t></w:r>')

    def paragraph(self, text="", bold=False, size=None, color=None,
                  align=None, space_before=0, space_after=120, font=None):
        ppr = ["<w:pPr>"]
        sp = f'w:before="{space_before}" w:after="{space_after}"'
        ppr.append(f"<w:spacing {sp}/>")
        if align:
            ppr.append(f'<w:jc w:val="{align}"/>')
        ppr.append("</w:pPr>")
        run = self._run(text, bold=bold, size=size, color=color, font=font) if text != "" else ""
        self.body_parts.append(f"<w:p>{''.join(ppr)}{run}</w:p>")

    def heading(self, text, level=1):
        sizes = {1: self.fonts["h1_size"], 2: self.fonts["h2_size"], 3: self.fonts["h3_size"]}
        colors = {1: self.brand["primary_dark"], 2: self.brand["primary"], 3: self.brand["text"]}
        before = {1: 260, 2: 200, 3: 140}[level]
        # coloured rule under H1 via bottom border
        pbdr = ""
        if level == 1:
            pbdr = (f'<w:pBdr><w:bottom w:val="single" w:sz="18" w:space="4" '
                    f'w:color="{_hex(self.brand["rule"])}"/></w:pBdr>')
        self.body_parts.append(
            f"<w:p><w:pPr>{pbdr}"
            f'<w:spacing w:before="{before}" w:after="120"/>'
            f'<w:keepNext/></w:pPr>'
            f"{self._run(text, bold=True, size=sizes[level], color=colors[level], font=self.fonts['heading_family'])}"
            f"</w:p>")

    def bullet(self, text):
        self.body_parts.append(
            "<w:p><w:pPr>"
            '<w:spacing w:after="40"/>'
            '<w:ind w:left="360" w:hanging="180"/></w:pPr>'
            f"{self._run('•  ' + str(text))}</w:p>")

    def page_break(self):
        self.body_parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def spacer(self, twips=120):
        self.body_parts.append(f'<w:p><w:pPr><w:spacing w:after="{twips}"/></w:pPr></w:p>')

    # -- image ----------------------------------------------------------------
    def image(self, path, max_width_in=6.3, caption=None):
        rid, px_w, px_h = self._add_image(path)
        w_emu = int(max_width_in * EMU_PER_INCH)
        h_emu = int(w_emu * px_h / px_w)
        drawing = (
            '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="60" w:after="40"/></w:pPr>'
            '<w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{w_emu}" cy="{h_emu}"/>'
            '<wp:docPr id="1" name="figure"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="0" name="figure"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{w_emu}" cy="{h_emu}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
        self.body_parts.append(drawing)
        if caption:
            self.body_parts.append(
                '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="160"/></w:pPr>'
                f"{self._run(caption, size=self.fonts['caption_size'], color=self.brand['muted'])}</w:p>")

    # -- table ----------------------------------------------------------------
    def table(self, headers, rows, col_widths=None, status_col=-1):
        b = self.cfg["table_style"]
        border = _hex(self.brand["table_border"])
        bw = int(b["border_width_pt"] * 8)  # eighths of a point
        n = len(headers)
        total = 9600
        if col_widths:
            widths = [int(total * w / sum(col_widths)) for w in col_widths]
        else:
            widths = [total // n] * n

        def border_xml():
            e = f'w:val="single" w:sz="{bw}" w:space="0" w:color="{border}"'
            return (f"<w:tcBorders><w:top {e}/><w:left {e}/>"
                    f"<w:bottom {e}/><w:right {e}/></w:tcBorders>")

        def cell(text, w, *, header=False, band=False, color=None, align="left"):
            shade = ""
            if header:
                shade = f'<w:shd w:val="clear" w:fill="{_hex(self.brand["table_header_fill"])}"/>'
            elif band:
                shade = f'<w:shd w:val="clear" w:fill="{_hex(self.brand["table_band_fill"])}"/>'
            pad = int(b["cell_padding_pt"] * 20)
            txt_color = self.brand["table_header_text"] if header else (color or self.brand["text"])
            size = self.fonts["table_header_size"] if header else self.fonts["table_cell_size"]
            bold = header and b.get("header_bold", True)
            run = self._run(text, bold=bold, size=size, color=txt_color)
            return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{border_xml()}{shade}'
                    f'<w:tcMar><w:top w:w="{pad}" w:type="dxa"/><w:bottom w:w="{pad}" w:type="dxa"/>'
                    f'<w:left w:w="{pad+20}" w:type="dxa"/><w:right w:w="{pad}" w:type="dxa"/></w:tcMar>'
                    f'<w:vAlign w:val="center"/></w:tcPr>'
                    f'<w:p><w:pPr><w:jc w:val="{align}"/><w:spacing w:after="0"/></w:pPr>{run}</w:p></w:tc>')

        parts = ['<w:tbl><w:tblPr>'
                 f'<w:tblW w:w="{total}" w:type="dxa"/>'
                 '<w:tblLayout w:type="fixed"/>'
                 '<w:tblLook w:val="04A0"/></w:tblPr>']
        parts.append("<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>")

        hdr_cells = "".join(cell(h, widths[i], header=True,
                                  align="center" if i else "left")
                            for i, h in enumerate(headers))
        repeat = "<w:tblHeader/>" if b.get("repeat_header_each_page", True) else ""
        parts.append(f'<w:tr><w:trPr>{repeat}</w:trPr>{hdr_cells}</w:tr>')

        for ri, row in enumerate(rows):
            band = b["banded_rows"] and (ri % 2 == 1)
            tcs = []
            for ci, val in enumerate(row):
                color = None
                if b["status_color_coding"] and (ci == status_col or (status_col == -1 and ci == len(row) - 1)):
                    v = str(val).upper()
                    if v in ("PASS", "A"):
                        color = self.brand["pass"]
                    elif v in ("FAIL", "B", "C", "D"):
                        color = self.brand["fail"]
                tcs.append(cell(val, widths[ci], band=band, color=color,
                                align="center" if ci else "left"))
            parts.append(f"<w:tr>{''.join(tcs)}</w:tr>")
        parts.append("</w:tbl>")
        self.body_parts.append("".join(parts))
        # small gap after table
        self.spacer(120)

    def caption(self, text):
        self.body_parts.append(
            f'<w:p><w:pPr><w:spacing w:before="40" w:after="60"/></w:pPr>'
            f"{self._run(text, bold=True, size=self.fonts['caption_size'], color=self.brand['muted'])}</w:p>")

    # -- cover ----------------------------------------------------------------
    def add_cover(self, meta, assets_dir):
        cov = self.cfg["cover"]
        # logo (left) — Word inlines, so place at top
        if cov.get("show_logo"):
            lp = os.path.join(assets_dir, cov["logo"])
            if os.path.exists(lp):
                self.image(lp, max_width_in=1.4)
        if cov.get("classification_banner"):
            self.body_parts.append(
                f'<w:p><w:pPr><w:shd w:val="clear" w:fill="{_hex(self.brand["primary_dark"])}"/>'
                '<w:spacing w:before="120" w:after="200"/></w:pPr>'
                f"{self._run(meta['classification'], bold=True, color='#FFFFFF', size=11)}</w:p>")
        if cov.get("show_hero_image"):
            hp = os.path.join(assets_dir, cov["hero_image"])
            if os.path.exists(hp):
                self.image(hp, max_width_in=6.3)
        self.paragraph(meta["project_name"], bold=True, size=24,
                       color=self.brand["primary_dark"], space_before=120, space_after=60,
                       font=self.fonts["heading_family"])
        self.paragraph("EMC Compliance Test Report", bold=True, size=16,
                       color=self.brand["primary"], space_after=200,
                       font=self.fonts["heading_family"])
        meta_rows = [
            ["Document Number", meta["document_number"]],
            ["Revision", meta["revision"]],
            ["Issue Date", meta["issue_date"]],
            ["Client", meta["client"]],
            ["Test Laboratory", meta["test_lab"]],
            ["Accreditation", meta["accreditation"]],
        ]
        for k, v in meta_rows:
            self.body_parts.append(
                '<w:p><w:pPr><w:spacing w:after="40"/><w:tabs><w:tab w:val="left" w:pos="2600"/></w:tabs></w:pPr>'
                f"{self._run(k, bold=True, color=self.brand['muted'])}"
                "<w:r><w:tab/></w:r>"
                f"{self._run(v)}</w:p>")
        self.spacer(120)
        self.paragraph("Standards applied:", bold=True, color=self.brand["muted"], space_after=40)
        for s in meta["standards"]:
            self.bullet(s)
        self.page_break()

    # -- unified adapters (shared signature with pdf_writer) ------------------
    def add_table(self, headers, rows, fracs=None, status_col=-1):
        self.table(headers, rows, col_widths=fracs, status_col=status_col)

    def add_figure(self, path, caption=None):
        self.image(path, max_width_in=6.3, caption=caption)

    # -- assembly -------------------------------------------------------------
    def _footer_xml(self):
        f = self.cfg["footer"]
        left = escape(f.get("left_text", ""))
        center = escape(f.get("center_text", ""))
        col = _hex(self.brand["muted"])

        def r(t):
            return (f'<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="{col}"/></w:rPr>'
                    f'<w:t xml:space="preserve">{t}</w:t></w:r>')
        page_field = (
            f'<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="{col}"/></w:rPr><w:t xml:space="preserve">Page </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            f'<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="{col}"/></w:rPr><w:t xml:space="preserve"> of </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
        tab = '<w:r><w:tab/></w:r>'
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:p><w:pPr><w:pBdr><w:top w:val="single" w:sz="4" w:space="4" '
            f'w:color="{_hex(self.brand["table_border"])}"/></w:pBdr>'
            '<w:tabs><w:tab w:val="center" w:pos="4680"/><w:tab w:val="right" w:pos="9360"/></w:tabs></w:pPr>'
            f'{r(left)}{tab}{r(center)}{tab}{page_field}</w:p></w:ftr>')

    def _content_types(self):
        overrides = "".join(
            f'<Override PartName="/word/media/{os.path.basename(n)}" ContentType="image/png"/>'
            for n in [])  # media declared via Default png below
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            f'{overrides}</Types>')

    def _styles(self):
        f = self.fonts
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            f'<w:rFonts w:ascii="{f["body_family"]}" w:hAnsi="{f["body_family"]}"/>'
            f'<w:sz w:val="{int(f["body_size"]*2)}"/><w:color w:val="{_hex(self.brand["text"])}"/>'
            '</w:rPr></w:rPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
            '</w:styles>')

    def build(self, out_path: str, page_cfg: dict, core: dict):
        # section properties w/ footer + margins (A4)
        m = page_cfg
        w_pg, h_pg = 11906, 16838  # A4 in twips
        sect = (
            '<w:sectPr>'
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
            f'<w:pgSz w:w="{w_pg}" w:h="{h_pg}"/>'
            f'<w:pgMar w:top="{int(m["margin_top_mm"]*56.7)}" w:bottom="{int(m["margin_bottom_mm"]*56.7)}" '
            f'w:left="{int(m["margin_left_mm"]*56.7)}" w:right="{int(m["margin_right_mm"]*56.7)}" '
            'w:header="708" w:footer="454" w:gutter="0"/>'
            '</w:sectPr>')

        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<w:body>' + "".join(self.body_parts) + sect + '</w:body></w:document>')

        # document rels: styles, footer, images
        rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>']
        for rid, name in self.media_names.items():
            rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>')
        rels.append("</Relationships>")

        root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                     '</Relationships>')

        core_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(core.get("title",""))}</dc:title>'
            f'<dc:creator>{escape(core.get("author","Element / Databricks"))}</dc:creator>'
            f'<cp:lastModifiedBy>{escape(core.get("author","Element / Databricks"))}</cp:lastModifiedBy>'
            '</cp:coreProperties>')

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._content_types())
            z.writestr("_rels/.rels", root_rels)
            z.writestr("word/document.xml", document)
            z.writestr("word/_rels/document.xml.rels", "".join(rels))
            z.writestr("word/styles.xml", self._styles())
            z.writestr("word/footer1.xml", self._footer_xml())
            z.writestr("docProps/core.xml", core_xml)
            for rid, src in self.media.items():
                z.write(src, f"word/media/{self.media_names[rid]}")
        return out_path
