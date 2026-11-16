# StatCraft Live Desktop Launch & Codex Visual Inspection Runbook

This runbook defines the live Windows desktop launch procedure and visual inspection checklist for `scripts/visual_stress_suite.py` and the packaged `StatCraft.exe` binary.

---

## 1. Live Desktop Launch Commands

Run these commands from `work\statcraft` inside an interactive Windows desktop session (do **not** set `QT_QPA_PLATFORM=offscreen` during live visual QA):

### A. Automated Visual Stress Suite (Python Source)
```powershell
$env:PYTHONPATH = ""
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:STATCRAFT_TESTING -ErrorAction SilentlyContinue

..\statcraft-build-env\Scripts\python.exe scripts\visual_stress_suite.py --out-dir artifacts\visual_qa
```

For a fast smoke check (10k × 10 worksheet instead of 100k × 20):
```powershell
..\statcraft-build-env\Scripts\python.exe scripts\visual_stress_suite.py --out-dir artifacts\visual_qa --quick
```

### B. Live Desktop Launch (Python Source & Packaged `StatCraft.exe`)
Launch the interactive desktop application from Python source:
```powershell
..\statcraft-build-env\Scripts\python.exe -m statcraft
```

Launch the packaged `StatCraft.exe` directly on the Windows desktop:
```powershell
Start-Process .\dist\StatCraft\StatCraft.exe
```

Or run the visual stress suite with a live `StatCraft.exe` startup smoke check attached:
```powershell
..\statcraft-build-env\Scripts\python.exe scripts\visual_stress_suite.py --out-dir artifacts\visual_qa --exe .\dist\StatCraft\StatCraft.exe
```

---

## 2. Visual Inspection Checklist (`01`–`05`)

Inspect `artifacts\visual_qa\manifest.json` (`unhandled_exceptions == 0`, all 5 scenarios `"status": "ok"`) and open every generated PNG screenshot:

### Global Checks (All Screenshots)
- [ ] **No clipped/truncated UI:** Zero clipped or truncated dialog buttons, menu items, toolbar controls, or status-bar badges.
- [ ] **Header & grid alignment:** Table headers (`C1`, `C2`, column names) align cleanly with grid columns after font changes, horizontal/vertical scrolling, sorting, and column hiding/unhiding.
- [ ] **No frozen or orphaned frames:** Zero white/frozen `"Not Responding"` frames and zero orphaned floating popups after closing tabs or dialogs.
- [ ] **Clean typography:** Zero tofu (`□`) glyphs or overlapping labels.

### Per-Screenshot Checks
1. **`01_large_worksheet.png` — Large Dataset Stress (100k × 20)**
   - [ ] Worksheet renders populated rows/columns cleanly after rapid scrolling, sorting, and autofill.
   - [ ] Conditional formatting highlights (`out_of_control` red tint and `in_list` green tint) are visible and legible.
2. **`02_dark_compact_layout.png` — Dark Mode & Compact `1024×700` Layout**
   - [ ] Dark Mode palette applies consistently across menus, toolbars, worksheet grid, and output pane.
   - [ ] `Consolas 11` data font renders crisply without clipping row heights or column headers at `1024×700`.
3. **`03_charts_and_tabs.png` — Graph & Multi-Tab Thrash**
   - [ ] Chart axes, tick labels, legends, and titles are readable with zero overlapping text or cut-off legends.
   - [ ] Multi-tab bar and `Close Current Graph` leave active tabs clean with zero blank canvases.
4. **`04_dialogs.png` — Dialog & Bad-Input Torture**
   - [ ] Modal dialog (`StatGuide` / `Manage Conditional Formatting Rules` / `Hide or Unhide Columns`) fits cleanly within its frame with readable text and unobstructed `Close` / `OK` / `Cancel` buttons.
5. **`05_mpx_and_session.png` — MPX Open + Session Command Stress**
   - [ ] `.mpx` project data loads into the worksheet and `Command Line/History` pane is visible.
   - [ ] `MTB >` command history and session output render cleanly without layout overlap.

---

## 3. Defect Logging Rule

Any visual flaw observed in a screenshot (`01`–`05`) or during live desktop interaction **must** be logged as a concrete bug fix paired with a regression screenshot or widget test before release sign-off.
