# EMC demo elements

A self-contained demo that generates polished **`.docx` and `.pdf` EMC compliance
test reports** from a configurable template — pulling the correct tables and
spectrum-analyser plots for a selected project into a house-styled report at the
click of a button.

Built for the Element Materials Technology conversation (Charlie Spackman, EMC &
Wireless lab, Warwick) about automating their large EMC report production.

![cover](assets/element-lab-hero.png)

---

## Why this exists — mapping to the requirement

Charlie's ask was a UI that can:

| Requirement | How the demo shows it |
|---|---|
| Provide a report **template** that is *highly configurable* (e.g. table formatting) | [`templates/report_config.json`](templates/report_config.json) drives fonts, brand colours, table styling (header fill, banded rows, borders, PASS/FAIL colour coding), page setup, cover layout, header/footer and which sections are produced. Duplicate it to make alternative house styles. |
| Select the **project / scope** of data | `--project` selects one of the projects (scopes) in [`data/emc_report.json`](data/emc_report.json). |
| Select the **part of the report** to produce | `--sections cover,radiated_emissions,...` (or the `sections` toggles in the template) produce just those parts. |
| Click **Generate** → pulls the correct data/plots into the template | `python generate.py` assembles the selected sections, embeds the matching spectrum plots and result tables, and writes `.docx` + `.pdf`. |

The demo runs **entirely offline** and with **almost no dependencies** (standard
library + Pillow) so it works on any laptop, in a Databricks notebook, or inside
a Databricks App with nothing to install.

---

## Quick start

```bash
cd "EMC demo elements"

python3 generate.py --list                 # show projects (scopes) & section toggles
python3 generate.py                         # all projects, .docx + .pdf, default template
python3 generate.py --project PRJ-XR7-2026  # one project
python3 generate.py --format pdf            # pdf only
python3 generate.py --sections cover,executive_summary,radiated_emissions

# outputs land in ./output/
```

Generated with the default template:

* `output/RPT_XR7_2026_001.docx` / `.pdf` — XR-7 Advanced Signal Processing Module (7 pp)
* `output/RPT_AVN_2026_014.docx` / `.pdf` — Avalon-9 Automotive Radar ECU (6 pp)

---

## What's in the reports

Cover (logo, partner logo, classification banner, hero image, metadata,
standards) · revision history · contents · executive summary · equipment under
test · summary of results · **radiated emissions** (with spectrum plot vs limit
line) · **conducted emissions** (with plot) · radiated immunity · ESD immunity ·
appendix raw-data table · declaration of conformity. Every table carries the
configured house formatting; PASS/FAIL and criterion A/B cells are colour-coded;
the footer shows *Page X of Y* and the classification.

---

## Repository layout

```
EMC demo elements/
├── generate.py               # the "Generate" button — CLI entry point
├── requirements.txt
├── templates/
│   └── report_config.json    # the configurable template (style + section toggles)
├── data/
│   └── emc_report.json        # report dataset: projects, tables, plot links
├── assets/
│   ├── element-logo.png       # brand assets used on the cover
│   ├── databricks-logo.png
│   ├── element-lab-hero.png
│   └── plots/                 # spectrum-analyser plots (auto-generated)
├── src/
│   ├── spectrum_plots.py      # Pillow spectrum-analyser chart generator
│   ├── docx_writer.py         # hand-rolled OpenXML (.docx) writer — stdlib only
│   ├── pdf_writer.py          # flowing-layout PDF engine — stdlib + Pillow
│   └── report_builder.py      # section assembly (drives both writers)
└── output/                    # generated .docx / .pdf
```

---

## Customising the template

Everything a lab would change for house style lives in `report_config.json`:

* **`brand`** — primary/accent colours, table header fill, band colour, borders,
  PASS/FAIL colours.
* **`fonts`** — families and point sizes for body, headings, table cells/headers,
  captions.
* **`table_style`** — banded rows on/off, border width, cell padding, status
  colour coding, repeat-header-on-overflow.
* **`page`** — A4 margins.
* **`cover` / `header` / `footer`** — logos, hero image, classification banner,
  header/footer text (supports `{document_number}`, `{project_name}`,
  `{classification}`, `{page}`, `{pages}` tokens).
* **`sections`** — a boolean per report part; the UI's "select the part of the
  report" control.

Point `generate.py --template path/to/other.json` at a copy to switch styles.

---

## From demo to production on Databricks

In the real system the two data files are replaced by live sources — the code
path is otherwise identical:

* **`data/emc_report.json` → the Gold layer.** The result tables (radiated /
  conducted emissions, immunity, ESD, appendix) are read from Gold tables in
  Unity Catalog, filtered by the selected project/scope. `report_builder.py`
  already consumes plain lists of rows, so this is a query swap.
* **`assets/plots/*.png` → Azure + the linking table.** Rather than generating
  plots, the builder looks up each measurement record's plot location via the
  table that links measurement records to image blobs in Azure, and streams the
  image into the report. `spectrum_plots.py` is the offline stand-in.
* **`generate.py` → a Databricks App.** Wrap the same functions behind a small
  FastAPI/React UI (template upload, scope picker, section checkboxes, Generate
  button). The 700-page scale is handled by the auto-paginating writers and
  header-repeat-on-overflow tables already implemented here.

---

## Notes

* The `.docx` files are genuine OpenXML packages (a ZIP of XML parts) and open in
  Microsoft Word, Google Docs and LibreOffice. Validated with macOS `textutil`.
* The `.pdf` files are hand-assembled PDF 1.4 with embedded JPEG images and a
  WinAnsi-encoded Helvetica — no PDF library required.
* Spectrum plots are rendered with Pillow (no matplotlib) so there is nothing to
  compile or download.
