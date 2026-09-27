from __future__ import annotations

import json

from PySide6.QtCore import QSettings


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _is_open(dock) -> bool:
    """Panneau « ouvert » : vrai même s'il est un onglet non affiché.

    ``isHidden()`` est vrai pour un panneau rangé derrière un autre onglet :
    l'utiliser faisait enregistrer Ressources comme fermé dès qu'on regardait
    l'onglet Couleur, et il disparaissait à la session suivante."""
    try:
        return bool(dock.toggleViewAction().isChecked())
    except RuntimeError:
        return False


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
        self._factory_visibility = self._visibility()

    def _visibility(self) -> dict:
        return {dock.objectName(): _is_open(dock) for dock in self.docks if dock.objectName()}

    def _decode(self, raw):
        if raw is None:
            return None
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        if isinstance(raw, dict):
            return {str(k): _truthy(v) for k, v in raw.items()}
        if isinstance(raw, (list, tuple)):
            # Ancien format positionnel : ne s'applique que si la liste des
            # panneaux n'a pas changé depuis, sinon il cachait les mauvais.
            if len(raw) != len(self.docks):
                return None
            return {dock.objectName(): _truthy(v) for dock, v in zip(self.docks, raw)}
        return None

    def _apply_visibility(self, values, previous: dict | None = None) -> None:
        values = self._decode(values) if not isinstance(values, dict) else values
        for dock in self.docks:
            name = dock.objectName()
            if values is not None and name in values:
                dock.setVisible(values[name])
            elif previous is not None and name in previous:
                # Panneau inconnu de l'enregistrement (nouveau) : état d'origine.
                dock.setVisible(previous[name])

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
        self.settings.setValue(f"workspaces/{key}/visibility", json.dumps(self._visibility()))

    def load(self, name: str) -> bool:
        geometry = self.settings.value(f"workspaces/{name}/geometry")
        state = self.settings.value(f"workspaces/{name}/state")
        if geometry is None or state is None:
            return False
        self.window.setUpdatesEnabled(False)
        try:
            # Un ancien état peut contenir un conteneur de tabulation vide
            # (notamment après avoir déplacé puis fermé le dernier dock d'une
            # zone). On masque d'abord les docks connus pour éviter que Qt ne
            # réutilise ce conteneur orphelin pendant restoreState().
            previous = self._visibility()
            for dock in self.docks:
                dock.setVisible(False)
            geometry_ok = self.window.restoreGeometry(geometry)
            state_ok = self.window.restoreState(state, 3)
            self._apply_visibility(self.settings.value(f"workspaces/{name}/visibility"), previous)
        finally:
            self.window.setUpdatesEnabled(True)
            self.window.update()
        return bool(geometry_ok and state_ok)

    def save_session(self) -> None:
        self.settings.setValue("window/geometry", self.window.saveGeometry())
        self.settings.setValue("window/state", self.window.saveState(3))
        visibility = dict(self._visibility())
        if isinstance(self.session_visibility, dict):
            visibility.update(self.session_visibility)
        self.settings.setValue("window/visibility", json.dumps(visibility))
        self.settings.sync()

    def restore_session(self) -> bool:
        geometry = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        if geometry is None or state is None:
            return False
        self.window.setUpdatesEnabled(False)
        try:
            previous = self._visibility()
            for dock in self.docks:
                dock.setVisible(False)
            geometry_ok = self.window.restoreGeometry(geometry)
            state_ok = self.window.restoreState(state, 3)
            self._apply_visibility(self.settings.value("window/visibility"), previous)
        finally:
            self.window.setUpdatesEnabled(True)
            self.window.update()
        return bool(geometry_ok and state_ok)

    def reset(self) -> None:
        self.window.restoreGeometry(self._factory_geometry)
        self.window.restoreState(self._factory_state, 3)
        self._apply_visibility(self._factory_visibility)

    def remove(self, name: str) -> None:
        self.settings.remove(f"workspaces/{name}")
