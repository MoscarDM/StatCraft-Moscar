"""StatCraft Connect — Hub, Architecture Overview, and Visual Bridge Controls.

Connects Minitab quality & SPC procedures, JMP interactive visual exploration,
and Positron-style R Workbench into a unified, durable statistical workflow.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, TYPE_CHECKING
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGroupBox,
    QDialogButtonBox,
    QScrollArea,
    QWidget,
)

from .model import Column, Worksheet

if TYPE_CHECKING:
    from .modern_app import ModernWindow
    from .connect import ConnectedAnalysis


def _is_dark_active(widget=None) -> bool:
    if widget is not None:
        try:
            win = widget.window()
            if win and hasattr(win, "_dark_mode"):
                return bool(win._dark_mode)
        except Exception:
            pass
    app = QApplication.instance()
    if app:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return False


def create_chemical_process_sample() -> Worksheet:
    """Generate a realistic, deterministic 25-observation chemical engineering dataset.
    
    Variables:
    - Yield (%): Reaction conversion efficiency (Response)
    - Temperature (°C): Continuous process factor [140 - 165]
    - Pressure (psi): Continuous process factor [40 - 65]
    - Catalyst: Categorical text factor ("Alpha" / "Beta")
    """
    temps = [
        140.0, 142.5, 145.0, 147.5, 150.0, 152.5, 155.0, 157.5, 160.0, 162.5,
        141.0, 143.5, 146.0, 148.5, 151.0, 153.5, 156.0, 158.5, 161.0, 163.5,
        140.5, 145.5, 150.5, 155.5, 160.5
    ]
    pressures = [
        40.0, 42.0, 45.0, 47.0, 50.0, 52.0, 55.0, 57.0, 60.0, 62.0,
        60.0, 58.0, 55.0, 52.0, 50.0, 48.0, 45.0, 42.0, 40.0, 62.0,
        41.0, 46.0, 51.0, 56.0, 61.0
    ]
    catalysts = [
        "Alpha", "Alpha", "Alpha", "Alpha", "Alpha", "Beta", "Beta", "Beta", "Beta", "Beta",
        "Alpha", "Alpha", "Alpha", "Beta", "Beta", "Beta", "Alpha", "Alpha", "Beta", "Beta",
        "Alpha", "Beta", "Alpha", "Beta", "Alpha"
    ]
    # Yield = 42.0 + 0.32 * Temp + 0.16 * Pressure + (2.5 if Beta else 0.0) + noise
    yields = []
    for i, (t, p, cat) in enumerate(zip(temps, pressures, catalysts)):
        cat_effect = 2.4 if cat == "Beta" else 0.0
        synthetic_noise = math.sin(i * 1.7) * 0.45
        y = round(42.0 + 0.32 * (t - 140.0) + 0.16 * (p - 40.0) + cat_effect + synthetic_noise, 2)
        yields.append(y)

    ws = Worksheet("Chemical_Process", [
        Column("Yield", "number", yields),
        Column("Temperature", "number", temps),
        Column("Pressure", "number", pressures),
        Column("Catalyst", "text", catalysts),
    ])
    from .connect import ensure_worksheet_identities
    ensure_worksheet_identities(ws)
    return ws


class ConnectOverviewDialog(QDialog):
    """Publication-quality guide explaining how StatCraft Connect unifies Minitab, JMP, and R."""

    def __init__(self, window: "ModernWindow", parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle("StatCraft Connect — What is Connect?")
        self.setMinimumSize(760, 500)
        self.resize(840, 580)
        self.setSizeGripEnabled(True)
        self._init_ui()

    def _init_ui(self):
        dark = _is_dark_active(self)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 18)

        # Header Hero Banner
        hero = QFrame()
        if dark:
            hero.setStyleSheet("background-color: #18181b; border: 1px solid #0284c7; border-radius: 8px; padding: 14px;")
        else:
            hero.setStyleSheet("background-color: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 14px;")
        h_layout = QVBoxLayout(hero)
        h_layout.setSpacing(6)

        title = QLabel("<b>StatCraft Connect</b>: The Bridge Across Statistical Paradigms")
        title.setStyleSheet("font-size: 13pt; color: #0284c7;" if not dark else "font-size: 13pt; color: #38bdf8;")
        h_layout.addWidget(title)

        desc = QLabel(
            "StatCraft Connect unifies <b>three historically disconnected statistical tools</b> into one seamless desktop "
            "workflow. Rather than exporting CSVs, re-specifying models, or losing row selections, Connect preserves your "
            "worksheet data, variable roles, model definitions, and observation identities across all three modes."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 9.5pt; color: #334155;" if not dark else "font-size: 9.5pt; color: #cbd5e1;")
        h_layout.addWidget(desc)
        layout.addWidget(hero)

        # 3 Columns Visual Comparison
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        def make_pillar_card(badge_text: str, badge_color: str, heading: str, items: list[str]) -> QFrame:
            card = QFrame()
            if dark:
                card.setStyleSheet("background-color: #18181b; border: 1px solid #27272a; border-radius: 6px; padding: 12px;")
            else:
                card.setStyleSheet("background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px;")
            c_lay = QVBoxLayout(card)
            c_lay.setSpacing(8)

            badge = QLabel(f"<b>{badge_text}</b>")
            badge.setStyleSheet(f"color: {badge_color}; font-size: 8.5pt; text-transform: uppercase; font-weight: 700;")
            c_lay.addWidget(badge)

            h_lbl = QLabel(f"<b>{heading}</b>")
            h_lbl.setStyleSheet("font-size: 10.5pt; color: #0f172a;" if not dark else "font-size: 10.5pt; color: #f4f4f5;")
            c_lay.addWidget(h_lbl)

            for it in items:
                bullet = QLabel(f"• {it}")
                bullet.setWordWrap(True)
                bullet.setStyleSheet("font-size: 9pt; color: #475569;" if not dark else "font-size: 9pt; color: #a1a1aa;")
                c_lay.addWidget(bullet)
            c_lay.addStretch()
            return card

        card1 = make_pillar_card(
            "Mode 1 · Classic",
            "#0284c7",
            "Minitab Quality & Procedures",
            [
                "Familiar statistical dialogs with column selector list and [Select] button.",
                "SPC, Capability Sixpack, Gage R&R, ANOVA, and Design of Experiments (DOE).",
                "Formatted publication reports and Minitab Session command language (MTB >).",
            ],
        )

        card2 = make_pillar_card(
            "Mode 2 · Interactive",
            "#10b981",
            "JMP Visual Platforms",
            [
                "Interactive Prediction Profiler with draggable factor crosshairs and live response traces.",
                "Bivariate Fit Y by X platform with real-time linear, polynomial, and spline fits.",
                "Linked observation brushing: select points in scatter plots to highlight rows in the worksheet.",
            ],
        )

        card3 = make_pillar_card(
            "Mode 3 · Code-First",
            "#8b5cf6",
            "Positron-Style R Workbench",
            [
                "Zero-configuration Base R scripting; active worksheet automatically bound as 'df'.",
                "Non-parametric residual bootstrap uncertainty templates (2,000 replications).",
                "Sync R predictions, residuals, and diagnostics back to the sheet with stable row IDs.",
            ],
        )

        cards_layout.addWidget(card1, 1)
        cards_layout.addWidget(card2, 1)
        cards_layout.addWidget(card3, 1)
        layout.addLayout(cards_layout)

        # Core Guarantees Box
        guarantee_box = QFrame()
        if dark:
            guarantee_box.setStyleSheet("background-color: #1f1f23; border: 1px solid #27272a; border-radius: 6px; padding: 10px;")
        else:
            guarantee_box.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px;")
        g_lay = QVBoxLayout(guarantee_box)
        g_lay.setSpacing(4)
        g_title = QLabel("<b>The Connect Guarantee</b>")
        g_title.setStyleSheet("font-size: 9.5pt; color: #0f172a;" if not dark else "font-size: 9.5pt; color: #f4f4f5;")
        g_lay.addWidget(g_title)
        g_text = QLabel(
            "1. <b>Cryptographic Observation Identities</b>: Sorting, filtering, or moving rows never scrambles prediction bindings.<br>"
            "2. <b>Execution Verification</b>: The <i>Compare Implementations</i> tool checks coefficients against R <code>base::lm</code> to 10⁻⁴ tolerance.<br>"
            "3. <b>Zero Re-Entry</b>: Variable roles (Response, Predictors, Factors) flow automatically between dialogs, profilers, and R scripts."
        )
        g_text.setWordWrap(True)
        g_text.setStyleSheet("font-size: 8.5pt; color: #475569;" if not dark else "font-size: 8.5pt; color: #a1a1aa;")
        g_lay.addWidget(g_text)
        layout.addWidget(guarantee_box)

        # Actions & Sample Launcher
        btn_row = QHBoxLayout()
        load_sample_btn = QPushButton("🚀 Load Sample Project & Experience Connect (Chemical Yield)")
        load_sample_btn.setStyleSheet(
            "background-color: #0284c7; color: #ffffff; font-weight: 600; padding: 7px 16px; border-radius: 5px;"
        )
        load_sample_btn.clicked.connect(self._load_sample_and_close)
        btn_row.addWidget(load_sample_btn)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load_sample_and_close(self):
        self.accept()
        self.window.load_connect_sample()




class ViewRCodeDialog(QDialog):
    """Modern, multi-engine R Code Viewer displaying Tidyverse/ggplot2, Base R, and vroom ingestion with 1-click toggling."""

    def __init__(
        self,
        parent=None,
        r_script: str = "",
        title: str = "Reproducible R Script",
        tidyverse_script: str = "",
        vroom_script: str = "",
    ):
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.title_text = title
        self.setWindowTitle(f"R Code Viewer — {title}")
        self.resize(840, 580)
        self.setMinimumSize(680, 440)

        self.base_r_script = r_script
        self.tidyverse_script = tidyverse_script or r_script
        self.vroom_script = vroom_script

        # Default to tidyverse if available, otherwise base_r
        self.current_mode = "tidyverse" if tidyverse_script else "base_r"
        self.r_script = self.tidyverse_script if self.current_mode == "tidyverse" else self.base_r_script

        self._init_ui()

    def _init_ui(self):
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QFileDialog
        from PySide6.QtGui import QFont
        dark = _is_dark_active(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header Section
        self.header_label = QLabel()
        self.header_label.setStyleSheet("font-size: 11pt; font-weight: 700; color: #0284c7;" if not dark else "font-size: 11pt; font-weight: 700; color: #38bdf8;")
        self.sub_label = QLabel()
        self.sub_label.setStyleSheet("font-size: 8.5pt; color: #64748b;" if not dark else "font-size: 8.5pt; color: #94a3b8;")
        layout.addWidget(self.header_label)
        layout.addWidget(self.sub_label)

        # Mode Selector Ribbon (Segmented Pills)
        pill_box = QHBoxLayout()
        pill_box.setSpacing(6)

        self.btn_mode_tidy = QPushButton("📊 Modern Tidyverse & ggplot2")
        self.btn_mode_tidy.setCheckable(True)
        self.btn_mode_tidy.clicked.connect(lambda: self.set_mode("tidyverse"))
        pill_box.addWidget(self.btn_mode_tidy)

        self.btn_mode_base = QPushButton("⚙️ Pure Base R (Zero Dependencies)")
        self.btn_mode_base.setCheckable(True)
        self.btn_mode_base.clicked.connect(lambda: self.set_mode("base_r"))
        pill_box.addWidget(self.btn_mode_base)

        if self.vroom_script:
            self.btn_mode_vroom = QPushButton("⚡ Fast Data Ingest (vroom / readxl)")
            self.btn_mode_vroom.setCheckable(True)
            self.btn_mode_vroom.clicked.connect(lambda: self.set_mode("vroom"))
            pill_box.addWidget(self.btn_mode_vroom)
        else:
            self.btn_mode_vroom = None

        pill_box.addStretch()
        layout.addLayout(pill_box)

        # Monospace Code Editor with line numbers and R syntax highlighting
        from .r_workbench_widget import RCodeEditor
        self.code_view = RCodeEditor(parent=self, is_dark=dark, read_only=True, with_highlighter=True)
        self.code_view.setPlainText(self.r_script)
        self.highlighter = self.code_view.highlighter
        layout.addWidget(self.code_view, 1)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self.btn_copy = QPushButton("📋 Copy to Clipboard")
        self.btn_copy.setStyleSheet("QPushButton { font-weight: 600; padding: 6px 14px; background: #0284c7; color: white; border-radius: 4px; } QPushButton:hover { background: #0369a1; }")
        self.btn_copy.clicked.connect(self._copy_code)
        btn_bar.addWidget(self.btn_copy)

        btn_save = QPushButton("💾 Save .R File...")
        btn_save.setStyleSheet("QPushButton { padding: 6px 12px; }")
        btn_save.clicked.connect(self._save_file)
        btn_bar.addWidget(btn_save)

        btn_bar.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(btn_close)

        layout.addLayout(btn_bar)

        self._refresh_display()

    def set_mode(self, mode: str):
        self.current_mode = mode
        if mode == "tidyverse":
            self.r_script = self.tidyverse_script
        elif mode == "base_r":
            self.r_script = self.base_r_script
        elif mode == "vroom":
            self.r_script = self.vroom_script or self.base_r_script
        self.code_view.setPlainText(self.r_script)
        self.btn_copy.setText("📋 Copy to Clipboard")
        self._refresh_display()

    def _refresh_display(self):
        dark = _is_dark_active(self)
        active_pill = (
            "QPushButton { background: #0284c7; color: #ffffff; border: 1px solid #0369a1; border-radius: 14px; padding: 4px 12px; font-weight: 600; font-size: 8.5pt; }"
            if not dark else
            "QPushButton { background: #0284c7; color: #ffffff; border: 1px solid #38bdf8; border-radius: 14px; padding: 4px 12px; font-weight: 600; font-size: 8.5pt; }"
        )
        inactive_pill = (
            "QPushButton { background: #ffffff; color: #475569; border: 1px solid #cbd5e1; border-radius: 14px; padding: 4px 12px; font-size: 8.5pt; }"
            "QPushButton:hover { background: #f1f5f9; color: #0f172a; border-color: #94a3b8; }"
            if not dark else
            "QPushButton { background: #27272a; color: #a1a1aa; border: 1px solid #3f3f46; border-radius: 14px; padding: 4px 12px; font-size: 8.5pt; }"
            "QPushButton:hover { background: #3f3f46; color: #f4f4f5; border-color: #52525b; }"
        )

        self.btn_mode_tidy.setChecked(self.current_mode == "tidyverse")
        self.btn_mode_tidy.setStyleSheet(active_pill if self.current_mode == "tidyverse" else inactive_pill)

        self.btn_mode_base.setChecked(self.current_mode == "base_r")
        self.btn_mode_base.setStyleSheet(active_pill if self.current_mode == "base_r" else inactive_pill)

        if self.btn_mode_vroom is not None:
            self.btn_mode_vroom.setChecked(self.current_mode == "vroom")
            self.btn_mode_vroom.setStyleSheet(active_pill if self.current_mode == "vroom" else inactive_pill)

        if self.current_mode == "tidyverse":
            self.header_label.setText("Modern Tidyverse & ggplot2 Pipeline")
            self.sub_label.setText("Publication-ready dplyr / tidyr / ggplot2 code. Self-contained with embedded tibble dataset.")
        elif self.current_mode == "base_r":
            self.header_label.setText("Pure Base R Script (Zero Dependencies)")
            self.sub_label.setText("100% standard R library code. Runs cleanly out-of-the-box in any vanilla R console or RStudio.")
        elif self.current_mode == "vroom":
            self.header_label.setText("High-Performance Data Ingestion (vroom / readxl)")
            self.sub_label.setText("Multi-threaded memory-mapped CSV/TSV ingestion and native Excel reader workflows.")

    def _copy_code(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.r_script)
        self.btn_copy.setText("✓ Copied!")

    def _save_file(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        clean_title = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in self.title_text).strip("_") or "analysis"
        suffix = "tidyverse" if self.current_mode == "tidyverse" else ("base_r" if self.current_mode == "base_r" else "vroom_import")
        default_name = f"{clean_title}_{suffix}.R"
        path, _ = QFileDialog.getSaveFileName(self, "Save R Script", default_name, "R Files (*.R *.r)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.r_script)
            except OSError as err:
                QMessageBox.critical(self, "Export Error", f"Failed to save R script:\n{err}")


from PySide6.QtCore import QPoint as _QPoint, QRect as _QRect, QSize as _QSize
from PySide6.QtWidgets import QLayout as _QLayout


class FlowLayout(_QLayout):
    """Horizontal wrapping layout so action ribbons fit narrow report panes without overflow."""

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 6, v_spacing: int = 5):
        super().__init__(parent)
        self._items = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item is not None:
            item = self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(_QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = _QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + _QSize(left + right, top + bottom)

    def _do_layout(self, rect: _QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        eff = rect.adjusted(left, top, -right, -bottom)
        x = eff.x()
        y = eff.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_space
            if line_height > 0 and next_x - self._h_space > eff.right() + 1:
                x = eff.x()
                y = y + line_height + self._v_space
                next_x = x + hint.width() + self._h_space
                line_height = 0
            if not test_only:
                item.setGeometry(_QRect(_QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + bottom


class StatCraftAnalysisBar(QFrame):
    """Modern StatCraft Analysis ribbon with 1-click R script copy/export and dialog recall."""

    def __init__(self, window: "ModernWindow", entry: Dict[str, Any], conn_dict: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.window = window
        self.entry = entry
        self.conn_dict = conn_dict
        self._init_ui()

    def _resolve_worksheet(self):
        presenter = getattr(self.window, "presenter", None)
        if presenter is None:
            return None
        if hasattr(presenter, "resolve_entry_worksheet"):
            return presenter.resolve_entry_worksheet(self.entry)
        return getattr(presenter, "worksheet", None)

    def _init_ui(self):
        from .connect import ConnectedAnalysis, check_analysis_freshness
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication, QFileDialog

        self.conn_obj = ConnectedAnalysis.from_dict(self.conn_dict)
        worksheet = self._resolve_worksheet()
        if worksheet is not None:
            status, status_msg = check_analysis_freshness(self.conn_obj, worksheet)
        else:
            ws_name = self.entry.get("worksheet_name") or self.conn_obj.worksheet_name or ""
            status = "missing_sheet"
            status_msg = f"Source worksheet '{ws_name}' is unavailable."
        dark = _is_dark_active(self)

        self.setObjectName("statcraftAnalysisBar")
        if dark:
            self.setStyleSheet(
                "QFrame#statcraftAnalysisBar { background-color: #18181b; border: 1px solid #0284c7; border-radius: 6px; padding: 6px 12px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#statcraftAnalysisBar { background-color: #f0f9ff; border: 1px solid #7dd3fc; border-radius: 6px; padding: 6px 12px; }"
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        # Top Bar: Identity & Summary
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        badge = QLabel("<b>📊 R TRANSLATOR</b>")
        badge.setStyleSheet("color: #0284c7; font-size: 9pt;" if not dark else "color: #38bdf8; font-size: 9pt;")
        top_bar.addWidget(badge)

        r2_val = self.entry.get("result", {}).get("r_squared")
        r2_str = f"R² = {r2_val:.4f}" if r2_val is not None else "Fitted Procedure"
        meta = self.conn_obj.metadata or {}
        if self.conn_obj.analysis_type == "two_sample_t" and meta.get("data_format", 1) != 2:
            n1 = meta.get("sample1_n") or (meta.get("sample1") or {}).get("n")
            n2 = meta.get("sample2_n") or (meta.get("sample2") or {}).get("n")
            n_text = f"N1 = {n1}, N2 = {n2}" if (n1 is not None and n2 is not None) else f"N = {len(self.conn_obj.fitted_row_ids)}"
        else:
            n_text = f"N = {len(self.conn_obj.fitted_row_ids)}"
        model_info = QLabel(f"<b>{self.conn_obj.title}</b>  |  {r2_str}  |  {n_text}")
        model_info.setWordWrap(True)
        model_info.setStyleSheet("font-size: 8.5pt; color: #334155;" if not dark else "font-size: 8.5pt; color: #cbd5e1;")
        self.model_info = model_info
        top_bar.addWidget(model_info, 1)

        if status != "current":
            if status == "stale":
                warn_text = "⚠ Data Modified Since Fit"
            elif status == "missing_sheet":
                warn_text = "⚠ Source Worksheet Unavailable"
            else:
                warn_text = "⚠ Source Column Missing"
            warn_badge = QLabel(warn_text)
            warn_color = "#f59e0b" if status == "stale" else "#ef4444"
            warn_badge.setStyleSheet(
                f"color: {warn_color}; font-size: 8pt; font-weight: 600; padding: 2px 6px; border: 1px solid {warn_color}; border-radius: 3px;"
            )
            warn_badge.setToolTip(status_msg)
            top_bar.addWidget(warn_badge)
        else:
            sync_badge = QLabel("✓ In Sync")
            sync_badge.setStyleSheet(
                "color: #10b981; font-size: 8pt; font-weight: 600; padding: 2px 6px; border: 1px solid #10b981; border-radius: 3px;"
            )
            sync_badge.setToolTip("Source worksheet data matches analysis training state.")
            top_bar.addWidget(sync_badge)

        root.addLayout(top_bar)

        # Action Buttons Ribbon
        btn_bar = FlowLayout(h_spacing=6, v_spacing=5)

        btn_primary_qss = (
            "QPushButton { background: #0284c7; color: #ffffff; border: 1px solid #0369a1; border-radius: 4px; padding: 4px 10px; font-size: 8.5pt; font-weight: 700; }"
            "QPushButton:hover { background: #0369a1; }"
        )

        btn_qss = (
            "QPushButton { background: #27272a; color: #f4f4f5; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 9px; font-size: 8.5pt; font-weight: 500; }"
            "QPushButton:hover { background: #3f3f46; border-color: #0284c7; color: #38bdf8; }"
            if dark else
            "QPushButton { background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 9px; font-size: 8.5pt; font-weight: 500; }"
            "QPushButton:hover { background: #e0f2fe; border-color: #0284c7; color: #005a9e; }"
        )

        self.badge = badge

        b_copy_r = QPushButton("📋 Copy R Script")
        b_copy_r.setStyleSheet(btn_primary_qss)
        b_copy_r.setToolTip("Copy modern Tidyverse & ggplot2 R script for this analysis to clipboard (self-contained with embedded data)")
        b_copy_r.clicked.connect(self.copy_r_script)
        btn_bar.addWidget(b_copy_r)
        self.btn_copy_r = b_copy_r

        b_copy_base = QPushButton("⚙️ Pure Base R")
        b_copy_base.setStyleSheet(btn_qss)
        b_copy_base.setToolTip("Copy 100% pure Base R script (zero external packages) to clipboard")
        b_copy_base.clicked.connect(self.copy_base_r_script)
        btn_bar.addWidget(b_copy_base)
        self.btn_copy_base = b_copy_base

        b_view_r = QPushButton("👁️ View R Code")
        b_view_r.setStyleSheet(btn_qss)
        b_view_r.setToolTip("Inspect generated Base R code in a syntax-highlighted code viewer")
        b_view_r.clicked.connect(self.view_r_code)
        btn_bar.addWidget(b_view_r)
        self.btn_view_r = b_view_r

        b_export_r = QPushButton("💾 Export .R...")
        self.btn_export_r = b_export_r
        b_export_r.setStyleSheet(btn_qss)
        b_export_r.setToolTip("Save standalone Base R script to a file")
        b_export_r.clicked.connect(self.export_r_file)
        btn_bar.addWidget(b_export_r)

        b_dialog = QPushButton("🔙 Recall Dialog...")
        b_dialog.setStyleSheet(btn_qss)
        b_dialog.setToolTip("Edit variables, options, and parameters in the classic procedure dialog (restoring previous selections)")
        b_dialog.clicked.connect(lambda: self.window.connect_open_dialog(self.entry) if hasattr(self.window, "connect_open_dialog") else None)
        btn_bar.addWidget(b_dialog)

        b_report = QPushButton("📑 Add to ReportPad")
        b_report.setStyleSheet(btn_qss)
        b_report.setToolTip("Append this analysis report to the active StatCraft ReportPad")
        b_report.clicked.connect(lambda: self.window.append_connected_report_to_report_pad(self.entry) if hasattr(self.window, "append_connected_report_to_report_pad") else None)
        btn_bar.addWidget(b_report)

        root.addLayout(btn_bar)

    def get_full_r_script(self) -> str:
        ws = self._resolve_worksheet()
        if ws is not None:
            from .r_universal_translator import translate_entry_to_r
            base, _, _ = translate_entry_to_r(self.entry, ws)
            return base
        return self.conn_obj.r_script or ""

    def get_tidyverse_r_script(self) -> str:
        ws = self._resolve_worksheet()
        if ws is not None:
            from .r_universal_translator import translate_entry_to_r
            _, tidy, _ = translate_entry_to_r(self.entry, ws)
            return tidy
        meta_tidy = self.conn_obj.metadata.get("tidyverse_script") if isinstance(self.conn_obj.metadata, dict) else None
        if meta_tidy:
            return meta_tidy
        if self.conn_obj.r_script:
            return self.conn_obj.r_script
        from .connect_r import generate_r_tidyverse_script
        return generate_r_tidyverse_script(self.conn_obj, ws)

    def get_vroom_r_script(self) -> str:
        from .connect_r import generate_vroom_data_import_code
        ws = self._resolve_worksheet()
        if ws is None:
            ws = getattr(self.window.presenter, "worksheet", None) if hasattr(self.window, "presenter") else None
        return generate_vroom_data_import_code(ws)

    def copy_r_script(self):
        from PySide6.QtWidgets import QApplication
        script = self.get_tidyverse_r_script() or self.get_full_r_script()
        QApplication.clipboard().setText(script)
        if hasattr(self.window, "statusBar") and self.window.statusBar():
            self.window.statusBar().showMessage(f"✓ Copied modern Tidyverse & ggplot2 R script for '{self.conn_obj.title}' to clipboard!", 5000)

    def copy_base_r_script(self):
        from PySide6.QtWidgets import QApplication
        script = self.get_full_r_script()
        QApplication.clipboard().setText(script)
        if hasattr(self.window, "statusBar") and self.window.statusBar():
            self.window.statusBar().showMessage(f"✓ Copied pure Base R script for '{self.conn_obj.title}' to clipboard!", 5000)

    def view_r_code(self):
        base_script = self.get_full_r_script()
        tidy_script = self.get_tidyverse_r_script()
        vroom_script = self.get_vroom_r_script()
        dlg = ViewRCodeDialog(
            self.window,
            r_script=base_script,
            title=f"R Code: {self.conn_obj.title}",
            tidyverse_script=tidy_script,
            vroom_script=vroom_script,
        )
        dlg.exec()

    def export_r_file(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        script = self.get_tidyverse_r_script() or self.get_full_r_script()
        clean = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in self.conn_obj.title).strip("_")
        default_name = f"{clean}_tidyverse.R"
        path, _ = QFileDialog.getSaveFileName(self, "Export R Script", default_name, "R Scripts (*.R *.r)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(script)
                if hasattr(self.window, "statusBar") and self.window.statusBar():
                    self.window.statusBar().showMessage(f"✓ Saved R script to {path}", 5000)
            except OSError as err:
                QMessageBox.critical(self, "Export Error", f"Failed to save R script:\n{err}")


ConnectBridgeWidget = StatCraftAnalysisBar
