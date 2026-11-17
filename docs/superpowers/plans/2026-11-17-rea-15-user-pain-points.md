# 15 Minitab 22 User Pain Points — REA-Grounded Implementation Plan

> **For agentic workers:** Batch A, B, and C implement core logic + unit tests in parallel across disjoint modules; final pass wires all 15 actions into `statcraft/modern_app.py` and runs UI integration tests.

## Identified Pain Points (`MtbResources.dll` `RT_STRING` Grounded)

1. **`#43102` / `#43103` Freeze Panes & Unfreeze Rows/Cols** — Pin top rows / left columns so IDs stay visible while scrolling wide/tall worksheets.
2. **`#27459` Auto-Save & Crash Recovery (`Recover auto-saved file`)** — Periodic autosave snapshot & startup recovery prompt so long sessions aren't lost.
3. **`#42469` / `#42472` Save History As… & Clear History** — Export `MTB >` command history to `.mtb`/`.exec` and clear the History pane.
4. **`#42460` / `#42462` Save Session Window… & Clear Session Window** — Export formatted Session output to `.html`/`.txt` and expose Session clear directly.
5. **`#42473` / `#42474` / `#42475` Navigator Output Ordering** — Sort/group Navigator items `Chronologically`, `By Worksheet`, or `By Title`.
6. **`#46701` / `#46702` Split View / Unsplit View** — Compare two output/graph tabs side-by-side in `OutputWorkspace`.
7. **`#42403` Tile With Worksheet** — One-click balanced side-by-side / split arrangement of active output/graph with worksheet.
8. **`#674` Merge Worksheets…** — UI dialog in `D&ata` calling `data_prep.merge_worksheets` to join two open worksheets by key column.
9. **`#42446` / `#42417` Append Active Output / Graph to ReportPad** — One-click menu/toolbar action sending the active output or graph into ReportPad.
10. **`#46058` Set Cell Comment…** — Menu action + shortcut (`Ctrl+Shift+M`) in `&Edit` / `D&ata` for cell comments.
11. **`#44220` / `#44304` Update Graph Automatically** — Checkable `Graph > Update Graph Automatically` toggle refreshing graphs when worksheet data changes.
12. **`#44346` / `#44347` Add Reference Line… & Add Percentile Line…** — Quick actions to add X/Y reference lines or percentile lines to the active graph.
13. **`#44349` / `#44350` / `#44351` Add Title / Subtitle / Footnote…** — Quick dialog to edit title, subtitle, and footnote on the active graph.
14. **`#44352` Toggle Graph Gridlines** — Quick `Graph > Toggle Gridlines` action on the active graph.
15. **`#44291` / `#44294` Set Brushing Color… & Show/Hide Brushing Palette** — Customize brushing highlight color and toggle the brushing palette/HUD.
