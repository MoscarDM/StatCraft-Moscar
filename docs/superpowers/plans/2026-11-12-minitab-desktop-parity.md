# Minitab Desktop Parity Implementation Plan

## ARIMA input integrity and desktop checks — 2026-11-12

Manual and automatic ARIMA now share row-preserving observation validation. Missing, nonnumeric, and infinite observations produce a row-specific error instead of silently compressing time. Manual model orders, seasonal period, forecast count, confidence level, and iteration count are validated before fitting. A failed Presenter analysis leaves worksheet columns and history unchanged.

Verification: 29 computational and Presenter tests passed, followed by 14 Qt tests for ARIMA, automatic-ARIMA dialog storage options, imported output startup, and the restored Sandbox. NumPy, SciPy, and PySide6 were restored in the local build environment. This resolves the previous missing-Qt test blocker. No interface redesign or EXE rebuild was performed. Minitab likelihood equivalence, log transformations, and the broader DOE/quality comparisons remain open.

## Forecast reconstruction correction — 2026-11-12

Replaced the forecast undifferencing fallback with inversion of the full differencing polynomial. This fixes combinations such as second-order nonseasonal plus seasonal differencing and all higher orders exposed in the existing dialog. Empty forecast requests now return no values; insufficient history raises an explicit error. The existing interface is retained.

Verification: 26 tests passed across forecast reconstruction, time series, and automatic ARIMA. Reconstruction covers all 72 combinations of d=0..5, D=0..3 and periods 1, 4, 12, with eight future observations each. Before the correction, 59 assertions failed. The additional tests.test_arima module could not import because this local build environment lacks PySide6. No packaged EXE was rebuilt in this increment. These checks establish internal numerical consistency, not numerical equivalence with Minitab's estimation method.

> **For agentic workers:** Use superpowers:executing-plans, test-driven-development, and verification-before-completion.

**Goal** — Close verified differences in workflows, calculations, and output against Minitab Desktop.

**Baseline** — StatCraft v119.0.0 at 2060cbc. Earlier worksheet, chart, and dialog passes are present in source. A matching menu name counts as coverage to investigate. A published or captured comparison is needed to mark behavior verified.

| Priority | Area | Work and acceptance |
| --- | --- | --- |
| 1 | Power and sample size | Implement both tolerance-interval planning modes and verify the published washer example. Then audit estimation precision in both directions, the four equivalence power procedures, and Plackett-Burman and general full factorial power. The current menu exposes one generic TOST power entry. |
| 2 | DOE and quality | Compare setup, options, reported results, and storage for screening designs, response surface, Gage R&R, and capability. Start with grouped or blocked data and repeat the flow after reopening a saved project. |
| 3 | Modeling and time series | Compare options and results for the regression and forecasting procedures already present. Include model terms, categorical coding, row omissions, and prediction intervals. The current menu exposes manual ARIMA. Add Forecast with Best ARIMA Model after checking candidate selection, forecasts, and residual diagnostics against a reference run. |
| 4 | Worksheet, charts, and interchange | Verify the recent navigation, graph editing, brushing, worksheet edits, and SVG export in the desktop build. Compare MPX/MWX import and round trips using representative fixtures. Record unsupported native project features explicitly. |

## First increment — Sample Size for Tolerance Intervals

**Reference** — [Minitab methods](https://support.minitab.com/en-us/minitab/help-and-how-to/statistics/power-and-sample-size/how-to/sample-size/sample-size-for-tolerance-intervals/methods-and-formulas/methods-and-formulas/) and [published washer example](https://support.minitab.com/en-us/minitab/help-and-how-to/statistics/power-and-sample-size/how-to/sample-size/sample-size-for-tolerance-intervals/before-you-start/example/).

- [x] Add a test for both solve directions. At 95% minimum coverage, 95% confidence and 5% excess probability, normal sample sizes for 96% and 97% are 2480 and 525. Nonparametric sample sizes are 4654 and 1036. For N = 50 and 100, the normal maximum coverage rounds to 99.4015% and 98.6914%.
- [x] Implement `tolerance_interval_planning` alongside the current precision-factor API. Use the noncentral t distribution for normal one-sided limits, normal probability integrated over the sample mean for two-sided intervals, and order-statistic beta probabilities for the nonparametric method. Search for the first qualifying integer, accounting for discrete jumps in the nonparametric result.
- [x] Wire both solve directions and both interval types into the existing Stat > Power and Sample Size dialog and Presenter recipe. Render the result rows in a table, including achieved nonparametric confidence and excess probability. Keep the old recipe reproducible.
- [x] Verify the published values, one-sided behavior, invalid inputs, legacy calculations and Presenter rerun. Exercise the dialog and report through their ordinary desktop entry points.

Source verification passed 34 tests across the power, tolerance, and neighboring modeling suites. The Windows Qt menu, dialog, and selected report were exercised for both solve directions. The planner reports requests beyond its 100,000-observation search limit explicitly. The Windows preview built successfully, and the published values were checked using the calculation code bundled in the EXE. The broader packaged smoke stopped at an R Workbench console assertion. The same assertion failed on the unchanged v119 source baseline.

## Next acceptance fixtures

- **Estimation** — Compare unknown-variance mean planning, binomial planning, and Poisson rate planning. For each, solve for sample size and then solve for margin of error with that size. Check the selected interval method and exposure. [Minitab power and sample size catalog](https://support.minitab.com/en-us/minitab/help-and-how-to/statistics/power-and-sample-size/supporting-topics/power-and-sample-size-analyses-in-minitab/)
- **DOE power** — Use a fixed Plackett-Burman design and a general full factorial with unequal numbers of levels. Compare the required replicates and achieved power, including the effect of center points where supported. [General full factorial reference example](https://support.minitab.com/en-us/minitab/help-and-how-to/statistics/power-and-sample-size/how-to/linear-models/power-and-sample-size-for-general-full-factorial-design/before-you-start/example/)
- **Screening and response surface** — Generate a design with center points, then fit the saved model on a blocked fixture. Compare design metadata, model terms, and fit results after reopening.
- **Quality** — Use crossed and expanded Gage R&R fixtures and subgrouped capability data. Compare variance components, selected estimation methods, and stored columns.
- **Time series** — Use one seasonal and one nonseasonal example. Compare AICc, AIC, and BIC candidate rankings, forecast limits, residual ACF/PACF, and forecast storage with a reference run. [Seasonal ARIMA reference example](https://support.minitab.com/en-us/minitab/help-and-how-to/statistical-modeling/time-series/how-to/forecast-with-best-arima-model/before-you-start/seasonal-example/)
- **Interchange and desktop** — Use native projects that include text and dates, stored designs, and output graphs. Verify which objects remain editable after export and reopening. Recheck keyboard navigation, graph selection, and SVG output in the packaged app.

The broader audit proceeds in priority order. Optional R output is outside this plan.

## Second increment — automatic ARIMA storage and MPX startup output

- [x] Expose separate fitted-value, residual, and forecast storage checkboxes in Forecast with Best ARIMA Model.
- [x] Select the newest renderable native saved graph when opening MPX. Fall back to the latest output when no saved graph can be drawn.
- [x] Verify synthetic selection tests and actual MPX startup using the PP pyrolysis lecture project. StatCraft previously chose the unsupported Response Optimization graph and showed no chart; it now opens the blocked Response Surface Regression chart.
- [x] Re-run regression suites for ARIMA, time series, DOE, Gage R&R, capability, MPX, worksheet navigation, graph output, Office export, and startup.

Implementation evidence: `tests/test_best_arima_dialog.py`, `tests/test_native_output_startup.py`, and the user-provided MPX were used. All focused assertions pass. Capability and full discovery pass their assertions but the test process reports a Windows Qt/Python teardown access violation. Isolated dotplot dialogs pass. Existing full packaged R console smoke remains a baseline failure.

Known time-series parity gap: automatic ARIMA ranks with conditional Gaussian likelihood. Minitab documents recursive likelihood. Seasonal log transformation remains unimplemented, so the published seasonal example is not a full numerical comparison.

Packaged desktop verification: `outputs/StatCraft-parity-next.exe` was launched as a standalone process and opened the user-provided PP pyrolysis MPX. Startup selected the saved “Response Surface Regression: Y versus Blocks, Temp °C, Veloc. ft-sec” result; its report and saved-output navigator were visible with the active worksheet. This verifies the MPX startup-output selection in the packaged UI, not full MPX fidelity. `git diff --check` passed. The local-integrations packaged smoke continues to fail at the same pre-existing R console text assertion observed on the unchanged v119 baseline.

Remaining parity work: the acceptance fixtures above are still open for estimation and DOE power, broader blocked response-surface and screening design validation, quality procedures, seasonal forecasting, and MPX object round trips. This increment did not complete the plan or establish an overall parity percentage.
