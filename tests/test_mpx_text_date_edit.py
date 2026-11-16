import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from statcraft import mpx
from statcraft.io import MISSING_SENTINEL, UnsupportedFormatError
from statcraft.mpx import load_mpx, save_mpx
from test_mpx import fixture, variable


def _rewrite_mpx(path, mutator):
    with zipfile.ZipFile(path) as archive:
        members = [(info, archive.read(info)) for info in archive.infolist()]
        comment = archive.comment
    extra = []
    mutator(members, extra)
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = comment
        for info, raw in members:
            archive.writestr(copy.deepcopy(info), raw)
        for name, raw in extra:
            archive.writestr(name, raw, compress_type=zipfile.ZIP_DEFLATED)


def _date_blob_fixture(path, values=(43831.0, 43832.5)):
    fixture(path)
    def mutate(members, extra):
        for idx, (info, raw) in enumerate(members):
            if info.filename == "/sheets/1/sheet.json":
                sheet = json.loads(raw)
                body = sheet["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"]
                body["CellCt"] = len(values)
                body["NumericData"] = f"/blobs/blob2?size={len(values)}"
                members[idx] = (info, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))
        extra.append(("/blobs/blob2", struct.pack(f"<{len(values)}d", *values)))
    _rewrite_mpx(path, mutate)


class MpxTextDateEditTests(unittest.TestCase):
    def test_edit_text_beyond_char_ct_updates_metadata_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.mpx"
            out = Path(tmp) / "edited.mpx"
            fixture(src)

            def add_format_value(members, _extra):
                for idx, (info, raw) in enumerate(members):
                    if info.filename == "/sheets/0/sheet.json":
                        sheet = json.loads(raw)
                        sheet["Data"]["Columns"][1]["WorksheetVarBody"]["Format"]["Value"] = {
                            "ClassId": 18,
                            "CharCt": 4,
                            "DataToStr": [],
                            "StrToStr": [],
                        }
                        members[idx] = (info, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))

            _rewrite_mpx(src, add_format_value)
            proj = load_mpx(src)
            proj.active_worksheet.columns[1].values = ["UpdatedLabel", "Ω"]
            save_mpx(proj, out)

            reopened = load_mpx(out)
            self.assertEqual(reopened.active_worksheet.columns[1].values, ["UpdatedLabel", "Ω"])
            with zipfile.ZipFile(out) as archive:
                sheet = json.loads(archive.read("/sheets/0/sheet.json"))
                wrapper = sheet["Data"]["Columns"][1]["WorksheetVarBody"]
                self.assertEqual(wrapper["VarData"]["VarDataBody"]["CharCt"], len("UpdatedLabel"))
                self.assertEqual(wrapper["Format"]["Value"]["CharCt"], len("UpdatedLabel"))

    def test_resize_text_column_grow_and_shrink_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.mpx"
            grown = Path(tmp) / "grown.mpx"
            shrunk = Path(tmp) / "shrunk.mpx"
            fixture(src)

            proj = load_mpx(src)
            proj.active_worksheet.columns[1].values = ["alpha", "beta", "gamma_long", ""]
            save_mpx(proj, grown)
            reopened = load_mpx(grown)
            self.assertEqual(reopened.active_worksheet.columns[1].values, ["alpha", "beta", "gamma_long", ""])

            reopened.active_worksheet.columns[1].values = ["only_one"]
            save_mpx(reopened, shrunk)
            reopened_shrunk = load_mpx(shrunk)
            self.assertEqual(reopened_shrunk.active_worksheet.columns[1].values, ["only_one"])

    def test_edit_and_resize_inline_date_column_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.mpx"
            out = Path(tmp) / "edited_date.mpx"
            fixture(src)

            proj = load_mpx(src)
            date_col = proj.worksheets[0].columns[1]
            self.assertEqual(date_col.kind, "date")
            date_col.values = [43833.0, 44000.25, 45000.5]
            save_mpx(proj, out)

            reopened = load_mpx(out)
            self.assertEqual(reopened.worksheets[0].columns[1].kind, "date")
            self.assertEqual(reopened.worksheets[0].columns[1].values, [43833.0, 44000.25, 45000.5])

    def test_edit_and_resize_blob_backed_date_column_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "blob_date.mpx"
            out = Path(tmp) / "blob_date_edited.mpx"
            _date_blob_fixture(src, values=(43831.0, 43832.5))

            proj = load_mpx(src)
            proj.worksheets[0].columns[1].values = [44197.0, 44198.5, 44199.75]
            save_mpx(proj, out)

            reopened = load_mpx(out)
            self.assertEqual(reopened.worksheets[0].columns[1].values, [44197.0, 44198.5, 44199.75])
            with zipfile.ZipFile(out) as archive:
                sheet = json.loads(archive.read("/sheets/1/sheet.json"))
                body = sheet["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"]
                self.assertEqual(body["CellCt"], 3)
                self.assertEqual(body["NumericData"], "/blobs/blob2?size=3")

    def test_preserves_safety_guards_for_text_and_date_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.mpx"
            fixture(src)

            # 1. None in native text column
            p = load_mpx(src)
            p.active_worksheet.columns[1].values = ["ok", None]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "text_none.mpx")

            # 2. Non-BMP Unicode in native text column
            p = load_mpx(src)
            p.active_worksheet.columns[1].values = ["🧪", "b"]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "text_nonbmp.mpx")

            # 3. None in native date column
            p = load_mpx(src)
            p.worksheets[0].columns[1].values = [43831.0, None]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "date_none.mpx")

            # 4. MISSING_SENTINEL in native date column
            p = load_mpx(src)
            p.worksheets[0].columns[1].values = [43831.0, MISSING_SENTINEL]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "date_sentinel.mpx")

            # 5. Kind mismatch
            p = load_mpx(src)
            p.active_worksheet.columns[1].kind = "number"
            p.active_worksheet.columns[1].values = [1.0, 2.0]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "kind_mismatch.mpx")

            # 6. Metadata mismatch
            p = load_mpx(src)
            p.active_worksheet.columns[1].metadata["extra"] = 1
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "meta_mismatch.mpx")

            # 7. Shared blob in date column
            shared = Path(tmp) / "shared_date.mpx"
            _date_blob_fixture(shared)
            def share_blob(members, _extra):
                for idx, (info, raw) in enumerate(members):
                    if info.filename == "/sheets/1/sheet.json":
                        sheet = json.loads(raw)
                        sheet["Data"]["Columns"][0]["WorksheetVarBody"]["VarData"]["VarDataBody"]["NumericData"] = "/blobs/blob2?size=2"
                        members[idx] = (info, json.dumps(sheet).encode("utf-8"))
            _rewrite_mpx(shared, share_blob)
            p = load_mpx(shared)
            p.worksheets[0].columns[1].values = [44000.0, 44001.0]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "shared_out.mpx")

            # 8. Absent CharCt metadata when growing text
            no_charct = Path(tmp) / "no_charct.mpx"
            fixture(no_charct)
            def drop_charct(members, _extra):
                for idx, (info, raw) in enumerate(members):
                    if info.filename == "/sheets/0/sheet.json":
                        sheet = json.loads(raw)
                        sheet["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"].pop("CharCt", None)
                        members[idx] = (info, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))
            _rewrite_mpx(no_charct, drop_charct)
            p = load_mpx(no_charct)
            p.active_worksheet.columns[1].values = ["longer_than_before", "b"]
            with self.assertRaises(UnsupportedFormatError):
                save_mpx(p, Path(tmp) / "no_charct_out.mpx")
