import unittest
import statcraft
from statcraft import updater

class TestVersionBump(unittest.TestCase):
    def test_version_118(self):
        self.assertEqual(statcraft.__version__, updater.STATCRAFT_VERSION)
        self.assertGreaterEqual(tuple(int(x) for x in statcraft.__version__.split(".")), (118, 0, 0))

if __name__ == "__main__":
    unittest.main()
