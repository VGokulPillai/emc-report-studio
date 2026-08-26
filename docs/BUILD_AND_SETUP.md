# EMC Report Studio — Build & Setup Guide

A Databricks App that turns Unity Catalog **Gold** lab data into a house‑styled
`.docx` / `.pdf` EMC test report. This guide explains how the system is put
together, how to set it up in a fresh workspace, and how to extend it — so you
can hand it to a client and they can run and adapt it themselves.

---

## 1. What it does (the end‑to‑end flow)

```
  Lakeflow DLT pipeline            Unity Catalog (Gold)            FastAPI Databricks App
 ┌───────────────────┐      ┌──────────────────────────┐      ┌──────────────────────────┐
 │ bronze → silver → │  →   │ projects                 │  →   │  Lab data  · browse UC   │
 │ gold (emc_pipeline)│     │ section_meta             │      │  Wrangle   · shape tables│
 └───────────────────┘      │ measurements             │      │  Report    · build PDF   │
                            │ report_tables  ◄─────────┼──────┤  (saved wrangled tables) │
                            └──────────────────────────┘      └──────────────────────────┘
                                          ▲                                  │
                                          └──────── Save to Gold ────────────┘
                                              (in‑app wrangler writes here)
```

The three app tabs map to the three things a lab engineer does:

1. **Lab data** — search Unity Catalog and preview the raw measurement tables.
2. **Wrangle** — run a SQL SELECT, then reshape the result (rename / reorder /
   hide / sort / merge repeated values / highlight) and **save it to Gold**
   (`emc_gold.report_tables`). This is the notebook *Interactive SQL Query
   Executor*, rebuilt as a UI.
3. **Report** — choose a template, project scope and sections, drop in any saved
   wrangled table, then click **Issue the pack** to render the `.docx` + `.pdf`.

The **Wrangle → Save to Gold → Report** path is the important one: data is
wrangled *before* it lands in the PDF, and every wrangled table is versioned in
Unity Catalog so it can be reused, audited and regenerated.

---

## 2. Repository layout

| Path | Purpose |
|------|---------|
| `app.py` | FastAPI app: all `/api/*` routes, template merge, report jobs. |
| `server/gold.py` | Unity Catalog access (SELECT guard, `report_tables` read/write). |
| `server/wrangle.py` | The wrangling transform (single source of truth). |
| `server/agent.py` | NL→SQL / SQL‑rewrite via the serving endpoint. |
| `server/docmodel.py` | Builds the live HTML document blocks (hover‑to‑edit). |
| `src/` | Offline report engine (`report_builder`, `pdf_writer`, `docx_writer`, `spectrum_plots`). |
| `generate.py` | Wraps the engine; produces `.docx` / `.pdf` from a project + template. |
| `templates/*.json` | House styles (fully configurable — see §6). |
| `static/` | Frontend (`index.html`, `app.js`, `styles.css`). |
| `notebooks/` | `emc_report_table_builder.py` — the notebook version of the wrangler. |
| `pipelines/` | Lakeflow DLT that produces the Gold tables. |
| `app.yaml` | App runtime + resource bindings. |

---

## 3. Prerequisites

- Databricks workspace with **Unity Catalog** and a **SQL warehouse**.
- A **Serving endpoint** (Foundation Model API) for the NL→SQL features.
- Databricks CLI (`databricks -v` ≥ 0.230) authenticated to the workspace.
- The Gold schema populated by the DLT pipeline in `pipelines/` (bronze → silver
  → gold), or the bundled demo JSON in `data/` (used automatically when no
  warehouse is connected).

---

## 4. Configuration

The app is configured entirely through environment variables (see `app.yaml`):

| Variable | Meaning | Example |
|----------|---------|---------|
| `EMC_UC_SCHEMA` | Catalog + schema holding the Gold tables. | `serverless_stable_1acr1x_catalog.emc_gold` |
| `DATABRICKS_WAREHOUSE_ID` | Warehouse used for all SQL. | bound via `valueFrom: sql-warehouse` |
| `SERVING_ENDPOINT` | Model serving endpoint for NL→SQL. | bound via `valueFrom: serving-endpoint` |

In `app.yaml`, `DATABRICKS_WAREHOUSE_ID` and `SERVING_ENDPOINT` are wired as
**app resources** (`valueFrom`), so they are granted and injected by the platform
at deploy time. `EMC_UC_SCHEMA` is a plain value you point at your own catalog.

> The app degrades gracefully: if no warehouse is bound it serves the bundled
> demo data from `data/`, and the **Wrangle**/**Save to Gold** features are
> simply disabled until a warehouse is present.

### Grants needed
The app's service principal needs:
- `USE CATALOG` / `USE SCHEMA` on your catalog + `emc_gold`.
- `SELECT` on `projects`, `section_meta`, `measurements`.
- `SELECT`, `MODIFY`, and `CREATE TABLE` on the schema (so the wrangler can
  create and upsert `report_tables`).

---

## 5. Deploy

From the project root, with the CLI authenticated (`databricks auth login`):

```bash
# 1) sync source into the workspace
databricks sync . /Workspace/Users/<you>/apps/element-emc-reports \
  --exclude output --exclude .venv --exclude __pycache__ --exclude .git \
  --exclude .databricks --exclude dist

# 2) deploy the app
databricks apps deploy element-emc-reports \
  --source-code-path /Workspace/Users/<you>/apps/element-emc-reports \
  --mode SNAPSHOT
```

Get the URL / status any time with:

```bash
databricks apps get element-emc-reports -o json | jq '{url, app_status, compute_status}'
```

Run locally for development:

```bash
pip install -r requirements.txt
export EMC_UC_SCHEMA=<catalog>.emc_gold
export DATABRICKS_WAREHOUSE_ID=<warehouse-id>
uvicorn app:app --reload --port 8000
```

---

## 6. The wrangler (in the app **and** the notebook)

Both the **Wrangle** tab and `notebooks/emc_report_table_builder.py` produce the
same artifact — a row in `emc_gold.report_tables`:

| Column | Meaning |
|--------|---------|
| `table_key` | `"{project_id}__{discipline}"` (the upsert key). |
| `project_id`, `discipline`, `label` | Where the table belongs + its display name. |
| `headers` | JSON array of column headers (after rename / hide‑header). |
| `rows` | JSON array of string rows (after hide / reorder / sort). |
| `highlight` | Hex colour used for merged/repeated cells. |
| `source_sql` | The SELECT it came from (for audit / re‑run). |
| `updated_at` | Upsert timestamp. |

The transform itself lives in **one place** — `server/wrangle.apply_recipe()` —
and is applied identically whether you save from the UI (`/api/wrangle/save`) or
run the notebook. Operations, in order: **hide columns → reorder → rename →
sort → merge repeats + highlight**.

### API surface used by the Wrangle tab
| Endpoint | Body | Returns |
|----------|------|---------|
| `POST /api/wrangle/run` | `{sql, project_id}` | `{columns, rows, row_count}` |
| `POST /api/wrangle/preview` | `{columns, rows, recipe}` | shaped `{headers, rows, merges, highlight}` |
| `POST /api/wrangle/save` | `{project_id, discipline, label, columns, rows, recipe, source_sql}` | `{saved, headers, rows}` |
| `GET  /api/report-tables?project_id=…` | — | the saved tables the Report tab lists |

Once saved, the table appears in the Report tab's **Saved report tables** picker
(hover a table in the live document → *Saved report tables* → **Use saved**), and
is baked into the `.docx`/`.pdf` on **Issue the pack**.

---

## 7. Report templates (fully configurable)

Templates are plain JSON in `templates/`. A user can pick a shipped style,
tweak it live (colours, fonts, margins, banded rows, header fill, PASS/FAIL
colours, watermark, cover elements…), or **upload their own JSON**. Anything not
specified is deep‑merged over the default, so a template only has to carry what
it changes. Key sections of a template:

```jsonc
{
  "template_name": "…", "description": "…",
  "brand":       { "primary", "primary_dark", "table_header_fill", "pass", "fail", … },
  "fonts":       { "body_size", "h1_size", "table_header_size", "table_cell_size" },
  "table_style": { "banded_rows", "header_bold", "status_color_coding", "border_width_pt", "cell_padding_pt" },
  "page":        { "margin_top_mm", "margin_bottom_mm", "margin_left_mm", "margin_right_mm" },
  "cover":       { "show_hero_image", "show_logo", "show_partner_strip", "classification_banner" },
  "options":     { "include_plots", "watermark_draft", "watermark_text" },
  "sections":    { "cover": true, "radiated_emissions": true, … }
}
```

---

## 8. How to extend it

- **New test discipline** — add it to the DLT gold `measurements`/`section_meta`,
  then add a `(key, label)` to `DISCIPLINES` in `static/app.js` and to
  `SECTION_LABELS` in `app.py`.
- **New house style** — drop a JSON file into `templates/`; it shows up in the
  picker automatically.
- **New data source** — extend `server/gold.py` (keep `validate_select` as the
  read guard and `save_report_table` as the only write path).
- **Change the wrangling rules** — edit `server/wrangle.apply_recipe()`; both the
  UI and notebook inherit the change.

---

## 9. Quick smoke test

```bash
export DATABRICKS_WAREHOUSE_ID=<id>
python - <<'PY'
from fastapi.testclient import TestClient
import app
c = app.gold.SCHEMA
tc = TestClient(app.app)
sql = f"SELECT freq_mhz, reading, margin_db, status FROM {c}.measurements WHERE discipline='radiated_emissions' LIMIT 5"
run = tc.post('/api/wrangle/run', json={'sql': sql}).json()
prev = tc.post('/api/wrangle/preview', json={'columns': run['columns'], 'rows': run['rows'], 'recipe': {}}).json()
print('columns:', run['columns'])
print('headers:', prev['headers'])
PY
```
