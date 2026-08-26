#!/usr/bin/env python3
"""
generate.py — the "Generate" button for the Element EMC report demo.

This is the offline stand-in for the UI Charlie described: pick a template,
pick the project/scope, pick which report sections to produce, and generate the
report — pulling the right tables and spectrum-analyser plots into the template
— as .docx, .pdf, or both.

Examples
--------
  python generate.py                          # all projects, both formats, default template
  python generate.py --project PRJ-XR7-2026    # one project
  python generate.py --format pdf              # pdf only
  python generate.py --sections cover,executive_summary,radiated_emissions
  python generate.py --list                    # list available projects & sections
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from docx_writer import DocxWriter          # noqa: E402
from pdf_writer import PDFDoc                # noqa: E402
import report_builder                        # noqa: E402
import spectrum_plots                        # noqa: E402

ASSETS = os.path.join(HERE, "assets")
PLOTS = os.path.join(ASSETS, "plots")
OUTPUT = os.path.join(HERE, "output")
DATA = os.path.join(HERE, "data", "emc_report.json")
DEFAULT_TEMPLATE = os.path.join(HERE, "templates", "report_config.json")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def ensure_plots(project, cfg):
    """Generate the spectrum plots for a project if they are not already present."""
    pid = project["project_id"]
    brand = cfg["brand"]
    re_plot = os.path.join(PLOTS, f"{pid}_radiated_emissions.png")
    ce_plot = os.path.join(PLOTS, f"{pid}_conducted_emissions.png")
    if not os.path.exists(re_plot):
        spectrum_plots.build_radiated_emissions(
            re_plot, brand, project["radiated_emissions"]["table_rows"],
            project["radiated_emissions"]["standard"])
    if not os.path.exists(ce_plot):
        spectrum_plots.build_conducted_emissions(
            ce_plot, brand, project["conducted_emissions"]["table_rows"],
            project["conducted_emissions"]["standard"])


def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")


def generate_one(project, cfg, formats, output_dir=None):
    ensure_plots(project, cfg)
    footer_left = cfg["footer"]["left_text"].format(
        document_number=project["document_number"],
        project_name=project["project_name"],
        classification=project["classification"])
    base = slug(project["document_number"])
    dest = output_dir or OUTPUT
    os.makedirs(dest, exist_ok=True)
    written = []

    if "docx" in formats:
        w = DocxWriter(cfg)
        report_builder.build_report(w, project, cfg, PLOTS, ASSETS)
        out = os.path.join(dest, f"{base}.docx")
        w.build(out, cfg["page"],
                {"title": f"{project['project_name']} — EMC Report",
                 "author": project["test_lab"]})
        written.append((out, os.path.getsize(out), None))

    if "pdf" in formats:
        p = PDFDoc(cfg)
        report_builder.build_report(p, project, cfg, PLOTS, ASSETS)
        out = os.path.join(dest, f"{base}.pdf")
        _, pages = p.build(out, footer_left=footer_left)
        written.append((out, os.path.getsize(out), pages))

    return written


def main():
    ap = argparse.ArgumentParser(description="Generate Element EMC compliance reports (.docx / .pdf).")
    ap.add_argument("--project", default="all", help="project_id, or 'all' (default)")
    ap.add_argument("--format", default="both", choices=["docx", "pdf", "both"])
    ap.add_argument("--template", default=DEFAULT_TEMPLATE, help="template config JSON")
    ap.add_argument("--sections", default=None,
                    help="comma-separated section keys to include (overrides template)")
    ap.add_argument("--list", action="store_true", help="list projects and sections, then exit")
    args = ap.parse_args()

    cfg = load_json(args.template)
    data = load_json(DATA)
    projects = data["projects"]

    if args.list:
        print("\nProjects (scopes):")
        for p in projects:
            print(f"  {p['project_id']:16s}  {p['project_name']}  [{p['document_number']} rev {p['revision']}]")
        print("\nSections (template toggles):")
        for k, v in cfg["sections"].items():
            print(f"  {'[x]' if v else '[ ]'} {k}")
        return

    if args.sections:
        wanted = {s.strip() for s in args.sections.split(",")}
        cfg["sections"] = {k: (k in wanted) for k in cfg["sections"]}

    if args.project != "all":
        projects = [p for p in projects if p["project_id"] == args.project]
        if not projects:
            sys.exit(f"No project with id '{args.project}'. Use --list to see options.")

    formats = ["docx", "pdf"] if args.format == "both" else [args.format]
    os.makedirs(OUTPUT, exist_ok=True)

    print(f"Template : {cfg['template_name']}")
    print(f"Sections : {', '.join(k for k, v in cfg['sections'].items() if v)}")
    print(f"Formats  : {', '.join(formats)}\n")

    for project in projects:
        print(f"► {project['project_name']} ({project['project_id']})")
        for path, size, pages in generate_one(project, cfg, formats):
            extra = f", {pages} pages" if pages else ""
            print(f"    ✓ {os.path.relpath(path, HERE)}  ({size:,} bytes{extra})")
    print("\nDone. Files are in ./output/")


if __name__ == "__main__":
    main()
