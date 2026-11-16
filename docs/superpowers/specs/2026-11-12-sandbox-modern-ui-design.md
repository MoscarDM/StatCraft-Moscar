# StatCraft Sandbox Modern UI Design

## Intent

Create a modern, carefully finished StatCraft desktop experience inspired by the supplied Monarch Finance light and dark dashboard references. The images are visual references for hierarchy, spacing, navigation, cards, charts, and theme quality; StatCraft keeps its own identity and statistical workflow. Build and evaluate the redesign in Live Sandbox so the regular app remains visually unchanged until the user explicitly approves broader adoption.

## Current state

- StatCraft is a PySide6 / Qt Widgets desktop application launched from `launch_modern.py`.
- `ModernWindow(sandbox_mode=True)` is selected by the `--sandbox` argument and displays an obvious live-sandbox title/banner.
- Sandbox already keeps a scratch workspace under `.sandbox_workspace`, but the light/dark value and UI-mode value currently use the same `QSettings("StatCraft", "StatCraft")` namespace as normal mode. Theme preference isolation is required before visual iteration.
- The current application is a dense statistical workspace: menus and toolbars, navigator, result/report area, worksheet grid, graph editing pane, and many dialogs. The design must preserve its data density and interaction model where the financial dashboard reference has no equivalent.
- Charts and dialogs already have theme-aware helpers, but component styling is distributed across shared stylesheets and local `setStyleSheet` strings.

## Goals

1. Give the app a contemporary, cohesive light and dark visual system with deliberate typography, spacing, surfaces, borders, controls, selection, focus, and hover states.
2. Translate the references into StatCraft-appropriate patterns: calm neutral canvas, clear persistent navigation, concise utility toolbar, well-defined work surfaces, restrained accent color, and readable chart/report hierarchy.
3. Keep the worksheet fast and compact, preserving column names, row/column headers, keyboard navigation, selection, editing, and existing context actions.
4. Keep statistical output, charts, and procedure dialogs legible at normal desktop sizes and usable at common display scaling settings.
5. Make every visual experiment selectable only in Sandbox, including isolated theme and layout preferences.
6. Let the user inspect and test the work in Sandbox before any release, commit, or GitHub publication.

## Non-goals

- Replacing Qt Widgets with React, shadcn/ui, Qt WebEngine, or a new frontend stack.
- Copying Monarch's name, logo, proprietary icons, finance-specific content, or exact screen composition.
- Changing statistical calculations, project-file formats, or analysis behavior as part of the visual pass.
- Removing established menus, keyboard shortcuts, or power-user worksheet density to make the app resemble a consumer finance dashboard.
- Publishing or merging the Sandbox redesign without a separate user decision.

## Approaches considered

### A. Modernize the existing Qt interface in Sandbox — recommended

Build a reusable StatCraft theme/token layer and apply it to the existing widgets, starting with the main shell and then the worksheet, reports/charts, and procedure dialogs. Keep native Qt tables, charts, menus, and dialog behavior. This minimizes migration risk and gives the largest part of the application one coherent visual language.

### B. Put a React/shadcn shell inside Qt

Add a web frontend and bridge it to Python. This could use shadcn components directly, but introduces another UI technology, packaging/runtime dependencies, and a cross-language interface. It is a poor first move for an app whose core is an editable native worksheet plus many statistical dialogs.

### C. Restyle only the main shell

Update the top-level window, navigation, and welcome screen, leaving analysis dialogs and internal work surfaces largely as they are. This is faster to preview but likely creates the same visible inconsistency the design is meant to solve.

**Chosen direction:** A, with staged review so the design can be adjusted before it reaches every dialog.

## Visual direction

- **Light theme:** soft neutral application canvas; white or near-white work surfaces; warm StatCraft orange as a controlled brand accent; cool, low-contrast separators; dark ink for primary text and muted gray for secondary text.
- **Dark theme:** deep charcoal canvas; slightly lighter charcoal surfaces; restrained gray separators; the same accent family tuned for contrast; avoid pure black backgrounds and over-bright large regions.
- **Typography:** Windows Segoe UI with appropriate system fallbacks; clear title/body/metadata hierarchy; use monospaced faces only for code and command output.
- **Shape and elevation:** consistent small-to-medium radii for cards, menus, and floating panes; subtle borders and limited shadows so information remains primary.
- **Navigation:** persistent, compact left navigation for major work areas; contextual navigator remains available for worksheet outputs and analyses. Preserve access to existing menus and shortcuts.
- **Workspace composition:** keep the statistical work area dominant. Use cards and stronger spacing for summaries and key actions, while keeping the grid and dense result tables compact. Charts retain readable labels, axes, legends, and hover behavior.
- **Theme parity:** all surfaces, dialogs, selection/focus indicators, reports, custom-painted charts, and utility panes must remain intentional in both themes.

## Sandbox isolation and safety boundaries

- In Sandbox mode only, read and write UI preferences from a distinct `QSettings` organization/application scope (or an equivalent isolated settings store). At minimum isolate theme, UI mode, window geometry, and any new layout preferences. Normal mode retains its existing settings namespace and behavior.
- Keep the existing explicit Sandbox title/banner and scratch workspace. Do not make the redesigned theme the default for normal mode.
- Source edits will exist locally for the user to test, but no release build, commit, push, pull request, or GitHub publication is part of this work. The user decides later whether any part should leave Sandbox.
- Do not change or overwrite the user's MPX/MWX projects during visual validation. Use disposable or copied fixtures when a workflow needs mutations.

## Delivery phases

1. **Isolation and visual inventory:** route Sandbox settings to isolated storage; capture a baseline of the current Sandbox in light and dark mode; inventory core surfaces and identify one representative screen per surface type.
2. **Theme foundation:** define semantic color, typography, spacing, radius, border, elevation, and interaction tokens in one Qt-native theme module; generate/compose QSS from those tokens rather than scattering unrelated palette literals. Keep graph color semantics separate from decorative UI colors.
3. **Application shell:** update window background, title/utility area, toolbar controls, persistent navigation, selected/hover states, status area, welcome screen, and Sandbox banner.
4. **Primary workspace:** update worksheet frame and headers, navigator, output tabs, report/summary surfaces, and graph-options pane. Preserve grid density, selection contrast, keyboard movement, and existing actions.
5. **Procedure dialogs and auxiliary views:** migrate shared dialog primitives and common dialog patterns first, then apply them to analysis dialogs, settings, and JMP/R panels where appropriate. Do not change analysis semantics.
6. **Sandbox review loop:** build/launch via the existing Sandbox entry point; inspect screenshots at realistic window sizes and both themes; collect user feedback; correct visual and behavioral regressions before expanding the phase.

## Acceptance criteria

- Sandbox can switch light/dark themes and remember its own choice without changing the normal app's saved theme or UI mode.
- The normal app launch retains its pre-redesign stylesheet and settings behavior throughout this work.
- Light and dark screenshots show consistent surfaces, typography, borders, hover/selection/focus states, charts, and dialogs; neither theme has unreadable text or unthemed high-visibility panes.
- The worksheet remains dense enough for statistical work and still supports naming columns, editing cells, keyboard navigation, selecting ranges, context menus, and existing column/worksheet actions.
- Existing MPX opening and saved-output display continue to work; chart hover/editing and report readability are preserved.
- No statistical result, stored-column, export, or project persistence behavior changes as a side effect of the visual work.
- All review builds and manual testing occur through Sandbox. No GitHub/release action occurs before a separate user approval.

## Builder review

Reviewed against `ModernWindow`, `sandbox_hub`, `get_theme_stylesheet`, `set_dark_mode`, `chart_theme`, and `dialog_theme`. The key implementation risk is the currently shared `QSettings` namespace; the first implementation phase must isolate it before theme changes. Qt Widgets is the chosen rendering stack. A cross-framework React bridge is excluded from the first implementation because it would increase packaging and interaction risk without improving the core worksheet workflow.

## Decisions left to implementation

- Exact token values and typography scale should be tuned against real Sandbox screenshots rather than set from the reference images alone.
- Migrate dialog families incrementally, prioritizing the most visible and frequently used analysis flows.
- Keep all existing controls available unless a later user-approved UX design explicitly changes information architecture.
