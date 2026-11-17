"""Tests for native MPX structural worksheet operations (rename, add, delete, reorder)."""
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

from test_mpx import documents, fixture, scratch, variable
from statcraft import session, workspace_state as ws
from statcraft.app import Presenter
from statcraft.io import UnsupportedFormatError
from statcraft.model import Column, Worksheet
from statcraft.mpx import load_mpx, save_mpx
from statcraft.mpx_columns import preflight


def _plain_documents():
    meta = {
        "Version": 20200604,
        "Worksheets": {
            "Items": [
                {"Id": "a", "Name": "Sheet A", "Uri": "/sheets/0/sheet"},
                {"Id": "b", "Name": "Sheet B", "Uri": "/sheets/1/sheet"},
            ],
            "ExtraInformation": {
                "current_worksheet": "a",
                "worksheet_ordering": ["b", "a"],
            },
        },
        "NextSheet": 2,
        "History": ["Initial command"],
        "Commands": {"Items": []},
        "Models": {"Items": []},
        "Reports": {"Items": []},
    }
    first = {
        "Version": 20200604,
        "Data": {
            "Name": "Sheet A",
            "PrivateTitle": "Sheet A",
            "Columns": [variable("X", [1.0, 2.0]), variable("Labels", ["u", "v"], "text")],
            "Constants": [],
            "Matrices": [],
            "HasDOE": False,
        },
    }
    second = {
        "Version": 20200604,
        "Data": {
            "Name": "Sheet B",
            "PrivateTitle": "Sheet B",
            "Columns": [variable("Y", [3.0, 4.0])],
            "Constants": [],
            "Matrices": [],
            "HasDOE": False,
        },
    }
    return meta, first, second


def _write_plain_fixture(path, extra=None, meta_mutator=None, first_mutator=None):
    meta, first, second = _plain_documents()
    if meta_mutator:
        meta_mutator(meta)
    if first_mutator:
        first_mutator(first)
    members = [
        ("/", b""),
        ("/project_metadata_20.json", json.dumps(meta).encode("utf8")),
        ("/sheets/0/sheet.json", json.dumps(first).encode("utf8")),
        ("/sheets/1/sheet.json", json.dumps(second).encode("utf8")),
        ("/unknown/blob.bin", b"\x01\x02\x03\x04"),
    ] + (extra or [])
    with ZipFile(path, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)


class MpxWorksheetOpsTests(unittest.TestCase):
    def test_rename_plain_worksheet_updates_metadata_sheet_and_session(self):
        with scratch() as folder:
            source = Path(folder) / "source.mpx"
            target = Path(folder) / "renamed.mpx"
            _write_plain_fixture(source)
            p = load_mpx(source)
            # Active index is 1 ('a', 'Sheet A')
            p.active_worksheet.name = "Renamed A"
            wid = p.worksheet_ids[p.active_index]
            records = [{
                "entry_id": "statcraft:1",
                "origin": "statcraft",
                "title": "Describe X",
                "time": "2026-11-17T00:00:00Z",
                "worksheet_id": wid,
                "worksheet_name": "Sheet A",
                "result": {"mean": 1.5},
            }]
            save_mpx(p, target, session_records=records)

            loaded = load_mpx(target)
            self.assertEqual(loaded.active_worksheet.name, "Renamed A")
            self.assertEqual(loaded.session_records[0]["worksheet_name"], "Renamed A")
            with ZipFile(target) as z:
                self.assertEqual(z.read("/unknown/blob.bin"), b"\x01\x02\x03\x04")
                sheet_doc = json.loads(z.read("/sheets/0/sheet.json"))
                self.assertEqual(sheet_doc["Data"]["Name"], "Renamed A")
                self.assertEqual(sheet_doc["Data"]["PrivateTitle"], "Renamed A")
                meta = json.loads(z.read("/project_metadata_20.json"))
                names = {item["Id"]: item["Name"] for item in meta["Worksheets"]["Items"]}
                self.assertEqual(names[wid], "Renamed A")

    def test_add_plain_worksheet_writes_sheet_json_and_updates_next_sheet(self):
        with scratch() as folder:
            source = Path(folder) / "source.mpx"
            target = Path(folder) / "added.mpx"
            _write_plain_fixture(source)
            p = load_mpx(source)
            new_sheet = Worksheet("Sheet C", [Column("Z", "number", [10.0, 20.0]), Column("Tag", "text", ["p", "q"])])
            p.worksheets.append(new_sheet)
            p.worksheet_ids.append("c")
            p.worksheet_uris.append("/sheets/2/sheet")
            p.active_index = 2
            save_mpx(p, target)

            loaded = load_mpx(target)
            self.assertEqual([s.name for s in loaded.worksheets], ["Sheet B", "Sheet A", "Sheet C"])
            self.assertEqual(loaded.worksheet_ids, ["b", "a", "c"])
            self.assertEqual(loaded.worksheet_uris, ["/sheets/1/sheet", "/sheets/0/sheet", "/sheets/2/sheet"])
            self.assertEqual(loaded.active_index, 2)
            self.assertEqual(loaded.active_worksheet.columns[0].values, [10.0, 20.0])
            self.assertEqual(loaded.active_worksheet.columns[1].values, ["p", "q"])
            with ZipFile(target) as z:
                self.assertIn("/sheets/2/sheet.json", z.namelist())
                meta = json.loads(z.read("/project_metadata_20.json"))
                self.assertEqual(meta["NextSheet"], 3)
                self.assertEqual(meta["Worksheets"]["ExtraInformation"]["worksheet_ordering"], ["b", "a", "c"])

    def test_delete_plain_worksheet_removes_member_and_prunes_session_and_workspace(self):
        with scratch() as folder:
            source = Path(folder) / "source.mpx"
            target = Path(folder) / "deleted.mpx"
            _write_plain_fixture(source)
            p = load_mpx(source)
            # Delete 'b' (index 0, /sheets/1/sheet)
            p.session_records = [
                {
                    "entry_id": "statcraft:b1",
                    "origin": "statcraft",
                    "title": "B Stat",
                    "time": "2026-11-17T00:00:00Z",
                    "worksheet_id": "b",
                    "worksheet_name": "Sheet B",
                    "result": {"mean": 3.5},
                },
                {
                    "entry_id": "statcraft:a1",
                    "origin": "statcraft",
                    "title": "A Stat",
                    "time": "2026-11-17T00:00:00Z",
                    "worksheet_id": "a",
                    "worksheet_name": "Sheet A",
                    "result": {"mean": 1.5},
                },
            ]
            state = ws.empty()
            state.update(
                open_ids=["statcraft:b1", "native:cmd1:grp1", ws.REPORT],
                active="statcraft:b1",
                closed_ids=["statcraft:b1"],
                views={
                    "statcraft:b1": {"view": "Report", "zoom": {}, "scroll": {}, "editor": False},
                    "native:cmd1:grp1": {"view": "Graph", "zoom": {}, "scroll": {}, "editor": False},
                },
                report_pad="Keep me",
            )
            p.workspace = state
            del p.worksheets[0]
            del p.worksheet_ids[0]
            del p.worksheet_uris[0]
            p.active_index = 0
            save_mpx(p, target)

            loaded = load_mpx(target)
            self.assertEqual(loaded.worksheet_ids, ["a"])
            self.assertEqual([s.name for s in loaded.worksheets], ["Sheet A"])
            self.assertEqual([r["entry_id"] for r in loaded.session_records], ["statcraft:a1"])
            self.assertEqual(loaded.workspace["open_ids"], ["native:cmd1:grp1", ws.REPORT])
            self.assertEqual(loaded.workspace["closed_ids"], [])
            self.assertEqual(set(loaded.workspace["views"]), {"native:cmd1:grp1"})
            self.assertEqual(loaded.workspace["active"], ws.REPORT)
            self.assertEqual(loaded.workspace["report_pad"], "Keep me")
            with ZipFile(target) as z:
                self.assertNotIn("/sheets/1/sheet.json", z.namelist())
                self.assertIn("/sheets/0/sheet.json", z.namelist())

    def test_reorder_worksheets_and_preflight_on_reordered_and_added_sheets(self):
        with scratch() as folder:
            source = Path(folder) / "source.mpx"
            target = Path(folder) / "reordered.mpx"
            _write_plain_fixture(source)
            pres = Presenter()
            pres.load(source)
            pres.reorder_worksheets(0, 1)
            self.assertEqual(pres.native_project.worksheet_ids, ["a", "b"])
            self.assertEqual(pres.native_project.worksheet_uris, ["/sheets/0/sheet", "/sheets/1/sheet"])
            # Preflight must match baseline by worksheet ID, not positional index
            preflight(pres.native_project, pres.native_project.worksheets[0])
            preflight(pres.native_project, pres.native_project.worksheets[1])
            pres.save(target)

            loaded = load_mpx(target)
            self.assertEqual(loaded.worksheet_ids, ["a", "b"])
            self.assertEqual([s.name for s in loaded.worksheets], ["Sheet A", "Sheet B"])

    def test_collection_json_manifest_updated_when_present(self):
        with scratch() as folder:
            source = Path(folder) / "source.mpx"
            target = Path(folder) / "collection.mpx"
            collection = {
                "Items": [
                    {"Id": "a", "Name": "Sheet A", "Uri": "/sheets/0/sheet"},
                    {"Id": "b", "Name": "Sheet B", "Uri": "/sheets/1/sheet"},
                ],
                "ExtraInformation": {"worksheet_ordering": ["b", "a"]},
            }
            _write_plain_fixture(
                source,
                extra=[("/sheets/collection.json", json.dumps(collection).encode("utf8"))],
            )
            p = load_mpx(source)
            p.worksheets[1].name = "Alpha"
            p.worksheets.append(Worksheet("Gamma", [Column("G", "number", [5.0])]))
            p.worksheet_ids.append("c")
            p.worksheet_uris.append("/sheets/2/sheet")
            save_mpx(p, target)

            with ZipFile(target) as z:
                updated = json.loads(z.read("/sheets/collection.json"))
                self.assertEqual([item["Id"] for item in updated["Items"]], ["b", "a", "c"])
                self.assertEqual([item["Name"] for item in updated["Items"]], ["Sheet B", "Alpha", "Gamma"])
                self.assertEqual(updated["ExtraInformation"]["worksheet_ordering"], ["b", "a", "c"])

    def test_reject_unsafe_delete_rename_and_uri_mutations(self):
        with scratch() as folder:
            # 1. Deleting a sheet referenced by a native command is rejected
            cmd_src = Path(folder) / "cmd.mpx"
            _write_plain_fixture(
                cmd_src,
                meta_mutator=lambda m: m["Commands"]["Items"].append(
                    {"Id": "cmd1", "InputWorksheet": "b", "OutputWorksheet": "b"}
                ),
            )
            p = load_mpx(cmd_src)
            del p.worksheets[0], p.worksheet_ids[0], p.worksheet_uris[0]
            p.active_index = 0
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(folder) / "bad_cmd.mpx")

            # 2. Deleting a sheet referenced by a native model is rejected
            model_src = Path(folder) / "model.mpx"
            _write_plain_fixture(
                model_src,
                meta_mutator=lambda m: m["Models"]["Items"].append(
                    {"Type": "RegressionModel", "Items": [{"Id": "m1", "worksheet_id": "b"}]}
                ),
            )
            p = load_mpx(model_src)
            del p.worksheets[0], p.worksheet_ids[0], p.worksheet_uris[0]
            p.active_index = 0
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(folder) / "bad_model.mpx")

            # 3. Renaming a sheet with HasDOE=True is rejected
            doe_src = Path(folder) / "doe.mpx"
            _write_plain_fixture(doe_src, first_mutator=lambda f: f["Data"].update(HasDOE=True))
            p = load_mpx(doe_src)
            p.active_worksheet.name = "Changed DOE"
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(folder) / "bad_doe.mpx")

            # 4. Reassigning an existing sheet's URI is rejected
            uri_src = Path(folder) / "uri.mpx"
            _write_plain_fixture(uri_src)
            p = load_mpx(uri_src)
            p.worksheet_uris[0] = "/sheets/99/sheet"
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(folder) / "bad_uri.mpx")

            # 5. Deleting the last worksheet is rejected
            p = load_mpx(uri_src)
            p.worksheets.clear()
            p.worksheet_ids.clear()
            p.worksheet_uris.clear()
            with self.assertRaises((UnsupportedFormatError, ValueError)):
                save_mpx(p, Path(folder) / "empty.mpx")


if __name__ == "__main__":
    unittest.main()
