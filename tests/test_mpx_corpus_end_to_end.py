import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("STATCRAFT_TESTING", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from statcraft.app import Presenter
from statcraft.mpx import load_mpx

FIXTURES_DIR = ROOT / "tests" / "fixtures"
CORPUS_DIR = ROOT.parent / "mpx-research"


class MPXCorpusEndToEndTests(unittest.TestCase):
    def test_01_fixture_profiles_load_edit_and_roundtrip(self):
        fixtures = sorted(FIXTURES_DIR.glob("statcraft-profile-v*.mpx"))
        self.assertGreaterEqual(len(fixtures), 3)
        for path in fixtures:
            with self.subTest(fixture=path.name):
                p = Presenter()
                p.load(str(path))
                self.assertGreaterEqual(len(p.worksheets), 1)
                if p.worksheet.columns and p.worksheet.columns[0].kind == "number":
                    p.set_cell(0, 0, "123.45")
                    p.set_cell_comment(0, 0, f"Verified in {path.name}")
                    p.set_column_description(0, f"Fixture desc {path.name}")
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / f"copy_{path.name}"
                    p.save(str(out))
                    self.assertTrue(out.is_file() and out.stat().st_size > 0)
                    p2 = Presenter()
                    p2.load(str(out))
                    self.assertEqual(len(p2.worksheets), len(p.worksheets))

    def test_02_owned_multiworksheet_project_add_edit_save_reload(self):
        p = Presenter()
        p.set_cell(0, 0, "10")
        p.set_cell(1, 0, "20")
        p.set_cell_comment(0, 0, "Baseline sample")
        p.set_column_description(0, "Measurement X")
        p.add_worksheet("Run2")
        p.set_cell(0, 0, "30")
        p.set_cell(1, 0, "40")
        p.imr_chart({"variables": [0]})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "owned_project.mpx"
            p.save(str(out))
            p2 = Presenter()
            p2.load(str(out))
            self.assertEqual(len(p2.worksheets), 2)
            self.assertEqual([w.name for w in p2.worksheets], ["Untitled", "Run2"])
            self.assertEqual(p2.worksheets[0].columns[0].metadata.get("description"), "Measurement X")
            self.assertEqual(p2.worksheets[0].columns[0].metadata.get("cell_comments", {}).get("0"), "Baseline sample")
            self.assertTrue(any("I-MR Chart" in e.get("title", "") for e in p2.history))

    @unittest.skipUnless(CORPUS_DIR.is_dir(), "Local mpx-research corpus directory not present")
    def test_03_real_minitab22_corpus_analyses_and_mpx_roundtrip(self):
        expected_files = [
            "ANOVA-SALES.mpx",
            "SPC - P CHART.mpx",
            "SPC - U CHART.mpx",
            "SPC-I-MR.mpx",
            "SPC-XBAR-R.mpx",
            "TEST FOR EQUAL VARIANCES.mpx",
        ]
        for fname in expected_files:
            fpath = CORPUS_DIR / fname
            self.assertTrue(fpath.is_file(), f"Missing corpus file: {fpath}")

        # 1. ANOVA-SALES.mpx: unstacked (sheet 0) + stacked (sheet 1)
        p = Presenter()
        p.load(str(CORPUS_DIR / "ANOVA-SALES.mpx"))
        self.assertEqual(len(p.worksheets), 2)
        p.select_worksheet(0)
        e_un = p.oneway_anova_unstacked([0, 1, 2])
        self.assertIn("One-Way ANOVA", e_un["title"])
        p.select_worksheet(1)
        e_st = p.oneway_anova(response_index=1, factor_index=0, stacked=True)
        self.assertIn("One-Way ANOVA", e_st["title"])

        # 2. SPC - P CHART.mpx
        p = Presenter()
        p.load(str(CORPUS_DIR / "SPC - P CHART.mpx"))
        e_p = p.attribute_control_chart({
            "chart_type": "P",
            "variables": [0],
            "is_subgroup_col": True,
            "subgroup_col_idx": 1,
        })
        self.assertIn("P Chart", e_p["title"])

        # 3. SPC - U CHART.mpx
        p = Presenter()
        p.load(str(CORPUS_DIR / "SPC - U CHART.mpx"))
        e_u = p.attribute_control_chart({
            "chart_type": "U",
            "variables": [1],
            "is_subgroup_col": True,
            "subgroup_col_idx": 2,
        })
        self.assertIn("U Chart", e_u["title"])

        # 4. SPC-I-MR.mpx + edit + overlay metadata + save copy + reload
        p = Presenter()
        p.load(str(CORPUS_DIR / "SPC-I-MR.mpx"))
        e_imr = p.imr_chart({"variables": [0]})
        self.assertIn("I-MR Chart", e_imr["title"])
        orig_val = p.worksheet.columns[0].values[0]
        p.set_cell(0, 0, "49.75")
        p.set_cell_comment(0, 0, "Rechecked bag weight")
        p.set_column_description(0, "Net bag weight in kg")
        with tempfile.TemporaryDirectory() as tmp:
            copy_path = Path(tmp) / "SPC-I-MR-edited.mpx"
            p.save(str(copy_path))
            p2 = Presenter()
            p2.load(str(copy_path))
            self.assertAlmostEqual(float(p2.worksheet.columns[0].values[0]), 49.75, places=4)
            self.assertNotEqual(orig_val, 49.75)
            self.assertTrue(any("I-MR Chart" in e.get("title", "") for e in p2.history))
            raw_proj = load_mpx(copy_path)
            self.assertEqual(len(raw_proj.worksheets), 1)

        # 5. SPC-XBAR-R.mpx: stacked (sheet 0) + rows (sheet 1)
        p = Presenter()
        p.load(str(CORPUS_DIR / "SPC-XBAR-R.mpx"))
        self.assertEqual(len(p.worksheets), 2)
        p.select_worksheet(0)
        e_xs = p.xbar_r_stacked(0, 1)
        self.assertIn("Xbar-R", e_xs["title"])
        p.select_worksheet(1)
        e_xr = p.xbar_r_rows([1, 2, 3, 4, 5])
        self.assertIn("Xbar-R", e_xr["title"])

        # 6. TEST FOR EQUAL VARIANCES.mpx
        p = Presenter()
        p.load(str(CORPUS_DIR / "TEST FOR EQUAL VARIANCES.mpx"))
        e_eq = p.equal_variances_stacked(0, 1, method="Levene")
        self.assertIn("Equal Variances", e_eq["title"])


if __name__ == "__main__":
    unittest.main()
