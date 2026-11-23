"""Define Custom Factorial Design validation and worksheet DOE metadata attachment."""
from __future__ import annotations

import copy
import math
from typing import Dict, Iterable, List, Optional, Sequence

from .model import Worksheet, finite_number


def _sort_levels(values: Iterable[object], kind: str) -> List[object]:
    unique = []
    seen = set()
    for val in values:
        key = (type(val).__name__, val) if kind != "number" else float(val)
        if key not in seen:
            seen.add(key)
            unique.append(float(val) if kind == "number" else str(val))
    if kind == "number":
        return sorted(unique)
    try:
        return sorted(unique, key=lambda s: str(s).casefold())
    except TypeError:
        return unique


def _validate_col_index(worksheet: Worksheet, idx: int, label: str) -> int:
    if type(idx) is not int or not 0 <= idx < len(worksheet.columns):
        raise ValueError(f"{label} refers to an unknown worksheet column.")
    return idx


def _parse_two_level_numeric(col, observed: List[float], override: Optional[tuple] = None) -> dict:
    levels = _sort_levels(observed, "number")
    if override is not None:
        raw_low, raw_high = override
        low = finite_number(float(raw_low))
        high = finite_number(float(raw_high))
        if low >= high:
            raise ValueError(f"Low must be below High for numeric factor '{col.name}'.")
        center = math.fsum((low / 2.0, high / 2.0))
        half = (high - low) / 2.0
        for val in observed:
            if not (
                abs(val - low) <= 1e-8
                or abs(val - high) <= 1e-8
                or abs(val - center) <= 1e-8
            ):
                raise ValueError(
                    f"Factor '{col.name}' contains {val:g}, which is outside Low ({low:g}), High ({high:g}), and midpoint ({center:g})."
                )
        if not any(abs(v - low) <= 1e-8 for v in observed) or not any(abs(v - high) <= 1e-8 for v in observed):
            raise ValueError(f"Factor '{col.name}' must observe both Low ({low:g}) and High ({high:g}) levels.")
    else:
        if len(levels) < 2:
            raise ValueError(f"Factor '{col.name}' must have at least 2 distinct levels.")
        if len(levels) == 2:
            low, high = float(levels[0]), float(levels[1])
        elif len(levels) == 3:
            low, mid, high = float(levels[0]), float(levels[1]), float(levels[2])
            expected_mid = math.fsum((low / 2.0, high / 2.0))
            if abs(mid - expected_mid) > 1e-8:
                raise ValueError(
                    f"Factor '{col.name}' has {len(levels)} non-midpoint levels ({levels}). "
                    "Choose General full factorial for 3+ factor levels."
                )
        else:
            raise ValueError(
                f"Factor '{col.name}' has {len(levels)} levels; a 2-level design supports 2 levels "
                "(plus an optional midpoint center). Choose General full factorial instead."
            )
        center = math.fsum((low / 2.0, high / 2.0))
        half = (high - low) / 2.0
    if not math.isfinite(half) or half <= 0:
        raise ValueError(f"Factor '{col.name}' level span exceeds supported numeric range.")
    return {
        "name": col.name,
        "kind": "number",
        "levels": [low, high],
        "low": low,
        "high": high,
        "center": center,
        "half_range": half,
    }


def _parse_two_level_text(col, observed: List[str], override: Optional[tuple] = None) -> dict:
    levels = _sort_levels(observed, "text")
    if override is not None:
        low = str(override[0]).strip()
        high = str(override[1]).strip()
        if not low or not high or low == high:
            raise ValueError(f"Text factor '{col.name}' requires two distinct non-empty levels.")
        if set(observed) - {low, high}:
            extra = sorted(set(observed) - {low, high})
            raise ValueError(
                f"Factor '{col.name}' contains unexpected level(s) {', '.join(extra)} not in ({low}, {high})."
            )
        if low not in observed or high not in observed:
            raise ValueError(f"Factor '{col.name}' must observe both '{low}' and '{high}'.")
    else:
        if len(levels) != 2:
            raise ValueError(
                f"Text factor '{col.name}' has {len(levels)} distinct level(s); "
                "a 2-level design requires exactly 2 levels. Choose General full factorial for 3+ levels."
            )
        low, high = str(levels[0]), str(levels[1])
    return {
        "name": col.name,
        "kind": "text",
        "levels": [low, high],
        "low": low,
        "high": high,
        "center": None,
        "half_range": None,
    }


def _parse_general_factor(col, observed: Sequence[object]) -> dict:
    levels = _sort_levels(observed, col.kind)
    if len(levels) < 2:
        raise ValueError(f"Factor '{col.name}' requires at least 2 observed distinct levels.")
    if len(levels) > 50:
        raise ValueError(f"Factor '{col.name}' has too many levels ({len(levels)}) for a categorical factorial design.")
    info = {
        "name": col.name,
        "kind": col.kind,
        "levels": levels,
    }
    if len(levels) == 2:
        info["low"] = levels[0]
        info["high"] = levels[1]
        if col.kind == "number":
            low, high = float(levels[0]), float(levels[1])
            info["center"] = math.fsum((low / 2.0, high / 2.0))
            info["half_range"] = (high - low) / 2.0
        else:
            info["center"] = None
            info["half_range"] = None
    return info


def define_custom_factorial(
    worksheet: Worksheet,
    factor_indices: Sequence[int],
    design_type: str = "two_level",
    *,
    hard_factor_indices: Optional[Sequence[int]] = None,
    std_order_index: Optional[int] = None,
    run_order_index: Optional[int] = None,
    point_type_index: Optional[int] = None,
    blocks_index: Optional[int] = None,
    low_high: Optional[Dict[int, tuple]] = None,
) -> dict:
    """Validate and attach custom factorial DOE metadata to an existing worksheet."""
    if not isinstance(worksheet, Worksheet):
        raise ValueError("A Worksheet is required.")
    if design_type not in ("two_level", "split_plot", "general_full"):
        raise ValueError("Choose 2-level factorial, 2-level split-plot, or General full factorial.")

    factors = list(factor_indices or [])
    if len(set(factors)) != len(factors):
        raise ValueError("Select distinct worksheet columns for Factors.")
    min_factors = 1 if design_type == "general_full" else 2
    if not min_factors <= len(factors) <= 15:
        raise ValueError(f"Select {min_factors} to 15 factor columns for this design type.")
    for idx in factors:
        _validate_col_index(worksheet, idx, "Factors")

    factor_cols = [worksheet.columns[idx] for idx in factors]
    for col in factor_cols:
        if col.kind not in ("number", "text"):
            raise ValueError(f"Factor column '{col.name}' must be Numeric or Text (not {col.kind}).")
    factor_names = [col.name.strip() for col in factor_cols]
    if any(not name for name in factor_names) or len({n.casefold() for n in factor_names}) != len(factor_names):
        raise ValueError("Selected factors must have non-empty distinct column names.")

    # Validate hard-to-change factors
    hard_list = list(hard_factor_indices or [])
    if design_type != "split_plot":
        if hard_list:
            raise ValueError("Hard-to-change factors apply only to 2-level split-plot designs.")
    else:
        if len(set(hard_list)) != len(hard_list) or any(idx not in factors for idx in hard_list):
            raise ValueError("Hard-to-change factors must be selected from the chosen Factors.")
        if not 1 <= len(hard_list) < len(factors):
            raise ValueError("A split-plot design requires at least one hard-to-change factor and one easy-to-change factor.")

    # Validate optional special role columns and detect collisions
    specials = [
        ("Standard Order", std_order_index, ("number",)),
        ("Run Order", run_order_index, ("number",)),
        ("Point Type", point_type_index, ("number",)),
        ("Blocks", blocks_index, ("number", "text")),
    ]
    used_roles: Dict[int, str] = {}
    for role_name, col_idx, allowed_kinds in specials:
        if col_idx is None:
            continue
        _validate_col_index(worksheet, col_idx, role_name)
        if col_idx in factors:
            raise ValueError(f"{role_name} column '{worksheet.columns[col_idx].name}' cannot also be selected as a Factor.")
        if col_idx in used_roles:
            raise ValueError(
                f"{role_name} column '{worksheet.columns[col_idx].name}' conflicts with {used_roles[col_idx]}."
            )
        col = worksheet.columns[col_idx]
        if col.kind not in allowed_kinds:
            expected = "/".join("Numeric" if k == "number" else "Text" for k in allowed_kinds)
            raise ValueError(f"{role_name} column '{col.name}' must be {expected} (found {col.kind}).")
        used_roles[col_idx] = role_name

    n_rows = worksheet.row_count
    if n_rows < 2:
        raise ValueError("Worksheet needs at least 2 rows to define a factorial design.")

    # Collect complete design rows across selected factors and special columns
    complete_rows: List[int] = []
    for row in range(n_rows):
        missing = False
        for idx in factors:
            col = worksheet.columns[idx]
            val = col.values[row] if row < len(col.values) else None
            if val is None or (col.kind == "text" and str(val).strip() == ""):
                missing = True
                break
            if col.kind == "number":
                finite_number(val)
        if missing:
            continue
        for role_name, col_idx, _ in specials:
            if col_idx is None:
                continue
            col = worksheet.columns[col_idx]
            val = col.values[row] if row < len(col.values) else None
            if val is None or (col.kind == "text" and str(val).strip() == ""):
                raise ValueError(
                    f"{role_name} column '{col.name}' has a missing value at row {row + 1} on an active design run."
                )
            if col.kind == "number":
                finite_number(val)
        complete_rows.append(row)

    if len(complete_rows) < 2:
        raise ValueError("At least 2 complete rows across all selected factors are required.")

    # Build validated factor metadata descriptors
    low_high = low_high or {}
    from .fractional import _FACTOR_LETTERS

    factor_descriptors: List[dict] = []
    for pos, idx in enumerate(factors):
        col = worksheet.columns[idx]
        observed = [col.values[r] for r in complete_rows]
        override = low_high.get(idx)
        if design_type == "general_full":
            desc = _parse_general_factor(col, observed)
        elif col.kind == "text":
            desc = _parse_two_level_text(col, [str(v) for v in observed], override=override)
        else:
            desc = _parse_two_level_numeric(col, [float(v) for v in observed], override=override)
        desc["column_index"] = idx
        desc["letter"] = _FACTOR_LETTERS[pos] if pos < len(_FACTOR_LETTERS) else f"F{pos + 1}"
        if design_type == "split_plot":
            desc["stratum"] = "hard" if idx in hard_list else "easy"
        factor_descriptors.append(desc)

    design_labels = {
        "two_level": "Custom two-level factorial design",
        "split_plot": "Custom two-level split-plot design",
        "general_full": "Custom general full factorial design",
    }
    meta = {
        "schema": "statcraft-custom-factorial-v1",
        "origin": "Custom-defined StatCraft factorial design",
        "custom_defined": True,
        "design": design_labels[design_type],
        "design_type": design_type,
        "factors": factor_descriptors,
        "hard_factors": [copy.deepcopy(d) for d in factor_descriptors if d.get("stratum") == "hard"],
        "easy_factors": [copy.deepcopy(d) for d in factor_descriptors if d.get("stratum") == "easy"],
        "runs": len(complete_rows),
        "std_order_mode": "column" if std_order_index is not None else "row_order",
        "std_order_column": worksheet.columns[std_order_index].name if std_order_index is not None else None,
        "std_order_column_index": std_order_index,
        "run_order_mode": "column" if run_order_index is not None else "row_order",
        "run_order_column": worksheet.columns[run_order_index].name if run_order_index is not None else None,
        "run_order_column_index": run_order_index,
        "point_type_mode": "column" if point_type_index is not None else "unknown",
        "point_type_column": worksheet.columns[point_type_index].name if point_type_index is not None else None,
        "point_type_column_index": point_type_index,
        "blocks_mode": "column" if blocks_index is not None else "none",
        "blocks_column": worksheet.columns[blocks_index].name if blocks_index is not None else None,
        "blocks_column_index": blocks_index,
        "native_parity": False,
    }
    if worksheet.metadata is None or not isinstance(worksheet.metadata, dict):
        worksheet.metadata = {}
    worksheet.metadata["doe"] = meta
    return copy.deepcopy(meta)
