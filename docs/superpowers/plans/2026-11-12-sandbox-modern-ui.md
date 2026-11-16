# StatCraft Sandbox Modern UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cohesive, Monarch-reference-inspired light and dark StatCraft interface in Live Sandbox while preserving the native Qt worksheet and statistical workflows.

**Architecture:** Keep the PySide6 / Qt Widgets stack. Isolate Sandbox UI settings, add a semantic theme-token module, then migrate the application shell, worksheet/output surfaces, charts, and dialogs in reviewable stages. Normal mode continues using the existing appearance and settings until a later, separate approval.

**Tech Stack:** Python 3.10+, PySide6 / Qt Widgets, Qt stylesheets/palettes, existing QPainter charts, unittest/pytest already used by the repository, and Codex computer-use screenshot review for the live Sandbox.

**Spec:** `docs/superpowers/specs/2026-11-12-sandbox-modern-ui-design.md`

## Global Constraints

- Build and visually test changes only through Live Sandbox (`launch_modern.py --sandbox`).
- Do not publish, push, open a PR, or change the normal app's default theme as part of this plan.
- Use the supplied Monarch images as the aesthetic reference: soft neutral canvas, crisp white/light surfaces, warm orange accent, consistent iconography, spacious summary areas, clean chart presentation, and a restrained charcoal dark mode.
- Preserve StatCraft identity and statistical density; do not copy Monarch branding, icons, financial information architecture, or exact pixel layout.
- Keep the editable worksheet, MPX/MWX workflows, menus, shortcuts, charts, and procedure behavior working.
- Keep the Qt Widgets stack; do not add React, shadcn, WebEngine, or another UI runtime.
- Keep custom chart color semantics distinct from decorative interface colors.
- Do not make any user project edits during screenshot validation; use scratch or disposable project files.
- Keep implementation changes local and reviewable; no release or GitHub action is in scope.

## Review Focus

1. **Sandbox setting leakage:** toggling theme/UI mode or clearing recents in Sandbox must not affect normal mode. Pin this to Task 1 settings tests.
2. **Normal-mode visual leakage:** the standard launch must retain the pre-redesign palette and stylesheet until separately approved. Pin this to Task 2/3 theme-selection tests.
3. **Dense worksheet usability:** styling must not clip headers, reduce usable column count excessively, or break Tab/Enter movement, cell editing, selection, and context menus. Pin interaction assertions to Task 4 and inspect the real Sandbox grid at common scaling.
4. **Theme readability:** muted labels, selection, focus, chart axes, and dialog fields must remain readable in both themes. Pin semantic token contrast tests to Task 2 and inspect representative charts/dialogs in Task 5/6.
5. **Project and analysis preservation:** opening MPX/MWX and showing saved results must behave as before after theme changes. Pin startup and output checks to Task 7 using a copy of a representative project.

---

## File Map

- Create `statcraft/settings_scope.py`: return the correct `QSettings` namespace for normal and Sandbox mode.
- Create `statcraft/ui_theme.py`: semantic light/dark tokens, Qt palette application, and reusable QSS generation.
- Modify `statcraft/modern_app.py`: select isolated Sandbox settings; apply the new theme conditionally in Sandbox; restyle shell, worksheet/output containers, and theme controls.
- Modify `statcraft/modern_worksheet.py`: align worksheet grid/header/selection metrics with shared tokens without changing editing or navigation behavior.
- Modify `statcraft/chart_theme.py`: source neutral plot/surface colors from the semantic theme while preserving statistical series colors and existing graph options.
- Modify `statcraft/dialog_theme.py`: migrate shared dialog styles to semantic tokens and shared control states.
- Modify shared dialog/view modules only when required to remove hardcoded visual overrides: `statcraft/variable_dialogs.py`, plus highest-visibility procedure dialogs selected during inventory.
- Add focused tests under `tests/` for settings scopes, theme token selection/contrast, and Sandbox-only application of the new stylesheet.
- Add screenshots only to ignored `.sandbox_workspace` review artifacts; do not add reference images or generated screenshots to release assets.

## Task 1: Isolate Sandbox Settings

**Files:**
- Create: `statcraft/settings_scope.py`
- Modify: `statcraft/modern_app.py:681-689, 2078-2093, 3696-3745`
- Test: `tests/test_settings_scope.py`

**Interfaces:**
- Produce `settings_for_mode(sandbox_mode: bool = False) -> QSettings`.
- The normal namespace remains `QSettings("StatCraft", "StatCraft")`.
- The Sandbox namespace uses a distinct organization, `QSettings("StatCraft Sandbox", "StatCraft")`.
- `ModernWindow` stores this as `self._settings` and uses it for theme, UI mode, and recent-project menu state. Existing sandbox behavior that avoids adding opened projects to normal recents remains.

- [ ] **Step 1: Write failing settings-scope tests**
  - Assert normal and Sandbox settings return distinct `organizationName()` values and share the application name.
  - Assert writes under the Sandbox namespace do not change the normal namespace's `dark_mode`, `ui_mode`, or `recent_projects` values. Use a temporary QSettings INI path and clear test state in teardown.
- [ ] **Step 2: Run the focused test and confirm the new helper is missing.**
- [ ] **Step 3: Implement `settings_for_mode` and route all ModernWindow theme/UI-mode/recent-menu reads and writes through `self._settings`.**
- [ ] **Step 4: Run `pytest tests/test_settings_scope.py -q` and confirm both scopes remain independent.**
- [ ] **Step 5: Run existing recent-project and theme-related tests.**

## Task 2: Add the Semantic Theme Foundation

**Files:**
- Create: `statcraft/ui_theme.py`
- Modify: `statcraft/modern_app.py:162-280, 688-726, 2086-2118`
- Test: `tests/test_ui_theme.py`

**Interfaces:**
- Define immutable `ThemeTokens` with semantic roles for `window`, `surface`, `surface_alt`, `text`, `text_muted`, `border`, `accent`, `accent_hover`, `selection`, `focus`, `success`, `warning`, and `danger`.
- Provide `theme_tokens(dark: bool) -> ThemeTokens`, `application_stylesheet(dark: bool) -> str`, and `apply_application_palette(app: QApplication, dark: bool) -> None`.
- For `sandbox_mode=True`, use the new theme. For normal mode, preserve the current stylesheet/palette path unchanged during this project.

- [ ] **Step 1: Write tests for both token sets, required semantic roles, valid QColor values, readable text/muted-text contrast, and stable mode selection.**
- [ ] **Step 2: Run `pytest tests/test_ui_theme.py -q` and confirm it fails because the module does not exist.**
- [ ] **Step 3: Implement the token dataclass and palette/QSS functions.**
  - Tune token values against the supplied references: warm restrained orange; light neutral canvas and bright surfaces; charcoal dark canvas and layered charcoal surfaces.
  - Use shared font, radius, spacing, border, and focus conventions in the generated QSS.
  - Keep typography legible and Qt-native; avoid relying on unsupported browser-only CSS effects.
- [ ] **Step 4: Run the focused theme tests and confirm contrast thresholds pass.**
- [ ] **Step 5: Add a Sandbox-only theme-selection test proving normal mode still calls the legacy stylesheet/palette path.**

## Task 3: Modernize the Application Shell

**Files:**
- Modify: `statcraft/modern_app.py` main window construction, `_create_layout`, `_create_status_bar`, `set_dark_mode`, and `set_ui_mode`
- Modify: `statcraft/sandbox_hub.py` only if Sandbox entry-point labeling/launch context needs a visual or isolation correction
- Test: `tests/test_sandbox_theme_selection.py`

**Interfaces:**
- `ModernWindow(sandbox_mode=True)` selects `application_stylesheet` and isolated `_settings`; normal mode keeps legacy styling.
- Keep existing menu actions, toolbar command connections, status actions, theme toggle, startup update behavior, and `[LIVE SANDBOX]` indicator.

- [ ] **Step 1: Write a focused test for Sandbox/normal theme selection and isolated setting persistence.**
- [ ] **Step 2: Run it and confirm Sandbox currently uses the normal theme and shared preference scope.**
- [ ] **Step 3: Style the main background, title/utility strip, toolbar buttons, persistent navigation, current-location heading, status strip, welcome surface, and Sandbox indicator.**
  - Follow reference hierarchy: compact persistent left navigation with clear icon/label states; restrained top utility area; rounded but subtle working surfaces; consistent spacing; orange for active/primary states.
  - Do not remove existing menus or hide established commands.
- [ ] **Step 4: Run focused tests, then launch both standard and Sandbox modes and confirm only Sandbox has the new appearance.**

## Task 4: Modernize the Worksheet and Output Workspace

**Files:**
- Modify: `statcraft/modern_worksheet.py`
- Modify: `statcraft/modern_app.py` `_create_layout`, worksheet/output split, navigator, result tabs, and worksheet headers
- Test: existing worksheet tests plus `tests/test_sandbox_workspace_visual_contract.py`

**Interfaces:**
- Worksheet painting reads semantic tokens from the owning window, with a legacy fallback when normal mode is active.
- Preserve existing table model, delegate, navigation, editing, selection, context-menu, column-name-row, and scroll behavior.

- [ ] **Step 1: Write/extend assertions for column-name row visibility, selected-cell contrast, and Tab/Enter movement in the Sandbox palette path.**
- [ ] **Step 2: Run the focused worksheet tests and confirm they exercise currently shared/legacy visual state.**
- [ ] **Step 3: Restyle grid canvas, column and row headers, name row, selected cell/range, navigator tree, output tabs, split handles, and view controls using theme roles.**
  - Keep row height and column width compact enough to show many observations at once.
  - Use clear borders and a distinct active cell similar in clarity to the reference's selected navigation state.
- [ ] **Step 4: Run worksheet navigation, column manipulation, worksheet tabs, and MPX startup-output tests.**
- [ ] **Step 5: Launch Sandbox and inspect the worksheet at 100% and Windows display scaling representative of the user's setup.**

## Task 5: Modernize Reports, Charts, and Graph Editing Surfaces

**Files:**
- Modify: `statcraft/chart_theme.py`
- Modify: `statcraft/modern_app.py` report header, result summary cards, output actions, and graph options pane integration
- Modify only chart-specific modules whose neutral plot colors bypass the shared theme, beginning with `statcraft/modern_charts.py` and `statcraft/modern_expanded_charts.py`
- Test: existing chart interaction/theme tests and `tests/test_sandbox_chart_theme.py`

**Interfaces:**
- `get_chart_theme(widget)` remains the public chart-theme lookup and resolves its neutral colors from the semantic theme where available.
- Preserve series-specific statistical colors, accessible line distinctions, graph hover tooltips, brushing, editing, and export.

- [ ] **Step 1: Add tests for neutral chart canvas, axes/grid/labels, and callout colors in both themes while preserving series palette values.**
- [ ] **Step 2: Run focused chart tests to confirm which current neutral colors are hard-coded.**
- [ ] **Step 3: Migrate chart-neutral surfaces and report/output framing to shared theme tokens.**
  - Use a light card/plot surface in light mode and layered charcoal surfaces in dark mode, with careful axis/grid contrast.
  - Keep report metrics and key conclusions hierarchically clear without turning statistical tables into oversized dashboard cards.
- [ ] **Step 4: Run graph hover, edit-graph, brushing, SVG export, and graph theme tests.**
- [ ] **Step 5: Inspect one histogram, one saved MPX graph, and one dense model report in both Sandbox themes.**

## Task 6: Migrate Dialogs and Auxiliary Workbenches

**Files:**
- Modify: `statcraft/dialog_theme.py`
- Modify: `statcraft/variable_dialogs.py` and the most visible procedure dialogs identified by a Sandbox inventory; retain each dialog's current signals and settings payloads
- Modify: theme update methods for JMP/R workbench panels only if they are currently attached and visibly inconsistent
- Test: existing dialog suites plus `tests/test_sandbox_dialog_theme.py`

**Interfaces:**
- `dialog_stylesheet(dark: bool)` keeps its current signature but is generated from semantic theme tokens.
- Existing dialog APIs, default selections, variable labels, keyboard behavior, validation, and `get_settings()` payloads remain unchanged.

- [ ] **Step 1: Add tests for shared dialog surface/control roles and theme-aware labels/fields/buttons.**
- [ ] **Step 2: Run representative scatter, regression, DOE, and graph-edit dialog suites to establish behavior baselines.**
- [ ] **Step 3: Migrate common dialogs and variable selectors to shared typography, fields, buttons, focus, error, and spacing styles.**
- [ ] **Step 4: Apply shared styles to high-visibility analysis dialogs by family without changing analysis behavior.**
- [ ] **Step 5: Run focused dialog suites for defaults, settings payloads, keyboard use, and validation in both themes.**
- [ ] **Step 6: Inspect one representative dialog from each family in the live Sandbox.**

## Task 7: Full Sandbox Review and Regression Gate

**Files:**
- Modify only items found during visual review in the files above
- Store local captures/notes in ignored `.sandbox_workspace/ui-review/`
- Update the plan checklist with results; do not add captures to tracked release assets

**Interfaces:** No new product API. The normal application remains on the legacy theme path.

- [ ] **Step 1: Run focused tests for settings isolation, theme tokens, worksheet interactions, chart interactions, and representative dialogs.**
- [ ] **Step 2: Launch Live Sandbox from the existing sandbox entry point and verify the title/banner identifies the test instance.**
- [ ] **Step 3: Capture/inspect light and dark screenshots for the welcome screen, populated worksheet, saved MPX output/report, chart, and representative dialogs.**
- [ ] **Step 4: Verify Sandbox theme/UI-mode/recents changes do not leak into a regular app launch; verify regular app still has its previous appearance.**
- [ ] **Step 5: Verify the user fixture is not modified and MPX/MWX open/show-output workflows remain functional.**
- [ ] **Step 6: Run `git diff --check`, confirm no generated screenshots or packaging artifacts were staged/added, and hand the Sandbox build to the user for visual review.**

## Self-Review

- **Spec coverage:** isolation, design tokens, main shell, worksheet, outputs, charts, dialogs, and Sandbox review each have an owning task.
- **Step granularity:** each checklist step has one testable outcome; broad visual migration is split by separately reviewable interface surface.
- **Interface consistency:** task boundaries define the settings helper, semantic token API, palette/QSS API, and public chart/dialog theme functions.
- **Review focus:** the five likely failures are pinned to focused tests or named Sandbox inspection steps above.
- **Scope:** no React/shadcn migration or statistical behavior change; no production default, release, or GitHub publication.
