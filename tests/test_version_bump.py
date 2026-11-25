import re
import unittest
from pathlib import Path

import statcraft
from statcraft import updater

ROOT = Path(__file__).resolve().parent.parent


class TestVersionBump(unittest.TestCase):
    def test_version_alignment(self):
        self.assertEqual(statcraft.__version__, updater.STATCRAFT_VERSION)
        ver_tuple = tuple(int(x) for x in statcraft.__version__.split("."))
        self.assertEqual(len(ver_tuple), 3)
        self.assertGreaterEqual(ver_tuple, (122, 0, 0))

        expected3 = statcraft.__version__
        expected4 = f"{expected3}.0"

        pyproj = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m_proj = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproj, re.MULTILINE)
        self.assertIsNotNone(m_proj)
        self.assertEqual(m_proj.group(1), expected3)

        for rc_name in ("app_version.txt", "installer_version.txt"):
            rc_text = (ROOT / rc_name).read_text(encoding="utf-8")
            self.assertIn(f"filevers=({', '.join(expected4.split('.'))})", rc_text, rc_name)
            self.assertIn(f"StringStruct('FileVersion', '{expected4}')", rc_text, rc_name)
            self.assertIn(f"StringStruct('ProductVersion', '{expected4}')", rc_text, rc_name)

        for manifest_name in ("app_manifest.xml", "installer_manifest.xml"):
            mf_text = (ROOT / manifest_name).read_text(encoding="utf-8")
            m_mf = re.search(r'<assemblyIdentity[\s\S]*?version="([^"]+)"', mf_text)
            self.assertIsNotNone(m_mf, manifest_name)
            self.assertEqual(m_mf.group(1), expected4, manifest_name)


if __name__ == "__main__":
    unittest.main()
