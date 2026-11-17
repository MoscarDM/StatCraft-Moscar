# StatCraft Visual and Interaction Parity Stress-Test Plan

> For the implementing model: execute this plan in ordered batches using superpowers:executing-plans. This is a test-design and inspection handoff, not permission to redesign the application. Record a visible failure before changing application behavior. Preserve Antigravity's work.

**Goal:** Discover and fix the differences that a person sees and encounters while using StatCraft, even when the statistical engine is correct.

**Architecture:** Keep the existing Qt Widgets desktop. Add real-input journeys and evidence review around the existing visual harness. Compare matched Minitab 22 and StatCraft states, then pair each confirmed defect with a focused regression test and a before/after capture.

**Tech stack:** Python, PySide6, unittest, existing Windows desktop automation, packaged StatCraft EXE. Use REA for installed Minitab resource/shortcut evidence where helpful; use actual desktop observation for focus, layout, interaction and timing.

**Spec:** The user's November 17 request: inspect UI and visually observable expected behavior, plan stress tests for another model to implement, preserve current functionality and Minitab-style desktop layout.

## 1. Baseline and evidence honesty

Planning inspection found a clean checkout at `1603748687ec93d6f07d7c172f325b792e9eb789`, version 121.1.1. Recheck HEAD and working changes before executing: Antigravity may continue editing.

Recent changes inspected:

- `1603748`: exclusive column-name/data-cell selection and unclamped worksheet splitter.
- `dd1b4a0`: round-five menu actions, report pad, column ordering, brushed indicators, crosshair/annotations, duplicate graphs, 3D reset, MPX corpus tests.
- `699e2ec` and the November 15 REA plan: freeze, autosave, split view, graph tools, command/history behavior and accelerator mapping.
- Existing `scripts/visual_stress_suite.py` and `tests/test_visual_stress_harness.py`: five screenshot-producing scenarios.

**This planning pass did not execute those scenarios or compare live app renderings.** Desktop inventory found neither StatCraft nor Minitab running. All cases below begin NOT RUN. Earlier user screenshots and complaints are regression priorities, not proof that the current version still fails. Existing roadmap completion and test totals do not establish visual parity.

### Confirmed test-coverage weaknesses (source inspection, not observed UI defects)

1. The harness directly calls presenter/window methods for many actions. This bypasses menus, variable picking, modal focus, validation and click routing.
2. The harness test asserts nonempty PNG files, not readable or correct pixels. A blank or wrong screenshot can pass.
3. Dialogs are dismissed by timers. Only one of the three gets a screenshot; the fallback can capture the main window instead and still pass. No actual bad input is entered in the purported bad-input scenario.
4. The MPX scenario can report success with `loaded_mpx=False` if its fixture is missing.
5. EXE smoke records process survival after 2.5 seconds; the script's final success expression does not include EXE smoke failure. Process survival is not a ready, usable window.
6. The harness constructs `ModernWindow()` without explicit sandbox isolation, changes appearance/settings and shares mutable state across scenarios. Verify isolation before running it against a user's profile.
7. Widget captures do not establish native file-picker behavior, multi-monitor placement, popup stacking, pointer hover or packaged rendering correctness.

## 2. Global constraints and comparison rules

- Planning deliverable only in this pass. The executor adds tests first; make narrowly scoped fixes only for reproduced failures.
- No Monarch/shadcn migration, recoloring campaign, engine rewrite, blanket revert, GitHub publishing, installed-EXE replacement or edits to original user MPX files.
- Use separate disposable fixture copies and isolated settings/autosave directories. Verify the existing `--sandbox` path and `settings_scope.py` wiring before use; do not assume an arbitrary constructor is isolated.
- Record source commit, dirty diff, EXE absolute path/version/SHA-256, Minitab version, OS, screen size, DPI, app zoom, font, locale and fixture hash.
- Compare identical data, analysis options, window size, DPI and theme. Light mode is the Minitab fidelity baseline. Dark mode is StatCraft usability coverage unless a matching reference exists.
- Preserve StatCraft branding. Compare layout hierarchy, affordances, semantics and visual clarity; do not require Minitab logos, license UI or exact font rasterization.
- Never treat an unsupported feature's presence in a menu as a pass. An enabled action must complete its advertised workflow; a limitation must be visible and truthful.
- REA strings/resources establish labels and static hints, not whether an action is clickable or what happens at runtime. Cite evidence IDs/paths and separately record live observations. Do not decompile unrelated engines for this task.
- If Minitab cannot run, mark reference-dependent checks BLOCKED or REFERENCE NEEDED. User screenshots support only their visible states. Do not invent the reference behavior.
- Do not reset the user's settings or alter OS display scaling without authorization. Use an approved test profile/session for scale changes. Qt scale-factor simulation is supplemental, not native DPI proof.

## 3. Review focus

1. Column names, data cells, frozen panes and duplicated worksheet views disagree about selection or position: W01–W08.
2. A rendered graph exists but a person cannot create, edit, inspect or export it: V01–V05, G01–G10, E01–E04.
3. A saved MPX displays fewer outputs or associates a graph with the wrong worksheet: M01–M05.
4. Attractive DOE choices are inert, contradictory or fail to affect the resulting design: D01–D06.
5. Clean test runs hide clipping, wrong-window focus, settings leakage or stale packaged code: H01–H05, A01–A05, S01–S05.

## 4. Fixtures to prepare once

Create fixture copies under `artifacts/visual_qa/<run-id>/fixtures/`. Never overwrite the source files. Include a machine-readable inventory of columns, types, counts and hashes.

| ID | Exact preparation | Purpose |
|---|---|---|
| F0 | Empty project, then one empty worksheet. | Startup, empty/disabled states. |
| F1 | 24 rows: C1 `Run` = 1..24; C2 `Strength (N)` = `560 + 2*i + (i%3)` for i=1..24; C3 `Group` cycles A/B/C; C4 `Temperature (°C)` = `170 + 5*(i%4)`; C5 `Date` = consecutive dates from 2026-01-01; C6 name `Length µm — very long column name for clipping checks` with values i/10; C7 blank name, numeric i*i. | Small deterministic data, names/types/units and known hover values. |
| F2 | Copy F1; missing C2 at original rows 3 and 17; missing C3 at row 9; blank C4 at row 12; duplicate name C6=`Strength (N)` if allowed. Keep untouched F1. | Missing-row alignment, duplicate names, validation. |
| F3 | F1 plus histogram-boundary column `[0,0,1,1,2,2,3,3]`, constant column of 24 fives, extreme values column alternating 1e-9/1e9, and a categorical column with 24 distinct labels. | Bin edges, degeneracy, scientific notation and crowded legends. |
| F4 | Existing deterministic large data generator: seed 42, 100,000 rows × 20 columns; quick version 10,000 × 10. Add separate wide fixture 100 rows × 250 columns named `Variable_001`..`Variable_250`. | Vertical/horizontal navigation and variable-list stress. |
| F5 | Copy `C:\Users\funny\Downloads\quiz1.mpx`, if available. | Earlier MPX import regression. Missing file is BLOCKED, never silently skipped. |
| F6 | Copy `C:\Users\funny\Downloads\MFGEN 401 Lecture 22 - Example Response Surface Design PP pyrolysis yield.mpx`. Inventory current content in Minitab before counting expected outputs. Historical inspection found four worksheets and ten output groups; verify against hash. | DOE native outputs, optimizer, worksheet association, save/reopen. |
| F7 | Disposable project with 20 worksheets, each with distinguishable data, and 50 generated outputs, including repeated titles and long worksheet names. | Navigator/tab identity and repeated interactions. |
| F8 | In-app DOE fixtures: 2-factor CCD; 3-factor Box–Behnken; 8-factor/16-corner-run fractional design; PB20; mixed 3×2 general factorial; supported split-plot design. Record settings and expected run count before creation. | Reachability of modern engine features. |

If a fixture cannot be expressed in both apps, document the difference and compare the common subset. Do not silently coerce dates/text into numbers.

## 5. Environment matrix and evidence contract

Run all P0/P1 journeys at 1920×1080, 100% scale, light mode in source and the exact candidate EXE. Repeat critical dialogs/grid/graph flows at 1366×768 and 150% scale. Run a compact 1024×700 window, 200% scaling, dark mode and two monitors as separate stress configurations where supported. If there is insufficient usable space, scrolling must keep every required action reachable. Unsupported/unavailable configurations remain explicit coverage gaps.

For every case record:

`case_id, run_id, fixture_hash, app_build, configuration, reference_kind, reference_path_or_id, action_sequence, expected, actual, interaction_status, visual_status, duration_ms, before_capture, checkpoint_captures, after_capture, reviewer, defect_id`.

Statuses: NOT RUN, PASS, FAIL, BLOCKED, NOT APPLICABLE (with reason). Overall PASS requires both interaction and visual PASS. An automated capture begins visual NOT RUN until a reviewer has opened it. Missing/wrong/blank screenshots fail evidence collection. A platform limitation is not PASS.

Capture the full app/window plus cropped details as needed. Capture dialogs while open, visible focus/selection, validation messages, hovering tooltip and changed result, rather than only final main-window screenshots. Use short screen recordings or timed frame sequences for splitter/hover/3D/drag behavior. Mask only changing timestamps, private account identity and caret blinking for diffs; never mask the feature being tested. A newly captured image is not automatically an approved baseline.

Severity: P0 crash/data loss/wrong worksheet or data represented; P1 blocked common task, misleading selection/graph or unreachable required control; P2 usable but confusing/clipped/inconsistent; P3 cosmetic polish. Promote any lower-priority case to P0 if it reveals data loss.

## 6. Ordered test catalog

Each row specifies setup, real user actions, expected visible behavior and required evidence. Use mouse/keyboard or accessible controls. Internal calls may prepare data but must not perform the action under test. Match precise shortcuts/defaults against the reference before asserting them.

### Batch A — daily worksheet work and application shell (first)

| ID / priority | Setup and actions | Visible pass criteria / capture |
|---|---|---|
| A01 P1 | F0; launch exact EXE from closed state, wait for readiness, minimize/restore, close and reopen. | Brief splash ends; one usable main window opens maximized per user requirement; no hidden modal or stale white panel. Capture splash and ready window with timing. |
| A02 P1 | F1; resize and drag worksheet/output splitter near each extreme and back; toggle output/worksheet/split layouts. | Both panes can regain usable space; no hard clamp preventing intended layout, header collapse or unreachable divider. Capture both extremes and restored state. |
| A03 P1 | F1; open every top-level menu; hover each toolbar icon; use representative icon and its corresponding menu command. | Icons readable, tooltips identify action/shortcut, enabled state matches context, both routes perform same action. Capture menus and a tooltip; inventory every action. |
| A04 P2 | F7; scroll navigator, collapse/expand worksheet groups, change output tabs, close middle/last output, reopen from navigator. | Active title/worksheet/result agree; long names remain distinguishable; closing one output does not delete another. Capture selection before/after. |
| A05 P1 | F1; move window between monitors and reopen a child dialog after monitor removal where a test setup is available. | Dialog remains visible, owned by correct window and usable at new scale. Capture dialog bounds; unavailable setup BLOCKED. |
| W01 P1 | F1; click C2 name cell, edit name; then data cell row 4; alternate 20 times, including Shift-click ranges. | Only intended name/data selection active; typing changes exactly the intended location; highlight and caret agree. Capture both selections. Prior regression in v121.1.1. |
| W02 P1 | F0; type 1, Tab, 2, Enter, 3; repeat Shift+Tab/Shift+Enter, arrows, F2, Home/End, Ctrl+Home/End and Ctrl+Enter; test while editing and while navigating. | Commit/cancel and destination match observed Minitab behavior; no swallowed/doubled values, lost edit or accidental menu activation. Capture active cell after each transition. |
| W03 P1 | F1; insert a column before C2 and after last; rename, move, duplicate, clear cells and delete a selected column through context menus. Undo/redo each supported action. | Headers, names, types and values move together; selection remains understandable; destructive scope clear; undo restores exact state. Capture before/after and saved/reopened copy. |
| W04 P1 | F1; select rectangle, copy/paste to empty range and second worksheet; include tabs, blanks and mixed types; cut/paste; cancel overwrite prompt. | Rectangular alignment preserved; no extra header/data row, silent type loss or paste into wrong sheet; cancelled operation unchanged. Capture selection and pasted range. |
| W05 P1 | F1; rename/add/duplicate/delete worksheet from tabs and menus; cancel deletion; then delete disposable copy; close last worksheet. | Accessible action, clear target, cancellation keeps data, valid active sheet/empty state; no invisible surviving sheet. Capture tab menu, prompt, result. |
| W06 P1 | F4; freeze/unfreeze, hide/unhide, resize columns and scroll both directions to boundaries; edit visible cell. | Column-name row, identifiers and cells align; frozen area correct; no duplicate selection or displaced editor. Capture scroll boundary and edited cell. |
| W07 P1 | F1; split worksheet view; scroll panes independently, edit shared cell, change active worksheet, close split. | Shared data updates consistently; active selection and headers honest; no stale copy or edit sent to wrong sheet. Capture both panes before/after. |
| W08 P2 | F2; apply sort/filter and conditional formatting through dialogs, edit a value affecting a rule, undo, hide/unhide columns. | Whole-row relationships remain intact for requested scope; visible formatting updates and remains readable; filters visibly indicated. Capture rule dialog and resulting rows. |

### Batch B — variable dialogs and graph interaction

| ID / priority | Setup and actions | Visible pass criteria / capture |
|---|---|---|
| V01 P1 | F1; Graph > Scatterplot > Simple; choose Y then X by double-click, Select button and keyboard in separate runs. | List shows column identifier AND header name; active destination obvious; variables land in intended Y/X slot; only valid selection enables submission. Capture chooser and filled pair table. |
| V02 P1 | F2/F4-wide; search/filter list; choose duplicate/long names and blank-name column; type C2-C6 where supported; scroll to final variable. | Identity unambiguous, full name discoverable, no truncation that conceals identity, filtering does not substitute a different column. Capture list and resulting plot labels. |
| V03 P1 | F1; fill options, open child Scale/Labels/Data Options; Cancel child, then parent; reopen and use reset/F3 where supported. | Cancellation semantics match reference; cancelled changes do not silently create output; default/reset affects intended fields only; focus returns sensibly. Capture child before/after and reopened parent. |
| V04 P1 | F2/F3; submit empty variables, invalid numeric field, incompatible text column, identical axes, constant response and missing-data case. | Clear actionable error at relevant field or truthful result; no traceback, hidden message, silent success or stuck modal. Capture each error and successful correction. |
| V05 P1 | F1; repeat representative histogram, regression, ANOVA, capability, ARIMA and DOE dialogs keyboard-only with Tab/Shift+Tab, Space, Enter, Escape. | Logical focus order, visible focus, no trap or premature submission while selecting variables. Capture focused controls and final result. |
| G01 P1 | F1; create histogram, scatter and boxplot through menus. | Graph appears immediately as active output, not raw data/debug text; title, variable names, units, legend and worksheet association correct. Capture each initial result. |
| G02 P1 | F3; histogram with explicit boundaries; hover every bin, an edge and empty background; repeat after resize/zoom. | Tooltip identifies correct bin/count consistent with displayed bars and configured boundary convention; tooltip hides/moves correctly and does not obstruct permanently. Capture tooltip plus pointer location. |
| G03 P1 | F2; scatter X=Run, Y=Strength; hover known rows, missing-row neighbors and overlapping points; brush points if supported. | Tooltip and brush map to original worksheet rows, not compressed nonmissing indices; units and values correct. Capture tooltip and matching highlighted row. |
| G04 P1 | F1; right-click graph > Edit Graph; edit title/subtitle/footnote and axis text; close/reopen options. | Expected right-side options pane opens; edits affect selected graph, remain readable and persist appropriately; no unrelated debug bar. Capture menu, pane and changed graph. |
| G05 P1 | F1; edit axis range/log scale/reference line, series color/symbol, legend and annotation through actual exposed controls; try invalid limits. | Changes visibly apply only where intended; invalid values recover cleanly; options checked/unchecked state reflects chart. Capture controls and result. |
| G06 P1 | F1; generate 3D scatter and surface; drag to rotate, zoom, reset; hover where supported. | Perspective genuinely changes with depth; axes and labels follow correctly; Reset restores orientation; no flat plot masquerading as 3D. Record motion and reset frame. |
| G07 P1 | F7; duplicate graph, edit duplicate, close original, reopen duplicate, save/reopen project. | Independent edit state and correct identity; duplicated graph remains usable; no accidental mutation of original. Capture original/duplicate comparison. |
| G08 P2 | F1/F3; create matrix, marginal, contour, probability, interval, heatmap, time-series, grouped bar and pie graphs via menu. | Every required variable/options route reachable; correct graph type, readable panels/legends, no placeholder or debug payload. Capture each chooser and output. |
| G09 P1 | F1; enable crosshair/brush, add and move annotation; resize; select another output; use next/previous brushed-row shortcuts. | Tools track actual plot coordinates and active output; no stale annotation/brush overlay; toolbar checked state accurate. Capture overlay and worksheet link. |
| G10 P2 | F3; long titles/24-category legends; minimize plot area, restore, zoom 50/100/200% if available; light/dark. | No clipped data region or overlapping essential labels; legend can be read; fonts and contrast usable. Capture worst-size and restored state. |

### Batch C — MPX and DOE workflows

| ID / priority | Setup and actions | Visible pass criteria / capture |
|---|---|---|
| M01 P1 | F5/F6; File > Open using native picker; navigate each sheet and each output. | No array error; expected data/outputs listed with correct grouping; selecting an entry shows the intended visual/report. Capture navigator plus each distinct output type. |
| M02 P1 | F6; open contour, surface, factorial and optimizer saved outputs; hover and open Edit Graph. | Real saved information visible; supported edits work; unsupported native editing clearly distinguished from a rendered snapshot, with no deceptive controls. Capture each output and edit state. |
| M03 P0 | F6 copy; edit a cell/name, add an output, Save As new MPX; close and reopen it. | All original worksheets/outputs retained, edits retained, native vs added outputs distinguishable where needed; original hash unchanged. Capture before/after inventory and output. |
| M04 P1 | F6; switch worksheets while selecting outputs with similar titles; refit an imported model through available UI and cancel once. | Correct source sheet/columns and options visible; new result does not replace unrelated original; cancel leaves state unchanged. Capture source selection and resulting entry. |
| M05 P1 | Disposable malformed/truncated MPX copy and nonexistent recent-file path; attempt open then open valid F1 project. | Clear error, existing project not discarded, app remains usable and recent list not misleading. Capture error and recovered valid window. |
| D01 P1 | F8; open response-surface Available Designs matrix; select valid and blank cells using mouse/keyboard; proceed to Designs. | Supported choices visibly select and control subsequent configuration. Blank/unavailable cells cannot pretend to select a design. Capture selection and dependent dialog. Compare actual reference semantics, not assumed clickability. |
| D02 P1 | 2-factor CCD; switch blocked/unblocked, default/custom center points, alpha default/face-centered/custom, replicates and block-on-replicates. | Enable/disable dependencies correct; displayed run count/blocks and resulting worksheet match choices; invalid alpha/count corrected in place. Capture each dependency change and created design. |
| D03 P1 | F8; create PB20, 3×2 mixed factorial and supported fractions including 8-factor/16-corner-run; vary replicates. | Correct family/dialog labels, factor names/types preserved, corner versus total runs clear; supported runs above 16 usable. Arbitrary invalid run counts are explained, not silently rounded. |
| D04 P1 | F8; switch DOE families/factor counts repeatedly; revisit Factors/Options/Designs; cancel then reopen. | Stale settings cannot leak incompatibly across families; selections/counts consistently update; cancel creates no worksheet. Capture each switch and final configuration. |
| D05 P1 | Supported split-plot; assign whole/subplot factors and blocks then create/analyze via UI. | Factor roles, randomization structure and analysis labels are visible and consistent; no engine-only unreachable feature. Capture setup and visible report/diagnostics. |
| D06 P1 | F6; response-surface analysis through UI > contour/surface/factorial plots > optimizer. Change response/terms/range. | Same intended model/response carried through; axes and units meaningful; unsupported continuation is explicit rather than fabricated output. Capture chained states. |

### Batch D — exports, reports, persistence and discovery

| ID / priority | Setup and actions | Visible pass criteria / capture |
|---|---|---|
| E01 P1 | F1 histogram/heatmap and analysis report; export DOCX/PPTX using menu/native picker; open in Word/PowerPoint when available. | Actual Office documents with readable chart/table, correct title and orientation; no HTML/raw panel arrays. Capture exported app page/slide; unavailable viewer is BLOCKED for visual check. |
| E02 P1 | F1; copy graph into PowerPoint/Word and export PNG/SVG/PDF where exposed; compare light/dark source. | Correct chart, readable text, no missing fonts or truncated axes; transparent/background treatment sensible. Capture pasted/exported artifact at readable scale. |
| E03 P1 | F6; export worksheets to XLSX; open in Excel; inspect all sheets and numeric/text/date cells. | Names, order, counts and values usable; charts not advertised as converted if omitted. Capture workbook tabs/types and compare source. |
| E04 P1 | F7; select multiple outputs, add to report pad, reorder/remove, print preview/save report. | Explicit selection/order honored, complete pages, no blank clipped graphs, removal limited to report membership as advertised. Capture report pad and preview. |
| E05 P1 | F1; optional R export for a supported analysis; inspect and copy/save script; cancel once. | User can find export; readable selectable script reflects chosen columns/options; no abandoned Connect workflow required, no unexpected execution. Capture export UI and saved-file confirmation. |
| P01 P1 | F1; change worksheet zoom/font, panes, selection direction; restart isolated app. | Supported settings persist consistently; no change leaks into production settings; startup remains usable. Capture before/restart. |
| P02 P0 | Disposable project; dirty edits then New/Open/Close/Exit using Save/Discard/Cancel in separate runs. | Correct prompt/target; Cancel preserves window/data, Save writes selected copy, Discard only discards intended state. Capture prompts and resulting active project. |
| P03 P1 | Isolated autosave fixture; make edits, wait configured interval, close only test process unexpectedly, relaunch test profile. | Recovery UI is understandable, recovered data matches saved snapshot, user can decline; original projects unaffected. Capture recovery and restored worksheet. |
| P04 P1 | F1; Ctrl+L command pane, type valid and invalid commands, traverse history, return to worksheet; repeat using menu. | Focus moves predictably; command/error text readable; output and active sheet correspond; pane close restores expected focus. Capture input, error and recovery. |
| P05 P2 | F0/F1; enumerate all visible menu/submenu/context actions and toolbar buttons in empty, populated, selected-output and modal states. | Each action classified reachable/disabled-with-reason/missing/broken; no untested menu hidden behind a feature checklist. Capture menus and link each action to a journey or remaining-case record. |

### Batch E — repetition, responsiveness and accessibility

| ID / priority | Setup and actions | Visible pass criteria / capture |
|---|---|---|
| S01 P1 | F4; drag scrollbars top/bottom 30 times, switch to wide fixture, type/edit/copy at boundaries. | No frozen/blank grid, headers stay aligned, input applies once to visible cell. Record timings and boundary captures. |
| S02 P1 | F7; 100 output switches, 30 graph creates/closes, 30 dialog open/cancels, 20 worksheet switches. | No orphan dialogs, progressive slowdown, stale graphs or mismatched title. Record memory after warmup and each cycle block; growth must be investigated, not assumed a leak. |
| S03 P1 | Valid large analysis/import; interact with window during processing, try double-submit and Cancel if exposed. | Busy state visible; no duplicate runs from double-click, no silently lost input; cancellation either safe or clearly unavailable. Record heartbeat/interaction delay, completion and recovery. |
| S04 P1 | Critical A/W/V/G/D flows across scale/window matrix and light/dark; keyboard-only pass. | Controls reachable, focus visible, text readable, no color-only essential state. Use 4.5:1 normal-text and 3:1 large-text/control contrast as proposed usability targets, not claims about Minitab. |
| S05 P1 | Execute A01,W01,W02,V01,G01–G06,M01,M03,D01–D03,E01 against exact packaged EXE. | Same visible behavior as source; no missing icons/fonts/resources/Office templates; no stale version. Preserve EXE hash and paired captures. |

Responsiveness targets are proposed StatCraft quality budgets, not measured Minitab guarantees: ordinary focus/selection feedback within 200 ms (p95 across 30 samples); small dialog/graph readiness within 2 seconds after warmup; operations exceeding 2 seconds visibly communicate progress/busy state. Log hardware and elapsed times. Capture event-loop stalls over 500 ms and any OS Not Responding state. Treat violations as triage evidence; distinguish expensive valid computation from broken interaction. Do not add arbitrary sleeps and call that readiness.

## 7. Implementation tasks for the next model

### Task 1 — make evidence collection trustworthy

Files: modify `scripts/visual_stress_suite.py`, `tests/test_visual_stress_harness.py`, and `docs/superpowers/plans/visual-stress-runbook.md`; create `tests/test_visual_evidence_contract.py` and `scripts/visual_qa_cases.json`.

- [ ] Add negative tests first: missing MPX fixture, failed EXE launch, missing dialog capture, wrong-window capture and unreviewed screenshot must not produce overall PASS.
- [ ] Isolate settings, fixture copies and autosave using existing settings infrastructure. Add assertion that production settings/files remain unchanged.
- [ ] Keep original five scenarios as quick supporting coverage. Separate `automation_status` from `visual_review_status`; require explicit review before overall PASS.
- [ ] Replace fallback main-window image for missing dialog with explicit failure. Require ready-window check for EXE, not mere process liveness.
- [ ] Define `visual_qa_cases.json` with the IDs above, batch, priority, fixture IDs, action steps, expected checkpoints and configuration requirements. A record can remain NOT RUN; it cannot disappear from totals.
- [ ] Have each run emit the evidence fields from section 5 and list all unexecuted cases. Make the script exit nonzero for execution failures; do not mislabel pending review as completed verification.

### Task 2 — create matched reference captures and execute Batch A

Files: extend `tests/test_worksheet_navigation.py`, `tests/test_worksheet_workflows.py`, `tests/test_ui_behavior_parity.py`, `tests/test_minitab_parity_round5.py`; create `docs/qa/visual-interaction-findings.md`.

- [ ] Record Minitab installed-version identity and REA reference resources using the installed path in the November 15 evidence plan. Capture real dialog/navigation behavior for disputed semantics.
- [ ] Execute A/W journeys using visible input in both apps; save intermediate screenshots and annotate differences. Do not mutate user worksheets.
- [ ] Log observed defects with severity, reproducible steps and expected/actual evidence. Add focused UI regression tests for confirmed failures only.
- [ ] Fix P0/P1 failures locally if execution scope includes fixes; inspect likely owners `statcraft/modern_app.py`, `modern_worksheet.py`, `worksheet_tab_strip.py`, `output_workspace.py`. Do not use broad stylesheet changes as a substitute for interaction fixes.

### Task 3 — execute Batch B and close graph/selection defects

Files: extend `tests/test_variable_dialog_enhancements.py`, `tests/test_graph_options_specialized.py`, `tests/test_output_workspace.py`; add focused graph-hover interaction tests as needed. Owners: `statcraft/variable_dialogs.py`, individual graph dialogs, `modern_charts.py`, `graph_frame.py`, `graph_options_pane.py`, `native_output_chart.py`.

- [ ] Run all V/G cases through real controls, including intermediate chooser/options/error states.
- [ ] Test hover against known row/bin data and screen coordinates after resize, not only a tooltip helper return value.
- [ ] Capture actual 3D movement, right-side editing and immediate graph selection. Reopen saved edited graph to verify visible persistence.
- [ ] Compare before/after images for each fix; require no regression to adjacent graph families.

### Task 4 — execute Batch C and Batch D

Files: extend `tests/test_factorial_catalog_workflow.py`, `tests/test_mpx_corpus_end_to_end.py`, `tests/test_export_and_clipboard_fidelity.py`, `tests/test_office_export.py`; owners include `doe_dialogs.py`, `modern_app.py`, `native_mpx_outputs.py`, `office_export.py`, `xlsx_export.py`.

- [ ] Verify actual interactive design selection and option propagation before counting a DOE family covered.
- [ ] Capture MPX navigator/output inventory before editing and after reopening a copy. Verify original hash unchanged.
- [ ] Open exports in their target viewers. ZIP structure/unit-test validity alone does not satisfy visual acceptance.
- [ ] Run persistence/recovery only in disposable isolated projects; preserve explicit unsupported states.

### Task 5 — execute Batch E and final review

Files: extend the visual harness/runbook and findings; use existing `scripts/verify_built_executable.py` as supporting package verification.

- [ ] Run repetition/performance matrix and inspect every required screenshot, including errors and compact layouts.
- [ ] Run focused regression tests appropriate to actual fixes. Existing numerical suites need broad reruns only if numerical code changed.
- [ ] Test the same source revision in the candidate EXE; produce package identity and source/EXE comparison.
- [ ] Deliver ranked defect list, fixed/retested items, evidence index and explicit remaining gaps. Do not replace installed software or publish without the user's instruction.

## 8. Gates and reporting

Batch progression: A → B → C → D → E. Log unrelated issues immediately but do not interrupt a reproducible journey unless there is data-loss risk. Resolve P0 first, then common-workflow P1, then P2/P3. Each batch ends with reviewed captures, reproducible findings and retested fixes; source tests alone cannot close it.

Release acceptance for this scope:

- No unresolved P0 or common-workflow P1 in executed core journeys.
- All P0/P1 cases executed on source and candidate EXE in the baseline environment; critical scale variants reviewed.
- Every mandatory screenshot actually inspected; no masked clipping, blank/wrong-window capture or automatic baseline approval.
- MPX originals untouched; all expected saved data and outputs retained in tested copies.
- Remaining unsupported features, unavailable reference comparisons and environments explicitly listed.
- All menu inventory items have a disposition; every claimed supported UI path has at least one real-input journey.

Use separate metrics: executed/required cases, interaction passes, visually reviewed passes, matched-reference coverage and unresolved defects by severity. Denominator includes NOT RUN/BLOCKED cases. Do not call this a percentage of the entire Minitab product. A menu that opens and a screenshot that exists are neither feature parity nor visual approval.

### Defect record template

`ID; severity; source/EXE identity; configuration; fixture/hash; exact actions; Minitab/reference evidence; expected visible behavior; actual behavior; before screenshot/video; affected workflow; likely owner; regression test; fix summary; after screenshot; reviewer; status.`

### Final handoff report

Summarize what a user can now do correctly, the most noticeable remaining problems, cases not executed and why, and links to evidence. Keep the complete per-case ledger in the artifact folder. Do not state that the UI is equivalent to Minitab merely because this finite suite passes.
