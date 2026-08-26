#!/usr/bin/env python3
"""Create serverless_stable_1acr1x_catalog.emc_gold and load the Element EMC dataset."""
from __future__ import annotations

import json
import os
import sys

from databricks.sdk import WorkspaceClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data", "emc_report.json")
SCHEMA = os.environ.get("EMC_UC_SCHEMA", "serverless_stable_1acr1x_catalog.emc_gold")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "4484f27c707c5a31")
PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "fe-vm-serverless-stable-1acr1x")
APP_SP = "629623d5-2cf5-40f1-bd82-97fdfb7eea0c"

DISCIPLINES = (
    "radiated_emissions",
    "conducted_emissions",
    "radiated_immunity",
    "esd_immunity",
)


def sql_str(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def sql_num(value):
    if value is None or value == "":
        return "NULL"
    try:
        return str(float(str(value).replace("+/-", "").split(",")[0].strip()))
    except ValueError:
        return "NULL"


def parse_freq(cell: str):
    text = str(cell).replace(",", "").strip()
    if " - " in text:
        text = text.split(" - ", 1)[0]
    try:
        return float(text)
    except ValueError:
        return None


def parse_margin(row: list[str]):
    for cell in row:
        text = str(cell).strip()
        if text.startswith("-") or text.startswith("+"):
            try:
                return float(text)
            except ValueError:
                continue
    return None


def run(w: WorkspaceClient, statement: str) -> None:
    res = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        wait_timeout="50s",
    )
    state = getattr(getattr(res, "status", None), "state", None)
    state_name = getattr(state, "value", state)
    if str(state_name).endswith("FAILED") or str(state_name) == "FAILED":
        err = getattr(getattr(res, "status", None), "error", None)
        raise RuntimeError(f"SQL failed: {err or res}")


def main() -> None:
    w = WorkspaceClient(profile=PROFILE)
    catalog, schema = SCHEMA.split(".", 1)
    print(f"Seeding {SCHEMA} on warehouse {WAREHOUSE_ID}")

    with open(DATA) as fh:
        payload = json.load(fh)

    run(w, f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    run(w, f"DROP TABLE IF EXISTS {SCHEMA}.measurements")
    run(w, f"DROP TABLE IF EXISTS {SCHEMA}.section_meta")
    run(w, f"DROP TABLE IF EXISTS {SCHEMA}.projects")

    run(w, f"""
        CREATE TABLE {SCHEMA}.projects (
          project_id STRING,
          project_name STRING,
          document_number STRING,
          revision STRING,
          issue_date STRING,
          classification STRING,
          client STRING,
          test_lab STRING,
          accreditation STRING,
          standards STRING,
          eut_description STRING,
          eut_model STRING,
          eut_serial STRING,
          eut_supply STRING,
          eut_dimensions STRING,
          eut_modes STRING,
          eut_cables STRING,
          summary_json STRING,
          revision_history_json STRING,
          approvals_json STRING
        )
    """)
    run(w, f"""
        CREATE TABLE {SCHEMA}.section_meta (
          project_id STRING,
          discipline STRING,
          standard STRING,
          site STRING,
          detector STRING,
          field STRING,
          levels STRING,
          narrative STRING,
          plot STRING,
          plot_caption STRING,
          table_caption STRING,
          table_headers STRING
        )
    """)
    run(w, f"""
        CREATE TABLE {SCHEMA}.measurements (
          project_id STRING,
          discipline STRING,
          row_index INT,
          test_id STRING,
          freq_mhz DOUBLE,
          reading DOUBLE,
          limit_value DOUBLE,
          margin_db DOUBLE,
          detector STRING,
          polarisation STRING,
          conductor STRING,
          status STRING,
          cells STRING
        )
    """)

    project_values = []
    meta_values = []
    meas_values = []

    for project in payload["projects"]:
        eut = project["eut"]
        project_values.append(
            "(" + ", ".join([
                sql_str(project["project_id"]),
                sql_str(project["project_name"]),
                sql_str(project["document_number"]),
                sql_str(project["revision"]),
                sql_str(project["issue_date"]),
                sql_str(project["classification"]),
                sql_str(project["client"]),
                sql_str(project["test_lab"]),
                sql_str(project.get("accreditation", "")),
                sql_str(json.dumps(project["standards"])),
                sql_str(eut["description"]),
                sql_str(eut["model"]),
                sql_str(eut["serial"]),
                sql_str(eut["supply"]),
                sql_str(eut["dimensions"]),
                sql_str(eut["modes"]),
                sql_str(eut["cables"]),
                sql_str(json.dumps(project["summary_rows"])),
                sql_str(json.dumps(project["revision_history"])),
                sql_str(json.dumps(project["approvals"])),
            ]) + ")"
        )

        for disc in DISCIPLINES:
            block = project[disc]
            meta_values.append(
                "(" + ", ".join([
                    sql_str(project["project_id"]),
                    sql_str(disc),
                    sql_str(block.get("standard", "")),
                    sql_str(block.get("site", "")),
                    sql_str(block.get("detector", "")),
                    sql_str(block.get("field", "")),
                    sql_str(block.get("levels", "")),
                    sql_str(block.get("narrative", "")),
                    sql_str(block.get("plot", "")),
                    sql_str(block.get("plot_caption", "")),
                    sql_str(block.get("table_caption", "")),
                    sql_str(json.dumps(block.get("table_headers", []))),
                ]) + ")"
            )
            for idx, row in enumerate(block.get("table_rows", [])):
                test_id = row[0] if disc == "appendix" else None
                freq = parse_freq(row[0] if disc != "esd_immunity" else "")
                margin = parse_margin(row)
                status = row[-1] if row else None
                meas_values.append(
                    "(" + ", ".join([
                        sql_str(project["project_id"]),
                        sql_str(disc),
                        str(idx),
                        sql_str(test_id),
                        sql_num(freq),
                        sql_num(row[1] if len(row) > 1 and disc in ("radiated_emissions", "conducted_emissions") else None),
                        sql_num(row[2] if len(row) > 2 and disc == "radiated_emissions" else None),
                        sql_num(margin),
                        sql_str(row[4] if disc == "radiated_emissions" and len(row) > 4 else None),
                        sql_str(row[5] if disc == "radiated_emissions" and len(row) > 5 else None),
                        sql_str(row[5] if disc == "conducted_emissions" and len(row) > 5 else None),
                        sql_str(status),
                        sql_str(json.dumps(row)),
                    ]) + ")"
                )

        appendix = project["appendix"]
        meta_values.append(
            "(" + ", ".join([
                sql_str(project["project_id"]),
                sql_str("appendix"),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(""),
                sql_str(appendix.get("table_caption", "")),
                sql_str(json.dumps(appendix.get("table_headers", []))),
            ]) + ")"
        )
        for idx, row in enumerate(appendix.get("table_rows", [])):
            meas_values.append(
                "(" + ", ".join([
                    sql_str(project["project_id"]),
                    sql_str("appendix"),
                    str(idx),
                    sql_str(row[0] if row else None),
                    sql_num(parse_freq(row[1] if len(row) > 1 else "")),
                    sql_num(row[2] if len(row) > 2 else None),
                    sql_num(row[3] if len(row) > 3 else None),
                    sql_num(row[4] if len(row) > 4 else None),
                    sql_str(row[5] if len(row) > 5 else None),
                    "NULL",
                    "NULL",
                    sql_str(row[-1] if row else None),
                    sql_str(json.dumps(row)),
                ]) + ")"
            )

    run(w, f"INSERT INTO {SCHEMA}.projects VALUES {', '.join(project_values)}")
    run(w, f"INSERT INTO {SCHEMA}.section_meta VALUES {', '.join(meta_values)}")
    run(w, f"INSERT INTO {SCHEMA}.measurements VALUES {', '.join(meas_values)}")

    catalog_name = catalog
    grants = [
        f"GRANT USE CATALOG ON CATALOG {catalog_name} TO `{APP_SP}`",
        f"GRANT USE SCHEMA ON SCHEMA {SCHEMA} TO `{APP_SP}`",
        f"GRANT SELECT ON SCHEMA {SCHEMA} TO `{APP_SP}`",
    ]
    for grant in grants:
        try:
            run(w, grant)
            print("granted:", grant)
        except Exception as exc:  # noqa: BLE001
            print("grant skipped:", grant, exc)

    run(w, f"SELECT COUNT(*) AS n FROM {SCHEMA}.projects")
    print("Seed complete.")


if __name__ == "__main__":
    main()
