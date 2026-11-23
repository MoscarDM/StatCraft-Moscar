
"""End-to-end verification for everyday analysis workflows."""
from itertools import product
from json import dumps
from math import isclose, sqrt
from statistics import mean, stdev, variance

from .app import Presenter
from .graph_frame import GraphFrame


def export_graph(window, entry, path, tab="Graph"):
    window.show_result(entry, target_tab=tab)
    page = window.result_tabs.currentWidget()
    frame = page.content.findChild(GraphFrame)
    if window.result_tabs.tabText(window.result_tabs.currentIndex()) != tab or frame is None:
        raise RuntimeError(f"Could not open {tab} for {entry['title']}")
    if getattr(frame.chart, "error", None):
        raise RuntimeError(f"Could not render {entry['title']}: {frame.chart.error}")
    if not frame.capture().save(str(path), "PNG"):
        raise RuntimeError(f"Could not export {path.name}")
    return frame.chart


def verify_saved_results(window, path, entries):
    presenter = window.presenter
    presenter.workspace = window._workspace.snapshot()
    presenter.save(path)
    restored = Presenter()
    restored.load(path)
    for entry in entries:
        saved = next(item for item in restored.history if item["entry_id"] == entry["entry_id"])
        if saved["recipe"] != entry["recipe"] or dumps(saved["result"], sort_keys=True) != dumps(entry["result"], sort_keys=True):
            raise RuntimeError(f"Saved analysis changed: {entry['title']}")
        rerun = restored.rerun_result(saved)
        if dumps(rerun["result"], sort_keys=True) != dumps(saved["result"], sort_keys=True):
            raise RuntimeError(f"Rerun changed: {entry['title']}")


def verify_fractional_graphs(window, folder):
    p = window.presenter
    factors = [dict(name=name, low=-1, high=1) for name in "ABCD"]
    p.create_factorial(factors, generators={"D": "ABC"}, replicates=2, seed=42)
    p.add_column("Response")
    for row in range(p.worksheet.row_count):
        order, _, _, _, a, b, c, d, _ = p.worksheet.row(row)
        error = 1 if order <= 8 else -1
        p.set_cell(row, 8, str(10 + 2*a - 3*b + 1.5*c + .5*d + error))
    window.refresh()

    fit = p.analyze_factorial(8, [4, 5, 6, 7], max_order=1)
    effects = p.factorial_plots(fit["recipe"], options={"show_interaction_plot": False})
    export_graph(window, fit, folder / "fractional-pareto.png", "Effects Pareto")
    export_graph(window, fit, folder / "fractional-residuals.png", "Residual Plots")
    export_graph(window, effects, folder / "fractional-main-effects.png")
    verify_saved_results(window, folder / "fractional.mpx", (fit, effects))
    return 3


def verify_central_composite(window, folder):
    from .model import Column
    from .model_plot_dialogs import ModelContourPlotDialog, ModelSurfacePlotDialog
    from .response_surface_dialogs import AnalyzeSurfaceDialog

    p = window.presenter
    p.new()
    factors = [dict(name="Heat", low=100, high=140), dict(name="Time", low=20, high=40)]
    p.create_response_surface(factors, centers=5, alpha_mode="face", seed=17)
    sheet = p.worksheet
    offsets = [-.2, -.1, 0, .1, .2]

    def expected(heat, time):
        a = (heat - 120) / 20
        b = (time - 30) / 10
        return 20 + 2*a - 3*b + 4*a*a + 2*b*b + a*b

    measurements = []
    for order, _, _, _, heat, time in zip(*(column.values for column in sheet.columns), strict=True):
        deviation = offsets[int(order) - 9] if heat == 120 and time == 30 else 0
        measurements.append(expected(heat, time) + deviation)
    sheet.columns.append(Column("Yield", values=measurements))
    window.refresh()
    dialog = AnalyzeSurfaceDialog(window)
    dialog.controls["response_index"].setText("Yield")
    dialog.validate()
    fit = dialog.entry
    if fit is None:
        raise RuntimeError(dialog.error.text())
    result = fit["result"]
    if (result["count"], result["df_error"], result["pure_error"]["df"]) != (13, 7, 4):
        raise RuntimeError("Unexpected central composite count or degrees of freedom")
    for actual, target in zip(result["coefficients"], (20, 2, -3, 4, 2, 1), strict=True):
        if not isclose(actual["estimate"], target, abs_tol=1e-10):
            raise RuntimeError(f"Incorrect response surface coefficient: {actual}")

    graphs = []
    panels = []
    for dialog_type, kind in ((ModelContourPlotDialog, "contour"), (ModelSurfacePlotDialog, "surface")):
        plot = dialog_type(window, "response_surface")
        plot.validate()
        if plot.entry is None:
            raise RuntimeError(plot.error.text())
        graph = plot.entry
        graphs.append(graph)
        export_graph(window, graph, folder / f"response-{kind}.png")
        panel, = graph["result"]["panels"]
        if (panel["x_name"], panel["y_name"]) != ("Heat", "Time"):
            raise RuntimeError(f"Unexpected axis labels for {kind}")
        panels.append(panel)

    contour, surface = panels
    # 41 and 25 evenly spaced coordinates coincide every fifth and third step.
    points = [(surface["x_grid"][x], surface["y_grid"][y]) for y in range(0, 25, 3) for x in range(0, 25, 3)]
    prediction = p.predict_model(fit["recipe"], values=[list(point) for point in points])
    for index, (point, row) in enumerate(zip(points, prediction["result"]["rows"], strict=True)):
        y, x = divmod(index, 9)
        target = expected(*point)
        if not all(isclose(value, target, abs_tol=1e-10) for value in (
            contour["z_grid"][y*5][x*5], surface["z_grid"][y*3][x*3], row["fit"]
        )):
            raise RuntimeError(f"Prediction and plotted values disagree at {point}")

    window.show_result(graphs[-1])
    verify_saved_results(window, folder / "response-surface.mpx", (fit, *graphs, prediction))
    return len(points)


def verify_standard_regression(window, folder):
    from scipy import stats

    from .fitted_line_plot_dialog import FittedLinePlotDialog
    from .model import Column, Worksheet
    from .regression_dialog import FitRegressionModelDialog

    p = window.presenter
    p.new()
    rows = [(a, b, c) for a, b, c in product((-1, 1), repeat=3)]
    response = [10 + 2*a - 3*b + 4*(c == 1) + a*b*c for a, b, c in rows]
    x = list(range(-3, 5))
    line = [7 + 2*v + e for v, e in zip(x, (1, -1, -1, 1, 1, -1, -1, 1), strict=True)]

    def with_gap(values):
        values = list(values)
        return values[:2] + [None] + values[2:]

    p.worksheet = Worksheet("Regression verification", [
        Column("Factor A", values=with_gap(a for a, _, _ in rows)),
        Column("Factor B", values=with_gap(b for _, b, _ in rows)),
        Column("Shift", "text", with_gap("Late" if c == 1 else "Early" for _, _, c in rows)),
        Column("Yield", values=with_gap(response)),
        Column("Calibration", values=with_gap(x)),
        Column("Reading", values=with_gap(line)),
        Column("Duplicate A", values=with_gap(a for a, _, _ in rows)),
    ])
    window.refresh()
    dialog = FitRegressionModelDialog(window)
    dialog.controls["response_index"].setText("C4")
    dialog.controls["predictor_indices"].setText("C1 C7")
    dialog.validate()
    if dialog.entry is not None or "rank" not in dialog.error.text().lower() or p.history:
        raise RuntimeError("Collinear predictors should fail without creating a result")
    dialog.controls["predictor_indices"].setText("C1 C2")
    dialog.controls["categorical_indices"].setText("C3")
    dialog.options["graphs"] = "four"
    dialog.options["results"]["equation"] = False
    dialog.validate()
    fit = dialog.entry
    if fit is None:
        raise RuntimeError(dialog.error.text())
    result = fit["result"]
    if result["categorical_predictors"][0]["reference"] != "Early":
        raise RuntimeError("Unexpected categorical reference level")
    for row, coeff, se in zip(result["coefficients"], (10, 2, -3, 4), (sqrt(.5), .5, .5, 1), strict=True):
        require_close(row["estimate"], coeff, "regression coefficient")
        require_close(row["standard_error"], se, "coefficient standard error")
    if (result["df_regression"], result["df_error"], result["missing"]) != (3, 4, 1):
        raise RuntimeError("Unexpected regression degrees of freedom or missing count")
    require_close(result["ss_error"], 8, "residual sum of squares")
    require_close(result["ss_regression"], 136, "regression sum of squares")
    require_close(result["r_squared"], 136/144, "R-squared")
    require_close(result["f"], (136/3)/2, "regression F test")

    prediction = p.predict_model(fit["recipe"], values=[[0, 0, "Early"]])
    estimate, = prediction["result"]["rows"]
    critical = stats.t.ppf(.975, 4)
    require_close(estimate["fit"], 10, "categorical regression prediction")
    require_close(estimate["ci_low"], 10 - critical*sqrt(.5), "mean confidence limit")
    require_close(estimate["pi_high"], 10 + critical*sqrt(2.5), "individual prediction limit")

    diagnostics = export_graph(window, fit, folder / "regression-residuals.png")
    kept = [1, 2, 4, 5, 6, 7, 8, 9]
    if diagnostics.observation_order != kept:
        raise RuntimeError("Regression residuals lost their original worksheet rows")
    for index, (a, b, c) in enumerate(rows):
        require_close(diagnostics.fitted[index], 10 + 2*a - 3*b + 4*(c == 1), "plotted fitted value")
        require_close(diagnostics.std_resids[index], a*b*c, "plotted standardized residual")

    line_dialog = FittedLinePlotDialog(window)
    line_dialog.controls["response_index"].setText("C6")
    line_dialog.controls["predictor_index"].setText("C5")
    line_dialog.chk_show_ci.setChecked(True)
    line_dialog.chk_show_pi.setChecked(True)
    line_dialog.options["graphs"] = "four"
    line_dialog.validate()
    line_fit = line_dialog.entry
    if line_fit is None:
        raise RuntimeError(line_dialog.error.text())

    line_graph = export_graph(window, line_fit, folder / "fitted-line.png")
    if not line_graph.show_ci or not line_graph.show_pi:
        raise RuntimeError("The fitted-line graph hid requested intervals")
    variance = 8/6
    critical = stats.t.ppf(.975, 6)
    for index, v in enumerate(line_graph.curve_x):
        center = 7 + 2*v
        leverage = 1/8 + (v - .5)**2/42
        mean_margin = critical*sqrt(variance*leverage)
        pred_margin = critical*sqrt(variance*(1 + leverage))
        for actual, expected in (
            (line_graph.curve_fit[index], center),
            (line_graph.curve_ci_low[index], center - mean_margin),
            (line_graph.curve_ci_high[index], center + mean_margin),
            (line_graph.curve_pi_low[index], center - pred_margin),
            (line_graph.curve_pi_high[index], center + pred_margin),
        ):
            require_close(actual, expected, "fitted line or interval")
    diagnostics = export_graph(window, line_fit, folder / "line-residuals.png", "Residual Plots")
    if diagnostics.observation_order != kept or diagnostics.response_name != "Reading":
        raise RuntimeError("Fitted-line residuals lost the response label or original worksheet rows")

    window.show_result(line_fit, target_tab="Graph")
    verify_saved_results(window, folder / "standard-regression.mpx", (fit, line_fit, prediction))
    return kept, len(line_graph.curve_x)


def require_close(actual, expected, label):
    if not isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise RuntimeError(f"{label}: expected {expected}, got {actual}")


def verify_basic_statistics(window, folder):
    from scipy import stats

    from .model import Column, Worksheet
    from .oneway_dialogs import OneWayAnovaDialog

    p = window.presenter
    p.new()
    before = [2, 2, 3, None, 4, 5, 6, 7, 30]
    after = [1, 2, None, 4, 3, 4, 5, 6]
    p.worksheet = Worksheet("Basic statistics verification", [
        Column("Before", values=before),
        Column("After", values=after),
        Column("Strength", values=[3, 4, 4, None, 7, 8, 9, 18, 20]),
        Column("Batch", "text", ["A"]*4 + ["B"]*3 + ["C"]*2),
    ])
    window.refresh()
    first = [value for value in before if value is not None]
    second = [value for value in after if value is not None]
    pairs = [(a, b) for a, b in zip(before, after) if a is not None and b is not None]
    paired_before, paired_after = zip(*pairs)

    descriptive = p.describe_columns([0], graphs={"histogram": True, "boxplot": True})
    summary, = descriptive["result"]["columns"]
    if (summary["count"], summary["missing"], summary["median"]) != (8, 1, 4.5):
        raise RuntimeError("Incorrect descriptive counts or median")
    require_close(summary["mean"], 59/8, "descriptive mean")
    export_graph(window, descriptive, folder / "descriptive-summary.png")

    one_sample = p.one_sample_t({"sample_cols": [0], "hypothesized_mean": 5})
    sample, = one_sample["result"]["samples"]
    if sample["n"] != 8:
        raise RuntimeError("One-sample t used the wrong observations")
    check_t_test(sample, stats.ttest_1samp(first, 5), len(first) - 1, mean(first), stdev(first)/sqrt(len(first)))

    two_sample = p.two_sample_t({"sample1_col": 0, "sample2_col": 1})
    welch = two_sample["result"]
    if (welch["sample1"]["n"], welch["sample2"]["n"]) != (8, 7):
        raise RuntimeError("Welch's t used the wrong observations")
    first_var, second_var = variance(first)/len(first), variance(second)/len(second)
    welch_df = (first_var + second_var)**2 / (first_var**2/(len(first) - 1) + second_var**2/(len(second) - 1))
    check_t_test(
        welch, stats.ttest_ind(first, second, equal_var=False),
        welch_df, mean(first) - mean(second), sqrt(first_var + second_var),
    )

    paired = p.paired_t({"sample1_col": 0, "sample2_col": 1})
    differences = paired["result"]["differences"]
    if differences["n"] != 6:
        raise RuntimeError("Paired t used the wrong observations")
    deltas = [a - b for a, b in pairs]
    check_t_test(
        {**paired["result"], **differences}, stats.ttest_rel(paired_before, paired_after),
        len(pairs) - 1, mean(deltas), stdev(deltas)/sqrt(len(pairs)),
    )

    pearson = p.correlation([0, 1])
    correlation, = pearson["result"]["correlations"]
    if (correlation["count"], correlation["missing"]) != (6, 3):
        raise RuntimeError("Correlation used the wrong observation pairs")
    reference = stats.pearsonr(paired_before, paired_after)
    require_close(correlation["correlation"], reference.statistic, "Pearson r")
    require_close(correlation["p_value"], reference.pvalue, "Pearson p-value")
    interval = reference.confidence_interval()
    require_close(correlation["ci_low"], interval.low, "Pearson lower limit")
    require_close(correlation["ci_high"], interval.high, "Pearson upper limit")

    histogram = p.histogram_graphs([0], settings={"bins": 4})
    hist = export_graph(window, histogram, folder / "histogram.png")
    series, = hist.panels[0]["series"]
    if series["counts"] != [7, 0, 0, 1]:
        raise RuntimeError("Histogram bar counts differ from the source observations")
    boxplot = p.boxplot_graphs([0])
    box_chart = export_graph(window, boxplot, folder / "boxplot.png")
    box = box_chart.panels[0]["items"][0]["box"]
    if box != dict(q1=2.25, median=4.5, q3=6.75, low=2, high=7, outliers=[30]):
        raise RuntimeError(f"Boxplot summary differs from the source observations: {box}")
    scatter = p.scatter_plot(0, 1)
    scatter_chart = export_graph(window, scatter, folder / "scatterplot.png")
    points, = scatter_chart.panels[0]["series"]
    if list(zip(points["x"], points["y"], strict=True)) != pairs or points["row_indices"] != [1, 2, 5, 6, 7, 8]:
        raise RuntimeError("Scatterplot lost complete-pair row alignment")

    dialog = OneWayAnovaDialog(window)
    dialog.response_edit.setText("C3")
    dialog.factor_edit.setText("C4")
    dialog.options["comparisons"]["tukey"] = True
    dialog.options["graphs"]["residual_mode"] = "four_in_one"
    dialog.validate()
    anova = dialog.entry
    if anova is None:
        raise RuntimeError("The one-way ANOVA dialog rejected a valid fixture")
    result = anova["result"]
    groups = ([3, 4, 4], [7, 8, 9], [18, 20])
    table = result["anova_table"]
    if (table["df_factor"], table["df_error"]) != (2, 5) or [r["n"] for r in result["means"]] != [3, 3, 2]:
        raise RuntimeError("Incorrect ANOVA degrees of freedom or group counts")
    expected = stats.f_oneway(*groups)
    require_close(table["f_value"], expected.statistic, "one-way ANOVA F")
    require_close(table["p_value"], expected.pvalue, "one-way ANOVA p-value")
    tukey = stats.tukey_hsd(*groups)
    interval = tukey.confidence_interval()
    for row in result["comparisons"]["tukey"]["tests"]:
        a = "ABC".index(row["level_i"])
        b = "ABC".index(row["level_j"])
        require_close(row["difference"], tukey.statistic[a, b], "Tukey mean difference")
        require_close(row["adjusted_p"], tukey.pvalue[a, b], "Tukey adjusted p-value")
        require_close(row["ci_low"], interval.low[a, b], "Tukey lower limit")
        require_close(row["ci_high"], interval.high[a, b], "Tukey upper limit")
    chart = export_graph(window, anova, folder / "one-way-anova.png")
    residuals = next(panel for panel in chart.panels if panel["kind"] == "oneway_four_in_one")
    if residuals["orders"] != [1, 2, 3, 5, 6, 7, 8, 9]:
        raise RuntimeError("One-way residual graph lost its worksheet row numbers")

    for entry, name in ((one_sample, "one-sample-t"), (two_sample, "welch-t"), (paired, "paired-t")):
        export_graph(window, entry, folder / f"{name}.png")
    window.show_result(two_sample, target_tab="Report")
    entries = (descriptive, one_sample, two_sample, paired, pearson, histogram, boxplot, scatter, anova)
    verify_saved_results(window, folder / "basic-statistics.mpx", entries)
    return len(entries)


def check_t_test(result, expected, degrees_of_freedom, estimate, standard_error):
    from scipy import stats

    # The standalone t-test interval methods require a newer SciPy than the app.
    margin = stats.t.ppf(.975, degrees_of_freedom) * standard_error
    for key, target in (
        ("df", degrees_of_freedom),
        ("t_statistic", expected.statistic),
        ("p_value", expected.pvalue),
        ("ci_lower", estimate - margin),
        ("ci_upper", estimate + margin),
    ):
        require_close(result[key], target, key)


def verify_everyday_quality(window, folder):
    from scipy import stats

    from .capability_engine import c4, d2
    from .gage_rr_chart import CONSTANTS as GAGE_CONSTANTS
    from .model import Column, Worksheet
    from .subgroup_control import d3

    p = window.presenter
    p.new()

    # 1. I-MR starting from the same fractional-factorial worksheet setup as the native pass
    factors = [dict(name=name, low=-1, high=1) for name in "ABCD"]
    p.create_factorial(factors, generators={"D": "ABC"}, replicates=2, seed=42)
    p.add_column("Response")
    for row in range(p.worksheet.row_count):
        std_order, _, _, _, a, b, c, d, _ = p.worksheet.row(row)
        error = 1 if std_order <= 8 else -1
        p.set_cell(row, 8, str(10 + 2 * a - 3 * b + 1.5 * c + 0.5 * d + error))
    window.refresh()
    vals = p.worksheet.columns[8].numeric_values(True)
    imr = p.imr_chart({"variables": [8], "options": {}})
    imr_res = imr["result"]
    mrs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    mr_bar = sum(mrs) / len(mrs)
    sigma_imr = mr_bar / d2(2)
    require_close(imr_res["i_center"], 10.0, "I-MR center")
    require_close(imr_res["mr_center"], mr_bar, "MR center")
    require_close(imr_res["within_stdev"], sigma_imr, "I-MR sigma")
    require_close(imr_res["i_ucl"], 10.0 + 3.0 * sigma_imr, "I UCL")
    require_close(imr_res["mr_ucl"], (1.0 + 3.0 * d3(2) / d2(2)) * mr_bar, "MR UCL")
    imr_chart = export_graph(window, imr, folder / "quality-imr.png")
    require_close(imr_chart.panels[0]["ucl"], imr_res["i_ucl"], "I chart plotted UCL")
    verify_saved_results(window, folder / "quality-imr.mpx", (imr,))

    # 2. Xbar-R, p, u, and Normal Capability on unequal subgroup worksheet
    p.new()
    groups = [
        [10.0, 10.2, 9.8, 10.0],
        [10.1, 9.9, 10.0],
        [10.0, 10.3, 9.7, 10.1, 9.9],
        [16.0, 17.0],
        [10.2, 9.8, 10.1, 9.9],
    ]
    flat_meas = [v for g in groups for v in g]
    lot_ids = [f"Lot{i + 1}" for i, g in enumerate(groups) for _ in g]
    cap_groups = [[-0.4, -0.1, 0.2, 0.3], [-0.2, 0.1, 0.3], [-0.5, -0.2, 0.0, 0.2, 0.5], [-0.3, 0.0, 0.1, 0.2]]
    cap_vals = [v for g in cap_groups for v in g] + [None] * (len(flat_meas) - sum(len(g) for g in cap_groups))
    cap_lots = [f"B{i + 1}" for i, g in enumerate(cap_groups) for _ in g] + [None] * (len(flat_meas) - sum(len(g) for g in cap_groups))
    p_counts = [2, 3, 1, 18, 2, 3] + [None] * (len(flat_meas) - 6)
    p_sizes = [100, 120, 80, 150, 100, 90] + [None] * (len(flat_meas) - 6)
    u_counts = [4, 5, 3, 24, 4, 5] + [None] * (len(flat_meas) - 6)
    u_units = [2.0, 2.5, 1.5, 3.0, 2.0, 2.5] + [None] * (len(flat_meas) - 6)

    p.worksheet = Worksheet("Quality_SPC_Capability", [
        Column("Meas", "number", flat_meas),
        Column("Lot", "text", lot_ids),
        Column("P_Def", "number", p_counts),
        Column("P_N", "number", p_sizes),
        Column("U_Def", "number", u_counts),
        Column("U_N", "number", u_units),
        Column("Offset", "number", cap_vals),
        Column("Batch", "text", cap_lots),
    ])
    window.refresh()

    xbar_r = p.subgroup_control_chart(chart_type="xbar_r", stacked=True, response_index=0, factor_index=1)
    xr_res = xbar_r["result"]
    ns = [len(g) for g in groups]
    g_means = [sum(g) / len(g) for g in groups]
    g_ranges = [max(g) - min(g) for g in groups]
    xbar_bar = sum(n * m for n, m in zip(ns, g_means)) / sum(ns)
    weights = [(d2(n) ** 2) / (d3(n) ** 2) for n in ns]
    sigma_xr = sum(w * (r / d2(n)) for w, r, n in zip(weights, g_ranges, ns)) / sum(weights)
    require_close(xr_res["xbar_center"], xbar_bar, "Xbar-R center")
    require_close(xr_res["within_stdev"], sigma_xr, "Xbar-R weighted sigma")
    if 4 not in xr_res["test_failures"]:
        raise RuntimeError("Xbar-R failed to flag subgroup 4")
    xr_chart = export_graph(window, xbar_r, folder / "quality-xbar-r.png")
    if xr_chart.panels[0]["ucls"] != xr_res["xbar_ucl"] or xr_chart.panels[1]["centers"] != xr_res["disp_centers"]:
        raise RuntimeError("Xbar-R chart limits disagree with report")

    p_entry = p.attribute_control_chart({"chart_type": "P", "variables": [2], "is_subgroup_col": True, "subgroup_col_idx": 3})
    p_bar = 29.0 / 640.0
    require_close(p_entry["result"]["center"], p_bar, "P chart center")
    if 4 not in p_entry["result"]["test_failures"]:
        raise RuntimeError("P chart failed to flag subgroup 4")
    p_chart = export_graph(window, p_entry, folder / "quality-p.png")
    if p_chart.result["ucl"] != p_entry["result"]["ucl"]:
        raise RuntimeError("P chart plotted limits disagree with report")

    u_entry = p.attribute_control_chart({"chart_type": "U", "variables": [4], "is_subgroup_col": True, "subgroup_col_idx": 5})
    u_bar = 45.0 / 13.5
    require_close(u_entry["result"]["center"], u_bar, "U chart center")
    if 4 not in u_entry["result"]["test_failures"]:
        raise RuntimeError("U chart failed to flag subgroup 4")
    export_graph(window, u_entry, folder / "quality-u.png")

    cap_entry = p.normal_capability(settings={
        "single_column": True,
        "column_name": "Offset",
        "subgroup_spec": "Batch",
        "lsl": -3.0,
        "usl": 3.0,
        "options": {"target": 0.0, "estimate_method_gt1": "pooled", "unbiased_within": True},
    })
    cap_res = cap_entry["result"]
    cap_flat = [v for g in cap_groups for v in g]
    df_cap = sum(len(g) - 1 for g in cap_groups)
    ss_cap = sum((len(g) - 1) * (sum((v - sum(g) / len(g)) ** 2 for v in g) / (len(g) - 1)) for g in cap_groups)
    sd_cap_w = sqrt(ss_cap / df_cap) / c4(df_cap + 1)
    require_close(cap_res["stdev_within"], sd_cap_w, "Capability within SD")
    require_close(cap_res["cp"], 6.0 / (6.0 * sd_cap_w), "Capability Cp")
    require_close(cap_res["within_perf"]["expected_below"], float(stats.norm.cdf((-3.0 - cap_res["mean"]) / sd_cap_w)) * 1e6, "Capability expected PPM")
    export_graph(window, cap_entry, folder / "quality-capability.png")

    verify_saved_results(window, folder / "quality-spc-cap.mpx", (xbar_r, p_entry, u_entry, cap_entry))

    # 3. Crossed Gage R&R
    p.new()
    gage_rows = [
        ("P1", "OpA", 10.0), ("P1", "OpA", 10.2), ("P1", "OpB", 12.0), ("P1", "OpB", 12.2),
        ("P2", "OpA", 14.0), ("P2", "OpA", 14.2), ("P2", "OpB", 13.0), ("P2", "OpB", 13.2),
        ("P3", "OpA", 18.0), ("P3", "OpA", 18.2), ("P3", "OpB", 19.0), ("P3", "OpB", 19.2),
    ]
    p.worksheet = Worksheet("Gage_Study", [
        Column("Part", "text", [r[0] for r in gage_rows]),
        Column("Operator", "text", [r[1] for r in gage_rows]),
        Column("Measurement", "number", [r[2] for r in gage_rows]),
    ])
    window.refresh()
    gage_entry = p.gage_rr(2, 0, 1, options={"tolerance": 10.0})
    gage_chart = export_graph(window, gage_entry, folder / "quality-gage-rr.png")
    _, _, d4_g = GAGE_CONSTANTS[2]
    require_close(dict(gage_chart.panels[2]["limits"])["UCL"], d4_g * 0.2, "Gage R chart UCL")
    verify_saved_results(window, folder / "quality-gage.mpx", (gage_entry,))
    return 6


def verify_packaged_acceptance(window, folder):
    import hashlib
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtWidgets import QApplication

    from .app import Presenter
    from .attribute_control_chart import AttributeControlChartWidget
    from .capability_chart import CapabilityContainerWidget
    from .connect import create_connected_two_sample_t
    from .dsd_chart import DSDParetoEffectsWidget
    from .imr_chart import IMRChartWidget
    from .micro_innovations import StaleOutputBanner
    from .model import Column, Worksheet
    from .modern_app import ModernWindow
    from .modern_charts import ChartWidget
    from .r_universal_translator import generate_dataframe_r_code, translate_entry_to_r

    p = window.presenter
    p.new()

    # 1. W06 Freeze Panes on 150x30 worksheet
    p.worksheet = Worksheet(
        "FreezeQA",
        [Column(f"Col{c + 1}", "number", [float(r * 100 + c + 1) for r in range(150)]) for c in range(30)],
    )
    window.refresh()
    window.table.setCurrentCell(2, 1)
    window.freeze_panes()
    if (window._frozen_rows, window._frozen_cols) != (2, 1) or window.status_freeze_label.text() != "Frozen: 2R × 1C":
        raise RuntimeError("Freeze Panes failed to record 2R x 1C")
    window.table.verticalScrollBar().setValue(16)
    window.table.horizontalScrollBar().setValue(12)
    QApplication.processEvents()
    if window.table.property("frozen_rows") != 2 or window.table.property("frozen_cols") != 1:
        raise RuntimeError("Freeze Panes lost pinned geometry during scroll")
    window.unfreeze_panes()
    if (window._frozen_rows, window._frozen_cols) != (0, 0):
        raise RuntimeError("Unfreeze Panes did not reset frozen counts")

    # 2. Graph edit + save/reopen + zero false stale banner + Export All Graphs distinct PNGs
    p.new()
    p.worksheet = Worksheet(
        "PackagedQA",
        [
            Column("Temp", "number", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]),
            Column("Reading", "number", [2.1, 4.0, 6.2, 7.9, 10.1, 12.0, 14.2, 24.5]),
            Column("Def", "number", [1, 2, 1, 8, 1, 2, None, None]),
            Column("LotN", "number", [50, 60, 40, 50, 50, 55, None, None]),
        ],
    )
    window.refresh()
    hist_entry = window._call(lambda: p.histogram_graphs([1], settings={"bins": 4}), result=True)
    box_entry = window._call(lambda: p.boxplot_graphs([1]), result=True)
    imr_entry = window._call(lambda: p.imr_chart({"variables": [1], "options": {}}), result=True)
    attr_entry = window._call(
        lambda: p.attribute_control_chart({"chart_type": "P", "variables": [2], "is_subgroup_col": True, "subgroup_col_idx": 3}),
        result=True,
    )
    cap_entry = window._call(
        lambda: p.normal_capability(settings={"single_column": True, "column_name": "Reading", "lsl": 0.0, "usl": 30.0}),
        result=True,
    )

    window.show_result(hist_entry)
    window.graph_options_pane.load_entry(hist_entry)
    window.graph_options_pane.controls["title_enabled"].setChecked(True)
    window.graph_options_pane.controls["title"].setText("Packaged QA Histogram")
    if not window.graph_options_pane.flush():
        raise RuntimeError("Graph Options Pane failed to apply edited title")

    pkg_dir = folder / "packaged_acceptance"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    mpx_path = pkg_dir / "packaged_qa.mpx"
    if not window._call(lambda: window.save_path(str(mpx_path)), mutates_sheet=False):
        raise RuntimeError("Failed to save packaged QA project")
    page = window.result_tabs.currentWidget()
    if page is not None and page.findChildren(StaleOutputBanner):
        raise RuntimeError("Saving project triggered a false StaleOutputBanner")

    exported = window.export_all_graphs_to_dir(pkg_dir / "pngs")
    if len(exported) < 4:
        raise RuntimeError(f"Expected >= 4 exported PNGs, got {len(exported)}")
    hashes = set()
    for png in exported:
        img = QImage(str(png))
        if img.isNull():
            raise RuntimeError(f"Exported PNG failed to decode: {png}")
        hashes.add(hashlib.sha256(png.read_bytes()).hexdigest())
    if len(hashes) != len(exported):
        raise RuntimeError("Export All Graphs produced duplicate PNG contents")

    # Reopen saved project in a fresh ModernWindow and check edited title survived
    reopened_presenter = Presenter()
    reopened_presenter.load(mpx_path)
    reopened_window = ModernWindow(reopened_presenter)
    try:
        saved_hist = next(e for e in reopened_presenter.history if e["entry_id"] == hist_entry["entry_id"])
        if saved_hist.get("graph_presentation", {}).get("title") != "Packaged QA Histogram":
            raise RuntimeError("Reopened project lost edited histogram title")
        reopened_window.show_result(saved_hist)
        QApplication.processEvents()
    finally:
        reopened_presenter.dirty = False
        reopened_window.close()
        reopened_window.deleteLater()

    # 3. Pointer interaction sweep across chart widgets
    pareto_widget = DSDParetoEffectsWidget({
        "title": "Pareto 90%",
        "result": {
            "analysis": "definitive_screening_analysis",
            "response_name": "Reading",
            "alpha": 0.10,
            "t_crit": 2.00,
            "pareto_effects": [{"term": "A", "effect": 4.2}, {"term": "B", "effect": 2.00}],
        },
    })
    sweep_widgets = [
        pareto_widget,
        IMRChartWidget(imr_entry),
        AttributeControlChartWidget(attr_entry),
        CapabilityContainerWidget(cap_entry),
        ChartWidget(box_entry),
    ]
    pos = QPointF(40.0, 40.0)
    for w_item in sweep_widgets:
        w_item.resize(640, 420)
        w_item.grab()
        target = getattr(w_item, "plot", w_item)
        target.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, pos, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ))

    # 4. R translation fidelity on ragged two-sample input with reversed sample order
    p.new()
    p.worksheet = Worksheet(
        "RaggedWelch",
        [
            Column("Before", "number", [2, 2, 3, None, 4, 5, 6, 7, 30]),
            Column("After", "number", [1, 2, None, 4, 3, 4, 5, 6]),
        ],
    )
    t_entry = p.two_sample_t({
        "data_format": 1,
        "sample1_col": 1,
        "sample2_col": 0,
        "assume_equal_variances": True,
        "confidence_level": 90.0,
        "alternative": "greater",
        "hypothesized_difference": 1.5,
    })
    conn = create_connected_two_sample_t(p.worksheet, t_entry["recipe"]["parameters"]["settings"], t_entry["result"])
    if (conn.metadata.get("sample1_n"), conn.metadata.get("sample2_n")) != (7, 8):
        raise RuntimeError("Two-sample connected metadata recorded wrong independent sample counts")
    df_code = generate_dataframe_r_code(p.worksheet)
    after_row = next(line for line in df_code.splitlines() if '"After"' in line)
    after_vec = after_row.split("c(", 1)[1].rsplit(")", 1)[0]
    if len([tok.strip() for tok in after_vec.split(",")]) != 9 or not after_vec.endswith("NA"):
        raise RuntimeError("R data.frame did not pad ragged column to equal length")
    base_r, _, _ = translate_entry_to_r(t_entry, p.worksheet)
    if base_r.index('df[["After"]]') >= base_r.index('df[["Before"]]') or "var.equal = TRUE" not in base_r:
        raise RuntimeError("R translator dropped sample order or two-sample options")

    return {
        "freeze_panes_ok": True,
        "exported_png_count": len(exported),
        "distinct_png_hashes": len(hashes),
        "pointer_sweep_ok": True,
        "r_translation_ok": True,
    }


def verify_operating_window_flagship(window, folder):
    """Verify the 3D Operating Window & Confirmation Experiments workflow end-to-end."""
    from PySide6.QtWidgets import QToolButton
    from .operating_window import (
        chemical_operating_window_defaults,
        simulate_chemical_confirmation_responses,
    )

    p = window.presenter
    p.new()
    y_entry, v_entry = p.load_chemical_operating_window_demo()
    specs, opts = chemical_operating_window_defaults(y_entry["recipe"], v_entry["recipe"])
    opts["grid_size"] = 15

    ow_entry = p.operating_window_3d(specs, 0, 1, options=opts)
    ow_res = ow_entry["result"]
    if ow_res["predicted_optimum"]["worst_case_feasible"]:
        raise RuntimeError("Operating Window flagship smoke expected cliff optimum to fail drift")
    if not ow_res["robust_setting"]["worst_case_feasible"] or ow_res["robust_setting"]["outside_design_region"]:
        raise RuntimeError("Operating Window flagship smoke expected robust interior setting to pass drift")

    chart = export_graph(window, ow_entry, folder / "operating_window_3d.png", tab="Graph")
    chart.set_cad_orientation(45.0, 35.3)
    page = window.result_tabs.currentWidget()
    frame = page.content.findChild(GraphFrame)
    if frame is None or frame.findChild(QToolButton, "operatingWindowCreateConfirmation") is None:
        raise RuntimeError("Missing 'Create Confirmation Runs...' toolbar button on 3D Operating Window output")

    plan_entry = p.create_confirmation_plan(
        ow_res,
        setting_keys=["robust_setting"],
        replicates=3,
        seed=42,
        confidence=0.95,
    )
    simulate_chemical_confirmation_responses(p.worksheet, seed=101)
    eval_entry = p.evaluate_confirmation_runs(plan_entry["result"])
    if not eval_entry["result"]["confirmed"]:
        raise RuntimeError("Confirmation run evaluation did not confirm robust chemical process setting")

    export_graph(window, eval_entry, folder / "confirmation_evaluation.png", tab="Graph")
    mpx_path = folder / "operating_window_flagship.mpx"
    p.workspace = window._workspace.snapshot()
    p.save(mpx_path)
    restored = Presenter()
    restored.load(mpx_path)
    if not any(e.get("result", {}).get("analysis") == "operating_window_3d" for e in restored.history):
        raise RuntimeError("Reloaded flagship MPX missing 3D Operating Window history entry")
    if not any(e.get("result", {}).get("analysis") == "confirmation_evaluation" for e in restored.history):
        raise RuntimeError("Reloaded flagship MPX missing confirmation evaluation entry")

    return {
        "optimum_drift_failed": True,
        "robust_drift_feasible": True,
        "confirmation_confirmed": True,
        "drift_feasible_pct": ow_res["window_summary"]["drift_feasible_pct"],
    }
