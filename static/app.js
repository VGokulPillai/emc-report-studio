const state = {
  catalog: null,
  template: null,
  templateId: "",
  projectId: null,
  sections: {},
  formats: new Set(["docx", "pdf"]),
  previewUrl: null,
  lastJob: null,
  stale: true,
  tableOverrides: {},
  headerOverrides: {},
  sectionSql: {},
  tables: [],
  savedTables: [],
  editing: null,
  view: "doc",
  wrangle: null,
};

const DISCIPLINES = [
  ["radiated_emissions", "Radiated emissions"],
  ["conducted_emissions", "Conducted emissions"],
  ["radiated_immunity", "Radiated immunity"],
  ["esd_immunity", "ESD immunity"],
  ["appendix", "Appendix — raw data"],
];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const form = () => $("#editor");

const SECTION_LABELS = {
  test_summary: "Summary of results",
  radiated_emissions: "Radiated emissions",
  conducted_emissions: "Conducted emissions",
  radiated_immunity: "Radiated immunity",
  esd_immunity: "ESD immunity",
  appendix: "Appendix — raw data",
};

const UNITS = { mhz: "MHz", db: "dB", dbuv: "dBµV", kv: "kV", vm: "V/m", eut: "EUT", id: "ID" };

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function prettyHeader(name) {
  return String(name)
    .split("_")
    .map((part) => UNITS[part.toLowerCase()] || part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function currentProject() {
  return state.catalog?.projects.find((p) => p.project_id === state.projectId) || null;
}

function markStale() {
  state.stale = true;
  $("#stale").hidden = !state.lastJob;
}

function showWorkspace(name) {
  $$(".ws-tab").forEach((t) => t.classList.toggle("active", t.dataset.ws === name));
  ["data", "wrangle", "report"].forEach((id) => {
    const pane = $(`#ws-${id}`);
    if (pane) pane.hidden = id !== name;
  });
  if (name !== "report") closeEditor();
  if (name === "wrangle" && !$("#wr-sql").value.trim()) refreshWrangleSql();
}

function showView(name) {
  state.view = name;
  $("#view-doc").classList.toggle("active", name === "doc");
  $("#view-pdf").classList.toggle("active", name === "pdf");
  $("#doc-view").hidden = name !== "doc";
  $("#pdf-view").hidden = name !== "pdf";
  $("#doc-title").textContent = name === "doc" ? "Document" : "Issued PDF";
  if (name === "pdf") {
    closeEditor();
    if (!state.lastJob || state.stale) generate();
  }
}

async function loadMe() {
  try {
    const me = await (await fetch("/api/me")).json();
    const label = me.email || me.name;
    if (label) $("#user").textContent = label;
  } catch {
    $("#user").textContent = "Workspace user";
  }
}

function renderProjects() {
  for (const host of $$(".project-list")) {
    host.innerHTML = "";
    for (const project of state.catalog.projects) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `project-card${project.project_id === state.projectId ? " active" : ""}`;
      btn.innerHTML = `
        <div class="card-top">
          <div>
            <h3>${project.project_name}</h3>
            <p>${project.document_number} · rev ${project.revision}</p>
          </div>
          <span class="badge">${project.overall} ${project.pass_count}/${project.test_count}</span>
        </div>
        <div class="meta-row">
          <span class="chip">${project.client}</span>
          <span class="chip">${project.classification}</span>
        </div>`;
      btn.addEventListener("click", () => selectProject(project.project_id));
      host.appendChild(btn);
    }
  }
}

function fillEditor(project) {
  const el = form();
  el.project_name.value = project.project_name;
  el.document_number.value = project.document_number;
  el.revision.value = project.revision;
  el.issue_date.value = project.issue_date;
  el.classification.value = project.classification;
  el.client.value = project.client;
  el.eut_model.value = project.eut.model;
  el.eut_serial.value = project.eut.serial;
  el.eut_description.value = project.eut.description;
}

function readOverrides() {
  const el = form();
  return {
    project_name: el.project_name.value.trim(),
    document_number: el.document_number.value.trim(),
    revision: el.revision.value.trim(),
    issue_date: el.issue_date.value.trim(),
    classification: el.classification.value.trim(),
    client: el.client.value.trim(),
    eut: {
      model: el.eut_model.value.trim(),
      serial: el.eut_serial.value.trim(),
      description: el.eut_description.value.trim(),
    },
  };
}

function reportBody() {
  return {
    project_id: state.projectId,
    template: state.template,
    sections: state.sections,
    formats: Array.from(new Set([...state.formats, "pdf"])),
    overrides: readOverrides(),
    table_overrides: state.tableOverrides,
    header_overrides: state.headerOverrides,
  };
}

function selectProject(id) {
  if (id === state.projectId) return;
  state.projectId = id;
  state.tableOverrides = {};
  state.headerOverrides = {};
  state.sectionSql = {};
  closeEditor();
  renderProjects();
  const project = currentProject();
  if (project) fillEditor(project);
  markStale();
  loadDocument();
  loadSavedTables();
  refreshWrangleSql();
}

function renderSections() {
  const host = $("#sections");
  host.innerHTML = "";
  for (const section of state.catalog.sections) {
    const label = document.createElement("label");
    label.className = "section-item";
    label.innerHTML = `<input type="checkbox" ${state.sections[section.key] ? "checked" : ""} /><span>${section.label}</span>`;
    label.querySelector("input").addEventListener("change", (ev) => {
      state.sections[section.key] = ev.target.checked;
      markStale();
      loadDocument();
    });
    host.appendChild(label);
  }
}

function setAllSections(on) {
  for (const key of Object.keys(state.sections)) state.sections[key] = on;
  renderSections();
  markStale();
  loadDocument();
}

function toggleFormat(fmt, button) {
  if (state.formats.has(fmt)) {
    if (state.formats.size === 1) return;
    state.formats.delete(fmt);
  } else {
    state.formats.add(fmt);
  }
  button.classList.toggle("active", state.formats.has(fmt));
  markStale();
}

function setStatus(text, isError = false) {
  const el = $("#status");
  el.textContent = text || "";
  el.classList.toggle("error", isError);
}

/* ── report template ───────────────────────────────── */

function getPath(obj, path) {
  return path.split(".").reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const target = keys.reduce((acc, key) => (acc[key] = acc[key] || {}), obj);
  target[last] = value;
}

function styleDocument() {
  const paper = $("#doc-body");
  const t = state.template;
  if (!t) return;
  const brand = t.brand || {};
  const style = t.table_style || {};
  const fonts = t.fonts || {};
  const page = t.page || {};
  const set = (name, value) => paper.style.setProperty(name, value);
  set("--t-header-fill", brand.table_header_fill);
  set("--t-header-text", brand.table_header_text);
  set("--t-band", brand.table_band_fill);
  set("--t-border", brand.table_border);
  set("--t-pass", brand.pass);
  set("--t-fail", brand.fail);
  set("--t-heading", brand.primary_dark);
  set("--t-rule", brand.primary);
  set("--t-border-w", `${Math.max(Number(style.border_width_pt) || 0, 0.25)}px`);
  set("--t-pad", `${Number(style.cell_padding_pt) || 0}px`);
  set("--t-th-size", `${(Number(fonts.table_header_size) || 9) * 1.17}px`);
  set("--t-td-size", `${(Number(fonts.table_cell_size) || 9) * 1.17}px`);
  set("--t-h1", `${(Number(fonts.h1_size) || 18) * 1.05}px`);
  set("--t-body", `${(Number(fonts.body_size) || 10) * 1.3}px`);
  set("--t-mt", `${(Number(page.margin_top_mm) || 22) * 4.1}px`);
  set("--t-mb", `${(Number(page.margin_bottom_mm) || 20) * 4.1}px`);
  set("--t-mx", `${(Number(page.margin_left_mm) || 20) * 4.1}px`);
  paper.classList.toggle("banded", style.banded_rows !== false);
  paper.classList.toggle("header-bold", style.header_bold !== false);
  paper.classList.toggle("status-colour", style.status_color_coding !== false);

  paper.querySelector(".doc-watermark")?.remove();
  if (t.options?.watermark_draft) {
    // one mark per notional printed page, so it is visible wherever you scroll
    const perPage = 1080;
    const count = Math.max(1, Math.ceil(paper.scrollHeight / perPage));
    const text = t.options.watermark_text || "DRAFT";
    const layer = document.createElement("div");
    layer.className = "doc-watermark";
    layer.innerHTML = Array.from(
      { length: count },
      (_, i) => `<span style="top:${i * perPage + perPage / 2}px">${text}</span>`,
    ).join("");
    paper.appendChild(layer);
  }
}

function syncTemplateControls() {
  for (const input of $$("[data-tpl]")) {
    const value = getPath(state.template, input.dataset.tpl);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else if (value !== undefined && value !== null) input.value = value;
    if (input.dataset.out) {
      $(`#${input.dataset.out}`).textContent = `${input.value}${input.dataset.unit || ""}`;
    }
  }
}

function applyTemplate(cfg, { keepSections = false } = {}) {
  state.template = JSON.parse(JSON.stringify(cfg));
  $("#template-name").textContent = cfg.template_name || "Custom template";
  $("#template-desc").textContent = cfg.description || "Custom template.";
  if (!keepSections && cfg.sections) {
    state.sections = { ...cfg.sections };
    renderSections();
  }
  syncTemplateControls();
  markStale();
  loadDocument();
}

async function loadTemplates() {
  const payload = await (await fetch("/api/templates")).json();
  state.templates = payload.templates || [];
  const select = $("#template-pick");
  select.innerHTML = state.templates
    .map((t) => `<option value="${t.id}">${t.name}</option>`)
    .join("");
  const chosen = state.templates.find((t) => t.default) || state.templates[0];
  if (chosen) {
    select.value = chosen.id;
    await useTemplate(chosen.id);
  }
}

async function useTemplate(id) {
  const cfg = await (await fetch(`/api/templates/${encodeURIComponent(id)}`)).json();
  state.templateId = id;
  applyTemplate(cfg);
}

function downloadTemplate() {
  const blob = new Blob([JSON.stringify(state.template, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  const slug = (state.template.template_name || "template")
    .replace(/[^a-z0-9]+/gi, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  a.download = `${slug}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function uploadTemplate(file) {
  try {
    const cfg = JSON.parse(await file.text());
    for (const key of ["brand", "fonts", "table_style", "page", "sections"]) {
      if (!cfg[key]) throw new Error(`Template is missing "${key}"`);
    }
    state.templateId = "";
    applyTemplate(cfg);
    setStatus(`Loaded template “${cfg.template_name || file.name}”.`);
  } catch (err) {
    setStatus(`Could not read that template: ${err.message || err}`, true);
  }
}

/* ── live document ─────────────────────────────────── */

function statusClass(value) {
  const v = String(value).trim().toUpperCase();
  if (v === "PASS" || v === "A") return "pass";
  if (["FAIL", "B", "C", "D"].includes(v)) return "fail";
  return "";
}

function tableBlock(block) {
  const wrap = document.createElement("div");
  wrap.className = `doc-table-wrap${block.editable ? " editable" : ""}`;
  if (block.editable) {
    wrap.dataset.section = block.section;
    wrap.dataset.sql = state.sectionSql[block.section] || block.sql || "";
    if (state.tableOverrides[block.section]) wrap.classList.add("changed");
  }
  const statusCol = block.status_col;
  const body = block.rows
    .map((row) => {
      const cells = row
        .map((cell, i) => {
          const isStatus = i === statusCol || (statusCol === -1 && i === row.length - 1);
          const cls = isStatus ? statusClass(cell) : "";
          return `<td class="${cls}">${cell ?? ""}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  wrap.innerHTML = `<table>
      <thead><tr>${block.headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody>
    </table>`;

  if (block.editable) {
    const bar = document.createElement("div");
    bar.className = "table-bar";
    bar.innerHTML = `<button type="button" data-act="edit">Edit with AI</button>
      <button type="button" class="ghost" data-act="source">Change table</button>`;
    bar.addEventListener("click", (ev) => {
      const act = ev.target.dataset.act;
      if (act) openEditor(wrap, act);
    });
    wrap.appendChild(bar);
  }
  return wrap;
}

function coverBlock(block) {
  const el = document.createElement("div");
  el.className = "doc-cover";
  el.innerHTML = `
    <div class="cover-top">
      ${block.logo ? `<img src="${block.logo}" alt="Element" />` : "<span></span>"}
      ${block.partner ? `<img class="small" src="${block.partner}" alt="Databricks" />` : ""}
    </div>
    ${block.classification ? `<div class="cover-class">${block.classification}</div>` : ""}
    ${block.hero ? `<img class="cover-hero" src="${block.hero}" alt="" />` : ""}
    <h1 class="cover-title">${block.project_name}</h1>
    <p class="cover-sub">${block.subtitle}</p>
    <dl class="cover-fields">
      ${block.fields.map(([k, v]) => `<dt>${k}</dt><dd>${v || "—"}</dd>`).join("")}
    </dl>
    <div class="cover-standards">
      <strong>Standards applied</strong>
      ${block.standards.map((s) => `<div class="doc-bullet">${s}</div>`).join("")}
    </div>`;
  return el;
}

function renderDocument(payload) {
  const host = $("#doc-body");
  host.innerHTML = "";
  for (const block of payload.blocks) {
    let el;
    if (block.type === "cover") {
      el = coverBlock(block);
    } else if (block.type === "heading") {
      el = document.createElement("h1");
      el.textContent = block.text;
    } else if (block.type === "paragraph") {
      el = document.createElement("p");
      el.textContent = block.text;
      if (block.bold) el.classList.add("bold");
      if (block.muted) el.classList.add("muted");
    } else if (block.type === "bullet") {
      el = document.createElement("div");
      el.className = "doc-bullet";
      el.textContent = block.text;
    } else if (block.type === "caption") {
      el = document.createElement("p");
      el.className = "doc-caption";
      el.textContent = block.text;
    } else if (block.type === "figure") {
      el = document.createElement("figure");
      el.className = "doc-figure";
      el.innerHTML = `<img src="${block.src}" alt="" />${block.caption ? `<figcaption class="doc-caption">${block.caption}</figcaption>` : ""}`;
    } else if (block.type === "pagebreak") {
      el = document.createElement("div");
      el.className = "doc-break";
    } else if (block.type === "table") {
      if (block.caption) {
        const cap = document.createElement("p");
        cap.className = "doc-caption";
        cap.textContent = block.caption;
        host.appendChild(cap);
      }
      el = tableBlock(block);
    }
    if (el) host.appendChild(el);
  }
  styleDocument();
}

async function loadDocument() {
  if (!state.projectId) return;
  try {
    const res = await fetch("/api/document", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reportBody()),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "Could not build the document");
    renderDocument(payload);
    // images settle after first paint, so the watermark spacing is redone once
    setTimeout(styleDocument, 600);
    $("#preview-meta").textContent =
      `${payload.document_number} · rev ${payload.revision} — hover any table to change it`;
  } catch (err) {
    $("#doc-body").innerHTML = `<p class="doc-loading">${err.message || err}</p>`;
  }
}

/* ── table editor ──────────────────────────────────── */

function setEditorStatus(text, isError = false) {
  const el = $("#te-status");
  el.textContent = text || "";
  el.classList.toggle("error", isError);
}

function positionEditor(wrap) {
  const panel = $("#table-editor");
  const rect = wrap.getBoundingClientRect();
  const width = panel.offsetWidth || 420;
  const height = panel.offsetHeight || 400;
  let left = rect.right + 14;
  if (left + width > window.innerWidth - 12) left = Math.max(12, rect.left - width - 14);
  if (left < 12) left = Math.max(12, window.innerWidth - width - 12);
  let top = rect.top;
  if (top + height > window.innerHeight - 12) top = Math.max(12, window.innerHeight - height - 12);
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}

function fillTableOptions(sql) {
  const select = $("#te-table");
  const inSql = (sql.match(/\bfrom\s+([a-z0-9_.`]+)/i) || [])[1]?.replace(/`/g, "") || "";
  const names = state.tables.map((t) => t.full_name);
  if (inSql && !names.includes(inSql)) names.unshift(inSql);
  select.innerHTML = names
    .map((n) => `<option value="${n}"${n === inSql ? " selected" : ""}>${n}</option>`)
    .join("");
  select.dataset.original = inSql;
}

function fillSavedTables(section) {
  const select = $("#te-saved");
  const matches = state.savedTables.filter(
    (t) => t.discipline === section || (section === "appendix" && t.discipline === "appendix"),
  );
  const others = state.savedTables.filter((t) => !matches.includes(t));
  const opt = (t) =>
    `<option value="${t.table_key}">${t.label} · ${t.rows.length} rows${t.discipline !== section ? ` (${t.discipline})` : ""}</option>`;
  select.innerHTML =
    `<option value="">— ${matches.length ? "pick a saved table" : "none saved for this section"} —</option>` +
    matches.map(opt).join("") +
    (others.length ? `<optgroup label="Other sections">${others.map(opt).join("")}</optgroup>` : "");
}

function openEditor(wrap, focus) {
  const section = wrap.dataset.section;
  state.editing = { section, wrap };
  const sql = state.sectionSql[section] || wrap.dataset.sql || "";
  $("#te-title").textContent = SECTION_LABELS[section] || section;
  $("#te-prompt").value = "";
  $("#te-sql").value = sql;
  fillTableOptions(sql);
  fillSavedTables(section);
  setEditorStatus("");
  const panel = $("#table-editor");
  panel.hidden = false;
  positionEditor(wrap);
  ($(focus === "source" ? "#te-table" : "#te-prompt")).focus();
}

function closeEditor() {
  $("#table-editor").hidden = true;
  state.editing = null;
}

function headersFromRows(rows) {
  const first = rows?.[0];
  if (!first || "cells" in first) return null;
  const skip = new Set(["project_id", "discipline", "row_index"]);
  const cols = Object.keys(first).filter((k) => !skip.has(k));
  return cols.length ? cols.map(prettyHeader) : null;
}

function commitRows(section, payload) {
  state.tableOverrides = { ...state.tableOverrides, [section]: payload.table_rows };
  const headers = headersFromRows(payload.rows);
  if (headers) state.headerOverrides = { ...state.headerOverrides, [section]: headers };
  if (payload.sql) state.sectionSql[section] = payload.sql;
  markStale();
  closeEditor();
  loadDocument();
}

async function applyTableEdit() {
  const editing = state.editing;
  if (!editing) return;
  const prompt = $("#te-prompt").value.trim();
  const chosen = $("#te-table").value;
  const original = $("#te-table").dataset.original;
  const swapped = chosen && chosen !== original;
  if (!prompt && !swapped) {
    return setEditorStatus("Say what to change, or pick a different table.", true);
  }
  const btn = $("#te-apply");
  btn.disabled = true;
  setEditorStatus("Rewriting the SQL and rebuilding this table…");
  try {
    const res = await fetch("/api/gold/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: [
          prompt,
          swapped ? `Take the data from ${chosen} instead of ${original}.` : "",
          `This is the ${SECTION_LABELS[editing.section] || editing.section} table of the report — keep it row-level and readable.`,
        ]
          .filter(Boolean)
          .join(" "),
        project_id: state.projectId,
        current_sql: $("#te-sql").value,
        include_tables: swapped ? [chosen] : [],
        exclude_tables: swapped && original ? [original] : [],
      }),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "The model could not rewrite that");
    commitRows(editing.section, payload);
  } catch (err) {
    setEditorStatus(err.message || String(err), true);
  } finally {
    btn.disabled = false;
  }
}

function useSavedTable() {
  const editing = state.editing;
  if (!editing) return;
  const key = $("#te-saved").value;
  if (!key) return setEditorStatus("Pick a saved table first.", true);
  const saved = state.savedTables.find((t) => t.table_key === key);
  if (!saved) return setEditorStatus("That saved table is no longer available.", true);
  state.tableOverrides = { ...state.tableOverrides, [editing.section]: saved.rows };
  if (saved.headers?.length) {
    state.headerOverrides = { ...state.headerOverrides, [editing.section]: saved.headers };
  }
  if (saved.source_sql) state.sectionSql[editing.section] = saved.source_sql;
  markStale();
  closeEditor();
  loadDocument();
  setStatus(`Placed “${saved.label}” (from the notebook) into ${SECTION_LABELS[editing.section] || editing.section}.`);
}

async function loadSavedTables() {
  if (!state.projectId) return;
  try {
    const payload = await (
      await fetch(`/api/report-tables?project_id=${encodeURIComponent(state.projectId)}`)
    ).json();
    state.savedTables = payload.tables || [];
  } catch {
    state.savedTables = [];
  }
}

async function runEditorSql() {
  const editing = state.editing;
  if (!editing) return;
  const btn = $("#te-run");
  btn.disabled = true;
  setEditorStatus("Running SQL…");
  try {
    const res = await fetch("/api/gold/sql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: $("#te-sql").value, project_id: state.projectId }),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "SQL failed");
    commitRows(editing.section, payload);
  } catch (err) {
    setEditorStatus(err.message || String(err), true);
  } finally {
    btn.disabled = false;
  }
}

/* ── PDF ───────────────────────────────────────────── */

function showPreview(blobUrl, meta) {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = blobUrl;
  $("#preview-empty").hidden = true;
  const frame = $("#preview-frame");
  frame.hidden = false;
  frame.src = blobUrl;
  $("#stale").hidden = true;
  state.stale = false;
  setStatus(meta);
}

function renderDownloads(job) {
  const host = $("#downloads");
  host.innerHTML = "";
  for (const file of job.files) {
    const a = document.createElement("a");
    a.className = "download-btn";
    a.href = `/api/jobs/${job.job_id}/files/${encodeURIComponent(file.name)}`;
    a.textContent = `${file.format.toUpperCase()}${file.pages ? ` · ${file.pages}p` : ""}`;
    host.appendChild(a);
  }
}

async function generate() {
  if (!state.projectId) return setStatus("Select a project first.", true);
  const btn = $("#generate");
  btn.disabled = true;
  setStatus("Rendering the pack…");
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reportBody()),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "Generation failed");
    state.lastJob = payload;
    const pdf = payload.files.find((f) => f.format === "pdf");
    if (pdf) {
      const fileRes = await fetch(
        `/api/jobs/${payload.job_id}/files/${encodeURIComponent(pdf.name)}?inline=1`,
      );
      if (!fileRes.ok) throw new Error("Could not load the PDF");
      const blob = await fileRes.blob();
      showPreview(
        URL.createObjectURL(blob),
        `${payload.document_number} · ${pdf.pages || "?"} pages · ${fmtBytes(pdf.size)}`,
      );
    }
    renderDownloads(payload);
  } catch (err) {
    setStatus(err.message || String(err), true);
  } finally {
    btn.disabled = false;
  }
}

/* ── lab data tab ──────────────────────────────────── */

function renderGrid(host, rows) {
  if (!rows.length) {
    host.innerHTML = "<p class='hint'>No rows</p>";
    return;
  }
  const cols = Object.keys(rows[0]).filter((k) => k !== "cells");
  host.innerHTML = `<table><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${
    rows.map((row) => `<tr>${cols.map((c) => `<td>${row[c] ?? ""}</td>`).join("")}</tr>`).join("")
  }</tbody></table>`;
}

async function searchTables() {
  const q = $("#table-search").value.trim() || "emc";
  const host = $("#table-list");
  host.innerHTML = "<p class='hint'>Searching…</p>";
  try {
    const payload = await (await fetch(`/api/tables/search?q=${encodeURIComponent(q)}`)).json();
    state.tables = payload.tables || [];
    if (!state.tables.length) {
      host.innerHTML = "<p class='hint'>Nothing matched that search.</p>";
      return;
    }
    host.innerHTML = "";
    for (const table of state.tables) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "table-hit";
      btn.dataset.table = table.full_name;
      btn.innerHTML = `<strong>${table.name}</strong><span>${table.folder}</span>`;
      btn.addEventListener("click", () => {
        $$(".table-hit").forEach((el) => el.classList.remove("active"));
        btn.classList.add("active");
        previewTable(table);
      });
      host.appendChild(btn);
    }
    host.querySelector(".table-hit")?.classList.add("active");
    previewTable(state.tables[0]);
  } catch (err) {
    host.innerHTML = `<p class='hint'>${err.message || err}</p>`;
  }
}

async function previewTable(table) {
  const fullName = table.full_name;
  $("#table-title").textContent = table.name;
  $("#table-meta").textContent = `Loading ${fullName}…`;
  try {
    const payload = await (await fetch(`/api/tables/preview?table=${encodeURIComponent(fullName)}&limit=40`)).json();
    if (payload.detail) throw new Error(payload.detail);
    $("#table-meta").textContent = `${fullName} · ${payload.row_count} rows shown`;
    $("#table-sql").textContent = payload.sql || "";
    renderGrid($("#table-data"), payload.rows || []);
  } catch (err) {
    $("#table-meta").textContent = `${fullName} — ${err.message || err}`;
    $("#table-sql").textContent = "";
    $("#table-data").innerHTML = "";
  }
}

/* ── wrangle tab ───────────────────────────────────── */

function wrangleDiscipline() {
  return $("#wr-discipline").value || "radiated_emissions";
}

function buildWrangleSql(discipline) {
  const schema = state.catalog?.gold?.schema || "emc_gold";
  const pid = state.projectId || "";
  return (
    `SELECT * EXCEPT (project_id, row_index, discipline, cells)\n` +
    `FROM ${schema}.measurements\n` +
    `WHERE project_id = '${pid}' AND discipline = '${discipline}'\n` +
    `ORDER BY margin_db DESC\n` +
    `LIMIT 20`
  );
}

function refreshWrangleSql() {
  const box = $("#wr-sql");
  if (!box) return;
  box.value = buildWrangleSql(wrangleDiscipline());
}

function newRecipe(columns) {
  return {
    hide_columns: [],
    column_order: [...columns],
    renames: {},
    sort_by: null,
    sort_order: "asc",
    hide_headers: [],
    merge_columns: [],
    highlight: $("#wr-highlight").value || "#D4EDDA",
  };
}

function toggleIn(arr, val, on) {
  const i = arr.indexOf(val);
  if (on && i < 0) arr.push(val);
  if (!on && i >= 0) arr.splice(i, 1);
}

function setWrStatus(text, isError = false) {
  const el = $("#wr-status");
  el.textContent = text || "";
  el.classList.toggle("error", isError);
}

async function runWrangle() {
  const sql = $("#wr-sql").value.trim();
  if (!sql) return;
  const btn = $("#wr-run");
  btn.disabled = true;
  $("#wr-run-meta").textContent = "Running…";
  try {
    const res = await fetch("/api/wrangle/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, project_id: state.projectId }),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || "Query failed");
    state.wrangle = {
      sql: payload.sql,
      columns: payload.columns,
      rows: payload.rows,
      recipe: newRecipe(payload.columns),
    };
    $("#wr-run-meta").textContent = `${payload.row_count} rows · ${payload.columns.length} columns`;
    $("#wr-columns-panel").hidden = false;
    $("#wr-save-panel").hidden = false;
    $("#wr-save-report").hidden = true;
    if (!$("#wr-label").value.trim()) {
      $("#wr-label").value = (DISCIPLINES.find((d) => d[0] === wrangleDiscipline()) || [])[1] || "";
    }
    renderRawGrid(payload.columns, payload.rows);
    renderColumnControls();
    renderWranglePreview();
  } catch (err) {
    $("#wr-run-meta").textContent = err.message || String(err);
    $("#wr-columns-panel").hidden = true;
    $("#wr-save-panel").hidden = true;
    $("#wr-preview").innerHTML = `<p class="hint">${err.message || err}</p>`;
  } finally {
    btn.disabled = false;
  }
}

function renderRawGrid(columns, rows) {
  $("#wr-raw-grid").innerHTML = `<table><thead><tr>${
    columns.map((c) => `<th>${c}</th>`).join("")
  }</tr></thead><tbody>${
    rows.map((r) => `<tr>${r.map((c) => `<td>${c ?? ""}</td>`).join("")}</tr>`).join("")
  }</tbody></table>`;
}

function renderColumnControls() {
  const wr = state.wrangle;
  if (!wr) return;
  const rec = wr.recipe;
  const sortSel = $("#wr-sort-by");
  sortSel.innerHTML =
    `<option value="">— none —</option>` +
    rec.column_order
      .map(
        (c) =>
          `<option value="${c}"${rec.sort_by === c ? " selected" : ""}>${rec.renames[c] || prettyHeader(c)}</option>`,
      )
      .join("");
  const host = $("#wr-columns");
  host.innerHTML = "";
  for (const col of rec.column_order) {
    const hidden = rec.hide_columns.includes(col);
    const card = document.createElement("div");
    card.className = `wr-col${hidden ? " off" : ""}`;
    card.dataset.col = col;
    card.innerHTML = `
      <div class="wr-col-top">
        <span class="wr-key">${col}</span>
        <div class="wr-move">
          <button type="button" data-op="up" title="Move up">↑</button>
          <button type="button" data-op="down" title="Move down">↓</button>
        </div>
      </div>
      <input class="wr-rename" data-op="rename" placeholder="${prettyHeader(col)}" value="${rec.renames[col] || ""}" />
      <div class="wr-flags">
        <label class="tick"><input type="checkbox" data-op="hide" ${hidden ? "checked" : ""}/><span>Hide</span></label>
        <label class="tick"><input type="checkbox" data-op="hidehdr" ${rec.hide_headers.includes(col) ? "checked" : ""}/><span>No header</span></label>
        <label class="tick"><input type="checkbox" data-op="merge" ${rec.merge_columns.includes(col) ? "checked" : ""}/><span>Merge</span></label>
      </div>`;
    host.appendChild(card);
  }
}

function moveColumn(col, delta) {
  const arr = state.wrangle.recipe.column_order;
  const i = arr.indexOf(col);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= arr.length) return;
  [arr[i], arr[j]] = [arr[j], arr[i]];
  renderColumnControls();
  renderWranglePreview();
}

const debouncedPreview = () => {
  clearTimeout(state._wrTimer);
  state._wrTimer = setTimeout(renderWranglePreview, 180);
};

async function renderWranglePreview() {
  const wr = state.wrangle;
  if (!wr || !wr.columns) return;
  try {
    const res = await fetch("/api/wrangle/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ columns: wr.columns, rows: wr.rows, recipe: wr.recipe }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || "Preview failed");
    wr.shaped = out;
    drawShaped(out);
  } catch (err) {
    $("#wr-preview").innerHTML = `<p class="hint">${err.message || err}</p>`;
  }
}

function drawShaped(out) {
  const { headers, rows, merges, highlight, columns } = out;
  const statusCol = columns.indexOf("status");
  const spanAt = {};
  Object.entries(merges || {}).forEach(([col, arr]) => {
    spanAt[columns.indexOf(col)] = arr;
  });
  let body = "";
  rows.forEach((row, ri) => {
    body += "<tr>";
    row.forEach((cell, ci) => {
      const spans = spanAt[ci];
      if (spans) {
        if (spans[ri] === 0) return;
        const rs = spans[ri];
        const bg = rs > 1 ? ` style="background:${highlight}"` : "";
        body += `<td rowspan="${rs}"${bg}>${cell ?? ""}</td>`;
      } else {
        const cls = ci === statusCol ? statusClass(cell) : "";
        body += `<td class="${cls}">${cell ?? ""}</td>`;
      }
    });
    body += "</tr>";
  });
  $("#wr-preview").innerHTML = `<table class="wr-table"><thead><tr>${
    headers.map((h) => `<th>${h || ""}</th>`).join("")
  }</tr></thead><tbody>${body}</tbody></table>`;
  $("#wr-preview-meta").textContent =
    `${rows.length} rows · ${headers.length} columns — this is what saves to Gold and drops into the PDF.`;
}

async function saveWrangle() {
  const wr = state.wrangle;
  if (!wr) return setWrStatus("Run a query first.", true);
  const btn = $("#wr-save");
  btn.disabled = true;
  setWrStatus("Saving to Gold…");
  try {
    const res = await fetch("/api/wrangle/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        discipline: wrangleDiscipline(),
        label: $("#wr-label").value.trim(),
        columns: wr.columns,
        rows: wr.rows,
        recipe: wr.recipe,
        source_sql: wr.sql,
      }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || "Save failed");
    setWrStatus(`Saved “${out.saved.label}” (${out.saved.row_count} rows) into report_tables.`);
    $("#wr-save-report").hidden = false;
    await loadSavedTables();
  } catch (err) {
    setWrStatus(err.message || String(err), true);
  } finally {
    btn.disabled = false;
  }
}

/* ── boot ──────────────────────────────────────────── */

async function boot() {
  await loadMe();
  const catalog = await (await fetch("/api/catalog")).json();
  state.catalog = catalog;
  state.sections = Object.fromEntries(catalog.sections.map((s) => [s.key, s.enabled]));
  state.projectId = catalog.projects[0]?.project_id || null;
  $("#template-name").textContent = catalog.template_name;
  const gold = catalog.gold || {};
  $("#source-hint").textContent = gold.connected
    ? `Live from ${gold.schema} · ${gold.measurement_count} measurement rows`
    : "Using bundled demo data (Gold warehouse not connected)";
  $("#wr-discipline").innerHTML = DISCIPLINES.map(
    ([k, l]) => `<option value="${k}">${l}</option>`,
  ).join("");
  renderProjects();
  renderSections();
  const project = currentProject();
  if (project) fillEditor(project);
  await loadTemplates();
  refreshWrangleSql();
  searchTables();
  loadSavedTables();
}

form().addEventListener("input", () => {
  markStale();
  clearTimeout(state._formTimer);
  state._formTimer = setTimeout(loadDocument, 500);
});
$$(".ws-tab").forEach((tab) => tab.addEventListener("click", () => showWorkspace(tab.dataset.ws)));
$("#template-pick").addEventListener("change", (ev) => useTemplate(ev.target.value));
$("#template-reset").addEventListener("click", () => {
  const id = state.templateId || $("#template-pick").value;
  if (id) useTemplate(id);
});
$("#template-download").addEventListener("click", downloadTemplate);
$("#template-file").addEventListener("change", (ev) => {
  const file = ev.target.files?.[0];
  if (file) uploadTemplate(file);
  ev.target.value = "";
});
$$("[data-tpl]").forEach((input) => {
  const handler = () => {
    if (!state.template) return;
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (input.type === "number" || input.type === "range") value = Number(input.value);
    else value = input.value;
    setPath(state.template, input.dataset.tpl, value);
    if (input.dataset.out) {
      $(`#${input.dataset.out}`).textContent = `${input.value}${input.dataset.unit || ""}`;
    }
    styleDocument();
    markStale();
    clearTimeout(state._tplTimer);
    state._tplTimer = setTimeout(loadDocument, 260);
  };
  input.addEventListener("input", handler);
  input.addEventListener("change", handler);
});
$("#view-doc").addEventListener("click", () => showView("doc"));
$("#view-pdf").addEventListener("click", () => showView("pdf"));
$("#all-on").addEventListener("click", () => setAllSections(true));
$("#all-off").addEventListener("click", () => setAllSections(false));
$("#fmt-docx").addEventListener("click", (ev) => toggleFormat("docx", ev.currentTarget));
$("#fmt-pdf").addEventListener("click", (ev) => toggleFormat("pdf", ev.currentTarget));
$("#generate").addEventListener("click", () => {
  showView("pdf");
  generate();
});
$("#wr-discipline").addEventListener("change", () => {
  refreshWrangleSql();
  const label = (DISCIPLINES.find((d) => d[0] === wrangleDiscipline()) || [])[1] || "";
  $("#wr-label").value = label;
});
$("#wr-run").addEventListener("click", runWrangle);
$("#wr-columns").addEventListener("click", (ev) => {
  const op = ev.target.dataset.op;
  const col = ev.target.closest(".wr-col")?.dataset.col;
  if (!col) return;
  if (op === "up") moveColumn(col, -1);
  if (op === "down") moveColumn(col, 1);
});
$("#wr-columns").addEventListener("change", (ev) => {
  const op = ev.target.dataset.op;
  const col = ev.target.closest(".wr-col")?.dataset.col;
  if (!op || !col) return;
  const rec = state.wrangle.recipe;
  if (op === "hide") toggleIn(rec.hide_columns, col, ev.target.checked);
  else if (op === "hidehdr") toggleIn(rec.hide_headers, col, ev.target.checked);
  else if (op === "merge") toggleIn(rec.merge_columns, col, ev.target.checked);
  else return;
  renderColumnControls();
  renderWranglePreview();
});
$("#wr-columns").addEventListener("input", (ev) => {
  if (ev.target.dataset.op !== "rename") return;
  const col = ev.target.closest(".wr-col").dataset.col;
  const v = ev.target.value.trim();
  if (v) state.wrangle.recipe.renames[col] = v;
  else delete state.wrangle.recipe.renames[col];
  debouncedPreview();
});
$("#wr-sort-by").addEventListener("change", (ev) => {
  state.wrangle.recipe.sort_by = ev.target.value || null;
  renderWranglePreview();
});
$("#wr-sort-dir").addEventListener("click", (ev) => {
  const b = ev.currentTarget;
  const dir = b.dataset.dir === "asc" ? "desc" : "asc";
  b.dataset.dir = dir;
  b.textContent = dir === "asc" ? "▲ asc" : "▼ desc";
  if (state.wrangle) {
    state.wrangle.recipe.sort_order = dir;
    renderWranglePreview();
  }
});
$("#wr-highlight").addEventListener("input", (ev) => {
  if (state.wrangle) {
    state.wrangle.recipe.highlight = ev.target.value;
    renderWranglePreview();
  }
});
$("#wr-save").addEventListener("click", saveWrangle);
$("#wr-save-report").addEventListener("click", () => showWorkspace("report"));
$("#search-tables").addEventListener("click", searchTables);
$("#table-search").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") searchTables();
});
$("#te-close").addEventListener("click", closeEditor);
$("#te-apply").addEventListener("click", applyTableEdit);
$("#te-run").addEventListener("click", runEditorSql);
$("#te-use-saved").addEventListener("click", useSavedTable);
$("#te-prompt").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) applyTableEdit();
});
$$("#te-chips .chip-btn").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("#te-prompt").value = chip.dataset.te;
    applyTableEdit();
  });
});
$(".preview-stage").addEventListener("scroll", () => {
  if (state.editing) positionEditor(state.editing.wrap);
});
window.addEventListener("resize", () => {
  if (state.editing) positionEditor(state.editing.wrap);
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeEditor();
});
boot().catch((err) => {
  const message = err.message || String(err);
  setStatus(message, true);
  $("#doc-body").innerHTML = `<p class="doc-loading">Could not start: ${message}</p>`;
});
