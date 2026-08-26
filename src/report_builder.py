"""
report_builder.py — assemble an EMC report into a writer (docx or pdf).

`build_report` walks the selected sections (from the template config) and pulls
the matching tables and spectrum-analyser plots for the chosen project/scope.
The same code drives both the .docx and .pdf writers because they share a
common interface (heading / paragraph / bullet / caption / add_table /
add_figure / add_cover / page_break / spacer).
"""
from __future__ import annotations

import os

# Column proportions per table (kept sensible for A4 width)
_COLS = {
    "summary": [3.2, 2.6, 4.0, 1.4],
    "re": [1.4, 2.0, 2.0, 1.5, 1.3, 1.0, 1.3],
    "ce": [1.4, 1.6, 1.6, 1.6, 1.6, 1.2, 1.3],
    "rs": [2.2, 1.6, 1.0, 1.4, 3.0, 1.3],
    "esd": [3.0, 1.5, 2.0, 1.6, 3.0, 1.3],
    "appendix": [1.6, 1.6, 1.4, 1.3, 1.3, 1.5, 1.3],
    "rev": [1.2, 2.0, 2.4, 5.0],
    "approvals": [2.2, 2.4, 3.4, 2.0],
}


def _fracs(key, headers):
    """Column proportions only apply when the table still has its usual columns."""
    cols = _COLS.get(key)
    return cols if cols and len(cols) == len(headers) else None


def build_report(w, project, cfg, plots_dir, assets_dir):
    sec = cfg["sections"]
    opts = cfg["options"]
    pid = project["project_id"]

    # ---- cover ----
    if sec.get("cover"):
        w.add_cover(project, assets_dir)

    # ---- revision history ----
    if sec.get("revision_history"):
        w.heading("Revision History", 1)
        w.add_table(["Rev", "Date", "Author", "Description"],
                    project["revision_history"], _COLS["rev"], status_col=None)
        w.spacer(8)

    # ---- table of contents (static outline) ----
    if sec.get("table_of_contents"):
        w.heading("Contents", 1)
        toc = [
            "1  Executive Summary",
            "2  Equipment Under Test",
            "3  Summary of Results",
            "4  Radiated Emissions",
            "5  Conducted Emissions",
            "6  Radiated Immunity",
            "7  Electrostatic Discharge Immunity",
            "8  Appendix — Raw Data",
            "9  Declaration of Conformity",
        ]
        for t in toc:
            w.bullet(t)
        w.page_break()

    # ---- executive summary ----
    if sec.get("executive_summary"):
        w.heading("1  Executive Summary", 1)
        n_pass = sum(1 for r in project["summary_rows"] if str(r[-1]).upper() == "PASS")
        total = len(project["summary_rows"])
        overall = "PASS — full compliance" if n_pass == total else f"{n_pass}/{total} disciplines passed"
        w.paragraph(
            f"This report presents the electromagnetic compatibility (EMC) qualification results for the "
            f"{project['project_name']} ({project['eut']['model']}, S/N {project['eut']['serial']}), tested "
            f"at {project['test_lab']} on behalf of {project['client']}.")
        w.paragraph(f"Overall result: {overall}.", bold=True,
                    color=cfg["brand"]["pass"] if n_pass == total else cfg["brand"]["fail"])
        w.paragraph(
            "Testing was performed against the standards listed on the cover page. The sections that follow "
            "detail each discipline, the applicable limits, the measured results and the compliance margin. "
            "Full measurement extracts are provided in the appendix.")

    # ---- EUT description ----
    if sec.get("eut_description"):
        w.heading("2  Equipment Under Test", 1)
        eut = project["eut"]
        w.paragraph(eut["description"])
        w.add_table(["Attribute", "Value"], [
            ["Model", eut["model"]],
            ["Serial Number", eut["serial"]],
            ["Power Supply", eut["supply"]],
            ["Dimensions", eut["dimensions"]],
            ["Operating Modes", eut["modes"]],
            ["Cables / Ports", eut["cables"]],
        ], [1.6, 5.0], status_col=None)

    # ---- summary of results ----
    if sec.get("test_summary"):
        w.heading("3  Summary of Results", 1)
        w.caption("Table 3-1. Summary of EMC test results.")
        headers = project.get("summary_headers") or [
            "Discipline", "Standard / Limit", "Key Result", "Status",
        ]
        w.add_table(headers, project["summary_rows"], _fracs("summary", headers))

    # ---- radiated emissions ----
    if sec.get("radiated_emissions"):
        re = project["radiated_emissions"]
        w.heading("4  Radiated Emissions", 1)
        w.paragraph(f"Standard: {re['standard']}    Site: {re['site']}    Detector: {re['detector']}",
                    color=cfg["brand"]["muted"], size=cfg["fonts"]["body_size"] - 1)
        w.paragraph(re["narrative"])
        plot = os.path.join(plots_dir, f"{pid}_radiated_emissions.png")
        if opts.get("include_plots") and os.path.exists(plot):
            w.add_figure(plot, re["plot_caption"])
        w.caption(re["table_caption"])
        w.add_table(re["table_headers"], re["table_rows"], _fracs("re", re["table_headers"]))

    # ---- conducted emissions ----
    if sec.get("conducted_emissions"):
        ce = project["conducted_emissions"]
        w.heading("5  Conducted Emissions", 1)
        w.paragraph(f"Standard: {ce['standard']}    Site: {ce['site']}    Detector: {ce['detector']}",
                    color=cfg["brand"]["muted"], size=cfg["fonts"]["body_size"] - 1)
        w.paragraph(ce["narrative"])
        plot = os.path.join(plots_dir, f"{pid}_conducted_emissions.png")
        if opts.get("include_plots") and os.path.exists(plot):
            w.add_figure(plot, ce["plot_caption"])
        w.caption(ce["table_caption"])
        w.add_table(ce["table_headers"], ce["table_rows"], _fracs("ce", ce["table_headers"]))

    # ---- radiated immunity ----
    if sec.get("radiated_immunity"):
        rs = project["radiated_immunity"]
        w.heading("6  Radiated Immunity", 1)
        w.paragraph(f"Standard: {rs['standard']}    Field: {rs['field']}",
                    color=cfg["brand"]["muted"], size=cfg["fonts"]["body_size"] - 1)
        w.paragraph(rs["narrative"])
        w.caption(rs["table_caption"])
        w.add_table(rs["table_headers"], rs["table_rows"], _fracs("rs", rs["table_headers"]))

    # ---- ESD immunity ----
    if sec.get("esd_immunity"):
        esd = project["esd_immunity"]
        w.heading("7  Electrostatic Discharge Immunity", 1)
        w.paragraph(f"Standard: {esd['standard']}    Levels: {esd['levels']}",
                    color=cfg["brand"]["muted"], size=cfg["fonts"]["body_size"] - 1)
        w.paragraph(esd["narrative"])
        w.caption(esd["table_caption"])
        w.add_table(esd["table_headers"], esd["table_rows"], _fracs("esd", esd["table_headers"]))

    # ---- appendix ----
    if sec.get("appendix_raw_data"):
        ap = project["appendix"]
        w.heading("8  Appendix — Raw Data", 1)
        w.caption(ap["table_caption"])
        w.add_table(ap["table_headers"], ap["table_rows"], _fracs("appendix", ap["table_headers"]))

    # ---- declaration ----
    if sec.get("declaration"):
        w.heading("9  Declaration of Conformity", 1)
        w.paragraph(
            f"On the basis of the tests described in this report, the {project['project_name']} "
            f"({project['eut']['model']}) is assessed as compliant with the requirements of the standards "
            "listed, for the configuration and operating modes tested.")
        w.spacer(8)
        w.caption("Table 9-1. Approvals.")
        w.add_table(["Role", "Name", "Title", "Date"], project["approvals"],
                    _COLS["approvals"], status_col=None)
