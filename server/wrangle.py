"""Table wrangling — the in-app equivalent of the client's Interactive SQL
Query Executor notebook.

A *recipe* describes the same operations the notebook exposes as widgets:
hide columns, reorder, rename, sort, merge repeated values and a highlight
colour.  ``apply_recipe`` is the single source of truth used both by the
``/api/wrangle/*`` endpoints and (conceptually) by the notebook, so the table
that lands in ``report_tables`` — and therefore in the PDF — is identical to
what the engineer sees while wrangling.
"""
from __future__ import annotations

from typing import Any

_UNITS = {
    "mhz": "MHz", "db": "dB", "dbuv": "dBµV", "kv": "kV",
    "vm": "V/m", "eut": "EUT", "id": "ID",
}


def pretty_header(name: str) -> str:
    parts = str(name).split("_")
    out = []
    for part in parts:
        out.append(_UNITS.get(part.lower(), part[:1].upper() + part[1:]))
    return " ".join(out)


def _as_number(value: Any):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _sort_key(value: Any):
    num = _as_number(value)
    # numbers before strings, both ordered naturally
    return (0, num, "") if num is not None else (1, 0.0, str(value).lower())


def apply_recipe(
    columns: list[str],
    rows: list[list[str]],
    recipe: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply the wrangling recipe to a raw result set.

    ``columns``  original column keys from the SQL result.
    ``rows``     list of string rows aligned to ``columns``.
    ``recipe``   {hide_columns, column_order, renames, sort_by, sort_order,
                  hide_headers, merge_columns, highlight}.

    Returns {columns, headers, rows, merges, highlight} where ``headers`` and
    ``rows`` are what the PDF / report_tables should store, and ``merges`` is
    per-column rowspan metadata for the live preview.
    """
    recipe = recipe or {}
    columns = [str(c) for c in columns]
    hide = {c for c in (recipe.get("hide_columns") or []) if c in columns}
    order = [c for c in (recipe.get("column_order") or []) if c in columns]
    remaining = [c for c in columns if c not in order]
    ordered = [c for c in (order + remaining) if c not in hide]

    idx_of = {c: columns.index(c) for c in columns}
    data = [[_cell(row, idx_of[c]) for c in ordered] for row in rows]

    sort_by = recipe.get("sort_by")
    if sort_by in ordered:
        pos = ordered.index(sort_by)
        reverse = str(recipe.get("sort_order", "asc")).lower() == "desc"
        data.sort(key=lambda r: _sort_key(r[pos]), reverse=reverse)

    renames = recipe.get("renames") or {}
    hide_headers = set(recipe.get("hide_headers") or [])
    headers = [
        "" if c in hide_headers else (renames.get(c) or pretty_header(c))
        for c in ordered
    ]

    merge_cols = [c for c in (recipe.get("merge_columns") or []) if c in ordered]
    merges = _compute_merges(ordered, data, merge_cols)

    return {
        "columns": ordered,
        "headers": headers,
        "rows": data,
        "merges": merges,
        "highlight": recipe.get("highlight") or "#D4EDDA",
    }


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value)


def _compute_merges(
    ordered: list[str], data: list[list[str]], merge_cols: list[str]
) -> dict[str, list[int]]:
    """For each merge column, a per-row span count (0 = covered by the row above)."""
    n = len(data)
    result: dict[str, list[int]] = {}
    for col in merge_cols:
        pos = ordered.index(col)
        spans = [1] * n
        i = 0
        while i < n:
            j = i + 1
            while j < n and data[j][pos] == data[i][pos] and data[i][pos] != "":
                spans[j] = 0
                j += 1
            spans[i] = j - i
            i = j
        result[col] = spans
    return result
