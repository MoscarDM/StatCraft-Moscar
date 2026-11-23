import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from statcraft.settings_scope import settings_for_mode


class SettingsScopeTests(unittest.TestCase):
    def test_sandbox_preferences_use_only_the_given_ini_file(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            settings = settings_for_mode(True, sandbox_workspace=workspace)
            self.assertEqual(settings.format(), QSettings.Format.IniFormat)
            self.assertEqual(Path(settings.fileName()), workspace / "ui-settings.ini")
            self.assertFalse(settings.fallbacksEnabled())

            settings.setValue("dark_mode", True)
            settings.sync()
            self.assertEqual(settings.status(), QSettings.Status.NoError)
            fresh = settings_for_mode(True, sandbox_workspace=workspace)
            self.assertTrue(fresh.value("dark_mode", False, type=bool))

    def test_sandbox_requires_explicit_workspace(self):
        with self.assertRaises(ValueError):
            settings_for_mode(True)
