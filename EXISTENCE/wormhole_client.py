"""Nebula ⇄ Wormholes d'Existence.

* Image ▸ Wormhole ▸ Envoyer le calque / l'image vers <app>
* Image ▸ Wormhole ▸ Lier le calque en direct avec <app>
  → chaque trait sur ce calque est publié ; chaque modification faite dans
    l'autre app revient automatiquement dans le calque (annulable par Ctrl+Z).
* Ce qu'une autre app envoie arrive comme nouveau calque (ou nouveau
  document si aucun n'est ouvert).

Si Existence (Existence) est introuvable, tout reste silencieusement inactif.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QMenu, QMessageBox

APP_ID = "nebula"


def _load_wormhole():
    root = Path(os.environ.get("EXISTENCE_ROOT", "/home/deanos/Documents/Existence"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from modules.wormhole import Wormhole
        return Wormhole(APP_ID)
    except (ImportError, OSError):
        return None


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class NebulaWormholes(QObject):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.hole = _load_wormhole()
        self.layer_links: dict[str, str] = {}   # link id → layer id
        self.seen: dict[str, int] = {}          # link id → dernière révision appliquée
        self._dirty: set[str] = set()           # layer ids à publier
        self._applying = False
        if self.hole is None:
            return
        self.hole.heartbeat()
        self._beat = QTimer(self)
        self._beat.setInterval(5000)
        self._beat.timeout.connect(self.hole.heartbeat)
        self._beat.start()
        self._poll = QTimer(self)
        self._poll.setInterval(900)
        self._poll.timeout.connect(self.poll)
        self._poll.start()
        self._publish_timer = QTimer(self)
        self._publish_timer.setInterval(700)
        self._publish_timer.setSingleShot(True)
        self._publish_timer.timeout.connect(self._publish_dirty)
        canvas = app.canvas
        canvas.layer_thumbnail_dirty.connect(self._layer_changed)
        canvas.history_restored.connect(self._history_restored)
        self._build_menu()
        self._restore_links()
        QTimer.singleShot(400, self.poll)  # envois reçus avant le lancement

    # ── menu ──
    def _build_menu(self) -> None:
        export = self.app.ui.actions.get("export")
        menu = None
        for candidate in self.app.menuBar().findChildren(QMenu):
            if export is not None and export in candidate.actions():
                menu = candidate
                break
        if menu is None:
            menu = self.app.menuBar().addMenu("Image")
        self.menu = menu.addMenu("Wormhole ⇄")
        self.menu.aboutToShow.connect(self._fill_menu)
        self.app.ui.actions["wormhole_menu"] = self.menu.menuAction()

    def _fill_menu(self) -> None:
        menu = self.menu
        menu.clear()
        targets = self.hole.destinations("image")
        live_targets = self.hole.destinations("image", live=True)
        has_doc = self._document() is not None
        connected = getattr(self.app, "_existence_module_connected", lambda *_: True)
        if any(a == "nova" for a, _ in live_targets) and connected("nova"):
            develop = menu.addAction("✺ Développer le calque avec Nova (lien en direct)",
                                     lambda: self.send_layer("nova", live=True))
            develop.setEnabled(has_doc)
            menu.addSeparator()
        send_layer = menu.addMenu("Envoyer le calque vers")
        send_image = menu.addMenu("Envoyer l'image vers")
        link_layer = menu.addMenu("Lier le calque en direct avec")
        for app_id, name in targets:
            send_layer.addAction(name, lambda a=app_id: self.send_layer(a, live=False))
            send_image.addAction(name, lambda a=app_id: self.send_image(a))
        for app_id, name in live_targets:
            link_layer.addAction(name, lambda a=app_id: self.send_layer(a, live=True))
        for sub, items in ((send_layer, targets), (send_image, targets), (link_layer, live_targets)):
            sub.setEnabled(bool(items) and has_doc)
        menu.addSeparator()
        links = [l for l in self.hole.links() if l["id"] in self.layer_links]
        if links:
            live = menu.addMenu(f"Liens en direct ({len(links)})")
            for record in links:
                other = next((a for a in record["apps"] if a != APP_ID), "?")
                live.addAction(f"Délier « {record['name']} » ⇄ {other}", lambda l=record["id"]: self.unlink(l))
        else:
            empty = menu.addAction("Aucun lien en direct")
            empty.setEnabled(False)

    # ── accès document ──
    def _document(self):
        canvas = getattr(self.app, "canvas", None)
        return getattr(canvas, "document", None) if canvas is not None else None

    def _layer_by_id(self, layer_id: str):
        document = self._document()
        for layer in getattr(document, "layers", []) or []:
            if getattr(layer, "id", None) == layer_id:
                return layer
        return None

    def _fit(self, image: QImage, width: int, height: int) -> QImage:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        if image.width() == width and image.height() == height:
            return image
        canvas = QImage(width, height, QImage.Format.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 0))
        painter = QPainter(canvas)
        painter.drawImage(QPoint((width - image.width()) // 2, (height - image.height()) // 2), image)
        painter.end()
        return canvas

    def _status(self, text: str) -> None:
        try:
            self.app.statusBar().showMessage(text, 5000)
        except RuntimeError:
            pass

    # ── envoi ──
    def send_layer(self, target: str, live: bool) -> None:
        layer = self.app.canvas.get_active_layer()
        if layer is None:
            return
        name = f"{layer.name}.png"
        try:
            message = self.hole.send(target, data=_png_bytes(layer.image), name=name, live=live,
                                     meta={"layer": layer.id, "document": str(getattr(self.app, "current_file", "") or "")})
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.app, "Wormhole", f"Envoi impossible : {exc}")
            return
        if live:
            self.layer_links[message["link"]] = layer.id
            self.seen[message["link"]] = 1
        self._status(f"⇄ « {layer.name} » {'lié en direct avec' if live else 'envoyé vers'} {target}")

    def send_image(self, target: str) -> None:
        try:
            image = self.app.create_composite_image()
            self.hole.send(target, data=_png_bytes(image), name="image.png")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self.app, "Wormhole", f"Envoi impossible : {exc}")
            return
        self._status(f"⇄ Image envoyée vers {target}")

    def unlink(self, link_id: str) -> None:
        self.hole.unlink(link_id)
        self.layer_links.pop(link_id, None)
        self.seen.pop(link_id, None)
        self._status("Lien en direct retiré")

    # ── réception ──
    def poll(self) -> None:
        if self.hole is None:
            return
        for message in self.hole.receive():
            try:
                self._receive(message)
            except Exception as exc:  # noqa: BLE001 — un envoi invalide ne doit jamais faire tomber Nebula
                self._status(f"Wormhole : envoi ignoré ({exc})")
        self._apply_updates()

    def _receive(self, message: dict) -> None:
        if message.get("kind") == "control":
            target = message.get("to", "")
            if message.get("action") == "link_active" and target:
                if self._document() is None or self.app.canvas.get_active_layer() is None:
                    self._status("Wormhole : ouvre un document et choisis un calque à lier")
                    return
                self.send_layer(target, live=True)
                try:
                    self.app.raise_()
                    self.app.activateWindow()
                except RuntimeError:
                    pass
            return
        image = QImage(message["path"])
        if image.isNull():
            raise ValueError("image illisible")
        source = message.get("source", "?")
        link_id = message.get("link", "")
        ui = self.app.ui
        on_home = getattr(ui, "stack", None) is not None and ui.stack.currentWidget() is getattr(ui, "home_page", None)
        workspace_open = self._document() is not None and not on_home
        if not workspace_open:
            self.app.open_file(message["path"])
            layer = self.app.canvas.get_active_layer()
        else:
            document = self._document()
            fitted = self._fit(image, document.width, document.height)
            holder = {}

            def add():
                layer = self.app.layer_manager.add_layer(f"⇠ {source} · {message.get('name', 'envoi')}")
                layer.image = fitted
                holder["layer"] = layer
                return True

            self.app._with_layer_history(add, structure_only=False)
            layer = holder.get("layer")
            self._refresh(layer)
        if link_id and layer is not None:
            self.layer_links[link_id] = layer.id
            record = self.hole.link(link_id) or {}
            self.seen[link_id] = int(record.get("rev", 1))
            self.hole.attach(link_id, {"layer": layer.id})
        self._status(f"⇠ Reçu de {source} : {message.get('name', '')}" + (" (lien en direct)" if link_id else ""))
        try:
            self.app.raise_()
            self.app.activateWindow()
        except RuntimeError:
            pass

    def _apply_updates(self) -> None:
        for record in self.hole.updates(self.seen):
            link_id = record["id"]
            layer = self._layer_by_id(self.layer_links.get(link_id, ""))
            self.seen[link_id] = int(record.get("rev", 1))
            if layer is None:
                continue
            image = QImage(record["file"])
            if image.isNull():
                continue
            document = self._document()
            fitted = self._fit(image, document.width, document.height)

            def replace(layer=layer, fitted=fitted):
                layer.image = fitted
                return True

            self._applying = True
            try:
                self.app._with_layer_history(replace)
            finally:
                self._applying = False
            self._refresh(layer)
            self._status(f"⇠ « {layer.name} » mis à jour par {record.get('writer', '?')}")

    def _refresh(self, layer) -> None:
        canvas = self.app.canvas
        invalidate = getattr(canvas, "_invalidate_gpu_after_history", None)
        if callable(invalidate):
            invalidate()
        if layer is not None:
            try:
                self.app.ui.layers_dock.invalidate_thumb_cache(layer.id)
            except (AttributeError, RuntimeError):
                pass
        self.app.refresh_layers()
        canvas.update()

    # ── publication des modifications locales ──
    def _layer_changed(self, layer_id: str) -> None:
        if self._applying or layer_id not in self.layer_links.values():
            return
        self._dirty.add(layer_id)
        self._publish_timer.start()

    def _history_restored(self) -> None:
        if self._applying:
            return
        self._dirty.update(self.layer_links.values())
        if self._dirty:
            self._publish_timer.start()

    def _publish_dirty(self) -> None:
        dirty, self._dirty = self._dirty, set()
        for link_id, layer_id in list(self.layer_links.items()):
            if layer_id not in dirty:
                continue
            layer = self._layer_by_id(layer_id)
            if layer is None:
                continue
            try:
                self.seen[link_id] = self.hole.publish(link_id, data=_png_bytes(layer.image))
            except KeyError:
                # Lien retiré ailleurs (Existence, autre app).
                self.layer_links.pop(link_id, None)
            except OSError as exc:
                self._status(f"Wormhole : publication impossible ({exc})")

    def _restore_links(self) -> None:
        """Après un redémarrage : retrouve les calques liés encore ouverts."""
        for record in self.hole.links():
            ref = (record.get("refs") or {}).get(APP_ID, {})
            if ref.get("layer") and self._layer_by_id(ref["layer"]) is not None:
                self.layer_links[record["id"]] = ref["layer"]
                self.seen[record["id"]] = int(record.get("rev", 1))

    def shutdown(self) -> None:
        if self.hole is not None:
            self.hole.leave()


def install(app) -> NebulaWormholes | None:
    try:
        return NebulaWormholes(app)
    except Exception as exc:  # noqa: BLE001
        print(f"[Nebula] Wormholes indisponibles : {exc}", file=sys.stderr)
        return None
