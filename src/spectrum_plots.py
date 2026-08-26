"""
spectrum_plots.py — spectrum-analyser style charts for EMC reports.

Pure Pillow (no matplotlib) so the demo runs on a stock Python + Pillow install.
Each function renders a log-frequency emissions plot with a compliance limit
line and a measured trace, then saves a PNG into assets/plots/.

In production these images already exist in Azure and are referenced from the
Gold-layer image table; this module stands in for that so the demo is offline.
"""
from __future__ import annotations

import math
import os
import random
from PIL import Image, ImageDraw, ImageFont


# ---- styling ---------------------------------------------------------------

def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _font(size: int, bold: bool = False):
    """Best-effort system font; falls back to Pillow's bitmap font."""
    candidates = (
        ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/HelveticaNeue.ttc"]
        if bold else
        ["/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/HelveticaNeue.ttc"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---- core plotter ----------------------------------------------------------

def _render_plot(
    out_path: str,
    title: str,
    f_min: float,
    f_max: float,
    y_min: float,
    y_max: float,
    y_label: str,
    limit_points,          # list[(freq_mhz, dB)] — the compliance limit line
    peak_markers,          # list[(freq_mhz, dB, label)] — measured peaks to mark
    brand,
    scale: int = 2,
):
    W, H = 900 * scale, 520 * scale
    pad_l, pad_r, pad_t, pad_b = 78 * scale, 30 * scale, 54 * scale, 62 * scale
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_t - pad_b

    ink = _hex(brand.get("text", "#1A1A1A"))
    muted = _hex(brand.get("muted", "#5F6B7A"))
    grid = (222, 228, 236)
    limit_col = _hex(brand.get("fail", "#D93025"))
    trace_col = _hex(brand.get("primary", "#0B5FFF"))
    fill_col = _hex(brand.get("primary", "#0B5FFF")) + (46,)

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img, "RGBA")

    lf_min, lf_max = math.log10(f_min), math.log10(f_max)

    def fx(freq):
        return pad_l + (math.log10(freq) - lf_min) / (lf_max - lf_min) * plot_w

    def fy(db):
        return pad_t + (y_max - db) / (y_max - y_min) * plot_h

    # plot frame
    d.rectangle([pad_l, pad_t, pad_l + plot_w, pad_t + plot_h],
                fill=(252, 253, 255), outline=muted, width=scale)

    # decade gridlines + labels
    f_axis = _font(13 * scale)
    dec = math.floor(lf_min)
    while dec <= math.ceil(lf_max):
        base = 10 ** dec
        for m in range(1, 10):
            fv = base * m
            if fv < f_min or fv > f_max:
                continue
            x = fx(fv)
            major = (m == 1)
            d.line([x, pad_t, x, pad_t + plot_h],
                   fill=grid, width=(2 if major else 1) * (scale // 2 or 1))
            if major:
                lbl = _fmt_freq(fv)
                tw = d.textlength(lbl, font=f_axis)
                d.text((x - tw / 2, pad_t + plot_h + 6 * scale), lbl,
                       fill=ink, font=f_axis)
        dec += 1

    # horizontal gridlines + dB labels
    y_step = _nice_step(y_max - y_min)
    yv = math.ceil(y_min / y_step) * y_step
    while yv <= y_max:
        y = fy(yv)
        d.line([pad_l, y, pad_l + plot_w, y], fill=grid, width=scale // 2 or 1)
        lbl = f"{int(yv)}"
        tw = d.textlength(lbl, font=f_axis)
        d.text((pad_l - tw - 8 * scale, y - 8 * scale), lbl, fill=ink, font=f_axis)
        yv += y_step

    # ---- measured trace: dense random-walk floor with the given peaks -------
    trace = _synth_trace(f_min, f_max, y_min, y_max, limit_points, peak_markers)
    poly = [(fx(f), fy(v)) for f, v in trace]
    # filled area under trace
    area = poly + [(poly[-1][0], pad_t + plot_h), (poly[0][0], pad_t + plot_h)]
    d.polygon(area, fill=fill_col)
    d.line(poly, fill=trace_col, width=2 * scale, joint="curve")

    # ---- limit line (red, stepped) ------------------------------------------
    lp = [(fx(f), fy(v)) for f, v in limit_points]
    d.line(lp, fill=limit_col, width=3 * scale, joint="curve")

    # peak markers
    f_mark = _font(12 * scale, bold=True)
    for freq, db, label in peak_markers:
        x, y = fx(freq), fy(db)
        r = 5 * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill=limit_col, outline="white",
                  width=scale)
        txt = label
        tw = d.textlength(txt, font=f_mark)
        bx = min(max(x - tw / 2, pad_l + 2), pad_l + plot_w - tw - 2)
        d.text((bx, y - 22 * scale), txt, fill=ink, font=f_mark)

    # axis labels + title
    f_title = _font(18 * scale, bold=True)
    f_lab = _font(13 * scale, bold=True)
    d.text((pad_l, 16 * scale), title, fill=_hex(brand.get("primary_dark", "#0A2540")),
           font=f_title)
    # x label
    xl = "Frequency"
    d.text((pad_l + plot_w / 2 - d.textlength(xl, font=f_lab) / 2,
            H - 26 * scale), xl, fill=muted, font=f_lab)
    # y label (rotated)
    yl_img = Image.new("RGBA", (int(d.textlength(y_label, font=f_lab)) + 8 * scale,
                                22 * scale), (0, 0, 0, 0))
    yd = ImageDraw.Draw(yl_img)
    yd.text((0, 0), y_label, fill=muted, font=f_lab)
    yl_img = yl_img.rotate(90, expand=True)
    img.paste(yl_img, (6 * scale, pad_t + plot_h // 2 - yl_img.height // 2), yl_img)

    # legend
    lx, ly = pad_l + plot_w - 190 * scale, pad_t + 10 * scale
    d.rectangle([lx, ly, lx + 178 * scale, ly + 46 * scale],
                fill=(255, 255, 255, 235), outline=muted, width=scale)
    d.line([lx + 8 * scale, ly + 14 * scale, lx + 34 * scale, ly + 14 * scale],
           fill=trace_col, width=3 * scale)
    d.text((lx + 42 * scale, ly + 6 * scale), "Measured (QP)", fill=ink, font=f_axis)
    d.line([lx + 8 * scale, ly + 32 * scale, lx + 34 * scale, ly + 32 * scale],
           fill=limit_col, width=3 * scale)
    d.text((lx + 42 * scale, ly + 24 * scale), "Limit", fill=ink, font=f_axis)

    img = img.resize((W // scale, H // scale), Image.LANCZOS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _fmt_freq(mhz: float) -> str:
    if mhz >= 1000:
        v = mhz / 1000
        return f"{v:g} GHz"
    if mhz >= 1:
        return f"{mhz:g} MHz"
    return f"{int(mhz * 1000)} kHz"


def _nice_step(span: float) -> float:
    for s in (5, 10, 20, 25, 50):
        if span / s <= 8:
            return s
    return 100


def _interp_limit(freq, limit_points):
    """Linear interpolation of the limit line at a given frequency."""
    pts = limit_points
    if freq <= pts[0][0]:
        return pts[0][1]
    if freq >= pts[-1][0]:
        return pts[-1][1]
    for (f0, v0), (f1, v1) in zip(pts, pts[1:]):
        if f0 <= freq <= f1:
            t = (math.log10(freq) - math.log10(f0)) / (math.log10(f1) - math.log10(f0))
            return v0 + t * (v1 - v0)
    return pts[-1][1]


def _synth_trace(f_min, f_max, y_min, y_max, limit_points, peaks):
    """Build a realistic emissions floor as a log-frequency random walk that
    stays below the limit, then splice in the marked peaks."""
    rnd = random.Random(hash((f_min, f_max, tuple(map(tuple, peaks)))) & 0xFFFF)
    n = 260
    lf0, lf1 = math.log10(f_min), math.log10(f_max)
    floor_base = y_min + (y_max - y_min) * 0.18
    trace = []
    val = floor_base
    for i in range(n):
        lf = lf0 + (lf1 - lf0) * i / (n - 1)
        freq = 10 ** lf
        val += rnd.uniform(-2.2, 2.2)
        limit = _interp_limit(freq, limit_points)
        ceiling = limit - 7          # keep the broadband floor comfortably under
        val = max(y_min + 3, min(val, ceiling))
        # gentle upward tilt with frequency (typical broadband behaviour)
        tilt = (lf - lf0) / (lf1 - lf0) * 6
        trace.append((freq, min(val + tilt, ceiling)))
    # splice peaks: raise nearby samples toward the peak value
    for pf, pv, _ in peaks:
        for j, (f, v) in enumerate(trace):
            d_oct = abs(math.log10(f) - math.log10(pf))
            if d_oct < 0.035:
                trace[j] = (f, max(v, pv))
            elif d_oct < 0.09:
                trace[j] = (f, max(v, pv - (d_oct / 0.09) * 14))
    return trace


# ---- public builders -------------------------------------------------------

def build_radiated_emissions(out_path, brand, table_rows, standard=""):
    """Radiated emissions plot 30 MHz - 6 GHz with a stepped Class-B-style limit."""
    limit = [(30, 40), (230, 40), (230.01, 47), (1000, 47), (6000, 47)]
    peaks = []
    for row in table_rows[:4]:
        try:
            f = float(row[0]); v = float(row[1])
            peaks.append((f, v, f"{f:g} MHz"))
        except (ValueError, IndexError):
            continue
    return _render_plot(
        out_path,
        f"Radiated Emissions vs Limit  ({standard})".strip(),
        f_min=30, f_max=6000, y_min=0, y_max=60,
        y_label="Level (dBuV/m)",
        limit_points=limit, peak_markers=peaks, brand=brand,
    )


def build_conducted_emissions(out_path, brand, table_rows, standard=""):
    """Conducted emissions plot 150 kHz - 30 MHz with QP limit."""
    limit = [(0.15, 66), (0.5, 66), (0.5001, 60), (5, 60), (5.0001, 60), (30, 60)]
    peaks = []
    for row in table_rows[:4]:
        try:
            f = float(row[0]); v = float(row[1])
            peaks.append((f, v, f"{f:g} MHz"))
        except (ValueError, IndexError):
            continue
    return _render_plot(
        out_path,
        f"Conducted Emissions vs Limit  ({standard})".strip(),
        f_min=0.15, f_max=30, y_min=20, y_max=80,
        y_label="Level (dBuV)",
        limit_points=limit, peak_markers=peaks, brand=brand,
    )


if __name__ == "__main__":
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(here, "templates", "report_config.json")))
    data = json.load(open(os.path.join(here, "data", "emc_report.json")))
    brand = cfg["brand"]
    for p in data["projects"]:
        pid = p["project_id"]
        build_radiated_emissions(
            os.path.join(here, "assets", "plots", f"{pid}_radiated_emissions.png"),
            brand, p["radiated_emissions"]["table_rows"],
            p["radiated_emissions"]["standard"])
        build_conducted_emissions(
            os.path.join(here, "assets", "plots", f"{pid}_conducted_emissions.png"),
            brand, p["conducted_emissions"]["table_rows"],
            p["conducted_emissions"]["standard"])
        print("plots built for", pid)
