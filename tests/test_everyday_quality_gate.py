"""Gate 4 verification: Everyday quality analysis (I-MR, Xbar-R, p, u, Normal Capability, Crossed Gage R&R)."""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STATCRAFT_TESTING", "1")

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication
from scipy import stats

from statcraft.app import Presenter
from statcraft.attribute_control_chart import AttributeControlChartWidget
from statcraft.attribute_control_engine import run_attribute_control
from statcraft.attribute_control_report import format_attribute_control_report
from statcraft.capability_chart import CapabilityContainerWidget
from statcraft.capability_dialogs import CapabilityDialog
from statcraft.capability_engine import c4, d2, run_normal_capability
from statcraft.gage_rr import analyze as analyze_gage_rr
from statcraft.gage_rr_chart import CONSTANTS as GAGE_CONSTANTS
from statcraft.imr_chart import IMRChartWidget
from statcraft.imr_engine import run_imr_chart
from statcraft.imr_report import format_imr_report
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.modern_charts import ChartWidget
from statcraft.subgroup_control import d3, fit_from_worksheet, fit_subgroups
from statcraft.subgroup_control_dialogs import XbarRChartDialog
from statcraft.subgroup_control_report import text_report as subgroup_text_report


_APP = QApplication.instance() or QApplication([])


def _d2_exact_ref():
    return d2(2)


class Gate4EverydayQualityTests(unittest.TestCase):
    def test_imr_fractional_and_gap_signal_roundtrip(self):
        # Same fractional-factorial worksheet setup as native pass
        p = Presenter()
        factors = [dict(name=name, low=-1, high=1) for name in "ABCD"]
        p.create_factorial(factors, generators={"D": "ABC"}, replicates=2, seed=42)
        p.add_column("Response")
        for row in range(p.worksheet.row_count):
            std_order, _, _, _, a, b, c, d, _ = p.worksheet.row(row)
            error = 1 if std_order <= 8 else -1
            p.set_cell(row, 8, str(10 + 2 * a - 3 * b + 1.5 * c + 0.5 * d + error))

        vals = p.worksheet.columns[8].numeric_values(True)
        entry = p.imr_chart({"variables": [8], "options": {"k_sigma": 2.5}})
        res = entry["result"]

        expected_mrs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
        expected_mr_bar = sum(expected_mrs) / len(expected_mrs)
        expected_sigma = expected_mr_bar / d2(2)
        expected_mean = sum(vals) / len(vals)
        self.assertAlmostEqual(expected_mean, 10.0, places=10)
        self.assertAlmostEqual(res["i_center"], expected_mean, places=10)
        self.assertAlmostEqual(res["mr_center"], expected_mr_bar, places=10)
        self.assertAlmostEqual(res["within_stdev"], expected_sigma, places=10)
        self.assertAlmostEqual(res["i_ucl"], expected_mean + 2.5 * expected_sigma, places=10)
        self.assertAlmostEqual(res["i_lcl"], expected_mean - 2.5 * expected_sigma, places=10)

        # Custom k_sigma=2.5 must apply to MR limits consistently as well
        expected_mr_ucl = (1.0 + 2.5 * d3(2) / d2(2)) * expected_mr_bar
        expected_mr_lcl = max(0.0, (1.0 - 2.5 * d3(2) / d2(2)) * expected_mr_bar)
        self.assertAlmostEqual(res["mr_ucl"], expected_mr_ucl, places=10)
        self.assertAlmostEqual(res["mr_lcl"], expected_mr_lcl, places=10)

        # Gap (missing value) + Test 1 outlier + MPX JSON roundtrip string-key survival
        p2 = Presenter()
        gap_vals = [10.0, 10.4, None, 10.2, 10.6, 10.1, 10.5, 10.3, 10.4, 10.2, 25.0, 10.3]
        p2.worksheet = Worksheet("IMRGap", [Column("Response", "number", gap_vals)])
        e2 = p2.imr_chart({"variables": [0], "options": {"k_sigma": 3.0}})
        r2 = e2["result"]
        self.assertIsNone(r2["moving_ranges"][2])
        self.assertIsNone(r2["moving_ranges"][3])
        self.assertIn(11, r2["test_failures"])

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "imr_gap.mpx"
            p2.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved_entry = next(x for x in reopened.history if x.get("entry_id") == e2["entry_id"])
            # After JSON roundtrip, dict keys in test_failures become strings
            widget = IMRChartWidget(saved_entry)
            widget.resize(780, 680)
            pix = widget.grab()
            self.assertFalse(pix.isNull())
            # Ensure panel signals work even when test_failures keys are strings
            i_panel = widget.panels[0]
            self.assertIn(11, i_panel["signals"])
            rep = format_imr_report(saved_entry["result"])
            self.assertIn("Test Failed at points: 11", rep)
            rerun = reopened.rerun_result(saved_entry)
            self.assertAlmostEqual(rerun["result"]["i_center"], r2["i_center"], places=10)

        # Insufficient data must fail without mutating worksheet or history
        p_bad = Presenter()
        p_bad.worksheet = Worksheet("BadIMR", [Column("X", "number", [4.2, None])])
        hist_before = list(p_bad.history)
        with self.assertRaises(ValueError):
            p_bad.imr_chart({"variables": [0], "options": {}})
        self.assertEqual(p_bad.history, hist_before)
        self.assertEqual(p_bad.worksheet.columns[0].values, [4.2, None])

    def test_xbar_r_unequal_subgroups_picker_and_roundtrip(self):
        # Unequal subgroup sizes [4, 3, 5, 2, 4] with an out-of-control shift in subgroup 4
        groups = [
            [10.0, 10.2, 9.8, 10.0],
            [10.1, 9.9, 10.0],
            [10.0, 10.3, 9.7, 10.1, 9.9],
            [16.0, 17.0],
            [10.2, 9.8, 10.1, 9.9],
        ]
        # Independent weighted Rbar reference (Minitab method)
        ns = [len(g) for g in groups]
        means = [sum(g) / len(g) for g in groups]
        ranges = [max(g) - min(g) for g in groups]
        xbar_bar = sum(n * m for n, m in zip(ns, means)) / sum(ns)
        weights = [(d2(n) ** 2) / (d3(n) ** 2) for n in ns]
        sigma_ref = sum(w * (r / d2(n)) for w, r, n in zip(weights, ranges, ns)) / sum(weights)

        res = fit_subgroups(groups, chart_type="xbar_r", options={"k_sigma": 2.5})
        self.assertAlmostEqual(res["xbar_center"], xbar_bar, places=10)
        self.assertAlmostEqual(res["within_stdev"], sigma_ref, places=10)
        self.assertIn("disp_centers", res)
        for i, n in enumerate(ns):
            se = sigma_ref / math.sqrt(n)
            self.assertAlmostEqual(res["xbar_ucl"][i], xbar_bar + 2.5 * se, places=10)
            self.assertAlmostEqual(res["xbar_lcl"][i], xbar_bar - 2.5 * se, places=10)
            r_cl_i = d2(n) * sigma_ref
            self.assertAlmostEqual(res["disp_centers"][i], r_cl_i, places=10)
            self.assertAlmostEqual(res["disp_ucl"][i], r_cl_i + 2.5 * d3(n) * sigma_ref, places=10)
            self.assertAlmostEqual(res["disp_lcl"][i], max(0.0, r_cl_i - 2.5 * d3(n) * sigma_ref), places=10)
        self.assertIn(4, res["test_failures"])

        # Worksheet + Presenter + Chart + MPX roundtrip + Picker focus to sub_size_edit
        flat_vals = [v for g in groups for v in g]
        sub_ids = [f"Lot{i + 1}" for i, g in enumerate(groups) for _ in g]
        p = Presenter()
        p.worksheet = Worksheet("XbarR", [Column("Diameter", "number", flat_vals), Column("Lot", "text", sub_ids)])
        win = ModernWindow(p)
        try:
            dlg = XbarRChartDialog(win)
            # Focus sub_size_edit and select Lot text column in col_list
            QApplication.sendEvent(dlg.sub_size_edit, QFocusEvent(QEvent.Type.FocusIn))
            dlg.col_list.setCurrentRow(1)
            dlg._on_select()
            self.assertEqual(dlg.sub_size_edit.text().strip(), 'C2-T: "Lot"')
            # Cancel must leave history clean
            dlg.reject()
            self.assertEqual(len(p.history), 0)
        finally:
            win.close()

        entry = p.subgroup_control_chart(
            chart_type="xbar_r",
            stacked=True,
            response_index=0,
            factor_index=1,
            options={"k_sigma": 2.5},
        )
        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "xbar_r.mpx"
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(x for x in reopened.history if x["entry_id"] == entry["entry_id"])
            chart = ChartWidget(saved)
            chart.resize(780, 680)
            self.assertFalse(chart.grab().isNull())
            self.assertEqual(len(chart.panels), 2)
            self.assertEqual(chart.panels[0]["ucls"], saved["result"]["xbar_ucl"])
            self.assertEqual(chart.panels[1]["centers"], saved["result"]["disp_centers"])
            rep = subgroup_text_report(saved["result"])
            self.assertIn("Test Failed at points: 4", rep)
            rerun = reopened.rerun_result(saved)
            self.assertAlmostEqual(rerun["result"]["within_stdev"], sigma_ref, places=10)

        with self.assertRaises(ValueError):
            fit_from_worksheet(p.worksheet, stacked=True, response_index=0, subgroup_size=1)

    def test_p_and_u_charts_unequal_subgroups_and_validation(self):
        # p chart with unequal subgroup sizes + signal at point 4
        p_counts = [2, 3, 1, 18, 2, 3]
        p_sizes = [100, 120, 80, 150, 100, 90]
        p_bar = sum(p_counts) / sum(p_sizes)
        p_res = run_attribute_control("P", p_counts, sample_sizes=p_sizes, variable_name="Defectives")
        self.assertAlmostEqual(p_res["center"], p_bar, places=12)
        for i, (c, n) in enumerate(zip(p_counts, p_sizes)):
            sig_i = math.sqrt(p_bar * (1.0 - p_bar) / n)
            self.assertAlmostEqual(p_res["observations"][i], c / n, places=12)
            self.assertAlmostEqual(p_res["ucl"][i], min(1.0, p_bar + 3.0 * sig_i), places=12)
            self.assertAlmostEqual(p_res["lcl"][i], max(0.0, p_bar - 3.0 * sig_i), places=12)
        self.assertIn(4, p_res["test_failures"])

        # u chart with unequal exposure sizes + signal at point 4
        u_counts = [4, 5, 3, 24, 4, 5]
        u_units = [2.0, 2.5, 1.5, 3.0, 2.0, 2.5]
        u_bar = sum(u_counts) / sum(u_units)
        u_res = run_attribute_control("U", u_counts, sample_sizes=u_units, variable_name="Defects")
        self.assertAlmostEqual(u_res["center"], u_bar, places=12)
        for i, (c, n) in enumerate(zip(u_counts, u_units)):
            sig_i = math.sqrt(u_bar / n)
            self.assertAlmostEqual(u_res["observations"][i], c / n, places=12)
            self.assertAlmostEqual(u_res["ucl"][i], u_bar + 3.0 * sig_i, places=12)
            self.assertAlmostEqual(u_res["lcl"][i], max(0.0, u_bar - 3.0 * sig_i), places=12)
        self.assertIn(4, u_res["test_failures"])

        # Invalid inputs must raise ValueError (not silently turn into None!)
        with self.assertRaises(ValueError):
            run_attribute_control("P", [-1, 2, 3], sample_sizes=100)
        with self.assertRaises(ValueError):
            run_attribute_control("U", [1, 2, 3], sample_sizes=[2.0, 0.0, 2.0])
        with self.assertRaises(ValueError):
            run_attribute_control("P", [1, 105, 3], sample_sizes=100)
        with self.assertRaises(ValueError):
            run_attribute_control("NP", [1, 105, 3], sample_sizes=100)

        # MPX roundtrip + widget rendering + string-key survival
        pres = Presenter()
        pres.worksheet = Worksheet(
            "AttrQC",
            [
                Column("P_Def", "number", p_counts),
                Column("P_N", "number", p_sizes),
                Column("U_Def", "number", u_counts),
                Column("U_N", "number", u_units),
            ],
        )
        ep = pres.attribute_control_chart({"chart_type": "P", "variables": [0], "is_subgroup_col": True, "subgroup_col_idx": 1})
        eu = pres.attribute_control_chart({"chart_type": "U", "variables": [2], "is_subgroup_col": True, "subgroup_col_idx": 3})

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "attr.mpx"
            pres.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            for orig in (ep, eu):
                saved = next(x for x in reopened.history if x["entry_id"] == orig["entry_id"])
                widget = AttributeControlChartWidget(saved)
                widget.resize(820, 520)
                self.assertFalse(widget.grab().isNull())
                rep = format_attribute_control_report(saved["result"])
                self.assertIn("Test Failed at points: 4", rep)
                rerun = reopened.rerun_result(saved)
                self.assertAlmostEqual(rerun["result"]["center"], orig["result"]["center"], places=12)

    def test_normal_capability_subgroups_zero_target_and_validation(self):
        # Unequal subgroups via subgroup column and Target = 0.0
        subgroups = [
            [-0.4, -0.1, 0.2, 0.3],
            [-0.2, 0.1, 0.3],
            [-0.5, -0.2, 0.0, 0.2, 0.5],
            [-0.3, 0.0, 0.1, 0.2],
        ]
        flat = [v for g in subgroups for v in g]
        batch = [f"B{i + 1}" for i, g in enumerate(subgroups) for _ in g]
        lsl, usl, target = -3.0, 3.0, 0.0

        # Independent closed-form + SciPy calculations (pooled within stdev)
        mean_ref = float(np.mean(flat))
        sd_overall_ref = float(np.std(flat, ddof=1))
        df_total = sum(len(g) - 1 for g in subgroups)
        ss_within = sum((len(g) - 1) * float(np.var(g, ddof=1)) for g in subgroups)
        sd_within_ref = math.sqrt(ss_within / df_total) / c4(df_total + 1)

        p = Presenter()
        p.worksheet = Worksheet("Cap", [Column("Offset", "number", flat), Column("Batch", "text", batch)])
        entry = p.normal_capability(settings={
            "single_column": True,
            "column_name": "Offset",
            "subgroup_spec": "Batch",
            "lsl": lsl,
            "usl": usl,
            "options": {"target": target, "estimate_method_gt1": "pooled", "unbiased_within": True, "include_ci": True},
        })
        res = entry["result"]
        self.assertEqual(res["target"], 0.0)
        self.assertAlmostEqual(res["mean"], mean_ref, places=10)
        self.assertAlmostEqual(res["stdev_within"], sd_within_ref, places=10)
        self.assertAlmostEqual(res["stdev_overall"], sd_overall_ref, places=10)
        self.assertAlmostEqual(res["cp"], (usl - lsl) / (6.0 * sd_within_ref), places=10)
        self.assertAlmostEqual(res["cpl"], (mean_ref - lsl) / (3.0 * sd_within_ref), places=10)
        self.assertAlmostEqual(res["cpu"], (usl - mean_ref) / (3.0 * sd_within_ref), places=10)
        self.assertAlmostEqual(res["cpk"], min(res["cpl"], res["cpu"]), places=10)
        self.assertAlmostEqual(res["cpm"], (usl - lsl) / (6.0 * math.sqrt(sd_within_ref ** 2 + (mean_ref - target) ** 2)), places=10)
        self.assertAlmostEqual(res["pp"], (usl - lsl) / (6.0 * sd_overall_ref), places=10)

        exp_below_w = float(stats.norm.cdf((lsl - mean_ref) / sd_within_ref)) * 1_000_000.0
        exp_above_w = float(stats.norm.sf((usl - mean_ref) / sd_within_ref)) * 1_000_000.0
        self.assertAlmostEqual(res["within_perf"]["expected_below"], exp_below_w, places=6)
        self.assertAlmostEqual(res["within_perf"]["expected_above"], exp_above_w, places=6)
        self.assertAlmostEqual(
            res["within_perf"]["z_bench"],
            float(stats.norm.isf((exp_below_w + exp_above_w) / 1_000_000.0)),
            places=8,
        )

        # Chart widget rendering + MPX save/reopen/rerun
        container = CapabilityContainerWidget(entry)
        container.resize(820, 560)
        self.assertFalse(container.grab().isNull())

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "cap.mpx"
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(x for x in reopened.history if x["entry_id"] == entry["entry_id"])
            self.assertEqual(saved["result"]["target"], 0.0)
            rerun = reopened.rerun_result(saved)
            self.assertAlmostEqual(rerun["result"]["cpk"], res["cpk"], places=10)

        # Validation errors: missing specs, LSL >= USL, bad subgroup column, non-positive subgroup size
        with self.assertRaises(ValueError):
            run_normal_capability(flat, subgroup_spec=1)
        with self.assertRaises(ValueError):
            run_normal_capability(flat, subgroup_spec=0, lsl=-1.0, usl=1.0)
        with self.assertRaises(ValueError):
            p.normal_capability(settings={
                "single_column": True, "column_name": "Offset", "subgroup_spec": "NoSuchCol", "lsl": -1.0, "usl": 1.0,
            })

        dlg = CapabilityDialog(p.worksheet)
        dlg.edit_single_col.setText("Offset")
        dlg.edit_sub_size.setText("0")
        dlg.edit_lsl.setText("-1")
        dlg.edit_usl.setText("1")
        # Must reject 0 subgroup size without accepting
        from PySide6.QtWidgets import QMessageBox
        orig_critical = QMessageBox.critical
        QMessageBox.critical = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)
        try:
            dlg._accept()
            self.assertIsNone(dlg.selected_params)
        finally:
            QMessageBox.critical = orig_critical

    def test_crossed_gage_rr_anova_and_six_panel_chart(self):
        # 3 parts x 2 operators x 2 repeats, strong part*operator interaction (retained)
        rows = [
            # Part, Op, Meas
            ("P1", "OpA", 10.0), ("P1", "OpA", 10.2),
            ("P1", "OpB", 12.0), ("P1", "OpB", 12.2),
            ("P2", "OpA", 14.0), ("P2", "OpA", 14.2),
            ("P2", "OpB", 13.0), ("P2", "OpB", 13.2),
            ("P3", "OpA", 18.0), ("P3", "OpA", 18.2),
            ("P3", "OpB", 19.0), ("P3", "OpB", 19.2),
        ]
        p = Presenter()
        p.worksheet = Worksheet(
            "GageStudy",
            [
                Column("Part", "text", [r[0] for r in rows]),
                Column("Operator", "text", [r[1] for r in rows]),
                Column("Measurement", "number", [r[2] for r in rows]),
            ],
        )
        entry = p.gage_rr(2, 0, 1, options={"tolerance": 10.0})
        res = entry["result"]
        self.assertFalse(res["interaction"]["pooled"])

        # Independent closed-form ANOVA on 3x2x2 tensor
        arr = np.array([
            [[10.0, 10.2], [12.0, 12.2]],
            [[14.0, 14.2], [13.0, 13.2]],
            [[18.0, 18.2], [19.0, 19.2]],
        ])
        a_cnt, b_cnt, r_cnt = arr.shape
        grand = float(arr.mean())
        part_m = arr.mean(axis=(1, 2))
        op_m = arr.mean(axis=(0, 2))
        cell_m = arr.mean(axis=2)
        ss_p = float(b_cnt * r_cnt * np.sum((part_m - grand) ** 2))
        ss_o = float(a_cnt * r_cnt * np.sum((op_m - grand) ** 2))
        ss_po = float(r_cnt * np.sum((cell_m - part_m[:, None] - op_m[None, :] + grand) ** 2))
        ss_e = float(np.sum((arr - cell_m[:, :, None]) ** 2))
        ms_p, ms_o, ms_po, ms_e = ss_p / 2, ss_o / 1, ss_po / 2, ss_e / 6
        f_po = ms_po / ms_e
        p_po = float(stats.f.sf(f_po, 2, 6))
        self.assertAlmostEqual(res["interaction"]["p_value"], p_po, places=10)
        var_rep = ms_e
        var_int = max(0.0, (ms_po - ms_e) / r_cnt)
        var_op = max(0.0, (ms_o - ms_po) / (a_cnt * r_cnt))
        var_part = max(0.0, (ms_p - ms_po) / (b_cnt * r_cnt))
        var_grr = var_rep + var_op + var_int
        var_tot = var_grr + var_part
        vc = {row["key"]: row for row in res["variance_components"]}
        self.assertAlmostEqual(vc["total_grr"]["variance"], var_grr, places=10)
        self.assertAlmostEqual(vc["total_grr"]["percent_tolerance"], 100.0 * 6.0 * math.sqrt(var_grr) / 10.0, places=10)
        self.assertAlmostEqual(vc["part_to_part"]["variance"], var_part, places=10)
        self.assertEqual(res["ndc"], max(1, math.floor(1.41 * math.sqrt(var_part) / math.sqrt(var_grr))))

        # Chart panels match report cell means/ranges and A2/D3/D4 limits
        chart = ChartWidget(entry)
        chart.resize(900, 720)
        self.assertFalse(chart.grab().isNull())
        self.assertEqual(len(chart.panels), 6)
        r_panel = chart.panels[2]
        x_panel = chart.panels[4]
        a2, d3_g, d4_g = GAGE_CONSTANTS[2]
        avg_r = float(np.mean(np.ptp(arr, axis=2)))
        self.assertAlmostEqual(dict(r_panel["limits"])["UCL"], d4_g * avg_r, places=10)
        self.assertAlmostEqual(dict(x_panel["limits"])["UCL"], grand + a2 * avg_r, places=10)

        with tempfile.TemporaryDirectory() as tmp:
            mpx_path = Path(tmp) / "gage_rr.mpx"
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(x for x in reopened.history if x["entry_id"] == entry["entry_id"])
            rerun = reopened.rerun_result(saved)
            self.assertAlmostEqual(rerun["result"]["variance_components"][0]["variance"], var_grr, places=10)

        # Reject unbalanced study (missing one replicate)
        p_unbal = Presenter()
        p_unbal.worksheet = Worksheet(
            "Unbal",
            [
                Column("Part", "text", [r[0] for r in rows[:-1]]),
                Column("Operator", "text", [r[1] for r in rows[:-1]]),
                Column("Measurement", "number", [r[2] for r in rows[:-1]]),
            ],
        )
        with self.assertRaises(ValueError):
            analyze_gage_rr(p_unbal.worksheet, 2, 0, 1)


if __name__ == "__main__":
    unittest.main()
