"""Minitab-parity Matrix Algebra operations on Worksheet stored Matrix objects."""
from __future__ import annotations

from typing import Any

import numpy as np

from .model import Column, Matrix


def _find_matrix(worksheet: Any, name: str) -> Matrix:
    target = str(name or "").strip()
    for m in worksheet.matrices:
        if m.name == target:
            return m
    raise ValueError(f"Stored matrix '{target}' was not found.")


def _matrix_to_ndarray(matrix: Matrix) -> np.ndarray:
    if matrix.rows < 1 or matrix.columns < 1:
        raise ValueError(f"Matrix '{matrix.name}' must be non-empty.")
    if any(v is None for v in matrix.values):
        raise ValueError(f"Matrix '{matrix.name}' contains missing values.")
    # Matrix.values is column-major
    return np.asarray(matrix.values, dtype=float).reshape((matrix.columns, matrix.rows)).T


def _ndarray_to_matrix(name: str, arr: np.ndarray) -> Matrix:
    arr2 = np.asarray(arr, dtype=float)
    if arr2.ndim != 2:
        raise ValueError("Result must be a 2D matrix.")
    if not np.all(np.isfinite(arr2)):
        raise ValueError("Matrix operation produced non-finite values.")
    rows, cols = arr2.shape
    col_major = [float(x) for x in arr2.T.ravel()]
    return Matrix(name=name, rows=int(rows), columns=int(cols), values=col_major)


def _store_matrix(worksheet: Any, mat: Matrix) -> Matrix:
    for i, existing in enumerate(worksheet.matrices):
        if existing.name == mat.name:
            worksheet.matrices[i] = mat
            return mat
    worksheet.matrices.append(mat)
    return mat


def _format_matrix_report(title: str, mat: Matrix) -> dict[str, Any]:
    rows = mat.as_rows()
    headers = [f"C{c + 1}" for c in range(mat.columns)]
    str_rows = [[f"{float(v):.6g}" if v is not None else "*" for v in r] for r in rows]
    lines = [f"{title} ({mat.rows} × {mat.columns})", ""]
    lines.append("  " + "  ".join(f"{h:>10}" for h in headers))
    for r_idx, r in enumerate(str_rows):
        lines.append(f"R{r_idx + 1:<2} " + "  ".join(f"{val:>10}" for val in r))
    return {
        "analysis": "matrix_operation",
        "text": "\n".join(lines),
        "tables": [{"title": f"Matrix {mat.name} ({mat.rows}×{mat.columns})", "headers": headers, "rows": str_rows}],
    }


def matrix_arithmetic(
    worksheet: Any,
    operation: str,
    left_name: str,
    right_name: str | None = None,
    scalar: float | None = None,
    dest_name: str = "M_Out",
) -> dict[str, Any]:
    """Perform Add, Subtract, Multiply, or Scalar Multiply on stored matrices."""
    op = str(operation or "").strip().lower()
    a = _matrix_to_ndarray(_find_matrix(worksheet, left_name))
    dest = (dest_name or "").strip() or "M_Out"

    if op in ("add", "subtract"):
        b = _matrix_to_ndarray(_find_matrix(worksheet, right_name or ""))
        if a.shape != b.shape:
            raise ValueError(f"Matrix dimensions must match for {op}: {a.shape} vs {b.shape}.")
        res_arr = a + b if op == "add" else a - b
        label = f"Matrix {op.title()}: {left_name} {'+' if op == 'add' else '-'} {right_name} -> {dest}"
    elif op == "multiply":
        b = _matrix_to_ndarray(_find_matrix(worksheet, right_name or ""))
        if a.shape[1] != b.shape[0]:
            raise ValueError(f"Inner dimensions must match for multiplication: {a.shape} × {b.shape}.")
        res_arr = a @ b
        label = f"Matrix Multiply: {left_name} × {right_name} -> {dest}"
    elif op == "scalar":
        if scalar is None:
            raise ValueError("Provide a finite scalar multiplier.")
        k = float(scalar)
        res_arr = k * a
        label = f"Matrix Scalar Multiply: {k:g} × {left_name} -> {dest}"
    else:
        raise ValueError("Operation must be Add, Subtract, Multiply, or Scalar.")

    mat = _store_matrix(worksheet, _ndarray_to_matrix(dest, res_arr))
    return _format_matrix_report(label, mat)


def matrix_transpose(worksheet: Any, src_name: str, dest_name: str = "") -> dict[str, Any]:
    """Transpose a stored matrix and save to dest_name."""
    a = _matrix_to_ndarray(_find_matrix(worksheet, src_name))
    dest = (dest_name or "").strip() or f"{src_name}_T"
    mat = _store_matrix(worksheet, _ndarray_to_matrix(dest, a.T))
    return _format_matrix_report(f"Matrix Transpose: {src_name}' -> {dest}", mat)


def matrix_invert(worksheet: Any, src_name: str, dest_name: str = "") -> dict[str, Any]:
    """Invert a square non-singular stored matrix and save to dest_name."""
    a = _matrix_to_ndarray(_find_matrix(worksheet, src_name))
    if a.shape[0] != a.shape[1]:
        raise ValueError(f"Matrix '{src_name}' must be square to invert (got {a.shape[0]}×{a.shape[1]}).")
    if abs(float(np.linalg.det(a))) < 1e-12:
        raise ValueError(f"Matrix '{src_name}' is singular or nearly singular and cannot be inverted.")
    inv = np.linalg.inv(a)
    dest = (dest_name or "").strip() or f"{src_name}_Inv"
    mat = _store_matrix(worksheet, _ndarray_to_matrix(dest, inv))
    return _format_matrix_report(f"Matrix Invert: inv({src_name}) -> {dest}", mat)


def matrix_eigenanalysis(
    worksheet: Any,
    src_name: str,
    store_values_col: str = "",
    store_vectors_matrix: str = "",
) -> dict[str, Any]:
    """Compute eigenvalues and eigenvectors of a square matrix (sorted descending)."""
    a = _matrix_to_ndarray(_find_matrix(worksheet, src_name))
    if a.shape[0] != a.shape[1]:
        raise ValueError(f"Eigenanalysis requires a square matrix (got {a.shape[0]}×{a.shape[1]}).")
    if not np.allclose(a, a.T, atol=1e-10):
        raise ValueError(f"Eigenanalysis currently requires a symmetric matrix ('{src_name}' is asymmetric).")

    vals, vecs = np.linalg.eigh(a)
    order = np.argsort(vals)[::-1]
    vals = vals[order]
    vecs = vecs[:, order]

    total = float(np.sum(vals))
    props = [float(v / total) if abs(total) > 1e-12 else 0.0 for v in vals]
    cums = []
    running = 0.0
    for pr in props:
        running += pr
        cums.append(running)

    if store_values_col and store_values_col.strip():
        cname = store_values_col.strip()
        col_vals = [float(v) for v in vals]
        existing = next((i for i, c in enumerate(worksheet.columns) if c.name == cname), None)
        if existing is not None:
            worksheet.columns[existing].values = col_vals
            worksheet.columns[existing].kind = "number"
        else:
            worksheet.columns.append(Column(name=cname, kind="number", values=col_vals))

    if store_vectors_matrix and store_vectors_matrix.strip():
        _store_matrix(worksheet, _ndarray_to_matrix(store_vectors_matrix.strip(), vecs))

    headers = [f"PC{i + 1}" for i in range(len(vals))]
    rows = [
        ["Eigenvalue"] + [f"{float(v):.6g}" for v in vals],
        ["Proportion"] + [f"{p:.4f}" for p in props],
        ["Cumulative"] + [f"{c:.4f}" for c in cums],
    ]
    vec_rows = [[f"Row {r + 1}"] + [f"{float(vecs[r, c]):.6g}" for c in range(len(vals))] for r in range(len(vals))]
    text_lines = [
        f"Eigenanalysis of Matrix {src_name} ({a.shape[0]} × {a.shape[1]})",
        "Eigenvalues: " + ", ".join(f"{float(v):.6g}" for v in vals),
    ]
    return {
        "analysis": "matrix_eigenanalysis",
        "eigenvalues": [float(v) for v in vals],
        "eigenvectors": vecs.tolist(),
        "text": "\n".join(text_lines),
        "tables": [
            {"title": "Eigenanalysis of Symmetric Matrix", "headers": ["Statistic"] + headers, "rows": rows},
            {"title": "Eigenvectors", "headers": ["Variable"] + headers, "rows": vec_rows},
        ],
    }


def copy_columns_to_matrix(worksheet: Any, col_indices: list[int], dest_name: str = "M1") -> dict[str, Any]:
    """Copy equal-length numeric worksheet columns into a stored Matrix."""
    indices = list(col_indices or [])
    if not indices:
        raise ValueError("Select at least one numeric column.")
    cols = [worksheet.columns[i] for i in indices]
    if any(c.kind != "number" for c in cols):
        raise ValueError("Copy Columns to Matrix requires numeric columns.")
    n_rows = max((len(c.values) for c in cols), default=0)
    if n_rows < 1:
        raise ValueError("Selected columns contain no rows.")
    col_major = []
    for c in cols:
        for r in range(n_rows):
            v = c.values[r] if r < len(c.values) else None
            if v is None:
                raise ValueError(f"Column '{c.name}' contains missing values; matrices cannot hold missing cells.")
            col_major.append(float(v))
    dest = (dest_name or "").strip() or "M1"
    mat = _store_matrix(worksheet, Matrix(name=dest, rows=n_rows, columns=len(cols), values=col_major))
    return _format_matrix_report(f"Copy Columns to Matrix -> {dest}", mat)


def copy_matrix_to_columns(worksheet: Any, src_name: str, col_prefix: str = "") -> dict[str, Any]:
    """Copy each column of a stored Matrix into worksheet numeric columns."""
    m = _find_matrix(worksheet, src_name)
    prefix = (col_prefix or "").strip() or m.name
    created = []
    for c in range(m.columns):
        cname = f"{prefix}_{c + 1}" if m.columns > 1 else prefix
        vals = [m.cell(r, c) for r in range(m.rows)]
        existing = next((i for i, col in enumerate(worksheet.columns) if col.name == cname), None)
        if existing is not None:
            worksheet.columns[existing].values = vals
            worksheet.columns[existing].kind = "number"
        else:
            worksheet.columns.append(Column(name=cname, kind="number", values=vals))
        created.append(cname)
    return {
        "analysis": "matrix_copy",
        "text": f"Copied matrix '{m.name}' ({m.rows} × {m.columns}) to column(s): {', '.join(created)}.",
        "tables": [],
    }
