"""Qt-free bridge between the browser UI and the StatCraft engines.

The browser (running inside Pyodide) calls ``run(analysis, payload_json)`` and gets back a JSON
string.  Nothing here imports PySide6, so it runs identically in CPython and in Pyodide.

payload = {
    "columns": [{"name": str, "kind": "number" | "text", "values": [number | string | null, ...]}],
    "options": {...analysis specific...}
}
Column references in ``options`` are zero-based indexes into ``columns``.
"""
import json
import math

from statcraft.model import Column, Worksheet


def _clean(value):
    """Make engine output JSON-safe (NaN/inf -> null, sets/tuples -> lists, numpy -> python)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(v) for v in (sorted(value) if isinstance(value, (set, frozenset)) else value)]
    if hasattr(value, "item") and callable(value.item):  # numpy scalar
        return _clean(value.item())
    if hasattr(value, "tolist") and callable(value.tolist):  # numpy array
        return _clean(value.tolist())
    return value


def _worksheet(payload):
    columns = []
    for raw in payload.get("columns", []):
        kind = "text" if raw.get("kind") == "text" else "number"
        values = []
        for v in raw.get("values", []):
            if v is None or (isinstance(v, str) and v.strip() == ""):
                values.append(None)
            elif kind == "number":
                values.append(float(v))
            else:
                values.append(str(v))
        columns.append(Column(str(raw.get("name") or "C%d" % (len(columns) + 1)), kind, values))
    return Worksheet("Worksheet", columns)


def _numbers(ws, index):
    if not 0 <= index < len(ws.columns):
        raise ValueError("Select a valid column.")
    col = ws.columns[index]
    if col.kind != "number":
        raise ValueError('Column "%s" must be numeric.' % col.name)
    return col.name, list(col.values)


def _describe(ws, opts):
    from statcraft.analyses import describe

    items = []
    for index in opts.get("columns") or [i for i, c in enumerate(ws.columns) if c.kind == "number"]:
        name, values = _numbers(ws, index)
        items.append({"name": name, "stats": describe(values)})
    if not items:
        raise ValueError("Select at least one numeric column.")
    return {"graph": "describe", "items": items}


def _histogram(ws, opts):
    from statcraft import histograms

    return histograms.compute(
        ws, [int(opts["column"])], bins=int(opts.get("bins", 10)), fit_normal=bool(opts.get("fit_normal", False))
    )


def _boxplot(ws, opts):
    from statcraft import boxplot_graphs

    resp = [int(i) for i in opts["columns"]]
    args = {"response_indices": resp}
    multi = len(resp) > 1
    grouped = opts.get("group") not in (None, "", -1)
    variants = getattr(boxplot_graphs, "VARIANTS", ())
    if grouped:
        args["group_indices"] = [int(opts["group"])]
        args["variant"] = "multiple_groups" if multi else "one_groups"
    else:
        args["variant"] = "multiple" if multi else "one"
    if variants and args["variant"] not in variants:
        args["variant"] = "one"
    return boxplot_graphs.build_boxplots(ws, **args)


def _scatter(ws, opts):
    from statcraft import scatter

    mode = opts.get("mode", "simple")
    group = opts.get("group")
    group = None if group in (None, "", -1) else int(group)
    return scatter.build(ws, int(opts["x"]), int(opts["y"]), mode=mode, group_index=group)


def _run_chart(ws, opts):
    from statcraft.run_chart import run_chart

    name, values = _numbers(ws, int(opts["column"]))
    result = run_chart(values, int(opts.get("subgroup_size", 1)))
    result.update({"graph": "run_chart", "variable_name": name})
    return result


def _imr(ws, opts):
    from statcraft.imr_engine import run_imr_chart

    name, values = _numbers(ws, int(opts["column"]))
    settings = {k: v for k, v in opts.items() if k not in ("column",)}
    return run_imr_chart(values, settings, name)


def _pareto(ws, opts):
    from statcraft.pareto_engine import run_pareto_chart

    defect = ws.columns[int(opts["defect"])]
    count = opts.get("count")
    counts = None
    if count not in (None, "", -1):
        _, counts = _numbers(ws, int(count))
    result = run_pareto_chart(
        list(defect.values),
        counts,
        combine_percent=float(opts.get("combine_percent", 95.0)),
        variable_name=defect.name,
    )
    result["graph"] = "pareto"
    return result


ANALYSES = {
    "describe": _describe,
    "histogram": _histogram,
    "boxplot": _boxplot,
    "scatter": _scatter,
    "run_chart": _run_chart,
    "imr": _imr,
    "pareto": _pareto,
}


def run(analysis, payload_json):
    """Entry point called from JavaScript. Always returns a JSON string, never raises."""
    try:
        payload = json.loads(payload_json)
        if analysis not in ANALYSES:
            raise ValueError("Unknown analysis: %s" % analysis)
        ws = _worksheet(payload)
        result = ANALYSES[analysis](ws, payload.get("options") or {})
        result = _clean(result)
        result.setdefault("graph", analysis)
        return json.dumps({"ok": True, "analysis": analysis, "result": result})
    except Exception as exc:  # surfaced to the UI as a readable message
        return json.dumps({"ok": False, "analysis": analysis, "error": "%s: %s" % (type(exc).__name__, exc)})
