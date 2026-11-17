"""Graph ergonomics helpers for StatCraft chart entries (#44346, #44347, #44349-#44352).

Provides entry-mutating helpers that update ``graph_presentation`` (and
companion metadata) on StatCraft chart entries so quick actions and dialogs
stay synchronized with ``GraphFrame`` and ``GraphOptionsPane``.
"""

from __future__ import annotations

import math
import numbers
from typing import Iterable

import numpy as np

from .graph_presentation import graph_presentation, parse_ref_lines, validate_presentation


def _require_entry_dict(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("Graph entry must be a dictionary.")
    return entry


def _validate_axis(axis: str) -> str:
    if not isinstance(axis, str) or axis.strip().lower() not in ("x", "y"):
        raise ValueError("Axis must be 'x' or 'y'.")
    return axis.strip().lower()


def _validate_finite_number(value: float, name: str = "Value") -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a finite number.")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f"{name} must be a finite number.")
    return num


def _format_ref_number(value: float) -> str:
    return f"{value:.12g}"


def add_reference_line(entry: dict, axis: str, value: float, label: str = "") -> dict:
    """Append a finite reference line on ``axis`` ('x' or 'y') to ``entry``."""
    _require_entry_dict(entry)
    axis_norm = _validate_axis(axis)
    num_value = _validate_finite_number(value, "Reference line value")
    if label is None:
        label_str = ""
    elif not isinstance(label, str):
        raise ValueError("Reference line label must be a string.")
    else:
        label_str = label.strip()

    pres = graph_presentation(entry)
    ref_key = f"{axis_norm}_ref_line"
    existing = parse_ref_lines(pres.get(ref_key, ""))
    updated = existing + [num_value]
    pres[ref_key] = ", ".join(_format_ref_number(v) for v in updated)
    entry["graph_presentation"] = validate_presentation(pres)

    refs = list(entry["reference_lines"]) if isinstance(entry.get("reference_lines"), list) else []
    refs.append({"axis": axis_norm, "value": num_value, "label": label_str})
    entry["reference_lines"] = refs
    return entry


def add_percentile_line(
    entry: dict,
    values: Iterable[float],
    percentile: float,
    axis: str = "y",
) -> dict:
    """Compute ``percentile`` (0 < p < 100) of ``values`` and add it as a reference line."""
    _require_entry_dict(entry)
    axis_norm = _validate_axis(axis)
    pct = _validate_finite_number(percentile, "Percentile")
    if not (0.0 < pct < 100.0):
        raise ValueError("Percentile must be strictly between 0 and 100.")

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ValueError("Values must be a non-empty sequence of finite numbers.")
    clean = [_validate_finite_number(v, "Data value") for v in values]
    if not clean:
        raise ValueError("Values must be a non-empty sequence of finite numbers.")

    pct_value = float(np.percentile(clean, pct))
    return add_reference_line(entry, axis=axis_norm, value=pct_value, label=f"P{pct:g}")


def update_graph_annotations(
    entry: dict,
    title: str | None = None,
    subtitle: str | None = None,
    footnote: str | None = None,
) -> dict:
    """Update title, subtitle, and/or footnote on ``entry``."""
    _require_entry_dict(entry)
    pres = graph_presentation(entry)

    for field, raw in (("title", title), ("subtitle", subtitle), ("footnote", footnote)):
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ValueError(f"{field.capitalize()} must be a string.")
        cleaned = raw.strip()
        pres[field] = cleaned
        pres[f"{field}_enabled"] = bool(cleaned)

    validated = validate_presentation(pres)
    entry["graph_presentation"] = validated
    if title is not None:
        entry["title"] = validated["title"]
    return entry


def toggle_graph_gridlines(entry: dict, show: bool | None = None) -> bool:
    """Toggle or explicitly set major gridlines visibility on ``entry``."""
    _require_entry_dict(entry)
    pres = graph_presentation(entry)
    if show is None:
        new_state = not bool(pres["grid_enabled"])
    elif isinstance(show, bool):
        new_state = show
    else:
        raise ValueError("Gridlines visibility must be a boolean.")

    pres["grid_enabled"] = new_state
    entry["graph_presentation"] = validate_presentation(pres)
    return new_state
