# EMC Report Table Builder

A Databricks notebook that lets an engineer **run SQL, wrangle the result table, and save it straight into the EMC compliance report** — built from your *Interactive SQL Query Executor* notebook and wired into the Element EMC Report Studio app.

The original notebook ran a query, let you rename / reorder / hide columns, sort, merge repeated cells and highlight them, then exported a styled PNG + HTML to a Volume. This version keeps all of that and adds one step: it **saves the wrangled table into Unity Catalog** (`emc_gold.report_tables`) so the report app can drop it into the issued `.pdf` / `.docx` — no copy-paste.

```
Gold data  ──SQL──▶  wrangle (rename / sort / merge / highlight)  ──▶  emc_gold.report_tables  ──▶  Report Studio  ──▶  PDF / DOCX
   (Unity Catalog)          (this notebook)                              (Delta table)              (hover a table)     (issued pack)
```

---

## 1. The notebook

`emc_report_table_builder.py` — import it into Databricks (Workspace → Import → File) and attach to a SQL-enabled cluster or serverless.

![Notebook overview](screenshots/01-notebook-overview.png)

It is parameterised entirely with widgets, so nothing needs editing in code:

| Widget | Purpose |
|---|---|
| `catalog`, `gold_schema` | where the EMC Gold data lives |
| `project_id`, `discipline` | which report + section this table is for |
| `table_label` | friendly name shown in the app |
| `sql_query` | any `SELECT` against Gold |
| `rename_columns`, `column_order`, `hide_columns`, `hide_headers` | column shaping |
| `sort_by`, `sort_order` | ordering |
| `merge_columns`, `highlight_color` | merge repeated cells + highlight |
| `volume_path` | optional PNG/HTML export location |

## 2. Run your SQL

Cmd 2 runs the query and shows the raw result. The default pulls worst-case radiated emissions for the selected project.

![Run SQL](screenshots/02-run-sql.png)

## 3. Wrangle the table

Set the customization widgets (Cmd 3) and run Cmd 4 to preview. Below: sorted by **Margin (dB)** descending, trimmed to the worst 6, **Detector** column merged and highlighted — exactly the behaviour from your original notebook.

![Wrangle preview](screenshots/03-wrangle-preview.png)

## 4. Save into Unity Catalog → feeds the PDF

Cmd 5 upserts the wrangled table into `emc_gold.report_tables` (one row per project + section), storing the headers, rows, highlight and the source SQL. This is the bridge to the report.

![Save to Unity Catalog](screenshots/04-save-to-unity-catalog.png)

`report_tables` schema:

| column | type | notes |
|---|---|---|
| `table_key` | string | `"{project_id}__{discipline}"` (upsert key) |
| `project_id`, `discipline`, `label` | string | routing + display |
| `headers`, `rows` | string | JSON — the wrangled table |
| `highlight`, `source_sql`, `updated_at` | string / timestamp | provenance |

Cmd 6 (optional) still exports the styled **PNG + HTML** to a Volume, exactly like the original notebook.

## 5. It appears in the report

In the Report Studio, open the project, hover the matching table, choose **Edit table → Saved report tables**, and pick what the notebook saved. It drops into the document and flows through to the issued PDF and Word pack.

![In the report](screenshots/05-in-the-report.png)

A ready-made example pack is in [`sample_report/`](sample_report/) (`RPT_XR7_2026_001.pdf` / `.docx`).

---

## How the app reads it

The app exposes `GET /api/report-tables?project_id=…`, which reads `emc_gold.report_tables`. The picker in the table editor lists saved tables for the current section; selecting one places its rows (and column headings) into that section and re-renders the document. If the table doesn't exist yet, the app simply shows "none saved" — nothing breaks before the notebook has been run.

## Quick start

1. Import `emc_report_table_builder.py` into Databricks.
2. Set `catalog` / `gold_schema` to your EMC Gold location (default `serverless_stable_1acr1x_catalog.emc_gold`).
3. Edit `sql_query`, set the wrangling widgets, **Run all**.
4. Open the Report Studio → hover the section's table → **Edit table → Saved report tables**.

> The notebook is `SELECT`-only against Gold and writes just the one `report_tables` Delta table; it does not modify the measurement data.
