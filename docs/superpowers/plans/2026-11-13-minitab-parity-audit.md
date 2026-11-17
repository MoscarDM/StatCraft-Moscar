# Minitab parity audit — 2026-11-13

## Scope and evidence standard

Requested outcome: identify remaining Minitab parity work. This is a source and evidence audit, not an implementation pass or a new full regression run. Preserve the restored desktop interface. The abandoned Monarch redesign and Connect concept are excluded; optional R verification is separate from Minitab parity.

Baseline reference is the installed Minitab 22 family documented in retained REA artifacts. Current online documentation is useful for catalog coverage but may describe a newer version or separately licensed modules. Core desktop and Predictive Analytics should have separate acceptance lists. Cloud products and Model Ops are not silently included.

Status definitions: **confirmed gap** means inspected source explicitly lacks or restricts behavior; **partial** means a working implementation has a known boundary; **unverified** means comparative evidence is missing, not that the implementation is absent. Menu names, file counts, and test counts cannot establish a completion percentage.

## Priority backlog

### Default factorial designs and native response-surface save copies

- The default two-level design catalog now offers all published full and principal-fraction base designs for two through eight factors. The design picker selects the generators that the worksheet actually uses. Resolution describes the unblocked design. The default fractional route supports grouping complete replicates into blocks. Published confounding schemes and split-plot designs remain open. [Minitab generator reference](https://support.minitab.com/en-us/minitab/help-and-how-to/statistical-modeling/doe/supporting-topics/factorial-and-screening-designs/design-generators-for-2-level-designs/)
- Saved optimizer charts use a common response scale across factors and show the saved solution settings when present. The lecture MPX displayed both saved factor curves through the normal desktop result view.
- Response-surface refits on imported MPX projects now generate R verification metadata without changing the native worksheet metadata. In the lecture project all three recovered fits matched the saved coefficients, standard errors, residual mean square and error degrees of freedom. A copy reopened in StatCraft with all three refits and ten original output groups.
- The combined DOE, MPX, chart, Office export and Sandbox suite completed 211 tests with one skipped.

### Execution increment: saved native optimization curves

Added decoding of the saved optimizer figure's `NumPlotPoints`, `XPoints`, `YPoints`, factor/response labels, fitted response and desirability. Samples are split by factor and response into existing native line-chart panels; no native command or model is executed. Strict dimension, finite-number, ordering and size checks retain the unsupported warning for malformed inputs.

The PP pyrolysis project's Response Optimization output now produces two renderable panels, each with 20 saved points. Tested source immutability, malformed arrays, multiple responses, chart rendering and neighboring native output/model behavior: 68 tests passed. Offscreen rendering on the actual user project was inspected after loading installed verification fonts. The snapshot uses saved factor labels (including their original truncation). Interactive re-optimization and exact native optimizer layout are still open. No EXE rebuild or native Minitab save/reopen claim is made.

### Execution increment: factorial-family routing and MPX reproduction

Implemented the Plackett–Burman and general-factorial selections in Create Factorial Design using the existing calculated-preview planner. Setup buttons open the selected family; accepted settings persist until creation. Numeric and text levels, screening run counts, cancellation, and creation are covered. Catalog creation appends a worksheet without invoking the destructive leave-project path or clearing existing history. Split-plot remains disabled, and the default fractional-generator catalog remains open.

Verified a 20-run screening design through dialog → Presenter → MPX save → StatCraft reopen, preserving design configuration and columns. Verified a 3-by-2 numeric/text factorial produces six runs. Regression batch: 68 tests, one skipped; subsequent dialog/integration batch: 19 tests passed. The first attempted run exposed a test harness import-path issue and an incorrect single-worksheet `.statcraft` save target; both were corrected before the passing runs. Native Minitab reopening was not tested.

Read-only reproduction on the user's PP pyrolysis MPX found four worksheets and ten saved output entries. Seven entries are renderable: three response-surface regression results, two factorial plots, a contour plot and a surface plot. Response Optimization is not renderable; the two Central Composite Design entries are not classified as charts and must not be counted as missing graphs solely on that basis. Native optimizer rendering/refit and the wider native-save restrictions remain open. No user project was overwritten and no EXE was rebuilt in this increment.

| Priority | Area / status | Evidence and remaining work | Acceptance gate |
|---|---|---|---|
| 1 | MPX project editing and saving — partial | `mpx.py:263–358` rejects new native project creation, worksheet structural changes, history edits, date edits, some text edits, and type/metadata changes. `mpx_append.py` restricts appended columns to independent numeric columns and rejects structural changes with native DOE metadata. `app.py` rejects imported-project row deletion and variable erasure. | Fixture matrix for numbers, text, dates, missing values, multiple sheets and DOE: edit, save a copy, reopen in both applications, compare values, identities, design metadata and retained output. Keep unsupported operations explicit until safe. |
| 2 | Imported graphs and model editability — partial | `native_mpx_outputs.py:481` still has an unsupported-representation path. `native_mpx_models.py` limits recovered refit setups to declarative, unweighted, untransformed continuous response-surface models. A saved chart snapshot is not a rerunnable analysis. | Inventory each unsupported object in user projects. For every supported model, recover settings, rerun, edit graph, save and reopen. Cover the PP pyrolysis project, including its optimizer output. |
| 3 | DOE creation workflow — partial | The main dialog offers Plackett–Burman and general factorial creation and the default two-level catalog for 2–8 factors. Split-plot, the larger default factorial catalog, and native block generators remain open. | Every selectable design must generate the stated runs, factors, blocks, center points, resolution and generators. Verify split-plot analysis with whole-plot and subplot error terms. |
| 4 | DOE analysis and saved design continuity — unverified/partial | Existing response-surface, screening, special-design, planner and analysis modules are substantial. Prior plan still leaves blocked and screening acceptance fixtures open. Native DOE structural edits remain restricted. | Generate → analyze → residual diagnostics → factorial/contour/surface plots → optimize → store → reopen → refit. Compare block terms, hierarchy, aliasing, coded units and prediction intervals using fixed reference fixtures. |
| 5 | Statistical method/options gaps — confirmed examples | `variance_tests.py` explicitly excludes Bonett, simultaneous comparisons and variance intervals in that module. The modern one-variance dialog also states Bonett/robust methods are absent. `arima.py` uses conditional likelihood; prior plan records recursive-likelihood equivalence and log transformation as open. | Implement missing methods with published reference results and edge cases. Audit methods individually; do not infer all variance procedures lack intervals merely from this module. ARIMA needs candidate rankings, transformed forecasts and interval comparisons. |
| 6 | Quality and measurement systems — unverified | Crossed/expanded Gage R&R, attribute studies, capability and control-chart implementations exist. `capability_engine.py` uses an approximate Cpk/Ppk interval; this alone does not establish disagreement with Minitab. | Compare crossed/nested/expanded studies, unbalanced data, variance-component rules, subgroup handling, nonnormal capability, historical parameters, stages and rule tests. Verify stored columns and saved-project reruns. |
| 7 | Everyday desktop behavior — comparative audit needed | Original layout is restored. Existing plans and tests cover worksheet fill/navigation, navigator filtering, report precision, zoom/pan and legend behavior; these should not be listed as missing without reproduction. The recent focused Sandbox test is narrower than a visual acceptance pass. | Recorded task scripts in both apps: import, rename/insert/move/delete columns, Tab/Enter, undo/redo, delete sheet, choose named variables, create/edit graph, hover, copy/export, reopen. Fix reproducible differences in the existing layout. |
| 8 | Regression, ANOVA, mixed models and multivariate — unverified | Engines and dialogs exist; presence does not prove matching terms, contrasts, sums of squares, estimation or diagnostics. | Reference fixtures for categorical predictors, interactions, weights, missing rows, singular models, mixed effects, prediction and storage. Compare estimates, SEs, tests, intervals and row alignment independently. |
| 9 | Reliability and survival — unverified | Reliability engines include arbitrary censoring; therefore this is not a blank feature area. | Compare supported censoring patterns, distributions, estimation, confidence limits, percentiles, accelerated-life behavior and graphics. Build an option matrix before claiming unsupported analyses. |
| 10 | Predictive Analytics — implemented, parity unverified | `predictive_ml.py` contains forest, boosting, MARS and model-comparison implementations; `modern_app.py` exposes them. These are StatCraft implementations, not evidence of identical branded algorithms. | Compare validation splits, categorical encoding, missing data, tuning, pruning, weighting, model selection, importance, predictions and persistence. Track separately from core desktop parity. |
| 11 | Session commands and macros — partial | `session_commands.py` implements a command dispatcher, subcommands, scripts and loops, ending with an explicit unsupported-command error. This does not establish full Minitab macro-language support. | Diff supported commands and subcommands against the versioned reference. Run representative scripts; audit local/global macros, declarations, control flow, arguments and error behavior rather than assuming they work. |
| 12 | Distribution and release consistency — open | Recent improvements were source-only; no new EXE was built in the last two calculation passes. Source test success does not establish the installed executable's behavior. | Reproducible build, inspect bundled version, run acceptance fixtures against the exact EXE, and retain its hash and results. Include MPX, Office output, saved projects and optional R export. |

## Recommended execution sequence

1. Make the MPX limitations visible in a fixture-based compatibility matrix; reproduce the user project's unsupported charts and models. Close the highest-impact native workflow gaps first.
2. Complete the factorial-design dialog's family routing and design catalog, using existing engines where available. Validate displayed and generated designs together.
3. Complete one blocked response-surface and one screening workflow end to end, including save/reopen and model recovery.
4. Close confirmed method gaps, then validate quality, regression and reliability procedure families against external numerical references.
5. Run the restored desktop interaction checklist and package the verified source. Repeat this release check after each substantive batch.
6. Extend the command language and Predictive Analytics option matrices in their own tracks.

Each batch should name concrete workflows, fixtures and passing comparisons. Avoid percentage targets such as “10% per pass” until there is a versioned denominator.

## How to measure parity honestly

Create one row per procedure/workflow and relevant option combination. Record: reference version; UI entry; inputs/options; computation; report/graph; storage; persistence; numerical tolerance; StatCraft source/build; external expected result; observed result; status. Score implemented and externally verified coverage separately. Weight frequent MPX/DOE/worksheet tasks explicitly if a user-workflow score is desired. Report unreviewed items as unknown.

No defensible overall percentage follows from this audit. It is also not a claim that half the product is missing. Much of the remaining uncertainty is depth and verification inside existing features.

## Evidence inventory and limits

- Local REA resource evidence: `../output-workspace-rea-subset.json`, Evidence `ev_5b4e2e673fd6029b9cafee70dc98bbb232853d75d872ef31782981d541894abe`, identifies Minitab 22 `MtbResources.dll` SHA-256 `be284aeb444800e7ddced0e4071cb1341bd7bfafffe7acb8c1ef0113e6455cf3`.
- Optimizer resource evidence: `../optimizer-rea-verified.json`, Evidence `ev_c2916589e1b468632686068bb0c211ddca1f3831b0c12cc05f800d75de3983f6`, contains resource locations for that artifact. Resource evidence supports labels/structure, not numerical runtime behavior.
- The connected REA session returned **zero retained records** during this audit. Historical files were read locally; no fresh native execution or decompilation is claimed.
- Existing parity plan: `2026-11-12-minitab-desktop-parity.md`. Its documented prior test results are historical evidence, not a full-suite run today.
- [Official feature catalog](https://www.minitab.com/en-us/products/minitab/features/)
- [Official analysis categories](https://support.minitab.com/en-us/minitab-solution-center/analytics/)
- [Official session command reference](https://support.minitab.com/en-us/minitab/session-command-help/)
- [Discover Best Model scope and module requirement](https://support.minitab.com/en-us/minitab/help-and-how-to/statistical-modeling/predictive-analytics/how-to/discover-best-model-continuous-response/before-you-start/overview/)

This audit sampled implementation boundaries and feature families; it is not an exhaustive control-by-control census. Next work should turn this backlog into version-specific acceptance rows, not treat every unverified row as a demonstrated defect.
