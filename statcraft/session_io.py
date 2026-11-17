"""Session, history, autosave recovery, and navigator ordering helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from .model import Column, Matrix, Worksheet

AUTOSAVE_SCHEMA = "statcraft.autosave"
AUTOSAVE_VERSION = 1

_VALID_EXPORT_FORMATS = {"html", "txt"}
_VALID_NAVIGATOR_MODES = {"chronological", "worksheet", "title"}


def _atomic_write_text(path: Path, text: str) -> Path:
    """Atomically write UTF-8 text to *path*, preserving any existing file on error."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=".statcraft-",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _json_safe(value: Any) -> Any:
    """Convert nested structures into JSON-serializable values without NaN/Inf."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    item_fn = getattr(value, "item", None)
    if callable(item_fn):
        return _json_safe(item_fn())
    return str(value)


def _render_entry_text(entry: dict) -> str:
    """Render a session entry dict to plain text."""
    if "result" in entry and entry["result"] is not None:
        try:
            from .app import format_entry

            return format_entry(entry)
        except Exception:
            pass
    title = str(entry.get("title") or "Analysis")
    time_str = str(entry.get("time") or entry.get("timestamp") or "")
    header = title + ("\n" + time_str if time_str else "")
    divider = "─" * 76
    body = entry.get("text") or entry.get("body") or entry.get("output") or ""
    if body:
        return f"{header}\n{divider}\n\n{body}"
    return f"{header}\n{divider}"


def export_history_script(lines: list[str], path: Path) -> Path:
    """Export command history lines to an executable script file (``.mtb`` / ``.txt``)."""
    cleaned = [str(line).rstrip("\r\n") for line in lines]
    content = ("\n".join(cleaned) + "\n") if cleaned else ""
    return _atomic_write_text(Path(path), content)


def export_session_window(entries: list[dict], path: Path, fmt: str = "html") -> Path:
    """Export session window entries to ``.html`` or ``.txt``."""
    fmt_norm = str(fmt).strip().lower().lstrip(".")
    if fmt_norm not in _VALID_EXPORT_FORMATS:
        raise ValueError(f"Unsupported session export format: {fmt!r}")

    target = Path(path)
    if fmt_norm == "txt":
        blocks = [_render_entry_text(entry) for entry in entries]
        content = ("\n\n".join(blocks) + "\n") if blocks else ""
        return _atomic_write_text(target, content)

    sections: list[str] = []
    for entry in entries:
        title = html.escape(str(entry.get("title") or "Analysis"))
        meta_parts = [
            str(part)
            for part in (entry.get("time") or entry.get("timestamp"), entry.get("worksheet"))
            if part
        ]
        meta_html = (
            f'<div class="meta">{html.escape(" · ".join(meta_parts))}</div>'
            if meta_parts
            else ""
        )
        rendered = _render_entry_text(entry)
        sections.append(
            f'<section class="session-entry">'
            f"<h2>{title}</h2>"
            f"{meta_html}"
            f"<pre>{html.escape(rendered)}</pre>"
            f"</section>"
        )

    body_html = (
        "\n".join(sections)
        if sections
        else '<p class="empty">No session entries.</p>'
    )
    document = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>StatCraft Session Window</title>\n"
        "<style>\n"
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "margin: 24px; color: #0f172a; background: #ffffff; }\n"
        ".session-entry { border: 1px solid #e2e8f0; border-radius: 6px; "
        "padding: 16px; margin-bottom: 16px; background: #f8fafc; }\n"
        ".session-entry h2 { margin: 0 0 6px 0; font-size: 16px; }\n"
        ".session-entry .meta { font-size: 12px; color: #64748b; margin-bottom: 10px; }\n"
        ".session-entry pre { margin: 0; font-family: Consolas, 'Courier New', monospace; "
        "font-size: 13px; white-space: pre-wrap; }\n"
        ".empty { color: #64748b; font-style: italic; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>\n"
    )
    return _atomic_write_text(target, document)


def _serialize_column(col: Column) -> dict[str, Any]:
    return {
        "name": col.name,
        "kind": col.kind,
        "values": list(col.values),
        "metadata": _json_safe(col.metadata),
    }


def _serialize_worksheet(worksheet: Worksheet | None) -> dict[str, Any] | None:
    if worksheet is None:
        return None
    worksheet.validate()
    return {
        "name": worksheet.name,
        "columns": [_serialize_column(c) for c in worksheet.columns],
        "constants": [_serialize_column(c) for c in worksheet.constants],
        "matrices": [
            {
                "name": m.name,
                "rows": m.rows,
                "columns": m.columns,
                "values": list(m.values),
                "metadata": _json_safe(m.metadata),
            }
            for m in worksheet.matrices
        ],
        "metadata": _json_safe(worksheet.metadata),
    }


def autosave_snapshot(worksheet: Worksheet | None, history: list[Any], path: Path) -> Path:
    """Atomically write an autosave crash-recovery snapshot of *worksheet* and *history*."""
    payload = {
        "schema": AUTOSAVE_SCHEMA,
        "version": AUTOSAVE_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "worksheet": _serialize_worksheet(worksheet),
        "history": _json_safe(list(history or [])),
    }
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    return _atomic_write_text(Path(path), raw)


def load_autosave_snapshot(path: Path) -> dict | None:
    """Load and validate an autosave snapshot, returning ``None`` if missing or corrupt."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != AUTOSAVE_SCHEMA
            or payload.get("version") != AUTOSAVE_VERSION
        ):
            return None
        ws_raw = payload.get("worksheet")
        worksheet: Worksheet | None = None
        if ws_raw is not None:
            if not isinstance(ws_raw, dict):
                return None
            worksheet = Worksheet(
                ws_raw["name"],
                [Column(**c) for c in ws_raw.get("columns", [])],
                [Column(**c) for c in ws_raw.get("constants", [])],
                [Matrix(**m) for m in ws_raw.get("matrices", [])],
                ws_raw.get("metadata", {}),
            )
        history_raw = payload.get("history", [])
        if not isinstance(history_raw, list):
            return None
        return {
            "schema": payload["schema"],
            "version": payload["version"],
            "saved_at": payload.get("saved_at"),
            "worksheet": worksheet,
            "history": history_raw,
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None


def clear_autosave_snapshot(path: Path) -> None:
    """Remove an autosave snapshot file if it exists."""
    Path(path).unlink(missing_ok=True)


def order_navigator_entries(entries: list[dict], mode: str = "chronological") -> list[dict]:
    """Return a new list of Navigator entries ordered by ``chronological``, ``worksheet``, or ``title``."""
    mode_norm = str(mode).strip().lower()
    if mode_norm not in _VALID_NAVIGATOR_MODES:
        raise ValueError(f"Unsupported navigator order mode: {mode!r}")
    if mode_norm == "chronological":
        return list(entries)
    if mode_norm == "worksheet":
        return sorted(
            entries,
            key=lambda entry: (
                0 if entry.get("worksheet") else 1,
                str(entry.get("worksheet") or "").casefold(),
            ),
        )
    return sorted(
        entries,
        key=lambda entry: str(entry.get("title") or "").casefold(),
    )
