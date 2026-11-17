"""Minitab Session Command & Batch Exec (.MTB) Interpreter for StatCraft."""
from __future__ import annotations

import math
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MAX_MACRO_STEPS = 100_000
MAX_MACRO_DEPTH = 64

_BUILTIN_VERBS = frozenset({
    "DESCRIBE", "DESC", "INFO", "INFORMATION", "CORRELATION", "CORR",
    "NORMALITY", "NORM", "LET", "NAME", "ERASE", "COPY", "DELETE", "SET",
    "PRINT", "READ", "MEAN", "STDEV", "MEDIAN", "SUM", "MINIMUM", "MAXIMUM",
    "COUNT", "N", "NMISS",
    "HISTOGRAM", "HIST", "BOXPLOT", "BOX", "DOTPLOT", "DOT", "PARETO",
    "TSPLOT", "INTERVALPLOT", "IPLOT", "INDIVIDUAL", "INDPLOT", "PLOT", "SCATTERPLOT",
    "REGRESS", "REGR", "ANOVA", "ONEWAY", "AOVONEWAY",
    "TWOSAMPLE", "TWOSAMPLE-T", "TTEST", "TINTERVAL", "1SAMPLE", "ONESAMPLE", "CHI", "CHISQUARE",
    "TALLY", "INDICATOR", "SUBSET", "RANDOM", "SORT", "RANK", "CAPABILITY", "CAPA",
    "XBARR", "XBARCHART", "XBAR-R", "IMR", "ICHART", "PCHART", "NPCHART", "CCHART", "UCHART",
    "EWMA", "CUSUM", "PCA", "FACTOR", "CLUSTER", "KMEANS", "ARIMA",
    "ACF", "PACF", "CCF", "RSCR", "RSCRIPT", "R", "BOOTSTRAP", "RANDTEST",
    "PGOF", "NBREG", "BANOVA", "NESTED", "MANOVA", "REML", "MIXED",
    "COXPH", "SIXSIGMA", "RANDOMFOREST", "TREENET", "MARS", "BESTMODEL",
    "MONTECARLO",
})


@dataclass
class _MacroDef:
    name: str
    is_global: bool
    params: List[str]
    body: List[Any]


@dataclass
class _MacroScope:
    constants: Dict[str, Optional[float]] = field(default_factory=dict)
    columns: Dict[str, str] = field(default_factory=dict)
    matrices: Dict[str, str] = field(default_factory=dict)
    param_bindings: Dict[str, str] = field(default_factory=dict)
    scratch_col_count: int = 0


@dataclass
class _ExecContext:
    steps: int = 0
    depth: int = 0

    def tick(self) -> None:
        self.steps += 1
        if self.steps > MAX_MACRO_STEPS:
            raise ValueError(f"Macro execution exceeded maximum step limit ({MAX_MACRO_STEPS}).")


@dataclass
class _CommandStmt:
    main_cmd: str
    subcommands: List[str]


@dataclass
class _MacroDefStmt:
    macro: _MacroDef


@dataclass
class _DeclStmt:
    kind: str
    names: List[str]


@dataclass
class _IfStmt:
    branches: List[Tuple[Optional[str], List[Any]]]


@dataclass
class _DoStmt:
    var_name: str
    start_expr: str
    end_expr: str
    body: List[Any]


def _strip_comment(line: str) -> str:
    """Strip unquoted # comments or Minitab NOTE statements."""
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.upper() == "NOTE" or stripped.upper().startswith("NOTE "):
        return ""
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:idx].strip()
    return stripped


def _split_unquoted_semicolons(line: str) -> List[Tuple[str, bool]]:
    """Split a line by unquoted semicolons; returns (segment_text, had_trailing_semicolon)."""
    segments: List[Tuple[str, bool]] = []
    start = 0
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ";" and not in_single and not in_double:
            seg = line[start:idx].strip()
            if seg:
                segments.append((seg, True))
            start = idx + 1
    tail = line[start:].strip()
    if tail:
        segments.append((tail, False))
    return segments


def parse_script_blocks(script_text: str) -> List[Tuple[str, List[str]]]:
    """Parse multi-line Minitab command script with ';' continuations and '.' terminators."""
    raw_lines = [_strip_comment(ln) for ln in script_text.splitlines()]
    raw_lines = [ln for ln in raw_lines if ln]
    blocks: List[Tuple[str, List[str]]] = []
    current_main: str | None = None
    current_subs: List[str] = []

    for ln in raw_lines:
        for seg, has_semi in _split_unquoted_semicolons(ln):
            if current_main is None:
                if has_semi:
                    current_main = seg
                    current_subs = []
                elif seg.endswith("."):
                    blocks.append((seg[:-1].strip(), []))
                else:
                    blocks.append((seg, []))
            else:
                if has_semi:
                    current_subs.append(seg)
                elif seg.endswith("."):
                    sub = seg[:-1].strip()
                    if sub:
                        current_subs.append(sub)
                    blocks.append((current_main, current_subs))
                    current_main = None
                    current_subs = []
                else:
                    current_subs.append(seg)

    if current_main is not None:
        blocks.append((current_main, current_subs))
    return blocks


def _get_macro_registry(presenter) -> Dict[str, _MacroDef]:
    registry = getattr(presenter, "_macros", None)
    if registry is None:
        registry = {}
        presenter._macros = registry
    return registry


def _split_macro_args(text: str) -> List[str]:
    if not text.strip():
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _format_scalar(val: float) -> str:
    if float(val).is_integer():
        return str(int(val))
    return repr(float(val))


def _substitute_scope_tokens(text: str, scope: Optional[_MacroScope]) -> str:
    """Substitute local MCOLUMN/MMATRIX/MCONSTANT symbols outside quoted strings."""
    if scope is None or not text:
        return text
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and text[j] != quote:
                j += 1
            if j < n:
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tok = text[i:j]
            up = tok.upper()
            if up in scope.columns:
                out.append(scope.columns[up])
            elif up in scope.matrices:
                out.append(scope.matrices[up])
            elif up in scope.constants:
                val = scope.constants[up]
                if val is None:
                    raise ValueError(f"Macro constant '{tok}' is not initialized.")
                out.append(_format_scalar(val))
            else:
                out.append(tok)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _normalize_condition_expr(expr: str) -> str:
    """Normalize Minitab comparison/boolean operators (=, <>, AND, OR, NOT) outside quotes."""
    out: List[str] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and expr[j] != quote:
                j += 1
            if j < n:
                j += 1
            out.append(expr[i:j])
            i = j
            continue
        if expr[i:i + 2] in ("<=", ">=", "==", "!="):
            out.append(expr[i:i + 2])
            i += 2
            continue
        if expr[i:i + 2] == "<>":
            out.append("!=")
            i += 2
            continue
        if ch == "=":
            out.append("==")
            i += 1
            continue
        if ch == "&":
            out.append(" and ")
            i += 1
            continue
        if ch == "|":
            out.append(" or ")
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            tok = expr[i:j]
            up = tok.upper()
            if up == "AND":
                out.append("and")
            elif up == "OR":
                out.append("or")
            elif up == "NOT":
                out.append("not")
            else:
                out.append(tok)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _eval_scalar_expr(expr: str, worksheet) -> Any:
    """Evaluate a scalar expression even when the worksheet currently has 0 rows."""
    from .calculator import evaluate_advanced
    from .model import Column, Worksheet

    if worksheet.row_count > 0:
        vals = evaluate_advanced(expr, worksheet)
        return vals[0] if vals else None
    cols = [
        Column(c.name, c.kind, list(c.values) if c.values else [None])
        for c in worksheet.columns
    ]
    if not cols:
        cols = [Column("_", "number", [0.0])]
    tmp_ws = Worksheet(worksheet.name, cols, worksheet.constants, worksheet.matrices)
    vals = evaluate_advanced(expr, tmp_ws)
    return vals[0] if vals else None


def _eval_scalar(expr: str, presenter, scope: Optional[_MacroScope]) -> float:
    resolved = _substitute_scope_tokens(expr, scope)
    val = _eval_scalar_expr(resolved, presenter.worksheet)
    if val is None:
        raise ValueError(f"Expression '{expr}' did not evaluate to a numeric scalar.")
    if not isinstance(val, (int, float)):
        raise ValueError(f"Expression '{expr}' must evaluate to a numeric scalar.")
    return float(val)


def _eval_condition(expr: str, presenter, scope: Optional[_MacroScope]) -> bool:
    resolved = _substitute_scope_tokens(expr, scope)
    normalized = _normalize_condition_expr(resolved)
    val = _eval_scalar_expr(normalized, presenter.worksheet)
    return bool(val)


def _split_verb_rest(main_cmd: str) -> Tuple[str, str]:
    raw = main_cmd.strip()
    if raw.endswith(".") or raw.endswith(";"):
        raw = raw[:-1].strip()
    parts = raw.split(None, 1)
    verb = parts[0].upper() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    return verb, rest


def _parse_statements(
    blocks: List[Tuple[str, List[str]]],
    idx: int = 0,
    stop_verbs: Tuple[str, ...] = (),
    in_macro: bool = False,
) -> Tuple[List[Any], int, Optional[str], str]:
    stmts: List[Any] = []
    while idx < len(blocks):
        main_cmd, subcommands = blocks[idx]
        verb, rest = _split_verb_rest(main_cmd)
        if verb in stop_verbs:
            return stmts, idx, verb, rest

        if verb in ("MACRO", "GMACRO"):
            if in_macro:
                raise ValueError("Nested MACRO/GMACRO definitions are not supported.")
            is_global = verb == "GMACRO"
            header = rest
            idx += 1
            if not header:
                if idx >= len(blocks):
                    raise ValueError(f"Unexpected end of script after {verb}.")
                header, _ = blocks[idx]
                header = header.strip().rstrip(".;")
                idx += 1
            toks = _split_macro_args(header)
            if not toks or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", toks[0]):
                raise ValueError(f"Invalid {verb} name in header '{header}'.")
            macro_name = toks[0].upper()
            params = [t.upper() for t in toks[1:]]
            body, idx, end_verb, _ = _parse_statements(
                blocks, idx, stop_verbs=("ENDMACRO",), in_macro=True
            )
            if end_verb != "ENDMACRO":
                raise ValueError(f"Missing ENDMACRO for {verb} '{macro_name}'.")
            idx += 1
            stmts.append(_MacroDefStmt(_MacroDef(macro_name, is_global, params, body)))
            continue

        if verb == "IF":
            if not rest:
                raise ValueError("Syntax: IF <condition>")
            branches: List[Tuple[Optional[str], List[Any]]] = []
            cond: Optional[str] = rest
            idx += 1
            while True:
                branch_body, idx, term_verb, term_rest = _parse_statements(
                    blocks, idx, stop_verbs=("ELSEIF", "ELSE", "ENDIF"), in_macro=in_macro
                )
                branches.append((cond, branch_body))
                if term_verb == "ELSEIF":
                    if not term_rest:
                        raise ValueError("Syntax: ELSEIF <condition>")
                    cond = term_rest
                    idx += 1
                elif term_verb == "ELSE":
                    cond = None
                    idx += 1
                    else_body, idx, end_verb, _ = _parse_statements(
                        blocks, idx, stop_verbs=("ENDIF",), in_macro=in_macro
                    )
                    if end_verb != "ENDIF":
                        raise ValueError("Missing ENDIF for IF block.")
                    branches.append((None, else_body))
                    idx += 1
                    break
                elif term_verb == "ENDIF":
                    idx += 1
                    break
                else:
                    raise ValueError("Missing ENDIF for IF block.")
            stmts.append(_IfStmt(branches))
            continue

        if verb == "DO":
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*:\s*(.+)$", rest)
            if not m:
                raise ValueError("Syntax: DO var = start:end")
            var_name = m.group(1).upper()
            start_expr = m.group(2).strip()
            end_expr = m.group(3).strip()
            idx += 1
            body, idx, end_verb, _ = _parse_statements(
                blocks, idx, stop_verbs=("ENDDO",), in_macro=in_macro
            )
            if end_verb != "ENDDO":
                raise ValueError("Missing ENDDO for DO loop.")
            idx += 1
            stmts.append(_DoStmt(var_name, start_expr, end_expr, body))
            continue

        if verb in ("MCONSTANT", "MCOLUMN", "MMATRIX"):
            names = [t.upper() for t in re.split(r"[\s,]+", rest) if t]
            if not names:
                raise ValueError(f"Syntax: {verb} name1 [name2 ...]")
            stmts.append(_DeclStmt(verb, names))
            idx += 1
            continue

        if verb in ("ELSEIF", "ELSE", "ENDIF", "ENDDO", "ENDMACRO"):
            raise ValueError(f"Unexpected '{verb}' without matching opening statement.")

        stmts.append(_CommandStmt(main_cmd, subcommands))
        idx += 1

    return stmts, idx, None, ""


def _parse_number_tokens(text: str) -> List[float]:
    """Parse space/comma-separated numbers and start:end ranges (e.g. '1:5 10')."""
    out: List[float] = []
    for tok in re.split(r"[\s,]+", text.strip()):
        if not tok:
            continue
        if ":" in tok:
            parts = tok.split(":", 1)
            a, b = int(parts[0]), int(parts[1])
            step = 1 if b >= a else -1
            if abs(b - a) > 10000:
                raise ValueError("Range cannot exceed 10,000 steps.")
            out.extend(float(x) for x in range(a, b + step, step))
        else:
            out.append(float(tok))
    return out


def execute_command_block(
    presenter,
    main_cmd: str,
    subcommands: List[str] | Tuple[str, ...] = (),
    scope: Optional[_MacroScope] = None,
) -> Any:
    """Execute one Minitab command statement (with optional subcommands)."""
    from .variable_dialogs import resolve_variables
    from .calculator import evaluate_advanced
    from .model import Column

    raw = main_cmd.strip()
    if not raw:
        raise ValueError("Enter a session command (for example: DESCRIBE C1, LET C3 = C1 + C2, INFO).")
    if raw.endswith(".") or raw.endswith(";"):
        raw = raw[:-1].strip()

    parts = raw.split(None, 1)
    verb = parts[0].upper()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if verb == "LET":
        if "=" not in rest:
            raise ValueError("Syntax: LET C1 = expression or LET K1 = expression")
        raw_lhs, raw_expr = [s.strip() for s in rest.split("=", 1)]
        lhs_up = raw_lhs.upper()
        expr = _substitute_scope_tokens(raw_expr, scope)
        if scope is not None and lhs_up in scope.constants:
            scalar = _eval_scalar_expr(expr, presenter.worksheet)
            if scalar is not None and not isinstance(scalar, (int, float)):
                raise ValueError("Stored constant value must be numeric.")
            scope.constants[lhs_up] = None if scalar is None else float(scalar)
            return presenter._record("Let Macro Constant", {"constant": lhs_up, "expression": expr, "value": scalar})
        lhs = _substitute_scope_tokens(raw_lhs, scope)
        lhs_up = lhs.upper()
        cell_match = re.match(r"^(C[1-9][0-9]*)\s*\(\s*(.+?)\s*\)$", lhs, re.IGNORECASE)
        if cell_match:
            col_tok = cell_match.group(1).upper()
            row_expr = cell_match.group(2).strip()
            c_idx = int(col_tok[1:]) - 1
            row_num = int(round(_eval_scalar(row_expr, presenter, scope)))
            if row_num < 1:
                raise ValueError("Row index must be >= 1.")
            scalar = _eval_scalar_expr(expr, presenter.worksheet)
            while len(presenter.worksheet.columns) <= c_idx:
                presenter.worksheet.columns.append(Column(f"C{len(presenter.worksheet.columns) + 1}", "number", []))
            col = presenter.worksheet.columns[c_idx]
            while len(col.values) < row_num:
                col.values.append(None)
            col.values[row_num - 1] = float(scalar) if isinstance(scalar, (int, float)) else scalar
            presenter.dirty = True
            return presenter._record("Let Cell", {"column": col_tok, "row": row_num, "expression": expr, "value": scalar})
        if lhs_up.startswith("K") and lhs_up[1:].isdigit():
            k_idx = int(lhs_up[1:]) - 1
            scalar = _eval_scalar_expr(expr, presenter.worksheet)
            if scalar is not None and not isinstance(scalar, (int, float)):
                raise ValueError("Stored constant value must be numeric.")
            while len(presenter.worksheet.constants) <= k_idx:
                next_num = len(presenter.worksheet.constants) + 1
                presenter.worksheet.constants.append(Column(f"K{next_num}", "number", [None]))
            presenter.worksheet.constants[k_idx].kind = "number"
            presenter.worksheet.constants[k_idx].values = [None if scalar is None else float(scalar)]
            presenter.dirty = True
            return presenter._record("Let Constant", {"constant": lhs_up, "expression": expr, "value": scalar})
        if lhs_up.startswith("C") and lhs_up[1:].isdigit():
            c_idx = int(lhs_up[1:]) - 1
            if 0 <= c_idx < len(presenter.worksheet.columns):
                try:
                    return presenter.assign_formula(c_idx, expr)
                except ValueError:
                    pass
        return presenter.calculate(expr, lhs)

    if scope is not None:
        rest = _substitute_scope_tokens(rest, scope)
        subcommands = [_substitute_scope_tokens(s, scope) for s in subcommands]

    if verb in ("DESCRIBE", "DESC"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.describe_columns(indices)

    if verb in ("INFO", "INFORMATION"):
        return presenter.worksheet_information()

    if verb in ("CORRELATION", "CORR"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.correlation(indices)

    if verb in ("NORMALITY", "NORM"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) != 1:
            raise ValueError("NORMALITY takes one numeric column (e.g., NORMALITY C1).")
        return presenter.normality(indices[0])

    if verb == "NAME":
        tokens = rest.split(None, 1)
        if len(tokens) != 2:
            raise ValueError("Syntax: NAME C1 'ColumnName'")
        indices = resolve_variables(tokens[0], presenter.worksheet, ("number", "text", "date"))
        clean_name = tokens[1].strip().strip("'\"")
        presenter.rename_column(indices[0], clean_name)
        return presenter._record("Name Column", {"column": "C" + str(indices[0] + 1), "name": clean_name})

    if verb == "ERASE":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        presenter.erase_variables(indices=indices)
        return presenter._record("Erase Variables", {"columns": ["C" + str(i + 1) for i in indices]})

    if verb == "COPY":
        cols = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        if len(cols) < 2 or len(cols) % 2 != 0:
            raise ValueError("Syntax: COPY C_src [C_src2 ...] C_dst [C_dst2 ...]")
        half = len(cols) // 2
        src_cols, dst_cols = cols[:half], cols[half:]
        inc_rows, omit_rows = None, None
        for sub in subcommands:
            toks = sub.strip().split()
            if not toks:
                continue
            head = toks[0].upper()
            if head == "USE":
                inc_rows = {int(v) - 1 for v in _parse_number_tokens(" ".join(toks[1:])) if v >= 1}
            elif head == "OMIT":
                omit_rows = {int(v) - 1 for v in _parse_number_tokens(" ".join(toks[1:])) if v >= 1}
        created = presenter.copy_columns_to_columns(src_cols, dst_cols, include_rows=inc_rows, omit_rows=omit_rows)
        return presenter._record("Copy Columns", {"columns": ["C" + str(i + 1) for i in created]})

    if verb == "DELETE":
        toks = rest.split()
        if len(toks) < 2:
            raise ValueError("Syntax: DELETE rows C1 [C2 ...]")
        split_at = next((idx for idx, t in enumerate(toks) if t.upper().startswith("C") and t[1:].isdigit()), None)
        if split_at is None or split_at == 0:
            raise ValueError("Syntax: DELETE rows C1 [C2 ...]")
        rows_zero = sorted({int(v) - 1 for v in _parse_number_tokens(" ".join(toks[:split_at])) if v >= 1})
        col_indices = resolve_variables(" ".join(toks[split_at:]), presenter.worksheet, ("number", "text", "date"))
        presenter.delete_rows(rows_zero, col_indices)
        return presenter._record("Delete Rows", {"rows": [r + 1 for r in rows_zero], "columns": ["C" + str(i + 1) for i in col_indices]})

    if verb == "SET":
        m = re.match(r"^(C[1-9][0-9]*)\s*(.*)$", rest, re.IGNORECASE)
        if not m:
            raise ValueError("Syntax: SET C1 1 2 3 or SET C1; 1:10.")
        col_tok, inline_vals = m.group(1).upper(), m.group(2).strip()
        col_idx = int(col_tok[1:]) - 1
        val_text = " ".join([inline_vals] + list(subcommands)).strip()
        nums = _parse_number_tokens(val_text)
        return presenter.set_column_values(col_idx, nums, "number")

    if verb in ("HISTOGRAM", "HIST"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) != 1:
            raise ValueError("HISTOGRAM takes one numeric column (e.g., HISTOGRAM C1).")
        from .recipes import run
        return run(presenter, {"action": "graph", "parameters": {"method": "histogram", "indices": indices, "bins": 10}})

    if verb in ("BOXPLOT", "BOX"):
        cleaned = rest.replace("*", " ")
        indices = resolve_variables(cleaned, presenter.worksheet, ("number", "text"))
        if len(indices) == 1:
            from .recipes import run
            return run(presenter, {"action": "graph", "parameters": {"method": "boxplot", "indices": indices, "bins": 1}})
        if len(indices) == 2 and "*" in rest:
            return presenter.boxplot_graphs([indices[0]], "one_groups", [indices[1]])
        if not indices:
            raise ValueError("BOXPLOT takes a numeric column (e.g., BOXPLOT C1 or BOXPLOT C1 * C2).")
        from .recipes import run
        return run(presenter, {"action": "graph", "parameters": {"method": "boxplot", "indices": indices, "bins": 1}})

    if verb in ("DOTPLOT", "DOT"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) < 1:
            raise ValueError("DOTPLOT takes one or more numeric columns (e.g., DOTPLOT C1).")
        return presenter.dotplot_graphs(indices, "one" if len(indices) == 1 else "multiple")

    if verb == "PARETO":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text"))
        if len(indices) != 1:
            raise ValueError("PARETO takes one defect column (e.g., PARETO C1).")
        return presenter.pareto_chart({
            "is_summarized": False,
            "defect_column": presenter.worksheet.columns[indices[0]].name,
            "combine_percent": 95.0,
            "show_cumulative": True,
        })

    if verb == "TSPLOT":
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) < 1:
            raise ValueError("TSPLOT takes one or more numeric columns (e.g., TSPLOT C1).")
        return presenter.expanded_graph("time_series", indices)

    if verb in ("INTERVALPLOT", "IPLOT"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) < 1:
            raise ValueError("INTERVALPLOT takes one or more numeric columns (e.g., INTERVALPLOT C1).")
        return presenter.expanded_graph("interval_plot", indices)

    if verb in ("INDIVIDUAL", "INDPLOT"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) < 1:
            raise ValueError("INDIVIDUAL takes one or more numeric columns (e.g., INDIVIDUAL C1).")
        return presenter.expanded_graph("individual_value", indices)

    if verb in ("PLOT", "SCATTERPLOT"):
        cleaned = rest.replace("*", " ")
        indices = resolve_variables(cleaned, presenter.worksheet, ("number",))
        if len(indices) != 2:
            raise ValueError("Syntax: PLOT C2 * C1 (Y then X)")
        return presenter.scatter_plot(indices[1], indices[0])

    if verb in ("REGRESS", "REGR", "REG"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) < 2:
            raise ValueError("Syntax: REGRESS C_response C_predictor1 [C_predictor2 ...]")
        return presenter.multiple_regression(indices[0], indices[1:])

    if verb in ("ONEWAY", "AOVONEWAY", "ANOVA"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) == 2:
            return presenter.oneway_anova(response_index=indices[0], factor_index=indices[1])
        elif len(indices) > 2:
            return presenter.oneway_anova_unstacked(indices)
        raise ValueError("Syntax: ONEWAY C_response C_factor or ONEWAY C1 C2 C3...")

    if verb in ("TTEST", "TINTERVAL"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if not indices:
            raise ValueError("Syntax: TTEST C1 [C2 ...]")
        return presenter.one_sample_t({"sample_cols": indices})

    if verb in ("TWOSAMPLE", "TWOSAMPLE-T"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) != 2:
            raise ValueError("Syntax: TWOSAMPLE C1 C2")
        return presenter.two_sample_t({"data_format": 1, "sample1_col": indices[0], "sample2_col": indices[1]})

    if verb in ("XBARCHART", "XBAR-R", "XBARR"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(indices) == 2:
            return presenter.xbar_r_stacked(response_index=indices[0], factor_index=indices[1])
        elif len(indices) > 2:
            return presenter.xbar_r_rows(indices)
        raise ValueError("Syntax: XBARCHART C_response C_subgroup or XBARCHART C1 C2 ...")

    if verb in ("IMR", "ICHART"):
        indices = resolve_variables(rest, presenter.worksheet, ("number",))
        if not indices:
            raise ValueError("Syntax: IMR C1")
        return presenter.imr_chart({"variables": indices, "options": {}})

    if verb in ("CAPABILITY", "CAPA"):
        indices = resolve_variables(rest.split()[0] if rest else "", presenter.worksheet, ("number",))
        if not indices:
            raise ValueError("Syntax: CAPABILITY C1; LSPEC lsl; USPEC usl.")
        lspec = uspec = target = None
        for sub in subcommands:
            sp = sub.split(None, 1)
            if not sp:
                continue
            sverb = sp[0].upper()
            sval = float(sp[1].strip()) if len(sp) > 1 else None
            if sverb in ("LSPEC", "LSL"):
                lspec = sval
            elif sverb in ("USPEC", "USL"):
                uspec = sval
            elif sverb == "TARGET":
                target = sval
        return presenter.normal_capability(indices[0], lspec, uspec, target)

    if verb == "TALLY":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        return presenter.tally_variables({"columns": indices})

    if verb == "INDICATOR":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        if len(indices) != 1:
            raise ValueError("Syntax: INDICATOR C1")
        return presenter.make_indicator_variables(indices[0])

    if verb == "SUBSET":
        cond = rest
        name = "Subset"
        for sub in subcommands:
            sp = sub.split(None, 1)
            if not sp:
                continue
            if sp[0].upper() in ("WHERE", "CONDITION") and len(sp) > 1:
                cond = sp[1].strip()
            elif sp[0].upper() == "NAME" and len(sp) > 1:
                name = sp[1].strip().strip("'\"")
        if not cond:
            raise ValueError("Syntax: SUBSET; WHERE C1 > 10.")
        return presenter.subset_worksheet_by_condition(cond, name=name)

    if verb == "RANDOM":
        tokens = rest.split()
        if len(tokens) < 2:
            raise ValueError("Syntax: RANDOM N C1 [; NORMAL mu sigma.]")
        n_rows = int(tokens[0])
        col_tok = tokens[1].upper()
        target_idx = int(col_tok[1:]) - 1 if col_tok.startswith("C") and col_tok[1:].isdigit() else -1
        dist_name = "Normal"
        dist_params: Tuple[float, ...] = (0.0, 1.0)
        for sub in subcommands:
            sp = sub.split()
            if not sp:
                continue
            dkey = sp[0].upper()
            pvals = [float(x) for x in sp[1:]]
            alias_map = {
                "NORMAL": ("Normal", (0.0, 1.0)),
                "UNIFORM": ("Uniform", (0.0, 1.0)),
                "EXPONENTIAL": ("Exponential", (1.0,)),
                "POISSON": ("Poisson", (5.0,)),
                "BINOMIAL": ("Binomial", (10.0, 0.5)),
                "WEIBULL": ("Weibull", (2.0, 1.0)),
                "GAMMA": ("Gamma", (2.0, 1.0)),
                "LOGNORMAL": ("Lognormal", (0.0, 1.0)),
                "BETA": ("Beta", (2.0, 2.0)),
                "INTEGER": ("Integer", (1.0, 10.0)),
            }
            if dkey in alias_map:
                dist_name, defaults = alias_map[dkey]
                dist_params = tuple(pvals) if pvals else defaults
        return presenter.generate_random_distribution_data(target_idx, dist_name, n_rows, dist_params)

    if verb == "SORT":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        if len(indices) < 1:
            raise ValueError("Syntax: SORT C1 [by C2]")
        return presenter.sort_columns(indices[:-1] or indices, indices[-1])

    if verb == "RANK":
        tokens = rest.split()
        if len(tokens) != 2:
            raise ValueError("Syntax: RANK C1 C2")
        indices = resolve_variables(tokens[0], presenter.worksheet, ("number",))
        return presenter.rank_column(indices[0], tokens[1])

    if verb == "CCF":
        fields = rest.split(maxsplit=1)
        lag_count = int(fields[0]) if len(fields) == 2 and fields[0].isdigit() else 0
        variables = fields[1] if lag_count or len(fields) == 2 and fields[0] == "0" else rest
        indices = resolve_variables(variables, presenter.worksheet, ("number",))
        if len(indices) != 2:
            raise ValueError("Use CCF [lags] C1 C2.")
        return presenter.cross_correlation(*indices, lags=lag_count)

    if verb in ("RSCR", "RSCRIPT", "R"):
        from .r_bridge import execute_r_code
        code = rest.strip()
        if (code.startswith('"') and code.endswith('"')) or (code.startswith("'") and code.endswith("'")):
            target_path = code[1:-1]
        else:
            target_path = code
        if os.path.isfile(target_path):
            code = Path(target_path).read_text(encoding="utf-8")
        res = execute_r_code(code, worksheet=presenter.worksheet)
        session_out = f"R Output:\n{res.get('stdout', '')}"
        if res.get("stderr"):
            session_out += f"\nR Diagnostics:\n{res['stderr']}"
        return presenter._record("R Script Output", {
            "analysis": "r_script",
            "session_text": session_out,
            "stdout": res.get("stdout", ""),
            "stderr": res.get("stderr", ""),
            "plot_path": res.get("plot_path"),
        })

    def _split_eq(expr_str: str) -> Tuple[List[int], List[int]]:
        if "=" in expr_str:
            lhs_s, rhs_s = expr_str.split("=", 1)
            return (
                resolve_variables(lhs_s, presenter.worksheet, ("number", "text")),
                resolve_variables(rhs_s, presenter.worksheet, ("number", "text")),
            )
        cols_all = resolve_variables(expr_str, presenter.worksheet, ("number", "text"))
        if len(cols_all) < 2:
            raise ValueError("Provide response and predictor columns (e.g., CMD C1 = C2 C3).")
        return [cols_all[0]], cols_all[1:]

    if verb == "BOOTSTRAP":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        opts = {k.upper(): v for k, v in (sub.split(None, 1) for sub in subcommands if sub.strip() and " " in sub.strip())}
        n_res = int(opts.get("RESAMPLES", 1000))
        stat = opts.get("STATISTIC", "Mean" if len(cols) == 1 else "Mean Difference")
        if len(cols) == 1:
            return presenter.bootstrap_1sample(cols[0], statistic=stat, n_resamples=n_res)
        if len(cols) == 2:
            return presenter.bootstrap_2sample(cols[0], cols[1], statistic=stat, n_resamples=n_res)
        raise ValueError("Syntax: BOOTSTRAP C1 [C2]")

    if verb == "RANDTEST":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(cols) == 1:
            return presenter.randomization_1sample(cols[0], n_resamples=1000)
        if len(cols) == 2:
            return presenter.randomization_2sample(cols[0], cols[1], n_resamples=1000)
        raise ValueError("Syntax: RANDTEST C1 [C2]")

    if verb == "PGOF":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.goodness_of_fit_poisson(cols[0])

    if verb == "NBREG":
        lhs, rhs = _split_eq(rest)
        return presenter.negative_binomial_regression(lhs[0], rhs)

    if verb == "BANOVA":
        lhs, rhs = _split_eq(rest)
        return presenter.balanced_anova(lhs[0], rhs)

    if verb == "NESTED":
        lhs, rhs = _split_eq(rest)
        return presenter.fully_nested_anova(lhs[0], rhs)

    if verb == "MANOVA":
        lhs, rhs = _split_eq(rest)
        return presenter.oneway_manova(lhs, rhs[0])

    if verb in ("REML", "MIXED"):
        lhs, rhs = _split_eq(rest)
        rnd_cols = []
        for sub in subcommands:
            if sub.strip().upper().startswith("RANDOM "):
                rnd_cols.extend(resolve_variables(sub.strip()[7:], presenter.worksheet, ("number", "text")))
        fixed_cols = [c for c in rhs if c not in rnd_cols]
        if not rnd_cols:
            rnd_cols = [rhs[-1]]
            fixed_cols = rhs[:-1]
        return presenter.fit_mixed_reml(lhs[0], fixed_indices=fixed_cols, random_indices=rnd_cols)

    if verb == "COXPH":
        lhs, rhs = _split_eq(rest)
        if len(lhs) != 2:
            raise ValueError("Syntax: COXPH Time Event = Covariates")
        return presenter.cox_ph_regression(lhs[0], lhs[1], rhs)

    if verb == "SIXSIGMA":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        lsl, usl, sub_sz = None, None, 1
        for sub in subcommands:
            toks = sub.strip().split()
            if len(toks) >= 2 and toks[0].upper() == "LSL":
                lsl = float(toks[1])
            elif len(toks) >= 2 and toks[0].upper() == "USL":
                usl = float(toks[1])
            elif len(toks) >= 2 and toks[0].upper() == "SUBGROUP":
                sub_sz = int(float(toks[1]))
        return presenter.six_sigma_process_report(cols[0], lsl=lsl, usl=usl, subgroup_size=sub_sz)

    if verb == "RANDOMFOREST":
        lhs, rhs = _split_eq(rest)
        return presenter.random_forest(lhs[0], rhs)

    if verb == "TREENET":
        lhs, rhs = _split_eq(rest)
        return presenter.treenet_gbm(lhs[0], rhs)

    if verb == "MARS":
        lhs, rhs = _split_eq(rest)
        return presenter.mars_regression(lhs[0], rhs)

    if verb == "BESTMODEL":
        lhs, rhs = _split_eq(rest)
        return presenter.discover_best_model(lhs[0], rhs)

    if verb == "MONTECARLO":
        inputs_s = rest or "X1: Normal(10, 0.5)"
        formula_s = "X1"
        lsl, usl, n_sims = None, None, 5000
        for sub in subcommands:
            s_up = sub.strip().upper()
            if s_up.startswith("FORMULA "):
                formula_s = sub.strip()[8:].strip().strip('"').strip("'")
            elif s_up.startswith("INPUTS "):
                inputs_s = sub.strip()[7:].strip().strip('"').strip("'")
            elif s_up.startswith("LSL "):
                lsl = float(sub.strip().split()[1])
            elif s_up.startswith("USL "):
                usl = float(sub.strip().split()[1])
            elif s_up.startswith("SIMS "):
                n_sims = int(float(sub.strip().split()[1]))
        return presenter.monte_carlo_simulation(inputs_s, formula_s, lsl=lsl, usl=usl, n_sims=n_sims)

    if verb in ("MEAN", "STDEV", "MEDIAN", "SUM", "MINIMUM", "MAXIMUM", "COUNT", "N", "NMISS"):
        toks = rest.split()
        if not toks or len(toks) > 2:
            raise ValueError(f"Syntax: {verb} C1 [K1]")
        col_idx = resolve_variables(toks[0], presenter.worksheet, ("number",))[0]
        col = presenter.worksheet.columns[col_idx]
        vals = [
            float(v) for v in col.values
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
        ]
        n_total = len(col.values)
        n_valid = len(vals)
        n_miss = n_total - n_valid
        if verb == "COUNT":
            val = float(n_total)
        elif verb == "N":
            val = float(n_valid)
        elif verb == "NMISS":
            val = float(n_miss)
        elif verb == "SUM":
            val = float(sum(vals))
        else:
            if not vals:
                raise ValueError(f"Column '{col.name}' has no numeric observations for {verb}.")
            if verb == "MEAN":
                val = float(sum(vals) / n_valid)
            elif verb == "STDEV":
                if n_valid < 2:
                    raise ValueError(f"STDEV requires at least 2 numeric observations in '{col.name}'.")
                m_val = sum(vals) / n_valid
                val = math.sqrt(sum((x - m_val) ** 2 for x in vals) / (n_valid - 1))
            elif verb == "MEDIAN":
                s_vals = sorted(vals)
                mid = n_valid // 2
                val = float(s_vals[mid]) if n_valid % 2 else float((s_vals[mid - 1] + s_vals[mid]) / 2.0)
            elif verb == "MINIMUM":
                val = float(min(vals))
            else:
                val = float(max(vals))
        if len(toks) == 2:
            dest_up = toks[1].upper()
            if scope is not None and dest_up in scope.constants:
                scope.constants[dest_up] = val
            elif dest_up.startswith("K") and dest_up[1:].isdigit():
                k_idx = int(dest_up[1:]) - 1
                while len(presenter.worksheet.constants) <= k_idx:
                    next_num = len(presenter.worksheet.constants) + 1
                    presenter.worksheet.constants.append(Column(f"K{next_num}", "number", [None]))
                presenter.worksheet.constants[k_idx].kind = "number"
                presenter.worksheet.constants[k_idx].values = [val]
                presenter.dirty = True
            else:
                raise ValueError(f"Destination '{toks[1]}' must be a stored constant (K1, K2, ...) or macro constant.")
        col_label = col.name or f"C{col_idx + 1}"
        return presenter._record(
            f"{verb} of {col_label}",
            {"column": col_label, "statistic": verb, "value": val, "text": f"{verb} of {col_label} = {val:.6g}"},
        )

    if verb == "PRINT":
        indices = resolve_variables(rest, presenter.worksheet, ("number", "text", "date"))
        if not indices:
            raise ValueError("Syntax: PRINT C1 [C2 ...]")
        sel_cols = [presenter.worksheet.columns[i] for i in indices]
        col_names = [c.name or f"C{i + 1}" for i, c in zip(indices, sel_cols)]
        max_rows = max((len(c.values) for c in sel_cols), default=0)
        lines = ["Row\t" + "\t".join(col_names)]
        for r in range(min(max_rows, 500)):
            row_cells = []
            for c in sel_cols:
                v = c.values[r] if r < len(c.values) else None
                row_cells.append("*" if v is None else str(v))
            lines.append(f"{r + 1}\t" + "\t".join(row_cells))
        formatted_text = "\n".join(lines)
        return presenter._record("Print Data", {"columns": col_names, "text": formatted_text})

    if verb == "READ":
        toks = rest.split()
        col_tokens = []
        inline_rest = []
        for idx_t, tok in enumerate(toks):
            if re.match(r"^C[1-9][0-9]*$", tok, re.IGNORECASE) and not inline_rest:
                col_tokens.append(tok.upper())
            else:
                inline_rest = toks[idx_t:]
                break
        if not col_tokens:
            raise ValueError("Syntax: READ C1 [C2 ...]; row1; row2.")
        col_indices = [int(ct[1:]) - 1 for ct in col_tokens]
        sub_lines = [s for s in subcommands if s.strip() and s.strip().upper() != "END"]
        val_text = " ".join([" ".join(inline_rest)] + sub_lines).strip()
        nums = _parse_number_tokens(val_text)
        n_cols = len(col_indices)
        last_entry = None
        for pos, col_idx in enumerate(col_indices):
            last_entry = presenter.set_column_values(col_idx, nums[pos::n_cols], "number")
        return last_entry

    if verb in ("PCHART", "NPCHART", "CCHART", "UCHART"):
        toks = rest.split()
        if not toks:
            raise ValueError(f"Syntax: {verb} C1 [C2 | subgroup_size]")
        cols = resolve_variables(toks[0], presenter.worksheet, ("number",))
        chart_type = verb[:-5]  # P, NP, C, U
        is_subgroup_col = False
        subgroup_col_idx = None
        subgroup_size = None
        if len(toks) >= 2:
            try:
                subgroup_col_idx = resolve_variables(toks[1], presenter.worksheet, ("number",))[0]
                is_subgroup_col = True
            except ValueError:
                subgroup_size = float(toks[1])
        elif chart_type == "C":
            subgroup_size = 1.0
        return presenter.attribute_control_chart({
            "chart_type": chart_type,
            "variables": [cols[0]],
            "subgroup_size": subgroup_size,
            "subgroup_col_idx": subgroup_col_idx,
            "is_subgroup_col": is_subgroup_col,
            "options": {},
        })

    if verb in ("EWMA", "CUSUM"):
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        if not cols:
            raise ValueError(f"Syntax: {verb} C1")
        return presenter.time_weighted_control_chart({
            "chart_type": verb,
            "columns": [cols[0]],
            "arranged_mode": 0,
            "subgroup_spec": 1,
            "options": {},
        })

    if verb == "PCA":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.pca({"variable_indices": cols, "matrix_type": "correlation"})

    if verb == "FACTOR":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.factor_analysis(variable_columns=cols)

    if verb == "CLUSTER":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.cluster_observations({"variable_indices": cols, "n_clusters": 3})

    if verb == "KMEANS":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        return presenter.cluster_kmeans({"variable_indices": cols, "k_clusters": 3})

    if verb == "ACF":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(cols) != 1:
            raise ValueError("Syntax: ACF C1")
        return presenter.autocorrelation({"series_index": cols[0]})

    if verb == "PACF":
        cols = resolve_variables(rest, presenter.worksheet, ("number",))
        if len(cols) != 1:
            raise ValueError("Syntax: PACF C1")
        return presenter.partial_autocorrelation({"series_index": cols[0]})

    if verb == "ARIMA":
        toks = rest.split()
        if not toks:
            raise ValueError("Syntax: ARIMA [p d q] C1")
        ints = []
        col_parts = []
        for idx_t, tok in enumerate(toks):
            if not col_parts and re.fullmatch(r"\d+", tok):
                ints.append(int(tok))
            else:
                col_parts = toks[idx_t:]
                break
        if not col_parts:
            raise ValueError("Syntax: ARIMA [p d q] C1")
        p = ints[0] if len(ints) >= 1 else 1
        d = ints[1] if len(ints) >= 2 else 0
        q = ints[2] if len(ints) >= 3 else 0
        cols = resolve_variables(" ".join(col_parts), presenter.worksheet, ("number",))
        if len(cols) != 1:
            raise ValueError("Syntax: ARIMA [p d q] C1")
        return presenter.arima({
            "series_index": cols[0],
            "p": p,
            "d": d,
            "q": q,
            "P": 0,
            "D": 0,
            "Q": 0,
            "S": 1,
            "include_constant": True,
            "forecasts": 3,
        })

    raise ValueError(f"Unsupported session command '{verb}'.")


def _resolve_macro_column_arg(arg_tok: str, presenter, caller_scope: Optional[_MacroScope]) -> str:
    resolved = _substitute_scope_tokens(arg_tok, caller_scope).strip()
    if re.match(r"^C[1-9][0-9]*$", resolved, re.IGNORECASE):
        return resolved.upper()
    clean = resolved.strip("'\"")
    for idx, col in enumerate(presenter.worksheet.columns):
        if col.name.strip().casefold() == clean.casefold():
            return f"C{idx + 1}"
    return resolved


def _invoke_macro(
    macro: _MacroDef,
    args_text: str,
    presenter,
    caller_scope: Optional[_MacroScope],
    ctx: _ExecContext,
) -> List[Any]:
    if ctx.depth >= MAX_MACRO_DEPTH:
        raise ValueError(f"Maximum macro recursion depth ({MAX_MACRO_DEPTH}) exceeded.")
    args = _split_macro_args(args_text)
    if len(args) != len(macro.params):
        raise ValueError(
            f"Macro '{macro.name}' expects {len(macro.params)} argument(s), got {len(args)}."
        )
    bindings = {p: a for p, a in zip(macro.params, args)}
    new_scope = _MacroScope(param_bindings=bindings)
    # Pre-bind any params if a global macro or undeclared param is referenced directly
    for p, a in bindings.items():
        if re.match(r"^C[1-9][0-9]*$", a, re.IGNORECASE):
            new_scope.columns[p] = a.upper()
        elif re.match(r"^M[1-9][0-9]*$", a, re.IGNORECASE):
            new_scope.matrices[p] = a.upper()
        else:
            try:
                new_scope.constants[p] = _eval_scalar(a, presenter, caller_scope)
            except ValueError:
                pass

    initial_col_count = len(presenter.worksheet.columns)
    ctx.depth += 1
    try:
        return _exec_statements(macro.body, presenter, new_scope, ctx, caller_scope=caller_scope)
    finally:
        ctx.depth -= 1
        if new_scope.scratch_col_count > 0 and len(presenter.worksheet.columns) > initial_col_count:
            del presenter.worksheet.columns[initial_col_count:]


def _exec_statements(
    stmts: List[Any],
    presenter,
    scope: Optional[_MacroScope],
    ctx: _ExecContext,
    caller_scope: Optional[_MacroScope] = None,
) -> List[Any]:
    from .model import Column

    results: List[Any] = []
    registry = _get_macro_registry(presenter)

    for stmt in stmts:
        if isinstance(stmt, _MacroDefStmt):
            registry[stmt.macro.name] = stmt.macro
            continue

        if isinstance(stmt, _DeclStmt):
            if scope is None:
                raise ValueError(f"{stmt.kind} is only valid inside a MACRO or GMACRO.")
            for name in stmt.names:
                if stmt.kind == "MCONSTANT":
                    if name in scope.param_bindings:
                        scope.constants[name] = _eval_scalar(
                            scope.param_bindings[name], presenter, caller_scope
                        )
                    elif name not in scope.constants:
                        scope.constants[name] = None
                elif stmt.kind == "MCOLUMN":
                    if name in scope.param_bindings:
                        scope.columns[name] = _resolve_macro_column_arg(
                            scope.param_bindings[name], presenter, caller_scope
                        )
                    elif name not in scope.columns:
                        presenter.worksheet.columns.append(
                            Column(f"C{len(presenter.worksheet.columns) + 1}", "number", [])
                        )
                        scope.scratch_col_count += 1
                        scope.columns[name] = f"C{len(presenter.worksheet.columns)}"
                elif stmt.kind == "MMATRIX":
                    if name in scope.param_bindings:
                        scope.matrices[name] = _substitute_scope_tokens(
                            scope.param_bindings[name], caller_scope
                        ).upper()
                    elif name not in scope.matrices:
                        scope.matrices[name] = name
            continue

        if isinstance(stmt, _IfStmt):
            ctx.tick()
            for cond_expr, branch_body in stmt.branches:
                if cond_expr is None or _eval_condition(cond_expr, presenter, scope):
                    results.extend(_exec_statements(branch_body, presenter, scope, ctx, caller_scope))
                    break
            continue

        if isinstance(stmt, _DoStmt):
            start_v = int(round(_eval_scalar(stmt.start_expr, presenter, scope)))
            end_v = int(round(_eval_scalar(stmt.end_expr, presenter, scope)))
            step = 1 if end_v >= start_v else -1
            for val in range(start_v, end_v + step, step):
                ctx.tick()
                if scope is not None and (
                    stmt.var_name in scope.constants or not re.match(r"^K[1-9][0-9]*$", stmt.var_name)
                ):
                    scope.constants[stmt.var_name] = float(val)
                elif re.match(r"^K[1-9][0-9]*$", stmt.var_name):
                    k_idx = int(stmt.var_name[1:]) - 1
                    while len(presenter.worksheet.constants) <= k_idx:
                        next_num = len(presenter.worksheet.constants) + 1
                        presenter.worksheet.constants.append(Column(f"K{next_num}", "number", [None]))
                    presenter.worksheet.constants[k_idx].kind = "number"
                    presenter.worksheet.constants[k_idx].values = [float(val)]
                else:
                    raise ValueError(f"DO loop variable '{stmt.var_name}' must be a K constant or MCONSTANT.")
                results.extend(_exec_statements(stmt.body, presenter, scope, ctx, caller_scope))
            continue

        if isinstance(stmt, _CommandStmt):
            ctx.tick()
            verb, rest = _split_verb_rest(stmt.main_cmd)
            if verb.startswith("%"):
                mac_name = verb[1:].upper()
                if mac_name not in registry:
                    raise ValueError(f"Undefined macro '{mac_name}'.")
                results.extend(_invoke_macro(registry[mac_name], rest, presenter, scope, ctx))
                continue
            if verb not in _BUILTIN_VERBS and verb in registry:
                results.extend(_invoke_macro(registry[verb], rest, presenter, scope, ctx))
                continue
            results.append(execute_command_block(presenter, stmt.main_cmd, stmt.subcommands, scope=scope))

    return results


def execute_script(presenter, script_text: str) -> List[Any]:
    """Parse and run a multi-statement Minitab Exec / session command script."""
    blocks = parse_script_blocks(script_text)
    if not blocks:
        raise ValueError("Script contains no executable session commands.")
    stmts, _, _, _ = _parse_statements(blocks)
    if not stmts:
        raise ValueError("Script contains no executable session commands.")
    ctx = _ExecContext()
    return _exec_statements(stmts, presenter, scope=None, ctx=ctx)
