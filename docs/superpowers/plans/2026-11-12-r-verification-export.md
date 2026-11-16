# Optional R Verification Export Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation. Track each step below.

**Goal** — Export a runnable R script that independently reproduces the supported StatCraft result.

**Architecture** — Resolve and validate the source in the existing Presenter and window paths. Generate verification code in the existing R translator and use the same generator for view, copy, and save.

**Tech stack** — Python, PySide6, Base R, unittest, PyInstaller.

**Spec** — [Optional R verification export](../specs/2026-11-12-r-verification-export.md).

## Global constraints

- Certify numeric ordinary least squares with the standard intercept in this increment.
- Base R verification scripts require zero external packages.
- Keep R execution optional and project data read-only in the export flow.
- Retain the existing formats, ordinary R Workbench, and standalone worksheet exports.
- Use the explicit result actions as entry points.

## Task 1 — Route result export to its source

**Files** — `statcraft/modern_app.py`, `statcraft/app.py` for existing source and freshness APIs, and `tests/test_r_code_export_bar.py`.

- [ ] Add a two-sheet fixture with same-name, different-value columns. Check that View, Copy, and Save use sheet A for A's result while B is active. Cover a stale result, an unavailable source, and a worksheet-only export with no selected analysis.
- [ ] Run `python -m unittest discover -s tests -p "test_r_code_export_bar.py"` and confirm the source assertions expose the v119 behavior.
- [ ] Consolidate the result path through `ModernWindow._get_entry_r_script(entry=None, *, dialect="base") -> tuple[str, str]`. Resolve an explicit or selected result through `Presenter.result_worksheet(entry)` and evaluate `Presenter.result_stale(entry)` for verification. Use the active worksheet for explicitly worksheet-only operations. Report stale or missing sources without writing a file or replacing the clipboard. Route result viewer variants to the same source.
- [ ] Run the focused suite. Expect all three actions and stale/missing-source checks to pass.

## Task 2 — Generate and check Base R verification code

**Files** — `statcraft/r_universal_translator.py`, `statcraft/connect_hub.py` for the existing viewer, and `tests/test_r_verification_export.py` (new).

- [ ] Add a live test with the spec's two-predictor example. Include an unrelated short column, a quoted column name, and missing values on different rows. Compare sample count exactly and coefficient estimates and interval endpoints within absolute and relative tolerances of `1e-7`. Add a categorical or interaction model and assert it gets exploratory output rather than a numeric OLS verification label.
- [ ] Run `python -m unittest discover -s tests -p "test_r_verification_export.py"` with R installed. Confirm the v119 script fails the new fixture or its parity assertions.
- [ ] In `translate_entry_to_r(entry, worksheet)`, recognize supported numeric regression using the explicit recipe and model settings. Render R-safe string literals, preserve column values and lengths, apply complete-case handling to model columns, and print the coefficient table, sample count, and intervals at the recorded confidence level. Use stable internal formula names where needed and show the mapping to the user’s column names. Distinguish verification output from exploratory scripts in the viewer and script header. Keep copy and save on the displayed script and make Base R the default for verification.
- [ ] Run both focused suites. Run the saved script using `Rscript --vanilla <script.R>` from a clean directory and verify it requires no worksheet files or packages.

## Task 3 — Remove legacy entry points and verify the desktop flow

**Files** — `statcraft/modern_app.py`, `statcraft/r_workbench_widget.py`, `tests/test_connect_mode_switch.py`, `tests/test_r_code_export_bar.py`, and the existing packaged smoke checks in `statcraft/local_integrations_smoke.py`. Update user documentation when the change is packaged.

- [ ] Replace the auto-translation mode-switch expectation with a test that switches to R and back with an existing editor buffer and a selected result. Assert the buffer survives, the result menu exposes R export, and the Workbench exposes no linked Apply Predictions action. Check that viewing, copying, and saving code works with R discovery mocked unavailable.
- [ ] Run the mode-switch and export suites and verify the regression tests fail on v119 where the retired actions remain.
- [ ] Remove automatic result loading on R mode switch and retire any reachable controls that advertise linked worksheet write-back. Preserve explicit worksheet sync and ordinary R script execution. Leave deserialization of existing project data intact. Document the optional export flow and its verified scope.
- [ ] Run the affected suites. Build with `python -m PyInstaller --noconfirm StatCraft.spec`. In the Windows build, open a fitted result, view and save Base R code, run it externally, and check the reported values. Verify source edits prompt a rerun and switching modes preserves the R editor buffer.

After numeric regression passes, use the same verification pattern for one-sample t tests and one-way ANOVA. Add model types when a live parity fixture covers the method and its settings.
