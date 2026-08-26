"""Live document model — the same content the PDF writer receives, as JSON blocks.

The report is assembled once by ``report_builder.build_report``; this collector
implements the writer interface so the browser can render an identical-looking,
hoverable document where each table knows which report section and SQL it came
from.
"""
from __future__ import annotations

import os
from typing import Any

from . import gold

# heading text -> report section key used by table overrides
_SECTION_BY_HEADING = (
    ("summary of results", "test_summary"),
    ("radiated emissions", "radiated_emissions"),
    ("conducted emissions", "conducted_emissions"),
    ("radiated immunity", "radiated_immunity"),
    ("electrostatic discharge", "esd_immunity"),
    ("appendix", "appendix"),
)

_MEASUREMENT_SECTIONS = {
    "radiated_emissions",
    "conducted_emissions",
    "radiated_immunity",
    "esd_immunity",
    "appendix",
}


def default_sql(section: str, project_id: str) -> str:
    schema = gold.SCHEMA
    if section == "test_summary":
        return (
            f"SELECT discipline,\n"
            f"       count(*) AS points,\n"
            f"       round(min(margin_db), 1) AS worst_margin_db,\n"
            f"       CASE WHEN min(margin_db) < 0 THEN 'FAIL' ELSE 'PASS' END AS status\n"
            f"FROM {schema}.measurements\n"
            f"WHERE project_id = '{project_id}'\n"
            f"GROUP BY discipline\n"
            f"ORDER BY discipline"
        )
    if section in _MEASUREMENT_SECTIONS:
        return (
            f"SELECT cells\n"
            f"FROM {schema}.measurements\n"
            f"WHERE project_id = '{project_id}'\n"
            f"  AND discipline = '{section}'\n"
            f"ORDER BY row_index\n"
            f"LIMIT 50"
        )
    return ""


class DocumentCollector:
    """Writer-shaped sink that records blocks instead of drawing pages."""

    def __init__(self, project: dict[str, Any], cfg: dict[str, Any], assets_dir: str):
        self.project = project
        self.cfg = cfg
        self.assets_dir = assets_dir
        self.blocks: list[dict[str, Any]] = []
        self._heading = ""
        self._caption = ""
        self._table_seq = 0

    # -- helpers --------------------------------------------------------------
    def _asset_url(self, path: str) -> str:
        rel = os.path.relpath(path, self.assets_dir).replace(os.sep, "/")
        return f"/assets/{rel}"

    def _section_key(self) -> str:
        text = self._heading.lower()
        for needle, key in _SECTION_BY_HEADING:
            if needle in text:
                return key
        return ""

    # -- writer interface -----------------------------------------------------
    def add_cover(self, meta: dict[str, Any], assets_dir: str) -> None:
        cover = self.cfg.get("cover", {})

        def art(key: str, enabled: bool) -> str:
            path = os.path.join(assets_dir, cover.get(key, ""))
            return self._asset_url(path) if enabled and os.path.exists(path) else ""

        self.blocks.append({
            "type": "cover",
            "classification": meta["classification"] if cover.get("classification_banner", True) else "",
            "project_name": meta["project_name"],
            "subtitle": "EMC Compliance Test Report",
            "hero": art("hero_image", cover.get("show_hero_image", True)),
            "logo": art("logo", cover.get("show_logo", True)),
            "partner": art("partner_logo", cover.get("show_partner_strip", True)),
            "fields": [
                ["Document Number", meta["document_number"]],
                ["Revision", meta["revision"]],
                ["Issue Date", meta["issue_date"]],
                ["Client", meta["client"]],
                ["Test Laboratory", meta["test_lab"]],
                ["Accreditation", meta.get("accreditation", "")],
            ],
            "standards": list(meta.get("standards", [])),
        })

    def heading(self, text: str, level: int = 1) -> None:
        self._heading = text
        self.blocks.append({"type": "heading", "text": text, "level": level})

    def paragraph(self, text: str, size=None, color=None, bold=False, gap=6, align="left") -> None:
        self.blocks.append({
            "type": "paragraph",
            "text": text,
            "bold": bool(bold),
            "color": color or "",
            "muted": color == self.cfg.get("brand", {}).get("muted"),
        })

    def bullet(self, text: str) -> None:
        self.blocks.append({"type": "bullet", "text": text})

    def caption(self, text: str) -> None:
        # captions always introduce the next table — hold it so the table owns it
        if self._caption:
            self.blocks.append({"type": "caption", "text": self._caption})
        self._caption = text

    def spacer(self, pts: int = 8) -> None:
        pass

    def page_break(self) -> None:
        self.blocks.append({"type": "pagebreak"})

    def add_figure(self, path: str, caption: str | None = None) -> None:
        if not os.path.exists(path):
            return
        self.blocks.append({
            "type": "figure",
            "src": self._asset_url(path),
            "caption": caption or "",
        })

    def add_table(self, headers, rows, fracs=None, status_col=-1) -> None:
        self._table_seq += 1
        section = self._section_key()
        norm = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
        self.blocks.append({
            "type": "table",
            "table_id": f"t{self._table_seq}",
            "section": section,
            "editable": bool(section),
            "headers": [str(h) for h in headers],
            "rows": norm,
            "widths": list(fracs) if fracs else [],
            "status_col": status_col,
            "caption": self._caption,
            "sql": default_sql(section, self.project["project_id"]) if section else "",
        })
        self._caption = ""
