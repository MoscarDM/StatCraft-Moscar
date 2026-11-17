# StatCraft Full Remaining Roadmap Implementation Plan

> **Status (2026-11-17):** **Tasks 1–10 (Tracks 1–6) are COMPLETE and shipped**, including `v120.0.2` multi-platform release (`254209e`) and post-plan MPX/numerical parity expansions through `236703a`. See **Execution Ledger** below and **Next Horizon (Track 7+)** at the bottom of this document.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement remaining Next Horizon tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

## Execution Ledger (Completed)

- [x] **Task 1 (`1dc1b7e`):** Safe text & date column editing/resizing in `.mpx` copies (`mpx.py`, `mpx_rows.py`, `tests/test_mpx_text_date_edit.py`).
- [x] **Task 2 (`54af029`):** Expanded native MPX model recovery for 2-level factorial and GLM/One-Way ANOVA (`native_mpx_models.py`, `app.py`).
- [x] **Task 3 (`6a72636`):** Split-plot factorial design creation & two-stratum whole-plot/subplot ANOVA (`doe_split_plot.py`, `tests/test_doe_split_plot.py`).
- [x] **Task 4 (`d04941a`):** Extended 2-level principal-fraction generator catalog for 9–15 factors (`fractional.py`, `doe_catalog_designs.py`) + blocked/screening end-to-end fixtures.
- [x] **Task 5 (`f0c62cb`):** Bonett test, Multiple Comparisons, and Bonferroni-adjusted variance/stdev CIs (`variance_tests.py`).
- [x] **Task 6 (`672bd4c`):** ARIMA exact/ML estimation (`method='ML'`) and log/Box-Cox forecast back-transformation (`arima.py`, `arima_dialogs.py`, `arima_report.py`).
- [x] **Task 7 (`c12eb05`):** Local/global `MACRO` / `GMACRO` / `ENDMACRO`, `MCONSTANT` / `MCOLUMN` / `MMATRIX`, `IF/ENDIF`, and bounded `DO/ENDDO` loops (`session_commands.py`).
- [x] **Task 8 (`4d00985`):** `--smoke-verify`, `scripts/verify_built_executable.py`, CI/Release `.exe` SHA-256 verification gates (`ci.yml`, `release.yml`).
- [x] **Tasks 9–10 (`1cd905f`):** Automated GUI visual stress harness (`scripts/visual_stress_suite.py`) + live desktop inspection runbook (`visual-stress-runbook.md`), plus Dark Mode conditional highlight contrast fix (`d61b6b7`).
- [x] **Release `v120.0.2` (`b4d5cc5` → `254209e`):** PyInstaller `StatCraft.exe` built & verified, `pyproject.toml` synced, macOS DMG `-fs HFS+` + `ditto` ZIP packaging hardened, full 2,814-test suite passed (`OK`, `skipped=1`), and `Multi-Platform Release` succeeded.
- [x] **Post-Plan Phase A (`4195b81`, `236703a`):** Copy-on-write shared numeric/date `/blobs/blobM` allocation (`mpx.py`), Binary/Ordinal/Nominal Logistic & Poisson native model recovery (`native_mpx_models.py`), and `ui/zoom_percent` persistence (`modern_app.py`).
- [x] **Post-Plan Phase B (`80a8650`, `4553139`):** External Numerical Reference Parity Suites 1 & 2 (`tests/test_numerical_reference_parity.py`, `tests/test_numerical_reference_parity_phase2.py`) — NIST StRD `Norris`/`Pontius`, Normal Capability, 3×10×3 Gage R&R, Montgomery Two-Way ANOVA, Lieblein-Zelen & censored Weibull MLE, Binary Logistic MLE, Poisson MLE, EWMA, and One-Way ANOVA + Tukey HSD.

**Goal:** Close all remaining Minitab 22 parity, MPX native continuity, DOE, statistical method, session macro, and built-executable release gaps across StatCraft.

**Architecture:** Five ordered, independently verifiable tracks build on StatCraft's existing Python/PySide6 modules (`mpx*.py`, `doe*.py`, `variance_tests.py`, `arima.py`, `session_commands.py`) without altering the restored Minitab desktop layout. Every task follows strict red-green-refactor TDD with isolated fixtures and ends with a verified commit and release check.

**Tech Stack:** Python 3.12, PySide6 (Qt6 offscreen in CI), NumPy, SciPy, Matplotlib, PyInstaller, `unittest`.

**Spec:** [2026-11-13-minitab-parity-audit.md](2026-11-13-minitab-parity-audit.md)

## Global Constraints

- Preserve the restored Minitab desktop UI layout, menus, and existing keyboard accelerators (`RT_ACCELERATOR 8445` / `MtbResources.dll`).
- Keep `STATCRAFT_TESTING=1` and `QT_QPA_PLATFORM=offscreen` CI-safe on Windows, macOS, and Linux (`..\statcraft-build-env\Scripts\python.exe`).
- Never silently overwrite user `.mpx` files or silently mutate native metadata when round-trip safety is unverified; explicit `UnsupportedFormatError` must guard unverified operations.
- Every numerical method addition must be validated against published reference fixtures before enabling UI entry points.
- Preserve existing comments and docstrings unrelated to a task's diff.

## Review Focus

- Editing or resizing text/date columns in an imported `.mpx` worksheet without corrupting `/blobs` offsets, `CellCt`, or `StringTable` entries.
- Running a split-plot DOE analysis with unbalanced subplots or missing cells where whole-plot vs. subplot error degrees of freedom must not silently collapse to pooled residual error.
- Computing Bonett's variance test and simultaneous intervals on skewed or small-sample (`n = 2..4`) groups without divide-by-zero or negative degrees of freedom.
- Fitting seasonal ARIMA with `Method='ML'` (exact/recursive likelihood) or log/Box-Cox transform when observations contain zeros or nonpositive values (must raise clear `ValueError`, not `NaN` forecasts).
- Executing `.mac` / `.mtb` loops (`DO ... ENDDO`, `IF ... ELSE ... ENDIF`) with nested variables or undefined macro arguments without infinite loops or partial worksheet mutation.

---

## Track 1: MPX Native Continuity & Imported Model/Graph Recovery

### Task 1: Safe Text & Date Column Editing in MPX Copies

**Files:**
- Modify: `statcraft/mpx.py:298-358`
- Modify: `statcraft/mpx_text_create.py`
- Modify: `statcraft/mpx_date_create.py`
- Test: `tests/test_mpx_text_date_edit.py`

**Interfaces:**
- Consumes: `mpx_columns.prepare_columns(document, columns, baseline_columns, extent, appended_ids, uri)`
- Produces: `mpx.save(project, path, session_records=None)` supporting modified/resized `text` and `date` columns in `.mpx` copies.

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path
from statcraft import mpx


class MpxTextDateEditTests(unittest.TestCase):
    def test_edit_text_and_date_cells_roundtrip_in_mpx_copy(self):
        proj = mpx.open_project("tests/fixtures/sample_mixed.mpx")
        sheet = proj.worksheets[0]
        sheet.columns[1].values[0] = "UpdatedLabel"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "edited_copy.mpx"
            mpx.save(proj, out)
            reopened = mpx.open_project(out)
        self.assertEqual(reopened.worksheets[0].columns[1].values[0], "UpdatedLabel")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_mpx_text_date_edit -v`
Expected: FAIL with `UnsupportedFormatError` on resized/edited native text or date column.

- [ ] **Step 3: Implement safe text/date column re-encoding in `statcraft/mpx.py:308-355`**

Route edited `text` and `date` columns through `mpx_text_create` and `mpx_date_create` encoders when `column.values != baseline.values`, updating `CellCt` and `StringTable`/blob members while retaining the `UnsupportedFormatError` guard for `column.kind != baseline.kind` or `column.metadata != baseline.metadata`.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_mpx_text_date_edit tests.test_mpx tests.test_mpx_text_create tests.test_mpx_date_create -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/mpx.py tests/test_mpx_text_date_edit.py
git commit -m "feat(mpx): support safe text and date cell edits in MPX copies"
```

---

### Task 2: Expanded Native MPX Model Recovery (Factorial, ANOVA, & Non-Continuous Predictors)

**Files:**
- Modify: `statcraft/native_mpx_models.py`
- Modify: `statcraft/native_mpx_outputs.py`
- Test: `tests/test_native_mpx_models.py`

**Interfaces:**
- Consumes: `native_mpx_models.recover_model_setup(entry, worksheet)`
- Produces: `recover_model_setup(...) -> dict` covering 2-level factorial, General Linear Model (categorical factors), and response-surface setups.

- [ ] **Step 1: Write the failing test**

```python
def test_recover_factorial_model_setup_from_mpx(self):
    proj = mpx.open_project("tests/fixtures/sample_factorial.mpx")
    entry = next(e for e in proj.native_views if "Factorial" in e.get("title", ""))
    setup = recover_model_setup(entry, proj.worksheets[0])
    self.assertEqual(setup["family"], "factorial")
    self.assertTrue(setup["factors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_native_mpx_models -v`
Expected: FAIL (`Unsupported` / `None` returned for factorial native model).

- [ ] **Step 3: Implement factorial & categorical factor recovery in `statcraft/native_mpx_models.py`**

Decode `Factors`, `Terms`, and `Response` blocks from saved factorial/ANOVA XML/JSON nodes into StatCraft `doe_analysis` / `glm` parameter dictionaries, keeping explicit `Unsupported` diagnostics for weighted or transformed legacy models.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_native_mpx_models tests.test_native_mpx_outputs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/native_mpx_models.py statcraft/native_mpx_outputs.py tests/test_native_mpx_models.py
git commit -m "feat(mpx): recover factorial and categorical factor setups from native views"
```

---

## Track 2: DOE Completion (Split-Plot & Extended 2-Level Catalog)

### Task 3: Split-Plot Factorial Design Creation & Whole-Plot / Subplot Analysis

**Files:**
- Create: `statcraft/doe_split_plot.py`
- Modify: `statcraft/doe_dialogs.py`
- Modify: `statcraft/doe_analysis_dialogs.py`
- Test: `tests/test_doe_split_plot.py`

**Interfaces:**
- Produces: `create_split_plot_design(hard_factors: list, easy_factors: list, replicates: int = 1) -> Worksheet` and `analyze_split_plot(worksheet, response: str, whole_plot_col: str, terms: list) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
import unittest
from statcraft.doe_split_plot import create_split_plot_design, analyze_split_plot


class SplitPlotDoeTests(unittest.TestCase):
    def test_split_plot_design_and_two_stratum_anova(self):
        ws = create_split_plot_design(
            hard_factors=[{"name": "Temp", "levels": [100, 150]}],
            easy_factors=[{"name": "Time", "levels": [10, 20]}],
            replicates=2,
        )
        self.assertIn("WP", [c.name for c in ws.columns])
        self.assertEqual(len(ws.columns[0].values), 8)
        ws.columns[-1].values = [12.1, 14.3, 18.0, 20.2, 11.9, 14.1, 17.8, 20.4]
        res = analyze_split_plot(ws, response=ws.columns[-1].name, whole_plot_col="WP", terms=["Temp", "Time", "Temp*Time"])
        self.assertGreater(res["whole_plot_df"], 0)
        self.assertGreater(res["subplot_df"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_doe_split_plot -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'statcraft.doe_split_plot'`).

- [ ] **Step 3: Implement `statcraft/doe_split_plot.py` and enable Split-Plot option in `doe_dialogs.py` / `doe_analysis_dialogs.py`**

Generate randomized whole-plot (`WP`) blocks for hard-to-change factors and subplot runs for easy-to-change factors; compute restricted-maximum-likelihood / two-stratum ANOVA separating whole-plot error from subplot residual error.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_doe_split_plot tests.test_doe tests.test_doe_integration -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/doe_split_plot.py statcraft/doe_dialogs.py statcraft/doe_analysis_dialogs.py tests/test_doe_split_plot.py
git commit -m "feat(doe): add split-plot factorial design creation and two-stratum analysis"
```

---

### Task 4: Extended 2-Level Fractional Catalog (9–15 Factors) & Blocked / Screening End-to-End Fixtures

**Files:**
- Modify: `statcraft/doe_catalog_designs.py`
- Modify: `statcraft/doe_planner.py`
- Test: `tests/test_doe_catalog_designs.py`

**Interfaces:**
- Consumes: `doe_catalog_designs.two_level_design_spec(factors, runs)`
- Produces: Complete published principal-fraction generators and block generators for `k = 9..15` factors (up to 128 runs).

- [ ] **Step 1: Write the failing test**

```python
def test_nine_factor_resolution_iv_design(self):
    spec = two_level_design_spec(num_factors=9, runs=32)
    self.assertEqual(spec["resolution"], 4)
    self.assertEqual(len(spec["generators"]), 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_doe_catalog_designs -v`
Expected: FAIL (`ValueError` / missing generator entry for 9 factors).

- [ ] **Step 3: Implement 9–15 factor principal-fraction & block generator tables in `statcraft/doe_catalog_designs.py`**

Add published Minitab minimum-aberration defining relations for `k = 9..15` (16, 32, 64, 128 runs) and validate orthogonality + resolution metadata in `doe_planner.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_doe_catalog_designs tests.test_doe_planner_workflows -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/doe_catalog_designs.py statcraft/doe_planner.py tests/test_doe_catalog_designs.py
git commit -m "feat(doe): extend 2-level principal-fraction generator catalog to 15 factors"
```

---

## Track 3: Statistical Method Gaps & Numerical Parity Verification

### Task 5: Bonett Test, Simultaneous Comparisons, and Variance Confidence Intervals (`variance_tests.py`)

**Files:**
- Modify: `statcraft/variance_tests.py:1-92`
- Modify: `statcraft/modern_app.py` (equal-variances / one-variance dialog options)
- Test: `tests/test_variance_tests.py`

**Interfaces:**
- Produces: `equal_variances(groups, method='MultipleComparisons', alpha=0.05) -> dict` returning Bonett p-value, Multiple Comparisons p-value, and per-group Bonett / Chi-square variance & stdev confidence intervals.

- [ ] **Step 1: Write the failing test**

```python
def test_bonett_and_multiple_comparisons_intervals(self):
    g1 = [10.1, 10.4, 9.8, 10.2, 10.5, 9.9]
    g2 = [12.0, 14.5, 11.2, 15.1, 13.0, 14.8]
    res = equal_variances([g1, g2], method="MultipleComparisons", alpha=0.05)
    self.assertIn("bonett_p_value", res)
    self.assertIn("multiple_comparisons_p_value", res)
    self.assertEqual(len(res["confidence_intervals"]), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_variance_tests -v`
Expected: FAIL (`ValueError: Method must be median-centered Levene or Bartlett.`).

- [ ] **Step 3: Implement Bonett, Multiple Comparisons, and Bonferroni-adjusted variance CIs in `statcraft/variance_tests.py`**

Implement Bonett's kurtosis-adjusted confidence intervals for standard deviations (`1 - alpha_bonf`), Bonett's 2+/k-group test, and Minitab's Multiple Comparisons test, handling small `n >= 2` safely.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_variance_tests tests.test_equal_variances tests.test_one_variance -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/variance_tests.py statcraft/modern_app.py tests/test_variance_tests.py
git commit -m "feat(stats): add Bonett, Multiple Comparisons, and variance CIs to variance_tests"
```

---

### Task 6: ARIMA Exact/Recursive Likelihood & Log/Box-Cox Forecast Back-Transformation (`arima.py`)

**Files:**
- Modify: `statcraft/arima.py`
- Modify: `statcraft/arima_dialogs.py`
- Modify: `statcraft/arima_report.py`
- Test: `tests/test_arima.py`

**Interfaces:**
- Consumes: `fit_arima(values, order, seasonal_order, include_constant=True, method='CLS', transform=None)`
- Produces: Exact/MLE estimation (`method='ML'` via state-space / Kalman likelihood) and `transform='log'` / `transform='boxcox'` with bias-adjusted back-transformed forecasts & intervals.

- [ ] **Step 1: Write the failing test**

```python
def test_arima_ml_and_log_transform_rejects_nonpositive(self):
    series = [10.0, 12.1, 13.4, 15.2, 16.0, 18.5, 20.1, 22.0, 24.3, 26.8]
    fit = fit_arima(series, order=(1, 1, 0), method="ML", transform="log", forecast_steps=3)
    self.assertEqual(fit["method"], "ML")
    self.assertEqual(len(fit["forecasts"]), 3)
    with self.assertRaises(ValueError):
        fit_arima([0.0, 1.0, 2.0, 3.0, 4.0], order=(1, 0, 0), transform="log")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_arima -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'method'` / `'transform'`).

- [ ] **Step 3: Implement `method='ML'` & `transform` in `statcraft/arima.py` and expose in `arima_dialogs.py`**

Add state-space exact Gaussian likelihood optimization when `method='ML'` and validate strictly positive observations before applying log or Box-Cox transformation and back-transforming forecast intervals.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_arima tests.test_arima_integration tests.test_forecast_best_arima -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/arima.py statcraft/arima_dialogs.py statcraft/arima_report.py tests/test_arima.py
git commit -m "feat(arima): add exact ML estimation and log/Box-Cox forecast transforms"
```

---

## Track 4: Session Command & Macro Language (`session_commands.py`)

### Task 7: Local & Global `.mac` Macro Execution, Typed Declarations, and Control Flow

**Files:**
- Modify: `statcraft/session_commands.py`
- Test: `tests/test_session_commands_and_batch.py`

**Interfaces:**
- Consumes: `Presenter.execute_session_script(script_text: str)`
- Produces: Macro parser supporting `GMACRO` / `MACRO` / `ENDMACRO`, `MCONSTANT` / `MCOLUMN`, `IF ... ELSEIF ... ELSE ... ENDIF`, and bounded `DO k = a:b ... ENDDO` loops.

- [ ] **Step 1: Write the failing test**

```python
def test_local_macro_with_do_loop_and_conditional(self):
    script = """
    MACRO
    SUMSEQ N RES
    MCONSTANT N I S
    MCOLUMN RES
    LET S = 0
    DO I = 1:N
      IF I > 2
        LET S = S + I
      ENDIF
    ENDDO
    LET RES(1) = S
    ENDMACRO
    %SUMSEQ 4 C1
    """
    self.presenter.execute_session_script(script)
    self.assertEqual(self.presenter.worksheet.columns[0].values[0], 7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_session_commands_and_batch -v`
Expected: FAIL with unsupported macro/control-flow command error.

- [ ] **Step 3: Implement macro scope, `IF/ELSE/ENDIF`, and bounded `DO/ENDDO` in `statcraft/session_commands.py`**

Register macro definitions in session state, bind positional arguments to local `MCONSTANT`/`MCOLUMN` symbols, and enforce a maximum loop iteration guard (`MAX_MACRO_STEPS = 100_000`) to prevent runaway scripts.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_session_commands_and_batch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add statcraft/session_commands.py tests/test_session_commands_and_batch.py
git commit -m "feat(session): support MACRO/ENDMACRO, IF/ENDIF, and DO/ENDDO loops"
```

---

## Track 5: Release Packaging & Built-Binary Acceptance Gate

### Task 8: Reproducible Build & Built-Executable Acceptance Verification

**Files:**
- Modify: `.github/workflows/ci.yml` (or release build workflow)
- Create: `scripts/verify_built_executable.py`
- Test: `tests/test_installer_wizard.py`

**Interfaces:**
- Produces: `scripts/verify_built_executable.py --exe <path-to-StatCraft.exe>` running headless startup, `.mpx` open, `.xlsx` export, and analysis smoke checks against the compiled binary and recording its SHA-256 hash.

- [ ] **Step 1: Write the failing test / verification script**

Create `scripts/verify_built_executable.py` that asserts the built executable returns exit code `0` on `--smoke-verify`, prints bundled version matching `statcraft/__init__.py`, and outputs SHA-256 digest.

- [ ] **Step 2: Run full Windows test suite and build check**

Run:
```powershell
cd work\statcraft
$env:PYTHONPATH=""; $env:QT_QPA_PLATFORM="offscreen"; $env:STATCRAFT_TESTING="1"
..\statcraft-build-env\Scripts\python.exe -c "import ctypes, os, sys, unittest; suite = unittest.defaultTestLoader.discover('tests'); res = unittest.TextTestRunner(verbosity=1).run(suite); sys.stdout.flush(); sys.stderr.flush(); code = 0 if res.wasSuccessful() else 1; k32 = ctypes.windll.kernel32 if os.name == 'nt' else None; (setattr(k32.GetCurrentProcess, 'restype', ctypes.c_void_p), setattr(k32.TerminateProcess, 'argtypes', [ctypes.c_void_p, ctypes.c_uint]), k32.TerminateProcess(k32.GetCurrentProcess(), code)) if k32 else os._exit(code)"
```
Expected: All tests PASS (`PS_EXIT:0`).

- [ ] **Step 3: Commit & Tag Release**

```bash
git add scripts/verify_built_executable.py .github/workflows/ci.yml
git commit -m "ci(release): add built-executable smoke verification and SHA-256 gate"
```

---

## Track 6: Visual Stress Testing & Real-User GUI QA

### Task 9: Automated Visual Stress Harness (`scripts/visual_stress_suite.py`)

**Files:**
- Create: `scripts/visual_stress_suite.py`
- Test: `tests/test_visual_stress_harness.py`

**Interfaces:**
- Produces: `scripts/visual_stress_suite.py --out-dir <dir> [--exe <path-to-StatCraft.exe>]` launching the real visible GUI (no `offscreen` platform), driving real user mouse/keyboard stress scenarios, capturing PNG screenshots of the main window, dialogs, and charts, and emitting a `manifest.json` of timings, unhandled-exception checks, and screenshot paths for visual inspection.

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class VisualStressHarnessTests(unittest.TestCase):
    def test_visual_stress_script_emits_manifest_and_screenshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "scripts/visual_stress_suite.py", "--out-dir", tmp, "--quick"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            self.assertGreaterEqual(len(list(Path(tmp).glob("*.png"))), 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_visual_stress_harness -v`
Expected: FAIL (`can't open file 'scripts/visual_stress_suite.py'`).

- [ ] **Step 3: Implement `scripts/visual_stress_suite.py` covering 6 real-user stress scenarios**

Implement GUI-driven scenarios using real Qt event loop processing (`QApplication.processEvents()`), `QTest` clicks/keystrokes, and `window.grab().save(...)`:
1. **Large Dataset Stress:** Load/generate 100,000 rows × 20 columns, scroll rapidly, sort, autofill, apply conditional formatting (`out_of_control` + `in_list`), verify responsive UI (< 2s per action) and capture `01_large_worksheet.png`.
2. **Dark Mode & Font/DPI Resizing:** Switch Light ↔ Dark Mode, apply `Select Data Font…` (`Consolas 11`), resize main window from `1920x1080` down to `1024x700` and back, capture `02_dark_compact_layout.png` to visually check for clipped toolbars/labels.
3. **Graph & Multi-Tab Thrash:** Create I-MR, Sixpack, Boxplot, Scatter, and 3D Surface plots; switch tabs rapidly, zoom/pan, open Graph Options pane, `Close Current Graph`, capture `03_charts_and_tabs.png` to visually inspect overlapping tick labels, cut-off legends, or blank canvases.
4. **Dialog Stress & Bad-Input Torture:** Open complex dialogs (DOE Planner, Regression, ARIMA, Manage Conditional Rules, Hide/Unhide Columns), enter invalid/empty/non-numeric inputs, cancel mid-flow, reopen via `Edit Last Dialog (Ctrl+E)`, capture `04_dialogs.png`.
5. **MPX Open + Session Command Stress:** Open a real `.mpx` project, run `MTB >` commands + `Previous`/`Next` history cycling + `StatGuide`, capture `05_mpx_and_session.png`.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\statcraft-build-env\Scripts\python.exe -m unittest tests.test_visual_stress_harness -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/visual_stress_suite.py tests/test_visual_stress_harness.py
git commit -m "test(qa): add automated GUI visual stress-testing harness"
```

---

### Task 10: Live Desktop Launch & Codex Visual Inspection Runbook

**Files:**
- Create: `docs/superpowers/plans/visual-stress-runbook.md`

**Interfaces:**
- Produces: A concrete visual-inspection checklist and launch procedure for running the real desktop program (`python -m statcraft` or `StatCraft.exe`) and inspecting every generated PNG screenshot for visual defects.

- [ ] **Step 1: Write `docs/superpowers/plans/visual-stress-runbook.md`**

Include:
1. Exact launch command on a real Windows desktop session (`..\statcraft-build-env\Scripts\python.exe scripts/visual_stress_suite.py --out-dir artifacts/visual_qa` and live `Start-Process` launch of `StatCraft.exe`).
2. Visual inspection checklist for every screenshot (`01`–`05`):
   - Zero clipped/truncated dialog buttons, menu items, or status-bar badges.
   - Chart axes, legends, and titles readable in both Light Mode and Dark Mode with zero overlapping text.
   - Table headers (`C1`, `C2`, column names) aligned cleanly with grid columns after font changes, horizontal scrolling, and column hiding/unhiding.
   - Zero frozen/white "Not Responding" frames or orphaned floating popups after closing tabs/dialogs.
3. Defect logging rule: any visual flaw seen in a screenshot becomes a concrete bug fix + regression screenshot test before release sign-off.

- [ ] **Step 2: Execute a live visual pass (or hand off to Codex with `scripts/visual_stress_suite.py`) and inspect every PNG**

Run: `..\statcraft-build-env\Scripts\python.exe scripts/visual_stress_suite.py --out-dir artifacts/visual_qa`
Inspect every generated `.png` in `artifacts/visual_qa/` visually and verify zero layout/rendering defects.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/visual-stress-runbook.md
git commit -m "docs(qa): add Codex visual stress-testing inspection runbook"
```

---

## Next Horizon (Track 7+: Remaining Deeper Parity)

### Task 11: Native MPX Structural Worksheet Edits (Add / Delete / Reorder Sheets)
- [x] Safely support adding, renaming, deleting, and reordering worksheets in `.mpx` copies (`mpx.py`, `session.py`, `workspace_state.py`, `mpx_columns.py`, `app.py`), updating `worksheet_ids`, `worksheet_uris`, and ZIP members atomically while preserving retained native output links (`tests/test_mpx_worksheet_ops.py`).

### Task 12: Remaining Native MPX Model Recovery (Reliability, ARIMA, Mixed Models)
- [x] Extend `native_mpx_models.py` and `Presenter.refit_native_model` to recover Parametric Distribution/Reliability, ARIMA, and Mixed-Effects native model recipes with strict unsupported-option diagnostics (`tests/test_native_mpx_models_phase2.py`).

### Task 13: External Numerical Reference Parity Phase 3 (Mixed Models, ARIMA, Nonnormal Capability, Predictive ML)
- [x] Add `tests/test_numerical_reference_parity_phase3.py` validating REML Mixed Models, Seasonal ARIMA (`CLS` & `ML`), Nonnormal Capability (Johnson/Box-Cox/Weibull), and Predictive ML (CART/Random Forest) against external analytical/reference fixtures.

