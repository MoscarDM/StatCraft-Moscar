"""Zero-dependency atomic Excel (.xlsx) worksheet reader for StatCraft."""
from __future__ import annotations

from datetime import datetime
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from zipfile import BadZipFile, ZipFile

from .io import FormatError, MAX_CELLS, MAX_TOTAL_BYTES
from .model import Column, Worksheet, datetime_to_serial, display_date, finite_number, serial_to_datetime

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_BUILTIN_DATE_FMTS = frozenset(range(14, 23)) | frozenset((27, 28, 29, 30, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58))
_DATE_TOKEN_RE = re.compile(r"(?:y{2,4}|m{1,5}|d{1,4}|h{1,2}|s{1,2}|am/pm)", re.IGNORECASE)
_CELL_REF_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")
_XESC_RE = re.compile(r"_x([0-9a-fA-F]{4})_")


def _unescape_x(text: str) -> str:
    return _XESC_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def _col_to_index(col_letters: str) -> int:
    idx = 0
    for ch in col_letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _index_to_col(index: int) -> str:
    """Convert a 0-based column index to an Excel column letter (0 -> 'A')."""
    if index < 0:
        raise ValueError("Column index must be non-negative.")
    letters: List[str] = []
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


_DATE_INPUT_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d-%b-%Y",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
)

_KIND_ALIASES = {
    "auto": None,
    "number": "number",
    "numeric": "number",
    "text": "text",
    "date": "date",
    "date/time": "date",
    "datetime": "date",
}

_KIND_LABELS = {
    "number": "Numeric",
    "text": "Text",
    "date": "Date/Time",
}


def _normalize_kind(kind: Optional[str]) -> Optional[str]:
    if kind is None:
        return None
    key = str(kind).strip().lower()
    if key == "":
        return None
    if key not in _KIND_ALIASES:
        raise FormatError(f"Unsupported column type '{kind}'. Choose Numeric, Text, or Date/Time.")
    return _KIND_ALIASES[key]


def _parse_shared_strings(archive: ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    raw = archive.read("xl/sharedStrings.xml")
    if len(raw) > MAX_TOTAL_BYTES:
        raise FormatError("Excel shared string table exceeds size limit.")
    root = ET.fromstring(raw)
    out: List[str] = []
    for si in root.findall(f"{{{_MAIN_NS}}}si"):
        t_el = si.find(f"{{{_MAIN_NS}}}t")
        if t_el is not None:
            out.append(_unescape_x(t_el.text or ""))
        else:
            parts = [(_unescape_x(r.text or "")) for r in si.findall(f".//{{{_MAIN_NS}}}t")]
            out.append("".join(parts))
    return out


def _parse_date_style_indices(archive: ZipFile) -> set[int]:
    """Identify cellXfs indices that format numbers as Excel serial dates."""
    if "xl/styles.xml" not in archive.namelist():
        return set()
    try:
        root = ET.fromstring(archive.read("xl/styles.xml"))
    except ET.ParseError:
        return set()
    custom_date_fmts: set[int] = set()
    num_fmts = root.find(f"{{{_MAIN_NS}}}numFmts")
    if num_fmts is not None:
        for nf in num_fmts.findall(f"{{{_MAIN_NS}}}numFmt"):
            try:
                fmt_id = int(nf.attrib.get("numFmtId", "-1"))
            except ValueError:
                continue
            code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", nf.attrib.get("formatCode", ""))
            if _DATE_TOKEN_RE.search(code):
                custom_date_fmts.add(fmt_id)
    date_styles: set[int] = set()
    xfs = root.find(f"{{{_MAIN_NS}}}cellXfs")
    if xfs is not None:
        for idx, xf in enumerate(xfs.findall(f"{{{_MAIN_NS}}}xf")):
            try:
                fid = int(xf.attrib.get("numFmtId", "0"))
            except ValueError:
                continue
            if fid in _BUILTIN_DATE_FMTS or fid in custom_date_fmts:
                date_styles.add(idx)
    return date_styles


def _resolve_sheet_targets(archive: ZipFile) -> List[Tuple[str, str]]:
    names = set(archive.namelist())
    if "xl/workbook.xml" not in names:
        raise FormatError("Invalid .xlsx file: missing xl/workbook.xml.")
    wb_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_map: Dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for rel in rels_root:
            if rel.tag.endswith("Relationship"):
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "").lstrip("/")
                if target and not target.startswith("xl/"):
                    target = f"xl/{target}"
                if rid and target:
                    rels_map[rid] = target

    sheets: List[Tuple[str, str]] = []
    for sheet_el in wb_root.findall(f".//{{{_MAIN_NS}}}sheet"):
        title = sheet_el.attrib.get("name", "Sheet")
        rid = sheet_el.attrib.get(f"{{{_REL_NS}}}id", "")
        target = rels_map.get(rid)
        if target and target in names:
            sheets.append((title, target))
    if not sheets:
        fallback = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        sheets = [(f"Sheet{i + 1}", path) for i, path in enumerate(fallback)]
    if not sheets:
        raise FormatError("Excel workbook contains no worksheets.")
    return sheets


def _parse_sheet_grid(
    raw_xml: bytes,
    sheet_name: str,
    shared_strings: List[str],
    date_styles: set[int],
) -> Tuple[Dict[int, Dict[int, Tuple[str, object]]], int, int]:
    if len(raw_xml) > MAX_TOTAL_BYTES:
        raise FormatError(f"Worksheet '{sheet_name}' exceeds XML size limit.")
    root = ET.fromstring(raw_xml)
    grid: Dict[int, Dict[int, Tuple[str, object]]] = {}
    max_row = -1
    max_col = -1
    seq_row = 0
    for row_el in root.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
        r_attr = row_el.attrib.get("r")
        r_idx = (int(r_attr) - 1) if (r_attr and r_attr.isdigit()) else seq_row
        seq_row = max(seq_row + 1, r_idx + 1)
        row_cells = grid.setdefault(r_idx, {})
        seq_col = 0
        for c_el in row_el.findall(f"{{{_MAIN_NS}}}c"):
            ref = c_el.attrib.get("r", "")
            m = _CELL_REF_RE.match(ref)
            if m:
                c_idx = _col_to_index(m.group(1))
                r_idx_cell = int(m.group(2)) - 1
                if r_idx_cell != r_idx:
                    r_idx = r_idx_cell
                    row_cells = grid.setdefault(r_idx, {})
            else:
                c_idx = seq_col
            seq_col = c_idx + 1

            ctype = c_el.attrib.get("t", "")
            style_idx = int(c_el.attrib["s"]) if c_el.attrib.get("s", "").isdigit() else 0
            v_el = c_el.find(f"{{{_MAIN_NS}}}v")
            is_el = c_el.find(f"{{{_MAIN_NS}}}is")
            cell_pair: Optional[Tuple[str, object]] = None
            if ctype == "s":
                if v_el is not None and v_el.text is not None:
                    idx = int(v_el.text)
                    val = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
                    cell_pair = ("text", val)
            elif ctype == "inlineStr":
                if is_el is not None:
                    t_el = is_el.find(f"{{{_MAIN_NS}}}t")
                    txt = _unescape_x(t_el.text or "") if t_el is not None else "".join(
                        _unescape_x(t.text or "") for t in is_el.findall(f".//{{{_MAIN_NS}}}t")
                    )
                    cell_pair = ("text", txt)
            elif ctype in ("str", "e"):
                if v_el is not None and v_el.text is not None:
                    cell_pair = ("text", _unescape_x(v_el.text))
            elif ctype == "b":
                if v_el is not None and v_el.text is not None:
                    cell_pair = ("number", 1.0 if v_el.text.strip() in ("1", "true", "TRUE") else 0.0)
            else:
                if v_el is not None and v_el.text is not None and v_el.text.strip():
                    num = finite_number(float(v_el.text))
                    if style_idx in date_styles:
                        ole_num = num + 1.0 if 1.0 <= num < 61.0 else num
                        cell_pair = ("date", ole_num)
                    else:
                        cell_pair = ("number", num)
            if cell_pair is not None:
                row_cells[c_idx] = cell_pair
                if c_idx > max_col:
                    max_col = c_idx
                if r_idx > max_row:
                    max_row = r_idx
    return grid, max_row, max_col


def _infer_kind(raw_pairs: Sequence[Optional[Tuple[str, object]]]) -> str:
    observed_kinds = {p[0] for p in raw_pairs if p is not None and str(p[1]).strip() != ""}
    if not observed_kinds:
        return "text"
    if "text" in observed_kinds:
        # Try numeric parse in case numeric column arrived stored as text strings
        try:
            for p in raw_pairs:
                if p is not None and p[0] == "text" and str(p[1]).strip() not in ("", "*"):
                    finite_number(float(str(p[1]).strip()))
            return "date" if "date" in observed_kinds else "number"
        except ValueError:
            # Try ISO/common date strings only if every non-empty text cell parses cleanly
            try:
                for p in raw_pairs:
                    if p is not None and str(p[1]).strip() not in ("", "*"):
                        _parse_date_pair(p)
                return "date"
            except ValueError:
                return "text"
    if observed_kinds == {"date"}:
        return "date"
    return "number"


def _parse_date_pair(pair: Tuple[str, object]) -> float:
    raw_kind, raw_val = pair
    if raw_kind == "date":
        val = float(raw_val)
        serial_to_datetime(val)
        return val
    if raw_kind == "number":
        num = finite_number(raw_val)
        ole = num + 1.0 if 1.0 <= num < 61.0 else num
        serial_to_datetime(ole)
        return ole
    s = str(raw_val).strip()
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return datetime_to_serial(dt)
    except ValueError:
        pass
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime_to_serial(datetime.strptime(s, fmt))
        except ValueError:
            continue
    raise ValueError(f"Cannot interpret {s!r} as a Date/Time value.")


def _format_cell_as_text(pair: Tuple[str, object]) -> str:
    raw_kind, raw_val = pair
    if raw_kind == "date":
        return display_date(raw_val)
    if raw_kind == "number":
        num = float(raw_val)
        if num.is_integer():
            return str(int(num))
        return f"{num:.12g}"
    return str(raw_val)


def _coerce_cell(pair: Optional[Tuple[str, object]], kind: str) -> object:
    if pair is None:
        return None
    raw_kind, raw_val = pair
    if kind == "text":
        return _format_cell_as_text(pair)
    if kind == "date":
        if raw_kind == "text" and str(raw_val).strip() in ("", "*"):
            return None
        return _parse_date_pair(pair)
    # Numeric target
    if raw_kind == "text":
        s = str(raw_val).strip()
        if s in ("", "*"):
            return None
        return finite_number(float(s))
    return finite_number(float(raw_val))


def format_preview_cell(value: object, kind: str) -> str:
    if value is None:
        return "*"
    if kind == "date":
        return display_date(value)
    if kind == "number":
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return f"{num:.6g}"
    return str(value)


def infer_sheet_columns(
    sheet_info: dict,
    start_row: int = 1,
    has_header: bool = True,
) -> List[dict]:
    """Infer column names and StatCraft types starting at 1-based ``start_row``."""
    max_row = int(sheet_info.get("max_row", 0))
    max_col = int(sheet_info.get("max_col", 0))
    name = str(sheet_info.get("name", "Sheet"))
    if max_row <= 0 or max_col <= 0:
        return []
    if start_row < 1 or start_row > max_row:
        raise FormatError(
            f"First row to read ({start_row}) is outside '{name}' (valid range: 1 to {max_row})."
        )
    grid: Dict[int, Dict[int, Tuple[str, object]]] = sheet_info["grid"]
    header_row_idx = start_row - 1
    data_start_idx = start_row if has_header else start_row - 1
    header_cells = grid.get(header_row_idx, {})
    descriptors: List[dict] = []
    for c_idx in range(max_col):
        hdr_pair = header_cells.get(c_idx) if has_header else None
        hdr_text = str(hdr_pair[1]).strip() if (hdr_pair and hdr_pair[1] is not None) else ""
        col_name = hdr_text or f"C{c_idx + 1}"
        raw_pairs = [grid.get(r_idx, {}).get(c_idx) for r_idx in range(data_start_idx, max_row)]
        while raw_pairs and raw_pairs[-1] is None:
            raw_pairs.pop()
        inferred = _infer_kind(raw_pairs)
        has_data = bool(hdr_text) or any(
            p is not None and str(p[1]).strip() != "" for p in raw_pairs
        )
        descriptors.append({
            "col_index": c_idx,
            "letter": _index_to_col(c_idx),
            "name": col_name,
            "raw_header": hdr_text,
            "inferred_kind": inferred,
            "has_data": has_data,
        })
    return descriptors


def build_worksheet_from_sheet_info(
    sheet_info: dict,
    *,
    start_row: int = 1,
    has_header: bool = True,
    included_columns: Optional[Sequence[int]] = None,
    column_types: Optional[Dict[int, Optional[str]] | Sequence[Optional[str]]] = None,
    strict: bool = True,
) -> Worksheet:
    """Build a StatCraft ``Worksheet`` from inspected sheet data and import options."""
    sheet_name = str(sheet_info.get("name", "Sheet"))
    max_row = int(sheet_info.get("max_row", 0))
    max_col = int(sheet_info.get("max_col", 0))
    if max_row <= 0 or max_col <= 0:
        raise FormatError(f"Worksheet '{sheet_name}' is empty and has no rows to import.")
    if start_row < 1 or start_row > max_row:
        raise FormatError(
            f"First row to read ({start_row}) is outside '{sheet_name}' (valid range: 1 to {max_row})."
        )

    descriptors = infer_sheet_columns(sheet_info, start_row=start_row, has_header=has_header)
    if included_columns is None:
        target_indices = [d["col_index"] for d in descriptors]
    else:
        seen = set()
        target_indices = []
        for idx in included_columns:
            if 0 <= idx < max_col and idx not in seen:
                seen.add(idx)
                target_indices.append(idx)
    if not target_indices:
        raise FormatError(f"Select at least one column to import from '{sheet_name}'.")

    data_start_idx = start_row if has_header else start_row - 1
    n_data_rows = max(0, max_row - data_start_idx)
    if max(1, n_data_rows) * len(target_indices) > MAX_CELLS:
        raise FormatError(f"Worksheet '{sheet_name}' exceeds the maximum cell budget.")

    if isinstance(column_types, dict):
        type_map = {int(k): _normalize_kind(v) for k, v in column_types.items()}
    elif column_types is not None:
        if len(column_types) == max_col:
            type_map = {i: _normalize_kind(t) for i, t in enumerate(column_types)}
        elif len(column_types) == len(target_indices):
            type_map = {c_idx: _normalize_kind(t) for c_idx, t in zip(target_indices, column_types)}
        else:
            raise FormatError("Specify one type per column.")
    else:
        type_map = {}

    grid: Dict[int, Dict[int, Tuple[str, object]]] = sheet_info["grid"]
    columns: List[Column] = []
    for out_idx, c_idx in enumerate(target_indices):
        desc = descriptors[c_idx]
        col_name = desc["raw_header"] or f"C{out_idx + 1}"
        kind = type_map.get(c_idx) or desc["inferred_kind"]
        raw_pairs = [grid.get(r_idx, {}).get(c_idx) for r_idx in range(data_start_idx, max_row)]
        while raw_pairs and raw_pairs[-1] is None:
            raw_pairs.pop()

        values = []
        for offset, p in enumerate(raw_pairs):
            src_row = data_start_idx + offset + 1
            try:
                values.append(_coerce_cell(p, kind))
            except (ValueError, TypeError, OverflowError) as exc:
                if strict:
                    raw_display = p[1] if p is not None else ""
                    label = _KIND_LABELS.get(kind, kind)
                    raise FormatError(
                        f"Sheet '{sheet_name}', column {desc['letter']} ({col_name}), "
                        f"row {src_row}: cannot convert {raw_display!r} to {label}."
                    ) from exc
                values.append(None)
        columns.append(Column(col_name, kind, values))

    return Worksheet(
        sheet_name,
        columns,
        metadata={
            "import": {
                "format": "xlsx",
                "start_row": int(start_row),
                "has_header": bool(has_header),
            }
        },
    )


def _sheet_info_from_xml(
    raw_xml: bytes,
    sheet_name: str,
    sheet_index: int,
    shared_strings: List[str],
    date_styles: set[int],
) -> dict:
    grid, max_row_idx, max_col_idx = _parse_sheet_grid(raw_xml, sheet_name, shared_strings, date_styles)
    n_rows = max_row_idx + 1 if max_row_idx >= 0 else 0
    n_cols = max_col_idx + 1 if max_col_idx >= 0 else 0
    raw_rows: List[List[object]] = []
    for r_idx in range(n_rows):
        row_cells = grid.get(r_idx, {})
        raw_rows.append([
            row_cells[c_idx][1] if c_idx in row_cells else None
            for c_idx in range(n_cols)
        ])
    return {
        "name": sheet_name,
        "sheet_index": sheet_index,
        "grid": grid,
        "raw_rows": raw_rows,
        "max_row": n_rows,
        "max_col": n_cols,
        "column_letters": [_index_to_col(c) for c in range(n_cols)],
    }


def inspect_xlsx(path: str | Path) -> dict:
    """Inspect an Excel .xlsx workbook cleanly before importing selected sheets."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Excel file not found: {p}")
    if p.stat().st_size > MAX_TOTAL_BYTES:
        raise FormatError("Excel workbook exceeds the maximum file size limit.")
    try:
        with ZipFile(p, "r") as archive:
            shared = _parse_shared_strings(archive)
            date_styles = _parse_date_style_indices(archive)
            targets = _resolve_sheet_targets(archive)
            sheets = [
                _sheet_info_from_xml(archive.read(member), name, idx, shared, date_styles)
                for idx, (name, member) in enumerate(targets)
            ]
            return {"path": str(p), "filename": p.name, "sheets": sheets}
    except BadZipFile as exc:
        raise FormatError(f"'{p.name}' is not a valid .xlsx workbook.") from exc


def load_xlsx_with_options(
    path: str | Path,
    sheet_options: Sequence[dict],
) -> List[Worksheet]:
    """Import selected .xlsx sheets using per-sheet row, header, and type options."""
    info = inspect_xlsx(path)
    sheets_by_name = {s["name"]: s for s in info["sheets"]}
    sheets_by_idx = {s["sheet_index"]: s for s in info["sheets"]}
    worksheets: List[Worksheet] = []
    for opt in sheet_options:
        if not opt.get("import_sheet", True):
            continue
        sheet_info = None
        if "sheet_index" in opt and opt["sheet_index"] in sheets_by_idx:
            sheet_info = sheets_by_idx[opt["sheet_index"]]
        elif "name" in opt and opt["name"] in sheets_by_name:
            sheet_info = sheets_by_name[opt["name"]]
        if sheet_info is None:
            raise FormatError(f"Worksheet option refers to unknown sheet: {opt.get('name', opt.get('sheet_index'))}.")
        worksheets.append(
            build_worksheet_from_sheet_info(
                sheet_info,
                start_row=int(opt.get("start_row", 1)),
                has_header=bool(opt.get("has_header", True)),
                included_columns=opt.get("included_columns"),
                column_types=opt.get("column_types"),
                strict=bool(opt.get("strict", True)),
            )
        )
    if not worksheets:
        raise FormatError("Select at least one worksheet to import.")
    return worksheets


def _parse_sheet_xml(
    raw_xml: bytes,
    sheet_name: str,
    shared_strings: List[str],
    date_styles: set[int],
    has_header: bool = True,
    column_types: Optional[List[str]] = None,
) -> Worksheet:
    grid, max_row_idx, max_col_idx = _parse_sheet_grid(raw_xml, sheet_name, shared_strings, date_styles)
    if max_row_idx < 0 or max_col_idx < 0:
        return Worksheet(sheet_name)

    n_cols = max_col_idx + 1
    data_start = 1 if has_header else 0
    n_data_rows = max(0, max_row_idx + 1 - data_start)
    if max(1, n_data_rows) * n_cols > MAX_CELLS:
        raise FormatError(f"Worksheet '{sheet_name}' exceeds the maximum cell budget.")
    if column_types is not None and len(column_types) != n_cols:
        raise FormatError("Specify one type per column.")

    header_cells = grid.get(0, {})
    columns: List[Column] = []
    for c_idx in range(n_cols):
        if has_header:
            hdr_pair = header_cells.get(c_idx)
            hdr = str(hdr_pair[1]).strip() if (hdr_pair and hdr_pair[1] is not None) else ""
        else:
            hdr = ""
        col_name = hdr or f"C{c_idx + 1}"

        raw_pairs = [grid.get(r_idx, {}).get(c_idx) for r_idx in range(data_start, max_row_idx + 1)]
        while raw_pairs and raw_pairs[-1] is None:
            raw_pairs.pop()

        explicit_kind = _normalize_kind(column_types[c_idx]) if column_types is not None else None
        kind = explicit_kind if explicit_kind is not None else _infer_kind(raw_pairs)
        values = [_coerce_cell(p, kind) for p in raw_pairs]
        columns.append(Column(col_name, kind, values))

    return Worksheet(sheet_name, columns, metadata={"import": {"format": "xlsx"}})


def load_xlsx(
    path: str | Path,
    sheet_name: Optional[str] = None,
    has_header: bool = True,
    column_types: Optional[List[str]] = None,
) -> List[Worksheet]:
    """Read one or all worksheets cleanly from an Excel .xlsx workbook."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Excel file not found: {p}")
    if p.stat().st_size > MAX_TOTAL_BYTES:
        raise FormatError("Excel workbook exceeds the maximum file size limit.")
    try:
        with ZipFile(p, "r") as archive:
            shared = _parse_shared_strings(archive)
            date_styles = _parse_date_style_indices(archive)
            targets = _resolve_sheet_targets(archive)
            if sheet_name is not None:
                targets = [(name, member) for name, member in targets if name == sheet_name]
                if not targets:
                    raise FormatError(f"Worksheet '{sheet_name}' not found in '{p.name}'.")
            worksheets: List[Worksheet] = []
            for name, member in targets:
                raw_xml = archive.read(member)
                worksheets.append(_parse_sheet_xml(raw_xml, name, shared, date_styles, has_header, column_types))
            return worksheets
    except BadZipFile as exc:
        raise FormatError(f"'{p.name}' is not a valid .xlsx workbook.") from exc
