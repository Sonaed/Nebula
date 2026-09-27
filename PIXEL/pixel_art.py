"""Module Pixel Art de Nebula (module Existence ``pixel_art``, orbite Nebula).

Branché dans Existence, il ajoute le panneau « Pixel Art » :

* Crayon / gomme pixel (aucun anticrénelage), pointe 1–16 px carrée ou ronde,
  mode pixel-perfect, ligne droite avec Maj+clic, tramage ordonné (Bayer)
  avec couleur secondaire.
* Palette : palettes intégrées, palettes des Ressources, extraction depuis le
  calque ; verrouillage de la couleur sur la palette ; réduction du calque.
* Grille de pixels et grille de tuiles, zoom entier (×1, ×2, ×4…), rendu net
  au plus proche.
* Tuiles : aperçu en mosaïque, dessin en boucle sur les bords, décalage ½
  (raccords), export des tuiles ou d'une planche.
* Export ×N au plus proche et PNG indexé sur la palette.

Tout le dessin passe par l'historique de Nebula (Ctrl+Z).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform, qRgba
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDockWidget, QFileDialog, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from PIXEL import pixel_core as core

PIXEL_TOOLS = ("pixel", "pixel_eraser")
HINTS = {
    "pixel": "Crayon pixel · Maj+clic : ligne depuis le dernier point · Alt : pipette",
    "pixel_eraser": "Gomme pixel · Maj+clic : ligne depuis le dernier point",
}


def _settings() -> QSettings:
    return QSettings("CreativeSystem", "CreativeSystem")


def _shared_library():
    root = Path(os.environ.get("EXISTENCE_ROOT", "/home/deanos/Documents/Existence"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from modules.resource_center.library import SharedLibrary
        return SharedLibrary()
    except (ImportError, OSError):
        return None


def _palette_from_json(path: Path) -> list[core.Color]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("colors") or data.get("swatches") or []
    colors = []
    for item in raw:
        value = item.get("hex") or item.get("color") if isinstance(item, dict) else item
        if isinstance(value, str):
            try:
                colors.append(core.hex_to_rgb(value))
            except ValueError:
                pass
        elif isinstance(value, (list, tuple)) and len(value) >= 3:
            colors.append(tuple(int(v) for v in value[:3]))
    return colors


# ══════════════════════════════════════════════════════════════
#  Panneau
# ══════════════════════════════════════════════════════════════

class SwatchButton(QToolButton):
    def __init__(self, color: core.Color) -> None:
        super().__init__()
        self.color = color
        self.setFixedSize(22, 22)
        self.setToolTip(core.rgb_to_hex(color))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        border = "#FFFFFF" if selected else "rgba(255,255,255,40)"
        width = 2 if selected else 1
        self.setStyleSheet(f"QToolButton{{background:{core.rgb_to_hex(self.color)};"
                           f"border:{width}px solid {border};border-radius:3px;}}")


class PixelArtPanel(QWidget):
    def __init__(self, controller: "PixelArtController") -> None:
        super().__init__()
        self.c = controller
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        def section(title: str) -> QVBoxLayout:
            label = QLabel(title.upper())
            label.setStyleSheet("color:#8A93B8;font-size:10px;font-weight:600;letter-spacing:1px;padding-top:4px;")
            layout.addWidget(label)
            box = QVBoxLayout()
            box.setSpacing(5)
            layout.addLayout(box)
            return box

        # ── mode & outils
        self.mode = QCheckBox("Mode pixel (rendu net, grille, zoom entier)")
        self.mode.toggled.connect(controller.set_mode)
        layout.addWidget(self.mode)

        box = section("Outil")
        row = QHBoxLayout()
        self.tool_group = QButtonGroup(self)
        for tool, label in (("pixel", "✎ Crayon"), ("pixel_eraser", "⌫ Gomme")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, t=tool: controller.select_tool(t))
            self.tool_group.addButton(button)
            button.setProperty("tool", tool)
            row.addWidget(button)
        fill = QPushButton("▨ Seau")
        fill.setToolTip("Remplissage de Nebula (tolérance 0 conseillée)")
        fill.clicked.connect(lambda: controller.canvas.tools.set_fill())
        row.addWidget(fill)
        box.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Taille"))
        self.size = QSpinBox()
        self.size.setRange(1, 16)
        self.size.setSuffix(" px")
        self.size.valueChanged.connect(lambda v: controller.set_option("size", v))
        row.addWidget(self.size)
        self.shape = QComboBox()
        self.shape.addItem("Carrée", "square")
        self.shape.addItem("Ronde", "round")
        self.shape.currentIndexChanged.connect(lambda _i: controller.set_option("shape", self.shape.currentData()))
        row.addWidget(self.shape)
        box.addLayout(row)
        self.perfect = QCheckBox("Pixel-perfect (supprime les coins en L)")
        self.perfect.toggled.connect(lambda v: controller.set_option("perfect", v))
        box.addWidget(self.perfect)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tramage"))
        self.dither = QComboBox()
        for label, value in (("Aucun", 1.0), ("75 %", .75), ("50 % (damier)", .5), ("25 %", .25), ("12 %", .125)):
            self.dither.addItem(label, value)
        self.dither.currentIndexChanged.connect(lambda _i: controller.set_option("dither", self.dither.currentData()))
        row.addWidget(self.dither, 1)
        box.addLayout(row)
        self.dither_secondary = QCheckBox("Remplir les trous avec la couleur secondaire")
        self.dither_secondary.toggled.connect(lambda v: controller.set_option("dither_secondary", v))
        box.addWidget(self.dither_secondary)
        row = QHBoxLayout()
        row.addWidget(QLabel("Secondaire"))
        self.secondary = QPushButton()
        self.secondary.setFixedHeight(22)
        self.secondary.setToolTip("Clic droit sur une case de palette pour la choisir")
        self.secondary.clicked.connect(controller.swap_colors)
        row.addWidget(self.secondary, 1)
        box.addLayout(row)

        # ── palette
        box = section("Palette")
        row = QHBoxLayout()
        self.palette_combo = QComboBox()
        self.palette_combo.currentIndexChanged.connect(self._palette_chosen)
        row.addWidget(self.palette_combo, 1)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        from PySide6.QtWidgets import QMenu
        menu = QMenu(more)
        menu.addAction("Extraire les couleurs du calque", controller.palette_from_layer)
        menu.addAction("Ajouter la couleur actuelle", controller.add_current_color)
        menu.addAction("Enregistrer dans les Ressources…", controller.save_palette)
        menu.addAction("Recharger les palettes des Ressources", controller.reload_palettes)
        more.setMenu(menu)
        row.addWidget(more)
        box.addLayout(row)
        self.swatch_host = QWidget()
        self.swatch_grid = QGridLayout(self.swatch_host)
        self.swatch_grid.setContentsMargins(0, 0, 0, 0)
        self.swatch_grid.setSpacing(3)
        box.addWidget(self.swatch_host)
        self.lock = QCheckBox("Verrouiller la couleur sur la palette")
        self.lock.toggled.connect(lambda v: controller.set_option("lock_palette", v))
        box.addWidget(self.lock)
        reduce = QPushButton("Réduire le calque à la palette")
        reduce.clicked.connect(controller.reduce_layer)
        box.addWidget(reduce)

        # ── grille & zoom
        box = section("Grille et zoom")
        self.pixel_grid = QCheckBox("Grille de pixels (dès ×6)")
        self.pixel_grid.toggled.connect(lambda v: controller.set_option("pixel_grid", v))
        box.addWidget(self.pixel_grid)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tuiles"))
        self.tile_w = QSpinBox()
        self.tile_h = QSpinBox()
        for spin, key in ((self.tile_w, "tile_w"), (self.tile_h, "tile_h")):
            spin.setRange(0, 512)
            spin.setSpecialValueText("—")
            spin.valueChanged.connect(lambda v, k=key: controller.set_option(k, v))
        row.addWidget(self.tile_w)
        row.addWidget(QLabel("×"))
        row.addWidget(self.tile_h)
        box.addLayout(row)
        self.integer_zoom = QCheckBox("Zoom entier à la molette")
        self.integer_zoom.toggled.connect(lambda v: controller.set_option("integer_zoom", v))
        box.addWidget(self.integer_zoom)
        row = QHBoxLayout()
        for factor in (1, 2, 4, 8, 16):
            button = QPushButton(f"×{factor}")
            button.clicked.connect(lambda _=False, f=factor: controller.set_zoom(f))
            row.addWidget(button)
        box.addLayout(row)

        # ── tuiles
        box = section("Tuiles")
        self.tile_preview = QCheckBox("Aperçu en mosaïque (3 × 3)")
        self.tile_preview.toggled.connect(lambda v: controller.set_option("tile_preview", v))
        box.addWidget(self.tile_preview)
        self.wrap = QCheckBox("Dessin en boucle sur les bords")
        self.wrap.toggled.connect(lambda v: controller.set_option("wrap", v))
        box.addWidget(self.wrap)
        row = QHBoxLayout()
        offset = QPushButton("Décaler ½ (raccords)")
        offset.setToolTip("Décale le calque d'une demi-image en boucle pour travailler les raccords")
        offset.clicked.connect(controller.offset_half)
        row.addWidget(offset)
        export_tiles = QPushButton("Exporter les tuiles…")
        export_tiles.clicked.connect(controller.export_tiles)
        row.addWidget(export_tiles)
        box.addLayout(row)

        # ── document & export
        box = section("Document et export")
        new_doc = QPushButton("Nouveau document pixel…")
        new_doc.clicked.connect(controller.new_pixel_document)
        box.addWidget(new_doc)
        row = QHBoxLayout()
        self.scale = QComboBox()
        for factor in (1, 2, 3, 4, 6, 8, 10, 16):
            self.scale.addItem(f"×{factor}", factor)
        self.scale.setCurrentIndex(3)
        row.addWidget(self.scale)
        export = QPushButton("Exporter PNG net")
        export.clicked.connect(lambda: controller.export_scaled(int(self.scale.currentData())))
        row.addWidget(export, 1)
        box.addLayout(row)
        indexed = QPushButton("Exporter PNG indexé (palette)")
        indexed.clicked.connect(controller.export_indexed)
        box.addWidget(indexed)
        layout.addStretch(1)

    # ── synchronisation
    def load(self, options: dict) -> None:
        widgets = (self.size, self.shape, self.perfect, self.dither, self.dither_secondary, self.lock,
                   self.pixel_grid, self.tile_w, self.tile_h, self.integer_zoom, self.tile_preview, self.wrap)
        for widget in widgets:
            widget.blockSignals(True)
        self.size.setValue(options["size"])
        self.shape.setCurrentIndex(max(0, self.shape.findData(options["shape"])))
        self.perfect.setChecked(options["perfect"])
        self.dither.setCurrentIndex(max(0, self.dither.findData(options["dither"])))
        self.dither_secondary.setChecked(options["dither_secondary"])
        self.lock.setChecked(options["lock_palette"])
        self.pixel_grid.setChecked(options["pixel_grid"])
        self.tile_w.setValue(options["tile_w"])
        self.tile_h.setValue(options["tile_h"])
        self.integer_zoom.setChecked(options["integer_zoom"])
        self.tile_preview.setChecked(options["tile_preview"])
        self.wrap.setChecked(options["wrap"])
        for widget in widgets:
            widget.blockSignals(False)
        self.set_secondary(options["secondary"])

    def set_secondary(self, color: core.Color) -> None:
        self.secondary.setStyleSheet(f"QPushButton{{background:{core.rgb_to_hex(color)};"
                                     f"border:1px solid rgba(255,255,255,60);border-radius:4px;}}")

    def set_tool(self, tool: str) -> None:
        for button in self.tool_group.buttons():
            button.setChecked(button.property("tool") == tool)

    def set_palettes(self, names: list[str], current: str) -> None:
        self.palette_combo.blockSignals(True)
        self.palette_combo.clear()
        self.palette_combo.addItems(names)
        index = self.palette_combo.findText(current)
        self.palette_combo.setCurrentIndex(max(0, index))
        self.palette_combo.blockSignals(False)

    def _palette_chosen(self, _index: int) -> None:
        self.c.choose_palette(self.palette_combo.currentText())

    def show_swatches(self, colors: list[core.Color], selected: core.Color | None) -> None:
        while self.swatch_grid.count():
            item = self.swatch_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, color in enumerate(colors):
            swatch = SwatchButton(color)
            swatch.set_selected(color == selected)
            swatch.clicked.connect(lambda _=False, c=color: self.c.pick_palette_color(c))
            swatch.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            swatch.customContextMenuRequested.connect(lambda _p, c=color: self.c.set_secondary(c))
            self.swatch_grid.addWidget(swatch, index // 8, index % 8)


# ══════════════════════════════════════════════════════════════
#  Contrôleur
# ══════════════════════════════════════════════════════════════

DEFAULTS = {
    "size": 1, "shape": "square", "perfect": True, "dither": 1.0, "dither_secondary": False,
    "lock_palette": False, "pixel_grid": True, "tile_w": 0, "tile_h": 0, "integer_zoom": True,
    "tile_preview": False, "wrap": False, "secondary": (255, 255, 255), "palette": "PICO-8",
}


class PixelArtController(QObject):
    changed = Signal()

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.canvas = app.canvas
        self.enabled = False       # module branché
        self.mode = False          # mode pixel actif
        self.options = self._load_options()
        self.palettes: dict[str, list[core.Color]] = {}
        self.stroke = None
        self.last_point = None
        self.hover = None
        self._tiled_cache = None
        self._tiled_key = None

        self.panel = PixelArtPanel(self)
        self.dock = QDockWidget("Pixel Art", app)
        self.dock.setObjectName("pixel_art_dock")
        self.dock.setWidget(self.panel)
        self.panel.load(self.options)
        self.reload_palettes()
        self.canvas.installEventFilter(self)
        self.canvas.pixel_art = self
        self.canvas.tool_changed.connect(self._tool_changed)
        self.canvas.layer_thumbnail_dirty.connect(lambda *_: self._invalidate_tiles())
        self.canvas.history_restored.connect(self._invalidate_tiles)
        try:
            from UI import ui as ui_module
            ui_module.TOOL_HINTS.update(HINTS)
        except ImportError:
            pass

    # ── options ──
    def _load_options(self) -> dict:
        options = dict(DEFAULTS)
        try:
            stored = json.loads(_settings().value("pixel_art/options", "{}", str) or "{}")
            options.update({k: v for k, v in stored.items() if k in DEFAULTS})
            options["secondary"] = tuple(options["secondary"])
        except (ValueError, TypeError):
            pass
        return options

    def _save_options(self) -> None:
        _settings().setValue("pixel_art/options", json.dumps(self.options))

    def set_option(self, key: str, value) -> None:
        self.options[key] = value
        self._save_options()
        if key in {"tile_preview", "tile_w", "tile_h", "pixel_grid"}:
            self._invalidate_tiles()
        self.canvas.update()

    # ── branchement / mode ──
    def set_available(self, available: bool) -> None:
        self.enabled = bool(available)
        if not available:
            self.set_mode(False)
            if self.canvas.tools.current_tool in PIXEL_TOOLS:
                self.canvas.tools.set_brush()

    def set_mode(self, on: bool) -> None:
        on = bool(on) and self.enabled
        if self.panel.mode.isChecked() != on:
            self.panel.mode.blockSignals(True)
            self.panel.mode.setChecked(on)
            self.panel.mode.blockSignals(False)
        if on == self.mode:
            return
        self.mode = on
        try:
            from CANVAS import gpu_renderer
            gpu_renderer.PIXEL_NEAREST[0] = on
        except ImportError:
            pass
        invalidate = getattr(self.canvas, "_invalidate_gpu_after_history", None)
        if callable(invalidate):
            invalidate()  # re-téléverse les textures avec le nouveau filtrage
        if on and self.canvas.tools.current_tool not in PIXEL_TOOLS:
            self.select_tool("pixel")
        self.canvas.update()

    def select_tool(self, tool: str) -> None:
        if not self.enabled:
            return
        if not self.mode:
            self.set_mode(True)
        self.canvas.tools._select_tool(tool, eraser=(tool == "pixel_eraser"))
        self.panel.set_tool(tool)

    def _tool_changed(self, tool: str) -> None:
        self.panel.set_tool(tool)
        self.canvas.update()

    # ── couleurs ──
    def primary(self) -> tuple[int, int, int, int]:
        r, g, b, a = self.canvas.brush_settings.snapshot()["color"]
        return int(r), int(g), int(b), int(a)

    def set_primary(self, color: core.Color) -> None:
        self.canvas.set_brush_setting("color", [color[0], color[1], color[2], 255])
        try:
            self.app.ui.set_color(core.rgb_to_hex(color).lower())
        except AttributeError:
            pass
        self.panel.show_swatches(self.current_palette(), color)

    def set_secondary(self, color: core.Color) -> None:
        self.options["secondary"] = tuple(color)
        self._save_options()
        self.panel.set_secondary(color)

    def swap_colors(self) -> None:
        primary = self.primary()[:3]
        secondary = self.options["secondary"]
        self.set_secondary(primary)
        self.set_primary(secondary)

    def pick_palette_color(self, color: core.Color) -> None:
        self.set_primary(color)
        if self.canvas.tools.current_tool not in PIXEL_TOOLS and self.mode:
            self.select_tool("pixel")

    # ── palettes ──
    def current_palette(self) -> list[core.Color]:
        return self.palettes.get(self.options["palette"]) or self.palettes.get("PICO-8", [])

    def reload_palettes(self) -> None:
        palettes = {name: [core.hex_to_rgb(h) for h in hexes] for name, hexes in core.BUILTIN_PALETTES.items()}
        library = _shared_library()
        if library is not None:
            try:
                for entry in library.entries(app="nebula", kind="palettes"):
                    colors = _palette_from_json(Path(entry["path"]))
                    if colors:
                        palettes[f"◇ {entry['name']}"] = colors
            except OSError:
                pass
        custom = self.options.get("custom_palette")
        if custom:
            palettes["Personnalisée"] = [tuple(c) for c in custom]
        self.palettes = palettes
        if self.options["palette"] not in palettes:
            self.options["palette"] = "PICO-8"
        self.panel.set_palettes(list(palettes), self.options["palette"])
        self.panel.show_swatches(self.current_palette(), self.primary()[:3])

    def choose_palette(self, name: str) -> None:
        if name in self.palettes:
            self.options["palette"] = name
            self._save_options()
            self.panel.show_swatches(self.current_palette(), self.primary()[:3])

    def _set_custom(self, colors: list[core.Color]) -> None:
        self.palettes["Personnalisée"] = colors
        self.options["palette"] = "Personnalisée"
        self.options["custom_palette"] = [list(c) for c in colors]
        DEFAULTS.setdefault("custom_palette", [])
        self._save_options()
        self.panel.set_palettes(list(self.palettes), "Personnalisée")
        self.panel.show_swatches(colors, self.primary()[:3])

    def palette_from_layer(self) -> None:
        layer = self.canvas.get_active_layer()
        if layer is None:
            return
        image = layer.image.convertToFormat(QImage.Format.Format_RGBA8888)
        colors = core.unique_colors(self._pixels(image), limit=64)
        if not colors:
            QMessageBox.information(self.app, "Pixel Art", "Le calque actif est vide.")
            return
        self._set_custom(colors)

    def add_current_color(self) -> None:
        colors = list(self.current_palette())
        color = self.primary()[:3]
        if color not in colors:
            colors.append(color)
        self._set_custom(colors)

    def save_palette(self) -> None:
        name, ok = QInputDialog.getText(self.app, "Enregistrer la palette", "Nom de la palette :",
                                        text=self.options["palette"].lstrip("◇ "))
        if not ok or not name.strip():
            return
        library = _shared_library()
        if library is None:
            QMessageBox.warning(self.app, "Pixel Art", "Bibliothèque de Ressources introuvable.")
            return
        payload = {"format": "CreativeSystemPalette", "version": 2, "name": name.strip(),
                   "colors": [core.rgb_to_hex(c) for c in self.current_palette()], "source": "nebula/pixel_art"}
        library.add_json("palettes", name.strip(), payload, owner="nebula")
        self.reload_palettes()
        self.choose_palette(f"◇ {name.strip()}")

    @staticmethod
    def _pixels(image: QImage):
        width, height = image.width(), image.height()
        data = bytes(image.constBits())[: image.sizeInBytes()]
        stride = image.bytesPerLine()
        for y in range(height):
            row = y * stride
            for x in range(width):
                i = row + x * 4
                yield data[i], data[i + 1], data[i + 2], data[i + 3]

    # ── dessin ──
    def _color_for(self, x: int, y: int, erase: bool):
        """ARGB final du pixel, ou None s'il ne doit pas être touché."""
        if erase:
            return 0 if core.dither_on(x, y, float(self.options["dither"])) else None
        r, g, b, a = self.primary()
        if self.options["lock_palette"]:
            r, g, b = core.nearest((r, g, b), self.current_palette())
        if not core.dither_on(x, y, float(self.options["dither"])):
            if not self.options["dither_secondary"]:
                return None
            r, g, b = self.options["secondary"]
            a = 255
        return qRgba(r, g, b, a)

    def _begin(self, point: tuple[int, int], shift: bool) -> None:
        layer = self.canvas.get_active_layer()
        if layer is None or layer.locked or getattr(layer, "layer_kind", "raster") != "raster":
            return
        self.canvas.begin_stroke_history()
        self.stroke = {
            "layer": layer, "image": layer.image, "erase": self.canvas.tools.current_tool == "pixel_eraser",
            "path": [], "original": {}, "dirty": None, "alpha_lock": bool(getattr(layer, "lock_alpha", False)),
        }
        if shift and self.last_point is not None:
            for p in core.line(*self.last_point, *point):
                self._extend(p, freehand=False)
        else:
            self._extend(point, freehand=True)
        self._flush()

    def _extend(self, point: tuple[int, int], freehand: bool = True) -> None:
        stroke = self.stroke
        path = stroke["path"]
        segment = core.line(*path[-1], *point) if path else [point]
        for p in segment:
            if path and path[-1] == p:
                continue
            path.append(p)
            self._stamp(p)
            if (freehand and self.options["perfect"] and int(self.options["size"]) == 1
                    and len(path) >= 3):
                (ax, ay), (bx, by), (cx, cy) = path[-3], path[-2], path[-1]
                if (abs(ax - bx) + abs(ay - by) == 1 and abs(bx - cx) + abs(by - cy) == 1
                        and abs(ax - cx) == 1 and abs(ay - cy) == 1):
                    self._restore(path[-2])
                    del path[-2]
        self.last_point = point

    def _targets(self, point: tuple[int, int]) -> list[tuple[int, int]]:
        image = self.stroke["image"]
        points = core.expand([point], core.stamp(int(self.options["size"]), self.options["shape"]))
        if self.options["wrap"]:
            return core.wrap(points, image.width(), image.height())
        return core.clip(points, image.width(), image.height())

    def _touch(self, x: int, y: int) -> None:
        rect = QRect(x, y, 1, 1)
        dirty = self.stroke["dirty"]
        self.stroke["dirty"] = rect if dirty is None else dirty.united(rect)

    def _stamp(self, point: tuple[int, int]) -> None:
        stroke = self.stroke
        image = stroke["image"]
        for x, y in self._targets(point):
            color = self._color_for(x, y, stroke["erase"])
            if color is None:
                continue
            old = image.pixel(x, y)
            if stroke["alpha_lock"]:
                if (old >> 24) == 0:
                    continue
                color = (old & 0xFF000000) | (color & 0x00FFFFFF)
            stroke["original"].setdefault((x, y), old)
            if old != color:
                image.setPixel(x, y, color)
                self._touch(x, y)

    def _restore(self, point: tuple[int, int]) -> None:
        stroke = self.stroke
        for x, y in self._targets(point):
            old = stroke["original"].get((x, y))
            if old is not None:
                stroke["image"].setPixel(x, y, old)
                self._touch(x, y)

    def _flush(self) -> None:
        stroke = self.stroke
        if stroke is None or stroke["dirty"] is None:
            return
        layer = stroke["layer"]
        if getattr(layer, "_image_cache", None) is not stroke["image"]:
            # Le rendu a pu libérer le cache du calque pendant le trait :
            # on lui redonne notre image (contient déjà tout le trait).
            layer.adopt_image_cache(stroke["image"])
        layer.mark_image_cache_dirty()
        self.canvas.sync_gpu_layer(stroke["dirty"].adjusted(-1, -1, 1, 1))
        stroke["dirty"] = None

    def _end(self) -> None:
        stroke = self.stroke
        if stroke is None:
            return
        self._flush()
        self.stroke = None
        self.canvas.commit_stroke_history()
        self.canvas.layer_thumbnail_dirty.emit(stroke["layer"].id)

    def _image_point(self, position) -> tuple[int, int]:
        p = self.canvas.screen_to_image_f(QPointF(position))
        import math
        return int(math.floor(p.x())), int(math.floor(p.y()))

    # ── interception des évènements du canvas ──
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is not self.canvas or not self.enabled:
            return False
        etype = event.type()
        if etype == QEvent.Type.Wheel and self.mode and self.options["integer_zoom"]:
            if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                return False
            delta = event.angleDelta().y()
            if delta:
                self._zoom_step(1 if delta > 0 else -1, event.position())
                return True
            return False
        if etype in (QEvent.Type.MouseButtonRelease, QEvent.Type.TabletRelease) and self.stroke is not None:
            # Toujours terminer un trait commencé, même si l'outil a changé entre-temps.
            self._end()
            event.accept()
            return True
        if self.canvas.tools.current_tool not in PIXEL_TOOLS:
            return False
        if getattr(self.canvas, "space_pressed", False):
            return False  # la barre d'espace garde la main pour la navigation
        if etype in (QEvent.Type.MouseMove, QEvent.Type.TabletMove):
            point = self._image_point(event.position())
            if point != self.hover:
                self.hover = point
                self.canvas.update()
        if etype in (QEvent.Type.MouseButtonPress, QEvent.Type.TabletPress):
            button = event.button()
            if button != Qt.MouseButton.LeftButton:
                return False
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                return False  # pipette temporaire de Nebula
            self._begin(self._image_point(event.position()),
                        bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
            return True
        if etype in (QEvent.Type.MouseMove, QEvent.Type.TabletMove) and self.stroke is not None:
            self._extend(self._image_point(event.position()))
            self._flush()
            event.accept()
            return True
        if etype in (QEvent.Type.MouseButtonRelease, QEvent.Type.TabletRelease) and self.stroke is not None:
            self._end()
            event.accept()
            return True
        if etype == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            return True
        return False

    # ── zoom ──
    def _zoom_step(self, direction: int, position) -> None:
        zoom = float(self.canvas.zoom)
        target = core.next_integer_zoom(zoom, direction)
        if abs(target - zoom) > 1e-6:
            self.canvas.zoom_at(QPointF(position), target / zoom)
            if hasattr(self.app.ui, "set_zoom"):
                self.app.ui.set_zoom(float(self.canvas.zoom))

    def set_zoom(self, factor: float) -> None:
        zoom = float(self.canvas.zoom)
        center = QPointF(self.canvas.width() / 2, self.canvas.height() / 2)
        self.canvas.zoom_at(center, factor / zoom)
        if hasattr(self.app.ui, "set_zoom"):
            self.app.ui.set_zoom(float(self.canvas.zoom))

    # ── rendu des aides ──
    def _image_transform(self) -> QTransform:
        c = self.canvas

        def to_screen(x: float, y: float) -> QPointF:
            return c._view_transform_point(c.offset + QPointF(x, y) * c.zoom)

        origin = to_screen(0, 0)
        ex = to_screen(1, 0) - origin
        ey = to_screen(0, 1) - origin
        return QTransform(ex.x(), ex.y(), ey.x(), ey.y(), origin.x(), origin.y())

    def _invalidate_tiles(self) -> None:
        self._tiled_cache = None

    def _composite(self) -> QImage | None:
        if self._tiled_cache is None:
            try:
                self._tiled_cache = self.app.create_composite_image()
            except (RuntimeError, AttributeError):
                self._tiled_cache = None
        return self._tiled_cache

    def paint_overlay(self, painter: QPainter) -> None:
        if not (self.enabled and self.mode):
            return
        document = getattr(self.canvas, "document", None)
        if document is None:
            return
        width, height = document.width, document.height
        zoom = float(self.canvas.zoom)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setTransform(self._image_transform(), True)

        if self.options["tile_preview"]:
            composite = self._composite()
            if composite is not None:
                painter.setOpacity(0.45)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx or dy:
                            painter.drawImage(QPointF(dx * width, dy * height), composite)
                painter.setOpacity(1.0)

        pen = QPen(QColor(255, 255, 255, 34))
        pen.setCosmetic(True)
        if self.options["pixel_grid"] and zoom >= 6:
            painter.setPen(pen)
            for x in range(width + 1):
                painter.drawLine(QPointF(x, 0), QPointF(x, height))
            for y in range(height + 1):
                painter.drawLine(QPointF(0, y), QPointF(width, y))
        tw, th = int(self.options["tile_w"]), int(self.options["tile_h"])
        if tw > 0 or th > 0:
            tile_pen = QPen(QColor(34, 211, 238, 140))
            tile_pen.setCosmetic(True)
            painter.setPen(tile_pen)
            if tw > 0:
                for x in range(0, width + 1, tw):
                    painter.drawLine(QPointF(x, 0), QPointF(x, height))
            if th > 0:
                for y in range(0, height + 1, th):
                    painter.drawLine(QPointF(0, y), QPointF(width, y))

        if self.hover is not None and self.canvas.tools.current_tool in PIXEL_TOOLS:
            offsets = core.stamp(int(self.options["size"]), self.options["shape"])
            cells = core.expand([self.hover], offsets)
            if self.options["wrap"]:
                cells = core.wrap(cells, width, height)
            outline = QPen(QColor(255, 255, 255, 200))
            outline.setCosmetic(True)
            painter.setPen(outline)
            r, g, b, _a = self.primary()
            fill = QColor(r, g, b, 110 if self.canvas.tools.current_tool == "pixel" else 0)
            for x, y in cells[:1024]:
                painter.fillRect(QRect(x, y, 1, 1), fill)
            xs = [c[0] for c in cells] or [0]
            ys = [c[1] for c in cells] or [0]
            painter.drawRect(QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
        painter.restore()

    # ── opérations sur le calque ──
    def _replace_active(self, transform) -> bool:
        layer = self.canvas.get_active_layer()
        if layer is None or layer.locked:
            return False
        image = layer.image.convertToFormat(QImage.Format.Format_ARGB32)
        result = transform(image)
        if result is None:
            return False

        def apply():
            layer.image = result
            return True

        self.app._with_layer_history(apply)
        invalidate = getattr(self.canvas, "_invalidate_gpu_after_history", None)
        if callable(invalidate):
            invalidate()
        self.canvas.layer_thumbnail_dirty.emit(layer.id)
        self.canvas.update()
        return True

    def reduce_layer(self) -> None:
        mapper = core.PaletteMapper(self.current_palette())

        def reduce(image: QImage):
            out = QImage(image)
            for y in range(out.height()):
                for x in range(out.width()):
                    value = out.pixel(x, y)
                    alpha = value >> 24
                    if alpha == 0:
                        continue
                    r, g, b = mapper(((value >> 16) & 255, (value >> 8) & 255, value & 255))
                    out.setPixel(x, y, qRgba(r, g, b, 255 if alpha >= 128 else 0))
            return out

        if self.canvas.document.width * self.canvas.document.height > 2048 * 2048:
            if QMessageBox.question(self.app, "Pixel Art", "Le document est grand : la réduction peut prendre du temps. Continuer ?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self._replace_active(reduce)

    def offset_half(self) -> None:
        def shift(image: QImage):
            w, h = image.width(), image.height()
            out = QImage(w, h, QImage.Format.Format_ARGB32)
            out.fill(0)
            painter = QPainter(out)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            hx, hy = w // 2, h // 2
            for dx, dy in ((0, 0), (-w, 0), (0, -h), (-w, -h)):
                painter.drawImage(hx + dx, hy + dy, image)
            painter.end()
            return out

        self._replace_active(shift)

    # ── document & export ──
    def new_pixel_document(self) -> None:
        sizes = ["16 × 16", "24 × 24", "32 × 32", "48 × 48", "64 × 64", "128 × 128", "256 × 256", "320 × 180", "Autre…"]
        choice, ok = QInputDialog.getItem(self.app, "Nouveau document pixel", "Taille :", sizes, 2, False)
        if not ok:
            return
        if choice == "Autre…":
            text, ok = QInputDialog.getText(self.app, "Nouveau document pixel", "Largeur × hauteur :", text="96 × 64")
            if not ok:
                return
            choice = text
        try:
            width, height = (int(part.strip()) for part in choice.lower().replace("x", "×").split("×")[:2])
        except ValueError:
            return
        from DOCUMENTS.document import Document
        from DOCUMENTS.layer_manager import LayerManager
        document = Document(max(1, width), max(1, height), 72, None)
        app = self.app
        app.canvas.set_document(document)
        app.layer_manager = LayerManager(document)
        app.document_manager.documents.append(document)
        app.document_manager.active_document = document
        app.current_file = None
        app._last_saved_history_index = app.canvas.tile_history.index
        app.refresh_layers()
        app.update_window_title()
        app.ui.show_workspace()
        self.set_mode(True)
        fit = max(1, min(64, int(min(self.canvas.width() * .8 / width, self.canvas.height() * .8 / height))))
        self.set_zoom(float(core.next_integer_zoom(fit + .5, -1)))

    def apply_canvas_preset(self, preset: dict) -> None:
        """Toile prête : mode pixel, crayon, palette, grille de tuiles, zoom entier."""
        self.set_mode(True)
        tile = int(preset.get("tile") or 0)
        wrap = bool(preset.get("wrap"))
        self.options.update(tile_w=tile, tile_h=tile, wrap=wrap, tile_preview=wrap,
                            pixel_grid=True, integer_zoom=True)
        if preset.get("palette") in self.palettes:
            self.options["palette"] = preset["palette"]
        self._save_options()
        self.panel.load(self.options)
        self.panel.set_palettes(list(self.palettes), self.options["palette"])
        palette = self.current_palette()
        if palette:
            self.set_primary(palette[0] if len(palette) < 3 else palette[1])
        self.select_tool("pixel")
        self.dock.show()
        self.dock.raise_()
        self.set_zoom(float(preset.get("zoom") or 8))
        self._invalidate_tiles()
        self.canvas.update()

    def _ask_save(self, title: str, suggested: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self.app, title, suggested, "PNG (*.png)")
        if path and not path.lower().endswith(".png"):
            path += ".png"
        return path

    def export_scaled(self, factor: int) -> None:
        path = self._ask_save(f"Exporter ×{factor}", f"pixel_x{factor}.png")
        if not path:
            return
        image = self.app.create_composite_image()
        scaled = image.scaled(image.width() * factor, image.height() * factor,
                              Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        if not scaled.save(path, "PNG"):
            QMessageBox.warning(self.app, "Pixel Art", "Export impossible.")
            return
        self.app.statusBar().showMessage(f"Exporté ×{factor} : {path}", 5000)

    def export_indexed(self) -> None:
        palette = self.current_palette()
        if not palette or len(palette) > 255:
            QMessageBox.warning(self.app, "Pixel Art", "Il faut une palette de 1 à 255 couleurs.")
            return
        path = self._ask_save("Exporter en PNG indexé", "pixel_indexe.png")
        if not path:
            return
        factor = int(self.panel.scale.currentData() or 1)
        image = self.app.create_composite_image().convertToFormat(QImage.Format.Format_ARGB32)
        mapper = core.PaletteMapper(palette)
        index_of = {color: i + 1 for i, color in enumerate(palette)}
        indexed = QImage(image.width(), image.height(), QImage.Format.Format_Indexed8)
        indexed.setColorTable([qRgba(0, 0, 0, 0)] + [qRgba(r, g, b, 255) for r, g, b in palette])
        for y in range(image.height()):
            for x in range(image.width()):
                value = image.pixel(x, y)
                if (value >> 24) < 128:
                    indexed.setPixel(x, y, 0)
                else:
                    indexed.setPixel(x, y, index_of[mapper(((value >> 16) & 255, (value >> 8) & 255, value & 255))])
        if factor > 1:
            indexed = indexed.scaled(indexed.width() * factor, indexed.height() * factor,
                                     Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        if not indexed.save(path, "PNG"):
            QMessageBox.warning(self.app, "Pixel Art", "Export impossible.")
            return
        self.app.statusBar().showMessage(f"PNG indexé ({len(palette)} couleurs) : {path}", 5000)

    def export_tiles(self) -> None:
        tw, th = int(self.options["tile_w"]), int(self.options["tile_h"])
        if tw <= 0 or th <= 0:
            QMessageBox.information(self.app, "Exporter les tuiles",
                                    "Règle d'abord la taille des tuiles (Grille et zoom ▸ Tuiles).")
            return
        folder = QFileDialog.getExistingDirectory(self.app, "Dossier des tuiles")
        if not folder:
            return
        image = self.app.create_composite_image()
        count = 0
        for index, (x, y, w, h) in enumerate(core.tiles(image.width(), image.height(), tw, th)):
            tile = image.copy(x, y, w, h)
            if tile.save(str(Path(folder) / f"tuile_{index:03d}.png"), "PNG"):
                count += 1
        self.app.statusBar().showMessage(f"{count} tuile(s) exportée(s) dans {folder}", 6000)


def install(app) -> PixelArtController | None:
    try:
        return PixelArtController(app)
    except Exception as exc:  # noqa: BLE001 — le module ne doit jamais empêcher Nebula de démarrer
        print(f"[Nebula] Module Pixel Art indisponible : {exc}", file=sys.stderr)
        return None
