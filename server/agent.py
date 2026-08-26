"""Natural-language → SQL agent for EMC Gold selection."""
from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from databricks.sdk import WorkspaceClient

from . import gold

ENDPOINT = os.environ.get("SERVING_ENDPOINT") or os.environ.get(
    "SERVING_ENDPOINT_NAME", "databricks-claude-sonnet-4-5"
)

SYSTEM = """You rewrite Databricks SQL for an EMC lab report. Return ONLY JSON:
  sql: one SELECT or WITH statement
  discipline: radiated_emissions | conducted_emissions | radiated_immunity | esd_immunity | appendix
  explanation: one sentence of what changed

Preferred tables (fully qualify as catalog.schema.table):
  serverless_stable_1acr1x_catalog.emc_gold.measurements
    (project_id, discipline, row_index, test_id, freq_mhz, reading, limit_value, margin_db, detector, polarisation, conductor, status, cells)
  serverless_stable_1acr1x_catalog.emc_gold.projects
    (project_id, project_name, document_number, client, classification, eut_model, eut_serial)
  serverless_stable_1acr1x_catalog.emc_gold.section_meta
  serverless_stable_1acr1x_catalog.emc_pipeline.silver_measurements
  serverless_stable_1acr1x_catalog.emc_pipeline.gold_report_measurements
  serverless_stable_1acr1x_catalog.emc_pipeline.gold_worst_emissions

Rules:
- SELECT only. Prefer keeping a cells column when the query is still row-level measurements.
- If the user says "use this table, not that one", REPLACE the FROM table. Do not keep the excluded table.
- If they say JOIN, add an INNER JOIN on project_id (and discipline when both sides have it).
- Honour LIMIT, ORDER BY, GROUP BY / aggregations (count, avg(margin_db), min/max) exactly as asked.
- Start from current_sql when provided; only change what the user asked.
- Filter by current project_id unless they name another.
- margin_db: closer to 0 = worst case. Worst N = ORDER BY margin_db DESC LIMIT N.
- LIMIT at most 80.
"""


def _host_and_token() -> tuple[str, str]:
    if os.environ.get("DATABRICKS_APP_NAME"):
        w = WorkspaceClient()
    else:
        profile = os.environ.get("DATABRICKS_CONFIG_PROFILE") or os.environ.get(
            "DATABRICKS_PROFILE", "fe-vm-serverless-stable-1acr1x"
        )
        w = WorkspaceClient(profile=profile)
    host = w.config.host or os.environ.get("DATABRICKS_HOST", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    headers = w.config.authenticate() or {}
    token = ""
    if "Authorization" in headers:
        token = headers["Authorization"].replace("Bearer ", "")
    token = token or os.environ.get("DATABRICKS_TOKEN", "")
    if not token:
        raise RuntimeError("Could not obtain a Databricks token for the model")
    return host.rstrip("/"), token


def plan_sql(
    prompt: str,
    project_id: str,
    current_sql: str | None = None,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    join_tables: list[str] | None = None,
) -> dict[str, Any]:
    host, token = _host_and_token()
    parts = [f"Current project_id={project_id}."]
    if current_sql:
        parts.append(f"Current SQL:\n{current_sql}")
    if include_tables:
        parts.append("USE / REPLACE with these tables: " + ", ".join(include_tables))
    if exclude_tables:
        parts.append("Do NOT use these tables: " + ", ".join(exclude_tables))
    if join_tables:
        parts.append("JOIN these tables: " + ", ".join(join_tables))
    parts.append(f"Request: {prompt}")
    resp = requests.post(
        f"{host}/serving-endpoints/{ENDPOINT}/invocations",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": "\n".join(parts)},
            ],
            "max_tokens": 1200,
            "temperature": 0.1,
        },
        timeout=90,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Model {ENDPOINT} failed ({resp.status_code}): {resp.text[:400]}")
    payload = resp.json()
    text = ""
    if isinstance(payload, dict):
        choices = payload.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
        elif payload.get("output"):
            text = json.dumps(payload["output"])
    if not text:
        text = json.dumps(payload)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise RuntimeError(f"Agent did not return JSON: {text[:300]}")
    data = json.loads(match.group(0))
    if not data.get("sql"):
        raise RuntimeError("Agent did not propose SQL")
    data["sql"] = gold.validate_select(data["sql"])
    data["discipline"] = data.get("discipline") or "radiated_emissions"
    data["project_id"] = data.get("project_id") or project_id
    return data
