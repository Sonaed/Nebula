from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtGui import QOpenGLContext
import ctypes
import base64
import math
import time
from pathlib import Path

from PySide6.QtWidgets import QInputDialog
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from PySide6.QtGui import (
    QPainter,
    QImage,
    QTabletEvent,
    QMouseEvent,
    QWheelEvent,
    QResizeEvent,
    QColor,
    QPen,
    QFont,
    QFontMetricsF,
    QPainterPath,
    QKeyEvent,
    QEnterEvent,
)

from CANVAS.gpu_renderer import CanvasGPURenderer
from CANVAS.gpu_instanced_stroke import GPUInstancedStrokeRenderer

from PySide6.QtCore import (
    Qt,
    Signal,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QEvent,
    QSettings,
    QTimer,
)

from TOOLS.tool_manager import ToolManager
from TOOLS.cpp_brush_presets import CanvasBrushPresetController
from TOOLS.brush_settings_state import BrushSettingsState, DEFAULT_BRUSH_SETTINGS
from TOOLS.brush_preset_manager import BrushPresetManager
from TOOLS.transform_tool import TransformSpec
from TOOLS.crop_tool import CropTool
from DOCUMENTS.document import Document
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.layer import Layer
from DOCUMENTS.selection import SelectionOperation
from DOCUMENTS.blend_modes import has_non_normal, composite_layers
from UI.qt_blend_modes import composition_mode
from CANVAS.tile_history import TileHistory
from CORE.projection_worker import ProjectionWorker, ProjectionLayer
from CORE.native_bridge import (clone_image_native, draw_text_native,
                                apply_alpha_mask_native, fill_image_native,
                                filter_brush_segment,
                                load_creative_core, restore_image_alpha_rect,
                                restore_image_alpha_tile)
from DOCUMENTS.tile_store import TileStore, TILE_SIZE


class Canvas(QOpenGLWidget):

    color_sampled = Signal(QColor)
    brush_settings_changed = Signal(dict)
    tool_changed = Signal(str)
    canvas_only_changed = Signal(bool)
    view_flip_changed = Signal(bool, bool)
    symmetry_changed = Signal(bool, bool)
    history_restored = Signal()

    def __init__(
        self
    ) -> None:

        super().__init__()

        self.document: Document = Document(
            800,
            600
        )
        self.projection_store = TileStore(self.document.width, self.document.height, TILE_SIZE)
        self._projection_tile_signatures: dict[tuple[int, int], tuple] = {}
        self._projection_tile_generation: dict[tuple[int, int], int] = {}
        self._projection_ready_tiles: set[tuple[int, int]] = set()

        background = (
            self.document.get_active_layer()
        )

        if background is not None:

            background.name = "Arrière-plan"

            if not fill_image_native(background.image, QColor(255, 255, 255, 255)):
                raise RuntimeError("CreativeCore a refusé le remplissage de l’arrière-plan")

        self.tools: ToolManager = ToolManager(self._tool_changed)

        # -----------------------------------------------------
        # BRUSH C++ / CREATIVE CORE
        # -----------------------------------------------------

        self.cpp_brush_enabled: bool = False
        self.cpp_brush = None
        self.cpp_brush_library = None
        self._brush_bitmap_tip_png: bytes | None = None
        self._cpp_bitmap_tip_png: bytes | None = None
        self.cpp_brush_buffer = None
        self._connected_gl_context = None
        self._gl_cleanup_in_progress = False

        # Source de vérité unique : CreativeCore possède le rendu et les
        # dynamiques; Python ne conserve que l'état exposé aux contrôles Qt.
        self.brush_settings = BrushSettingsState(
            self._apply_brush_settings
        )
        self._brush_settings_tool = "brush"
        default_spacing = QSettings("CreativeSystem", "CreativeSystem").value("brush/spacing", 10, int)
        self.brush_settings.update({"spacing": max(1, min(500, default_spacing)) / 100.0}, notify=False)
        preferences = QSettings("CreativeSystem", "CreativeSystem")
        self.use_gpu = preferences.value("performance/use_gpu", True, bool)
        self.zoom_behavior = preferences.value("canvas/zoom_behavior", "At cursor", str)
        self.canvas_background = preferences.value("canvas/background", "Checkerboard", str)
        self.show_brush_cursor_preview = preferences.value("brush/show_cursor_preview", True, bool)
        self.tablet_pressure_enabled = preferences.value("tablet/pressure", True, bool)
        self.ignore_synthetic_mouse_after_tablet = preferences.value(
            "tablet/ignore_mouse_after_tablet", True, bool
        )
        self._last_tablet_event_time = 0.0
        self.right_click_color_picker = preferences.value(
            "input/right_click_color_picker", True, bool
        )

        self._init_cpp_brush()

        self.projection_worker = ProjectionWorker(
            self, self.cpp_brush_library if self.cpp_brush_enabled else None
        )
        self.projection_worker.projected.connect(self._on_projected_tile)
        self.projection_worker.failed.connect(self._on_projection_failed)

        self.cpp_preset_controller = None
        self.cpp_preset_shortcuts = []
        self.brush_preset_manager = BrushPresetManager()

        if self.cpp_brush_enabled:
            try:
                self.cpp_preset_controller = CanvasBrushPresetController(
                    self.cpp_brush_library,
                    self.cpp_brush,
                )

                print(
                    "✓ Presets C++ connectés au Canvas"
                )

            except Exception as exc:
                print(
                    f"⚠ Impossible de connecter les presets C++ : {exc}"
                )

        self._install_cpp_brush_preset_shortcuts()

        self._apply_brush_settings(
            self.brush_settings.snapshot()
        )

        self.drawing: bool = False

        self.gradient_drawing: bool = False
        self.gradient_start: QPoint = QPoint()
        self.gradient_original: QImage | None = None

        self.shape_drawing: bool = False
        self.shape_start: QPoint = QPoint()
        self.shape_original: QImage | None = None

        self.selection_drawing: bool = False
        self.selection_points: list[QPoint] = []
        self.selection_operation = SelectionOperation.REPLACE

        self.last_point: QPoint = QPoint()

        self.zoom: float = 1.0
        self.view_rotation: float = 0.0
        self.view_flip_x: bool = False
        self.view_flip_y: bool = False
        self.canvas_only: bool = False
        self.symmetry_horizontal: bool = False
        self.symmetry_vertical: bool = False
        self.assistant_mode: str = "none"
        self.assistant_vanishing_point = QPointF(0.5, 0.5)
        self._assistant_angle: float | None = None
        self.view_dragging: bool = False
        self.view_drag_angle: float = 0.0
        self.view_drag_rotation: float = 0.0

        self.min_zoom: float = 0.05

        self.max_zoom: float = 8.0

        self.offset: QPointF = QPointF(
            0,
            0
        )

        self.panning: bool = False

        self.pan_start: QPointF = QPointF()

        self.offset_start: QPointF = QPointF()

        self.space_pressed: bool = False

        self.cursor_position: QPointF = QPointF(
            -1,
            -1
        )

        self.cursor_visible: bool = False

        # -----------------------------------------------------
        # OUTIL TRANSFORMER
        # -----------------------------------------------------

        self.transforming: bool = False

        self.transform_handle: str = ""

        self.transform_start: QPointF = QPointF()

        self.transform_scale_x: float = 1.0

        self.transform_scale_y: float = 1.0

        self.transform_original_scale_x: float = 1.0

        self.transform_original_scale_y: float = 1.0

        self.transform_move_delta: QPointF = QPointF(
            0,
            0
        )
        self.transform_rotation: float = 0.0

        self.crop_drawing: bool = False
        self.crop_start: QPoint = QPoint()
        self.crop_current: QPoint = QPoint()

        self.selection_moving: bool = False
        self.selection_move_start: QPoint = QPoint()
        self.selection_move_original: QImage | None = None
        self.selection_move_original_mask: QImage | None = None
        self.selected_reference_id: str | None = None
        self.reference_drag_id: str | None = None
        self.reference_drag_anchor = QPointF()
        self.selected_text_id: str | None = None
        self.text_drag_id: str | None = None
        self.text_drag_anchor = QPointF()
        self.bezier_stage = 0
        self.bezier_start = QPointF()
        self.bezier_control1 = QPointF()
        self.bezier_end = QPointF()
        self.bezier_control2 = QPointF()
        self.bezier_dragging = False

        self.tile_history = TileHistory(
            tile_size=TILE_SIZE,
            max_steps=max(1, min(1000, preferences.value("performance/undo_steps", 30, int))),
        )
        self.history = self.tile_history.steps
        self.history_index = 0
        self.max_history = self.tile_history.max_steps
        self._stroke_image_format = None
        self._pending_color_sample: QPoint | None = None
        self._deferred_undo_count = 0

        self.setAttribute(
            Qt.WidgetAttribute.WA_OpaquePaintEvent
        )

        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)

        # -----------------------------------------------------
        # VIEWPORT GPU
        # -----------------------------------------------------

        self.gpu_renderer = CanvasGPURenderer()
        self.gpu_renderer.on_tile_ready = self._on_scratch_tile_ready
        self.gpu_instanced_stroke = GPUInstancedStrokeRenderer(self)

        self.gpu_ready = False

        self.setMouseTracking(
            True
        )

        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus
        )

        self._initial_view_fitted = False

        # Snapshot de l'alpha au début d'un trait lorsque l'alpha lock est
        # actif. Il est réutilisé par les chemins Python et C++.
        self._alpha_lock_snapshot: QImage | bool | None = None
        self.clone_source: QImage | None = None
        self.clone_source_point: QPoint | None = None
        self.clone_offset: QPoint | None = None
        self._last_tablet_tilt = (0.0, 0.0)

    # =========================================================
    # CREATIVE CORE C++
    # =========================================================

    def _init_cpp_brush(self) -> None:
        """Connecte le moteur natif via le chargeur ABI partagé."""
        lib = load_creative_core()
        if lib is None:
            raise RuntimeError("CreativeCore est requis pour initialiser le BrushEngine")

        try:
            brush = lib.cs_brush_create()

            if not brush:
                raise RuntimeError("CreativeCore n’a pas pu créer le BrushEngine")

            self.cpp_brush_library = lib
            self.cpp_brush = brush
            self.cpp_brush_enabled = True
            self.tools.set_cpp_library(lib)

            print(
                "✓ CreativeCore C++ brush connecté au Canvas"
            )

        except Exception as exc:
            self.cpp_brush_enabled = False
            self.cpp_brush = None
            self.cpp_brush_library = None

            raise RuntimeError("CreativeCore n’a pas pu initialiser le BrushEngine") from exc

    def _sync_cpp_brush(self) -> None:
        """Réapplique l'état canonique, jamais l'ancien état Python."""
        self._apply_brush_settings(
            self.brush_settings.snapshot()
        )

    def _apply_brush_settings(self, settings) -> None:
        """Miroir atomique des préférences vers le backend C++ et l’interface."""
        settings = dict(settings)
        preferences = QSettings("CreativeSystem", "CreativeSystem")
        pressure_enabled = preferences.value("tablet/pressure", True, bool)
        settings["pressureSize"] = bool(settings.get("pressureSize", True)) and pressure_enabled and preferences.value("tablet/pressure_size", True, bool)
        settings["pressureOpacity"] = bool(settings.get("pressureOpacity", False)) and pressure_enabled and preferences.value("tablet/pressure_opacity", True, bool)
        settings["pressureFlow"] = bool(settings.get("pressureFlow", False)) and pressure_enabled
        brush = self.tools.brush
        brush.antialiasing = preferences.value("canvas/antialias", True, bool)
        brush.sync_engine()
        python_map = {
            "size": "size",
            "opacity": "opacity",
            "flow": "flow",
            "hardness": "hardness",
            "spacing": "spacing",
            "pressureSize": "pressure_size",
            "pressureOpacity": "pressure_opacity",
            "pressureFlow": "pressure_flow",
            "minimumSize": "minimum_size",
        }
        for key, attribute in python_map.items():
            if key in settings:
                setattr(brush, attribute, settings[key])

        # Advanced dynamics stay in the same canonical state.  The existing
        # Python engine already evaluates these factors; C++ continues to be
        # the primary backend for the core parameters and can consume the
        # additional input channels incrementally.
        dynamics_map = {
            "velocitySize": "speed_size",
            "velocityOpacity": "speed_opacity",
            "velocityFlow": "speed_flow",
            "tiltSize": "tilt_size",
            "tiltOpacity": "tilt_opacity",
            "randomSize": "random_size",
            "randomOpacity": "random_opacity",
        }
        for key, attribute in dynamics_map.items():
            if key in settings:
                setattr(brush.dynamics, attribute, float(settings[key]))
        if hasattr(brush, "speed_sensitivity"):
            brush.speed_sensitivity = float(settings.get("velocitySpacing", 0.0))

        color = settings.get("color")
        if color is not None and len(color) >= 4:
            brush.color = QColor(*[int(value) for value in color[:4]])

        eraser = self.tools.current_tool == "eraser"
        brush.eraser = eraser

        if self.cpp_brush_enabled:
            self.cpp_brush_library.cs_brush_set_smoothing(
                self.cpp_brush, float(getattr(brush, "smoothing", 0.0))
            )
        if self.cpp_brush_enabled and self.cpp_preset_controller is not None:
            cpp_settings = dict(settings)
            cpp_settings["eraser"] = eraser
            cpp_settings["smudgeTool"] = False
            if self.tools.current_tool == "smudge":
                cpp_settings.update({
                    "eraser": False,
                    "smudgeTool": True,
                    "wetMix": True,
                    "sampleCanvas": True,
                    "wetness": max(0.5, float(settings["wetness"])),
                    "pickup": max(0.75, float(settings["pickup"])),
                    "smudge": max(0.5, float(settings["smudge"])),
                    "paintMix": max(0.01, float(settings["paintMix"])),
                })
            self.cpp_preset_controller.applier.apply(cpp_settings)
            tip_png = self._brush_bitmap_tip_png
            if tip_png != self._cpp_bitmap_tip_png:
                if tip_png:
                    encoded = (ctypes.c_uint8 * len(tip_png)).from_buffer_copy(tip_png)
                    loaded = self.cpp_brush_library.cs_brush_set_bitmap_tip_png(
                        self.cpp_brush, encoded, len(tip_png)
                    )
                    if loaded:
                        self._cpp_bitmap_tip_png = tip_png
                else:
                    self.cpp_brush_library.cs_brush_clear_bitmap_tip(self.cpp_brush)
                    self._cpp_bitmap_tip_png = None

        self.brush_settings_changed.emit(dict(settings))
        self.update()

    def set_brush_setting(self, key, value) -> None:
        self.brush_settings.set(key, value)

    def load_brush_texture(self, path: str) -> bool:
        """Ask CreativeCore to decode and own a brush texture image."""
        if not self.cpp_brush_enabled or not path:
            return False
        encoded_path = path.encode("utf-8")
        if not self.cpp_brush_library.cs_brush_set_texture_path(
            self.cpp_brush, encoded_path
        ):
            return False
        self.set_brush_setting("textureStrength", 1.0)
        return True

    def clear_brush_texture(self) -> None:
        if self.cpp_brush_enabled:
            self.cpp_brush_library.cs_brush_clear_texture(self.cpp_brush)

    def load_brush_bitmap_tip(self, path: str) -> bool:
        """Load a full-color stamp tip directly into CreativeCore."""
        if not self.cpp_brush_enabled or not path:
            return False
        try:
            if Path(path).stat().st_size > 32 * 1024 * 1024:
                return False
            encoded_png = Path(path).read_bytes()
        except OSError:
            return False
        if not encoded_png.startswith(b"\x89PNG\r\n\x1a\n") or len(encoded_png) > 32 * 1024 * 1024:
            return False
        buffer = (ctypes.c_uint8 * len(encoded_png)).from_buffer_copy(encoded_png)
        if not self.cpp_brush_library.cs_brush_set_bitmap_tip_png(
            self.cpp_brush, buffer, len(encoded_png)
        ):
            return False
        self._brush_bitmap_tip_png = encoded_png
        self._cpp_bitmap_tip_png = encoded_png
        return True

    def clear_brush_bitmap_tip(self) -> None:
        if self.cpp_brush_enabled:
            self.cpp_brush_library.cs_brush_clear_bitmap_tip(self.cpp_brush)
        self._brush_bitmap_tip_png = None
        self._cpp_bitmap_tip_png = None

    def set_brush_settings(self, values) -> None:
        self.brush_settings.update(values)

    def _tool_changed(self, _name: str) -> None:
        preferences = QSettings("CreativeSystem", "CreativeSystem")
        if preferences.value("brush/remember_per_tool", True, bool):
            preferences.setValue(
                f"brush/tool_settings/{self._brush_settings_tool}",
                self.brush_settings.snapshot(),
            )
            saved = preferences.value(f"brush/tool_settings/{_name}", None)
            self.brush_settings.update(
                saved if isinstance(saved, dict) else DEFAULT_BRUSH_SETTINGS,
                notify=False,
            )
        self._brush_settings_tool = _name
        if _name != "bezier":
            self.bezier_stage = 0
            self.bezier_dragging = False
        if hasattr(self, "brush_settings"):
            self._apply_brush_settings(self.brush_settings.snapshot())
        self.tool_changed.emit(_name)

    def sample_composite_color(self, position: QPoint) -> QColor | None:
        if not (0 <= position.x() < self.document.width and
                0 <= position.y() < self.document.height):
            return None

        # A picker only needs one pixel. Never force a swapped tile back onto
        # the UI thread just to read it; queue the sample and resume once the
        # requested tile data has arrived.
        for layer in self.document.layers:
            layer.commit_image_cache()
        key = self.document.layers[0].tile_store.tile_key(position.x(), position.y()) if self.document.layers else (0, 0)
        pending_stores = [
            layer.tile_store for layer in self.document.layers
            if layer.visible and layer.tile_store.has_tile(*key)
            and not layer.tile_store.tile_is_resident(*key)
        ]
        if pending_stores:
            self._pending_color_sample = QPoint(position)
            for store in pending_stores:
                store.request_tile_async(*key, self._on_scratch_tile_ready)
            return None
        self._pending_color_sample = None

        if (has_non_normal(self.document) or self.document.layer_groups
                or self.view_rotation or self.view_flip_x or self.view_flip_y):
            store = self.projection_store
            signature = self._projection_signature_for(*key)
            if (key in self._projection_ready_tiles
                    and self._projection_tile_signatures.get(key) == signature):
                composite_tile = store.tile(*key)
            else:
                rect = store.tile_rect(*key)
                tile_layers, missing = self._tile_projection_layers(key[0], key[1], rect)
                if missing:
                    self._pending_color_sample = QPoint(position)
                    return None
                composite_tile = composite_layers(rect.width(), rect.height(), tile_layers)
            rect = store.tile_rect(*key)
            for item in self.document.text_objects:
                if not draw_text_native(
                        composite_tile, item.text, item.font,
                        item.position.x() - rect.x(), item.position.y() - rect.y(),
                        item.color):
                    raise RuntimeError("CreativeCore is required to sample document text")
            color = composite_tile.pixelColor(position.x() - rect.x(), position.y() - rect.y())
            self.set_brush_setting("color", [color.red(), color.green(), color.blue(), color.alpha()])
            self.color_sampled.emit(color)
            return color

        # Composition d'un seul pixel : évite d'allouer une image complète
        # lors de chaque prélèvement sur un grand document.
        out_r = out_g = out_b = out_a = 0.0
        for layer in self.document.layers:
            if not layer.visible:
                continue
            source_tile = layer.tile_store.tile(*key)
            tile_rect = layer.tile_store.tile_rect(*key)
            source = source_tile.pixelColor(position.x() - tile_rect.x(),
                                            position.y() - tile_rect.y())
            source_a = source.alphaF() * float(layer.opacity)
            if source_a <= 0.0:
                continue
            remaining = 1.0 - source_a
            out_r = source.redF() * source_a + out_r * remaining
            out_g = source.greenF() * source_a + out_g * remaining
            out_b = source.blueF() * source_a + out_b * remaining
            out_a = source_a + out_a * remaining

        if out_a <= 0.0:
            return None
        color = QColor.fromRgbF(
            out_r / out_a,
            out_g / out_a,
            out_b / out_a,
            1.0,
        )
        self.set_brush_setting(
            "color",
            [color.red(), color.green(), color.blue(), color.alpha()],
        )
        self.color_sampled.emit(color)
        return color

    def _prepare_cpp_image(
        self,
        image: QImage
    ) -> QImage:
        """
        Le bridge C++ travaille en RGBA8888.
        On convertit uniquement si nécessaire.
        """

        if (
            image.format()
            != QImage.Format.Format_RGBA8888
        ):
            return image.convertToFormat(
                QImage.Format.Format_RGBA8888
            )

        return image

    @staticmethod
    def _clone_raster_native(image: QImage) -> QImage:
        clone = clone_image_native(image)
        if clone is None:
            raise RuntimeError("CreativeCore is required to clone raster snapshots")
        return clone

    def _cpp_begin_stroke(
        self,
        image: QImage,
        position: QPoint,
        pressure: float
    ) -> QImage | None:

        if not self.cpp_brush_enabled:
            return None

        image = self._prepare_cpp_image(
            image
        )

        self._sync_cpp_brush()
        self._cpp_smoothed_point = QPointF(position)

        lib = self.cpp_brush_library
        handle = self.cpp_brush

        lib.cs_brush_begin_stroke(
            handle,
            ctypes.c_float(
                float(position.x())
            ),
            ctypes.c_float(
                float(position.y())
            ),
            ctypes.c_float(
                float(pressure)
            )
        )
        self._cpp_smooth_native_point(position)

        # Le begin initialise l'état du moteur mais ne pose pas de dab.
        return self._cpp_draw_segment(
            image,
            position,
            position,
            pressure,
            pressure,
        )

    def _cpp_begin_clone_stroke(
        self, image: QImage, position: QPoint, pressure: float,
    ) -> QImage | None:
        if not self.cpp_brush_enabled or self.clone_source is None or self.clone_offset is None:
            return None
        image = self._prepare_cpp_image(image)
        self._sync_cpp_brush()
        self._cpp_smoothed_point = QPointF(position)
        self.cpp_brush_library.cs_brush_begin_stroke(
            self.cpp_brush, float(position.x()), float(position.y()), float(pressure)
        )
        self._cpp_smooth_native_point(position)
        return self._cpp_draw_segment(
            image, position, position, pressure, pressure,
            clone_source=self.clone_source, clone_offset=self.clone_offset,
        )

    def _set_clone_source(self, position: QPoint) -> bool:
        if not (0 <= position.x() < self.document.width and
                0 <= position.y() < self.document.height):
            return False
        self.clone_source_point = QPoint(position)
        self.clone_source = None
        self.clone_offset = None
        self.update()
        return True

    def _begin_clone_sampling(self, layer, target: QPoint) -> bool:
        if self.clone_source_point is None:
            return False
        self.clone_source = layer.image.convertToFormat(QImage.Format.Format_RGBA8888)
        self.clone_offset = self.clone_source_point - target
        return True

    def _apply_filter_segment(self, image: QImage, start: QPoint, end: QPoint,
                              start_pressure: float, end_pressure: float,
                              sharpen: bool) -> QImage:
        settings = self.brush_settings.snapshot()
        image = image if image.format() == QImage.Format.Format_RGBA8888 else image.convertToFormat(QImage.Format.Format_RGBA8888)
        dirty = self._brush_dirty_rect(start, end)
        layer = self.get_active_layer()
        if layer is not None:
            self.tile_history.capture_before(layer, dirty)
        segments = [(start, end)]
        cx, cy = self.document.width - 1, self.document.height - 1
        if self.symmetry_horizontal:
            segments.append((QPoint(cx - start.x(), start.y()), QPoint(cx - end.x(), end.y())))
        if self.symmetry_vertical:
            segments.append((QPoint(start.x(), cy - start.y()), QPoint(end.x(), cy - end.y())))
        if self.symmetry_horizontal and self.symmetry_vertical:
            segments.append((QPoint(cx - start.x(), cy - start.y()), QPoint(cx - end.x(), cy - end.y())))
        native_filter = True
        for a, b in segments:
            if filter_brush_segment(
                image, a.x(), a.y(), start_pressure, b.x(), b.y(), end_pressure,
                settings.get("size", 10.0), settings.get("spacing", 0.15),
                float(settings.get("opacity", 1.0)) * float(settings.get("flow", 1.0)),
                sharpen,
            ) is None:
                native_filter = False
                break
        if not native_filter:
            # La référence Python reste disponible pour les benchmarks et la
            # comparaison de parité, mais elle ne doit plus être appelée par
            # l'édition réelle : les outils de filtre appartiennent au moteur
            # CreativeCore comme les autres outils de peinture.
            return image
        image = self._restore_locked_alpha(image, dirty) or image
        if layer is not None:
            layer.image = image
            self.tile_history.mark_dirty(layer, dirty)
        if getattr(self, "gpu_ready", False) and layer is not None:
            self.gpu_renderer.mark_layer_dirty(layer, dirty)
        self.update()
        return image

    def _cpp_draw_segment(
        self,
        image: QImage,
        start: QPoint,
        end: QPoint,
        start_pressure: float,
        end_pressure: float,
        start_tilt: tuple[float, float] = (0.0, 0.0),
        end_tilt: tuple[float, float] = (0.0, 0.0),
        clone_source: QImage | None = None,
        clone_offset: QPoint | None = None,
        stabilize: bool = False,
    ) -> QImage | None:

        if not self.cpp_brush_enabled:
            return None

        if stabilize:
            previous = getattr(self, "_cpp_smoothed_point", QPointF(start))
            out_x = ctypes.c_float()
            out_y = ctypes.c_float()
            if self.cpp_brush_library.cs_brush_smooth_point(
                self.cpp_brush, float(end.x()), float(end.y()),
                ctypes.byref(out_x), ctypes.byref(out_y),
            ):
                start = QPoint(round(previous.x()), round(previous.y()))
                end = QPoint(round(out_x.value), round(out_y.value))
                self._cpp_smoothed_point = QPointF(out_x.value, out_y.value)

        layer = self.get_active_layer()
        if layer is not None:
            self.tile_history.capture_before(layer, self._brush_dirty_rect(start, end))

        image = self._prepare_cpp_image(image)
        cx = self.document.width - 1
        cy = self.document.height - 1
        segments = [(start, end, start_tilt, end_tilt)]
        if self.symmetry_horizontal:
            segments.append((
                QPoint(cx - start.x(), start.y()),
                QPoint(cx - end.x(), end.y()),
                (-start_tilt[0], start_tilt[1]),
                (-end_tilt[0], end_tilt[1]),
            ))
        if self.symmetry_vertical:
            segments.append((
                QPoint(start.x(), cy - start.y()),
                QPoint(end.x(), cy - end.y()),
                (start_tilt[0], -start_tilt[1]),
                (end_tilt[0], -end_tilt[1]),
            ))
        if self.symmetry_horizontal and self.symmetry_vertical:
            segments.append((
                QPoint(cx - start.x(), cy - start.y()),
                QPoint(cx - end.x(), cy - end.y()),
                (-start_tilt[0], -start_tilt[1]),
                (-end_tilt[0], -end_tilt[1]),
            ))

        for segment_start, segment_end, tilt_start, tilt_end in segments:
            offset = QPoint(clone_offset) if clone_offset is not None else QPoint()
            if segment_start.x() != start.x():
                offset.setX(-offset.x())
            if segment_start.y() != start.y():
                offset.setY(-offset.y())
            image = self._cpp_draw_segment_once(
                image, segment_start, segment_end,
                start_pressure, end_pressure, tilt_start, tilt_end,
                clone_source, offset,
            )
            if image is None:
                return None
        return image

    def _cpp_smooth_native_point(self, position: QPoint) -> QPointF:
        out_x = ctypes.c_float()
        out_y = ctypes.c_float()
        if self.cpp_brush_library.cs_brush_smooth_point(
            self.cpp_brush, float(position.x()), float(position.y()),
            ctypes.byref(out_x), ctypes.byref(out_y),
        ):
            point = QPointF(out_x.value, out_y.value)
            self._cpp_smoothed_point = point
            return point
        point = QPointF(position)
        self._cpp_smoothed_point = point
        return point

    def _cpp_draw_segment_once(
        self,
        image: QImage,
        start: QPoint,
        end: QPoint,
        start_pressure: float,
        end_pressure: float,
        start_tilt: tuple[float, float],
        end_tilt: tuple[float, float],
        clone_source: QImage | None = None,
        clone_offset: QPoint | None = None,
    ) -> QImage | None:

        if not self.cpp_brush_enabled:
            return None

        image = self._prepare_cpp_image(
            image
        )

        bits = image.bits()

        try:
            buffer_type = (
                ctypes.c_uint8 *
                (
                    image.bytesPerLine() *
                    image.height()
                )
            )

            self.cpp_brush_buffer = (
                buffer_type.from_buffer(
                    bits
                )
            )

            if clone_source is not None and clone_offset is not None:
                source = self._prepare_cpp_image(clone_source)
                source_buffer_type = ctypes.c_uint8 * (source.bytesPerLine() * source.height())
                source_buffer = source_buffer_type.from_buffer(source.bits())
                self.cpp_brush_library.cs_brush_draw_segment_clone(
                    self.cpp_brush, self.cpp_brush_buffer, source_buffer,
                    image.width(), image.height(), image.bytesPerLine(), source.bytesPerLine(),
                    clone_offset.x(), clone_offset.y(),
                    float(start.x()), float(start.y()), float(start_pressure),
                    float(start_tilt[0]), float(start_tilt[1]),
                    float(end.x()), float(end.y()), float(end_pressure),
                    float(end_tilt[0]), float(end_tilt[1]),
                )
            else:
                draw_function = getattr(self.cpp_brush_library, "cs_brush_draw_segment_tilt", None)
                if draw_function is not None and (start_tilt != (0.0, 0.0) or end_tilt != (0.0, 0.0)):
                    draw_function(
                    self.cpp_brush, self.cpp_brush_buffer, image.width(), image.height(), image.bytesPerLine(),
                    float(start.x()), float(start.y()), float(start_pressure), float(start_tilt[0]), float(start_tilt[1]),
                    float(end.x()), float(end.y()), float(end_pressure), float(end_tilt[0]), float(end_tilt[1])
                )
                else:
                    self.cpp_brush_library.cs_brush_draw_segment(
                self.cpp_brush,
                self.cpp_brush_buffer,
                image.width(),
                image.height(),
                image.bytesPerLine(),
                ctypes.c_float(
                    float(start.x())
                ),
                ctypes.c_float(
                    float(start.y())
                ),
                ctypes.c_float(
                    float(start_pressure)
                ),
                ctypes.c_float(
                    float(end.x())
                ),
                ctypes.c_float(
                    float(end.y())
                ),
                ctypes.c_float(
                    float(end_pressure)
                )
            )

            return image

        except Exception as exc:
            print(f"CreativeCore : erreur buffer QImage, dab annulé ({exc})")

            return None

        finally:
            self.cpp_brush_buffer = None

    def _cpp_end_stroke(self) -> None:

        if not self.cpp_brush_enabled:
            return

        self.cpp_brush_library.cs_brush_end_stroke(
            self.cpp_brush
        )
        self._cpp_smoothed_point = None

    def _cpp_active(
        self
    ) -> bool:

        return (
            self.cpp_brush_enabled
            and self.cpp_brush is not None
        )

    def _try_begin_instanced_stroke(self, layer, position: QPoint,
                                    pressure: float, tool: str) -> bool:
        if (float(getattr(self.tools.brush, "smoothing", 0.0)) > 0.0
                or not self.gpu_ready or not self.use_gpu or self.transforming
                or self.document.layer_groups or has_non_normal(self.document)
                or not self.document.selection.is_empty()
                or getattr(layer, "lock_alpha", False)):
            return False
        settings = self.brush_settings.snapshot()
        if not GPUInstancedStrokeRenderer.supports(
            settings, tool, self.document.width, self.document.height,
            self.symmetry_horizontal, self.symmetry_vertical,
        ):
            return False
        if not self.gpu_instanced_stroke.begin(
            layer, layer.image, settings, position, pressure,
            eraser=(tool == "eraser" or bool(settings.get("eraser", False))),
        ):
            return False
        self.tile_history.capture_before(layer, self._brush_dirty_rect(position, position))
        return True

    def _queue_instanced_stroke_segment(self, start: QPoint, end: QPoint,
                                        start_pressure: float, end_pressure: float) -> bool:
        renderer = self.gpu_instanced_stroke
        if not renderer.active:
            return False
        dirty = self._brush_dirty_rect(start, end)
        layer = renderer.layer
        if layer is not None:
            self.tile_history.capture_before(layer, dirty)
        renderer.queue_segment(start, end, start_pressure, end_pressure, dirty)
        return True

    # =========================================================
    # DOCUMENT
    # =========================================================

    def _install_cpp_brush_preset_shortcuts(self):
        # Ouvre le sélecteur de preset.
        shortcut = QShortcut(
            QKeySequence("Ctrl+Alt+P"),
            self,
        )

        shortcut.activated.connect(
            self.choose_cpp_brush_preset
        )

        self.cpp_preset_shortcuts.append(
            shortcut
        )

        # Raccourcis directs pour les 4 presets principaux.
        preset_keys = [
            ("Ctrl+Alt+1", "Pencil"),
            ("Ctrl+Alt+2", "Ink"),
            ("Ctrl+Alt+3", "Paint"),
            ("Ctrl+Alt+4", "Charcoal"),
        ]

        for sequence, preset_name in preset_keys:
            preset_shortcut = QShortcut(
                QKeySequence(sequence),
                self,
            )

            preset_shortcut.activated.connect(
                lambda name=preset_name:
                self.load_cpp_brush_preset(name)
            )

            self.cpp_preset_shortcuts.append(
                preset_shortcut
            )

    def load_cpp_brush_preset(self, name):
        try:
            settings = self.brush_preset_manager.load(name)

            if settings is not None:
                encoded_tip = settings.get("_csbr_bitmap_tip_png")
                try:
                    tip = base64.b64decode(encoded_tip, validate=True) if encoded_tip else None
                except (ValueError, TypeError):
                    tip = None
                self._brush_bitmap_tip_png = (
                    tip if tip and len(tip) <= 32 * 1024 * 1024 else None
                )
                self.brush_settings.update(settings)
                print(
                    f"✓ Brush preset chargé dans le Canvas : {name}"
                )

                # Conserve le preset courant.
                self._current_cpp_brush_preset_name = name

                # Le Canvas utilise désormais le nouveau
                # réglage C++ pour les prochains strokes.
                self.update()

                return True

            print(
                f"⚠ Preset introuvable : {name}"
            )

            return False

        except Exception as exc:
            print(
                f"⚠ Erreur chargement preset {name} : {exc}"
            )

            return False

    def get_cpp_brush_settings(self):
        """
        Retourne les paramètres connus du dernier preset chargé.

        Cette méthode permet au Brush Presets Dock
        de sauvegarder l'état courant.
        """

        settings = self.brush_settings.snapshot()
        if self._brush_bitmap_tip_png:
            settings["_csbr_bitmap_tip_png"] = base64.b64encode(
                self._brush_bitmap_tip_png
            ).decode("ascii")
        return settings

    def get_cpp_brush_preset_name(self):
        return getattr(
            self,
            "_current_cpp_brush_preset_name",
            None,
        )

    def choose_cpp_brush_preset(self):
        presets = self.brush_preset_manager.list_presets()

        if not presets:
            return

        name, accepted = QInputDialog.getItem(
            self,
            "CreativeSystem — Brush Preset",
            "Choisir un preset :",
            presets,
            0,
            False,
        )

        if not accepted:
            return

        self.load_cpp_brush_preset(
            name
        )

    def set_document(
        self,
        document: Document
    ) -> None:

        self.document = document
        self.selected_reference_id = None
        self.reference_drag_id = None
        self.selected_text_id = None
        self.text_drag_id = None

        self.canvas_brush_end_stroke()


        self.drawing = False

        self.panning = False

        self.tools.move_tool.end()

        self.transforming = False

        self.transform_handle = ""

        self.last_point = QPoint()

        self._reset_history()

        self.fit_document()
        self._initial_view_fitted = True

        self.update()

    def create_new_image(
        self,
        width: int,
        height: int,
        dpi: int = 300,
        background_color: QColor | None = None
    ) -> None:

        document = Document(
            width,
            height,
            dpi,
            background_color
        )

        self.set_document(
            document
        )

    def load_image(
        self,
        file_path: str
    ) -> bool:

        image = QImage(
            file_path
        )

        if image.isNull():
            return False

        image = image.convertToFormat(
            QImage.Format.Format_ARGB32
        )

        document = Document(
            image.width(),
            image.height(),
            300,
            None
        )

        layer = document.get_active_layer()

        if layer is None:
            return False

        layer.name = "Image"

        layer.image = image

        self.set_document(
            document
        )

        return True

    # =========================================================
    # VIEW
    # =========================================================

    def canvas_brush_begin_stroke(
        self
    ) -> None:

        layer = self.get_active_layer()
        if layer is not None and getattr(layer, "lock_alpha", False):
            # Stroke history already captures original sparse tiles on first
            # touch; reuse those instead of copying the entire canvas.
            self._alpha_lock_snapshot = True
        else:
            self._alpha_lock_snapshot = None

        if hasattr(
            self.tools.brush,
            "begin_stroke"
        ):

            self.tools.brush.begin_stroke()


    def canvas_brush_end_stroke(
        self
    ) -> None:

        if hasattr(
            self.tools.brush,
            "end_stroke"
        ):

            self.tools.brush.end_stroke()

        self._alpha_lock_snapshot = None
        self.clone_source = None
        self.clone_offset = None

    def _restore_alpha_from(
        self, image: QImage | None, snapshot: QImage | None,
        rect: QRect | None = None,
    ) -> QImage | None:
        """Restore alpha from *snapshot* without changing the painted RGB."""
        if image is None or snapshot is None:
            return image
        if image.size() != snapshot.size():
            return image

        current = image if image.format() == QImage.Format.Format_RGBA8888 else image.convertToFormat(QImage.Format.Format_RGBA8888)
        source = snapshot if snapshot.format() == QImage.Format.Format_RGBA8888 else snapshot.convertToFormat(QImage.Format.Format_RGBA8888)
        area = (QRect(0, 0, current.width(), current.height()) if rect is None else
                rect.intersected(QRect(0, 0, current.width(), current.height())))
        if area.isEmpty():
            return current

        if not restore_image_alpha_rect(current, source, area.x(), area.y(),
                                        area.width(), area.height()):
            raise RuntimeError("CreativeCore is required to restore locked alpha")
        return current

    def _restore_alpha_from_history(self, image: QImage | None, layer: Layer,
                                    rect: QRect | None) -> QImage | None:
        if image is None or rect is None:
            return image
        area = rect.intersected(image.rect())
        if area.isEmpty():
            return image
        current = (image if image.format() == QImage.Format.Format_RGBA8888 else
                   image.convertToFormat(QImage.Format.Format_RGBA8888))
        for tx, ty in self.tile_history._tile_keys(
                layer.tile_store.width, layer.tile_store.height, area):
            captured, before = self.tile_history.captured_before_tile(layer.id, tx, ty)
            if not captured:
                continue
            tile_rect = layer.tile_store.tile_rect(tx, ty)
            target_rect = area.intersected(tile_rect)
            if target_rect.isEmpty():
                continue
            if before is None:
                before = QImage(tile_rect.size(), QImage.Format.Format_RGBA8888)
                if not fill_image_native(before, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore is required to clear alpha history")
            elif before.format() != QImage.Format.Format_RGBA8888:
                before = before.convertToFormat(QImage.Format.Format_RGBA8888)
            if not restore_image_alpha_tile(
                    current, before, target_rect.x(), target_rect.y(),
                    target_rect.x() - tile_rect.x(), target_rect.y() - tile_rect.y(),
                    target_rect.width(), target_rect.height()):
                raise RuntimeError("CreativeCore is required to restore locked alpha")
        return current

    def _restore_locked_alpha(self, image: QImage | None, rect: QRect | None = None) -> QImage | None:
        if self._alpha_lock_snapshot is True:
            layer = self.get_active_layer()
            if layer is None:
                return image
            return self._restore_alpha_from_history(image, layer, rect)
        return self._restore_alpha_from(image, self._alpha_lock_snapshot, rect)


    def fit_document(
        self
    ) -> None:

        if self.width() <= 1:
            return

        if self.height() <= 1:
            return

        document_width = (
            self.document.width
        )

        document_height = (
            self.document.height
        )

        if document_width <= 0:
            return

        if document_height <= 0:
            return

        margin = 40

        available_width = max(
            self.width() - margin,
            1
        )

        available_height = max(
            self.height() - margin,
            1
        )

        angle = math.radians(self.view_rotation)
        rotated_width = abs(document_width * math.cos(angle)) + abs(document_height * math.sin(angle))
        rotated_height = abs(document_width * math.sin(angle)) + abs(document_height * math.cos(angle))
        zoom_x = available_width / rotated_width
        zoom_y = available_height / rotated_height

        self.zoom = min(
            zoom_x,
            zoom_y
        )

        self.zoom = max(
            self.min_zoom,
            min(
                self.zoom,
                self.max_zoom
            )
        )

        scaled_width = (
            document_width
            * self.zoom
        )

        scaled_height = (
            document_height
            * self.zoom
        )

        self.offset = QPointF(
            (
                self.width()
                - scaled_width
            ) / 2,
            (
                self.height()
                - scaled_height
            ) / 2
        )

    def reset_view(
        self
    ) -> None:

        self.fit_document()

        self.update()

    def reset_canvas_rotation(self) -> None:
        self.view_rotation = 0.0
        self.update()

    def rotate_canvas(self, degrees: float) -> None:
        self.view_rotation = (self.view_rotation + float(degrees)) % 360.0
        self.update()

    def flip_canvas_view_horizontal(self) -> None:
        self.view_flip_x = not self.view_flip_x
        self.view_flip_changed.emit(self.view_flip_x, self.view_flip_y)
        self.update()

    def flip_canvas_view_vertical(self) -> None:
        self.view_flip_y = not self.view_flip_y
        self.view_flip_changed.emit(self.view_flip_x, self.view_flip_y)
        self.update()

    def zoom_100(self) -> None:
        self.zoom = 1.0
        self.offset = QPointF((self.width() - self.document.width) / 2.0,
                              (self.height() - self.document.height) / 2.0)
        self.update()

    def toggle_canvas_only(self) -> None:
        self.canvas_only = not self.canvas_only
        self.canvas_only_changed.emit(self.canvas_only)
        self.update()

    def toggle_horizontal_symmetry(self) -> None:
        self.symmetry_horizontal = not self.symmetry_horizontal
        self.symmetry_changed.emit(self.symmetry_horizontal, self.symmetry_vertical)
        self.update()

    def toggle_vertical_symmetry(self) -> None:
        self.symmetry_vertical = not self.symmetry_vertical
        self.symmetry_changed.emit(self.symmetry_horizontal, self.symmetry_vertical)
        self.update()

    def toggle_assistant(self, mode: str) -> None:
        self.assistant_mode = "none" if self.assistant_mode == mode else mode
        self._assistant_angle = None
        self.update()

    def set_assistant_mode(self, mode: str) -> None:
        self.assistant_mode = mode if mode in {"ruler", "ellipse", "perspective"} else "none"
        self._assistant_angle = None
        self.update()

    def set_vanishing_point(self, point: QPoint) -> None:
        self.assistant_vanishing_point = QPointF(
            max(0.0, min(1.0, point.x() / max(1, self.document.width - 1))),
            max(0.0, min(1.0, point.y() / max(1, self.document.height - 1))),
        )
        self._assistant_angle = None
        self.update()

    def zoom_at(self, screen_position: QPointF, factor: float) -> None:
        if self.zoom_behavior == "At canvas center":
            screen_position = QPointF(self.width() * 0.5, self.height() * 0.5)
        old_zoom = self.zoom
        new_zoom = max(self.min_zoom, min(self.max_zoom, old_zoom * factor))
        if new_zoom != old_zoom:
            image_position = self.screen_to_image_f(screen_position)
            local_screen = self._view_transform_point(screen_position, inverse=True)
            self.zoom = new_zoom
            self.offset = local_screen - image_position * new_zoom
            self.update()

    def _view_transform_point(self, position: QPointF, inverse: bool = False) -> QPointF:
        center = QPointF(self.width() * 0.5, self.height() * 0.5)
        point = position - center
        if inverse:
            angle = -self.view_rotation
            radians = math.radians(angle)
            point = QPointF(
                point.x() * math.cos(radians) - point.y() * math.sin(radians),
                point.x() * math.sin(radians) + point.y() * math.cos(radians),
            )
            if self.view_flip_x:
                point.setX(-point.x())
            if self.view_flip_y:
                point.setY(-point.y())
        else:
            if self.view_flip_x:
                point.setX(-point.x())
            if self.view_flip_y:
                point.setY(-point.y())
            radians = math.radians(self.view_rotation)
            point = QPointF(
                point.x() * math.cos(radians) - point.y() * math.sin(radians),
                point.x() * math.sin(radians) + point.y() * math.cos(radians),
            )
        return center + point

    def constrain_assistant_point(self, point: QPoint, begin: bool = False) -> QPoint:
        cx = (self.document.width - 1) * 0.5
        cy = (self.document.height - 1) * 0.5
        x, y = float(point.x()), float(point.y())
        if self.assistant_mode == "ruler":
            if abs(x - cx) < abs(y - cy):
                x = cx
            else:
                y = cy
        elif self.assistant_mode == "ellipse":
            rx, ry = max(cx, 1.0), max(cy, 1.0)
            angle = math.atan2((y - cy) / ry, (x - cx) / rx)
            x, y = cx + rx * math.cos(angle), cy + ry * math.sin(angle)
        elif self.assistant_mode == "perspective":
            cx = self.assistant_vanishing_point.x() * (self.document.width - 1)
            cy = self.assistant_vanishing_point.y() * (self.document.height - 1)
            if begin or self._assistant_angle is None:
                self._assistant_angle = round(math.atan2(y - cy, x - cx) / (math.pi / 12)) * (math.pi / 12)
            direction_x = math.cos(self._assistant_angle)
            direction_y = math.sin(self._assistant_angle)
            distance = (x - cx) * direction_x + (y - cy) * direction_y
            x, y = cx + direction_x * distance, cy + direction_y * distance
        return QPoint(round(x), round(y))

    def get_document_rect(
        self
    ) -> QRectF:

        return QRectF(
            self.offset.x(),
            self.offset.y(),
            self.document.width * self.zoom,
            self.document.height * self.zoom
        )

    # =========================================================
    # LAYERS
    # =========================================================

    def get_active_layer(
        self
    ) -> Layer | None:

        return self.document.get_active_layer()

    def get_active_image(
        self
    ) -> QImage | None:

        layer = self.get_active_layer()

        if layer is None:
            return None

        return layer.image

    # =========================================================
    # HISTORY
    # =========================================================

    def _reset_history(self) -> None:
        self.tile_history.reset()
        self.history = self.tile_history.steps
        self.history_index = 0
        self._stroke_image_format = None

    def begin_history_action(self, dirty_only: bool = False) -> None:
        self.tile_history.begin(self.document, dirty_only=dirty_only)

    def _begin_fill_history_action(self, layer: Layer, position: QPoint) -> QRect | None:
        """Start a tile-delta transaction when CreativeCore can plan the fill."""
        bounds = self.tools.fill_tool.preview_bounds(layer.image, position)
        if bounds is None:
            self.begin_history_action()
            return None
        # Flush any compatibility image edits first so captured before-tiles
        # reflect exactly the pixels that the fill is about to modify.
        layer.commit_image_cache()
        self.begin_history_action(dirty_only=True)
        self.tile_history.capture_before(layer, bounds)
        return bounds

    def _finish_fill_history_action(self, layer: Layer, bounds: QRect | None,
                                    changed: QRect | None) -> None:
        if bounds is not None and changed is not None and not changed.isEmpty():
            self.tile_history.mark_dirty(layer, changed)
        self.commit_history_action()

    def begin_selection_history_action(self) -> None:
        self.tile_history.begin(self.document, selection_only=True)

    def _set_selection_operation(self, modifiers) -> None:
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if shift and alt:
            self.selection_operation = SelectionOperation.INTERSECT
        elif shift:
            self.selection_operation = SelectionOperation.ADD
        elif alt:
            self.selection_operation = SelectionOperation.SUBTRACT
        else:
            self.selection_operation = SelectionOperation.REPLACE

    def _begin_selection_gesture(self, position: QPointF, modifiers) -> None:
        self._set_selection_operation(modifiers)
        self.begin_selection_history_action()
        self.selection_drawing = True
        self.selection_points = [self.screen_to_image(position)]

    def _update_selection_gesture(self, position: QPointF) -> None:
        point = self.screen_to_image(position)
        if self.tools.current_tool == "lasso":
            if not self.selection_points or point != self.selection_points[-1]:
                self.selection_points.append(point)
        elif len(self.selection_points) == 1:
            self.selection_points.append(point)
        else:
            self.selection_points[-1] = point

    def _finish_selection_gesture(self) -> None:
        if not self.selection_drawing:
            return
        tool = self.tools.current_tool
        points = list(self.selection_points)
        self.selection_drawing = False
        try:
            candidate = self.tools.selection_tools.shape_mask(
                tool, self.document.selection.image.size(), points
            )
            self.document.selection.combine(candidate, self.selection_operation)
        except Exception:
            self.cancel_history_action()
            self.selection_points = []
            raise
        self.selection_points = []
        self.commit_history_action()

    def apply_selection_edit(self, operation) -> bool:
        """Record a one-shot selection edit without snapshotting paint layers."""
        owns_transaction = self.tile_history._pending is None
        if owns_transaction:
            self.begin_selection_history_action()
        try:
            operation()
        except Exception:
            if owns_transaction:
                self.cancel_history_action()
            raise
        return self.commit_history_action() if owns_transaction else False

    def commit_history_action(self) -> bool:
        changed = self.tile_history.commit(self.document)
        self.history = self.tile_history.steps
        self.history_index = self.tile_history.index
        self._schedule_deferred_undo()
        return changed

    def cancel_history_action(self) -> None:
        self.tile_history.cancel()
        self._schedule_deferred_undo()

    def _schedule_deferred_undo(self) -> None:
        if self._deferred_undo_count and self.tile_history._pending is None:
            self._deferred_undo_count -= 1
            QTimer.singleShot(0, self.undo)

    def save_history(self) -> None:
        """Compatibility entry point: alternating calls begin and commit an action."""
        if self.tile_history._pending is None:
            self.begin_history_action()
        else:
            self.commit_history_action()

    def begin_stroke_history(self) -> None:
        layer = self.get_active_layer()
        self._stroke_image_format = (
            layer.tile_store.image_format if layer is not None else None
        )
        self.begin_history_action(dirty_only=True)

    def commit_stroke_history(self) -> None:
        self.commit_history_action()
        self._stroke_image_format = None

    def add_reference_image(self, source: str | QImage) -> bool:
        image = QImage(source) if isinstance(source, str) else QImage(source)
        if image.isNull():
            return False
        max_width, max_height = self.document.width * 0.45, self.document.height * 0.45
        scale = min(1.0, max_width / image.width(), max_height / image.height())
        position = QPointF(
            (self.document.width - image.width() * scale) * 0.5,
            (self.document.height - image.height() * scale) * 0.5,
        )
        self.save_history()
        item = ReferenceImage(image, position, scale, 0.8)
        self.document.reference_images.append(item)
        self.selected_reference_id = item.id
        self.save_history()
        self.tools.set_reference()
        self.update()
        return True

    def delete_selected_reference(self) -> None:
        if self.selected_reference_id is None:
            return
        index = next((i for i, item in enumerate(self.document.reference_images)
                      if item.id == self.selected_reference_id), None)
        if index is None:
            return
        self.save_history()
        self.document.reference_images.pop(index)
        self.selected_reference_id = None
        self.save_history()
        self.update()

    def _text_item_at(self, position: QPointF) -> EditableText | None:
        for item in reversed(self.document.text_objects):
            metrics = QFontMetricsF(item.font)
            bounds = metrics.boundingRect(QRectF(0, 0, max(200, self.document.width),
                                                  max(100, self.document.height)),
                                          int(Qt.TextFlag.TextWordWrap), item.text)
            bounds.translate(item.position)
            if bounds.adjusted(-4, -4, 4, 4).contains(position):
                return item
        return None

    def _edit_text_at(self, position: QPointF) -> None:
        item = self._text_item_at(position)
        prompt = item.text if item is not None else ""
        text, accepted = QInputDialog.getMultiLineText(
            self, "Texte éditable", "Texte :", prompt
        )
        if not accepted:
            return
        self.save_history()
        if item is None:
            color_values = self.brush_settings.snapshot().get("color", [0, 0, 0, 255])
            color = QColor(*[int(value) for value in color_values[:4]])
            font = QFont("Sans Serif")
            font.setPixelSize(32)
            item = EditableText(text, QPointF(position), color, font)
            self.document.text_objects.append(item)
        elif text:
            item.text = text
        else:
            self.document.text_objects.remove(item)
            item = None
        self.selected_text_id = item.id if item is not None else None
        self.save_history()
        self.update()

    def _commit_bezier_curve(self) -> None:
        layer = self.get_active_layer()
        if layer is None or layer.locked:
            return
        path = QPainterPath(self.bezier_start)
        path.cubicTo(self.bezier_control1, self.bezier_control2, self.bezier_end)
        length = (self.bezier_start - self.bezier_control1).manhattanLength()
        length += (self.bezier_control1 - self.bezier_control2).manhattanLength()
        length += (self.bezier_control2 - self.bezier_end).manhattanLength()
        spacing = max(0.02, float(self.brush_settings.get("spacing", 0.15)))
        brush_size = max(1.0, float(self.brush_settings.get("size", 10.0)))
        points = [path.pointAtPercent(index / max(8, math.ceil(length / (brush_size * spacing))))
                  for index in range(max(8, math.ceil(length / (brush_size * spacing))) + 1)]
        integer_points = [QPoint(round(point.x()), round(point.y())) for point in points]
        pad = math.ceil(brush_size * 0.5) + 4
        left = min(point.x() for point in integer_points) - pad
        top = min(point.y() for point in integer_points) - pad
        right = max(point.x() for point in integer_points) + pad
        bottom = max(point.y() for point in integer_points) + pad
        dirty = QRect(left, top, right - left + 1, bottom - top + 1).intersected(layer.image.rect())
        self.begin_stroke_history()
        self.canvas_brush_begin_stroke()
        if not self._cpp_active():
            self.tile_history.cancel()
            self.canvas_brush_end_stroke()
            return
        image = self._cpp_begin_stroke(layer.image, integer_points[0], 1.0)
        if image is None:
            self._cpp_end_stroke()
            self.tile_history.cancel()
            self.canvas_brush_end_stroke()
            return
        for start, end in zip(integer_points, integer_points[1:]):
            rendered = self._cpp_draw_segment(image, start, end, 1.0, 1.0)
            if rendered is None:
                self._cpp_end_stroke()
                self.tile_history.cancel()
                self.canvas_brush_end_stroke()
                return
            image = rendered
        self._cpp_end_stroke()
        layer.image = self._restore_locked_alpha(image, dirty) or image
        self.tile_history.mark_dirty(layer, dirty)
        if getattr(self, "gpu_ready", False):
            self.gpu_renderer.mark_layer_dirty(layer, dirty)
        self.commit_stroke_history()
        self.canvas_brush_end_stroke()
        self.update()

    def undo(
        self
    ) -> None:

        if self.tile_history._pending is not None:
            # Keep the UI responsive during an active stroke/action. The queued
            # undo runs immediately after its transaction commits or cancels.
            self._deferred_undo_count += 1
            return

        if self.tile_history.undo(self.document):
            self._invalidate_projection_cache()
            self.history_index = self.tile_history.index
            self.history_restored.emit()
            self.update()
            self._schedule_deferred_undo()

    def redo(
        self
    ) -> None:

        if self.tile_history.redo(self.document):
            self._invalidate_projection_cache()
            self.history_index = self.tile_history.index
            self.history_restored.emit()
            self.update()

    def _invalidate_projection_cache(self) -> None:
        """Reject in-flight native frames that were captured before undo/redo."""
        stale_keys = (set(self.projection_store.occupied_keys)
                      | set(self._projection_tile_generation)
                      | set(self._projection_tile_signatures))
        for key in stale_keys:
            self._projection_tile_generation[key] = -1
            self._projection_tile_signatures.pop(key, None)
            self._projection_ready_tiles.discard(key)

    # =========================================================
    # TRANSFORMER
    # =========================================================

    def get_transform_rect(
        self
    ) -> QRectF:
        selection_bounds = self.document.selection.bounds()
        base = QRectF(selection_bounds if not selection_bounds.isEmpty() else self.document.selection.image.rect())
        width = base.width() * self.transform_scale_x
        height = base.height() * self.transform_scale_y
        center_x = base.center().x()
        center_y = base.center().y()

        return QRectF(
            center_x - width / 2.0,
            center_y - height / 2.0,
            width,
            height
        )

    def get_transform_handle(
        self,
        position: QPointF
    ) -> str:

        rect = self.get_transform_rect()

        threshold = (
            10.0
            / max(
                self.zoom,
                0.01
            )
        )

        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()

        center_x = (
            left + right
        ) / 2.0

        center_y = (
            top + bottom
        ) / 2.0

        if abs(position.x() - center_x) <= threshold and abs(position.y() - (top - threshold * 3)) <= threshold:
            return "rotate"

        if (
            abs(
                position.x() - left
            ) <= threshold
            and abs(
                position.y() - top
            ) <= threshold
        ):
            return "top_left"

        if (
            abs(
                position.x() - center_x
            ) <= threshold
            and abs(
                position.y() - top
            ) <= threshold
        ):
            return "top"

        if (
            abs(
                position.x() - right
            ) <= threshold
            and abs(
                position.y() - top
            ) <= threshold
        ):
            return "top_right"

        if (
            abs(
                position.x() - right
            ) <= threshold
            and abs(
                position.y() - center_y
            ) <= threshold
        ):
            return "right"

        if (
            abs(
                position.x() - right
            ) <= threshold
            and abs(
                position.y() - bottom
            ) <= threshold
        ):
            return "bottom_right"

        if (
            abs(
                position.x() - center_x
            ) <= threshold
            and abs(
                position.y() - bottom
            ) <= threshold
        ):
            return "bottom"

        if (
            abs(
                position.x() - left
            ) <= threshold
            and abs(
                position.y() - bottom
            ) <= threshold
        ):
            return "bottom_left"

        if (
            abs(
                position.x() - left
            ) <= threshold
            and abs(
                position.y() - center_y
            ) <= threshold
        ):
            return "left"

        if rect.contains(
            position
        ):

            return "move"

        return ""

    def update_transform(
        self,
        position: QPointF
    ) -> None:

        base = self.document.selection.bounds()
        if base.isEmpty():
            base = self.document.selection.image.rect()
        center_x = base.center().x()
        center_y = base.center().y()

        min_scale = 0.05

        handle = self.transform_handle

        if handle in (
            "left",
            "right",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right"
        ):

            width_half = max(
                abs(
                    position.x()
                    - center_x
                ),
                base.width()
                * min_scale
                / 2.0
            )

            self.transform_scale_x = max(
                min_scale,
                (
                    width_half
                    * 2.0
                )
                / base.width()
            )

        if handle in (
            "top",
            "bottom",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right"
        ):

            height_half = max(
                abs(
                    position.y()
                    - center_y
                ),
                base.height()
                * min_scale
                / 2.0
            )

            self.transform_scale_y = max(
                min_scale,
                (
                    height_half
                    * 2.0
                )
                / base.height()
            )

        if handle == "move":

            self.transform_move_delta = (
                position
                - self.transform_start
            )

        if handle == "rotate":
            from math import atan2, degrees
            angle = degrees(atan2(position.y() - center_y, position.x() - center_x))
            start_angle = degrees(atan2(self.transform_start.y() - center_y, self.transform_start.x() - center_x))
            self.transform_rotation = angle - start_angle

    def apply_transform_to_layer(
        self,
        layer: Layer
    ) -> None:

        scale_x = self.transform_scale_x

        scale_y = self.transform_scale_y

        if (
            abs(
                scale_x - 1.0
            ) < 0.0001
            and abs(
                scale_y - 1.0
            ) < 0.0001
        ):

            return

        self.apply_affine_to_layer(layer, TransformSpec(scale_x=scale_x, scale_y=scale_y, rotation=self.transform_rotation))

    def apply_affine_to_layer(self, layer: Layer, spec: TransformSpec) -> None:
        selection = self.document.selection
        result = self.tools.transform_tool.apply(layer.image, spec, selection)
        layer.image = result.image
        if result.selection_image is not None:
            selection.image = result.selection_image
            selection.invalidate()
        self.sync_gpu_layer()

    def rotate_active(self, degrees: float) -> None:
        layer = self.get_active_layer()
        if layer is None:
            return
        self.save_history()
        self.apply_affine_to_layer(layer, TransformSpec(rotation=degrees))
        self.save_history()

    def flip_active_horizontal(self) -> None:
        layer = self.get_active_layer()
        if layer is not None:
            self.save_history(); self.apply_affine_to_layer(layer, TransformSpec(scale_x=-1)); self.save_history()

    def flip_active_vertical(self) -> None:
        layer = self.get_active_layer()
        if layer is not None:
            self.save_history(); self.apply_affine_to_layer(layer, TransformSpec(scale_y=-1)); self.save_history()

    def apply_crop(self) -> None:
        rect = CropTool.normalized_rect(
            self.crop_start, self.crop_current,
            QRect(0, 0, self.document.width, self.document.height),
        )
        if rect.isEmpty() or rect.width() < 2 or rect.height() < 2:
            self.cancel_history_action()
            self.update()
            return
        for layer in self.document.layers:
            layer.image = self.tools.crop_tool.apply(layer.image, rect)
        self.document.width, self.document.height = rect.width(), rect.height()
        from DOCUMENTS.selection import SelectionMask
        self.document.selection = SelectionMask(self.document.width, self.document.height)
        self.offset = QPointF(0, 0)
        self.fit_document()
        self.save_history()
        self.sync_gpu_layer()

    # =========================================================
    # PAINT
    # =========================================================

    def draw_transparency_grid(
        self,
        painter: QPainter
    ) -> None:

        rect = self.get_document_rect()

        if rect.width() <= 0:
            return

        if rect.height() <= 0:
            return

        background = self.canvas_background
        if background == "Dark":
            painter.fillRect(rect, QColor("#252525"))
            return
        if background == "Light":
            painter.fillRect(rect, QColor("#e6e6e6"))
            return

        # -----------------------------------------------------
        # Checkerboard cache
        #
        # Au lieu de dessiner chaque case individuellement,
        # on crée une seule petite texture 24x24 puis Qt la
        # répète dans le rectangle.
        # -----------------------------------------------------

        if not hasattr(
            self,
            "_transparency_brush"
        ):

            from PySide6.QtGui import (
                QBrush,
                QImage,
                QPainter as GridPainter,
            )

            tile = 12

            image = QImage(
                tile * 2,
                tile * 2,
                QImage.Format.Format_ARGB32,
            )

            image.fill(
                QColor(
                    38,
                    38,
                    38
                )
            )

            grid_painter = GridPainter(
                image
            )

            grid_painter.fillRect(
                0,
                0,
                tile,
                tile,
                QColor(
                    54,
                    54,
                    54
                )
            )

            grid_painter.fillRect(
                tile,
                tile,
                tile,
                tile,
                QColor(
                    54,
                    54,
                    54
                )
            )

            grid_painter.end()

            self._transparency_brush = QBrush(
                image
            )

        painter.save()

        painter.setClipRect(
            rect
        )

        painter.fillRect(
            rect,
            self._transparency_brush
        )

        painter.restore()


    def draw_transform_overlay(
        self,
        painter: QPainter
    ) -> None:

        if (
            self.tools.current_tool
            != "transform"
        ):

            return

        rect = self.get_transform_rect()

        left = (
            self.offset.x()
            + rect.left()
            * self.zoom
        )

        top = (
            self.offset.y()
            + rect.top()
            * self.zoom
        )

        right = (
            self.offset.x()
            + rect.right()
            * self.zoom
        )

        bottom = (
            self.offset.y()
            + rect.bottom()
            * self.zoom
        )

        center_x = (
            left + right
        ) / 2.0

        center_y = (
            top + bottom
        ) / 2.0

        painter.save()

        pen = QPen(
            QColor(
                235,
                235,
                235,
                230
            ),
            1
        )

        pen.setStyle(
            Qt.PenStyle.DashLine
        )

        painter.setPen(
            pen
        )

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.drawRect(
            QRectF(
                left,
                top,
                right - left,
                bottom - top
            )
        )

        handles = [
            QPointF(
                left,
                top
            ),
            QPointF(
                center_x,
                top
            ),
            QPointF(
                right,
                top
            ),
            QPointF(
                right,
                center_y
            ),
            QPointF(
                right,
                bottom
            ),
            QPointF(
                center_x,
                bottom
            ),
            QPointF(
                left,
                bottom
            ),
            QPointF(
                left,
                center_y
            ),
        ]

        painter.setPen(
            QPen(
                QColor(
                    40,
                    40,
                    40
                ),
                1
            )
        )

        painter.setBrush(
            QColor(
                235,
                235,
                235
            )
        )

        handle_size = 8.0

        for handle in handles:

            painter.drawRect(
                QRectF(
                    handle.x()
                    - handle_size / 2.0,
                    handle.y()
                    - handle_size / 2.0,
                    handle_size,
                    handle_size
                )
            )

        rotation_handle = QPointF(center_x, top - 24.0)
        painter.setPen(QPen(QColor(80, 170, 220), 1))
        painter.drawLine(QPointF(center_x, top), rotation_handle)
        painter.setBrush(QColor(80, 170, 220))
        painter.drawEllipse(rotation_handle, 5.0, 5.0)

        painter.restore()

    def draw_selection_overlay(self, painter: QPainter) -> None:
        """Draw a lightweight marching-ants style selection/creation overlay."""
        painter.save()
        pen = QPen(QColor(245, 245, 245), 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        bounds = self.document.selection.bounds()
        if not bounds.isEmpty():
            painter.drawRect(QRectF(
                self.offset.x() + bounds.x() * self.zoom,
                self.offset.y() + bounds.y() * self.zoom,
                bounds.width() * self.zoom,
                bounds.height() * self.zoom,
            ))

        if self.selection_drawing and len(self.selection_points) >= 2:
            screen_points = [
                QPointF(
                    self.offset.x() + point.x() * self.zoom,
                    self.offset.y() + point.y() * self.zoom,
                )
                for point in self.selection_points
            ]
            if self.tools.current_tool == "select_rectangle":
                painter.drawRect(QRectF(screen_points[0], screen_points[-1]).normalized())
            elif self.tools.current_tool == "select_ellipse":
                painter.drawEllipse(QRectF(screen_points[0], screen_points[-1]).normalized())
            else:
                for start, end in zip(screen_points, screen_points[1:]):
                    painter.drawLine(start, end)
        if self.crop_drawing:
            start = QPointF(self.offset.x() + self.crop_start.x() * self.zoom, self.offset.y() + self.crop_start.y() * self.zoom)
            end = QPointF(self.offset.x() + self.crop_current.x() * self.zoom, self.offset.y() + self.crop_current.y() * self.zoom)
            painter.setPen(QPen(QColor("#E8C36A"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(start, end).normalized())
        painter.restore()

    def draw_symmetry_guides(self, painter: QPainter) -> None:
        if not (self.symmetry_horizontal or self.symmetry_vertical):
            return
        painter.save()
        painter.setPen(QPen(QColor(90, 170, 220, 150), 1, Qt.PenStyle.DashLine))
        if self.symmetry_horizontal:
            x = self.offset.x() + (self.document.width - 1) * self.zoom * 0.5
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        if self.symmetry_vertical:
            y = self.offset.y() + (self.document.height - 1) * self.zoom * 0.5
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        painter.restore()

    def draw_assistant_guides(self, painter: QPainter) -> None:
        if self.assistant_mode == "none":
            return
        left, top = self.offset.x(), self.offset.y()
        right = left + self.document.width * self.zoom
        bottom = top + self.document.height * self.zoom
        center = QPointF(
            left + (self.document.width - 1) * self.zoom * 0.5,
            top + (self.document.height - 1) * self.zoom * 0.5,
        )
        painter.save()
        pen = QPen(QColor(231, 190, 93, 175), 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.assistant_mode == "ruler":
            painter.drawLine(QPointF(left, center.y()), QPointF(right, center.y()))
            painter.drawLine(QPointF(center.x(), top), QPointF(center.x(), bottom))
        elif self.assistant_mode == "ellipse":
            painter.drawEllipse(QRectF(
                left, top,
                max(0, self.document.width - 1) * self.zoom,
                max(0, self.document.height - 1) * self.zoom,
            ))
        elif self.assistant_mode == "perspective":
            center = QPointF(
                left + self.assistant_vanishing_point.x() * max(0, self.document.width - 1) * self.zoom,
                top + self.assistant_vanishing_point.y() * max(0, self.document.height - 1) * self.zoom,
            )
            for index in range(24):
                angle = math.tau * index / 24
                dx, dy = math.cos(angle), math.sin(angle)
                distances = []
                if dx > 0: distances.append((right - center.x()) / dx)
                elif dx < 0: distances.append((left - center.x()) / dx)
                if dy > 0: distances.append((bottom - center.y()) / dy)
                elif dy < 0: distances.append((top - center.y()) / dy)
                distance = min(value for value in distances if value >= 0)
                painter.drawLine(center, QPointF(center.x() + dx * distance,
                                                 center.y() + dy * distance))
            painter.drawEllipse(center, 3.0, 3.0)
        painter.restore()

    def draw_view_overlays(self, painter: QPainter) -> None:
        painter.save()
        painter.translate(self.width() * 0.5, self.height() * 0.5)
        painter.rotate(self.view_rotation)
        painter.scale(-1.0 if self.view_flip_x else 1.0,
                      -1.0 if self.view_flip_y else 1.0)
        painter.translate(-self.width() * 0.5, -self.height() * 0.5)
        self.draw_canvas_objects(painter)
        self.draw_transform_overlay(painter)
        self.draw_selection_overlay(painter)
        self.draw_symmetry_guides(painter)
        self.draw_assistant_guides(painter)
        painter.restore()

    def draw_canvas_objects(self, painter: QPainter) -> None:
        painter.save()
        for item in self.document.reference_images:
            rect = QRectF(
                self.offset.x() + item.position.x() * self.zoom,
                self.offset.y() + item.position.y() * self.zoom,
                item.image.width() * item.scale * self.zoom,
                item.image.height() * item.scale * self.zoom,
            )
            painter.setOpacity(item.opacity)
            painter.drawImage(rect, item.image)
            if item.id == self.selected_reference_id:
                painter.setOpacity(1.0)
                painter.setPen(QPen(QColor(70, 190, 255), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
        if not has_non_normal(self.document) and not self.document.layer_groups:
            painter.setOpacity(1.0)
            for item in self.document.text_objects:
                font = QFont(item.font)
                original_size = font.pixelSize() if font.pixelSize() > 0 else 24
                font.setPixelSize(max(1, round(original_size * self.zoom)))
                painter.setFont(font)
                painter.setPen(item.color)
                x = self.offset.x() + item.position.x() * self.zoom
                y = self.offset.y() + item.position.y() * self.zoom
                metrics = QFontMetricsF(font)
                painter.drawText(QPointF(x, y + metrics.ascent()), item.text)
                if item.id == self.selected_text_id:
                    text_bounds = metrics.boundingRect(item.text)
                    scaled_bounds = QRectF(x + text_bounds.x(), y + text_bounds.y(),
                                           text_bounds.width(), text_bounds.height())
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(70, 190, 255), 1.0, Qt.PenStyle.DashLine))
                    painter.drawRect(scaled_bounds.adjusted(-3, -3, 3, 3))
        if self.bezier_stage:
            def screen_point(point):
                return QPointF(self.offset.x() + point.x() * self.zoom,
                               self.offset.y() + point.y() * self.zoom)
            curve = QPainterPath(screen_point(self.bezier_start))
            if self.bezier_stage == 1:
                end = self.screen_to_image_f(self.cursor_position)
                curve.quadTo(screen_point(self.bezier_control1), screen_point(end))
            else:
                curve.cubicTo(screen_point(self.bezier_control1),
                              screen_point(self.bezier_control2), screen_point(self.bezier_end))
            painter.setOpacity(1.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(90, 205, 255), 1.5, Qt.PenStyle.DashLine))
            painter.drawPath(curve)
        painter.restore()

    def draw_brush_cursor(
        self,
        painter: QPainter
    ) -> None:

        if not self.show_brush_cursor_preview:
            return

        if self.tools.current_tool not in (
            "brush",
            "eraser"
        ):

            return

        if not self.cursor_visible:
            return

        if not self.rect().contains(
            int(
                self.cursor_position.x()
            ),
            int(
                self.cursor_position.y()
            )
        ):

            return

        if self.panning:
            return

        brush = self.tools.brush

        size = max(
            1.0,
            brush.size
        )

        diameter = (
            size
            * self.zoom
        )

        radius = (
            diameter
            / 2.0
        )

        if diameter < 2.0:
            return

        painter.save()

        center = self.cursor_position

        if (
            self.tools.current_tool
            == "eraser"
        ):

            outer_color = QColor(
                255,
                255,
                255,
                220
            )

            inner_color = QColor(
                20,
                20,
                20,
                220
            )

        else:

            outer_color = QColor(
                20,
                20,
                20,
                230
            )

            inner_color = QColor(
                255,
                255,
                255,
                210
            )

        painter.setPen(
            QPen(
                outer_color,
                2
            )
        )

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.drawEllipse(
            center,
            radius,
            radius
        )

        if radius > 2.0:

            painter.setPen(
                QPen(
                    inner_color,
                    1
                )
            )

            painter.drawEllipse(
                center,
                max(
                    radius - 2.0,
                    0.5
                ),
                max(
                    radius - 2.0,
                    0.5
                )
            )

        painter.restore()

    # =========================================================
    # OPENGL VIEWPORT
    # =========================================================

    def initializeGL(
        self
    ) -> None:

        context = QOpenGLContext.currentContext()
        if context is not None and context is not self._connected_gl_context:
            previous = self._connected_gl_context
            if previous is not None:
                try:
                    previous.aboutToBeDestroyed.disconnect(self.cleanup_gl_resources)
                except (RuntimeError, TypeError):
                    pass
            context.aboutToBeDestroyed.connect(self.cleanup_gl_resources)
            self._connected_gl_context = context

        self.gpu_ready = (
            self.gpu_renderer.initialize()
        )

        if self.gpu_ready:

            print(
                "✓ Canvas GPU actif"
            )

        else:

            print(
                "GPU indisponible : fallback CPU"
            )

    def paintGL(
        self
    ) -> None:

        from PySide6.QtGui import QOpenGLContext

        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:

            self._paint_cpu_fallback()

            return

        if not self.use_gpu:
            self._paint_cpu_fallback()
            return

        if (has_non_normal(self.document) or self.document.layer_groups
                or self.view_rotation or self.view_flip_x or self.view_flip_y):
            self._paint_cpu_fallback()
            return

        # -----------------------------------------------------
        # Fond + grille
        # -----------------------------------------------------

        painter = QPainter(
            self
        )

        painter.fillRect(
            self.rect(),
            QColor(
                18,
                18,
                18
            )
        )

        self.draw_transparency_grid(
            painter
        )

        # -----------------------------------------------------
        # GPU
        # -----------------------------------------------------

        if not self.gpu_ready:

            painter.end()

            self._paint_cpu_fallback()

            return

        # QPainter et OpenGL partagent le même framebuffer. Encadrer les
        # appels GL évite que leur état alterne entre deux rafraîchissements.
        painter.beginNativePainting()

        gl = context.functions()

        dpr = self.devicePixelRatioF()

        gl.glViewport(
            0,
            0,
            int(self.width() * dpr),
            int(self.height() * dpr),
        )

        gl.glEnable(
            0x0BE2
        )

        # Layers are uploaded as premultiplied-alpha textures. RGB therefore
        # uses ONE; alpha uses ONE/ONE_MINUS_SRC_ALPHA so soft brush edges do
        # not acquire a black fringe from transparent texture neighbors.
        # On a composited fullscreen desktop that briefly exposes the window
        # underneath whenever a semi-transparent brush/layer is displayed.
        gl.glBlendFuncSeparate(
            0x0001,  # GL_ONE (premultiplied RGB)
            0x0303,  # GL_ONE_MINUS_SRC_ALPHA
            0x0001,  # GL_ONE
            0x0303,  # GL_ONE_MINUS_SRC_ALPHA
        )

        gl.glDisable(
            0x0B71
        )

        gl.glDisable(
            0x0B44
        )

        # Consume all dabs accumulated since the previous paint in one or a
        # few instanced draws. Stroke completion performs one dirty-rect
        # readback before the ordinary tiled renderer resumes.
        self.gpu_instanced_stroke.process()
        gl.glViewport(
            0, 0, int(self.width() * dpr), int(self.height() * dpr)
        )
        gl.glEnable(0x0BE2)
        gl.glBlendFuncSeparate(0x0001, 0x0303, 0x0001, 0x0303)

        # -----------------------------------------------------
        # Calques
        # -----------------------------------------------------

        self.gpu_renderer.prune_layers(self.document.layers)

        # Flush cached stroke pixels before inspecting alpha coverage. The
        # opacity map is exact per document tile and cached by tile revision.
        for index, layer in enumerate(self.document.layers):
            self._commit_layer_cache_for_render(layer, index)
        occlusion = {}
        if not self.transforming:
            occlusion = self.gpu_renderer.compute_occlusion(
                self.document.layers, self.document.width, self.document.height
            )
        tile_columns = (self.document.width + TILE_SIZE - 1) // TILE_SIZE
        tile_rows = (self.document.height + TILE_SIZE - 1) // TILE_SIZE
        document_tile_count = tile_columns * tile_rows

        for index, layer in enumerate(
            self.document.layers
        ):

            if not layer.visible:
                continue

            stroke_texture = self.gpu_instanced_stroke.texture_for(layer)

            occluded_tiles = occlusion.get(id(layer), set())
            skip_full_layer = (
                getattr(layer, "tile_store", None) is None
                and len(occluded_tiles) >= document_tile_count
            )

            is_transform_preview = (
                self.transforming
                and self.tools.current_tool
                == "transform"
                and index
                == self.document.active_layer_index
            )

            self.gpu_renderer.draw_layer(
                layer=layer,
                document=self.document,
                viewport_width=float(
                    self.width()
                ),
                viewport_height=float(
                    self.height()
                ),
                zoom=self.zoom,
                offset=self.offset,
                transform_scale_x=(
                    self.transform_scale_x
                    if is_transform_preview
                    else 1.0
                ),
                transform_scale_y=(
                    self.transform_scale_y
                    if is_transform_preview
                    else 1.0
                ),
                is_transforming=is_transform_preview,
                device_pixel_ratio=dpr,
                occluded_tiles=occluded_tiles,
                skip_full_layer=skip_full_layer,
                texture_override_id=stroke_texture,
            )

        gl.glDisable(
            0x0BE2
        )

        painter.endNativePainting()

        # -----------------------------------------------------
        # Overlays Qt
        # -----------------------------------------------------

        self.draw_view_overlays(painter)

        self.draw_brush_cursor(
            painter
        )

        painter.end()

    def _paint_cpu_fallback(
        self
    ) -> None:

        painter = QPainter(
            self
        )

        painter.fillRect(
            self.rect(),
            QColor(
                18,
                18,
                18
            )
        )

        self.draw_transparency_grid(
            painter
        )

        painter.save()

        if self.view_rotation or self.view_flip_x or self.view_flip_y:
            painter.translate(self.width() * 0.5, self.height() * 0.5)
            painter.rotate(self.view_rotation)
            painter.scale(-1.0 if self.view_flip_x else 1.0,
                          -1.0 if self.view_flip_y else 1.0)
            painter.translate(-self.width() * 0.5, -self.height() * 0.5)

        painter.translate(
            self.offset
        )

        painter.scale(
            self.zoom,
            self.zoom
        )

        # QOpenGLWidget may use the OpenGL paint engine for QPainter calls.
        # Several advanced composition modes are not consistently supported
        # by that engine and silently behave like SourceOver.  Compose those
        # layers on a raster QImage first, then upload/draw the result in one
        # operation.  The normal-only path below remains unchanged and keeps
        # the lightweight fallback behaviour.
        if has_non_normal(self.document) or self.document.layer_groups:
            self._ensure_projection()
            painter.setOpacity(1.0)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            tile_keys = set(self.projection_store.resident_keys())
            if self.document.text_objects:
                columns = (self.document.width + TILE_SIZE - 1) // TILE_SIZE
                rows = (self.document.height + TILE_SIZE - 1) // TILE_SIZE
                tile_keys.update((tx, ty) for ty in range(rows) for tx in range(columns))
            for (tx, ty) in sorted(tile_keys, key=lambda key: (key[1], key[0])):
                tile = QImage(self.projection_store.tile(tx, ty))
                tile_origin_x, tile_origin_y = tx * TILE_SIZE, ty * TILE_SIZE
                for item in self.document.text_objects:
                    if not draw_text_native(
                            tile, item.text, item.font,
                            item.position.x() - tile_origin_x,
                            item.position.y() - tile_origin_y,
                            item.color):
                        painter.restore()
                        self.draw_view_overlays(painter)
                        self.draw_brush_cursor(painter)
                        painter.end()
                        raise RuntimeError("CreativeCore is required to render CPU text")
                painter.drawImage(tx * TILE_SIZE, ty * TILE_SIZE,
                                  tile)

            painter.restore()

            self.draw_view_overlays(painter)
            self.draw_brush_cursor(painter)
            painter.end()
            return

        for index, layer in enumerate(
            self.document.layers
        ):

            if not layer.visible:
                continue

            painter.setOpacity(
                layer.opacity
            )
            painter.setCompositionMode(composition_mode(getattr(layer, "blend_mode", "normal")))

            is_transform_preview = (
                self.transforming
                and self.tools.current_tool
                == "transform"
                and index
                == self.document.active_layer_index
            )

            if is_transform_preview:

                center_x = (
                    self.document.width
                    / 2.0
                )

                center_y = (
                    self.document.height
                    / 2.0
                )

                painter.save()

                painter.translate(
                    center_x,
                    center_y
                )

                painter.scale(
                    self.transform_scale_x,
                    self.transform_scale_y
                )

                painter.translate(
                    -center_x,
                    -center_y
                )

                painter.drawImage(
                    0,
                    0,
                    layer.image
                )

                painter.restore()

            else:

                painter.drawImage(
                    0,
                    0,
                    layer.image
                )

        painter.setOpacity(
            1.0
        )
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.restore()

        self.draw_view_overlays(painter)

        self.draw_brush_cursor(
            painter
        )

        painter.end()


    def _preview_brush_shape(self, end: QPoint) -> None:
        """Render a transactional shape with the current brush backend."""
        layer = self.get_active_layer()
        if layer is None or self.shape_original is None:
            return
        layer.image = self._clone_raster_native(self.shape_original)
        points = self.tools.shape_path(self.shape_start, end)
        if len(points) < 2:
            return

        if self._cpp_active():
            image = self._cpp_begin_stroke(layer.image, points[0].toPoint(), 1.0)
            if image is None:
                self._cpp_end_stroke()
                return
            for start, finish in zip(points, points[1:]):
                rendered = self._cpp_draw_segment(
                    image, start.toPoint(), finish.toPoint(), 1.0, 1.0
                )
                if rendered is None:
                    self._cpp_end_stroke()
                    return
                image = rendered
            self._cpp_end_stroke()
            layer.image = self._restore_alpha_from(image, self.shape_original) if getattr(layer, "lock_alpha", False) else image
        else:
            return
        self.sync_gpu_layer()

    def _brush_dirty_rect(self, start: QPoint, end: QPoint) -> QRect:
        points = [(start, end)]
        cx, cy = self.document.width - 1, self.document.height - 1
        if self.symmetry_horizontal:
            points.append((QPoint(cx - start.x(), start.y()), QPoint(cx - end.x(), end.y())))
        if self.symmetry_vertical:
            points.append((QPoint(start.x(), cy - start.y()), QPoint(end.x(), cy - end.y())))
        if self.symmetry_horizontal and self.symmetry_vertical:
            points.append((QPoint(cx - start.x(), cy - start.y()), QPoint(cx - end.x(), cy - end.y())))
        settings = self.brush_settings.snapshot()
        size = float(settings.get("size", 10.0))
        # Bound the maximum jittered dab plus its scatter displacement so
        # alpha restoration covers every pixel the C++ brush may have touched.
        radius = math.ceil(size * (1.0 + float(settings.get("sizeJitter", 0.0)) +
                                   float(settings.get("scatter", 0.0))) * 0.5) + 2
        left = min(min(a.x(), b.x()) for a, b in points) - radius
        top = min(min(a.y(), b.y()) for a, b in points) - radius
        right = max(max(a.x(), b.x()) for a, b in points) + radius
        bottom = max(max(a.y(), b.y()) for a, b in points) + radius
        return QRect(left, top, right - left + 1, bottom - top + 1)

    def sync_gpu_layer(self, dirty_rect: QRect | None = None) -> None:
        """Invalide uniquement la texture après un dessin déjà fait en C++."""
        layer = self.document.get_active_layer()
        if layer is not None:
            # CreativeCore writes through a raw pointer, which does not bump
            # QImage.cacheKey(); explicitly copy its dirty area to tiles.
            layer.commit_image_cache(dirty_rect, force=True)
            self.tile_history.mark_dirty(layer, dirty_rect)
        if layer is not None and getattr(self, "gpu_ready", False):
            self.gpu_renderer.mark_layer_dirty(layer, dirty_rect)
        self.update()

    def _ensure_projection(self) -> None:
        for index, layer in enumerate(self.document.layers):
            self._commit_layer_cache_for_render(layer, index)
        if (self.projection_store.width != self.document.width
                or self.projection_store.height != self.document.height):
            self.projection_store.resize(self.document.width, self.document.height)
            self._projection_tile_signatures.clear()
            self._projection_tile_generation.clear()
            self._projection_ready_tiles.clear()
        keys = self.visible_document_tile_keys()
        known_keys = (self.projection_store.resident_keys()
                      | set(self._projection_tile_signatures)
                      | set(self._projection_tile_generation)
                      | self._projection_ready_tiles)
        for key in known_keys:
            if key not in keys:
                self.projection_store.remove_resident_tile(*key)
                self._projection_tile_signatures.pop(key, None)
                self._projection_ready_tiles.discard(key)
                self._projection_tile_generation.pop(key, None)
        inputs = {}
        for tx, ty in keys:
            key = (tx, ty)
            signature = self._projection_signature_for(tx, ty)
            if self._projection_tile_signatures.get(key) == signature:
                continue
            rect = self.projection_store.tile_rect(tx, ty)
            if rect.isEmpty():
                continue
            rect = self.projection_store.tile_rect(tx, ty)
            tile_layers, missing_scratch = self._tile_projection_layers(tx, ty, rect)
            if missing_scratch:
                continue
            inputs[key] = (rect.width(), rect.height(), tile_layers)
            self._projection_tile_signatures[key] = signature
            self._projection_ready_tiles.discard(key)
        if not inputs:
            return
        generation = self.projection_worker.request(inputs)
        for key in inputs:
            self._projection_tile_generation[key] = generation

    def _tile_projection_layers(self, tx: int, ty: int, rect: QRect):
        """Build projection entries, isolating and caching each layer group."""
        document = self.document
        group_by_id = {group.id: group for group in document.layer_groups}
        children = {group_id: [] for group_id in group_by_id}
        roots = []
        for group in document.layer_groups:
            if group.parent_id is None:
                roots.append(group)
            elif group.parent_id in children and group.parent_id != group.id:
                children[group.parent_id].append(group)
            else:
                raise ValueError("Hiérarchie de groupes invalide")
        positions = {layer.id: index for index, layer in enumerate(document.layers)}

        def members(group):
            result = [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]
            if not result or result != list(range(min(result), max(result) + 1)):
                raise ValueError("Les groupes doivent contenir une plage contiguë")
            return result

        def render_group(group):
            group_members = members(group)
            child_groups = sorted(children[group.id], key=lambda item: min(members(item)))
            child_starts = {}
            covered = set()
            for child in child_groups:
                child_members = members(child)
                if (not set(child_members).issubset(group_members)
                        or covered.intersection(child_members)):
                    raise ValueError("Les groupes enfants doivent être disjoints")
                child_starts[min(child_members)] = child
                covered.update(child_members)
            tiles, pending, signature = [], False, [group.id, group.visible,
                float(group.opacity), group.blend_mode,
                tuple(sorted((str(k), repr(v)) for k, v in group.blend_parameters.items()))]
            position = min(group_members)
            while position <= max(group_members):
                child = child_starts.get(position)
                if child is not None:
                    child_tile, child_pending, child_signature = render_group(child)
                    tiles.append(child_tile)
                    pending |= child_pending
                    signature.append(child_signature)
                    position = max(members(child)) + 1
                    continue
                if position not in covered:
                    layer = document.layers[position]
                    child_tiles, child_pending = self._projection_tile_for_layer(layer, tx, ty, rect)
                    tiles.extend(child_tiles)
                    pending |= child_pending
                    signature.append((layer.id, layer.visible, float(layer.opacity), layer.blend_mode,
                                      bool(getattr(layer, "clipping", False)),
                                      tuple(sorted((str(k), repr(v)) for k, v in layer.blend_parameters.items())),
                                      layer.tile_store.tile_revision(tx, ty),
                                      getattr(getattr(layer, "alpha_mask_store", None),
                                              "tile_revision", lambda *_: 0)(tx, ty)))
                position += 1
            if pending or not group.visible:
                return ProjectionLayer(QImage(), False, 0.0, "normal", {}), pending, tuple(signature)
            tile_key = (tx, ty)
            group_signature = tuple(signature)
            image = group.cached_tile(tile_key, group_signature)
            if image is None:
                image = composite_layers(rect.width(), rect.height(), tiles)
                group.store_tile(tile_key, group_signature, image)
            return ProjectionLayer(image, True, float(group.opacity), str(group.blend_mode),
                                   dict(group.blend_parameters)), False, group_signature

        roots_by_start = {}
        root_coverage = set()
        for group in roots:
            group_members = members(group)
            if root_coverage.intersection(group_members):
                raise ValueError("Un calque appartient à plusieurs groupes racine")
            roots_by_start[min(group_members)] = group
            root_coverage.update(group_members)
        entries = []
        missing = False
        index = 0
        while index < len(document.layers):
            group = roots_by_start.get(index)
            if group is None and index not in root_coverage:
                items, pending = self._projection_tile_for_layer(document.layers[index], tx, ty, rect)
                missing |= pending
                entries.extend(items)
                index += 1
                continue
            if group is not None:
                entry, pending, _signature = render_group(group)
                missing |= pending
                if entry.visible:
                    entries.append(entry)
                index = max(members(group)) + 1
            else:
                index += 1
        return entries, missing

    def _projection_tile_for_layer(self, layer, tx: int, ty: int, rect: QRect):
        store = layer.tile_store
        if store.has_tile(tx, ty) and not store.tile_is_resident(tx, ty):
            store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
            return [], True
        if store.has_tile(tx, ty):
            image = store.tile(tx, ty)
        else:
            image = QImage(rect.size(), QImage.Format.Format_ARGB32)
            if not fill_image_native(image, QColor(0, 0, 0, 0)):
                raise RuntimeError("CreativeCore is required to clear projection tiles")
        mask_store = getattr(layer, "alpha_mask_store", None)
        if mask_store is not None and mask_store.has_tile(tx, ty):
            if not mask_store.tile_is_resident(tx, ty):
                mask_store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                return [], True
            mask = mask_store.tile(tx, ty)
            image = clone_image_native(image)
            if image is None or mask.size() != image.size() or not apply_alpha_mask_native(image, mask):
                raise RuntimeError("CreativeCore refused to apply the projection alpha mask")
        return [ProjectionLayer(image, layer.visible, float(layer.opacity),
                                str(layer.blend_mode), dict(layer.blend_parameters),
                                bool(getattr(layer, "clipping", False)))], False

    def _commit_layer_cache_for_render(self, layer, index: int) -> None:
        """Flush legacy pixels while retaining the active brush buffer mid-stroke."""
        keep_buffer = self.drawing and index == self.document.active_layer_index
        layer.commit_image_cache(release=not keep_buffer)

    def _on_projected_tile(self, generation: int, tx: int, ty: int, image) -> None:
        key = (tx, ty)
        if self._projection_tile_generation.get(key) != generation:
            return
        self.projection_store.set_tile(tx, ty, image)
        self._projection_ready_tiles.add(key)
        self.update()

    def _on_projection_failed(self, generation: int, tx: int, ty: int, error: str) -> None:
        key = (tx, ty)
        if self._projection_tile_generation.get(key) != generation:
            return
        self._projection_tile_signatures.pop(key, None)
        self._projection_ready_tiles.discard(key)
        print(f"Projection de tuile ({tx}, {ty}) impossible : {error}")

    def _projection_signature_for(self, tx: int, ty: int) -> tuple:
        layers = tuple(
            (layer.id, layer.visible, float(layer.opacity), str(layer.blend_mode),
             bool(getattr(layer, "clipping", False)),
             tuple(sorted((str(k), repr(v)) for k, v in layer.blend_parameters.items())),
             layer.tile_store.tile_revision(tx, ty),
             (getattr(getattr(layer, "alpha_mask_store", None),
                      "tile_revision", lambda *_: 0)(tx, ty)))
            for layer in self.document.layers
        )
        groups = tuple((group.id, group.name, tuple(group.layer_ids), group.visible,
                        float(group.opacity), group.blend_mode,
                        tuple(sorted((str(k), repr(v)) for k, v in group.blend_parameters.items())))
                       for group in self.document.layer_groups)
        return layers, groups

    def visible_document_tile_keys(self) -> set[tuple[int, int]]:
        """Conservative document-space tile bounds for the current viewport."""
        width, height = float(self.width()), float(self.height())
        center_x, center_y = width * 0.5, height * 0.5
        corners = []
        angle = math.radians(float(self.view_rotation))
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        for sx, sy in ((0.0, 0.0), (width, 0.0), (0.0, height), (width, height)):
            x, y = sx - center_x, sy - center_y
            # Undo the view's rotate, then undo its screen-space flips.
            rx = x * cos_a + y * sin_a
            ry = -x * sin_a + y * cos_a
            if self.view_flip_x:
                rx = -rx
            if self.view_flip_y:
                ry = -ry
            screen_x, screen_y = rx + center_x, ry + center_y
            doc_x = (screen_x - self.offset.x()) / max(0.001, self.zoom)
            doc_y = (screen_y - self.offset.y()) / max(0.001, self.zoom)
            corners.append((doc_x, doc_y))
        left = max(0, math.floor(min(p[0] for p in corners)))
        top = max(0, math.floor(min(p[1] for p in corners)))
        right = min(self.document.width, math.ceil(max(p[0] for p in corners)))
        bottom = min(self.document.height, math.ceil(max(p[1] for p in corners)))
        if right <= left or bottom <= top:
            return set()
        return {(tx, ty)
                for ty in range(top // TILE_SIZE, (bottom - 1) // TILE_SIZE + 1)
                for tx in range(left // TILE_SIZE, (right - 1) // TILE_SIZE + 1)}

    def _on_scratch_tile_ready(self, _tx: int, _ty: int, _success: bool, _error) -> None:
        if _success:
            self.update()
            position = self._pending_color_sample
            if position is not None:
                key = self.document.layers[0].tile_store.tile_key(position.x(), position.y()) if self.document.layers else (0, 0)
                if all(not layer.visible or not layer.tile_store.has_tile(*key)
                       or layer.tile_store.tile_is_resident(*key)
                       for layer in self.document.layers):
                    self.sample_composite_color(position)
        elif _error:
            print(f"Rechargement scratch impossible : {_error}")

    def prune_gpu_layers(self) -> None:
        """Évince les textures des calques retirés avec le contexte courant."""
        if not getattr(self, "gpu_ready", False):
            return
        self.makeCurrent()
        try:
            self.gpu_renderer.prune_layers(self.document.layers)
        finally:
            self.doneCurrent()
        self.update()

    # =========================================================
    # NETTOYAGE GPU
    # =========================================================

    def cleanup_gl_resources(self) -> None:
        if self._gl_cleanup_in_progress:
            return

        renderer = getattr(self, "gpu_renderer", None)
        context = self._connected_gl_context or self.context()
        if renderer is None or context is None:
            return

        self._gl_cleanup_in_progress = True
        made_current = QOpenGLContext.currentContext() is not context
        try:
            if made_current:
                self.makeCurrent()
            if QOpenGLContext.currentContext() is context:
                if self.gpu_instanced_stroke.active:
                    self.gpu_instanced_stroke.request_finish()
                    self.gpu_instanced_stroke.process()
                self.gpu_instanced_stroke.cleanup()
                renderer.cleanup()
                self.gpu_ready = False
        except RuntimeError as error:
            print(f"OpenGL cleanup : {error}")
        finally:
            if made_current and QOpenGLContext.currentContext() is context:
                self.doneCurrent()
            self._gl_cleanup_in_progress = False

    def _destroy_cpp_brush(self) -> None:
        brush = getattr(self, "cpp_brush", None)
        library = getattr(self, "cpp_brush_library", None)
        self.cpp_brush = None
        self.cpp_brush_enabled = False
        if brush and library is not None:
            try:
                library.cs_brush_destroy(brush)
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self._destroy_cpp_brush()
        except Exception:
            pass

    def closeEvent(
        self,
        event
    ) -> None:

        self.cleanup_gl_resources()
        self.projection_worker.close()
        self._destroy_cpp_brush()

        super().closeEvent(
            event
        )

    # =========================================================
    # EVENTS VIEW
    # =========================================================

    def resizeEvent(
        self,
        event: QResizeEvent
    ) -> None:

        if not self._initial_view_fitted:
            self.fit_document()
            self._initial_view_fitted = True

        super().resizeEvent(
            event
        )

        self.update()

    def enterEvent(
        self,
        event: QEnterEvent
    ) -> None:

        self.cursor_visible = True

        self.update()

        super().enterEvent(
            event
        )

    def leaveEvent(
        self,
        event: QEvent
    ) -> None:

        self.cursor_visible = False

        self.update()

        super().leaveEvent(
            event
        )

    # =========================================================
    # KEYBOARD
    # =========================================================

    def keyPressEvent(
        self,
        event: QKeyEvent
    ) -> None:

        if event.isAutoRepeat():
            return

        key = event.key()

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.tools.current_tool == "reference" and self.selected_reference_id is not None:
                self.delete_selected_reference()
                event.accept()
                return
            if self.tools.current_tool == "text" and self.selected_text_id is not None:
                item = next((obj for obj in self.document.text_objects
                             if obj.id == self.selected_text_id), None)
                if item is not None:
                    self.save_history()
                    self.document.text_objects.remove(item)
                    self.save_history()
                self.selected_text_id = None
                self.update()
                event.accept()
                return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_0:
                self.reset_canvas_rotation(); event.accept(); return
            if key == Qt.Key.Key_1:
                self.zoom_100(); event.accept(); return
            if key == Qt.Key.Key_5:
                self.flip_canvas_view_horizontal(); event.accept(); return
            if key == Qt.Key.Key_6:
                self.rotate_canvas(15.0); event.accept(); return
            if key == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.toggle_canvas_only(); event.accept(); return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_A:
                self.apply_selection_edit(self.document.selection.select_all)
                self.update()
                event.accept()
                return
            if key == Qt.Key.Key_D:
                self.apply_selection_edit(self.document.selection.clear)
                self.update()
                event.accept()
                return
            if key == Qt.Key.Key_I:
                self.apply_selection_edit(self.document.selection.invert)
                self.update()
                event.accept()
                return

        if key == Qt.Key.Key_B:

            self.tools.set_brush()

            self.update()

            event.accept()

            return

        if key == Qt.Key.Key_H:
            self.tools.set_hand(); event.accept(); return
        if key == Qt.Key.Key_Z:
            self.tools.set_zoom_view(); event.accept(); return
        if key == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.tools.set_rotate_view(); event.accept(); return

        if key == Qt.Key.Key_E:

            self.tools.set_eraser()

            self.update()

            event.accept()

            return

        if key == Qt.Key.Key_I:

            self.tools.set_picker()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_S:

            self.tools.set_smudge()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_F:
            self.tools.set_fill()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_G:
            self.tools.set_gradient()
            self.update()
            event.accept()
            return

        shape_shortcuts = {
            Qt.Key.Key_L: self.tools.set_line,
            Qt.Key.Key_R: self.tools.set_rectangle,
            Qt.Key.Key_O: self.tools.set_ellipse,
        }
        if key in shape_shortcuts:
            shape_shortcuts[key]()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_M:

            self.tools.set_move()

            self.update()

            event.accept()

            return

        if key == Qt.Key.Key_T:

            self.tools.set_transform()

            self.update()

            event.accept()

            return

        if key == Qt.Key.Key_Y:
            self.tools.set_text()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_P:
            self.tools.set_bezier()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_Space:

            self.space_pressed = True

            self.update()

            event.accept()

            return

        if key == Qt.Key.Key_C:
            self.tools.set_crop()
            self.update()
            event.accept()
            return

        if key == Qt.Key.Key_Escape:
            if self.selection_drawing:
                self.selection_drawing = False
                self.selection_points = []
                self.cancel_history_action()
                self.update()
                event.accept()
                return
            if self.gradient_drawing:
                layer = self.get_active_layer()
                if layer is not None and self.gradient_original is not None:
                    layer.image = self._clone_raster_native(self.gradient_original)
                self.gradient_drawing = False
                self.gradient_original = None
                self._alpha_lock_snapshot = None
                self.cancel_history_action()
                self.sync_gpu_layer()
                self.update()
                event.accept()
                return
            if self.shape_drawing:
                layer = self.get_active_layer()
                if layer is not None and self.shape_original is not None:
                    layer.image = self._clone_raster_native(self.shape_original)
                self.shape_drawing = False
                self.shape_original = None
                self._alpha_lock_snapshot = None
                self._cpp_end_stroke()
                self.cancel_history_action()
                self.sync_gpu_layer()
                self.update()
                event.accept()
                return
            if self.bezier_stage:
                self.bezier_stage = 0
                self.bezier_dragging = False
                self.update()
                event.accept()
                return
            if self.crop_drawing:
                self.crop_drawing = False
                self.cancel_history_action()
                self.update()
                event.accept()
                return
            if self.transforming:
                self.transforming = False
                self.cancel_history_action()
                self.transform_rotation = 0.0
                self.transform_scale_x = 1.0
                self.transform_scale_y = 1.0

                self.transform_rotation = 0.0
                self.update()
                event.accept()
                return

        super().keyPressEvent(
            event
        )

    def keyReleaseEvent(
        self,
        event: QKeyEvent
    ) -> None:

        if event.isAutoRepeat():
            return

        if (
            event.key()
            == Qt.Key.Key_Space
        ):

            self.space_pressed = False

            self.update()

            event.accept()

            return

        super().keyReleaseEvent(
            event
        )

    # =========================================================
    # MOUSE
    # =========================================================

    def mousePressEvent(
        self,
        event: QMouseEvent
    ) -> None:

        self.setFocus()

        if self._ignore_tablet_synthetic_mouse(event):
            event.accept()
            return

        if (event.button() == Qt.MouseButton.RightButton
                and self.right_click_color_picker
                and self.tools.current_tool != "zoom_view"):
            self.sample_composite_color(self.screen_to_image(event.position()))
            event.accept()
            return

        modifiers = event.modifiers()
        if (self.tools.current_tool == "clone_stamp" and
                event.button() == Qt.MouseButton.LeftButton and
                modifiers & Qt.KeyboardModifier.ShiftModifier):
            self._set_clone_source(self.screen_to_image(event.position()))
            event.accept()
            return
        if self.tools.current_tool == "reference" and event.button() == Qt.MouseButton.LeftButton:
            point = self.screen_to_image(event.position())
            hit = None
            for item in reversed(self.document.reference_images):
                rect = QRectF(item.position.x(), item.position.y(),
                              item.image.width() * item.scale, item.image.height() * item.scale)
                if rect.contains(QPointF(point)):
                    hit = item
                    break
            self.selected_reference_id = hit.id if hit is not None else None
            self.reference_drag_id = hit.id if hit is not None else None
            if hit is not None:
                self.save_history()
                self.reference_drag_anchor = QPointF(point) - hit.position
            self.update()
            event.accept()
            return
        if self.tools.current_tool == "text" and event.button() == Qt.MouseButton.LeftButton:
            point = self.screen_to_image(event.position())
            selected = self._text_item_at(QPointF(point))
            self.selected_text_id = selected.id if selected is not None else None
            if selected is not None and modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.text_drag_id = selected.id
                self.text_drag_anchor = QPointF(point) - selected.position
                self.save_history()
                event.accept()
                return
            self._edit_text_at(QPointF(point))
            event.accept()
            return
        if self.tools.current_tool == "bezier" and event.button() == Qt.MouseButton.LeftButton:
            layer = self.get_active_layer()
            if layer is None or layer.locked:
                event.accept()
                return
            point = QPointF(self.screen_to_image(event.position()))
            if self.bezier_stage == 0:
                self.bezier_start = point
                self.bezier_control1 = point
                self.bezier_stage = 1
            else:
                self.bezier_end = point
                self.bezier_control2 = point
                self.bezier_stage = 2
            self.bezier_dragging = True
            self.cursor_position = event.position()
            self.update()
            event.accept()
            return
        self._set_selection_operation(modifiers)

        if (
            self.assistant_mode == "perspective"
            and event.button() == Qt.MouseButton.LeftButton
            and modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            self.set_vanishing_point(self.screen_to_image(event.position()))
            event.accept()
            return

        # -----------------------------------------------------
        # PAN
        # -----------------------------------------------------

        if (
            event.button()
            == Qt.MouseButton.MiddleButton
        ):

            self.panning = True

            self.pan_start = (
                event.position()
            )

            self.offset_start = (
                self.offset
            )

            event.accept()

            return

        if (
            event.button()
            == Qt.MouseButton.LeftButton
            and self.space_pressed
        ):

            self.panning = True

            self.pan_start = (
                event.position()
            )

            self.offset_start = (
                self.offset
            )

            event.accept()

            return

        if event.button() == Qt.MouseButton.LeftButton and self.tools.current_tool == "hand":
            self.panning = True
            self.pan_start = event.position()
            self.offset_start = QPointF(self.offset)
            event.accept()
            return

        if self.tools.current_tool == "zoom_view" and event.button() in (
            Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton
        ):
            self.zoom_at(event.position(), 1.25 if event.button() == Qt.MouseButton.LeftButton else 0.8)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.tools.current_tool == "rotate_view":
            center = QPointF(self.width() * 0.5, self.height() * 0.5)
            delta = event.position() - center
            self.view_dragging = True
            self.view_drag_angle = math.atan2(delta.y(), delta.x())
            self.view_drag_rotation = self.view_rotation
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "picker"
        ):
            self.sample_composite_color(
                self.screen_to_image(event.position())
            )
            event.accept()
            return

        active_layer = self.get_active_layer()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and active_layer is not None
            and active_layer.locked
            and self.tools.current_tool not in {"picker", "select_rectangle", "select_ellipse", "lasso", "magic_wand"}
        ):
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "fill"
        ):
            layer = self.get_active_layer()
            if layer is None:
                return
            position = self.screen_to_image(event.position())
            color_values = self.brush_settings.snapshot()["color"]
            alpha_locked = bool(getattr(layer, "lock_alpha", False))
            fill_history_bounds = self._begin_fill_history_action(layer, position)
            alpha_snapshot = (self._clone_raster_native(layer.image) if alpha_locked and fill_history_bounds is None
                              else None)
            changed = self.tools.fill(
                layer.image,
                position,
                QColor(*[int(value) for value in color_values]),
            )
            if alpha_locked:
                restored = (self._restore_alpha_from_history(
                    layer.image, layer, fill_history_bounds)
                    if fill_history_bounds is not None else
                    self._restore_alpha_from(layer.image, alpha_snapshot))
                if restored is not None:
                    layer.image = restored
            if changed is not None and not changed.isEmpty():
                self.sync_gpu_layer(changed)
            self._finish_fill_history_action(layer, fill_history_bounds, changed)
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "gradient"
        ):
            layer = self.get_active_layer()
            if layer is None:
                return
            self.save_history()
            self.gradient_drawing = True
            self.gradient_start = self.screen_to_image(event.position())
            self.gradient_original = self._clone_raster_native(layer.image)
            if getattr(layer, "lock_alpha", False):
                self._alpha_lock_snapshot = layer.image.convertToFormat(
                    QImage.Format.Format_RGBA8888
                )
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "crop"
        ):
            self.crop_drawing = True
            self.crop_start = self.screen_to_image(event.position())
            self.crop_current = self.crop_start
            self.save_history()
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool in self.tools.shape_tools.SUPPORTED
        ):
            layer = self.get_active_layer()
            if layer is None:
                return
            self.save_history()
            self.shape_drawing = True
            self.shape_start = self.screen_to_image(event.position())
            self.shape_original = self._clone_raster_native(layer.image)
            if getattr(layer, "lock_alpha", False):
                self._alpha_lock_snapshot = layer.image.convertToFormat(
                    QImage.Format.Format_RGBA8888
                )
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "magic_wand"
        ):
            layer = self.get_active_layer()
            if layer is None:
                return
            self.begin_selection_history_action()
            candidate = self.tools.selection_tools.magic_wand(
                layer.image, self.screen_to_image(event.position()),
                cpp_library=self.cpp_brush_library,
            )
            self.document.selection.combine(candidate, self.selection_operation)
            self.commit_history_action()
            self.update()
            event.accept()
            return

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool in self.tools.selection_tools.SHAPE_TOOLS
        ):
            self._begin_selection_gesture(event.position(), modifiers)
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # OUTIL DÉPLACER
        # -----------------------------------------------------

        if (
            event.button()
            == Qt.MouseButton.LeftButton
            and self.tools.current_tool
            == "move"
        ):

            layer = (
                self.get_active_layer()
            )

            if layer is None:
                return

            position = (
                self.screen_to_image(
                    event.position()
                )
            )

            self.save_history()

            if not self.document.selection.is_empty():
                self.selection_moving = True
                self.selection_move_start = position
                self.selection_move_original = self._clone_raster_native(layer.image)
                self.selection_move_original_mask = self._clone_raster_native(self.document.selection.image)
                event.accept()
                return

            self.tools.begin_move(
                position
            )

            event.accept()

            return

        # -----------------------------------------------------
        # OUTIL TRANSFORMER
        # -----------------------------------------------------

        if (
            event.button()
            == Qt.MouseButton.LeftButton
            and self.tools.current_tool
            == "transform"
        ):

            layer = (
                self.get_active_layer()
            )

            if layer is None:
                return

            position = (
                self.screen_to_image(
                    event.position()
                )
            )

            handle = (
                self.get_transform_handle(
                    position
                )
            )

            if not handle:
                return

            self.save_history()

            self.transforming = True

            self.transform_handle = (
                handle
            )

            self.transform_start = (
                position
            )

            self.transform_original_scale_x = (
                self.transform_scale_x
            )

            self.transform_original_scale_y = (
                self.transform_scale_y
            )

            self.transform_move_delta = QPointF(
                0,
                0
            )

            event.accept()

            return

        # -----------------------------------------------------
        # DESSIN
        # -----------------------------------------------------

        if (
            event.button()
            == Qt.MouseButton.LeftButton
            and self.tools.current_tool
            in (
                "brush",
                "eraser",
                "smudge",
                "clone_stamp",
                "blur",
                "sharpen",
            )
        ):

            layer = (
                self.get_active_layer()
            )

            if layer is None:
                return

            self.last_point = self.constrain_assistant_point(
                self.screen_to_image(event.position()), begin=True
            )

            if self.tools.current_tool == "clone_stamp" and not self._begin_clone_sampling(layer, self.last_point):
                event.accept()
                return

            self.begin_stroke_history()
            self.canvas_brush_begin_stroke()
            self.drawing = True

            if self._try_begin_instanced_stroke(layer, self.last_point, 1.0,
                                                self.tools.current_tool):
                self.update()
                event.accept()
                return

            if self.tools.current_tool in ("blur", "sharpen"):
                layer.image = self._apply_filter_segment(
                    layer.image, self.last_point, self.last_point, 1.0, 1.0,
                    self.tools.current_tool == "sharpen",
                )
                event.accept()
                return

            if self._cpp_active():
                if self.tools.current_tool == "clone_stamp":
                    cpp_image = self._cpp_begin_clone_stroke(layer.image, self.last_point, 1.0)
                else:
                    cpp_image = self._cpp_begin_stroke(layer.image, self.last_point, 1.0)

                if cpp_image is not None:
                    dirty_rect = self._brush_dirty_rect(self.last_point, self.last_point)
                    if getattr(layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    layer.adopt_image_cache(cpp_image)
                    self.sync_gpu_layer(dirty_rect)
                else:
                    # CreativeCore is the only raster engine. Do not silently
                    # replace a failed dab with a different Python renderer.
                    self._cpp_end_stroke()
            else:
                # Raster editing is unavailable without CreativeCore.
                self._cpp_end_stroke()

            self.update()

            event.accept()

    def mouseMoveEvent(
        self,
        event: QMouseEvent
    ) -> None:

        if self._ignore_tablet_synthetic_mouse(event):
            event.accept()
            return

        previous_cursor_position = QPointF(self.cursor_position)
        self.cursor_position = (
            event.position()
        )

        self.cursor_visible = True

        if self.reference_drag_id is not None:
            item = next((ref for ref in self.document.reference_images
                         if ref.id == self.reference_drag_id), None)
            if item is not None:
                point = self.screen_to_image(event.position())
                item.position = QPointF(point) - self.reference_drag_anchor
            self.update()
            event.accept()
            return
        if self.text_drag_id is not None:
            item = next((obj for obj in self.document.text_objects if obj.id == self.text_drag_id), None)
            if item is not None:
                item.position = QPointF(self.screen_to_image(event.position())) - self.text_drag_anchor
            self.update()
            event.accept()
            return
        if self.bezier_dragging:
            point = QPointF(self.screen_to_image(event.position()))
            if self.bezier_stage == 1:
                self.bezier_control1 = point
            elif self.bezier_stage == 2:
                self.bezier_control2 = point
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # PAN
        # -----------------------------------------------------

        if self.panning:

            movement = (
                event.position()
                - self.pan_start
            )

            self.offset = (
                self.offset_start
                + movement
            )

            self.update()

            event.accept()

            return

        if self.view_dragging:
            center = QPointF(self.width() * 0.5, self.height() * 0.5)
            delta = event.position() - center
            angle = math.atan2(delta.y(), delta.x())
            self.view_rotation = (
                self.view_drag_rotation + math.degrees(angle - self.view_drag_angle)
            ) % 360.0
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # DÉPLACEMENT DU CALQUE
        # -----------------------------------------------------

        if (
            self.tools.current_tool
            == "move"
            and self.tools.move_tool.is_active()
        ):

            layer = (
                self.get_active_layer()
            )

            if layer is None:
                return

            current_point = self.screen_to_image(event.position())

            self.tools.move(
                layer.image,
                current_point
            )

            self.update()

            event.accept()

            return

        if self.selection_moving:
            layer = self.get_active_layer()
            if layer is None or self.selection_move_original is None:
                return
            position = self.screen_to_image(event.position())
            delta = position - self.selection_move_start
            layer.image = self._clone_raster_native(self.selection_move_original)
            if self.selection_move_original_mask is not None:
                self.document.selection.image = self._clone_raster_native(self.selection_move_original_mask)
                self.document.selection.invalidate()
            result = self.tools.transform_tool.apply(
                layer.image,
                TransformSpec(translate_x=delta.x(), translate_y=delta.y()),
                self.document.selection,
            )
            layer.image = result.image
            if result.selection_image is not None:
                self.document.selection.image = result.selection_image
                self.document.selection.invalidate()
            self.sync_gpu_layer()
            event.accept()
            return

        # -----------------------------------------------------
        # TRANSFORMATION
        # -----------------------------------------------------

        if self.transforming:

            position = (
                self.screen_to_image(
                    event.position()
                )
            )

            if self.transform_handle == "move":

                self.transform_move_delta = (
                    position
                    - self.transform_start
                )

            else:

                self.update_transform(
                    position
                )

            self.update()

            event.accept()

            return

        if self.gradient_drawing:
            layer = self.get_active_layer()
            if layer is None or self.gradient_original is None:
                return
            layer.image = self._clone_raster_native(self.gradient_original)
            color_values = self.brush_settings.snapshot()["color"]
            self.tools.gradient(
                layer.image,
                self.gradient_start,
                self.screen_to_image(event.position()),
                QColor(*[int(value) for value in color_values]),
            )
            if getattr(layer, "lock_alpha", False):
                restored = self._restore_alpha_from(layer.image, self.gradient_original)
                if restored is not None:
                    layer.image = restored
            self.sync_gpu_layer()
            event.accept()
            return

        if self.crop_drawing:
            self.crop_current = self.screen_to_image(event.position())
            self.update()
            event.accept()
            return

        if self.shape_drawing:
            self._preview_brush_shape(self.screen_to_image(event.position()))
            event.accept()
            return

        if self.selection_drawing:
            self._update_selection_gesture(event.position())
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # DESSIN
        # -----------------------------------------------------

        if self.drawing:

            if self.gpu_instanced_stroke.active:
                current_point = self.constrain_assistant_point(
                    self.screen_to_image(event.position())
                )
                self._queue_instanced_stroke_segment(
                    self.last_point, current_point, 1.0, 1.0
                )
                self.last_point = current_point
                self.update()
                event.accept()
                return

            image = (
                self.get_active_image()
            )

            if image is None:
                return

            current_point = self.constrain_assistant_point(
                self.screen_to_image(event.position())
            )

            if self.tools.current_tool in ("blur", "sharpen"):
                active_layer = self.get_active_layer()
                if active_layer is not None:
                    active_layer.image = self._apply_filter_segment(
                        image, self.last_point, current_point, 1.0, 1.0,
                        self.tools.current_tool == "sharpen",
                    )
            elif self._cpp_active():
                clone_mode = self.tools.current_tool == "clone_stamp"
                cpp_image = self._cpp_draw_segment(
                    image, self.last_point, current_point, 1.0, 1.0,
                    clone_source=self.clone_source if clone_mode else None,
                    clone_offset=self.clone_offset if clone_mode else None,
                    stabilize=True,
                )

                if cpp_image is not None:
                    active_layer = self.get_active_layer()
                    dirty_rect = self._brush_dirty_rect(self.last_point, current_point)
                    if active_layer is not None and getattr(active_layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    self.sync_gpu_layer(dirty_rect)
                else:
                    # Keep the current image untouched when the native dab
                    # fails; the release path will close the native stroke.
                    self._cpp_end_stroke()
            else:
                # Raster editing is unavailable without CreativeCore.
                self._cpp_end_stroke()

            self.last_point = (
                current_point
            )

        if self.drawing:
            self.update()
        else:
            radius = max(8.0, float(self.brush_settings.get("size", 10.0)) * self.zoom * 0.5 + 4.0)
            old_rect = QRectF(previous_cursor_position.x() - radius, previous_cursor_position.y() - radius, radius * 2, radius * 2)
            new_rect = QRectF(self.cursor_position.x() - radius, self.cursor_position.y() - radius, radius * 2, radius * 2)
            self.update(old_rect.united(new_rect).toAlignedRect())

        event.accept()

    def mouseReleaseEvent(
        self,
        event: QMouseEvent
    ) -> None:

        if self._ignore_tablet_synthetic_mouse(event):
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.bezier_dragging:
            self.bezier_dragging = False
            if self.bezier_stage == 2:
                self._commit_bezier_curve()
                self.bezier_stage = 0
            self.update()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.reference_drag_id is not None:
            self.reference_drag_id = None
            self.save_history()
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.text_drag_id is not None:
            self.text_drag_id = None
            self.save_history()
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # PAN
        # -----------------------------------------------------

        if (
            event.button()
            == Qt.MouseButton.MiddleButton
        ):

            self.panning = False

            self.update()

            event.accept()

            return

        if event.button() == Qt.MouseButton.LeftButton and self.tools.current_tool == "hand":
            self.panning = False
            self.update()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.view_dragging:
            self.view_dragging = False
            self.update()
            event.accept()
            return

        if (
            self.tools.current_tool == "zoom_view"
            and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
        ):
            event.accept()
            return

        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):

            if self.gradient_drawing:
                self.gradient_drawing = False
                self.gradient_original = None
                self.save_history()
                self.sync_gpu_layer()
                event.accept()
                return

            if self.crop_drawing:
                self.crop_current = self.screen_to_image(event.position())
                self.crop_drawing = False
                self.apply_crop()
                event.accept()
                return

            if self.shape_drawing:
                self.shape_drawing = False
                self.shape_original = None
                self.save_history()
                self.sync_gpu_layer()
                event.accept()
                return

            if self.selection_drawing:
                self._finish_selection_gesture()
                self.update()
                event.accept()
                return

            # -------------------------------------------------
            # DÉPLACEMENT
            # -------------------------------------------------

            if (
                self.tools.current_tool
                == "move"
                and self.tools.move_tool.is_active()
            ):

                self.tools.end_move()

                self.save_history()

                self.update()

                event.accept()

                return

            if self.selection_moving:
                self.selection_moving = False
                self.selection_move_original = None
                self.selection_move_original_mask = None
                self.save_history()
                self.sync_gpu_layer()
                event.accept()
                return

            # -------------------------------------------------
            # TRANSFORMATION
            # -------------------------------------------------

            if self.transforming:

                layer = (
                    self.get_active_layer()
                )

                if layer is not None:

                    if (
                        self.transform_handle
                        == "move"
                    ):

                        delta = (
                            self.transform_move_delta
                        )

                        self.apply_affine_to_layer(layer, TransformSpec(
                            translate_x=delta.x(), translate_y=delta.y()
                        ))

                    else:

                        self.apply_transform_to_layer(
                            layer
                        )

                self.transforming = False

                self.transform_handle = ""

                self.transform_scale_x = 1.0

                self.transform_scale_y = 1.0

                self.transform_original_scale_x = 1.0

                self.transform_original_scale_y = 1.0

                self.transform_move_delta = QPointF(
                    0,
                    0
                )

                self.save_history()

                self.update()

                event.accept()

                return

            # -------------------------------------------------
            # DESSIN
            # -------------------------------------------------

            if self.drawing:
                if self.gpu_instanced_stroke.active:
                    self.gpu_instanced_stroke.request_finish()
                else:
                    if self._cpp_active():
                        self._cpp_end_stroke()
                    self.commit_stroke_history()
                    self.canvas_brush_end_stroke()

            self.drawing = False
            self._assistant_angle = None

            self.update()

            event.accept()

    # =========================================================
    # ZOOM
    # =========================================================

    def wheelEvent(
        self,
        event: QWheelEvent
    ) -> None:

        delta = (
            event.angleDelta().y()
        )

        if delta == 0:
            return

        mouse_position = (
            event.position()
        )

        if self.tools.current_tool == "reference" and self.selected_reference_id is not None:
            item = next((ref for ref in self.document.reference_images
                         if ref.id == self.selected_reference_id), None)
            if item is not None:
                self.save_history()
                item.scale = max(0.05, min(10.0, item.scale * (1.1 if delta > 0 else 1.0 / 1.1)))
                self.save_history()
                self.update()
                event.accept()
                return

        self.zoom_at(mouse_position, 1.1 if delta > 0 else 1.0 / 1.1)

        event.accept()

    # =========================================================
    # TABLET XP-PEN
    # =========================================================

    def tabletEvent(
        self,
        event: QTabletEvent
    ) -> None:

        self._last_tablet_event_time = time.monotonic()

        self.setFocus()

        pressure_value = event.pressure() if self.tablet_pressure_enabled else 1.0
        current_tilt = (float(event.xTilt()), float(event.yTilt()))

        self.cursor_position = (
            event.position()
        )

        if event.type() == QTabletEvent.Type.TabletPress:
            locked_layer = self.get_active_layer()
            if locked_layer is not None and locked_layer.locked:
                non_raster_tools = {
                    "picker", "select_rectangle", "select_ellipse", "lasso",
                    "magic_wand", "reference", "text", "hand", "zoom_view",
                    "rotate_view",
                }
                source_pick = (self.tools.current_tool == "clone_stamp" and
                              bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                perspective_point = (self.assistant_mode == "perspective" and
                                     bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                if self.tools.current_tool not in non_raster_tools and not source_pick and not perspective_point:
                    event.accept()
                    return

        self.cursor_visible = True

        if self.tools.current_tool in self.tools.selection_tools.SHAPE_TOOLS:
            event_type = event.type()
            if event_type == QTabletEvent.Type.TabletPress:
                self._begin_selection_gesture(event.position(), event.modifiers())
            elif event_type == QTabletEvent.Type.TabletMove and self.selection_drawing:
                self._update_selection_gesture(event.position())
            elif event_type == QTabletEvent.Type.TabletRelease and self.selection_drawing:
                self._finish_selection_gesture()
            self.update()
            event.accept()
            return

        if (self.tools.current_tool == "magic_wand"
                and event.type() == QTabletEvent.Type.TabletPress):
            layer = self.get_active_layer()
            if layer is None:
                event.accept()
                return
            self._set_selection_operation(event.modifiers())
            self.begin_selection_history_action()
            try:
                candidate = self.tools.selection_tools.magic_wand(
                    layer.image,
                    self.screen_to_image(event.position()),
                    cpp_library=self.cpp_brush_library,
                )
                self.document.selection.combine(candidate, self.selection_operation)
            except Exception:
                self.cancel_history_action()
                raise
            self.commit_history_action()
            self.update()
            event.accept()
            return

        event_type = event.type()
        position = self.screen_to_image(event.position())
        if (self.tools.current_tool == "fill"
                and event_type == QTabletEvent.Type.TabletPress):
            layer = self.get_active_layer()
            if layer is None or layer.locked:
                event.accept()
                return
            color_values = self.brush_settings.snapshot()["color"]
            alpha_locked = bool(getattr(layer, "lock_alpha", False))
            fill_history_bounds = self._begin_fill_history_action(layer, position)
            alpha_snapshot = (self._clone_raster_native(layer.image) if alpha_locked and fill_history_bounds is None
                              else None)
            changed = self.tools.fill(
                layer.image, position,
                QColor(*[int(value) for value in color_values]),
            )
            if alpha_locked:
                restored = (self._restore_alpha_from_history(
                    layer.image, layer, fill_history_bounds)
                    if fill_history_bounds is not None else
                    self._restore_alpha_from(layer.image, alpha_snapshot))
                if restored is not None:
                    layer.image = restored
            if changed is not None and not changed.isEmpty():
                self.sync_gpu_layer(changed)
            self._finish_fill_history_action(layer, fill_history_bounds, changed)
            self.update()
            event.accept()
            return

        if self.tools.current_tool == "gradient":
            if event_type == QTabletEvent.Type.TabletPress:
                layer = self.get_active_layer()
                if layer is None:
                    return
                self.save_history()
                self.gradient_drawing = True
                self.gradient_start = position
                self.gradient_original = self._clone_raster_native(layer.image)
                if getattr(layer, "lock_alpha", False):
                    self._alpha_lock_snapshot = layer.image.convertToFormat(
                        QImage.Format.Format_RGBA8888
                    )
            elif event_type == QTabletEvent.Type.TabletMove and self.gradient_drawing:
                layer = self.get_active_layer()
                if layer is not None and self.gradient_original is not None:
                    layer.image = self._clone_raster_native(self.gradient_original)
                    color_values = self.brush_settings.snapshot()["color"]
                    self.tools.gradient(
                        layer.image, self.gradient_start, position,
                        QColor(*[int(value) for value in color_values]),
                    )
                    if getattr(layer, "lock_alpha", False):
                        restored = self._restore_alpha_from(layer.image, self.gradient_original)
                        if restored is not None:
                            layer.image = restored
                    self.sync_gpu_layer()
            elif event_type == QTabletEvent.Type.TabletRelease and self.gradient_drawing:
                self.gradient_drawing = False
                self.gradient_original = None
                self.save_history()
                self.sync_gpu_layer()
            self.update()
            event.accept()
            return

        if self.tools.current_tool == "crop":
            if event_type == QTabletEvent.Type.TabletPress:
                self.crop_drawing = True
                self.crop_start = position
                self.crop_current = position
                self.save_history()
            elif event_type == QTabletEvent.Type.TabletMove and self.crop_drawing:
                self.crop_current = position
            elif event_type == QTabletEvent.Type.TabletRelease and self.crop_drawing:
                self.crop_current = position
                self.crop_drawing = False
                self.apply_crop()
            self.update()
            event.accept()
            return

        if self.tools.current_tool in self.tools.shape_tools.SUPPORTED:
            if event_type == QTabletEvent.Type.TabletPress:
                layer = self.get_active_layer()
                if layer is None:
                    return
                self.save_history()
                self.shape_drawing = True
                self.shape_start = position
                self.shape_original = self._clone_raster_native(layer.image)
                if getattr(layer, "lock_alpha", False):
                    self._alpha_lock_snapshot = layer.image.convertToFormat(
                        QImage.Format.Format_RGBA8888
                    )
            elif event_type == QTabletEvent.Type.TabletMove and self.shape_drawing:
                self._preview_brush_shape(position)
            elif event_type == QTabletEvent.Type.TabletRelease and self.shape_drawing:
                self.shape_drawing = False
                self.shape_original = None
                self.save_history()
                self.sync_gpu_layer()
            self.update()
            event.accept()
            return

        if self.tools.current_tool == "reference":
            if event.type() == QTabletEvent.Type.TabletPress:
                point = self.screen_to_image(event.position())
                hit = next((item for item in reversed(self.document.reference_images)
                            if QRectF(item.position.x(), item.position.y(),
                                      item.image.width() * item.scale,
                                      item.image.height() * item.scale).contains(QPointF(point))), None)
                self.selected_reference_id = hit.id if hit is not None else None
                self.reference_drag_id = hit.id if hit is not None else None
                if hit is not None:
                    self.save_history()
                    self.reference_drag_anchor = QPointF(point) - hit.position
            elif event.type() == QTabletEvent.Type.TabletMove and self.reference_drag_id is not None:
                item = next((ref for ref in self.document.reference_images
                             if ref.id == self.reference_drag_id), None)
                if item is not None:
                    item.position = QPointF(self.screen_to_image(event.position())) - self.reference_drag_anchor
            elif event.type() == QTabletEvent.Type.TabletRelease and self.reference_drag_id is not None:
                self.reference_drag_id = None
                self.save_history()
            self.update()
            event.accept()
            return

        if self.tools.current_tool == "text" and event.type() == QTabletEvent.Type.TabletPress:
            point = self.screen_to_image(event.position())
            selected = self._text_item_at(QPointF(point))
            self.selected_text_id = selected.id if selected is not None else None
            if selected is not None and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.text_drag_id = selected.id
                self.text_drag_anchor = QPointF(point) - selected.position
                self.save_history()
                event.accept()
                return
            self._edit_text_at(QPointF(point))
            event.accept()
            return

        if self.tools.current_tool == "text" and self.text_drag_id is not None:
            if event.type() == QTabletEvent.Type.TabletMove:
                item = next((obj for obj in self.document.text_objects if obj.id == self.text_drag_id), None)
                if item is not None:
                    item.position = QPointF(self.screen_to_image(event.position())) - self.text_drag_anchor
            elif event.type() == QTabletEvent.Type.TabletRelease:
                self.text_drag_id = None
                self.save_history()
            self.update()
            event.accept()
            return

        if self.tools.current_tool == "bezier":
            point = QPointF(self.screen_to_image(event.position()))
            if event.type() == QTabletEvent.Type.TabletPress:
                if self.bezier_stage == 0:
                    self.bezier_start = point
                    self.bezier_control1 = point
                    self.bezier_stage = 1
                else:
                    self.bezier_end = point
                    self.bezier_control2 = point
                    self.bezier_stage = 2
                self.bezier_dragging = True
            elif event.type() == QTabletEvent.Type.TabletMove and self.bezier_dragging:
                if self.bezier_stage == 1:
                    self.bezier_control1 = point
                else:
                    self.bezier_control2 = point
            elif event.type() == QTabletEvent.Type.TabletRelease and self.bezier_dragging:
                self.bezier_dragging = False
                if self.bezier_stage == 2:
                    self._commit_bezier_curve()
                    self.bezier_stage = 0
            self.update()
            event.accept()
            return

        if (self.tools.current_tool == "clone_stamp" and
                event.type() == QTabletEvent.Type.TabletPress and
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._set_clone_source(self.screen_to_image(event.position()))
            event.accept()
            return

        if (
            self.assistant_mode == "perspective"
            and event.type() == QTabletEvent.Type.TabletPress
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.set_vanishing_point(self.screen_to_image(event.position()))
            event.accept()
            return

        # -----------------------------------------------------
        # ESPACE = PAN
        # -----------------------------------------------------

        if self.space_pressed or self.tools.current_tool == "hand":

            if (
                event.type()
                == QTabletEvent.Type.TabletPress
            ):

                self.panning = True

                self.pan_start = (
                    event.position()
                )

                self.offset_start = (
                    self.offset
                )

            elif (
                event.type()
                == QTabletEvent.Type.TabletMove
            ):

                if self.panning:

                    movement = (
                        event.position()
                        - self.pan_start
                    )

                    self.offset = (
                        self.offset_start
                        + movement
                    )

            elif (
                event.type()
                == QTabletEvent.Type.TabletRelease
            ):

                self.panning = False

            self.update()

            event.accept()

            return

        if self.tools.current_tool == "zoom_view" and event.type() == QTabletEvent.Type.TabletPress:
            factor = 0.8 if event.button() == Qt.MouseButton.RightButton else 1.25
            self.zoom_at(event.position(), factor)
            event.accept()
            return

        if self.tools.current_tool == "rotate_view":
            center = QPointF(self.width() * 0.5, self.height() * 0.5)
            delta = event.position() - center
            if event.type() == QTabletEvent.Type.TabletPress:
                self.view_dragging = True
                self.view_drag_angle = math.atan2(delta.y(), delta.x())
                self.view_drag_rotation = self.view_rotation
            elif event.type() == QTabletEvent.Type.TabletMove and self.view_dragging:
                angle = math.atan2(delta.y(), delta.x())
                self.view_rotation = (self.view_drag_rotation + math.degrees(angle - self.view_drag_angle)) % 360.0
            elif event.type() == QTabletEvent.Type.TabletRelease:
                self.view_dragging = False
            self.update()
            event.accept()
            return

        # -----------------------------------------------------
        # OUTIL DÉPLACER
        # -----------------------------------------------------

        if self.tools.current_tool == "move":

            position = (
                self.screen_to_image(
                    event.position()
                )
            )

            if (
                event.type()
                == QTabletEvent.Type.TabletPress
            ):

                layer = (
                    self.get_active_layer()
                )

                if layer is None:
                    return

                self.save_history()

                self.tools.begin_move(
                    position
                )

            elif (
                event.type()
                == QTabletEvent.Type.TabletMove
            ):

                layer = (
                    self.get_active_layer()
                )

                if layer is None:
                    return

                self.tools.move(
                    layer.image,
                    position
                )

            elif (
                event.type()
                == QTabletEvent.Type.TabletRelease
            ):

                self.tools.end_move()

                self.save_history()

            self.update()

            event.accept()

            return

        # -----------------------------------------------------
        # DESSIN XP-PEN
        # -----------------------------------------------------

        position = self.screen_to_image(event.position())
        if self.tools.current_tool in ("brush", "eraser", "smudge", "clone_stamp", "blur", "sharpen"):
            position = self.constrain_assistant_point(
                position, begin=event.type() == QTabletEvent.Type.TabletPress
            )

        if self.tools.current_tool == "picker":
            if event.type() == QTabletEvent.Type.TabletPress:
                self.sample_composite_color(position)
            event.accept()
            return

        if self.tools.current_tool not in ("brush", "eraser", "smudge", "clone_stamp", "blur", "sharpen"):
            super().tabletEvent(event)
            return

        if (
            event.type()
            == QTabletEvent.Type.TabletPress
        ):

            layer = (
                self.get_active_layer()
            )

            if layer is None:
                return

            self.last_point = position
            if self.tools.current_tool == "clone_stamp" and not self._begin_clone_sampling(layer, position):
                event.accept()
                return

            self.begin_stroke_history()
            self.canvas_brush_begin_stroke()
            self.drawing = True
            self._last_tablet_tilt = current_tilt

            pressure = float(pressure_value)
            # Preserve the previous sample until the segment has been sent to
            # CreativeCore. Updating it at the beginning of tabletEvent would
            # make every move look like a constant-pressure segment.
            self.tools.brush.pressure = pressure

            if self._try_begin_instanced_stroke(layer, position, pressure,
                                                self.tools.current_tool):
                self.update()
                event.accept()
                return

            if self.tools.current_tool in ("blur", "sharpen"):
                layer.image = self._apply_filter_segment(
                    layer.image, position, position, pressure, pressure,
                    self.tools.current_tool == "sharpen",
                )
                event.accept()
                return

            if self._cpp_active():
                if self.tools.current_tool == "clone_stamp":
                    cpp_image = self._cpp_begin_clone_stroke(layer.image, position, pressure)
                else:
                    cpp_image = self._cpp_begin_stroke(layer.image, position, pressure)

                if cpp_image is not None:
                    dirty_rect = self._brush_dirty_rect(position, position)
                    if getattr(layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    layer.adopt_image_cache(cpp_image)
                    self.sync_gpu_layer(dirty_rect)
                else:
                    self._cpp_end_stroke()
            else:
                self._cpp_end_stroke()

            self.update()

        elif (
            event.type()
            == QTabletEvent.Type.TabletMove
        ):

            if not self.drawing:
                return

            image = (
                self.get_active_image()
            )

            if image is None:
                return

            start_pressure, pressure = self._tablet_pressure_pair(pressure_value)

            if self.gpu_instanced_stroke.active:
                self._queue_instanced_stroke_segment(
                    self.last_point, position, start_pressure, pressure
                )
                self.tools.brush.pressure = pressure
                self.last_point = position
                self._last_tablet_tilt = current_tilt
                self.update()
                event.accept()
                return

            if self.tools.current_tool in ("blur", "sharpen"):
                active_layer = self.get_active_layer()
                if active_layer is not None:
                    active_layer.image = self._apply_filter_segment(
                        image, self.last_point, position,
                        start_pressure, pressure,
                        self.tools.current_tool == "sharpen",
                    )
            elif self._cpp_active():
                cpp_image = self._cpp_draw_segment(
                    image,
                    self.last_point,
                    position,
                    start_pressure,
                    pressure,
                    self._last_tablet_tilt,
                    current_tilt,
                    clone_source=self.clone_source if self.tools.current_tool == "clone_stamp" else None,
                    clone_offset=self.clone_offset if self.tools.current_tool == "clone_stamp" else None,
                    stabilize=True,
                )

                if cpp_image is not None:
                    active_layer = self.get_active_layer()
                    dirty_rect = self._brush_dirty_rect(self.last_point, position)
                    if active_layer is not None and getattr(active_layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    self.sync_gpu_layer(dirty_rect)
                else:
                    self._cpp_end_stroke()
            else:
                self._cpp_end_stroke()

            self.tools.brush.pressure = pressure

            self.last_point = position
            self._last_tablet_tilt = current_tilt

            self.update()

        elif (
            event.type()
            == QTabletEvent.Type.TabletRelease
        ):

            if self.drawing:
                if self.gpu_instanced_stroke.active:
                    self.gpu_instanced_stroke.request_finish()
                else:
                    if self._cpp_active():
                        self._cpp_end_stroke()
                    self.commit_stroke_history()
                    self.canvas_brush_end_stroke()

            self.drawing = False
            self._assistant_angle = None

            self.update()

        event.accept()

    def _ignore_tablet_synthetic_mouse(self, event: QMouseEvent) -> bool:
        """Drop duplicate mouse events Qt synthesizes immediately after tablet input."""
        if not self.ignore_synthetic_mouse_after_tablet:
            return False
        if event.source() == Qt.MouseEventSource.MouseEventNotSynthesized:
            return False
        return time.monotonic() - self._last_tablet_event_time <= 0.12

    def _tablet_pressure_pair(self, current_pressure: float) -> tuple[float, float]:
        """Return the previous/current sample and advance the tablet state."""
        start = max(0.0, min(1.0, float(self.tools.brush.pressure)))
        end = max(0.0, min(1.0, float(current_pressure)))
        self.tools.brush.pressure = end
        return start, end

    # =========================================================
    # COORDONNÉES
    # =========================================================

    def screen_to_image(
        self,
        position: QPointF
    ) -> QPoint:
        image_position = self.screen_to_image_f(position)
        return QPoint(round(image_position.x()), round(image_position.y()))

    def screen_to_image_f(self, position: QPointF) -> QPointF:
        untransformed = self._view_transform_point(position, inverse=True)
        return (untransformed - self.offset) / self.zoom
