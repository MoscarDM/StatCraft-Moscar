"""Settings storage for normal StatCraft and Live Sandbox."""

from pathlib import Path

from PySide6.QtCore import QSettings

_sandbox_workspace: Path | None = None


def configure_sandbox_process(workspace: Path) -> None:
    """Set the settings location for process-wide services such as R discovery."""
    global _sandbox_workspace
    _sandbox_workspace = workspace


def settings_for_process() -> QSettings:
    return settings_for_mode(_sandbox_workspace is not None, sandbox_workspace=_sandbox_workspace)


def settings_for_mode(sandbox_mode: bool = False, *, sandbox_workspace: Path | None = None) -> QSettings:
    """Store Sandbox preferences in its workspace, outside the Windows Registry."""
    if not sandbox_mode:
        return QSettings("StatCraft", "StatCraft")
    if sandbox_workspace is None:
        raise ValueError("Sandbox settings require a workspace")
    settings = QSettings(str(sandbox_workspace / "ui-settings.ini"), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    return settings
