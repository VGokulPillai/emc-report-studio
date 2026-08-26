# Databricks notebook source
# MAGIC %md
# MAGIC # EMC Report Table Builder
# MAGIC
# MAGIC Built from the client's **Interactive SQL Query Executor** notebook and wired into the
# MAGIC Element EMC Report Studio.
# MAGIC
# MAGIC **What it does**
# MAGIC 1. Run any SQL against the EMC Gold data (Unity Catalog).
# MAGIC 2. *Wrangle* the result — rename / reorder / hide columns, sort, merge repeated cells, highlight.
# MAGIC 3. **Save the wrangled table into Unity Catalog** (`emc_gold.report_tables`) so the
# MAGIC    Report Studio app can drop it straight into the PDF.
# MAGIC 4. (Optional) also export a styled PNG + HTML to a Volume, exactly like the original notebook.
# MAGIC
# MAGIC The app reads `report_tables` — anything you save here shows up under
# MAGIC **Edit table → Saved report tables** in the document, and flows into the issued `.pdf` / `.docx`.

# COMMAND ----------

# DBTITLE 1,Parameters
# --- Where the EMC data lives + where saved report tables go ---
dbutils.widgets.text("catalog", "serverless_stable_1acr1x_catalog", "Catalog")
dbutils.widgets.text("gold_schema", "emc_gold", "Gold schema")
dbutils.widgets.text("volume_path", "/Volumes/serverless_stable_1acr1x_catalog/emc_gold/reporting", "Volume path (for image export)")

# --- What this saved table is for (the app keys on these) ---
dbutils.widgets.text("project_id", "PRJ-XR7-2026", "Project ID")
dbutils.widgets.dropdown(
    "discipline",
    "radiated_emissions",
    ["radiated_emissions", "conducted_emissions", "radiated_immunity", "esd_immunity", "appendix", "test_summary"],
    "Report section",
)
dbutils.widgets.text("table_label", "Worst-case radiated emissions", "Table label (shown in the app)")

catalog = dbutils.widgets.get("catalog").strip()
gold_schema = dbutils.widgets.get("gold_schema").strip()
GOLD = f"{catalog}.{gold_schema}"
print(f"Reading from   {GOLD}")
print(f"Saving into    {GOLD}.report_tables")

# COMMAND ----------

# DBTITLE 1,1 · Run your SQL
# Default query pulls the worst-case radiated emissions for the project.
_default_sql = f"""
SELECT freq_mhz        AS `Frequency (MHz)`,
       reading         AS `Reading (dBµV/m)`,
       limit_value     AS `Limit (dBµV/m)`,
       margin_db       AS `Margin (dB)`,
       detector        AS `Detector`,
       polarisation    AS `Polarisation`,
       status          AS `Status`
FROM {GOLD}.measurements
WHERE project_id = '{dbutils.widgets.get("project_id")}'
  AND discipline = '{dbutils.widgets.get("discipline")}'
ORDER BY margin_db DESC
LIMIT 8
""".strip()

dbutils.widgets.text("sql_query", _default_sql, "Enter SQL Query")

query = dbutils.widgets.get("sql_query")
if query.strip():
    df = spark.sql(query)
    display(df)
else:
    print("No query provided. Enter a SQL query in the widget above.")

# COMMAND ----------

# DBTITLE 1,2 · Table customization options
import pandas as pd  # noqa: F401

dbutils.widgets.text("rename_columns", "", "Rename Columns (old:new, ...)")
dbutils.widgets.text("sort_by", "", "Sort By Column")
dbutils.widgets.dropdown("sort_order", "desc", ["asc", "desc"], "Sort Order")
dbutils.widgets.text("column_order", "", "Column Order (col1, col2, ...)")
dbutils.widgets.text("hide_columns", "", "Hide Columns (col1, col2, ...)")
dbutils.widgets.text("hide_headers", "", "Hide Headers (col1, col2, ...)")
dbutils.widgets.text("merge_columns", "", "Merge Repeated Values (col1, col2, ...)")
dbutils.widgets.text("highlight_color", "#D4EDDA", "Highlight Color (hex)")

print("Available columns from query result:")
print(list(df.columns))
print("\nConfigure the widgets above and run the next cell to apply.")

# COMMAND ----------

# DBTITLE 1,3 · Apply customizations and preview
from IPython.display import display as ipy_display, HTML

rename_raw = dbutils.widgets.get("rename_columns").strip()
sort_col = dbutils.widgets.get("sort_by").strip()
sort_order = dbutils.widgets.get("sort_order")
col_order_raw = dbutils.widgets.get("column_order").strip()
hide_cols_raw = dbutils.widgets.get("hide_columns").strip()
hide_headers_raw = dbutils.widgets.get("hide_headers").strip()
merge_cols_raw = dbutils.widgets.get("merge_columns").strip()
highlight_color = dbutils.widgets.get("highlight_color").strip() or "#D4EDDA"

pdf = df.toPandas()

# 1. Hide columns (original names)
if hide_cols_raw:
    hide_cols = [c.strip() for c in hide_cols_raw.split(",") if c.strip() in pdf.columns]
    pdf = pdf.drop(columns=hide_cols)

# 2. Reorder columns (original names)
if col_order_raw:
    new_order = [c.strip() for c in col_order_raw.split(",") if c.strip() in pdf.columns]
    remaining = [c for c in pdf.columns if c not in new_order]
    pdf = pdf[new_order + remaining]

# 3. Rename columns (after reorder)
if rename_raw:
    rename_map = {}
    for pair in rename_raw.split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2:
            rename_map[parts[0].strip()] = parts[1].strip()
    pdf = pdf.rename(columns=rename_map)

# 4. Sort
if sort_col and sort_col in pdf.columns:
    pdf = pdf.sort_values(by=sort_col, ascending=(sort_order == "asc")).reset_index(drop=True)

merge_cols = [c.strip() for c in merge_cols_raw.split(",") if c.strip() in pdf.columns] if merge_cols_raw else []
hide_header_cols = [c.strip() for c in hide_headers_raw.split(",") if c.strip() in pdf.columns] if hide_headers_raw else []


def style_merged_table(pdf, merge_cols, hide_header_cols, color):
    """Render an HTML table with merged (row-spanned) cells for repeated consecutive values."""
    if not merge_cols and not hide_header_cols:
        return pdf.style.set_table_styles([
            {"selector": "th", "props": [("background-color", "#0A2540"), ("color", "white"), ("padding", "8px")]},
            {"selector": "td", "props": [("padding", "6px"), ("border", "1px solid #dee2e6")]},
        ])

    html = '<table style="border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 13px;">'
    html += "<thead><tr>"
    for col in pdf.columns:
        if col in hide_header_cols:
            html += '<th style="background: transparent; border: none; padding: 8px;"></th>'
        else:
            html += f'<th style="background-color: #0A2540; color: white; padding: 8px; border: 1px solid #dee2e6;">{col}</th>'
    html += "</tr></thead><tbody>"

    n = len(pdf)
    skip = {col: [False] * n for col in merge_cols}
    spans = {col: [1] * n for col in merge_cols}
    for col in merge_cols:
        i = 0
        while i < n:
            j = i + 1
            while j < n and pdf.iloc[j][col] == pdf.iloc[i][col]:
                skip[col][j] = True
                j += 1
            spans[col][i] = j - i
            i = j

    for i in range(n):
        html += "<tr>"
        for col in pdf.columns:
            if col in merge_cols:
                if skip[col][i]:
                    continue
                span = spans[col][i]
                bg = f" background-color: {color};" if span > 1 else ""
                html += f'<td rowspan="{span}" style="padding: 6px; border: 1px solid #dee2e6; vertical-align: middle;{bg}">{pdf.iloc[i][col]}</td>'
            else:
                html += f'<td style="padding: 6px; border: 1px solid #dee2e6;">{pdf.iloc[i][col]}</td>'
        html += "</tr>"
    html += "</tbody></table>"
    return HTML(html)


result = style_merged_table(pdf, merge_cols, hide_header_cols, highlight_color)
table_html = result.data if isinstance(result, HTML) else result.to_html()
ipy_display(result)

# COMMAND ----------

# DBTITLE 1,4 · Save the wrangled table into Unity Catalog  →  feeds the PDF
import json
from datetime import datetime, timezone

project_id = dbutils.widgets.get("project_id").strip()
discipline = dbutils.widgets.get("discipline").strip()
table_label = dbutils.widgets.get("table_label").strip() or discipline
# a stable key the app can look up: <project>__<discipline>
table_key = f"{project_id}__{discipline}"

headers = [str(c) for c in pdf.columns]
rows = [[("" if v is None else str(v)) for v in row] for row in pdf.itertuples(index=False, name=None)]

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {GOLD}.report_tables (
        table_key     STRING,
        project_id    STRING,
        discipline    STRING,
        label         STRING,
        headers       STRING,   -- JSON array of column names
        rows          STRING,   -- JSON array of row arrays
        highlight     STRING,
        source_sql    STRING,
        updated_at    TIMESTAMP
    ) USING DELTA
""")

payload = {
    "table_key": table_key,
    "project_id": project_id,
    "discipline": discipline,
    "label": table_label,
    "headers": json.dumps(headers),
    "rows": json.dumps(rows),
    "highlight": highlight_color,
    "source_sql": query,
    "updated_at": datetime.now(timezone.utc),
}
save_df = spark.createDataFrame([payload])

# upsert: one saved table per (project, discipline)
save_df.createOrReplaceTempView("_incoming_report_table")
spark.sql(f"""
    MERGE INTO {GOLD}.report_tables AS t
    USING _incoming_report_table AS s
    ON t.table_key = s.table_key
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

print(f"Saved '{table_label}'  ({len(rows)} rows) as key '{table_key}'")
print(f"→ In the app: open the report, hover the {discipline} table, 'Edit table' → 'Saved report tables'.")
display(spark.sql(f"SELECT table_key, label, discipline, updated_at FROM {GOLD}.report_tables ORDER BY updated_at DESC"))

# COMMAND ----------

# DBTITLE 1,5 · (Optional) Export a styled PNG + HTML to a Volume
# Same capability as the original client notebook — useful for emailing a snapshot.
import matplotlib.pyplot as plt

export_image = True  # set False to skip

if export_image:
    volume_path = dbutils.widgets.get("volume_path").strip().rstrip("/")
    try:
        dbutils.fs.mkdirs(volume_path)
    except Exception as exc:  # noqa: BLE001
        print(f"(Could not create volume path {volume_path}: {exc})")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"{volume_path}/{table_key}_{timestamp}.png"
    html_path = f"{volume_path}/{table_key}_{timestamp}.html"

    display_pdf = pdf.copy()
    merge_mask = {}
    for col in merge_cols:
        if col in display_pdf.columns:
            merge_mask[col] = [False] * len(display_pdf)
            for i in range(1, len(display_pdf)):
                if display_pdf.iloc[i][col] == display_pdf.iloc[i - 1][col]:
                    display_pdf.at[display_pdf.index[i], col] = ""
                    merge_mask[col][i] = True

    col_labels = ["" if c in hide_header_cols else c for c in display_pdf.columns]
    n_rows, n_cols = display_pdf.shape
    fig, ax = plt.subplots(figsize=(max(14, n_cols * 2.8), max(4, (n_rows + 1) * 0.45)))
    ax.axis("off")
    table = ax.table(cellText=display_pdf.astype(str).values, colLabels=col_labels, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)
    for j in range(n_cols):
        cell = table[0, j]
        if display_pdf.columns[j] in hide_header_cols:
            cell.set_facecolor("white"); cell.set_edgecolor("white"); cell.set_text_props(color="white")
        else:
            cell.set_facecolor("#0A2540"); cell.set_text_props(color="white", weight="bold"); cell.set_edgecolor("#dee2e6")
    for i in range(1, n_rows + 1):
        for j in range(n_cols):
            cell = table[i, j]; cell.set_edgecolor("#dee2e6")
            col_name = display_pdf.columns[j]
            merged_here = col_name in merge_mask and merge_mask[col_name][i - 1]
            next_merged = col_name in merge_mask and i < n_rows and merge_mask[col_name][i]
            cell.set_facecolor(highlight_color if (merged_here or next_merged) else "white")
    table.auto_set_column_width(list(range(n_cols)))
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.05)
    plt.close()

    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(f'<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
                 f'<body style="margin:0;padding:20px;font-family:sans-serif;">{table_html}</body></html>')

    print(f"Image saved to: {output_path}")
    print(f"HTML saved to:  {html_path}")
    from IPython.display import Image as IPyImage
    ipy_display(IPyImage(filename=output_path))
