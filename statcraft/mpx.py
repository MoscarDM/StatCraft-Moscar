"""Original bounded reader and conservative save-copy editor for observed MPX.

Version 20200604 ZIP/JSON is supported. No extraction, target code, native model
execution, full-format compatibility or native application reopen is implied.
"""
from dataclasses import dataclass, field
import copy
import io as memory_io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
import struct
from .model import Column, Matrix, Worksheet, finite_number
from . import io


@dataclass
class Project:
    name: str
    worksheets: list = field(default_factory=list)
    active_index: int = 0
    history: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    source_path: str | None = None
    worksheet_ids: list = field(default_factory=list)
    worksheet_uris: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    retained_members: dict = field(default_factory=dict, repr=False)
    retained_zip_infos: list = field(default_factory=list, repr=False)
    archive_comment: bytes = field(default=b"", repr=False)
    workspace: dict | None = None
    _original_workspace: dict | None = field(default=None, repr=False)
    session_records: list = field(default_factory=list)
    _original_session_records: list = field(default_factory=list, repr=False)
    _archive_bytes: bytes = field(default=b"", repr=False)
    _original_members: dict = field(default_factory=dict, repr=False)
    _original_sheets: dict = field(default_factory=dict, repr=False)
    _baseline: list = field(default_factory=list, repr=False)
    _original_metadata: dict = field(default_factory=dict, repr=False)
    _original_ids: list = field(default_factory=list, repr=False)
    _original_uris: list = field(default_factory=list, repr=False)
    _original_history: list = field(default_factory=list, repr=False)
    _original_active: int = field(default=0, repr=False)
    _original_zip_infos: list = field(default_factory=list, repr=False)
    _original_comment: bytes = field(default=b"", repr=False)
    _bound_source_path: str | None = field(default=None, repr=False)
    _appended_ids: dict = field(default_factory=dict, repr=False)

    native_views: dict = field(default_factory=dict)
    _original_native_views: dict = field(default_factory=dict, repr=False)

    @property
    def active_worksheet(self):
        if not self.worksheets:
            raise ValueError("The project has no worksheets.")
        if type(self.active_index) is not int or not 0 <= self.active_index < len(self.worksheets):
            raise ValueError("The active worksheet index is invalid.")
        return self.worksheets[self.active_index]


def _read_archive(path):
    path = Path(path)
    if path.stat().st_size > io.MAX_TOTAL_BYTES:
        raise io.FormatError("Project archive exceeds the size limit.")
    archive_bytes = path.read_bytes()
    try:
        with zipfile.ZipFile(memory_io.BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > io.MAX_MEMBERS:
                raise io.FormatError("Project archive exceeds the member limit.")
            members, total = {}, 0
            for info in infos:
                name = info.filename
                if (name in members or "\\" in name or "\x00" in name or ":" in name or
                        any(part in (".", "..") for part in name.split("/"))):
                    raise io.FormatError("Duplicate or unsafe virtual project member.")
                if info.flag_bits & 1:
                    raise io.UnsupportedFormatError("Encrypted project members are unsupported.")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise io.UnsupportedFormatError("Unsupported project compression.")
                total += info.file_size
                if info.file_size > io.MAX_MEMBER_BYTES or total > io.MAX_TOTAL_BYTES:
                    raise io.FormatError("Decoded project archive exceeds the size limit.")
                members[name] = archive.read(info)  # CRC checked, no filesystem extraction.
            return archive_bytes, members, copy.deepcopy(infos), archive.comment
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as exc:
        raise io.FormatError("Cannot read project archive: " + str(exc)) from exc


def _worksheet(document, item, members=None):
    try:
        if not isinstance(document, dict) or document.get("Version") != 20200604:
            raise io.UnsupportedFormatError("Unverified project worksheet version.")
        data = document["Data"]
        if not isinstance(data, dict):
            raise io.FormatError("Worksheet Data must be an object.")
        parsed = {}
        total = 0
        for key, class_id, var_type, prefix in (("Columns", 434, 3, "C"), ("Constants", 435, 2, "K"), ("Matrices", 436, 4, "M")):
            entries = data.get(key, [])
            if not isinstance(entries, list):
                raise io.FormatError(key + " must be an array.")
            parsed[key] = []
            for index, entry in enumerate(entries):
                wrapper = entry.get("WorksheetVarBody", {}) if isinstance(entry, dict) else {}
                var = wrapper.get("VarData", {})
                body = var.get("VarDataBody", {})
                untyped_empty = (key == "Columns" and entry.get("ClassId") == 434 and
                    wrapper.get("ClassId") == 437 and var.get("ClassId") == 439 and
                    var.get("VariableType") == 3 and var.get("Data") == 0 and
                    wrapper.get("Format", {}).get("Key") == 0 and body.get("ClassId") == 447 and
                    body.get("CellCt") == 0 and body.get("ColCt") == 0 and
                    body.get("HasNumericData") is False and body.get("HasTextData") is False and
                    not body.get("NumericData") and not body.get("TextData") and
                    not entry.get("Compressed") and entry.get("WorksheetVar") is None)
                if untyped_empty:
                    column = Column(wrapper.get("Name", ""), "number", [],
                                    {"imported_variable_metadata": copy.deepcopy(entry),
                                     "unsupported_native_storage": "untyped-empty-v0"})
                    width = 1  # Display-only column convention; retained native ColCt remains zero.
                else:
                    column, width = io._mwx_variable(entry, class_id, var_type, members)
                column.name = column.name or prefix + str(index + 1)
                total += len(column.values)
                if total > io.MAX_CELLS:
                    raise io.FormatError("Worksheet exceeds the cell limit.")
                if key == "Matrices":
                    if column.kind != "number" or len(column.values) % width:
                        raise io.UnsupportedFormatError("Only regular numeric column-major matrices are supported.")
                    parsed[key].append(Matrix(column.name, len(column.values) // width, width, column.values, column.metadata))
                else:
                    if width != 1 or (key == "Constants" and len(column.values) != 1):
                        raise io.UnsupportedFormatError("Unsupported variable dimensions.")
                    parsed[key].append(column)
        return Worksheet(item.get("Name", "Worksheet"), parsed["Columns"], parsed["Constants"], parsed["Matrices"],
                         {"import": {"format": "MPX", "version": 20200604,
                          "native_worksheet_item": copy.deepcopy(item),
                          "warnings": ["Observed MPX schema only; native application reopen is unverified.",
                                       "Imported formulas, models and results are retained but remain inactive."]}})
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, io.FormatError): raise
        raise io.FormatError("Malformed project worksheet: " + str(exc)) from exc


def load_mpx(path):
    """Loads all referenced sheets in native UI ordering; retains all member bytes."""
    archive_bytes, members, infos, comment = _read_archive(path)
    if "/project_metadata_20.json" not in members:
        raise io.UnsupportedFormatError("The observed native project metadata member is absent.")
    metadata = io._json(members["/project_metadata_20.json"])
    try:
        if not isinstance(metadata, dict) or metadata.get("Version") != 20200604:
            raise io.UnsupportedFormatError("Unverified native project version.")
        collection = metadata["Worksheets"]
        items = collection["Items"]
        if not isinstance(items, list) or not items:
            raise io.UnsupportedFormatError("A native project must contain referenced worksheets.")
        by_id, original_documents, models = {}, {}, {}
        uris = set()
        total_cells = 0
        for item in items:
            if not isinstance(item, dict): raise io.FormatError("Invalid worksheet item.")
            identifier, uri = item.get("Id"), item.get("Uri")
            if not isinstance(identifier, str) or not identifier or identifier in by_id:
                raise io.FormatError("Worksheet IDs must be nonempty and unique.")
            if not isinstance(uri, str) or not re.fullmatch(r"/sheets/\d+/sheet", uri) or uri in uris:
                raise io.UnsupportedFormatError("Unsupported or duplicate worksheet URI.")
            uris.add(uri)
            member = uri + ".json"
            if member not in members:
                raise io.FormatError("A referenced worksheet member is absent.")
            document = io._json(members[member])
            sheet = _worksheet(document, item, members)
            total_cells += sum(len(c.values) for c in sheet.columns + sheet.constants) + sum(len(m.values) for m in sheet.matrices)
            if total_cells > io.MAX_CELLS:
                raise io.FormatError("Project exceeds the aggregate cell limit.")
            by_id[identifier] = item; models[identifier] = sheet
            original_documents[member] = document
        extra = collection.get("ExtraInformation", {})
        if not isinstance(extra, dict): raise io.FormatError("Invalid worksheet navigation metadata.")
        ordering = extra.get("worksheet_ordering", list(by_id))
        if not isinstance(ordering, list) or not all(isinstance(i, str) for i in ordering):
            raise io.FormatError("Worksheet ordering must contain IDs.")
        if len(set(ordering)) != len(ordering) or any(i not in by_id for i in ordering):
            raise io.UnsupportedFormatError("Unknown or duplicate worksheet ordering ID.")
        ordered_ids = ordering + [i for i in by_id if i not in ordering]
        current = extra.get("current_worksheet", ordered_ids[0])
        if current not in by_id:
            raise io.UnsupportedFormatError("Unknown current worksheet ID.")
        history = metadata.get("History", [])
        if not isinstance(history, list): raise io.FormatError("Project history must be an array.")
        warnings = ["All original package members are retained; only the observed 20200604 project schema is parsed.",
                    "Native models, formulas and stored results are retained but are not executed or recalculated.",
                    "Native project saving is save-copy only; original files cannot be overwritten.",
                    "Edited native project reopen in the reference application has not been verified."]
        if any(c.metadata.get("unsupported_native_storage") for sheet in models.values() for c in sheet.columns):
            warnings.append("Untyped empty native columns are displayed as numeric placeholders; native edits to those columns are unsupported.")
        project = Project(Path(path).stem, [models[i] for i in ordered_ids], ordered_ids.index(current),
                          copy.deepcopy(history), copy.deepcopy(metadata), str(Path(path).resolve()), ordered_ids,
                          [by_id[i]["Uri"] for i in ordered_ids], warnings, members, infos, comment)
        project._archive_bytes = archive_bytes
        project._original_members = copy.deepcopy(members)
        project._original_sheets = original_documents
        project._baseline = copy.deepcopy(project.worksheets)
        project._original_metadata = copy.deepcopy(metadata)
        project._original_ids = list(project.worksheet_ids)
        project._original_uris = list(project.worksheet_uris)
        project._original_history = copy.deepcopy(history)
        project._original_active = project.active_index
        project._original_zip_infos = copy.deepcopy(infos)
        project._original_comment = comment
        project._bound_source_path = project.source_path
        from . import session
        if session.MEMBER in members:
            project.session_records = session.decode(members[session.MEMBER], ordered_ids)
        project._original_session_records = copy.deepcopy(project.session_records)
        from . import workspace_state
        if workspace_state.MEMBER in members:project.workspace=workspace_state.decode(members[workspace_state.MEMBER])
        project._original_workspace=copy.deepcopy(project.workspace)
        from . import native_output_state
        if native_output_state.MEMBER in members:project.native_views=native_output_state.decode(members[native_output_state.MEMBER])
        project._original_native_views=copy.deepcopy(project.native_views)
        if '/statcraft/workbook.json' in members:
            from .mpx_create import restore_owned
            if restore_owned(project):
                project._baseline=copy.deepcopy(project.worksheets)
        return project
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, io.FormatError): raise
        raise io.FormatError("Malformed native project metadata: " + str(exc)) from exc


def _atomic_bytes(path, payload):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".statcraft-mpx-", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)


def _allocate_numeric_blob_member(original_members, changed_members):
    """Allocate a fresh unique /blobs/blobM member name not in original or changed members."""
    used = set(original_members) | set(changed_members)
    max_index = 0
    for name in used:
        match = re.fullmatch(r'/blobs/blob([1-9][0-9]*)', name)
        if match is not None:
            max_index = max(max_index, int(match.group(1)))
    candidate = max_index + 1
    while f'/blobs/blob{candidate}' in used:
        candidate += 1
    return f'/blobs/blob{candidate}'


def _validate_worksheet_structure(project):
    if not project.worksheets:
        raise io.UnsupportedFormatError("A native project must contain at least one worksheet.")
    project.active_worksheet  # Validate the selected index.
    if len(project.worksheet_ids) != len(project.worksheets) or len(project.worksheet_uris) != len(project.worksheets):
        raise io.FormatError("Worksheet identity counts do not match.")
    if any(not isinstance(wid, str) or not wid for wid in project.worksheet_ids) or len(set(project.worksheet_ids)) != len(project.worksheet_ids):
        raise io.FormatError("Worksheet IDs must be nonempty and unique.")
    if any(not isinstance(uri, str) or not re.fullmatch(r"/sheets/\d+/sheet", uri) for uri in project.worksheet_uris) or len(set(project.worksheet_uris)) != len(project.worksheet_uris):
        raise io.UnsupportedFormatError("Unsupported or duplicate worksheet URI.")
    orig_by_id = {wid: (idx, sheet, uri) for idx, (wid, sheet, uri) in enumerate(zip(project._original_ids, project._baseline, project._original_uris))}
    orig_uris = set(project._original_uris)
    for wid, uri in zip(project.worksheet_ids, project.worksheet_uris):
        if wid in orig_by_id:
            if uri != orig_by_id[wid][2]:
                raise io.UnsupportedFormatError("Reassigning native worksheet URIs is unsupported.")
        elif uri in orig_uris or (uri + ".json") in project._original_members:
            raise io.UnsupportedFormatError("New worksheet URI collides with existing package member.")
    return orig_by_id


def _check_deleted_worksheet_safety(project, deleted_ids, orig_by_id):
    if not deleted_ids:
        return
    from .mpx_append import validate_plain
    deleted_set = set(deleted_ids)
    for wid in deleted_ids:
        validate_plain(project._original_sheets[orig_by_id[wid][2] + ".json"])
    meta = project._original_metadata
    commands = meta.get("Commands", {}).get("Items", []) if isinstance(meta.get("Commands"), dict) else []
    for cmd in commands:
        if isinstance(cmd, dict) and (cmd.get("InputWorksheet") in deleted_set or cmd.get("OutputWorksheet") in deleted_set):
            raise io.UnsupportedFormatError("Cannot delete a native worksheet referenced by native commands or outputs.")
    models = meta.get("Models", {}).get("Items", []) if isinstance(meta.get("Models"), dict) else []
    for family in models:
        items = family.get("Items", []) if isinstance(family, dict) and isinstance(family.get("Items"), list) else []
        for item in items:
            if isinstance(item, dict) and any(item.get(k) in deleted_set for k in ("worksheet_id", "WorksheetId", "InputWorksheet", "OutputWorksheet")):
                raise io.UnsupportedFormatError("Cannot delete a native worksheet referenced by native models.")
    reports = meta.get("Reports", {}).get("Items", []) if isinstance(meta.get("Reports"), dict) else []
    for rep in reports:
        if isinstance(rep, dict) and any(rep.get(k) in deleted_set for k in ("worksheet_id", "WorksheetId", "InputWorksheet", "OutputWorksheet")):
            raise io.UnsupportedFormatError("Cannot delete a native worksheet referenced by native reports.")


def _validate_new_native_sheet(sheet):
    if sheet.constants or sheet.matrices:
        raise io.UnsupportedFormatError("New native worksheets with constants or matrices are unsupported.")
    for column in sheet.columns:
        if column.kind not in ("number", "date", "text"):
            raise io.UnsupportedFormatError("Unsupported native column type.")
        if column.kind == "date" and any(v is None for v in column.values):
            raise io.UnsupportedFormatError("Missing-date sentinel semantics have not been verified.")
        if column.kind == "text":
            if any(v is None for v in column.values):
                raise io.UnsupportedFormatError("Native text missing-value encoding is unverified; literal empty strings are supported.")
            if any(any(ord(c) > 0xffff or 0xd800 <= ord(c) <= 0xdfff for c in v) for v in column.values):
                raise io.UnsupportedFormatError("Native text editing beyond verified BMP Unicode is unsupported.")
        elif column.kind == "number" and any(v is not None and finite_number(v) == io.MISSING_SENTINEL for v in column.values):
            raise io.UnsupportedFormatError("This numeric value is reserved for native missing cells.")


def _update_collection_manifest(raw, project, orig_item_by_id):
    doc = io._json(raw)
    new_items = []
    for sheet, wid, uri in zip(project.worksheets, project.worksheet_ids, project.worksheet_uris):
        if wid in orig_item_by_id:
            item = copy.deepcopy(orig_item_by_id[wid])
            item["Name"] = sheet.name
        else:
            item = {"Id": wid, "Name": sheet.name, "Uri": uri}
        new_items.append(item)
    if isinstance(doc, dict) and isinstance(doc.get("Items"), list):
        doc["Items"] = new_items
        if isinstance(doc.get("ExtraInformation"), dict) and "worksheet_ordering" in doc["ExtraInformation"]:
            doc["ExtraInformation"]["worksheet_ordering"] = list(project.worksheet_ids)
        return json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if isinstance(doc, list):
        return json.dumps(new_items, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    raise io.UnsupportedFormatError("Unsupported /sheets/collection.json structure for worksheet edits.")


def save_mpx(project, path, session_records=None):
    """Save-copy: same-size edits, typed numeric resizing, numeric append, and plain worksheet ops.

    No new native project, type conversion, date/text resizing,
    constant, matrix or history edits are written. Unknown member bytes remain
    exact, but cached models/results may be stale after supported data edits.
    Optional StatCraft result snapshots use a separate original session member;
    they are not encoded as native Commands or Reports.
    Returns explicit verification/retained-output notices.
    """
    if isinstance(project,Project) and getattr(project,'statcraft_owned',False):
        from .mpx_create import save_owned
        return save_owned(project,path,session_records)
    path = Path(path)
    if not isinstance(project, Project) or not project._archive_bytes or not project._baseline:
        raise io.UnsupportedFormatError("New native project creation is unverified. Open an existing MPX project or save a StatCraft project.")
    if path.suffix.lower() != ".mpx":
        raise io.FormatError("Native project copies require the .mpx extension.")
    if project._bound_source_path and path.resolve() == Path(project._bound_source_path).resolve():
        raise io.UnsupportedFormatError("Original native projects cannot be overwritten until reopen compatibility is verified. Choose a separate .mpx copy.")
    if project._bound_source_path and path.exists() and Path(project._bound_source_path).exists():
        if os.path.samefile(path, project._bound_source_path):
            raise io.UnsupportedFormatError("Destination aliases the original native project. Choose a separate .mpx copy.")
    if project.metadata != project._original_metadata or project.history != project._original_history:
        raise io.UnsupportedFormatError("Native project metadata/history edits are unsupported; export new analysis output separately.")
    if project.retained_members != project._original_members:
        raise io.UnsupportedFormatError("Direct native package payload edits are unsupported.")
    if project.archive_comment != project._original_comment:
        raise io.UnsupportedFormatError("Native archive comment edits are unsupported.")
    if ([info.filename for info in project.retained_zip_infos] !=
            [info.filename for info in project._original_zip_infos]):
        raise io.UnsupportedFormatError("Native ZIP member ordering or structure was modified.")
    orig_by_id = _validate_worksheet_structure(project)
    deleted_ids = [wid for wid in project._original_ids if wid not in set(project.worksheet_ids)]
    _check_deleted_worksheet_safety(project, deleted_ids, orig_by_id)
    deleted_members = set()
    for wid in deleted_ids:
        orig_uri = orig_by_id[wid][2]
        deleted_members.add(orig_uri + ".json")
        dir_member = orig_uri.rsplit("/", 1)[0] + "/"
        if dir_member in project._original_members:
            deleted_members.add(dir_member)
    changed_members = {}
    appended_ids=copy.deepcopy(project._appended_ids)
    from . import session
    records = copy.deepcopy(project.session_records if session_records is None else session_records)
    removed_entry_ids = set()
    if deleted_ids:
        deleted_set = set(deleted_ids)
        keep_ids = set(project.worksheet_ids) | ({r.get('worksheet_id') for r in records if isinstance(r, dict)} - deleted_set)
        records, removed_entry_ids = session.prune(records, keep_ids)
    renamed_names = {
        wid: sheet.name
        for wid, sheet in zip(project.worksheet_ids, project.worksheets)
        if wid in orig_by_id and sheet.name != orig_by_id[wid][1].name
    }
    if renamed_names:
        session.sync_worksheet_names(records, renamed_names)
    session_payload = session.validate(records, project.worksheet_ids)
    if records != project._original_session_records:
        changed_members[session.MEMBER] = session_payload
    from . import workspace_state
    ws_state = workspace_state.prune_ids(project.workspace, removed_entry_ids) if (project.workspace is not None and removed_entry_ids) else project.workspace
    if ws_state != project._original_workspace:
        if ws_state is None:raise io.FormatError("Workspace removal must use an empty workspace record.")
        changed_members[workspace_state.MEMBER]=workspace_state.encode(ws_state)
    from . import native_output_state
    if project.native_views != project._original_native_views:
        changed_members[native_output_state.MEMBER]=native_output_state.encode(project.native_views)
    for index, (sheet, wid, uri) in enumerate(zip(project.worksheets, project.worksheet_ids, project.worksheet_uris)):
        sheet.validate()
        if wid not in orig_by_id:
            _validate_new_native_sheet(sheet)
            from .mpx_create import _sheet
            document = _sheet(sheet, wid, uri, appended_ids)
            dir_member = uri.rsplit("/", 1)[0] + "/"
            if "/sheets/" in project._original_members and dir_member not in project._original_members:
                changed_members[dir_member] = b""
            changed_members[uri + ".json"] = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            continue
        _, original, _ = orig_by_id[wid]
        if (sheet.constants != original.constants or sheet.matrices != original.matrices or
                sheet.metadata != original.metadata):
            raise io.UnsupportedFormatError("Native worksheet metadata, constants, matrices or column structure cannot be changed safely.")
        document = copy.deepcopy(project._original_sheets[uri + ".json"])
        renamed = sheet.name != original.name
        if renamed:
            from .mpx_append import validate_plain
            validate_plain(document)
            document["Data"]["Name"] = sheet.name
            if "PrivateTitle" in document["Data"]:
                document["Data"]["PrivateTitle"] = sheet.name
        from .mpx_columns import prepare_columns
        extent=max(original.row_count,max((len(column.values) for column in sheet.columns if any(column.metadata==base.metadata for base in original.columns)),default=0))
        matches, changed = prepare_columns(document,sheet.columns,original.columns,extent,appended_ids,uri)
        resized_sheet=False
        for position, (column, original_position) in enumerate(zip(sheet.columns, matches)):
            if original_position is None:
                continue
            baseline=original.columns[original_position]
            resized=len(column.values)!=len(baseline.values)
            if column.kind != baseline.kind or column.metadata != baseline.metadata:
                raise io.UnsupportedFormatError("Native column type and metadata changes are unverified.")
            if column.name == baseline.name and column.values == baseline.values:
                continue
            if baseline.metadata.get("unsupported_native_storage"):
                raise io.UnsupportedFormatError("Native edits to an untyped empty placeholder column require unverified storage initialization.")
            if column.kind not in ("number", "date", "text"):
                raise io.UnsupportedFormatError("Unsupported native column type.")
            wrapper = document["Data"]["Columns"][position]["WorksheetVarBody"]
            if column.name != baseline.name:
                wrapper["Name"] = column.name
            body = wrapper["VarData"]["VarDataBody"]
            if resized:
                from .mpx_rows import prepare_column_resize
                prepare_column_resize(document,wrapper,column.kind,len(column.values))
                resized_sheet=True
            if column.kind in ("number", "date"):
                if column.values != baseline.values:
                    if column.kind == "date" and any(value is None for value in column.values):
                        raise io.UnsupportedFormatError("Missing-date sentinel semantics have not been verified.")
                    if any(value is not None and finite_number(value)==io.MISSING_SENTINEL for value in column.values):
                        raise io.UnsupportedFormatError('This numeric value is reserved for native missing cells.')
                    values=[io.MISSING_SENTINEL if value is None else finite_number(value) for value in column.values]
                    if isinstance(body.get('NumericData'),str):
                        reference=body['NumericData']; member=io._numeric_blob_reference(reference,len(baseline.values))
                        from .mpx_rows import numeric_blob_uses
                        uses=numeric_blob_uses(project._original_members,member)
                        if uses!=1:
                            target_member=_allocate_numeric_blob_member(project._original_members,changed_members)
                        else:
                            target_member=member
                        changed_members[target_member]=struct.pack('<'+str(len(values))+'d',*values)
                        new_ref=target_member+'?size='+str(len(values))
                        body['NumericData']=new_ref
                        if isinstance(body.get('DateTimeData'),str):
                            body['DateTimeData']=new_ref
                    else: body["NumericData"]=values
                    if resized:
                        from .mpx_rows import update_numeric_bounds
                        update_numeric_bounds(wrapper,values)
            else:
                if any(value is None for value in column.values):
                    raise io.UnsupportedFormatError("Native text missing-value encoding is unverified; literal empty strings are supported.")
                capacity = body.get("CharCt")
                if any(any(ord(char) > 0xffff or 0xd800 <= ord(char) <= 0xdfff for char in value) for value in column.values):
                    raise io.UnsupportedFormatError("Native text editing beyond verified BMP Unicode is unsupported.")
                required = max(map(len, column.values), default=0)
                if capacity is None:
                    if required > max(map(len, baseline.values), default=0):
                        raise io.UnsupportedFormatError("Native text width metadata is absent; growing text is unverified.")
                else:
                    new_capacity = max(io._count(capacity, "CharCt"), required)
                    body["CharCt"] = new_capacity
                    fmt_value = wrapper.get("Format", {}).get("Value")
                    if isinstance(fmt_value, dict) and "CharCt" in fmt_value:
                        fmt_value["CharCt"] = max(io._count(fmt_value["CharCt"], "CharCt"), new_capacity)
                body["TextData"] = list(column.values)
            changed = True
        if changed or renamed:
            if resized_sheet and 'MaxRows_DEP' in document:
                document['MaxRows_DEP']=max(io._count(document['MaxRows_DEP'],'MaxRows_DEP'),sheet.row_count)
            changed_members[uri + ".json"] = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    structural_sheets = (project.worksheet_ids != project._original_ids or project.worksheet_uris != project._original_uris or bool(renamed_names))
    if structural_sheets or project.active_index != project._original_active:
        metadata = copy.deepcopy(project._original_metadata)
        orig_item_by_id = {item["Id"]: item for item in metadata["Worksheets"]["Items"] if isinstance(item, dict) and "Id" in item}
        if structural_sheets:
            new_items = []
            for sheet, wid, uri in zip(project.worksheets, project.worksheet_ids, project.worksheet_uris):
                if wid in orig_item_by_id:
                    item = copy.deepcopy(orig_item_by_id[wid])
                    item["Name"] = sheet.name
                else:
                    item = {"Id": wid, "Name": sheet.name, "Uri": uri, "Comments": "",
                            "Creator": "StatCraft", "Date": "",
                            "ExtraInformation": {"column_widths": {"default": 8}, "hidden_columns": []}}
                new_items.append(item)
            metadata["Worksheets"]["Items"] = new_items
            metadata["Worksheets"].setdefault("ExtraInformation", {})["worksheet_ordering"] = list(project.worksheet_ids)
            if "NextSheet" in metadata:
                metadata["NextSheet"] = max([io._count(metadata["NextSheet"], "NextSheet")] + [int(u.split("/")[2]) + 1 for u in project.worksheet_uris])
            if "/sheets/collection.json" in project._original_members:
                changed_members["/sheets/collection.json"] = _update_collection_manifest(
                    project._original_members["/sheets/collection.json"], project, orig_item_by_id)
        metadata["Worksheets"].setdefault("ExtraInformation", {})["current_worksheet"] = project.worksheet_ids[project.active_index]
        changed_members["/project_metadata_20.json"] = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    notices = ["Native application reopen of edited MPX copies remains unverified."]
    if not changed_members and not deleted_members:
        _atomic_bytes(path, project._archive_bytes)
        return notices + ["Untouched project copied byte-for-byte, including original ZIP layout."]
    notices.append("Stored formulas, models and analysis results are retained without recalculation and may be stale after data edits.")
    total = sum(len(changed_members.get(name, data)) for name, data in project._original_members.items() if name not in deleted_members)
    if sum(len(column.values) for sheet in project.worksheets for column in sheet.columns+sheet.constants)+sum(len(matrix.values) for sheet in project.worksheets for matrix in sheet.matrices)>io.MAX_CELLS:
        raise io.FormatError('Edited project exceeds the cell limit.')
    total += sum(len(data) for name, data in changed_members.items() if name not in project._original_members)
    member_count = len(project._original_members) - len(deleted_members) + sum(name not in project._original_members for name in changed_members)
    if member_count > io.MAX_MEMBERS:
        raise io.FormatError("Edited project exceeds the member count limit.")
    if total > io.MAX_TOTAL_BYTES or any(len(data) > io.MAX_MEMBER_BYTES for data in changed_members.values()):
        raise io.FormatError("Edited project exceeds package limits.")
    output = memory_io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = project.archive_comment
        for info in project._original_zip_infos:
            if info.filename not in project._original_members:
                raise io.UnsupportedFormatError("Native ZIP entry structure was modified.")
            if info.filename in deleted_members:
                continue
            archive.writestr(copy.deepcopy(info), changed_members.get(info.filename, project._original_members[info.filename]))
        for name, payload in changed_members.items():
            if name not in project._original_members:
                archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
    # Re-parse before publication; this validates our supported schema, not native reopening.
    if len(output.getvalue()) > io.MAX_TOTAL_BYTES:
        raise io.FormatError("Edited project archive exceeds the size limit.")
    with zipfile.ZipFile(memory_io.BytesIO(output.getvalue())) as check:
        present = set(check.namelist())
        for name, original in project._original_members.items():
            if name in deleted_members:
                if name in present:
                    raise io.FormatError("Deleted worksheet member was not removed; no copy was published.")
            elif check.read(name) != changed_members.get(name, original):
                raise io.FormatError("Package verification failed; no copy was published.")
        for name, payload in changed_members.items():
            if check.read(name) != payload:
                raise io.FormatError("New session verification failed; no copy was published.")
        members = {**{k: v for k, v in project._original_members.items() if k not in deleted_members}, **changed_members}
        for index, sheet in enumerate(project.worksheets):
            name = project.worksheet_uris[index] + '.json'
            if name in changed_members:
                decoded = _worksheet(io._json(check.read(name)), {'Name': sheet.name}, members)
                expected = [(c.name, c.kind, c.values) for c in sheet.columns]
                if [(c.name, c.kind, c.values) for c in decoded.columns] != expected:
                    raise io.FormatError('Edited worksheet round-trip verification failed; no copy was published.')
    _atomic_bytes(path, output.getvalue())
    project._appended_ids = appended_ids
    return notices
