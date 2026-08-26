"""
pdf_writer.py — a small flowing-layout PDF engine (stdlib + Pillow only).

Extends the project's original hand-rolled SimplePDF with the pieces an EMC
report needs: a y-cursor with automatic page breaks, word-wrapped paragraphs
with real Helvetica metrics, coloured headings with a rule, embedded raster
images (PNG/JPEG via Pillow -> DCTDecode XObject), fully formatted tables
(header fill, banded rows, borders, coloured PASS/FAIL cells, header repeated
on overflow), figure captions, and a footer with "Page X of Y".
"""
from __future__ import annotations

import io
import os
from PIL import Image

# Standard Helvetica character widths (1000-em units) for accurate wrapping.
_HELV = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667, "'": 191,
    '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333, '.': 278, '/': 278,
    '0': 556, '1': 556, '2': 556, '3': 556, '4': 556, '5': 556, '6': 556, '7': 556,
    '8': 556, '9': 556, ':': 278, ';': 278, '<': 584, '=': 584, '>': 584, '?': 556,
    '@': 1015, 'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778,
    'H': 722, 'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778,
    'P': 667, 'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944,
    'X': 667, 'Y': 667, 'Z': 611, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556,
    '`': 333, 'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278, 'g': 556,
    'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556, 'o': 556,
    'p': 556, 'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556, 'v': 500, 'w': 722,
    'x': 500, 'y': 500, 'z': 500, '{': 334, '|': 260, '}': 334, '~': 584,
}


def _rgb(hex_c: str):
    c = hex_c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


class PDFDoc:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.brand = cfg["brand"]
        self.fonts = cfg["fonts"]
        m = cfg["page"]
        self.W, self.H = 595.28, 841.89                      # A4 in points
        self.ml = m["margin_left_mm"] * 2.8346
        self.mr = m["margin_right_mm"] * 2.8346
        self.mt = m["margin_top_mm"] * 2.8346
        self.mb = m["margin_bottom_mm"] * 2.8346
        self.content_w = self.W - self.ml - self.mr

        self.objects: list = []
        self.pages: list[int] = []
        self.page_streams: list[str] = []
        self.stream = ""
        self.y = None
        self.images: dict[str, int] = {}       # path -> xobject num
        self.image_names: dict[str, str] = {}  # path -> /ImN
        self._img_seq = 0
        self.footer_cfg = cfg.get("footer", {})
        self.footer_fields = {}
        self._start_page()

    # -- text metrics ---------------------------------------------------------
    def text_width(self, s, size):
        return sum(_HELV.get(ch, 556) for ch in str(s)) / 1000.0 * size

    def _wrap(self, text, size, max_w):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if self.text_width(trial, size) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    # -- page management ------------------------------------------------------
    def _start_page(self):
        if self.stream:
            self.page_streams.append(self.stream)
        self.stream = ""
        self.y = self.mt

    def _ensure(self, needed):
        if self.y + needed > self.H - self.mb:
            self._start_page()

    # Map common Unicode punctuation to WinAnsi byte code points (valid latin-1).
    _WINANSI = {
        "•": "\x95",  # bullet
        "—": "\x97",  # em dash
        "–": "\x96",  # en dash
        "‘": "\x91", "’": "\x92",   # single quotes
        "“": "\x93", "”": "\x94",   # double quotes
        "…": "\x85",  # ellipsis
        "·": "\xb7",  # middle dot
        "™": "\x99",  # trademark
    }

    def _esc(self, s):
        s = str(s)
        for k, v in self._WINANSI.items():
            if k in s:
                s = s.replace(k, v)
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _emit_text(self, x, y, s, size, bold=False, color=None):
        font = "/F2" if bold else "/F1"
        r, g, b = color or _rgb(self.brand["text"])
        self.stream += (f"{r:.3f} {g:.3f} {b:.3f} rg BT {font} {size} Tf "
                        f"{x:.2f} {self.H - y:.2f} Td ({self._esc(s)}) Tj ET\n")

    def _rect(self, x, y, w, h, fill=None, stroke=None, lw=0.5):
        s = ""
        if fill:
            r, g, b = _rgb(fill)
            s += f"{r:.3f} {g:.3f} {b:.3f} rg "
        if stroke:
            r, g, b = _rgb(stroke)
            s += f"{r:.3f} {g:.3f} {b:.3f} RG {lw} w "
        op = "B" if (fill and stroke) else ("f" if fill else "S")
        s += f"{x:.2f} {self.H - y - h:.2f} {w:.2f} {h:.2f} re {op}\n"
        self.stream += s

    def _line(self, x1, y1, x2, y2, w=0.5, color=None):
        r, g, b = color or _rgb(self.brand["table_border"])
        self.stream += (f"{r:.3f} {g:.3f} {b:.3f} RG {w} w "
                        f"{x1:.2f} {self.H - y1:.2f} m {x2:.2f} {self.H - y2:.2f} l S\n")

    # -- public flow API ------------------------------------------------------
    def heading(self, text, level=1):
        sizes = {1: self.fonts["h1_size"], 2: self.fonts["h2_size"], 3: self.fonts["h3_size"]}
        colors = {1: self.brand["primary_dark"], 2: self.brand["primary"], 3: self.brand["text"]}
        before = {1: 16, 2: 12, 3: 8}[level]
        size = sizes[level]
        self._ensure(size + before + 14)
        self.y += before
        self._emit_text(self.ml, self.y + size, text, size, bold=True, color=_rgb(colors[level]))
        self.y += size + 4
        if level == 1:
            self._line(self.ml, self.y, self.ml + self.content_w, self.y, 1.4, _rgb(self.brand["rule"]))
            self.y += 8

    def paragraph(self, text, size=None, color=None, bold=False, gap=6, align="left"):
        size = size or self.fonts["body_size"]
        col = _rgb(color) if color else None
        for line in self._wrap(text, size, self.content_w):
            self._ensure(size + 3)
            x = self.ml
            if align == "center":
                x = self.ml + (self.content_w - self.text_width(line, size)) / 2
            self._emit_text(x, self.y + size, line, size, bold=bold, color=col)
            self.y += size + 3
        self.y += gap

    def bullet(self, text):
        size = self.fonts["body_size"]
        lines = self._wrap(text, size, self.content_w - 14)
        for i, line in enumerate(lines):
            self._ensure(size + 3)
            prefix = "•  " if i == 0 else "   "
            self._emit_text(self.ml + 8, self.y + size, prefix + line, size)
            self.y += size + 3
        self.y += 2

    def caption(self, text):
        self._ensure(14)
        self._emit_text(self.ml, self.y + self.fonts["caption_size"], text,
                        self.fonts["caption_size"], bold=True, color=_rgb(self.brand["muted"]))
        self.y += self.fonts["caption_size"] + 6

    def spacer(self, pts=8):
        self.y += pts

    def page_break(self):
        self._start_page()

    # -- images ---------------------------------------------------------------
    def _register_image(self, path):
        if path in self.image_names:
            return self.image_names[path]
        self._img_seq += 1
        name = f"/Im{self._img_seq}"
        self.image_names[path] = name
        with Image.open(path) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
            jpg = buf.getvalue()
            w, h = im.size
        obj = self._add_obj(
            (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
             f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
             f"/Length {len(jpg)} >>\nstream\n").encode("latin-1") + jpg + b"\nendstream")
        self.images[path] = (obj, name, w, h)
        return name

    def image(self, path, max_width_frac=1.0, caption=None, center=True):
        name = self._register_image(path)
        _, _, iw, ih = self.images[path]
        draw_w = self.content_w * max_width_frac
        draw_h = draw_w * ih / iw
        # if too tall, break page
        self._ensure(draw_h + (14 if caption else 4))
        x = self.ml + (self.content_w - draw_w) / 2 if center else self.ml
        y_top = self.y
        self.stream += (f"q {draw_w:.2f} 0 0 {draw_h:.2f} {x:.2f} "
                        f"{self.H - y_top - draw_h:.2f} cm {name} Do Q\n")
        self.y += draw_h + 4
        if caption:
            self._emit_text(self.ml + (self.content_w - self.text_width(caption, self.fonts["caption_size"])) / 2,
                            self.y + self.fonts["caption_size"], caption,
                            self.fonts["caption_size"], color=_rgb(self.brand["muted"]))
            self.y += self.fonts["caption_size"] + 8

    def image_fullwidth_banner(self, path, height):
        """Cover hero: draw an image spanning the content width at current y."""
        name = self._register_image(path)
        _, _, iw, ih = self.images[path]
        draw_w = self.content_w
        draw_h = height
        x = self.ml
        self.stream += (f"q {draw_w:.2f} 0 0 {draw_h:.2f} {x:.2f} "
                        f"{self.H - self.y - draw_h:.2f} cm {name} Do Q\n")
        self.y += draw_h

    def logo(self, path, width, x=None, y=None):
        """Draw a logo at absolute position (x,y from top-left). Returns height."""
        name = self._register_image(path)
        _, _, iw, ih = self.images[path]
        h = width * ih / iw
        xx = self.ml if x is None else x
        yy = self.y if y is None else y
        self.stream += (f"q {width:.2f} 0 0 {h:.2f} {xx:.2f} "
                        f"{self.H - yy - h:.2f} cm {name} Do Q\n")
        return h

    # -- table ----------------------------------------------------------------
    def table(self, headers, rows, col_fracs=None, status_col=-1):
        b = self.cfg["table_style"]
        n = len(headers)
        fracs = col_fracs or [1] * n
        total = sum(fracs)
        widths = [self.content_w * f / total for f in fracs]
        xs = [self.ml]
        for w in widths:
            xs.append(xs[-1] + w)

        hsize = self.fonts["table_header_size"]
        csize = self.fonts["table_cell_size"]
        pad = b["cell_padding_pt"]
        line_h = csize + 3

        def draw_header():
            self._ensure(hsize + 2 * pad + line_h)
            row_h = hsize + 2 * pad
            self._rect(self.ml, self.y, self.content_w, row_h, fill=self.brand["table_header_fill"])
            for i, htxt in enumerate(headers):
                align = "left" if i == 0 else "center"
                self._cell_text(htxt, xs[i], widths[i], self.y, row_h, hsize, pad,
                                bold=b.get("header_bold", True),
                                color=_rgb(self.brand["table_header_text"]), align=align)
            self.y += row_h

        draw_header()
        for ri, row in enumerate(rows):
            # compute row height from wrapped cells
            cell_lines = []
            for ci, val in enumerate(row):
                lines = self._wrap(val, csize, widths[ci] - 2 * pad - 2)
                cell_lines.append(lines)
            row_h = max(len(l) for l in cell_lines) * line_h + 2 * pad
            if self.y + row_h > self.H - self.mb:
                self._start_page()
                if b["repeat_header_each_page"]:
                    draw_header()
            band = b["banded_rows"] and (ri % 2 == 1)
            if band:
                self._rect(self.ml, self.y, self.content_w, row_h, fill=self.brand["table_band_fill"])
            # borders
            self._rect(self.ml, self.y, self.content_w, row_h,
                       stroke=self.brand["table_border"], lw=b["border_width_pt"])
            for i in range(1, n):
                self._line(xs[i], self.y, xs[i], self.y + row_h,
                           b["border_width_pt"], _rgb(self.brand["table_border"]))
            for ci, lines in enumerate(cell_lines):
                color = None
                is_status = (ci == status_col) or (status_col == -1 and ci == len(row) - 1)
                if b["status_color_coding"] and is_status:
                    v = str(row[ci]).upper()
                    if v in ("PASS", "A"):
                        color = _rgb(self.brand["pass"])
                    elif v in ("FAIL", "B", "C", "D"):
                        color = _rgb(self.brand["fail"])
                align = "left" if ci == 0 else "center"
                self._cell_text_multi(lines, xs[ci], widths[ci], self.y, csize, pad,
                                      line_h, color=color, align=align,
                                      bold=is_status and color is not None)
            self.y += row_h
        self.y += 8

    def _cell_text(self, text, x, w, y, h, size, pad, bold=False, color=None, align="left"):
        tw = self.text_width(text, size)
        if align == "center":
            tx = x + (w - tw) / 2
        elif align == "right":
            tx = x + w - tw - pad
        else:
            tx = x + pad + 1
        ty = y + (h + size) / 2 - 1
        self._emit_text(tx, ty, text, size, bold=bold, color=color)

    def _cell_text_multi(self, lines, x, w, y, size, pad, line_h, color=None, align="left", bold=False):
        ty = y + pad + size
        for line in lines:
            tw = self.text_width(line, size)
            if align == "center":
                tx = x + (w - tw) / 2
            else:
                tx = x + pad + 1
            self._emit_text(tx, ty, line, size, bold=bold, color=color)
            ty += line_h

    # -- cover ----------------------------------------------------------------
    def cover(self, meta, assets_dir):
        cov = self.cfg["cover"]
        # logo top-left
        if cov.get("show_logo"):
            lp = os.path.join(assets_dir, cov["logo"])
            if os.path.exists(lp):
                self.logo(lp, 120, x=self.ml, y=self.mt)
        # partner logo top-right
        if cov.get("show_partner_strip") and cov.get("partner_logo"):
            pp = os.path.join(assets_dir, cov["partner_logo"])
            if os.path.exists(pp):
                self.logo(pp, 46, x=self.W - self.mr - 46, y=self.mt)
        self.y = self.mt + 70
        # classification banner
        if cov.get("classification_banner"):
            self._rect(self.ml, self.y, self.content_w, 22, fill=self.brand["primary_dark"])
            self._emit_text(self.ml + 8, self.y + 15, meta["classification"], 11,
                            bold=True, color=(1, 1, 1))
            self.y += 40
        # hero image
        if cov.get("show_hero_image"):
            hp = os.path.join(assets_dir, cov["hero_image"])
            if os.path.exists(hp):
                self.image_fullwidth_banner(hp, 200)
                self.y += 24
        # title block
        self._emit_text(self.ml, self.y + 24, meta["project_name"], 24, bold=True,
                        color=_rgb(self.brand["primary_dark"]))
        self.y += 40
        self._emit_text(self.ml, self.y + 16, "EMC Compliance Test Report", 16, bold=True,
                        color=_rgb(self.brand["primary"]))
        self.y += 40
        rows = [
            ("Document Number", meta["document_number"]),
            ("Revision", meta["revision"]),
            ("Issue Date", meta["issue_date"]),
            ("Client", meta["client"]),
            ("Test Laboratory", meta["test_lab"]),
            ("Accreditation", meta["accreditation"]),
        ]
        for k, v in rows:
            self._emit_text(self.ml, self.y + 12, k, 10, bold=True, color=_rgb(self.brand["muted"]))
            self._emit_text(self.ml + 130, self.y + 12, v, 10)
            self.y += 20
        self.y += 8
        self._emit_text(self.ml, self.y + 11, "Standards applied:", 10, bold=True,
                        color=_rgb(self.brand["muted"]))
        self.y += 18
        for s in meta["standards"]:
            self.bullet(s)

    # -- unified adapters (shared signature with docx_writer) ----------------
    def add_cover(self, meta, assets_dir):
        self.cover(meta, assets_dir)
        self.page_break()

    def add_table(self, headers, rows, fracs=None, status_col=-1):
        self.table(headers, rows, col_fracs=fracs, status_col=status_col)

    def add_figure(self, path, caption=None):
        self.image(path, max_width_frac=1.0, caption=caption)

    # -- object plumbing ------------------------------------------------------
    def _add_obj(self, content):
        self.objects.append(content)
        return len(self.objects)  # provisional; renumbered at build

    def _footer_stream(self, page_idx, total):
        f = self.footer_cfg
        if not f.get("enabled", True):
            return ""
        col = _rgb(self.brand["muted"])
        y = self.H - self.mb + 14
        left = self.footer_fields.get("left", f.get("left_text", ""))
        center = f.get("center_text", "")
        right = f"Page {page_idx + 1} of {total}"
        s = ""
        r, g, bb = col
        s += f"{r:.3f} {g:.3f} {bb:.3f} RG 0.5 w {self.ml:.2f} {self.H - (self.H - self.mb + 6):.2f} m {self.W - self.mr:.2f} {self.H - (self.H - self.mb + 6):.2f} l S\n"
        def txt(x, string):
            return (f"{r:.3f} {g:.3f} {bb:.3f} rg BT /F1 8 Tf {x:.2f} {self.H - y:.2f} Td "
                    f"({self._esc(string)}) Tj ET\n")
        s += txt(self.ml, left)
        s += txt(self.ml + (self.content_w - self.text_width(center, 8)) / 2, center)
        s += txt(self.W - self.mr - self.text_width(right, 8), right)
        return s

    def _watermark_stream(self):
        opts = self.cfg.get("options", {})
        if not opts.get("watermark_draft"):
            return ""
        text = str(opts.get("watermark_text", "DRAFT"))
        size = 76
        width = self.text_width(text, size)
        cos = sin = 0.7071  # 45 degrees
        dx, dy = -width / 2, -size / 3
        tx = self.W / 2 + cos * dx - sin * dy
        ty = self.H / 2 + sin * dx + cos * dy
        return (f"0.90 0.90 0.90 rg BT /F2 {size} Tf "
                f"{cos:.4f} {sin:.4f} {-sin:.4f} {cos:.4f} {tx:.2f} {ty:.2f} Tm "
                f"({self._esc(text)}) Tj ET\n")

    def build(self, out_path, footer_left=""):
        self.footer_fields["left"] = footer_left
        if self.stream:
            self.page_streams.append(self.stream)
        total = len(self.page_streams)

        # image xobjects already added to self.objects with provisional nums;
        # rebuild object list deterministically.
        objs = []  # (kind, data)
        # 1 catalog, 2 pages, 3 F1, 4 F2 reserved
        image_objnums = {}
        img_obj_start = 5
        image_defs = list(self.images.items())  # path -> (provisionalnum, name, w, h)
        # assign real object numbers to images
        real_num = img_obj_start
        img_xml = {}
        for path, (_, name, w, h) in image_defs:
            image_objnums[path] = real_num
            real_num += 1

        # rebuild image streams
        def image_obj_bytes(path):
            with Image.open(path) as im:
                im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=88)
                jpg = buf.getvalue()
                w, h = im.size
            return ((f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                     f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                     f"/Length {len(jpg)} >>\nstream\n").encode("latin-1") + jpg + b"\nendstream")

        # xobject resource dict entries
        xobj_res = " ".join(f"{name} {image_objnums[path]} 0 R"
                            for path, (_, name, w, h) in image_defs)
        xobj_dict = f"/XObject << {xobj_res} >>" if image_defs else ""

        # page content + page objects come after images
        content_start = real_num
        page_content_nums = []
        page_nums = []
        cnum = content_start
        for i in range(total):
            page_content_nums.append(cnum); cnum += 1
            page_nums.append(cnum); cnum += 1

        # assemble byte objects in order 1..N
        out = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        offsets = {}
        buf = bytearray(out)

        def write_obj(num, data: bytes):
            offsets[num] = len(buf)
            buf.extend(f"{num} 0 obj\n".encode())
            buf.extend(data)
            buf.extend(b"\nendobj\n")

        kids = " ".join(f"{pn} 0 R" for pn in page_nums)
        write_obj(1, f"<< /Type /Catalog /Pages 2 0 R >>".encode())
        write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {total} >>".encode())
        write_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        write_obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        for path, (_, name, w, h) in image_defs:
            write_obj(image_objnums[path], image_obj_bytes(path))
        for i in range(total):
            full = self._watermark_stream() + self.page_streams[i] + self._footer_stream(i, total)
            sb = full.encode("latin-1", "replace")
            write_obj(page_content_nums[i],
                      f"<< /Length {len(sb)} >>\nstream\n".encode() + sb + b"\nendstream")
            res = f"/Font << /F1 3 0 R /F2 4 0 R >> {xobj_dict}"
            write_obj(page_nums[i],
                      (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.W:.2f} {self.H:.2f}] "
                       f"/Contents {page_content_nums[i]} 0 R /Resources << {res} >> >>").encode())

        n_objs = cnum - 1
        xref_off = len(buf)
        buf.extend(f"xref\n0 {n_objs + 1}\n".encode())
        buf.extend(b"0000000000 65535 f \n")
        for num in range(1, n_objs + 1):
            buf.extend(f"{offsets[num]:010d} 00000 n \n".encode())
        buf.extend(f"trailer\n<< /Size {n_objs + 1} /Root 1 0 R >>\nstartxref\n{xref_off}\n%%EOF\n".encode())

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(buf)
        return out_path, total
