"""Headless startup, everyday analysis, graph export, and file roundtrip verification."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def run_smoke_verify() -> int:
    """Run headless StatCraft smoke verification and emit structured status to stdout."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("STATCRAFT_TESTING", "1")

    from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .app import Presenter
    from .everyday_smoke import (
        verify_basic_statistics, verify_central_composite, verify_everyday_quality,
        verify_fractional_graphs, verify_operating_window_flagship, verify_packaged_acceptance,
        verify_standard_regression,
    )
    from .graph_frame import GraphFrame
    from .model import Column, Worksheet
    from .modern_app import ModernWindow
    from .xlsx_export import convert_mpx
    from .xlsx_import import load_xlsx

    with tempfile.TemporaryDirectory(prefix="statcraft-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path / "settings"),
        )

        app = QApplication.instance() or QApplication(["StatCraft", "--smoke-verify"])
        presenter = Presenter()
        presenter.worksheet = Worksheet(
            "Smoke",
            [
                Column("X", values=[1.0, 2.0, 3.0, 4.0, 5.0]),
                Column("Y", values=[2.0, 4.0, 6.0, 8.0, 10.0]),
            ],
        )

        window = ModernWindow(presenter)
        try:
            window.show()
            app.processEvents()

            desc = presenter.describe_columns([0, 1])
            window.show_result(desc)
            app.processEvents()

            pix = window.grab()
            if pix.isNull():
                raise RuntimeError("Grabbed offscreen ModernWindow is null")

            mpx_path = tmp_path / "smoke.mpx"
            presenter.save(mpx_path)
            if not mpx_path.exists() or mpx_path.stat().st_size == 0:
                raise RuntimeError("MPX save failed to produce a non-empty file")

            reloaded = Presenter()
            reloaded.load(mpx_path)
            if reloaded.worksheet.row_count != 5:
                raise RuntimeError(
                    f"MPX roundtrip row count mismatch: expected 5, got {reloaded.worksheet.row_count}"
                )
            if reloaded.worksheet.columns[0].values != [1.0, 2.0, 3.0, 4.0, 5.0]:
                raise RuntimeError("MPX roundtrip column values mismatch")

            xlsx_path = tmp_path / "smoke.xlsx"
            convert_mpx(mpx_path, xlsx_path)
            if not xlsx_path.exists() or xlsx_path.stat().st_size == 0:
                raise RuntimeError("XLSX export failed to produce a non-empty file")

            loaded_sheets = load_xlsx(xlsx_path)
            if not loaded_sheets or loaded_sheets[0].row_count != 5:
                raise RuntimeError("XLSX roundtrip verification failed")

            from .xlsx_import import inspect_xlsx, load_xlsx_with_options
            inspected = inspect_xlsx(xlsx_path)
            selective = load_xlsx_with_options(
                xlsx_path,
                [{
                    "name": inspected["sheets"][0]["name"],
                    "import_sheet": True,
                    "start_row": 1,
                    "has_header": True,
                    "included_columns": [0],
                    "column_types": {0: "text"},
                }],
            )
            if not selective or selective[0].columns[0].kind != "text" or selective[0].row_count != 5:
                raise RuntimeError("XLSX selective preview import verification failed")

            factors = [{"name": name, "low": -1, "high": 1} for name in ("A", "B")]
            presenter.create_factorial(factors, replicates=2, randomize=False)
            presenter.add_column("Yield")
            for row in range(presenter.worksheet.row_count):
                std_order, _, _, _, a, b, _ = presenter.worksheet.row(row)
                deviation = -1 if std_order <= 4 else 1
                presenter.set_cell(row, 6, str(20 + 3 * a + 2 * b + a * b + deviation))
            factorial = presenter.analyze_factorial(6, [4, 5])
            factorial_charts = ("Effects Pareto", "Residual Plots")
            for name in factorial_charts:
                window.show_result(factorial, target_tab=name)
                if window.result_tabs.tabText(window.result_tabs.currentIndex()) != name:
                    raise RuntimeError(f"Factorial smoke verification could not open {name}")
                page = window.result_tabs.currentWidget()
                frame = page.content.findChild(GraphFrame)
                if frame is None or frame.capture().isNull():
                    raise RuntimeError(f"Factorial smoke verification could not render {name}")
                position = QPointF(20, 20)
                frame.chart.mouseMoveEvent(QMouseEvent(
                    QEvent.Type.MouseMove, position, position, Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                ))

            presenter.workspace = window._workspace.snapshot()
            factorial_path = tmp_path / "factorial.mpx"
            presenter.save(factorial_path)
            reloaded_factorial = Presenter()
            reloaded_factorial.load(factorial_path)
            saved_fit = next(entry for entry in reloaded_factorial.history
                             if entry.get("recipe", {}).get("action") == "analyze_factorial")
            if saved_fit["result"] != factorial["result"] or saved_fit["output_view"]["view"] != "Residual Plots":
                raise RuntimeError("Factorial roundtrip did not retain the fit and selected output")

            # Custom Define Factorial + Create Factorial blank reuse / occupied tab smoke
            custom_p = Presenter()
            custom_p.worksheet = Worksheet(
                "PaperPlaneCustom",
                [
                    Column("RunSeq", "number", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
                    Column("Angle", "number", [15, 30, 45, 15, 30, 45, 15, 30, 45, 15, 30, 45]),
                    Column("Wing", "text", ["Short"] * 6 + ["Long"] * 6),
                    Column("TesterBlock", "text", ["B1", "B1", "B1", "B2", "B2", "B2"] * 2),
                    Column("Distance", "number", [10.0, 14.0, 12.0, 10.6, 14.6, 12.6, 12.0, 16.0, 14.0, 12.7, 16.6, 14.7]),
                ],
            )
            custom_p.define_custom_factorial([1, 2], design_type="general_full", std_order_index=0, blocks_index=3)
            custom_fit = custom_p.analyze_factorial(4, [1, 2])
            if not custom_fit["result"]["include_blocks"] or custom_fit["result"].get("blocks_column") != "TesterBlock":
                raise RuntimeError("Custom general factorial smoke did not honor configured block column")
            custom_mpx = tmp_path / "custom_doe.mpx"
            custom_p.save(custom_mpx)
            custom_reopened = Presenter()
            custom_reopened.load(custom_mpx)
            if custom_reopened.worksheet.metadata.get("doe", {}).get("blocks_column") != "TesterBlock":
                raise RuntimeError("Custom DOE metadata did not persist across MPX save/reopen")

            fractional_exports = verify_fractional_graphs(window, tmp_path)
            shared_grid_points = verify_central_composite(window, tmp_path)
            residual_rows, interval_points = verify_standard_regression(window, tmp_path)
            basic_workflows = verify_basic_statistics(window, tmp_path)
            quality_workflows = verify_everyday_quality(window, tmp_path)
            packaged_acceptance = verify_packaged_acceptance(window, tmp_path)
            operating_window_flagship = verify_operating_window_flagship(window, tmp_path)

            from openpyxl import load_workbook
            from .r_verification import build_script as build_r_verification_script
            from .xlsx_verification import write_verification

            excel_presenter = Presenter()
            excel_presenter.worksheet = Worksheet('Regression Verification', [
                Column('X', values=[1, 2, None, 4, 5, 6]),
                Column('Y', values=[4, 7, 8, 10, 16, 17]),
            ])
            regression = excel_presenter.multiple_regression(1, [0])
            reg_r_script = build_r_verification_script(excel_presenter, regression)
            fac_r_script = build_r_verification_script(reloaded_factorial, saved_fit)
            if 'lm(' not in reg_r_script or 'lm(' not in fac_r_script:
                raise RuntimeError('OLS R verification script check failed')

            quality_r_presenter = Presenter()
            quality_r_presenter.worksheet = Worksheet('Quality Verification', [
                Column('Meas', values=[10.0, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0, 10.3, 9.7, 10.1]),
                Column('Lot', 'text', ['L1', 'L1', 'L1', 'L1', 'L2', 'L2', 'L2', 'L3', 'L3', 'L3']),
                Column('DefCnt', values=[2, 3, 1, 8, 2, 3, 2, 1, 2, 3]),
                Column('SubSz', values=[100, 100, 100, 100, 100, 100, 100, 100, 100, 100]),
            ])
            imr_r = quality_r_presenter.imr_chart({'variables': [0], 'options': {}})
            xr_r = quality_r_presenter.subgroup_control_chart(chart_type='xbar_r', stacked=True, response_index=0, factor_index=1)
            xs_r = quality_r_presenter.subgroup_control_chart(chart_type='xbar_s', stacked=True, response_index=0, factor_index=1)
            attr_r = quality_r_presenter.attribute_control_chart({
                'chart_type': 'P', 'variables': [2], 'is_subgroup_col': True, 'subgroup_col_idx': 3,
            })
            cap_r = quality_r_presenter.normal_capability(settings={
                'single_column': True,
                'column_name': 'Meas',
                'subgroup_spec': 'Lot',
                'lsl': 9.0,
                'usl': 11.0,
                'options': {'target': 10.0, 'estimate_method_gt1': 'pooled', 'unbiased_within': True},
            })
            gage_smoke_sheet = quality_r_presenter.add_worksheet('Gage Verification')
            gage_smoke_sheet.columns = [
                Column('Part', 'text', ['P1', 'P1', 'P1', 'P1', 'P2', 'P2', 'P2', 'P2', 'P3', 'P3', 'P3', 'P3']),
                Column('Operator', 'text', ['A', 'A', 'B', 'B', 'A', 'A', 'B', 'B', 'A', 'A', 'B', 'B']),
                Column('Reading', values=[10.0, 10.1, 10.2, 10.1, 12.0, 12.1, 12.2, 12.2, 14.0, 13.9, 14.1, 14.2]),
            ]
            grr_r = quality_r_presenter.gage_rr(2, 0, 1, options={'tolerance': 6.0})
            if (
                'I-MR Control Chart' not in build_r_verification_script(quality_r_presenter, imr_r)
                or 'XBAR_R Control Chart' not in build_r_verification_script(quality_r_presenter, xr_r)
                or 'XBAR_S Control Chart' not in build_r_verification_script(quality_r_presenter, xs_r)
                or 'Attribute Control Chart' not in build_r_verification_script(quality_r_presenter, attr_r)
                or 'Normal Capability' not in build_r_verification_script(quality_r_presenter, cap_r)
                or 'Gage R&R' not in build_r_verification_script(quality_r_presenter, grr_r)
            ):
                raise RuntimeError('Quality R verification script generation failed')
            verification_path = write_verification(tmp_path / 'verify-regression.xlsx', excel_presenter, regression)
            workbook = load_workbook(verification_path)
            if (len(workbook['Verification']._charts) != 1
                    or not workbook['Verification']['B6'].value.startswith('=IF')):
                raise RuntimeError('Regression verification workbook did not retain formulas and chart')

            factorial_path = write_verification(tmp_path / 'verify-factorial.xlsx', reloaded_factorial, saved_fit)
            factorial_workbook = load_workbook(factorial_path)
            if (len(factorial_workbook['Verification']._charts) != 2
                    or 'Factor Coding' not in factorial_workbook.sheetnames
                    or 'PRODUCT' not in factorial_workbook['Calculations']['C2'].value):
                raise RuntimeError('Factorial verification workbook did not retain coding formulas and charts')

            for tag, q_entry, min_charts in (
                ('imr', imr_r, 2),
                ('xbar-r', xr_r, 2),
                ('xbar-s', xs_r, 2),
                ('attribute-p', attr_r, 1),
                ('capability', cap_r, 2),
                ('gage-rr', grr_r, 2),
            ):
                q_xlsx = write_verification(tmp_path / f'verify-{tag}.xlsx', quality_r_presenter, q_entry)
                q_wb = load_workbook(q_xlsx)
                if (len(q_wb['Verification']._charts) < min_charts
                        or not q_wb['Verification']['B6'].value.startswith('=IF')):
                    raise RuntimeError(f'{tag} verification workbook did not retain formulas and charts')

            from .subgroup_workflows import approve as approve_sg, point_trace as sg_point_trace, replay as replay_sg
            sg_trace = sg_point_trace(xr_r['result'], 'xbar', 1)
            if len(sg_trace['rows']) != 4:
                raise RuntimeError('Subgroup trace did not capture expected source rows')
            approve_sg(quality_r_presenter, xr_r, 0)
            sg_tpl = xr_r['result']['workflow_replay']
            quality_r_presenter.add_worksheet('Quality Batch 2').columns = [
                Column('Meas2', values=[10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9]),
                Column('Lot2', 'text', ['B1', 'B1', 'B1', 'B1', 'B2', 'B2', 'B2', 'B2']),
            ]
            sg_replay = replay_sg(quality_r_presenter, sg_tpl, response_index=0, factor_index=1)
            if not sg_replay['result'].get('workflow_comparison'):
                raise RuntimeError('Subgroup workflow replay missing comparison')

            from .connect import create_connected_analysis_from_entry
            resolved_grr_ws = quality_r_presenter.resolve_entry_worksheet(grr_r)
            if resolved_grr_ws is not gage_smoke_sheet:
                raise RuntimeError('Multi-worksheet source resolution failed for Gage R&R')
            grr_conn = create_connected_analysis_from_entry(grr_r, resolved_grr_ws)
            if not grr_conn or grr_conn.response_name != 'Reading' or grr_conn.worksheet_name != 'Gage Verification':
                raise RuntimeError('Connected Gage R&R bound to wrong worksheet or column')

            from .attribute_workflows import approve as approve_attr, point_trace as attr_point_trace, replay as replay_attr
            attr_trace = attr_point_trace(attr_r['result'], 4)
            if attr_trace['count'] != 8.0 or not attr_trace['rules']:
                raise RuntimeError('Attribute trace did not capture expected subgroup signal')
            approve_attr(quality_r_presenter, attr_r, max_signals=0)
            attr_tpl = attr_r['result']['workflow_replay']
            quality_r_presenter.add_worksheet('Quality Attr Batch').columns = [
                Column('DefBatch', values=[1, 2, 1, 2, 1, 2]),
                Column('SzBatch', values=[100, 100, 100, 100, 100, 100]),
            ]
            attr_replay = replay_attr(quality_r_presenter, attr_tpl, count_index=0, size_index=1)
            if not attr_replay['result'].get('workflow_comparison') or not attr_replay['result']['workflow_comparison'].get('passed'):
                raise RuntimeError('Attribute workflow replay missing passing comparison')

            imr_sens = quality_r_presenter.imr_sensitivity(imr_r, 'baseline_period', start_row=1, end_row=5)
            sg_sens = quality_r_presenter.subgroup_sensitivity(xr_r, 'baseline_period', start_subgroup=1, end_subgroup=2)
            attr_sens = quality_r_presenter.attribute_sensitivity(attr_r, 'baseline_period', start_row=1, end_row=5)
            cap_sens = quality_r_presenter.capability_sensitivity(cap_r, 'distribution', distribution='weibull')
            if (not imr_sens['result'].get('sensitivity', {}).get('conclusions')
                    or not sg_sens['result'].get('sensitivity', {}).get('conclusions')
                    or not attr_sens['result'].get('sensitivity', {}).get('conclusions')
                    or not cap_sens['result'].get('sensitivity', {}).get('conclusions')):
                raise RuntimeError('Quality sensitivity smoke check missing conclusions')

            from .capability_workflows import (
                approve as approve_cap,
                capability_trace_summary,
                replay as replay_cap,
            )
            cap_trace = capability_trace_summary(cap_r['result'], focus='overview')
            if len(cap_trace['rows']) != 10:
                raise RuntimeError('Capability trace did not capture expected source rows')
            approve_cap(quality_r_presenter, cap_r, min_ppk=1.0)
            cap_tpl = cap_r['result']['workflow_replay']
            cap_replay = replay_cap(quality_r_presenter, cap_tpl, column_index=0, subgroup_col_index=1)
            if not cap_replay['result'].get('workflow_comparison'):
                raise RuntimeError('Capability workflow replay missing comparison')

            sens_mpx = tmp_path / 'quality-sensitivity.mpx'
            quality_r_presenter.save(sens_mpx)
            sens_reloaded = Presenter()
            sens_reloaded.load(sens_mpx)
            if (not any(e.get('result', {}).get('sensitivity', {}).get('kind') == 'imr_baseline_period' for e in sens_reloaded.history)
                    or not any(e.get('result', {}).get('sensitivity', {}).get('kind') == 'subgroup_baseline_period' for e in sens_reloaded.history)
                    or not any(e.get('result', {}).get('sensitivity', {}).get('kind') == 'attribute_baseline_period' for e in sens_reloaded.history)
                    or not any(e.get('result', {}).get('workflow_comparison') and e.get('result', {}).get('analysis') == 'attribute_control' for e in sens_reloaded.history)
                    or not any(e.get('result', {}).get('workflow_comparison') and e.get('result', {}).get('analysis') == 'capability' for e in sens_reloaded.history)):
                raise RuntimeError('Quality sensitivity or replay comparison did not persist through MPX')

            payload = {
                "status": "ok",
                "version": __version__,
                "rows": reloaded.worksheet.row_count,
                "mpx_bytes": mpx_path.stat().st_size,
                "xlsx_bytes": xlsx_path.stat().st_size,
                "excel_verification_workflows": ["regression", "factorial", "imr", "xbar_r", "xbar_s", "attribute", "capability", "gage_rr"],
                "r_verification_workflows": ["regression", "factorial", "imr", "xbar_r", "xbar_s", "attribute", "capability", "gage_rr"],
                "quality_sensitivity": {
                    "imr_baseline_period": True,
                    "subgroup_baseline_period": True,
                    "attribute_baseline_period": True,
                    "capability_distribution": True,
                },
                "subgroup_workflows": {"trace_ok": True, "replay_ok": True},
                "attribute_workflows": {"trace_ok": True, "replay_ok": True},
                "capability_workflows": {"trace_ok": True, "replay_ok": True},
                "custom_doe_ok": True,
                "factorial_charts": factorial_charts,
                "fractional_graph_exports": fractional_exports,
                "response_surface_grid_points": shared_grid_points,
                "regression_residual_rows": residual_rows,
                "fitted_line_interval_points": interval_points,
                "basic_statistics_workflows": basic_workflows,
                "quality_workflows": quality_workflows,
                "packaged_acceptance": packaged_acceptance,
                "operating_window_flagship": operating_window_flagship,
            }
        finally:
            presenter.dirty = False
            presenter._results_dirty = False
            window.close()
            window.deleteLater()
            app.processEvents()

    print(f"STATCRAFT_SMOKE_VERIFY={json.dumps(payload, sort_keys=True)}", flush=True)
    print(f"StatCraft {__version__} smoke verification passed.", flush=True)
    return 0
