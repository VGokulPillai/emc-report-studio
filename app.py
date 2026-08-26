"""
Element EMC Report Studio — Databricks App.

Wraps the offline report generator behind a FastAPI UI so a lab engineer can
pick a project/scope, choose sections, and download a house-styled .docx / .pdf.
"""
from __future__ import annotations

import copy
import os
import re
import tempfile
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import generate as gen
import report_builder  # noqa: E402 — generate puts src/ on sys.path
from server import agent as emc_agent
from server import docmodel
from server import gold
from server import wrangle

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
ASSETS = os.path.join(HERE, "assets")
TEMPLATES = os.path.join(HERE, "templates")

SECTION_LABELS = {
    "cover": "Cover",
    "revision_history": "Revision history",
    "table_of_contents": "Contents",
    "executive_summary": "Executive summary",
    "eut_description": "Equipment under test",
    "test_summary": "Summary of results",
    "radiated_emissions": "Radiated emissions",
    "conducted_emissions": "Conducted emissions",
    "radiated_immunity": "Radiated immunity",
    "esd_immunity": "ESD immunity",
    "appendix_raw_data": "Appendix — raw data",
    "declaration": "Declaration of conformity",
}

JOBS: dict[str, dict[str, Any]] = {}
JOB_TTL_S = 60 * 60


class GenerateIn(BaseModel):
    project_id: str
    sections: dict[str, bool] | None = None
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    template: dict[str, Any] | None = None
    overrides: dict[str, Any] | None = None
    table_overrides: dict[str, list[list[str]]] | None = None
    header_overrides: dict[str, list[str]] | None = None


class SqlIn(BaseModel):
    sql: str
    project_id: str | None = None


class AgentIn(BaseModel):
    prompt: str
    project_id: str
    current_sql: str | None = None
    include_tables: list[str] | None = None
    exclude_tables: list[str] | None = None
    join_tables: list[str] | None = None


class PreviewIn(BaseModel):
    table: str
    limit: int = 40


class WrangleRunIn(BaseModel):
    sql: str
    project_id: str | None = None


class WrangleRecipe(BaseModel):
    hide_columns: list[str] = Field(default_factory=list)
    column_order: list[str] = Field(default_factory=list)
    renames: dict[str, str] = Field(default_factory=dict)
    sort_by: str | None = None
    sort_order: str = "asc"
    hide_headers: list[str] = Field(default_factory=list)
    merge_columns: list[str] = Field(default_factory=list)
    highlight: str = "#D4EDDA"


class WranglePreviewIn(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    recipe: WrangleRecipe = Field(default_factory=WrangleRecipe)


class WrangleSaveIn(BaseModel):
    project_id: str
    discipline: str
    label: str
    columns: list[str]
    rows: list[list[str]]
    recipe: WrangleRecipe = Field(default_factory=WrangleRecipe)
    source_sql: str = ""


_PROJECT_KEYS = (
    "project_name", "document_number", "revision", "issue_date",
    "classification", "client",
)
_EUT_KEYS = ("description", "model", "serial", "supply", "dimensions", "modes", "cables")


def _apply_overrides(project: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    if not overrides:
        return project
    project = copy.deepcopy(project)
    for key in _PROJECT_KEYS:
        if key in overrides and overrides[key] is not None:
            project[key] = str(overrides[key])
    eut = overrides.get("eut")
    if isinstance(eut, dict):
        for key in _EUT_KEYS:
            if key in eut and eut[key] is not None:
                project["eut"][key] = str(eut[key])
    return project


def _apply_tables(
    project: dict[str, Any],
    tables: dict[str, list[list[str]]] | None,
    headers: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    if not tables:
        return project
    project = copy.deepcopy(project)
    mapping = {
        "radiated_emissions": ("radiated_emissions",),
        "conducted_emissions": ("conducted_emissions",),
        "radiated_immunity": ("radiated_immunity",),
        "esd_immunity": ("esd_immunity",),
        "appendix": ("appendix",),
        "appendix_raw_data": ("appendix",),
        "test_summary": None,
    }
    headers = headers or {}
    for key, rows in tables.items():
        if key == "test_summary":
            project["summary_rows"] = rows
            if headers.get(key):
                project["summary_headers"] = headers[key]
            continue
        dest = mapping.get(key, (key,))
        if dest and dest[0] in project and isinstance(project[dest[0]], dict):
            block = project[dest[0]]
            block["table_rows"] = rows
            if headers.get(key):
                block["table_headers"] = headers[key]
    return project


def _json_projects() -> list[dict[str, Any]]:
    return gen.load_json(gen.DATA)["projects"]


def _load_projects() -> tuple[list[dict[str, Any]], str]:
    status = gold.available()
    if status.get("connected"):
        try:
            return gold.load_projects(), "unity_catalog"
        except Exception:
            pass
    return _json_projects(), "offline_json"


def _purge_jobs() -> None:
    now = time.time()
    stale = [jid for jid, job in JOBS.items() if now - job["created"] > JOB_TTL_S]
    for jid in stale:
        JOBS.pop(jid, None)


def _project_card(project: dict[str, Any]) -> dict[str, Any]:
    n_pass = sum(1 for row in project["summary_rows"] if str(row[-1]).upper() == "PASS")
    total = len(project["summary_rows"])
    return {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "document_number": project["document_number"],
        "revision": project["revision"],
        "issue_date": project["issue_date"],
        "classification": project["classification"],
        "client": project["client"],
        "test_lab": project["test_lab"],
        "accreditation": project.get("accreditation", ""),
        "standards": project["standards"],
        "eut": project["eut"],
        "pass_count": n_pass,
        "test_count": total,
        "overall": "PASS" if n_pass == total else "PARTIAL",
        "summary_rows": project["summary_rows"],
    }


def _load_catalog() -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    cfg = gen.load_json(gen.DEFAULT_TEMPLATE)
    projects, source = _load_projects()
    return cfg, projects, source


app = FastAPI(title="Element EMC Report Studio", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
def me(request: Request) -> dict[str, str]:
    return {
        "email": request.headers.get("x-forwarded-email")
        or request.headers.get("x-forwarded-user")
        or "",
        "name": request.headers.get("x-forwarded-preferred-username") or "",
    }


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    cfg, projects, source = _load_catalog()
    gold_status = gold.available()
    return {
        "template_name": cfg.get("template_name", "Default"),
        "template_version": cfg.get("template_version", ""),
        "brand": cfg.get("brand", {}),
        "source": source,
        "gold": gold_status,
        "sections": [
            {
                "key": key,
                "label": SECTION_LABELS.get(key, key.replace("_", " ").title()),
                "enabled": bool(enabled),
            }
            for key, enabled in cfg.get("sections", {}).items()
        ],
        "projects": [_project_card(p) for p in projects],
    }


@app.get("/api/report-tables")
def report_tables(project_id: str | None = None) -> dict[str, Any]:
    """Tables saved from the EMC Report Table Builder notebook, ready to drop into the PDF."""
    try:
        items = gold.list_report_tables(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tables": items}


@app.get("/api/templates")
def list_templates() -> dict[str, Any]:
    """Templates shipped with the app — a user can also upload their own JSON."""
    items = []
    for name in sorted(os.listdir(TEMPLATES)):
        if not name.endswith(".json"):
            continue
        try:
            cfg = gen.load_json(os.path.join(TEMPLATES, name))
        except Exception:  # noqa: BLE001 — skip a malformed file rather than 500
            continue
        items.append({
            "id": name[:-5],
            "name": cfg.get("template_name", name),
            "version": cfg.get("template_version", ""),
            "description": cfg.get("description", ""),
            "default": os.path.join(TEMPLATES, name) == gen.DEFAULT_TEMPLATE,
        })
    items.sort(key=lambda t: (not t["default"], t["name"].lower()))
    return {"templates": items}


@app.get("/api/templates/{template_id}")
def get_template(template_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", template_id):
        raise HTTPException(status_code=400, detail="Bad template id")
    path = os.path.join(TEMPLATES, f"{template_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"No template '{template_id}'")
    return gen.load_json(path)


@app.get("/api/gold/status")
def gold_status() -> dict[str, Any]:
    return gold.available()


@app.post("/api/gold/sql")
def run_sql(body: SqlIn) -> dict[str, Any]:
    try:
        sql = gold.validate_select(body.sql)
        rows = gold.query(sql)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    disciplines = sorted({str(r.get("discipline")) for r in rows if r.get("discipline")})
    return {
        "sql": sql,
        "row_count": len(rows),
        "rows": rows[:200],
        "table_rows": gold.rows_to_table(rows),
        "disciplines": disciplines,
        "discipline": disciplines[0] if len(disciplines) == 1 else None,
    }


@app.post("/api/wrangle/run")
def wrangle_run(body: WrangleRunIn) -> dict[str, Any]:
    """Run a SELECT and return raw columns + string rows for the wrangler grid."""
    try:
        sql = gold.validate_select(body.sql)
        rows = gold.query(sql)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    columns = list(rows[0].keys()) if rows else []
    columns = [c for c in columns if c != "cells"]
    data = [["" if r.get(c) is None else str(r.get(c)) for c in columns] for r in rows]
    disciplines = sorted({str(r.get("discipline")) for r in rows if r.get("discipline")})
    return {
        "sql": sql,
        "columns": columns,
        "rows": data,
        "row_count": len(data),
        "disciplines": disciplines,
        "discipline": disciplines[0] if len(disciplines) == 1 else None,
    }


@app.post("/api/wrangle/preview")
def wrangle_preview(body: WranglePreviewIn) -> dict[str, Any]:
    """Apply the wrangling recipe (no DB) — the authoritative transform."""
    try:
        return wrangle.apply_recipe(body.columns, body.rows, body.recipe.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/wrangle/save")
def wrangle_save(body: WrangleSaveIn) -> dict[str, Any]:
    """Wrangle then upsert into emc_gold.report_tables so the PDF can pick it up."""
    try:
        shaped = wrangle.apply_recipe(body.columns, body.rows, body.recipe.model_dump())
        saved = gold.save_report_table(
            project_id=body.project_id,
            discipline=body.discipline,
            label=body.label or wrangle.pretty_header(body.discipline),
            headers=shaped["headers"],
            rows=shaped["rows"],
            highlight=shaped["highlight"],
            source_sql=body.source_sql,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": saved, "headers": shaped["headers"], "rows": shaped["rows"]}


@app.get("/api/tables/search")
def search_tables(q: str = "emc") -> dict[str, Any]:
    try:
        rows = gold.search_tables(q)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tables = [
        {
            "full_name": f"{r['table_catalog']}.{r['table_schema']}.{r['table_name']}",
            "catalog": r["table_catalog"],
            "schema": r["table_schema"],
            "name": r["table_name"],
            "type": r.get("table_type"),
            "folder": f"{r['table_catalog']}/{r['table_schema']}",
        }
        for r in rows
    ]
    return {"query": q, "tables": tables}


@app.get("/api/tables/preview")
def preview_table(table: str, limit: int = 40) -> dict[str, Any]:
    try:
        rows = gold.preview_table(table, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    columns = list(rows[0].keys()) if rows else []
    shown = [c for c in columns if c != "cells"][:14] or ["*"]
    sql = f"SELECT {', '.join(shown)}\nFROM {table}\nLIMIT {max(1, min(limit, 80))}"
    return {"table": table, "columns": columns, "row_count": len(rows), "rows": rows, "sql": sql}


@app.get("/api/pipelines")
def list_pipelines() -> dict[str, Any]:
    try:
        w = gold.workspace_client()
        items = []
        for p in w.pipelines.list_pipelines():
            name = getattr(p, "name", "") or ""
            if "emc" in name.lower() or "element" in name.lower() or not name:
                items.append({
                    "pipeline_id": getattr(p, "pipeline_id", ""),
                    "name": name or "element-emc-dlt",
                    "state": str(getattr(getattr(p, "state", None), "value", getattr(p, "state", "")) or ""),
                })
        if not items:
            items = [{
                "pipeline_id": "53864b1e-49ac-4eb9-a48f-26ac48a4305f",
                "name": "element-emc-dlt",
                "state": "bronze / silver / gold in emc_pipeline",
            }]
        return {"pipelines": items}
    except Exception as exc:  # noqa: BLE001
        return {"pipelines": [], "error": str(exc)}


@app.post("/api/gold/agent")
def run_agent(body: AgentIn) -> dict[str, Any]:
    try:
        plan = emc_agent.plan_sql(
            body.prompt,
            body.project_id,
            current_sql=body.current_sql,
            include_tables=body.include_tables,
            exclude_tables=body.exclude_tables,
            join_tables=body.join_tables,
        )
        rows = gold.query(plan["sql"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sql": plan["sql"],
        "explanation": plan.get("explanation", ""),
        "discipline": plan.get("discipline"),
        "project_id": plan.get("project_id") or body.project_id,
        "row_count": len(rows),
        "rows": rows[:200],
        "table_rows": gold.rows_to_table(rows),
    }


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _prepare(body: GenerateIn) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg, projects, _source = _load_catalog()
    # a user-supplied template only has to carry what it wants to change
    cfg = _deep_merge(cfg, body.template) if body.template else copy.deepcopy(cfg)

    project = next((p for p in projects if p["project_id"] == body.project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project '{body.project_id}'")
    project = _apply_overrides(project, body.overrides)
    project = _apply_tables(project, body.table_overrides, body.header_overrides)

    if body.sections:
        cfg["sections"] = {
            key: bool(body.sections.get(key, False)) for key in cfg.get("sections", {})
        }
    return project, cfg


@app.post("/api/document")
def document(body: GenerateIn) -> dict[str, Any]:
    """The report as hoverable blocks — same content the PDF writer receives."""
    project, cfg = _prepare(body)
    try:
        gen.ensure_plots(project, cfg)
        collector = docmodel.DocumentCollector(project, cfg, ASSETS)
        report_builder.build_report(collector, project, cfg, gen.PLOTS, ASSETS)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "document_number": project["document_number"],
        "revision": project["revision"],
        "blocks": collector.blocks,
    }


@app.post("/api/generate")
def generate_report(body: GenerateIn) -> dict[str, Any]:
    _purge_jobs()
    project, cfg = _prepare(body)

    formats = [fmt for fmt in body.formats if fmt in ("docx", "pdf")]
    if not formats:
        raise HTTPException(status_code=400, detail="Choose at least one format: docx or pdf")

    job_id = uuid.uuid4().hex[:12]
    out_dir = tempfile.mkdtemp(prefix=f"emc_{job_id}_")
    try:
        written = gen.generate_one(project, cfg, formats, output_dir=out_dir)
    except Exception as exc:  # noqa: BLE001 — surface generator errors to the UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    files = []
    for path, size, pages in written:
        files.append({
            "name": os.path.basename(path),
            "size": size,
            "pages": pages,
            "format": "pdf" if path.endswith(".pdf") else "docx",
        })

    JOBS[job_id] = {
        "created": time.time(),
        "dir": out_dir,
        "files": {f["name"]: os.path.join(out_dir, f["name"]) for f in files},
        "project_id": project["project_id"],
        "project_name": project["project_name"],
    }
    return {
        "job_id": job_id,
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "document_number": project["document_number"],
        "files": files,
    }


@app.get("/api/jobs/{job_id}/files/{filename}")
def download(job_id: str, filename: str, inline: bool = False):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report expired or not found. Generate again.")
    path = job["files"].get(filename)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    media = (
        "application/pdf"
        if filename.endswith(".pdf")
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path,
        media_type=media,
        filename=filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "no-store"},
    )


if os.path.isdir(ASSETS):
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _static_version() -> str:
    """Newest static-file mtime, so a redeploy always busts the browser cache."""
    newest = 0.0
    for name in ("index.html", "app.js", "styles.css"):
        path = os.path.join(STATIC, name)
        if os.path.exists(path):
            newest = max(newest, os.path.getmtime(path))
    return str(int(newest))


@app.get("/")
def index():
    with open(os.path.join(STATIC, "index.html")) as fh:
        html = fh.read().replace("__V__", _static_version())
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
