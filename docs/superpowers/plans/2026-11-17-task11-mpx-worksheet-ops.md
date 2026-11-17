# Task 11: Native MPX Structural Worksheet Edits (Add / Rename / Delete / Reorder Sheets)

## Goal
Support **renaming**, **adding**, **deleting**, and **reordering** plain worksheets in imported native `.mpx` save-copy operations (`save_mpx`), updating `worksheet_ids`, `worksheet_uris`, `/project_metadata_20.json`, `/sheets/<idx>/sheet.json` (and `/sheets/collection.json` if present), `session.py`, and `workspace_state.py`, while preserving `UnsupportedFormatError` guards for unsafe native package mutations and retained native output/model links.

## Target Files & Interfaces
1. **`statcraft/mpx.py`** (`save_mpx`, `_validate_worksheet_structure`, `_update_collection_manifest`):
   - Replace the blanket `len(project.worksheets) != len(project._baseline) or project.worksheet_ids != project._original_ids or project.worksheet_uris != project._original_uris` rejection with bounded structural validation:
     - Require non-empty `project.worksheets`, matching lengths for `worksheet_ids` and `worksheet_uris`, unique non-empty string IDs, and unique `/sheets/<idx>/sheet` URIs.
     - Preserve ID-to-URI binding for retained baseline worksheets (`UnsupportedFormatError` if reassigned).
     - Reject new worksheet URIs that collide with existing `_original_uris` or `_original_members`.
   - **Delete guards:** For each deleted baseline `wid`, verify `validate_plain(original_doc)` passes and `wid` is not referenced by `Commands.Items` (`InputWorksheet`/`OutputWorksheet`), `Models.Items` (`worksheet_id`/`WorksheetId`/`command_id`), or `Reports.Items` in `_original_metadata`; otherwise raise `UnsupportedFormatError`.
   - **Rename:** Allow `sheet.name != original.name` on plain worksheets (`validate_plain(original_doc)`), updating `document["Data"]["Name"]` (and `PrivateTitle` if present) and `Worksheets.Items[k]["Name"]`. Keep `constants`, `matrices`, and `sheet.metadata` immutable (`UnsupportedFormatError`).
   - **Add:** Validate new `Worksheet` (`number`/`date`/`text` columns without `None` in `date`/`text` or `MISSING_SENTINEL` in `number`, no `constants`/`matrices`), build `/sheets/<idx>/sheet.json` via `mpx_create._sheet`, add `/sheets/<idx>/` directory entry if `/sheets/` exists, and add `Worksheets.Items` entry.
   - **Reorder:** Match retained sheets by `wid` (instead of positional index against `_baseline`), and update `Worksheets.ExtraInformation["worksheet_ordering"]` and `Worksheets.Items` order.
   - **Metadata & Manifest:** Update `/project_metadata_20.json` (`Worksheets.Items`, `ExtraInformation.worksheet_ordering`, `ExtraInformation.current_worksheet`, `NextSheet` if present) and `/sheets/collection.json` if present in `_original_members`.
   - **ZIP Packaging & Verification:** Exclude deleted sheet members (`/sheets/<idx>/sheet.json` and `/sheets/<idx>/`) from the written archive and verify their absence plus exact integrity of all other retained/changed/added members and round-trip worksheet decoding.
2. **`statcraft/session.py`**:
   - Add `prune(records, worksheet_ids)` (and `sync_worksheet_names(records, name_by_id)`) so `save_mpx` cleanly prunes StatCraft session records belonging to deleted worksheets and updates `worksheet_name` for renamed worksheets, while still raising `io.FormatError` on invalid/unknown `worksheet_id`s.
3. **`statcraft/workspace_state.py`**:
   - Add `prune_ids(state, removed_ids)` to remove `entry_id`s of pruned session records from `open_ids`, `closed_ids`, `views`, and update `active`, without disturbing `REPORT` or retained native output tabs.
4. **`statcraft/mpx_columns.py`**:
   - Update `preflight(project, sheet)` to look up baseline sheet/document by `wid = project.worksheet_ids[index]` (and return early for newly added worksheets) so column preflight works after sheet reorder/add/delete.
5. **`statcraft/app.py`**:
   - Update `Presenter.reorder_worksheets` to reorder `worksheet_ids` and `worksheet_uris` alongside `worksheets`.

## Safety Invariants
- Original `.mpx` file cannot be overwritten (`_bound_source_path` / `samefile`).
- Direct edits to `project.metadata`, `project.history`, `project.retained_members`, `project.archive_comment`, or `project.retained_zip_infos` still raise `UnsupportedFormatError`.
- Deleting a sheet with non-plain native state (`HasDOE`, `FormulaManager`, `RegressionModel`, etc.) or referenced by native `Commands`/`Models`/`Reports` raises `UnsupportedFormatError`.
- Renaming/modifying a sheet with non-plain native state or changing `constants`/`matrices`/`metadata` raises `UnsupportedFormatError`.
- All untouched retained members (blobs, unknown JSON, native outputs) remain byte-identical.

## TDD Test Cases (`tests/test_mpx_worksheet_ops.py`)
1. Rename plain native worksheet: updates `sheet.json`, `project_metadata_20.json`, and `session.json` `worksheet_name`; preserves unknown members.
2. Add plain native worksheet: allocates fresh `/sheets/<idx>/sheet.json`, updates `Worksheets.Items`, `worksheet_ordering`, `NextSheet`, and round-trips via `load_mpx`.
3. Delete plain native worksheet: removes `/sheets/<idx>/sheet.json` from archive, prunes its StatCraft session records and workspace tabs while keeping `REPORT` and other sheets' records/native outputs intact.
4. Reorder native worksheets (both via `Project` and `Presenter.reorder_worksheets`): updates `worksheet_ordering`, preserves column/blob identities, and `mpx_columns.preflight` works on reordered/added sheets.
5. Update `/sheets/collection.json` when present on add/rename/delete/reorder.
6. Safety guards (`UnsupportedFormatError`):
   - Deleting a sheet referenced by native `Commands` / `Models` / `Reports` or having `HasDOE`/`FormulaManager`/`RegressionModel`.
   - Renaming a sheet with non-plain native state (`HasDOE` / `RegressionModel`).
   - Reassigning an existing sheet's `worksheet_uris` or colliding new URI with existing member.
   - Deleting the last remaining worksheet.
