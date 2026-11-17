# Visual and interaction testing — November 17, 2026

## Result: incomplete acceptance; supporting tests pass

Source: `1603748687ec93d6f07d7c172f325b792e9eb789`, v121.1.1. No application implementation changed during this run.

57 targeted regression tests passed in 13.379 seconds. They cover worksheet navigation/workflows, UI behavior, round-five actions, variable dialogs, graph options, output workspace, factorial workflow, MPX corpus, clipboard/export and Office export. Log: `artifacts/visual_qa/2026-11-17/regressions.log`.

The existing five-scenario stress harness completed with zero exceptions, including 100,000 rows × 20 columns, dark/compact layout, four output tabs, modal captures and MPX/session commands. Its fixture loaded successfully. These are supporting source tests with internal calls, not completion of the 54 real-input journeys.

All five final screenshots were opened and reviewed. Initial offscreen screenshots had pervasive missing glyphs despite automation success. The evidence runner now loads the existing `verification_fonts` helper and redirects organization/application QSettings into disposable INI storage before importing the harness. This changes the test process only. Final captures are under `artifacts/visual_qa/2026-11-17/supporting-captures/`.

## Observed findings

| ID | Severity | Observation | Evidence and disposition |
|---|---|---|---|
| VIS-001 | P1 Sandbox usability | Modern Sandbox startup shows a very tall yellow banner, leaving only a small output area and roughly five visible worksheet rows in the desktop capture. | Live desktop screenshot displayed in conversation. Not reproduced in normal mode; do not generalize to released UI. Needs size-policy inspection and repeat at known native resolution/DPI. |
| VIS-002 | P2 | Sandbox banner reads v112.0.0-dev while window title reads v121.1.1-dev. | Live screenshot and accessibility text. Confirmed version inconsistency. |
| VIS-003 | P1 test documentation | The runbook's `python -m statcraft` opens the older interface with large text buttons, different menus and no modern worksheet chrome. `launch_modern.py --sandbox` opens the intended modern interface. | Live launch comparison; `statcraft/__main__.py` routes to `app.main`, while `launch_modern.py` routes to `modern_app.main`. Correct the test launch instructions. |
| QA-001 | P1 evidence quality | The harness reports success even when all text renders as squares. | First offscreen run. Final images regenerated with verification fonts. The harness still needs a visual-review status rather than claiming screenshot existence is acceptance. |
| REVIEW-001 | Needs live verification | Boxplot extends below the visible output pane; top-level capture shows only the upper plot. | `03_charts_and_tabs.png`. A scrollbar exists, so this is not yet proof of an unreachable chart. Test fit/scroll/resize and compare reference before changing behavior. |
| REVIEW-002 | P2 candidate | R export controls appear in global toolbar, output toolbar and a large report translation panel; in split command view, little report content remains visible. | `05_mpx_and_session.png`. Compare scroll/reflow against intended optional-R workflow; no engine defect established. |
| QA-002 | P1 automation reliability | Native picker opened/cancelled and worksheet selection moved, but text insertion through desktop automation did not reliably appear. Later targeting/capture stalled; a supposed StatCraft screenshot returned Minitab pixels. | Do not classify missing input as an application bug without reproduction. `statcraft-sandbox-startup.png` is INVALID wrong-app evidence and must never serve as a baseline. |

The final offscreen images still contain small missing icon glyphs in some R/pinned controls. Native startup showed readable labels; native rendering must be checked before assigning this to the product rather than the offscreen font environment.

## What was visually checked

- Modern startup: maximized window confirmed; banner size and version inconsistency observed. Splash duration/restart not verified.
- Native File Open: opened and cancelled; successful typed-path import not verified.
- Empty worksheet: pointer selection and keyboard movement observed; data entry not reliably verified.
- Minitab 22 startup: launched and inspected; reference screenshot `minitab-startup.png` saved. Live reference has a compact toolbar, broad output area and lower worksheet pane.
- Supporting large worksheet: readable aligned names/data after font correction; conditional highlights visible.
- Supporting dark compact layout: numeric data and conditional highlights readable; long names truncated. Full-name tooltip not checked.
- Supporting graph tabs: active boxplot/nav title agree; partial chart visibility requires further testing.
- Supporting modal: StatGuide readable, close button visible. This does not exercise bad-input validation.
- Supporting MPX/session: date/numeric/text columns visible, command/history panes readable, fixture loaded. This is not the user's real lecture-project import journey.

## Remaining execution and blockers

No complete plan case is signed off: the 54 cases combine multiple checkpoints/configurations and reference comparisons. Partial observations must not be counted as 54 passes. The ledger records every case independently.

Real-input journeys require reliable targeting/text entry and recovery of the stalled test window. After resolving that, continue A/W worksheet cases, then V/G graph cases, M/D MPX/DOE cases, exports/persistence and stress. All unexecuted steps remain NOT RUN, not PASS or skipped.

No packaged EXE was visually signed off. Candidate `dist/StatCraft.exe` SHA-256: `8F867E779475A856585AC01A63FBB68BD311C4E10E1A51134FF609ADC6E45DB3`. Its hash identifies the candidate only; it does not establish equivalence to the source.

No native DPI/multi-monitor acceptance, Office viewer inspection, hover/3D acceptance, autosave recovery or exhaustive menu inventory was completed. No Minitab parity percentage can be inferred from these results.

## Continuation: broader coverage and dialog review

The extended isolated run passed **514 tests in 33.765 seconds** across 68 matching UI/export/settings test modules. This overlaps the earlier 57-test run; do not add their counts together as unique coverage. Log: `artifacts/visual_qa/2026-11-17/extended-regressions.log`. A separate 83-test targeted run also passed, including painted-element hover handling, response-surface dialogs/catalog and DOE planner tests. Hover tests include mouse-move events and tooltip calls, but native pointer/tooltip appearance still requires desktop acceptance.

Candidate EXE verification **passed**: version 121.1.1 matched source; smoke fixture rows=5, MPX bytes=5601, XLSX bytes=2311. Structured result: `artifacts/visual_qa/2026-11-17/exe-verification.json`. This improves package verification but does not sign off the EXE visually.

Ten additional offscreen dialog screenshots were generated with installed verification fonts and individually opened for visual review:

- Histogram type chooser: four readable illustrated choices, selection outline and visible OK/Cancel.
- Histogram variables: identifiers plus `Strength (N)` and `Temperature (°C)` names visible, Scale/Labels and Select controls visible.
- Generic regression variable selector: names/units, response/predictor fields, visible focus, filter and Reset/OK/Cancel.
- Factorial creation: all five design-family choices and setup buttons visible, including split-plot.
- Response-surface creation, Available Designs, Designs, Factors, Options and Results: text/tables/buttons readable at captured logical dimensions; no essential button clipping in those captures.

Evidence: `artifacts/visual_qa/2026-11-17/dialog-captures/`. The matrix matches the run-count values shown in the user's earlier reference screenshot at the cells inspected. This is static screenshot comparison; existing matrix interaction tests, including every numbered cell, passed separately.

**Additional finding VIS-004 (P2, default fidelity):** fresh two-factor response-surface parent shows 14 runs. Opening Designs shows the 13-run catalog row selected with Custom center points=6 and a calculated run count=14. The user's reference shows Default center points=5 for the 13-run unblocked row. The custom settings explain the arithmetic; this is a surprising initial default/selection presentation, not evidence that the engine calculated runs incorrectly. Capture: `response-surface.png` and `surface-designs.png`. Decide whether to initialize from the chosen catalog default or explicitly distinguish a modified design in the selected row.

**Desktop blocker confirmed again:** launching the exact candidate via the desktop launcher failed with `accessibility window-opened handler did not become ready`. Earlier native windows had stale/ghost entries and wrong-window captures. Repeated attempts therefore do not establish a native application failure; they establish that this desktop automation session cannot currently provide reliable native acceptance evidence. Native real-input, scaling, pointer, EXE appearance and Office-viewer cases remain blocked pending a working desktop-control session.

No fixes to the application or normal installed executable were made. The only executable code added is a disposable evidence runner under the artifact folder, using redirected test settings and existing app/test interfaces.

## Desktop recovery: root cause and verified workaround

The shell's restricted environment enumerated only three processes and could not see the normal desktop's StatCraft process. An approved host-session inspection found the exact previously launched Sandbox window (handle 657916), owned by Python PID 2860, `Responding=False`. The DWM window was a ghost of this hung test window. Thus the earlier stale captures and missing process observations were not a valid test of StatCraft functionality.

After checking the exact window identity and empty Untitled Sandbox title, only that test process was stopped. The candidate `dist/StatCraft.exe --sandbox` was launched through an approved host-session command, leaving the installed application and unrelated user windows alone. Desktop inventory then returned a single fresh EXE-owned StatCraft window, handle 3083788.

The supported `@oai/sky` desktop client successfully captured this window. Its `type_text` insertion still silently failed, while `press_key` with printable keys worked. The reliable test-input workaround is direct key events, with a fresh window capture after each action. Do not declare the general text-insertion service repaired.

Verified in the actual packaged EXE through native input:

- Click row 1/C1, direct key `1`, Tab: value 1.0 committed and active cell advanced to row 1/C2.
- Direct key `2`, Enter: value 2.0 committed and active cell advanced to row 2/C2. Evidence: `native-keyboard-entry.png`.
- Graph menu → Histogram → Simple opened the actual variable dialog.
- Double-clicking the first available variable transferred it into Graph variables.
- OK generated an immediately active histogram graph and matching navigator entry. Evidence: `native-histogram-created.png`. One numeric observation is sufficient for this reachability check, not distribution accuracy/hover acceptance.
- Right-clicking the graph opened a full context menu containing Edit Graph, Edit Selected Object, Edit Scales and export actions. Activating Edit Graph was not confirmed; parent-window targeting of this transient menu remains to be resolved. The corresponding menu screenshot must not be labeled an editor-pane capture.

The oversized Sandbox banner and stale v112 banner version reproduce in the packaged EXE. The banner consumes enough height that the newly created histogram is only partly visible without scrolling/resizing.

For future native runs, launch GUI processes in the normal Windows session via approved host execution, select the freshly returned EXE-owned window, reject ghost/DWM windows, use direct key events where text insertion is unreliable, and refresh screenshots after every action. This resolves the stalled-window blocker and permits native interaction tests to continue; it does not complete the remaining 54-case acceptance matrix.

## Live continuation: imported graphs and edit/save/reopen

The same candidate EXE was tested in Sandbox and normal mode with a disposable copy of the 613,590-byte lecture MPX.

**Verified native checkpoints:**

- Lecture MPX opens, with four worksheet tabs, typed/named columns and a navigator containing saved model/graph entries. Optimization Plot is present and renders two curves with saved fit/settings reference lines.
- Output-only mode removes the worksheet. In normal mode this gives substantially more graph space; the screenshot is `native-normal-optimizer-full.png`. Essential horizontal labels still require scrolling at the captured viewport.
- Right-click → Edit Graph opens the right-side Options pane (`native-normal-edit-graph-pane.png`). A double-click on the menu action succeeded where earlier single-click attempts had not been confirmed. Do not diagnose earlier uncertain menu clicks as a StatCraft command-routing defect.
- Using the actual Title field and leaving it with Tab changes the chart title to `Optimizer visual check` (`native-normal-title-edited.png`).
- Save Project opens **Save MPX copy**; after an explicit native-copy disclosure, saving `lecture-edited.mpx` succeeds. This is expected protection of native data, not silent in-place save.
- A fresh EXE window reopens that saved file. Clicking Optimization Plot shows the edited title (`native-title-reopened.png`). The archive contains the change at `/statcraft/native-output-views.json`; all 123 original archive entry names are retained plus that extra entry (entry-byte equality not claimed). Evidence summary: `native-save-verification.json`.
- Original lecture file hash still matches the untouched test input copy. No original project was edited.
- In the separate one-observation histogram fixture, double-clicking the plotted area opens Edit Graph Object and brushes row 1. Cancel closes the object dialog; the highlighted bin and worksheet row remain visibly linked (`native-brushed-row.png`). Exact object hit-selection and full brush semantics still need broader fixtures.

**Confirmed findings / remaining concerns:**

- VIS-001 expands in Sandbox output-only mode: the yellow banner grows while the data worksheet disappears, leaving the saved graph partly hidden. Normal mode has no such banner. Classify this as a Sandbox layout defect rather than a general released-chart defect.
- VIS-005 (P2): on opening both the original copy and edited copy, Response Optimization is selected but **Report** is the active inner tab; the user must click **Optimization Plot**. This reproduces the earlier complaint about needing an extra graph-tab click for imported visual outputs. New histogram creation did activate its graph immediately.
- VIS-006 (P2/trust): the imported optimizer report displays an Executive Brief saying `StatCraft completed evaluation for 'Response Optimization: Y'.` Opening a saved native result is not evidence that StatCraft reran that evaluation. Wording should identify imported/saved output.
- **Invalid fixture F5:** the user's `Downloads/quiz1.mpx` was already 115 bytes, timestamp October 30, containing JSON startup diagnostics (`frozen`, `maximized`, `splash_dismissed`, `rows`, `project_loaded`) rather than MPX data. The test copy had the same content before launching it. Original was not overwritten in this pass. Its import cannot validate legitimate MPX compatibility; restore an authentic file before that specific regression is retried.

This pass establishes the imported optimizer edit/save/reopen path for this one fixture in the actual EXE. Other graph families, Office viewer exports, native tooltip appearance, 3D manipulation and exhaustive multi-configuration cases remain outstanding. Automated totals are unchanged; this continuation added native evidence rather than rerunning the same automated suite.

## Fix pass

Implemented the confirmed defects:

- Sandbox banner has fixed vertical size policy (46 pixels at 1280×900 and 1024×700 in verified renders), dynamic version, and accurate source-versus-packaged wording. Diagnostics also use the current version.
- Imported outputs containing graphs now open the graph first, even when report tables exist. Explicit Report/table navigation remains supported, with regression coverage.
- Imported native summaries state that they are saved output and have not been recalculated.
- Fresh two-factor CCD initializes from the actual unblocked catalog entry: 13 runs and five default center points. Custom options remain available.
- `python -m statcraft` now launches the modern interface; runbook EXE paths corrected.
- Autosave now uses a filesystem data folder rather than deriving a path from a Windows registry key; Sandbox uses its own workspace.
- Visual harness loads verification fonts, isolates organization/application settings into test INI storage, marks visual review pending, rejects missing fixture/modal captures, and includes EXE startup failure in its exit status.

Regression tests first reproduced five UI defects and three harness defects. Additional autosave regression reproduced the invalid registry-derived path. Focused suite then passed 30 tests. Existing assertions intentionally expecting the old six-center default and Report-first behavior were updated; explicit report-navigation assertions remain unchanged.

Recovered `outputs/quiz1-recovered.mpx` from the intact `Downloads/quiz1.mpx.bak`: ZIP verified and Presenter opened 1,200 rows/one column. The corrupted original and backup were preserved.

At the user's request, both desktop JavaScript sessions were reset and the identified Codex capture helper was stopped; its process exit was verified. Subsequent verification uses offscreen renders and tests, so no new native screen-capture session was started. Yellow desktop capture borders should therefore be released. Native visual acceptance of this new build remains outstanding until the user permits capture again.

Final fix validation: 514 broad tests passed after the autosave fix; 30 focused checks passed (overlapping the broad set); five harness-contract/capture tests passed after the isolation review correction. The review identified pre-imported QSettings aliases and lingering process settings as an isolation risk; the harness now restores aliases, process scope and closes its window before restoring globals. A pre-imported-module regression verifies that behavior.

Rebuilt EXE: `outputs/visual-fixes/StatCraft.exe`, SHA-256 `8655a87aae8e52c70aed74ad4269a9a3064a85923539aad39178587528208ec0`. Packaged smoke verification passed: version 121.1.1, five fixture rows, MPX save/reopen, XLSX output. Installed executable was not replaced. Review and test evidence supports these specific fixes; unexecuted visual-parity cases remain pending.
