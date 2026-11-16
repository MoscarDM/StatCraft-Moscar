# REA-Driven UI Behavior & Look Parity Plan (2026-11-15)

## REA Evidence Summary
Inspected `C:\Program Files\Minitab\Minitab 22\Resources\1033\MtbResources.dll` via `rea:inspect_pe_resources` (3,137 resources: `RT_ACCELERATOR 8445`, `RT_STRING`, `ASSISTANTMENU.CSS`, `PRINT.CSS`) and `C:\Program Files\Minitab\Minitab 22\Mtb.exe` via `rea:inspect_managed_artifact` (`x86_64` native PE32+).

### Observed Gaps vs Minitab 22 (`RT_ACCELERATOR 8445` & `RT_STRING`)
1. **`Ctrl+Enter` (`0x0d`, ID `46046`):** *"Move the active cell to the top of the next column."* Missing in `WorksheetTable.event()`.
2. **`F4` / `Shift+F4` (`0x73`, IDs `46045` / `46047`):** *"Move to the next / previous row of data in the brushing region."* `next_brushed_action` and `prev_brushed_action` lacked `F4` / `Shift+F4` shortcuts.
3. **`Ctrl+L` (`ID 46056`):** *"Edit and submit session commands."* Plus `toggle_command_line()` should focus `command_editor` when shown and return focus to `table` when hidden.
4. **`Ctrl+Insert` / `Shift+Insert` (`0x2d`, IDs `57634` / `57637`):** Standard Windows Copy / Paste in `WorksheetTable`.

## Execution Checklist
- [x] Add `Ctrl+Enter`, `Ctrl+Insert`, `Shift+Insert` to `WorksheetTable.event()` in `statcraft/modern_worksheet.py`.
- [x] Wire `F4` / `Shift+F4` to `next_brushed_action` / `prev_brushed_action` and `Ctrl+L` to `open_command_line()` in `statcraft/modern_app.py`.
- [x] Add `tests/test_rea_ui_parity.py` and verify all tests pass.
