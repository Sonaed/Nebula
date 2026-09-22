from __future__ import annotations

from PySide6.QtCore import QSettings


class WorkspaceManager:
    """Persists QMainWindow geometry and dock state without owning the docks."""

    def __init__(self, window, settings: QSettings | None = None) -> None:
        self.window = window
        self.settings = settings or QSettings("CreativeSystem", "CreativeSystem")
        self._factory_geometry = window.saveGeometry()
        self._factory_state = window.saveState(3)
        self.docks = ()
        self._factory_visibility = ()
        self.session_visibility = None

    def set_docks(self, docks) -> None:
        self.docks = tuple(docks)
        self._factory_visibility = tuple(not dock.isHidden() for dock in self.docks)

    def _visibility(self):
        return [not dock.isHidden() for dock in self.docks]

    def _apply_visibility(self, values) -> None:
        if values is None:
            return
        for dock, visible in zip(self.docks, values):
            dock.setVisible(bool(visible))

    def names(self) -> list[str]:
        self.settings.beginGroup("workspaces")
        names = sorted(self.settings.childGroups())
        self.settings.endGroup()
        return names

    def save(self, name: str) -> None:
        key = name.strip()
        if not key:
            raise ValueError("Le nom du workspace ne peut pas être vide")
        self.settings.setValue(f"workspaces/{key}/geometry", self.window.saveGeometry())
        self.settings.setValue(f"workspaces/{key}/state", self.window.saveState(3))
        self.settings.setValue(f"workspaces/{key}/visibility", self._visibility())

    def load(self, name: str) -> bool:
        geometry = self.settings.value(f"workspaces/{name}/geometry")
        state = self.settings.value(f"workspaces/{name}/state")
        if geometry is None or state is None:
            return False
        self.window.setUpdatesEnabled(False)
        try:
            geometry_ok = self.window.restoreGeometry(geometry)
            state_ok = self.window.restoreState(state, 3)
            self._apply_visibility(self.settings.value(f"workspaces/{name}/visibility"))
        finally:
            self.window.setUpdatesEnabled(True)
            self.window.update()
        return bool(geometry_ok and state_ok)

    def save_session(self) -> None:
        self.settings.setValue("window/geometry", self.window.saveGeometry())
        self.settings.setValue("window/state", self.window.saveState(3))
        self.settings.setValue("window/visibility", self.session_visibility or self._visibility())

    def restore_session(self) -> bool:
        geometry = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        if geometry is None or state is None:
            return False
        geometry_ok = self.window.restoreGeometry(geometry)
        state_ok = self.window.restoreState(state, 3)
        self._apply_visibility(self.settings.value("window/visibility"))
        return bool(geometry_ok and state_ok)

    def reset(self) -> None:
        self.window.restoreGeometry(self._factory_geometry)
        self.window.restoreState(self._factory_state, 3)
        self._apply_visibility(self._factory_visibility)

    def remove(self, name: str) -> None:
        self.settings.remove(f"workspaces/{name}")
