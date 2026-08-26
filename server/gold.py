"""Unity Catalog Gold access for EMC report data."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from databricks.sdk import WorkspaceClient

SCHEMA = os.environ.get("EMC_UC_SCHEMA", "serverless_stable_1acr1x_catalog.emc_gold")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
ALLOWED_TABLES = {
    f"{SCHEMA}.projects",
    f"{SCHEMA}.section_meta",
    f"{SCHEMA}.measurements",
    "projects",
    "section_meta",
    "measurements",
}
DISC_TO_KEY = {
    "radiated_emissions": "radiated_emissions",
    "conducted_emissions": "conducted_emissions",
    "radiated_immunity": "radiated_immunity",
    "esd_immunity": "esd_immunity",
    "appendix": "appendix",
}


def warehouse_id() -> str:
    return os.environ.get("DATABRICKS_WAREHOUSE_ID") or WAREHOUSE_ID


def workspace_client() -> WorkspaceClient:
    if os.environ.get("DATABRICKS_APP_NAME"):
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE") or os.environ.get("DATABRICKS_PROFILE", "fe-vm-serverless-stable-1acr1x")
    return WorkspaceClient(profile=profile)


def _rows(result) -> list[dict[str, Any]]:
    manifest = getattr(result, "manifest", None)
    schema = getattr(manifest, "schema", None) if manifest else None
    columns = [c.name for c in getattr(schema, "columns", [])] if schema else []
    data = getattr(getattr(result, "result", None), "data_array", None) or []
    out = []
    for row in data:
        out.append({columns[i]: row[i] if i < len(row) else None for i in range(len(columns))})
    return out


def query(sql: str, timeout: str = "50s") -> list[dict[str, Any]]:
    wid = warehouse_id()
    if not wid:
        raise RuntimeError("No SQL warehouse configured")
    result = workspace_client().statement_execution.execute_statement(
        warehouse_id=wid,
        statement=sql,
        wait_timeout=timeout,
    )
    state = getattr(getattr(result, "status", None), "state", None)
    state_name = str(getattr(state, "value", state) or "")
    if "FAILED" in state_name or "CANCELED" in state_name:
        err = getattr(getattr(result, "status", None), "error", None)
        raise RuntimeError(getattr(err, "message", None) or str(err or result))
    return _rows(result)


def available() -> dict[str, Any]:
    if not warehouse_id():
        return {"connected": False, "reason": "No warehouse", "schema": SCHEMA}
    try:
        rows = query(f"SELECT COUNT(*) AS n FROM {SCHEMA}.measurements")
        return {
            "connected": True,
            "schema": SCHEMA,
            "measurement_count": int(rows[0]["n"]) if rows else 0,
            "tables": ["projects", "section_meta", "measurements"],
        }
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "reason": str(exc), "schema": SCHEMA}


def _parse_json(value, default):
    if not value:
        return default
    if isinstance(value, (list, dict)):
        return value
    return json.loads(value)


def load_projects() -> list[dict[str, Any]]:
    rows = query(f"SELECT * FROM {SCHEMA}.projects ORDER BY project_id")
    return [assemble_project(row["project_id"], header=row) for row in rows]


def assemble_project(project_id: str, header: dict[str, Any] | None = None) -> dict[str, Any]:
    if header is None:
        found = query(f"SELECT * FROM {SCHEMA}.projects WHERE project_id = {json.dumps(project_id)}")
        if not found:
            raise KeyError(project_id)
        header = found[0]
    project = {
        "project_id": header["project_id"],
        "project_name": header["project_name"],
        "document_number": header["document_number"],
        "revision": header["revision"],
        "issue_date": header["issue_date"],
        "classification": header["classification"],
        "client": header["client"],
        "test_lab": header["test_lab"],
        "accreditation": header.get("accreditation") or "",
        "standards": _parse_json(header.get("standards"), []),
        "eut": {
            "description": header.get("eut_description") or "",
            "model": header.get("eut_model") or "",
            "serial": header.get("eut_serial") or "",
            "supply": header.get("eut_supply") or "",
            "dimensions": header.get("eut_dimensions") or "",
            "modes": header.get("eut_modes") or "",
            "cables": header.get("eut_cables") or "",
        },
        "summary_rows": _parse_json(header.get("summary_json"), []),
        "revision_history": _parse_json(header.get("revision_history_json"), []),
        "approvals": _parse_json(header.get("approvals_json"), []),
    }
    metas = query(
        f"SELECT * FROM {SCHEMA}.section_meta WHERE project_id = {json.dumps(project_id)}"
    )
    meas = query(
        f"""
        SELECT * FROM {SCHEMA}.measurements
        WHERE project_id = {json.dumps(project_id)}
        ORDER BY discipline, row_index
        """
    )
    by_disc: dict[str, list[dict[str, Any]]] = {}
    for row in meas:
        by_disc.setdefault(row["discipline"], []).append(row)
    for meta in metas:
        disc = meta["discipline"]
        block = {
            "standard": meta.get("standard") or "",
            "site": meta.get("site") or "",
            "detector": meta.get("detector") or "",
            "field": meta.get("field") or "",
            "levels": meta.get("levels") or "",
            "narrative": meta.get("narrative") or "",
            "plot": meta.get("plot") or "",
            "plot_caption": meta.get("plot_caption") or "",
            "table_caption": meta.get("table_caption") or "",
            "table_headers": _parse_json(meta.get("table_headers"), []),
            "table_rows": [
                _parse_json(item.get("cells"), []) for item in by_disc.get(disc, [])
            ],
        }
        if disc == "appendix":
            project["appendix"] = block
        else:
            project[disc] = block
    return project


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|grant|revoke|truncate|copy|put|remove)\b",
    re.I,
)


_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
_ALLOWED_SCHEMAS = {
    "emc_gold", "emc_pipeline", "elements_dev", "spec_docs",
    "sar_gold", "sar_silver", "warwick_quoting", "information_schema",
}


def search_tables(term: str = "emc") -> list[dict[str, Any]]:
    needle = (term or "emc").replace("'", "").replace("%", "").strip().lower() or "emc"
    return query(
        f"""
        SELECT table_catalog, table_schema, table_name, table_type
        FROM system.information_schema.tables
        WHERE table_schema NOT IN ('information_schema')
          AND table_name NOT LIKE '\\\\_\\\\_%' ESCAPE '\\\\'
          AND table_name NOT LIKE 'event_log_%'
          AND (
            lower(concat_ws('.', table_catalog, table_schema, table_name)) LIKE '%{needle}%'
            OR lower(table_schema) IN ('emc_gold', 'emc_pipeline', 'elements_dev', 'spec_docs', 'sar_gold', 'warwick_quoting')
          )
        ORDER BY
          CASE WHEN table_schema LIKE 'emc%' THEN 0
               WHEN table_schema IN ('elements_dev', 'spec_docs', 'sar_gold') THEN 1
               ELSE 2 END,
          table_schema, table_name
        LIMIT 80
        """
    )


def preview_table(full_name: str, limit: int = 40) -> list[dict[str, Any]]:
    parts = [p.strip("`") for p in full_name.split(".")]
    if len(parts) != 3 or not all(_IDENT.match(p) for p in parts):
        raise ValueError("Use catalog.schema.table")
    n = max(1, min(int(limit), 80))
    return query(f"SELECT * FROM {parts[0]}.{parts[1]}.{parts[2]} LIMIT {n}")


def validate_select(sql: str) -> str:
    text = sql.strip().rstrip(";")
    if ";" in text:
        raise ValueError("One statement only")
    if _FORBIDDEN.search(text):
        raise ValueError("Only SELECT / WITH queries are allowed")
    if not re.match(r"^(select|with)\b", text, re.I):
        raise ValueError("Query must start with SELECT or WITH")
    lowered = text.lower()
    allowed = SCHEMA.split(".", 1)[0].lower()
    if allowed not in lowered and not any(s in lowered for s in _ALLOWED_SCHEMAS) and "measurements" not in lowered:
        raise ValueError(f"Query must use {SCHEMA} or other EMC lab schemas")
    if "limit" not in lowered:
        text += " LIMIT 200"
    return text


def list_report_tables(project_id: str | None = None) -> list[dict[str, Any]]:
    """Tables saved by the EMC Report Table Builder notebook into emc_gold.report_tables.

    Returns [] if the table has not been created yet, so the app degrades gracefully
    before anyone has run the notebook.
    """
    where = ""
    if project_id:
        where = f"WHERE project_id = {json.dumps(project_id)}"
    try:
        rows = query(
            f"""
            SELECT table_key, project_id, discipline, label, headers, rows,
                   highlight, source_sql, updated_at
            FROM {SCHEMA}.report_tables
            {where}
            ORDER BY updated_at DESC
            """
        )
    except Exception:  # noqa: BLE001 — table absent / no grant yet
        return []
    out = []
    for row in rows:
        out.append({
            "table_key": row.get("table_key"),
            "project_id": row.get("project_id"),
            "discipline": row.get("discipline"),
            "label": row.get("label") or row.get("table_key"),
            "headers": _parse_json(row.get("headers"), []),
            "rows": _parse_json(row.get("rows"), []),
            "highlight": row.get("highlight") or "",
            "source_sql": row.get("source_sql") or "",
            "updated_at": str(row.get("updated_at") or ""),
        })
    return out


def _sql_str(value: Any) -> str:
    """Quote a value as a SQL string literal (single-quote escaped)."""
    return "'" + str("" if value is None else value).replace("'", "''") + "'"


def save_report_table(
    *,
    project_id: str,
    discipline: str,
    label: str,
    headers: list[str],
    rows: list[list[str]],
    highlight: str = "",
    source_sql: str = "",
) -> dict[str, Any]:
    """Upsert a wrangled table into ``{SCHEMA}.report_tables``.

    This is the one write path used by the in-app wrangler; it mirrors the MERGE
    the notebook performs so both routes land the same shape of data.
    """
    if not warehouse_id():
        raise RuntimeError("No SQL warehouse configured")
    if not project_id or not discipline:
        raise ValueError("project_id and discipline are required")
    table_key = f"{project_id}__{discipline}"
    headers_json = json.dumps(headers or [])
    rows_json = json.dumps(rows or [])

    query(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.report_tables (
          table_key STRING, project_id STRING, discipline STRING, label STRING,
          headers STRING, rows STRING, highlight STRING, source_sql STRING,
          updated_at TIMESTAMP
        ) USING DELTA
        """
    )
    query(
        f"""
        MERGE INTO {SCHEMA}.report_tables t
        USING (SELECT
          {_sql_str(table_key)} AS table_key,
          {_sql_str(project_id)} AS project_id,
          {_sql_str(discipline)} AS discipline,
          {_sql_str(label)} AS label,
          {_sql_str(headers_json)} AS headers,
          {_sql_str(rows_json)} AS rows,
          {_sql_str(highlight)} AS highlight,
          {_sql_str(source_sql)} AS source_sql,
          current_timestamp() AS updated_at) s
        ON t.table_key = s.table_key
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    return {
        "table_key": table_key,
        "project_id": project_id,
        "discipline": discipline,
        "label": label,
        "row_count": len(rows or []),
    }


def rows_to_table(rows: list[dict[str, Any]]) -> list[list[str]]:
    table = []
    for row in rows:
        if row.get("cells"):
            table.append([str(c) for c in _parse_json(row["cells"], [])])
        else:
            skip = {"project_id", "discipline", "row_index", "cells"}
            table.append(["" if row[k] is None else str(row[k]) for k in row if k not in skip])
    return table
