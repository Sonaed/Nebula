from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtGui import QOpenGLContext
import ctypes
import base64
import math
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

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
from CANVAS.gpu_tile_compositor import GPUTileCompositor
from CANVAS.live_stroke_preview import LiveStrokePreview

# The shader paths use the small native-GL adapters in their respective
# modules.  They deliberately do not use PySide's QOpenGLFunctions wrapper:
# that wrapper is unstable on the currently supported Python/Qt combination.
GPU_SHADER_COMPOSITING_ENABLED = True
GPU_SHADER_STROKES_ENABLED = True

from PySide6.QtCore import (
    Qt,
    Signal,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QLineF,
    QEvent,
    QSettings,
    QTimer,
)

from TOOLS.tool_manager import ToolManager
from TOOLS.cpp_brush_presets import CanvasBrushPresetController
from TOOLS.brush_settings_state import BrushSettingsState, DEFAULT_BRUSH_SETTINGS
from TOOLS.brush_preset_manager import BrushPresetManager
from TOOLS.transform_tool import TransformSpec, PerspectiveSpec, LiquifyStroke, WarpControl
from TOOLS.crop_tool import CropTool
from DOCUMENTS.document import Document
from DOCUMENTS.canvas_objects import EditableText, ReferenceImage
from DOCUMENTS.layer import Layer
from DOCUMENTS.selection import SelectionOperation
from CANVAS.free_transform import FreeTransformSession, CURSORS as FREE_TRANSFORM_CURSORS
from CORE.native_bridge import native_selection_bounds
from DOCUMENTS.blend_modes import (has_non_normal, composite_layers, apply_clipped_adjustment,
                                   adjustment_coverage, hide_clipped_over_hidden_base,
                                   adjustment_entry, resolve_stack)
from DOCUMENTS.adjustments import (AdjustmentLayerSpec, CurvesAdjustment,
                                   LevelsAdjustment, HueSaturationAdjustment,
                                   ExposureAdjustment, VibranceAdjustment,
                                   ColorBalanceAdjustment, ParametricCurvesAdjustment,
                                   SelectiveColorAdjustment, LuminosityMaskAdjustment,
                                   apply_adjustment)
from UI.qt_blend_modes import composition_mode
from CANVAS.tile_history import TileHistory
from CORE.projection_worker import ProjectionWorker, ProjectionLayer
from CORE.tile_cache_manager import TileCacheManager
from CORE.native_bridge import (clone_image_native, draw_text_native,
                                apply_alpha_mask_native, fill_image_native,
                                normalize_alpha_mask_native,
                                filter_brush_segment,
                                load_creative_core, restore_image_alpha_rect,
                                restore_image_alpha_tile)
from DOCUMENTS.tile_store import TileStore, TILE_SIZE
from UI.theme.palette import COLORS
from CANVAS.view_state import transform_point, fit_zoom
from CANVAS.canvas_assistants import AssistantManager


class Canvas(QOpenGLWidget):

    color_sampled = Signal(QColor)
    color_picked = Signal(QColor)          # emitted at end of brush stroke
    brush_settings_changed = Signal(dict)
    tool_changed = Signal(str)
    canvas_only_changed = Signal(bool)
    view_flip_changed = Signal(bool, bool)
    symmetry_changed = Signal(bool, bool)
    history_restored = Signal()
    history_operation_deferred = Signal(str)
    performance_warning = Signal(str)
    # Emitted with the painted-on layer's id whenever a stroke finishes.
    # LayersDock.invalidate_thumb_cache() existed already (its own docstring
    # says "called by the canvas after a brush stroke ... without this,
    # thumbnails stay frozen even when painting") but nothing ever actually
    # called it - so no layer thumbnail, mask thumbnails included, ever
    # refreshed from painting. Application connects this to invalidate the
    # cache and trigger a layers-panel refresh.
    layer_thumbnail_dirty = Signal(str)
    async_brush_patch = Signal(int, int, int, int, object, bool, str)
    assistant_build_step = Signal(int, int)   # (handles_placed, handles_needed)

    def __init__(
        self
    ) -> None:

        super().__init__()

        # Bounded in-memory telemetry: no I/O is performed while drawing.
        self._pending_input_ns: int | None = None
        self._input_to_paint_ms = deque(maxlen=240)
        self._brush_segment_ms = deque(maxlen=240)

        self.document: Document = Document(
            800,
            600
        )
        self.projection_store = TileStore(self.document.width, self.document.height, TILE_SIZE)
        # The native projection remains the authoritative compositor for
        # complex documents. This adapter lets its ready tiles stay resident
        # as GPU textures for pan/zoom instead of sending the whole viewport
        # through QPainter's CPU path.
        self._gpu_projection_layer = SimpleNamespace(
            tile_store=self.projection_store, visible=True, opacity=1.0,
            blend_mode="normal", blend_parameters={}, clipping=False,
        )
        self._projection_tile_signatures: dict[tuple[int, int], tuple] = {}
        self._projection_tile_generation: dict[tuple[int, int], int] = {}
        self._projection_ready_tiles: set[tuple[int, int]] = set()
        self._projection_pending_images = {}
        self._projection_publish_keys = set()
        self._projection_waiting_visible = set()
        self._projection_display_ready = False
        self._editing_alpha_mask_layer_id: str | None = None
        self._editing_alpha_mask_image: QImage | None = None
        self._async_brush_handle = None
        self._async_brush_layer_id: str | None = None
        self._async_symmetry_handles: list = []   # [(async_handle, tilt_sign_x, tilt_sign_y), …]
        self._async_stroke_pending: int = 0        # workers not yet complete
        # Bumped every _begin_async_brush() call. A worker's `receive`
        # callback closes over the generation it was started with, so a
        # patch that arrives from a worker whose stroke has since been
        # abandoned (see _begin_async_brush's cancel-stale-handle guard) is
        # dropped instead of being misapplied to whatever stroke is current.
        self._async_stroke_generation: int = 0
        # Keeps the async stroke's source QImage (and the raw ctypes view
        # over its buffer handed to the native worker(s)) alive for as long
        # as any of those workers could still be reading/writing it - see
        # _begin_async_brush for why this is load-bearing, not just tidiness.
        self._async_brush_source_image = None
        self._async_brush_source_raw = None
        self.async_brush_patch.connect(self._apply_async_brush_patch)
        # Retain one tile beyond the visible viewport.  Panning then presents
        # already-composed pixels instead of rebuilding every layer as soon
        # as a tile crosses the viewport edge.  The store remains sparse and
        # the margin is bounded, so this cannot turn a large document into a
        # full-document projection cache.
        self._projection_prefetch_margin_tiles = 1
        self.tile_cache_manager = TileCacheManager()
        # View offset is initialized later with the rest of the navigation
        # state; origin is the correct initial prediction anchor.
        self._last_view_offset = QPointF()
        self._tile_loading_since: dict[tuple[int, int], float] = {}
        self._projection_cache_stats = {
            "visible_hits": 0, "visible_misses": 0,
            "prefetch_hits": 0, "prefetch_misses": 0,
        }

        background = (
            self.document.get_active_layer()
        )

        if background is not None:

            background.name = "Arrière-plan"

            if not fill_image_native(background.image, QColor(255, 255, 255, 255)):
                raise RuntimeError("CreativeCore a refusé le remplissage de l’arrière-plan")
            background.mark_image_cache_dirty()

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
        self._preferences = preferences
        self.use_gpu = preferences.value("performance/use_gpu", True, bool)
        self.zoom_behavior = preferences.value("canvas/zoom_behavior", "At cursor", str)
        self.canvas_background = preferences.value("canvas/background", "Checkerboard", str)
        self.show_brush_cursor_preview = preferences.value("brush/show_cursor_preview", True, bool)
        self.live_stroke_preview = LiveStrokePreview(self)
        self.tablet_pressure_enabled = preferences.value("tablet/pressure", True, bool)
        self.ignore_synthetic_mouse_after_tablet = preferences.value(
            "tablet/ignore_mouse_after_tablet", True, bool
        )
        self._last_tablet_event_time = 0.0
        self.right_click_color_picker = preferences.value(
            "input/right_click_color_picker", True, bool
        )

        # Drawing assistants (ruler, ellipse, perspective …)
        self.assistants = AssistantManager()

        # Popup palette — injected by application.py after construction
        self.popup_palette = None

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
        # Mode chosen in the options bar (New/Add/Subtract/Intersect);
        # Shift/Alt at the start of a gesture override it, like Photoshop.
        self.selection_base_operation = SelectionOperation.REPLACE
        self._selection_anchor: QPointF | None = None
        self._selection_gesture_modifiers = Qt.KeyboardModifier.NoModifier
        self.free_transform: FreeTransformSession | None = None

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
        self.gpu_tile_compositor = GPUTileCompositor(self.gpu_renderer)
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
        preferences = self._preferences
        pressure_enabled = preferences.value("tablet/pressure", True, bool)
        settings["pressureSize"] = bool(settings.get("pressureSize", True)) and pressure_enabled and preferences.value("tablet/pressure_size", True, bool)
        settings["pressureOpacity"] = bool(settings.get("pressureOpacity", False)) and pressure_enabled and preferences.value("tablet/pressure_opacity", True, bool)
        settings["pressureFlow"] = bool(settings.get("pressureFlow", False)) and pressure_enabled
        brush = self.tools.brush
        # Presets may explicitly opt into crisp pixel-art dabs.  The global
        # preference remains the default for ordinary brushes.
        brush.antialiasing = bool(settings.get("antialiasing", preferences.value("canvas/antialias", True, bool)))
        brush.smoothing = max(0.0, min(1.0, float(settings.get("stabilization", 0.0))))
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

    def apply_sampled_brush_color(self, color: QColor) -> None:
        """Applique une couleur prélevée au brush, pas seulement au picker.

        Le picker possède temporairement son propre profil d'outil. Sans cette
        synchronisation, `_tool_changed("brush")` rechargeait l'ancienne
        couleur du brush dès que l'utilisateur quittait la pipette.
        """
        rgba = [color.red(), color.green(), color.blue(), color.alpha()]
        self.set_brush_setting("color", rgba)
        if getattr(self, "_alt_return_tool", None) is not None:
            self._alt_picker_sampled = True
        preferences = QSettings("CreativeSystem", "CreativeSystem")
        preferences.setValue(
            "brush/tool_settings/brush",
            self.brush_settings.snapshot(),
        )

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
        if getattr(self, "free_transform", None) is not None and _name != "transform":
            self.commit_free_transform()
        if _name == "transform" and getattr(self, "free_transform", None) is None:
            self.start_free_transform()
        if _name != "transform":
            self.unsetCursor()
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
            self.apply_sampled_brush_color(color)
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
        self.apply_sampled_brush_color(color)
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
        selection_before = self._selection_edit_snapshot(image, dirty)
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
        image = self._restore_selection_after_edit(image, selection_before, dirty)
        image = self._restore_locked_alpha(image, dirty) or image
        if layer is not None:
            # `layer.image = image` (the compatibility setter) writes through
            # to EVERY tile of the document, not just the ones this segment
            # touched — on a big canvas that's the same "redo the whole
            # document on every dab" cost the mask-painting bug had, except
            # here every caller below then repeated the same full write a
            # second time via its own `layer.image = ...`/`active_layer.image
            # = ...` assignment. Commit only the dirty rect, like every other
            # brush tool does, and let callers stop re-assigning.
            layer.tile_store.write_image(image, dirty)
            layer.discard_image_cache()
            self.tile_history.mark_dirty(layer, dirty)
        if getattr(self, "gpu_ready", False) and layer is not None:
            self.gpu_renderer.mark_layer_dirty(layer, dirty)
        self._repaint_brush_dirty_rect(dirty)
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
            # `getattr(..., default)` only falls back when the attribute is
            # MISSING - _cpp_end_stroke() deliberately sets
            # _cpp_smoothed_point to None when a stroke ends (line ~1036),
            # so the attribute is always present once a stroke has happened
            # once. If a TabletMove with stabilize=True reaches here while
            # self.drawing is still True but _cpp_smoothed_point is None -
            # e.g. the previous move's _cpp_draw_segment returned None
            # (bad QImage buffer, disabled brush, ...) and fell through to
            # the `self._cpp_end_stroke()` in tabletEvent's TabletMove
            # branch without a Release event in between - getattr(...)
            # happily returns that None instead of the QPointF default,
            # and `previous.x()` below crashes the tablet event handler.
            previous = getattr(self, "_cpp_smoothed_point", None)
            if previous is None:
                previous = QPointF(start)
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
            dirty = self._brush_dirty_rect(start, end)
            if self._editing_alpha_mask_layer_id == layer.id:
                self.tile_history.capture_mask_before(layer, dirty)
            else:
                self.tile_history.capture_before(layer, dirty)

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
            segment_dirty = self._brush_dirty_rect(segment_start, segment_end)
            # A selection is an edit constraint, not merely an overlay. Keep
            # a bounded pre-dab snapshot so the native brush can remain the
            # fast rasterizer while its result is composited back through the
            # selection alpha (including feathered edges).
            selection_before = self._selection_edit_snapshot(image, segment_dirty)
            if layer is not None:
                if self._editing_alpha_mask_layer_id == layer.id:
                    self.tile_history.capture_mask_before(layer, segment_dirty)
                else:
                    self.tile_history.capture_before(layer, segment_dirty)
            offset = QPoint(clone_offset) if clone_offset is not None else QPoint()
            if segment_start.x() != start.x():
                offset.setX(-offset.x())
            if segment_start.y() != start.y():
                offset.setY(-offset.y())
            started_ns = time.perf_counter_ns()
            image = self._cpp_draw_segment_once(
                image, segment_start, segment_end,
                start_pressure, end_pressure, tilt_start, tilt_end,
                clone_source, offset,
            )
            self._brush_segment_ms.append(
                (time.perf_counter_ns() - started_ns) / 1_000_000.0
            )
            if image is None:
                return None
            image = self._restore_selection_after_edit(image, selection_before, segment_dirty)
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

    def _can_use_async_brush(self, layer) -> bool:
        return (self._cpp_active() and layer is not None and self.use_gpu
                and self.tools.current_tool in ("brush", "eraser", "smudge")
                and not getattr(layer, "lock_alpha", False)
                and self._editing_alpha_mask_layer_id != layer.id
                and self.document.selection.is_empty())

    def _begin_async_brush(self, layer, position: QPoint, pressure: float) -> bool:
        # A stylus stroke's TabletRelease only *requests* the worker to wrap
        # up (cs_brush_async_finish is non-blocking) - the worker actually
        # finishes, and gets destroyed/joined, later when its final patch
        # reaches _apply_async_brush_patch on the UI thread. A fast
        # press-lift-press (or a click that lands before that queued signal
        # is processed) used to reach this point with the previous stroke's
        # handle still live: it got silently overwritten below, orphaning
        # that worker. It kept running on its own thread, and its late
        # patches - still matched by _apply_async_brush_patch on layer id
        # alone - landed on top of the new stroke's pixels as a hard-edged
        # block, and its eventual completion decremented the *new* stroke's
        # _async_stroke_pending counter, sometimes cancelling it outright.
        #
        # The generation MUST be bumped before we touch the stale handle at
        # all, not after cancelling it. cs_brush_async_destroy() deletes the
        # native worker synchronously, which joins its thread - and that
        # worker can still be mid-way through a batch it already popped off
        # its queue when cancel() is requested (cancel only stops *future*
        # batches). That in-flight batch finishes and calls back into
        # `receive` from the worker's own thread while our join blocks this
        # one. Bumping the generation first means that straggler always sees
        # a mismatch the instant it fires, no matter how the join is
        # scheduled relative to it; bumping it after (as this used to) left
        # a real window where that exact callback still read the old,
        # matching generation and slipped through.
        self._async_stroke_generation += 1
        generation = self._async_stroke_generation

        if self._async_brush_handle is not None:
            self._cancel_async_brush()

        image = layer.image.convertToFormat(QImage.Format.Format_RGBA8888)
        self._sync_cpp_brush()
        lib = self.cpp_brush_library
        lib.cs_brush_begin_stroke(
            self.cpp_brush, float(position.x()), float(position.y()), float(pressure))
        raw = (ctypes.c_uint8 * image.sizeInBytes()).from_buffer(image.bits())
        # `raw` is a zero-copy view over `image`'s own pixel buffer, and the
        # QImage handed to cs_brush_async_start() (and to every symmetry
        # clone below) is itself constructed the same way on the C++ side -
        # a non-owning wrapper around this exact memory (BrushAsyncWorker
        # keeps only a lambda that returns this QImage by value, which for a
        # QImage built over external memory is still the SAME buffer, not a
        # deep copy). Both `image` and `raw` were local variables with
        # nothing else referencing them, so the instant this method returned
        # they became eligible for garbage collection - while the worker
        # thread(s) kept reading and writing that exact memory for the rest
        # of the stroke. Whenever the allocator actually reclaimed it before
        # the stroke finished, the worker was compositing into freed memory:
        # a real, silent use-after-free, and a much better fit for what was
        # actually observed (clean, well-formed strokes in a color that was
        # never selected, changing shape between runs) than a torn/raced
        # patch would be. Pin both for the async brush's own lifetime -
        # cleared in _cancel_async_brush() once every worker that could still
        # be touching this memory has been joined.
        self._async_brush_source_image = image
        self._async_brush_source_raw = raw
        callback_type = lib._cs_brush_async_callback_type

        def receive(_id, x, y, width, height, pixels, stride, complete, error, _user):
            # Belt-and-suspenders on top of the cancel-before-begin guard
            # above: a callback already queued by the C++ side before that
            # cancel took effect can still arrive here for an abandoned
            # stroke. Drop it rather than let it touch the current stroke's
            # pixels or its pending-worker count.
            if generation != self._async_stroke_generation:
                return
            message = error.decode("utf-8", "replace") if error else ""
            patch = QImage()
            if pixels and width > 0 and height > 0:
                patch = QImage(
                    (ctypes.c_uint8 * (stride * height)).from_address(
                        ctypes.addressof(pixels.contents)),
                    width, height, stride, QImage.Format.Format_RGBA8888).copy()
            self.async_brush_patch.emit(
                int(x), int(y), int(width), int(height), patch, bool(complete), message)

        self._async_brush_callback = callback_type(receive)
        stroke_id = int(time.time_ns())
        handle = lib.cs_brush_async_start(
            self.cpp_brush, raw,
            image.width(), image.height(), image.bytesPerLine(),
            stroke_id, self._async_brush_callback, None)
        if not handle:
            return False
        self._async_brush_handle = handle
        self._async_brush_layer_id = layer.id

        # Symmetry: create one mirrored worker per active axis so that all
        # mirror strokes paint in the same background thread, without
        # touching the UI thread.  Each clone is destroyed immediately after
        # cs_brush_async_start because the worker keeps its own copy.
        self._async_symmetry_handles = []
        cx = self.document.width - 1
        cy = self.document.height - 1
        sym_axes: list[tuple[float, float, float, float]] = []
        if self.symmetry_horizontal:
            sym_axes.append((float(cx - position.x()), float(position.y()), -1.0, 1.0))
        if self.symmetry_vertical:
            sym_axes.append((float(position.x()), float(cy - position.y()), 1.0, -1.0))
        if self.symmetry_horizontal and self.symmetry_vertical:
            sym_axes.append((float(cx - position.x()), float(cy - position.y()), -1.0, -1.0))

        for idx, (mx, my, tsx, tsy) in enumerate(sym_axes):
            clone = lib.cs_brush_clone(self.cpp_brush)
            if not clone:
                continue
            lib.cs_brush_begin_stroke(clone, mx, my, float(pressure))
            sym_handle = lib.cs_brush_async_start(
                clone, raw,
                image.width(), image.height(), image.bytesPerLine(),
                stroke_id + idx + 1, self._async_brush_callback, None)
            lib.cs_brush_destroy(clone)   # worker owns its own engine copy
            if sym_handle:
                self._async_symmetry_handles.append((sym_handle, tsx, tsy))

        # Total workers to wait for before committing history
        self._async_stroke_pending = 1 + len(self._async_symmetry_handles)
        return self._queue_async_brush(position, position, pressure, pressure, (0.0, 0.0), (0.0, 0.0))

    def _queue_async_brush(self, start, end, p0, p1, tilt0, tilt1) -> bool:
        h = self._async_brush_handle
        if not h:
            return False
        lib = self.cpp_brush_library
        ok = bool(lib.cs_brush_async_submit(
            h,
            float(start.x()), float(start.y()), float(p0),
            float(tilt0[0]), float(tilt0[1]),
            float(end.x()), float(end.y()), float(p1),
            float(tilt1[0]), float(tilt1[1])))
        # Submit mirrored segment to each symmetric worker
        cx = self.document.width - 1
        cy = self.document.height - 1
        for sym_handle, tsx, tsy in self._async_symmetry_handles:
            sx = float(cx - start.x()) if tsx < 0 else float(start.x())
            sy = float(cy - start.y()) if tsy < 0 else float(start.y())
            ex = float(cx - end.x()) if tsx < 0 else float(end.x())
            ey = float(cy - end.y()) if tsy < 0 else float(end.y())
            lib.cs_brush_async_submit(
                sym_handle,
                sx, sy, float(p0), float(tilt0[0]) * tsx, float(tilt0[1]) * tsy,
                ex, ey, float(p1), float(tilt1[0]) * tsx, float(tilt1[1]) * tsy)
        return ok

    def _cancel_async_brush(self) -> None:
        """Stop a pending native stroke before its document can disappear.

        The worker owns a snapshot and may still call back after a document
        switch or shutdown.  Joining it here prevents such a late patch from
        being applied to the next document.  All symmetric workers are stopped
        and destroyed alongside the primary worker.
        """
        lib = self.cpp_brush_library
        handle = getattr(self, "_async_brush_handle", None)
        if handle:
            try:
                lib.cs_brush_async_cancel(handle)
                lib.cs_brush_async_destroy(handle)
            except Exception:
                pass
        for sym_handle, _tsx, _tsy in getattr(self, "_async_symmetry_handles", []):
            try:
                lib.cs_brush_async_cancel(sym_handle)
                lib.cs_brush_async_destroy(sym_handle)
            except Exception:
                pass
        self._async_brush_handle = None
        self._async_symmetry_handles = []
        self._async_stroke_pending = 0
        self._async_brush_layer_id = None
        self._async_brush_callback = None
        # Safe to drop now: every worker that could still be reading/writing
        # this buffer (the primary handle and every symmetry clone) has just
        # been destroyed above, which joins its thread first.
        self._async_brush_source_image = None
        self._async_brush_source_raw = None

    def _apply_async_brush_patch(self, x, y, width, height, patch, complete, error) -> None:
        layer = self.get_active_layer()
        if layer is None or layer.id != self._async_brush_layer_id:
            return
        if error:
            self._cancel_async_brush()
            self.cancel_history_action()
            self.canvas_brush_end_stroke()
            return
        if width and height and not patch.isNull():
            rect = QRect(x, y, width, height)
            layer.tile_store.write_image_at(patch, x, y)
            layer.discard_image_cache()
            self.gpu_renderer.mark_layer_dirty(layer, rect)
            self._repaint_brush_dirty_rect(rect)
        if complete:
            # Decrement the count of in-flight workers.  Only when every
            # worker (primary + all symmetry mirrors) has reported complete
            # do we commit history and end the stroke.
            self._async_stroke_pending = max(0, self._async_stroke_pending - 1)
            if self._async_stroke_pending == 0:
                self._cancel_async_brush()
                self.commit_stroke_history()
                self.canvas_brush_end_stroke()

    def _cpp_active(
        self
    ) -> bool:

        return (
            self.cpp_brush_enabled
            and self.cpp_brush is not None
        )

    def _try_begin_instanced_stroke(self, layer, position: QPoint,
                                    pressure: float, tool: str) -> bool:
        # This GPU fast path hands GPUInstancedStrokeRenderer.begin() the
        # REAL layer.image directly, and its eventual commit
        # (_commit_readback in gpu_instanced_stroke.py) writes straight back
        # into layer.image/layer.tile_store - it has no concept of mask
        # editing at all. Any plain/simple brush preset (roundness~1, no
        # wet-mix, normal blend - i.e. most default presets) qualifies for
        # it, so painting with one while a mask is being edited used to
        # silently divert the whole stroke onto the layer's real pixels
        # instead of the mask buffer: the mask itself never changed at all
        # ("je peins sur le masque et rien ne se passe"), while the layer's
        # actual content was quietly being painted on instead. Excluded here
        # the same way _can_use_async_brush already excludes it, so a
        # mask-editing stroke always falls through to the mask-aware
        # synchronous CreativeCore path (get_active_image() /
        # sync_gpu_layer()) instead.
        if (not GPU_SHADER_STROKES_ENABLED
                or float(getattr(self.tools.brush, "smoothing", 0.0)) > 0.0
                or not self.gpu_ready or not self.use_gpu or self.transforming
                or self.document.layer_groups or has_non_normal(self.document)
                or not self.document.selection.is_empty()
                or getattr(layer, "lock_alpha", False)
                or self._editing_alpha_mask_layer_id == getattr(layer, "id", None)):
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

        self._cancel_async_brush()
        # Reject callbacks and cached pixels belonging to the previous document,
        # even when the new document has exactly the same dimensions.
        self._projection_tile_generation.clear()
        self._projection_tile_signatures.clear()
        self._projection_ready_tiles.clear()
        self._projection_pending_images.clear()
        self.__dict__.pop('_projection_result_cache', None)
        self.__dict__.pop('_projection_checked_state', None)
        self._projection_publish_keys.clear()
        self._projection_waiting_visible.clear()
        self._projection_display_ready = False
        self._projection_scan_pending = True
        self._frame_index_cache = None
        self.projection_store.clear_resident()
        self.projection_store.resize(document.width, document.height)
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
        active_layer = self.get_active_layer()
        if active_layer is not None:
            self.layer_thumbnail_dirty.emit(active_layer.id)
        if self._brush_segment_ms:
            latest = self._brush_segment_ms[-1]
            if latest > 16.0:
                self.performance_warning.emit(
                    f"Trait ralenti : {latest:.1f} ms (cible 8 ms)"
                )

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

    def _selection_edit_snapshot(self, image: QImage, rect: QRect) -> QImage | None:
        """Return a small pre-edit snapshot only when selection constrains it."""
        selection = self.document.selection
        if selection.is_empty():
            return None
        area = rect.intersected(image.rect())
        if area.isEmpty() or not area.intersects(selection.bounds()):
            return image.copy(area) if not area.isEmpty() else None
        return image.copy(area)

    def _restore_selection_after_edit(self, image: QImage, before: QImage | None,
                                      rect: QRect) -> QImage:
        """Composite a bounded edit through the active selection alpha.

        The brush engine intentionally receives a normal raster.  Applying a
        mask directly to that raster would erase existing pixels outside the
        selection, so this instead overlays the masked *changed* area on the
        captured pre-edit pixels.  It preserves all outside pixels and gives
        feathered selections their expected partial dab.
        """
        if before is None:
            return image
        area = rect.intersected(image.rect())
        if area.isEmpty() or before.size() != area.size():
            return image
        selection = self.document.selection
        if selection.is_empty():
            return image
        changed = image.copy(area).convertToFormat(QImage.Format.Format_RGBA8888)
        mask = selection.image.copy(area).convertToFormat(QImage.Format.Format_ARGB32)
        if changed.isNull() or mask.isNull() or not apply_alpha_mask_native(changed, mask):
            return image
        restored = before.convertToFormat(QImage.Format.Format_RGBA8888)
        painter = QPainter(restored)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(0, 0, changed)
        painter.end()
        target = QPainter(image)
        target.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        target.drawImage(area.topLeft(), restored)
        target.end()
        return image


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

        self.zoom = fit_zoom(document_width, document_height, self.width(), self.height(),
                             self.view_rotation, self.min_zoom, self.max_zoom, margin)

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
        return transform_point(position, self.width(), self.height(), self.view_rotation,
                               self.view_flip_x, self.view_flip_y, inverse)

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
        result = QPoint(round(x), round(y))

        # Also apply freeform AssistantManager snap (if any assistant is active)
        if self.assistants.snap_enabled and self.assistants.assistants():
            from PySide6.QtCore import QPointF as _QPointF
            snapped_f = self.assistants.snap_point(_QPointF(result))
            result = QPoint(round(snapped_f.x()), round(snapped_f.y()))

        return result

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

        if self._editing_alpha_mask_layer_id == layer.id:
            if self._editing_alpha_mask_image is None:
                layer.ensure_alpha_mask()
                self._editing_alpha_mask_image = layer.alpha_mask_grayscale()
            return self._editing_alpha_mask_image

        return layer.image

    def edit_layer_alpha_mask(self, index: int) -> bool:
        """Select a layer mask as the direct paint target."""
        if not 0 <= int(index) < len(self.document.layers):
            return False
        layer = self.document.layers[int(index)]
        if layer.alpha_mask_store is None:
            return False
        self.document.set_active_layer(int(index))
        self._editing_alpha_mask_layer_id = layer.id
        # The edit buffer is an OPAQUE greyscale image, exactly like a
        # Photoshop mask: black hides, white reveals, grey attenuates. The
        # store keeps coverage in alpha; sync_gpu_layer() converts only the
        # dirty region on the way in. (The old buffer drew white+alpha tiles
        # over white, so hidden areas came back white and every new dab
        # re-revealed its whole dirty rectangle.)
        self._editing_alpha_mask_image = layer.alpha_mask_grayscale()
        self.update()
        return True

    def reload_alpha_mask_edit_buffer(self) -> None:
        """Rebuild the mask edit buffer after undo/redo/invert changed the store."""
        layer_id = self._editing_alpha_mask_layer_id
        if layer_id is None:
            return
        layer = next((l for l in self.document.layers if l.id == layer_id), None)
        if layer is None or layer.alpha_mask_store is None:
            self._editing_alpha_mask_layer_id = None
            self._editing_alpha_mask_image = None
            return
        self._editing_alpha_mask_image = layer.alpha_mask_grayscale()

    def edit_layer_pixels(self) -> None:
        self._editing_alpha_mask_layer_id = None
        self._editing_alpha_mask_image = None
        self.update()

    # =========================================================
    # HISTORY
    # =========================================================

    def _reset_history(self) -> None:
        self.tile_history.reset()
        self.history = self.tile_history.steps
        self.history_index = 0
        self._stroke_image_format = None

    def begin_history_action(self, dirty_only: bool = False,
                             structure_only: bool = False) -> None:
        """Start an undo transaction for pixels, selection, or layer structure.

        Keeping ``structure_only`` explicit prevents metadata edits from being
        recorded as dirty-pixel edits.  That distinction is required to restore
        layer names, masks, groups, blend settings and visibility correctly.
        """
        self.tile_history.begin(self.document, dirty_only=dirty_only,
                                structure_only=structure_only)

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
            self.selection_operation = getattr(
                self, "selection_base_operation", SelectionOperation.REPLACE)

    def _begin_selection_gesture(self, position: QPointF, modifiers) -> None:
        self._set_selection_operation(modifiers)
        self._selection_gesture_modifiers = modifiers
        self.begin_selection_history_action()
        self.selection_drawing = True
        anchor = self.screen_to_image_f(position)
        self._selection_anchor = anchor
        self.selection_points = [anchor]

    def _update_selection_gesture(self, position: QPointF) -> None:
        point = self.screen_to_image_f(position)
        if self.tools.current_tool == "lasso":
            if not self.selection_points or (point - self.selection_points[-1]).manhattanLength() >= 0.5:
                self.selection_points.append(point)
            return
        # Marquee: Shift pressed *during* the drag = square/circle, Alt = from
        # the centre (modifiers held at mouse-down only choose add/subtract).
        from PySide6.QtGui import QGuiApplication
        live = QGuiApplication.keyboardModifiers()
        start = self._selection_gesture_modifiers
        constrain = bool(live & Qt.KeyboardModifier.ShiftModifier) and not bool(start & Qt.KeyboardModifier.ShiftModifier)
        from_center = bool(live & Qt.KeyboardModifier.AltModifier) and not bool(start & Qt.KeyboardModifier.AltModifier)
        anchor = self._selection_anchor if self._selection_anchor is not None else QPointF(self.selection_points[0])
        dx, dy = point.x() - anchor.x(), point.y() - anchor.y()
        if constrain:
            side = max(abs(dx), abs(dy))
            dx = side if dx >= 0 else -side
            dy = side if dy >= 0 else -side
        first = QPointF(anchor.x() - dx, anchor.y() - dy) if from_center else QPointF(anchor)
        self.selection_points = [first, QPointF(anchor.x() + dx, anchor.y() + dy)]

    def select_magic_wand_at(self, position: QPointF, modifiers) -> None:
        """Magic wand click honouring the options bar (tolerance, contiguous, sample all layers)."""
        layer = self.get_active_layer()
        if layer is None:
            return
        options = self.tools.selection_tools.options
        self._set_selection_operation(modifiers)
        if options.sample_all_layers:
            from DOCUMENTS.blend_modes import composite_document
            source = composite_document(self.document)
        else:
            source = layer.image
        self.begin_selection_history_action()
        try:
            candidate = self.tools.selection_tools.magic_wand(
                source, self.screen_to_image(position),
                tolerance=options.tolerance, cpp_library=self.cpp_brush_library,
                contiguous=options.contiguous, anti_alias=options.anti_alias,
                feather=options.feather,
            )
            self.document.selection.combine(candidate, self.selection_operation)
        except Exception:
            self.cancel_history_action()
            raise
        self.commit_history_action()
        self.update()

    # ---------------------------------------------------------------
    # FREE TRANSFORM SESSION
    # ---------------------------------------------------------------

    def start_free_transform(self) -> bool:
        if self.free_transform is not None:
            return True
        layer = self.get_active_layer()
        if (layer is None or getattr(layer, "locked", False)
                or self._editing_alpha_mask_layer_id == getattr(layer, "id", None)
                or getattr(layer, "tile_store", None) is None):
            return False
        selection = self.document.selection
        if not selection.is_empty():
            selection_image = selection.image
            bounds = selection.bounds()
        else:
            selection_image = None
            image = layer.image
            argb = (image if image.format() == QImage.Format.Format_ARGB32
                    else image.convertToFormat(QImage.Format.Format_ARGB32))
            values = native_selection_bounds(argb)
            bounds = QRect(*values) if values else QRect()
        if bounds.isEmpty():
            return False
        self.begin_history_action()
        try:
            session = FreeTransformSession(layer, selection_image, bounds)
            layer.image = session.remainder_image()
        except Exception:
            self.cancel_history_action()
            raise
        self.free_transform = session
        self.sync_gpu_layer()
        self.update()
        return True

    def commit_free_transform(self) -> None:
        session, self.free_transform = self.free_transform, None
        if session is None:
            return
        layer = session.layer
        if session.is_identity():
            layer.image = session.original
            self.sync_gpu_layer()
            self.cancel_history_action()
            self.update()
            return
        image, selection_image = session.result()
        layer.image = image
        if selection_image is not None:
            self.document.selection.image = selection_image
            self.document.selection.invalidate()
        self.sync_gpu_layer()
        self.commit_history_action()
        self.update()

    def cancel_free_transform(self) -> None:
        session, self.free_transform = self.free_transform, None
        if session is None:
            return
        session.layer.image = session.original
        self.sync_gpu_layer()
        self.cancel_history_action()
        self.update()

    def _finish_selection_gesture(self) -> None:
        if not self.selection_drawing:
            return
        tool = self.tools.current_tool
        points = list(self.selection_points)
        self.selection_drawing = False
        try:
            options = self.tools.selection_tools.options
            candidate = self.tools.selection_tools.shape_mask(
                tool, self.document.selection.image.size(), points,
                anti_alias=options.anti_alias, feather=options.feather,
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
        # TileHistory rejects nested transactions.  Without an explicit
        # boundary here, a stroke begun while a layer action is still pending
        # gets attached to that layer action and Ctrl+Z can remove the layer.
        pending = self.tile_history._pending
        if pending is not None and pending.get("mode") != "dirty":
            self.commit_history_action()
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

        if self.free_transform is not None:
            self.cancel_free_transform()
            return

        if self.tile_history._pending is not None:
            # Keep the UI responsive during an active stroke/action. The queued
            # undo runs immediately after its transaction commits or cancels.
            self._deferred_undo_count += 1
            if self._deferred_undo_count == 1:
                self.history_operation_deferred.emit("Annulation en attente")
            return

        if self.tile_history.undo(self.document):
            self.reload_alpha_mask_edit_buffer()
            self._invalidate_projection_cache()
            self._invalidate_gpu_after_history()
            self.history_index = self.tile_history.index
            self.history_restored.emit()
            self.update()
            self._schedule_deferred_undo()

    def redo(
        self
    ) -> None:

        if self.tile_history.redo(self.document):
            self.reload_alpha_mask_edit_buffer()
            self._invalidate_projection_cache()
            self._invalidate_gpu_after_history()
            self.history_index = self.tile_history.index
            self.history_restored.emit()
            self.update()

    def _invalidate_gpu_after_history(self) -> None:
        """Après Ctrl+Z / Ctrl+Maj+Z : forcer le GPU à relire les tuiles restaurées.

        Le cache de dessin par calque ne surveille que les révisions des tuiles
        *couleur* : un masque restauré, ou des tuiles réécrites par le chemin
        natif sans nouvelle révision, laissaient les anciennes textures à
        l'écran (artefacts après annulation)."""
        preview = getattr(self, "live_stroke_preview", None)
        if preview is not None:
            preview.points.clear()
            preview.active = False
        if not getattr(self, "gpu_ready", False):
            return
        renderer = getattr(self, "gpu_renderer", None)
        if renderer is not None:
            for layer in self.document.layers:
                try:
                    renderer.mark_layer_dirty(layer)
                    renderer.invalidate_layer_draw_cache(layer)
                except Exception:  # noqa: BLE001 — l'invalidation ne doit jamais bloquer l'undo
                    pass
            if hasattr(renderer, "_opaque_set_cache"):
                renderer._opaque_set_cache.clear()
        compositor = getattr(self, "gpu_tile_compositor", None)
        for tile in getattr(compositor, "tiles", {}).values():
            tile.revision = None   # recomposition forcée à la prochaine frame

    def _invalidate_projection_cache(self) -> None:
        """Reject in-flight native frames that were captured before undo/redo."""
        self._projection_idle_key = None
        self.__dict__.pop('_projection_result_cache', None)
        self.__dict__.pop('_projection_checked_state', None)
        stale_keys = (set(self.projection_store.occupied_keys)
                      | set(self._projection_tile_generation)
                      | set(self._projection_tile_signatures))
        for key in stale_keys:
            self._projection_tile_generation[key] = -1
            self._projection_tile_signatures.pop(key, None)
            self._projection_ready_tiles.discard(key)
            self._projection_pending_images.pop(key, None)

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
        translate_x = self.transform_move_delta.x()
        translate_y = self.transform_move_delta.y()
        rotation = self.transform_rotation

        if (
            abs(
                scale_x - 1.0
            ) < 0.0001
            and abs(
                scale_y - 1.0
            ) < 0.0001
            and abs(translate_x) < 0.0001
            and abs(translate_y) < 0.0001
            and abs(rotation) < 0.0001
        ):

            return

        self.apply_affine_to_layer(layer, TransformSpec(
            translate_x=translate_x, translate_y=translate_y,
            scale_x=scale_x, scale_y=scale_y, rotation=rotation,
        ))

    def apply_affine_to_layer(self, layer: Layer, spec: TransformSpec) -> None:
        selection = self.document.selection
        result = self.tools.transform_tool.apply(layer.image, spec, selection)
        layer.image = result.image
        if result.selection_image is not None:
            selection.image = result.selection_image
            selection.invalidate()
        self.sync_gpu_layer()

    def apply_perspective_to_layer(self, layer: Layer, corners) -> None:
        """Commit a four-corner projective transform as one undoable edit."""
        result = self.tools.transform_tool.perspective(layer.image, PerspectiveSpec(tuple(corners)))
        layer.image = result
        self.sync_gpu_layer()

    def apply_liquify_to_layer(self, layer: Layer, strokes: list[LiquifyStroke]) -> None:
        result = self.tools.transform_tool.liquify(layer.image, strokes)
        layer.image = result
        self.sync_gpu_layer()

    def apply_warp_to_layer(self, layer: Layer, controls: list[WarpControl]) -> None:
        result = self.tools.transform_tool.warp(layer.image, controls)
        layer.image = result
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
            painter.fillRect(rect, QColor(COLORS["window"]))
            return
        if background == "Light":
            painter.fillRect(rect, QColor(COLORS["panel_raised"]))
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

        if self.free_transform is not None:
            layer = self.free_transform.layer
            opacity = float(getattr(layer, "opacity", 1.0)) if getattr(layer, "visible", True) else 0.0
            self.free_transform.draw(painter, QPointF(self.offset), self.zoom, opacity)
        # The legacy per-drag box below is superseded by the session.
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
        if not bounds.isEmpty() and self.free_transform is None:
            # Real pixel outline (was: only the bounding box, so ellipses,
            # lassos and wand selections all looked like rectangles).
            segments = self.document.selection.outline_segments()
            ox, oy, z = self.offset.x(), self.offset.y(), self.zoom
            lines = [QLineF(ox + x1 * z, oy + y1 * z, ox + x2 * z, oy + y2 * z)
                     for x1, y1, x2, y2 in segments]
            painter.save()
            white = QPen(QColor(255, 255, 255), 1.0)
            white.setCosmetic(True)
            painter.setPen(white)
            painter.drawLines(lines)
            black = QPen(QColor(0, 0, 0), 1.0, Qt.PenStyle.CustomDashLine)
            black.setDashPattern([4.0, 4.0])
            black.setCosmetic(True)
            painter.setPen(black)
            painter.drawLines(lines)
            painter.restore()

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
            painter.setPen(QPen(QColor(COLORS["gold"]), 2, Qt.PenStyle.DashLine))
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

        # ── New freeform AssistantManager overlay ──────────────────────────
        def _to_screen(image_pt: QPointF) -> QPointF:
            return QPointF(
                self.offset.x() + image_pt.x() * self.zoom,
                self.offset.y() + image_pt.y() * self.zoom,
            )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.assistants.draw_overlay(painter, _to_screen)
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

        # Aperçu anti-latence : dessiné dans tous les chemins de rendu, car
        # draw_brush_cursor est le dernier overlay de chacun d'eux.
        preview = getattr(self, "live_stroke_preview", None)
        if preview is not None:
            preview.paint(painter)
        # Module Pixel Art (Existence) : grilles, mosaïque et curseur pixel.
        pixel_art = getattr(self, "pixel_art", None)
        if pixel_art is not None:
            try:
                pixel_art.paint_overlay(painter)
            except Exception:  # noqa: BLE001 — une aide visuelle ne doit jamais casser le rendu
                pass

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
        # Le moteur de rendu lit l'état des tuiles (résidence, révision) une seule
        # fois par image au lieu de traverser ctypes plusieurs fois par tuile.
        renderer = getattr(self, "gpu_renderer", None)
        if renderer is None:
            self._paint_gl_frame()
            return
        renderer.begin_frame()
        try:
            self._paint_gl_frame()
        finally:
            renderer.end_frame()

    def _paint_gl_frame(
        self
    ) -> None:

        self._record_paint_start()

        preview = getattr(self.document, "_display_preview", None)
        if preview is not None and not preview.isNull():
            loading = getattr(self.document, "_loading_preview", False)
            if not loading and not self._projection_display_ready:
                self._ensure_projection()
            if loading or not self._projection_display_ready:
                self._paint_cpu_fallback()
                return

        # QOpenGLContext is already imported at the module level; no need to
        # re-import it on every paint call.
        context = (
            QOpenGLContext.currentContext()
        )

        if context is None:

            self._paint_cpu_fallback()

            return

        if not self.use_gpu:
            self._paint_cpu_fallback()
            return

        # Interactive affine previews and in-progress selections must remain
        # pixel-accurate while their geometry is changing.  The GPU texture
        # path is restored immediately after the gesture; this avoids visual
        # artefacts and keeps the selection feedback identical to the final
        # CreativeCore operation.
        if self.transforming or self.selection_drawing:
            self._paint_cpu_fallback()
            return

        large_stack = (self.document.width * self.document.height >= 16_000_000
                       and sum(layer.visible for layer in self.document.layers) >= 8)
        if (has_non_normal(self.document) or self.document.layer_groups
                or (large_stack and not self.gpu_instanced_stroke.active)):
            self._paint_gpu_projection()
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
        # Pre-compute once; reused after gpu_instanced_stroke.process() restores GL state.
        _vp_w = int(self.width() * dpr)
        _vp_h = int(self.height() * dpr)

        gl.glViewport(
            0,
            0,
            _vp_w,
            _vp_h,
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
        # Restore viewport/blend state that process() may have changed — reuse the
        # values computed above so we avoid re-multiplying width/height × dpr.
        gl.glViewport(0, 0, _vp_w, _vp_h)
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
                view_rotation=self.view_rotation,
                view_flip_x=self.view_flip_x,
                view_flip_y=self.view_flip_y,
                transform_rotation=(self.transform_rotation if is_transform_preview else 0.0),
                transform_translate_x=(self.transform_move_delta.x() if is_transform_preview else 0.0),
                transform_translate_y=(self.transform_move_delta.y() if is_transform_preview else 0.0),
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

    def _paint_gpu_projection(self) -> None:
        """Present native-composited tiles through OpenGL for complex documents."""
        if not self.gpu_ready:
            self._paint_cpu_fallback()
            return
        context = QOpenGLContext.currentContext()
        if context is None:
            self._paint_cpu_fallback()
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 18))
        self.draw_transparency_grid(painter)
        painter.beginNativePainting()
        gl = context.functions()
        dpr = self.devicePixelRatioF()
        gl.glViewport(0, 0, int(self.width() * dpr), int(self.height() * dpr))
        gl.glEnable(0x0BE2)
        gl.glBlendFuncSeparate(0x0001, 0x0303, 0x0001, 0x0303)
        # Standard blend stacks are composed tile-by-tile in shader FBOs.
        # Any advanced document returns None and falls through to the exact
        # asynchronous CreativeCore projection below.
        composed_tiles = []
        for index, layer in enumerate(self.document.layers):
            self._commit_layer_cache_for_render(layer, index)
        # supports_cached() memoizes the (also non-trivial) structure check
        # against a document signature; the plain supports() staticmethod
        # this used to call re-ran that whole per-layer/per-group check from
        # scratch every single frame regardless of whether anything changed.
        visible_keys = self.visible_document_tile_keys()
        # The shader compositor retains only MAX_TILE_CACHE FBOs. Composing
        # more before drawing evicts texture IDs still in composed_tiles and
        # repeats all of that work next frame. Use the budgeted projection
        # plus reduced overview for large viewports instead.
        if (GPU_SHADER_COMPOSITING_ENABLED
                and len(visible_keys) <= self.gpu_tile_compositor.MAX_TILE_CACHE
                and self.gpu_tile_compositor.supports_cached(self.document)):
            # Both computed once for every tile this frame instead of once
            # per visible layer per tile - see GPUTileCompositor._static_signature
            # and compose_tile()'s `supports` parameter.
            static = self.gpu_tile_compositor._static_signature(self.document)
            for tx, ty in visible_keys:
                texture_id = self.gpu_tile_compositor.compose_tile(self.document, tx, ty, static, True)
                if texture_id is None:
                    composed_tiles = []
                    break
                composed_tiles.append((tx, ty, texture_id))
            if composed_tiles:
                for tx, ty, texture_id in composed_tiles:
                    self.gpu_renderer.draw_texture_tile(
                        texture_id, self.projection_store.tile_rect(tx, ty),
                        float(self.width()), float(self.height()), self.zoom, self.offset,
                        device_pixel_ratio=dpr, view_rotation=self.view_rotation,
                        view_flip_x=self.view_flip_x, view_flip_y=self.view_flip_y,
                    )
                gl.glDisable(0x0BE2)
                painter.endNativePainting()
                self.draw_view_overlays(painter)
                self.draw_brush_cursor(painter)
                painter.end()
                return
        # Keep ordinary layer textures too: toggling a blend mode must not
        # evict the visible-tile cache and force an unnecessary re-upload.
        # Only advanced documents need the authoritative CPU projection.
        self._ensure_projection()
        self.gpu_renderer.prune_layers([self._gpu_projection_layer, *self.document.layers])
        if not self._draw_projection_overview(dpr):
            self.gpu_renderer.draw_layer(
                self._gpu_projection_layer, self.document, float(self.width()),
                float(self.height()), self.zoom, self.offset,
                device_pixel_ratio=dpr,
                view_rotation=self.view_rotation,
                view_flip_x=self.view_flip_x,
                view_flip_y=self.view_flip_y,
            )
        gl.glDisable(0x0BE2)
        painter.endNativePainting()
        self.draw_view_overlays(painter)
        self._draw_tile_loading_indicator(painter)
        self.draw_brush_cursor(painter)
        painter.end()

    def _draw_tile_loading_indicator(self, painter: QPainter) -> None:
        """Small, non-blocking feedback while old/proxy pixels cover a cold load."""
        waiting = len(getattr(self, "_projection_waiting_visible", ()))
        if not waiting:
            return
        text = "Chargement des tuiles…" if waiting > 1 else "Chargement de la tuile…"
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(12, self.height() - 36, 180, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 23, 42, 210))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor(203, 213, 225))
        painter.setFont(QFont("Sans Serif", 9))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _draw_projection_overview(self, dpr: float) -> bool:
        """Zoomed out: draw the projection as ONE reduced texture.

        At fit-to-screen a 3000 px document is ~2600 projection tiles, i.e.
        thousands of GL calls from Python every frame.  Below 50 % zoom the
        tiles are instead reduced (power-of-two scale, so tile edges stay on
        whole pixels) into a single texture that is updated only where a
        projection tile changed, and drawn with one call.
        """
        import math
        renderer = self.gpu_renderer
        screen_scale = float(self.zoom) * float(dpr)
        if screen_scale <= 0 or screen_scale > 0.5 or renderer.blitter is None:
            return False
        level = max(1, min(6, int(math.floor(math.log2(1.0 / screen_scale)))))
        scale = 1.0 / (1 << level)
        store = self.projection_store
        width = max(1, math.ceil(self.document.width * scale))
        height = max(1, math.ceil(self.document.height * scale))
        identity = (id(self.document), level, width, height, id(store))
        state = getattr(self, "_overview_state", None)
        if state is None or state["identity"] != identity:
            if state is not None:
                try:
                    state["texture"].destroy()
                except RuntimeError:
                    pass
            image = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
            image.fill(0)
            try:
                texture = renderer._create_texture(image, tiled=True)
            except RuntimeError:
                return False
            state = self._overview_state = {"identity": identity, "image": image,
                                            "texture": texture, "versions": {}}
        revisions = store.resident_revisions() or {}
        versions = state["versions"]
        changed = [key for key in self._projection_ready_tiles
                   if versions.get(key) != revisions.get(key)]
        if changed:
            image = state["image"]
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            left = top = 1 << 30
            right = bottom = -1
            for key in changed:
                rect = store.tile_rect(*key)
                try:
                    tile = store.tile(*key)
                except OSError:
                    continue
                x0, y0 = int(rect.x() * scale), int(rect.y() * scale)
                x1 = min(width, math.ceil((rect.x() + rect.width()) * scale))
                y1 = min(height, math.ceil((rect.y() + rect.height()) * scale))
                if x1 <= x0 or y1 <= y0:
                    continue
                painter.drawImage(QRectF(x0, y0, x1 - x0, y1 - y0), tile)
                versions[key] = revisions.get(key)
                left, top = min(left, x0), min(top, y0)
                right, bottom = max(right, x1), max(bottom, y1)
            painter.end()
            if right > left and bottom > top:
                patch = image.copy(left, top, right - left, bottom - top)
                if not renderer._upload_client_memory(state["texture"], patch, left, top):
                    return False
        target = QRectF(self.offset.x() * dpr, self.offset.y() * dpr,
                        self.document.width * self.zoom * dpr,
                        self.document.height * self.zoom * dpr)
        viewport = QRectF(0, 0, self.width() * dpr, self.height() * dpr).toRect()
        blitter = renderer.blitter
        blitter.bind()
        try:
            blitter.setOpacity(1.0)
            blitter.blit(int(state["texture"].textureId()),
                         renderer._blit_view_transform(target, viewport, self.view_rotation,
                                                       self.view_flip_x, self.view_flip_y),
                         "top_left")
        finally:
            blitter.release()
        return True

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

        preview = getattr(self.document, "_display_preview", None)
        if (preview is not None and not preview.isNull()
                and (getattr(self.document, "_loading_preview", False)
                     or not self._projection_display_ready)):
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(0, 0, self.document.width, self.document.height), preview)
            painter.restore()
            self.draw_view_overlays(painter)
            painter.end()
            return

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

            # This fast path (no non-normal blends, no groups - see
            # has_non_normal() above) used to draw layer.image directly and
            # never looked at alpha_mask_store at all, so any layer with an
            # alpha mask attached but otherwise "normal" blend/no clipping
            # rendered fully opaque no matter what was painted on its mask.
            # _ensure_projection()'s per-tile path already does exactly this
            # (see _projection_tile_for_layer) - mirrored here for the whole
            # flattened layer image instead of per-tile.
            image = layer.image
            mask_store = getattr(layer, "alpha_mask_store", None)
            if mask_store is not None and not getattr(layer, "mask_disabled", False):
                mask = layer.alpha_mask_coverage()
                masked_image = clone_image_native(image)
                if (masked_image is None or mask.size() != masked_image.size()
                        or not apply_alpha_mask_native(masked_image, mask)):
                    raise RuntimeError("CreativeCore refused to apply the alpha mask")
                image = masked_image

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
                    image
                )

                painter.restore()

            else:

                painter.drawImage(
                    0,
                    0,
                    image
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

    def _screen_rect_for_document_rect(self, document_rect: QRect) -> QRect:
        """Map a dirty document region to the widget, including view transforms.

        QWidget.update() consumes widget coordinates, whereas brush dabs are
        expressed in document coordinates.  Passing the latter directly made
        Qt repaint an unrelated (and often much larger) region while drawing.
        """
        if document_rect.isEmpty():
            return QRect()
        corners = (
            QPointF(document_rect.left(), document_rect.top()),
            QPointF(document_rect.right() + 1, document_rect.top()),
            QPointF(document_rect.left(), document_rect.bottom() + 1),
            QPointF(document_rect.right() + 1, document_rect.bottom() + 1),
        )
        mapped = [self._view_transform_point(self.offset + point * self.zoom)
                  for point in corners]
        bounds = QRectF(mapped[0], mapped[0])
        for point in mapped[1:]:
            bounds = bounds.united(QRectF(point, point))
        # One physical-pixel margin protects interpolation at transformed edges.
        return bounds.adjusted(-2.0, -2.0, 2.0, 2.0).toAlignedRect()

    def _repaint_brush_dirty_rect(self, document_rect: QRect) -> None:
        screen_rect = self._screen_rect_for_document_rect(document_rect)
        if screen_rect.isEmpty():
            return
        self.update(screen_rect.intersected(self.rect()))

    def sync_gpu_layer(self, dirty_rect: QRect | None = None) -> None:
        """Invalide uniquement la texture après un dessin déjà fait en C++."""
        layer = self.document.get_active_layer()
        if layer is not None:
            if (self._editing_alpha_mask_layer_id == layer.id
                    and self._editing_alpha_mask_image is not None):
                buffer = self._editing_alpha_mask_image
                region = (QRect(0, 0, buffer.width(), buffer.height()) if dirty_rect is None
                          else QRect(dirty_rect).intersected(QRect(0, 0, buffer.width(), buffer.height())))
                if region.isEmpty():
                    return
                # Snap to whole tiles: a missing mask tile reads back as
                # transparent (= hidden), so a partial write into it would
                # hide everything around the dab in that tile.
                tile = layer.ensure_alpha_mask().tile_size
                x0, y0 = (region.left() // tile) * tile, (region.top() // tile) * tile
                x1 = min(buffer.width(), ((region.right() // tile) + 1) * tile)
                y1 = min(buffer.height(), ((region.bottom() // tile) + 1) * tile)
                region = QRect(x0, y0, x1 - x0, y1 - y0)
                # Keep the edit buffer grey/opaque; only the copy that goes to
                # the store is converted to coverage-in-alpha. Normalising the
                # buffer in place turned grey into transparency, so later dabs
                # blended against transparent pixels (halos, uneven greys).
                coverage = buffer.copy(region)
                if not normalize_alpha_mask_native(coverage):
                    raise RuntimeError("CreativeCore n'a pas pu normaliser le masque alpha")
                # write_image() bumps the native tile revision for every tile it
                # touches, and the projection signature already keys off that
                # revision (see _projection_signature_for /
                # _tile_projection_layers). Clearing every cached tile signature
                # here made each single brush dab invalidate the WHOLE document's
                # projection cache instead of just the tiles the dab touched —
                # on a big canvas with folders/clipping (anything that routes
                # through _ensure_projection) that meant recomputing thousands of
                # tiles per dab, which is what made mask painting unusable. The
                # raster-layer branch below never needed this clear for the same
                # reason; masks don't either.
                layer.ensure_alpha_mask().write_image_at(
                    coverage.convertToFormat(layer.alpha_mask_store.image_format),
                    region.x(), region.y())
                if getattr(self, "gpu_ready", False):
                    self.gpu_renderer.mark_layer_dirty(layer, dirty_rect)
                    # mark_layer_dirty() alone only affects sync_layer()'s
                    # (untiled) dirty-rect path. The common case - a tiled
                    # layer drawn via _draw_tiled_layer_cached() - has its own
                    # per-layer cached tile-draw list keyed off the *color*
                    # tile store's signature only, which a mask edit never
                    # changes; without this it kept reusing last frame's
                    # (pre-edit) texture ids even after sync_tile() itself was
                    # made mask-aware.
                    self.gpu_renderer.invalidate_layer_draw_cache(layer)
                if dirty_rect is None:
                    self.update()
                else:
                    self._repaint_brush_dirty_rect(dirty_rect)
                return
            # CreativeCore writes through a raw pointer, which does not bump
            # QImage.cacheKey(); explicitly copy its dirty area to tiles.
            layer.commit_image_cache(dirty_rect, force=True)
            self.tile_history.mark_dirty(layer, dirty_rect)
        if layer is not None and getattr(self, "gpu_ready", False):
            self.gpu_renderer.mark_layer_dirty(layer, dirty_rect)
        if dirty_rect is None:
            self.update()
        else:
            self._repaint_brush_dirty_rect(dirty_rect)

    def _ensure_projection(self) -> None:
        # Garde-fou : un groupe non contigu ferait lever paintGL à chaque image
        # (et finit par faire planter l'application) ; on le répare avant de composer.
        repair = getattr(self.document, "repair_layer_groups", None)
        if repair is not None and repair():
            self._projection_tile_signatures.clear()
            print("Groupes de calques incohérents : réparés automatiquement.")
        for index, layer in enumerate(self.document.layers):
            self._commit_layer_cache_for_render(layer, index)
        if (self.projection_store.width != self.document.width
                or self.projection_store.height != self.document.height):
            self.projection_store.resize(self.document.width, self.document.height)
            self._projection_tile_signatures.clear()
            self._projection_tile_generation.clear()
            self._projection_ready_tiles.clear()
            self._projection_pending_images.clear()
            self._projection_display_ready = False
        # An unchanged viewport needs no tile enumeration or signature scan.
        # Pixel edits, masks, document structure and view changes all invalidate
        # this key; scratch residency changes advance the same store counters.
        def store_version(store):
            return None if store is None else (id(store), getattr(store, "_mutation_count", None))
        current_key = (
            id(self.document), self.width(), self.height(), self.zoom,
            self.offset.x(), self.offset.y(), self.view_rotation,
            self.view_flip_x, self.view_flip_y, self._projection_prefetch_margin_tiles,
            tuple((self._layer_static_signature(layer), store_version(layer.tile_store),
                   store_version(getattr(layer, "alpha_mask_store", None)))
                  for layer in self.document.layers), self._groups_static_signature())
        self._projection_current_key = current_key
        if (getattr(self, "_projection_idle_key", None) == current_key
                and self._projection_display_ready
                and not self._projection_scan_pending
                and not self._projection_waiting_visible
                and getattr(self, "_projection_idle_revision", None)
                    == self.projection_store._mutation_count):
            return
        visible_keys = self.visible_document_tile_keys()
        self._projection_publish_keys = visible_keys
        self._projection_waiting_visible = visible_keys - self._projection_ready_tiles
        # Keep a recent projection behind the moving viewport. A newly exposed
        # cold tile can therefore continue showing its former texture/overview
        # while its authoritative scratch source is restored asynchronously.
        pan_delta = (self.offset.x() - self._last_view_offset.x(),
                     self.offset.y() - self._last_view_offset.y())
        self._last_view_offset = QPointF(self.offset)
        active = self.document.get_active_layer()
        active_group = (self.document.group_for_layer(active.id) if active is not None else None)
        # The active group's visible tiles are promoted to their own class;
        # its isolated cache is consequently retained while the user edits it.
        active_group_keys = visible_keys if active_group is not None else ()
        desired = self.tile_cache_manager.update(visible_keys, pan_delta=pan_delta, zoom=self.zoom,
                                                 active_group_keys=active_group_keys)
        columns = (self.document.width + TILE_SIZE - 1) // TILE_SIZE
        rows = (self.document.height + TILE_SIZE - 1) // TILE_SIZE
        keys = {key for key in desired if 0 <= key[0] < columns and 0 <= key[1] < rows}
        known_keys = (self.projection_store.resident_keys()
                      | set(self._projection_tile_signatures)
                      | set(self._projection_tile_generation)
                      | self._projection_ready_tiles)
        for key in known_keys:
            if key not in keys and not self.tile_cache_manager.should_retain(key):
                self.projection_store.remove_resident_tile(*key)
                self._projection_tile_signatures.pop(key, None)
                self._projection_ready_tiles.discard(key)
                self._projection_tile_generation.pop(key, None)
                self._projection_pending_images.pop(key, None)
        visible_inputs = {}
        prefetch_inputs = {}
        # Computed once for the whole frame - see _projection_signature_for.
        layer_static = [self._layer_static_signature(layer) for layer in self.document.layers]
        groups_static = self._groups_static_signature()
        # One native call per tile store per frame instead of one per layer per
        # tile: with ~80 layers and ~2000 cached tiles the per-tile lookups
        # alone cost seconds per frame.
        # Nothing structural or pixel-wise changed since the last frame (the
        # common case: idle repaint, cursor move, pan): reuse the previous
        # index and skip every tile that already has an up-to-date signature.
        def mutations(store):
            return (id(store), getattr(store, "_mutation_count", None)) if store is not None else None
        frame_state = (tuple(hash(static) for static in layer_static), hash(groups_static),
                       tuple((mutations(layer.tile_store),
                              mutations(getattr(layer, "alpha_mask_store", None)))
                             for layer in self.document.layers))
        cached = getattr(self, "_frame_index_cache", None)
        unchanged = (cached is not None and cached[0] == frame_state
                     and all(item[1] is not None for pair in frame_state[2] for item in pair
                             if item is not None))
        incremental = False
        if unchanged:
            _state, revision_maps, tile_signature = cached
        elif (cached is not None and cached[0][0] == frame_state[0]
              and cached[0][1] == frame_state[1] and len(cached[0][2]) == len(frame_state[2])
              and all(old[0] is not None and new[0] is not None and old[0][0] == new[0][0]
                      and (old[1] is None) == (new[1] is None)
                      and (old[1] is None or old[1][0] == new[1][0])
                      for old, new in zip(cached[0][2], frame_state[2]))):
            # Only pixels changed (painting): re-read just the touched stores
            # and invalidate just the tiles whose revisions moved.
            old_state, old_maps, _old_signature = cached
            revision_maps = list(old_maps)
            dirty: set | None = set()
            layers = self.document.layers
            for index, (old_pair, new_pair) in enumerate(zip(old_state[2], frame_state[2])):
                if old_pair == new_pair:
                    continue
                layer = layers[index]
                colors = (self._store_revision_map(layer.tile_store)
                          if old_pair[0] != new_pair[0] else old_maps[index][0])
                masks = (self._store_revision_map(getattr(layer, "alpha_mask_store", None))
                         if old_pair[1] != new_pair[1] else old_maps[index][1])
                for before, after in ((old_maps[index][0], colors), (old_maps[index][1], masks)):
                    if before is None or after is None:
                        dirty = None
                        break
                    dirty.update(key for key in before.keys() | after.keys()
                                 if before.get(key) != after.get(key))
                if dirty is None:
                    break
                revision_maps[index] = (colors, masks)
            if dirty is not None:
                tile_signature = self._tile_signature_direct(layer_static, groups_static,
                                                             revision_maps)
                for key in dirty:
                    self._projection_tile_signatures.pop(key, None)
                self._frame_index_cache = (frame_state, revision_maps, tile_signature)
                unchanged = incremental = True
        if not unchanged:
            revision_maps = [(self._store_revision_map(layer.tile_store),
                              self._store_revision_map(getattr(layer, "alpha_mask_store", None)))
                             for layer in self.document.layers]
            tile_signature = self._tile_signature_index(layer_static, groups_static, revision_maps)
            self._frame_index_cache = (frame_state, revision_maps, tile_signature)
        # Only actually needed by tiles that miss the cache below, so unlike
        # layer_static/groups_static above (checked against every tile, hit or
        # miss) this is built lazily - a frame where everything is already
        # cached (nothing being painted, just an idle repaint) should not pay
        # an O(groups + layers) cost it will never use. See _group_hierarchy.
        hierarchy = None
        known_signatures = self._projection_tile_signatures
        # Never block the UI thread for long: tiles are recomputed within a
        # per-frame time budget, on-screen tiles first; the rest continue on
        # the next frames (the previous projection stays visible meanwhile).
        import time as _time
        started = _time.perf_counter()
        budget = 0.018
        more_work = False
        ordered = [key for key in keys if key in visible_keys]
        ordered += [key for key in keys if key not in visible_keys]
        # Continue a budget-limited scan without rechecking its completed prefix.
        checked_state = (current_key, frozenset(keys))
        if getattr(self, '_projection_checked_state', None) != checked_state:
            self._projection_checked_state = checked_state
            self._projection_checked_keys = set()
        checked = self._projection_checked_keys
        from collections import OrderedDict
        result_cache = self.__dict__.setdefault('_projection_result_cache', OrderedDict())
        batch_context = None
        batch_jobs = []
        # A frame cut short by the time budget has only re-checked part of the
        # tiles: until a full pass completes, stale signatures must not be
        # trusted (otherwise tiles changed by e.g. hiding a layer stay stale).
        if not unchanged:
            self._projection_scan_pending = True
        scan_pending = getattr(self, "_projection_scan_pending", False)
        for tx, ty in ordered:
            if more_work:
                break
            key = (tx, ty)
            if key in checked and key in known_signatures:
                self._projection_cache_stats["visible_hits" if key in visible_keys else "prefetch_hits"] += 1
                continue
            if (unchanged and not scan_pending and tile_signature is not None
                    and key in known_signatures):
                self._projection_cache_stats["visible_hits" if key in visible_keys else "prefetch_hits"] += 1
                continue            # same index as last frame: this tile is current
            signature = (tile_signature(tx, ty) if tile_signature is not None else
                         self._projection_signature_for(tx, ty, layer_static, groups_static,
                                                        revision_maps))
            if self._projection_tile_signatures.get(key) == signature:
                checked.add(key)
                stats_key = "visible_hits" if key in visible_keys else "prefetch_hits"
                self._projection_cache_stats[stats_key] += 1
                continue
            stats_key = "visible_misses" if key in visible_keys else "prefetch_misses"
            self._projection_cache_stats[stats_key] += 1
            self.tile_cache_manager.mark_request(key)
            self._tile_loading_since.setdefault(key, _time.perf_counter())
            self._projection_ready_tiles.discard(key)
            if key in visible_keys:
                self._projection_waiting_visible.add(key)
            self._projection_pending_images.pop(key, None)
            cache_key = (id(self.document), self.document.width, self.document.height, key, signature)
            cached_image = result_cache.get(cache_key)
            if cached_image is not None:
                result_cache.move_to_end(cache_key)
                self._projection_tile_generation.pop(key, None)
                self._projection_tile_signatures[key] = signature
                self._projection_pending_images[key] = cached_image
                self._projection_ready_tiles.add(key)
                self.tile_cache_manager.mark_ready(key)
                self._tile_loading_since.pop(key, None)
                self._projection_waiting_visible.discard(key)
                checked.add(key)
                continue
            rect = self.projection_store.tile_rect(tx, ty)
            if rect.isEmpty():
                continue
            rect = self.projection_store.tile_rect(tx, ty)
            if hierarchy is None:
                hierarchy = self._group_hierarchy()
            batch_program = None
            if batch_context is None:
                batch_context = self._native_batch_context(hierarchy, frame_state)
            if batch_context:
                batch_program = self._native_tile_program(tx, ty, batch_context, revision_maps)
            if batch_program is not None:
                program, missing_scratch = batch_program
                if missing_scratch:
                    continue
                batch_jobs.append((key, rect, signature, program))
                if len(batch_jobs) >= 384:
                    more_work = True
            else:
                native = self._native_tile_image(tx, ty, rect, hierarchy, revision_maps)
                if native is not None:
                    image, missing_scratch = native
                    tile_layers = ([] if image is None else
                                   [ProjectionLayer(image, True, 1.0, "normal", {})])
                else:
                    tile_layers, missing_scratch = self._tile_projection_layers(tx, ty, rect, hierarchy)
                if missing_scratch:
                    continue
                # The native worker is FIFO.  Submit the viewport first so a
                # quick pan never lets speculative work delay what is on screen.
                target = visible_inputs if key in visible_keys else prefetch_inputs
                target[key] = (rect.width(), rect.height(), tile_layers)
                self._projection_tile_signatures[key] = signature
                self._projection_ready_tiles.discard(key)
            if _time.perf_counter() - started > budget:
                more_work = True
        if batch_jobs:
            images = self._compose_native_batch(batch_context, batch_jobs)
            for (key, rect, signature, _program), image in zip(batch_jobs, images):
                if image is None:
                    continue
                # The native stack batch already produced the final pixels.
                # Do not run a second asynchronous normal-layer composition.
                self._projection_tile_generation.pop(key, None)
                self._projection_tile_signatures[key] = signature
                self._projection_pending_images[key] = image
                self._projection_ready_tiles.add(key)
                self.tile_cache_manager.mark_ready(key)
                self._tile_loading_since.pop(key, None)
                self._projection_waiting_visible.discard(key)
                checked.add(key)
                cache_key = (id(self.document), self.document.width, self.document.height, key, signature)
                result_cache[cache_key] = image
                result_cache.move_to_end(cache_key)
                # At most 128 MiB of 64x64 ARGB tile pixels, independent of canvas size.
                while len(result_cache) > 8192:
                    result_cache.popitem(last=False)
        if more_work:
            QTimer.singleShot(0, self.update)
        else:
            self._projection_scan_pending = False
        if not visible_inputs and not prefetch_inputs:
            self._publish_projection_frame()
            return
        for inputs in (visible_inputs, prefetch_inputs):
            if not inputs:
                continue
            generation = self.projection_worker.request(inputs)
            for key in inputs:
                self._projection_tile_generation[key] = generation

    def _native_batch_context(self, hierarchy, frame_state):
        """(template, batch function, positions) for this frame, or False."""
        from CORE.native_bridge import load_creative_core
        from DOCUMENTS.stack_program import build_stack_template, native_batch_function
        function = native_batch_function(load_creative_core())
        if function is None:
            return False
        structure = (frame_state[0], frame_state[1], len(self.document.layers))
        cached = getattr(self, "_stack_template_cache", None)
        if cached is not None and cached[0] == structure:
            template = cached[1]
        else:
            template = build_stack_template(self.document, hierarchy)
            self._stack_template_cache = (structure, template)
        if template is None:
            return False
        return (template, function, hierarchy[3])

    def _native_tile_program(self, tx: int, ty: int, context, revision_maps):
        """(program, pending) for one tile from the frame's template."""
        template, _function, positions = context
        key = (tx, ty)
        maps_ok = revision_maps is not None and len(revision_maps) == len(self.document.layers)

        def fetch(store, revisions):
            if revisions is not None and key not in revisions:
                return None, False
            if not store.has_tile(tx, ty):
                return None, False
            if not store.tile_is_resident(tx, ty):
                store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                return None, True
            return store.tile(tx, ty), False

        def layer_image(layer):
            return fetch(layer.tile_store, revision_maps[positions[layer.id]][0] if maps_ok else None)

        def layer_mask(layer):
            return fetch(layer.alpha_mask_store,
                         revision_maps[positions[layer.id]][1] if maps_ok else None)

        program = template.instantiate(layer_image, layer_mask)
        return program, program.pending

    def _compose_native_batch(self, context, jobs):
        """Compose every queued tile in one parallel CreativeCore call."""
        from CORE.native_bridge import qimage_pointer
        from DOCUMENTS.stack_program import compose_batch
        _template, function, _positions = context
        pointers = []

        def pixels_of(image):
            fmt = image.format()
            if fmt == QImage.Format.Format_ARGB32:
                code = 0
            elif fmt == QImage.Format.Format_RGBA8888:
                code = 1
            else:
                return None
            pointer = qimage_pointer(image)
            pointers.append(pointer)
            return ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine(), code

        def new_target(width, height):
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            pointer = qimage_pointer(image)
            pointers.append(pointer)
            return image, ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine()

        images = compose_batch([(program, rect.width(), rect.height())
                                for _key, rect, _signature, program in jobs],
                               function, pixels_of, new_target)
        return images if images is not None else [None] * len(jobs)

    def _native_tile_image(self, tx: int, ty: int, rect: QRect, hierarchy, revision_maps):
        """Compose one projection tile in a single CreativeCore call.

        Returns None when the document needs the Python path (old bridge,
        layer effects, non-LUT adjustments), else (image | None, pending).
        """
        from CORE.native_bridge import load_creative_core, qimage_pointer
        from DOCUMENTS.stack_program import (build_stack_program, compose_program,
                                             native_stack_function)
        function = native_stack_function(load_creative_core())
        if function is None:
            return None
        key = (tx, ty)
        positions = hierarchy[3]
        maps_ok = revision_maps is not None and len(revision_maps) == len(self.document.layers)

        def fetch(store, revisions):
            if revisions is not None and key not in revisions:
                return None, False
            if not store.has_tile(tx, ty):
                return None, False
            if not store.tile_is_resident(tx, ty):
                store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                return None, True
            return store.tile(tx, ty), False

        def layer_image(layer):
            colors = revision_maps[positions[layer.id]][0] if maps_ok else None
            return fetch(layer.tile_store, colors)

        def layer_mask(layer):
            masks = revision_maps[positions[layer.id]][1] if maps_ok else None
            return fetch(layer.alpha_mask_store, masks)

        program = build_stack_program(self.document, layer_image, layer_mask, hierarchy)
        if program is None:
            return None
        if program.pending:
            return None, True
        pointers = []

        def pixels_of(image):
            fmt = image.format()
            if fmt == QImage.Format.Format_ARGB32:
                code = 0
            elif fmt == QImage.Format.Format_RGBA8888:
                code = 1
            else:
                return None
            pointer = qimage_pointer(image)
            pointers.append(pointer)
            return ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine(), code

        def new_target(width, height):
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            pointer = qimage_pointer(image)
            pointers.append(pointer)
            return image, ctypes.cast(pointer, ctypes.c_void_p).value, image.bytesPerLine()

        image = compose_program(program, rect.width(), rect.height(), function, pixels_of,
                                new_target)
        if image is None:
            return None
        return image, False

    def _group_hierarchy(self) -> tuple:
        """Structural bookkeeping around groups that never varies by tile.

        `_tile_projection_layers` used to rebuild this - which group exists,
        its parent/child tree, and every layer's stack index - from scratch
        for EVERY dirty tile handled in a frame. A single big brush stroke on
        a grouped document can dirty dozens of tiles at once, each redoing an
        O(groups + layers) rebuild for data that's identical across all of
        them. _ensure_projection now builds this once per frame and threads
        it through instead.
        """
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
        return group_by_id, children, roots, positions

    def _tile_projection_layers(self, tx: int, ty: int, rect: QRect,
                                hierarchy: tuple | None = None):
        """Build projection entries, isolating and caching each layer group.

        `hierarchy`, when supplied by a caller processing several tiles from
        the same frame (see _ensure_projection), is `_group_hierarchy()`
        computed once up front instead of re-derived here on every tile.
        """
        document = self.document
        if hierarchy is None:
            hierarchy = self._group_hierarchy()
        group_by_id, children, roots, positions = hierarchy

        def members(group):
            result = [positions[layer_id] for layer_id in group.layer_ids if layer_id in positions]
            if not result or result != list(range(min(result), max(result) + 1)):
                raise ValueError("Les groupes doivent contenir une plage contiguë")
            return result

        def adjustment_tile(layer):
            """Return (entry-or-None, pending) for an adjustment layer on this tile."""
            mask = None
            mask_store = getattr(layer, "alpha_mask_store", None)
            if (mask_store is not None and not getattr(layer, "mask_disabled", False)
                    and mask_store.has_tile(tx, ty)):
                if not mask_store.tile_is_resident(tx, ty):
                    mask_store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                    return None, True
                mask = mask_store.tile(tx, ty)
            return adjustment_entry(layer, mask), False

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
                tuple(sorted((str(k), repr(v)) for k, v in group.blend_parameters.items())),
                bool(getattr(group, "mask_disabled", False)),
                getattr(getattr(group, "alpha_mask_store", None),
                        "tile_revision", lambda *_: 0)(tx, ty)]
            base_visible = [True]
            position = min(group_members)
            while position <= max(group_members):
                child = child_starts.get(position)
                if child is not None:
                    child_tile, child_pending, child_signature = render_group(child)
                    tiles.extend(hide_clipped_over_hidden_base([child_tile], base_visible))
                    pending |= child_pending
                    signature.append(child_signature)
                    position = max(members(child)) + 1
                    continue
                if position not in covered:
                    layer = document.layers[position]
                    if getattr(layer, "layer_kind", "raster") == "adjustment":
                        entry, child_pending = adjustment_tile(layer)
                        child_tiles = hide_clipped_over_hidden_base(
                            [entry] if entry is not None else [], base_visible)
                    else:
                        child_tiles, child_pending = self._projection_tile_for_layer(layer, tx, ty, rect)
                        child_tiles = hide_clipped_over_hidden_base(child_tiles, base_visible)
                    tiles.extend(child_tiles)
                    pending |= child_pending
                    if (str(getattr(layer, "layer_kind", "raster")) == "raster"
                            and not layer.tile_store.has_tile(tx, ty)):
                        # No pixels here: its visibility/opacity cannot change this tile.
                        signature.append((layer.id, None, bool(getattr(layer, "clipping", False))))
                        position += 1
                        continue
                    signature.append((layer.id, layer.visible, float(layer.opacity), layer.blend_mode,
                                      bool(getattr(layer, "clipping", False)),
                                      tuple(sorted((str(k), repr(v)) for k, v in layer.blend_parameters.items())),
                                      str(getattr(layer, "layer_kind", "raster")),
                                      repr(getattr(layer, "adjustment", None)),
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
                image = composite_layers(rect.width(), rect.height(),
                                         resolve_stack(tiles, rect.width(), rect.height()))
                group.store_tile(tile_key, group_signature, image)
            mask_store = getattr(group, "alpha_mask_store", None)
            if (mask_store is not None and not getattr(group, "mask_disabled", False)
                    and mask_store.has_tile(tx, ty)):
                if not mask_store.tile_is_resident(tx, ty):
                    mask_store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                    return ProjectionLayer(QImage(), False, 0.0, "normal", {}), True, group_signature
                masked = clone_image_native(image)
                if masked is None or not apply_alpha_mask_native(masked, mask_store.tile(tx, ty)):
                    raise RuntimeError("CreativeCore refused to apply the group alpha mask")
                image = masked
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
        base_visible = [True]
        index = 0
        while index < len(document.layers):
            group = roots_by_start.get(index)
            if group is None and index not in root_coverage:
                layer = document.layers[index]
                if getattr(layer, "layer_kind", "raster") == "adjustment":
                    entry, pending = adjustment_tile(layer)
                    items = hide_clipped_over_hidden_base(
                        [entry] if entry is not None else [], base_visible)
                else:
                    items, pending = self._projection_tile_for_layer(layer, tx, ty, rect)
                    items = hide_clipped_over_hidden_base(items, base_visible)
                missing |= pending
                entries.extend(items)
                index += 1
                continue
            if group is not None:
                entry, pending, _signature = render_group(group)
                missing |= pending
                # Kept even when hidden: resolve_stack drops it together with
                # the layers clipped onto the folder.
                entries.extend(hide_clipped_over_hidden_base([entry], base_visible))
                index = max(members(group)) + 1
            else:
                index += 1
        if missing:
            return entries, missing
        return resolve_stack(entries, rect.width(), rect.height()), missing

    def _projection_tile_for_layer(self, layer, tx: int, ty: int, rect: QRect):
        store = layer.tile_store
        # A TransformState is render-time metadata: source tiles are never
        # rewritten. Its cache is full-document for correctness across tile
        # boundaries; the projection still uploads only this requested tile.
        if getattr(layer, "transform_state", None):
            image = layer.render_image().copy(rect)
            return [ProjectionLayer(image, layer.visible, float(layer.opacity),
                                    str(layer.blend_mode), dict(layer.blend_parameters),
                                    bool(getattr(layer, "clipping", False)), False)], False
        if store.has_tile(tx, ty) and not store.tile_is_resident(tx, ty):
            store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
            return [], True
        if store.has_tile(tx, ty):
            image = store.tile(tx, ty)
        else:
            # Shared read-only transparent tile: compositors never write to
            # their inputs, and a masked layer clones it below.
            blanks = self.__dict__.setdefault("_blank_projection_tiles", {})
            key = (rect.width(), rect.height())
            image = blanks.get(key)
            if image is None:
                image = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32)
                if not fill_image_native(image, QColor(0, 0, 0, 0)):
                    raise RuntimeError("CreativeCore is required to clear projection tiles")
                blanks[key] = image
        mask_store = getattr(layer, "alpha_mask_store", None)
        if (mask_store is not None and not getattr(layer, "mask_disabled", False)
                and mask_store.has_tile(tx, ty)):
            if not mask_store.tile_is_resident(tx, ty):
                mask_store.request_tile_async(tx, ty, self._on_scratch_tile_ready)
                return [], True
            mask = mask_store.tile(tx, ty)
            image = clone_image_native(image)
            if image is None or mask.size() != image.size() or not apply_alpha_mask_native(image, mask):
                raise RuntimeError("CreativeCore refused to apply the projection alpha mask")
        return [ProjectionLayer(image, layer.visible, float(layer.opacity),
                                str(layer.blend_mode), dict(layer.blend_parameters),
                                bool(getattr(layer, "clipping", False)),
                                not store.has_tile(tx, ty))], False

    def _commit_layer_cache_for_render(self, layer, index: int) -> None:
        """Flush legacy pixels while retaining the active brush buffer mid-stroke."""
        keep_buffer = self.drawing and index == self.document.active_layer_index
        layer.commit_image_cache(release=not keep_buffer)

    def _publish_projection_frame(self) -> bool:
        """Publish a complete viewport, never a mix of old/new tile results."""
        if (getattr(self, "_projection_scan_pending", False)
                or self._projection_waiting_visible):
            return False
        visible = self._projection_publish_keys
        if (not visible or not visible.issubset(self._projection_ready_tiles)
                or not visible.issubset(self._projection_tile_signatures)):
            return False
        pending = self._projection_pending_images
        keys = visible.intersection(pending)
        if keys:
            writes = [(tx, ty, pending[(tx, ty)]) for tx, ty in keys]
            if not self.projection_store.set_tiles_batch(writes):
                return False
            for key in keys:
                pending.pop(key, None)
        first_frame = not self._projection_display_ready
        self._projection_display_ready = True
        self._projection_idle_key = getattr(self, "_projection_current_key", None)
        self._projection_idle_revision = self.projection_store._mutation_count
        if keys or first_frame:
            # Whole-viewport repaint: old pixels remain visible until all
            # replacements have been committed together above.
            self.update()
        return True

    def _on_projected_tile(self, generation: int, tx: int, ty: int, image) -> None:
        key = (tx, ty)
        if self._projection_tile_generation.get(key) != generation:
            return
        self._projection_pending_images[key] = image
        self._projection_ready_tiles.add(key)
        manager = getattr(self, "tile_cache_manager", None)
        if manager is not None:
            manager.mark_ready(key)
        getattr(self, "_tile_loading_since", {}).pop(key, None)
        self._projection_waiting_visible.discard(key)
        if key in self._projection_publish_keys:
            self._publish_projection_frame()

    def _on_projection_failed(self, generation: int, tx: int, ty: int, error: str) -> None:
        key = (tx, ty)
        if self._projection_tile_generation.get(key) != generation:
            return
        self._projection_tile_signatures.pop(key, None)
        self._projection_ready_tiles.discard(key)
        self._projection_pending_images.pop(key, None)
        print(f"Projection de tuile ({tx}, {ty}) impossible : {error}")

    def _layer_static_signature(self, layer) -> tuple:
        """The parts of a layer's projection signature that never vary by tile.

        Everything here (opacity, blend mode, clipping, adjustment, ...) is the
        same for every tile of the document at a given moment - only the two
        tile-revision numbers in _projection_signature_for actually depend on
        (tx, ty). Splitting it out lets a caller checking many tiles in one
        frame (_ensure_projection) build this once per layer instead of once
        per layer PER TILE.
        """
        return (layer.id, layer.visible, float(layer.opacity), str(layer.blend_mode),
                bool(getattr(layer, "clipping", False)),
                tuple(sorted((str(k), repr(v)) for k, v in layer.blend_parameters.items())),
                str(getattr(layer, "layer_kind", "raster")),
                repr(getattr(layer, "adjustment", None)))

    def _groups_static_signature(self) -> tuple:
        """Groups never carry per-tile state, so this is always frame-constant."""
        return tuple((group.id, group.name, tuple(group.layer_ids), group.visible,
                      float(group.opacity), group.blend_mode,
                      tuple(sorted((str(k), repr(v)) for k, v in group.blend_parameters.items())))
                     for group in self.document.layer_groups)

    @staticmethod
    def _store_revision_map(store):
        """{(tx, ty): revision} of a store in one native call, or None (fallback)."""
        if store is None:
            return {}
        getter = getattr(store, "resident_revisions", None)
        revisions = getter() if callable(getter) else None
        if revisions is None:
            return None
        revisions = dict(revisions)
        for key in tuple(getattr(store, "_swapped", ()) or ()):
            revisions[key] = store.tile_revision(*key)
        return revisions

    def _tile_signature_index(self, layer_static, groups_static, revision_maps):
        """Per-frame index -> signature(tx, ty), or None to use the slow path.

        Instead of walking every layer for every tile (80 layers x 2600 tiles
        per frame), each layer's occupied tiles are visited once and grouped
        by tile.  A tile's signature then only lists the layers that actually
        have pixels there (plus adjustment layers, which act everywhere).
        Layer metadata is folded in as a hash so the big adjustment payloads
        (3D LUTs) are never compared tile by tile.
        """
        layers = self.document.layers
        if len(revision_maps) != len(layers):
            return None
        present: dict = {}
        everywhere = []
        for index, (layer, static, (colors, masks)) in enumerate(zip(layers, layer_static,
                                                                     revision_maps)):
            if colors is None or masks is None:
                return None
            static_key = hash(static)
            if static[6] != "raster":
                everywhere.append((index, static_key, masks))
                continue
            for key, revision in colors.items():
                present.setdefault(key, []).append((index, static_key, revision, masks.get(key, 0)))
        frame = (hash(groups_static), len(layers),
                 tuple(bool(static[4]) for static in layer_static))
        empty = ()

        def signature(tx: int, ty: int):
            key = (tx, ty)
            return (frame, tuple(present.get(key, empty)),
                    tuple((index, static_key, masks.get(key, 0))
                          for index, static_key, masks in everywhere))
        return signature

    def _tile_signature_direct(self, layer_static, groups_static, revision_maps):
        """Same signatures as _tile_signature_index, computed per tile on demand.

        Used after an incremental (painting) update where only a few tiles
        need a new signature: no full per-frame index is rebuilt.
        """
        layers = self.document.layers
        static_keys = [hash(static) for static in layer_static]
        raster = [static[6] == "raster" for static in layer_static]
        everywhere = [(index, static_keys[index], masks)
                      for index, (colors, masks) in enumerate(revision_maps)
                      if not raster[index]]
        frame = (hash(groups_static), len(layers),
                 tuple(bool(static[4]) for static in layer_static))

        def signature(tx: int, ty: int):
            key = (tx, ty)
            present = tuple((index, static_keys[index], colors[key], masks.get(key, 0))
                            for index, (colors, masks) in enumerate(revision_maps)
                            if raster[index] and key in colors)
            return (frame, present,
                    tuple((index, static_key, masks.get(key, 0))
                          for index, static_key, masks in everywhere))
        return signature

    def _projection_signature_for(self, tx: int, ty: int,
                                  layer_static: list[tuple] | None = None,
                                  groups_static: tuple | None = None,
                                  revision_maps: list | None = None) -> tuple:
        """Per-tile cache-comparison key.

        `layer_static`/`groups_static` let a caller that is about to check many
        tiles in the same frame (_ensure_projection) precompute the
        tile-independent metadata once and pass it in here, instead of this
        method re-deriving it (including several `repr()`/`sorted()` calls per
        layer) for every single tile. Callers that only need one tile (the
        eyedropper colour sampler) can omit both and it falls back to
        deriving them itself, unchanged from before.
        """
        if layer_static is None:
            layer_static = [self._layer_static_signature(layer) for layer in self.document.layers]
        if groups_static is None:
            groups_static = self._groups_static_signature()
        if revision_maps is not None and len(revision_maps) == len(self.document.layers):
            key = (tx, ty)
            layers = []
            for layer, static, (colors, masks) in zip(self.document.layers, layer_static,
                                                      revision_maps):
                if colors is not None and key not in colors and static[6] == "raster":
                    # No pixels on this tile: toggling or fading the layer must
                    # not invalidate it (only the layer's own tiles recompute).
                    layers.append((static[0], None, static[4]))
                    continue
                color = (colors.get(key, 0) if colors is not None
                         else layer.tile_store.tile_revision(tx, ty))
                if masks is not None:
                    mask = masks.get(key, 0)
                else:
                    mask = layer.alpha_mask_store.tile_revision(tx, ty)
                layers.append((static, color, mask))
            return tuple(layers), groups_static
        layers = tuple(
            (static, layer.tile_store.tile_revision(tx, ty),
             (getattr(getattr(layer, "alpha_mask_store", None),
                      "tile_revision", lambda *_: 0)(tx, ty)))
            for layer, static in zip(self.document.layers, layer_static)
        )
        return layers, groups_static

    def visible_document_tile_keys(self, margin_tiles: int = 0) -> set[tuple[int, int]]:
        """Conservative document-space tile bounds for the viewport.

        ``margin_tiles`` is a bounded look-ahead cache around the viewport;
        it is used only for asynchronous projection and never changes what is
        drawn or saved.
        """
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
        margin = max(0, int(margin_tiles)) * TILE_SIZE
        left = max(0, math.floor(min(p[0] for p in corners)) - margin)
        top = max(0, math.floor(min(p[1] for p in corners)) - margin)
        right = min(self.document.width, math.ceil(max(p[0] for p in corners)) + margin)
        bottom = min(self.document.height, math.ceil(max(p[1] for p in corners)) + margin)
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

    def gpu_stats_snapshot(self, reset: bool = False) -> dict[str, int]:
        """Expose transfer and shader-composition counters for diagnostics."""
        stats = self.gpu_renderer.transfer_stats_snapshot(reset=reset)
        compositor = getattr(self, "gpu_tile_compositor", None)
        if compositor is not None:
            for key, value in compositor.frame_stats.items():
                stats[f"gpu_{key}"] = int(value)
            if reset:
                for key in compositor.frame_stats:
                    compositor.frame_stats[key] = 0
        return stats

    def _record_input_event(self) -> None:
        self._pending_input_ns = time.perf_counter_ns()

    def _record_paint_start(self) -> None:
        if self._pending_input_ns is not None:
            self._input_to_paint_ms.append(
                (time.perf_counter_ns() - self._pending_input_ns) / 1_000_000.0
            )
            self._pending_input_ns = None

    @staticmethod
    def _timing_summary(values) -> dict[str, float | int]:
        samples = sorted(values)
        if not samples:
            return {"samples": 0, "average_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        p95 = samples[min(len(samples) - 1, max(0, int(len(samples) * .95) - 1))]
        return {"samples": len(samples), "average_ms": round(sum(samples) / len(samples), 3),
                "p95_ms": round(p95, 3), "max_ms": round(samples[-1], 3)}

    def performance_stats_snapshot(self, reset: bool = False) -> dict:
        """Input-to-render, brush and projection-cache diagnostics.

        This is deliberately data only: the normal UI stays free of a costly
        live profiler while a real tablet test can identify the slow path.
        """
        result = {
            "input_to_paint": self._timing_summary(self._input_to_paint_ms),
            "native_brush_segment": self._timing_summary(self._brush_segment_ms),
            "projection_cache": dict(self._projection_cache_stats),
            "tile_cache": self.tile_cache_manager.snapshot(),
            "budget_ms": {"target": 8.0, "warning": 16.0, "unacceptable": 40.0},
        }
        if reset:
            self._input_to_paint_ms.clear()
            self._brush_segment_ms.clear()
            for key in self._projection_cache_stats:
                self._projection_cache_stats[key] = 0
        return result

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
        self._cancel_async_brush()
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

        # Alt maintenu = pipette temporaire (comme Photoshop) : relâcher Alt
        # revient à l'outil précédent, avec la couleur prélevée.
        if (key == Qt.Key.Key_Alt and not self.drawing
                and self.tools.current_tool in self.ALT_PICKER_TOOLS
                and getattr(self, "_alt_return_tool", None) is None):
            self._alt_return_tool = self.tools.current_tool
            self._alt_return_eraser = bool(self.tools.brush.eraser)
            # Tool switching has per-tool brush profiles. Keep an in-memory
            # copy because QSettings may deserialize a profile lazily (or not
            # at all on some Linux backends), which otherwise falls back to
            # DEFAULT_BRUSH_SETTINGS when Alt is released.
            self._alt_return_brush_settings = self.brush_settings.snapshot()
            self._alt_return_preset_name = self.get_cpp_brush_preset_name()
            self._alt_picker_sampled = False
            self.tools.set_picker()
            event.accept()
            return

        if self.free_transform is not None:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.commit_free_transform()
                event.accept()
                return
            if key == Qt.Key.Key_Escape:
                self.cancel_free_transform()
                event.accept()
                return
            arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                      Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
            if key in arrows:
                step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
                dx, dy = arrows[key]
                self.free_transform.nudge(dx * step, dy * step)
                self.update()
                event.accept()
                return

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

    ALT_PICKER_TOOLS = frozenset({"brush", "eraser", "smudge", "blur", "sharpen", "clone_stamp",
                                  "fill", "gradient", "line", "rectangle", "ellipse", "bezier",
                                  "pixel", "pixel_eraser"})

    def _restore_alt_picker(self) -> bool:
        previous = getattr(self, "_alt_return_tool", None)
        if previous is None:
            return False
        self._alt_return_tool = None
        eraser = bool(getattr(self, "_alt_return_eraser", previous == "eraser"))
        self._alt_return_eraser = None
        settings = getattr(self, "_alt_return_brush_settings", None)
        preset_name = getattr(self, "_alt_return_preset_name", None)
        sampled = bool(getattr(self, "_alt_picker_sampled", False))
        self._alt_return_brush_settings = None
        self._alt_return_preset_name = None
        self._alt_picker_sampled = False
        # Restore the captured tool even if another input event occurred
        # while Alt was held; the old conditional could leave ToolManager on
        # its default brush.
        self.tools._select_tool(previous, eraser=eraser)
        if isinstance(settings, dict):
            # The picker may legitimately have changed only the colour. All
            # other dynamics/tip settings belong to the original brush.
            if sampled:
                settings = dict(settings)
                settings["color"] = self.brush_settings.get("color")
            self.brush_settings.update(settings)
            self._current_cpp_brush_preset_name = preset_name
            QSettings("CreativeSystem", "CreativeSystem").setValue(
                f"brush/tool_settings/{previous}", self.brush_settings.snapshot())
        return True

    def focusOutEvent(self, event) -> None:
        # Alt+Tab ou perte de focus pendant Alt : ne jamais rester bloqué en pipette.
        self._restore_alt_picker()
        self.space_pressed = False
        self.panning = False
        self.update()
        super().focusOutEvent(event)

    def keyReleaseEvent(
        self,
        event: QKeyEvent
    ) -> None:

        if event.isAutoRepeat():
            return

        if event.key() == Qt.Key.Key_Alt and self._restore_alt_picker():
            event.accept()
            return

        if (
            event.key()
            == Qt.Key.Key_Space
        ):

            self.space_pressed = False
            self.panning = False

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

        if event.button() == Qt.MouseButton.LeftButton:
            self.live_stroke_preview.press(event.position(), 1.0)

        # ── Assistant build mode: left-click places handles ───────────────────
        if (event.button() == Qt.MouseButton.LeftButton
                and self.assistants.is_building()):
            image_pos = self.screen_to_image(event.position())
            from PySide6.QtCore import QPointF as _QPointF
            building = [a for a in self.assistants.assistants()
                        if len(a.handles) < a.HANDLES_NEEDED]
            done = self.assistants.build_click(_QPointF(image_pos))
            if building:
                a = building[0]
                self.assistant_build_step.emit(len(a.handles), a.HANDLES_NEEDED)
            self.update()
            event.accept()
            return

        if (event.button() == Qt.MouseButton.RightButton
                and self.right_click_color_picker
                and self.tools.current_tool != "zoom_view"):
            if self.popup_palette is not None:
                self.popup_palette.show_at(event.globalPosition().toPoint())
            else:
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
            self.select_magic_wand_at(event.position(), modifiers)
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
        # OUTIL TRANSFORMER (Free Transform session)
        # -----------------------------------------------------

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tools.current_tool == "transform"
        ):
            layer = self.get_active_layer()
            if self.free_transform is not None and self.free_transform.layer is not layer:
                self.commit_free_transform()
            if self.free_transform is None and not self.start_free_transform():
                event.accept()
                return
            position = self.screen_to_image_f(event.position())
            handle = self.free_transform.hit_test(position, self.zoom)
            self.free_transform.begin_drag(handle, position)
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
                self._apply_filter_segment(
                    layer.image, self.last_point, self.last_point, 1.0, 1.0,
                    self.tools.current_tool == "sharpen",
                )
                event.accept()
                return

            if self._cpp_active():
                if self.tools.current_tool == "clone_stamp":
                    cpp_image = self._cpp_begin_clone_stroke(self.get_active_image() or layer.image, self.last_point, 1.0)
                else:
                    cpp_image = self._cpp_begin_stroke(self.get_active_image() or layer.image, self.last_point, 1.0)

                if cpp_image is not None:
                    dirty_rect = self._brush_dirty_rect(self.last_point, self.last_point)
                    if getattr(layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    if self._editing_alpha_mask_layer_id != layer.id:
                        layer.adopt_image_cache(cpp_image)
                    else:
                        self._editing_alpha_mask_image = cpp_image
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

        self._record_input_event()

        if self._ignore_tablet_synthetic_mouse(event):
            event.accept()
            return

        self.live_stroke_preview.move(event.position(), 1.0)
        previous_cursor_position = QPointF(self.cursor_position)
        self.cursor_position = (
            event.position()
        )

        self.cursor_visible = True

        if self.free_transform is not None and self.tools.current_tool == "transform":
            position = self.screen_to_image_f(event.position())
            if self.free_transform.drag_handle:
                modifiers = event.modifiers()
                self.free_transform.update_drag(
                    position,
                    bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                    bool(modifiers & Qt.KeyboardModifier.AltModifier),
                )
                self.update()
                event.accept()
                return
            handle = self.free_transform.hit_test(position, self.zoom)
            self.setCursor(FREE_TRANSFORM_CURSORS.get(handle, Qt.CursorShape.ArrowCursor))

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
            stroke_previous_point = self.last_point

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

            # Compute the dirty rect once — used by both the lock-alpha restore and
            # the repaint below, avoiding two extra snapshot() + bbox calculations.
            dirty_rect = self._brush_dirty_rect(self.last_point, current_point)

            if self.tools.current_tool in ("blur", "sharpen"):
                active_layer = self.get_active_layer()
                if active_layer is not None:
                    self._apply_filter_segment(
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
            self._repaint_brush_dirty_rect(dirty_rect)
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

        if event.button() == Qt.MouseButton.LeftButton:
            self.live_stroke_preview.release()

        if (event.button() == Qt.MouseButton.LeftButton and self.free_transform is not None
                and self.free_transform.drag_handle):
            self.free_transform.end_drag()
            self.update()
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

        if event.button() == Qt.MouseButton.LeftButton and self.panning:
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

        self._record_input_event()

        self._last_tablet_event_time = time.monotonic()

        self.setFocus()

        pressure_value = event.pressure() if self.tablet_pressure_enabled else 1.0
        current_tilt = (float(event.xTilt()), float(event.yTilt()))

        self.cursor_position = (
            event.position()
        )

        _tablet_type = event.type()
        if _tablet_type == QTabletEvent.Type.TabletPress:
            self.live_stroke_preview.press(event.position(), pressure_value)
        elif _tablet_type == QTabletEvent.Type.TabletMove:
            self.live_stroke_preview.move(event.position(), pressure_value)
        elif _tablet_type == QTabletEvent.Type.TabletRelease:
            self.live_stroke_preview.release()

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

        if self.tools.current_tool == "transform":
            # Pen input: Qt's synthesized mouse events are dropped right after
            # tablet input, so the transform tool must handle the pen itself.
            event_type = event.type()
            position = self.screen_to_image_f(event.position())
            modifiers = event.modifiers()
            if event_type == QTabletEvent.Type.TabletPress:
                layer = self.get_active_layer()
                if self.free_transform is not None and self.free_transform.layer is not layer:
                    self.commit_free_transform()
                if self.free_transform is not None or self.start_free_transform():
                    self.free_transform.begin_drag(
                        self.free_transform.hit_test(position, self.zoom), position)
            elif self.free_transform is not None:
                if event_type == QTabletEvent.Type.TabletMove and self.free_transform.drag_handle:
                    self.free_transform.update_drag(
                        position,
                        bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                        bool(modifiers & Qt.KeyboardModifier.AltModifier))
                elif event_type == QTabletEvent.Type.TabletMove:
                    handle = self.free_transform.hit_test(position, self.zoom)
                    self.setCursor(FREE_TRANSFORM_CURSORS.get(handle, Qt.CursorShape.ArrowCursor))
                elif event_type == QTabletEvent.Type.TabletRelease:
                    self.free_transform.end_drag()
            self.update()
            event.accept()
            return

        if (self.tools.current_tool == "magic_wand"
                and event.type() == QTabletEvent.Type.TabletPress):
            self.select_magic_wand_at(event.position(), event.modifiers())
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

            if self._can_use_async_brush(layer) and self._begin_async_brush(layer, position, pressure):
                preview_settings = self.brush_settings.snapshot()
                # GPUInstancedStrokeRenderer.begin_preview() is a GPU-only
                # APPROXIMATION - it zeroes wetness/pickup/dilution/smudge
                # and forces roundness=1/blendMode=Normal before drawing a
                # single flat round dab (see gpu_instanced_stroke.py). While
                # it's active, paintGL renders the ENTIRE layer from that
                # preview FBO instead of the real tile_store
                # (texture_override_id in paintGL) - so for the whole
                # duration of a wet-mix or smudge stroke, every dab
                # CreativeCore's async worker has already computed and
                # written for real (_apply_async_brush_patch runs live,
                # per-patch, the whole time) stays completely hidden behind
                # this flat stand-in, only appearing once the stroke ends
                # and the override is released. That is exactly "je fais un
                # masque et j'ai le final au levé du stylet" - the real,
                # correct wet-blended pixels were live the entire time, they
                # just were never shown. Skipping the preview override for
                # wet-mix/smudge strokes lets the real async patches (which
                # already stream in live) be the only thing on screen, so
                # what's visible during the stroke IS the true result, not
                # an approximation of it.
                wet_mix_active = (
                    bool(preview_settings.get("wetMix"))
                    and float(preview_settings.get("wetness", 0.0) or 0.0) > 0.0
                )
                smudge_active = self.tools.current_tool == "smudge"
                if self.gpu_ready and not wet_mix_active and not smudge_active:
                    self.gpu_instanced_stroke.begin_preview(
                        layer, layer.image, preview_settings, position, pressure,
                        eraser=self.tools.current_tool == "eraser")
                # The preview is queued on the OpenGL canvas; request its
                # first frame now instead of waiting for the next tablet move.
                self.update()
                event.accept()
                return

            if self.tools.current_tool in ("blur", "sharpen"):
                self._apply_filter_segment(
                    layer.image, position, position, pressure, pressure,
                    self.tools.current_tool == "sharpen",
                )
                event.accept()
                return

            if self._cpp_active():
                if self.tools.current_tool == "clone_stamp":
                    cpp_image = self._cpp_begin_clone_stroke(self.get_active_image() or layer.image, position, pressure)
                else:
                    cpp_image = self._cpp_begin_stroke(self.get_active_image() or layer.image, position, pressure)

                if cpp_image is not None:
                    dirty_rect = self._brush_dirty_rect(position, position)
                    if getattr(layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    if self._editing_alpha_mask_layer_id != layer.id:
                        layer.adopt_image_cache(cpp_image)
                    else:
                        self._editing_alpha_mask_image = cpp_image
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

            if self.gpu_instanced_stroke.active and not self.gpu_instanced_stroke.preview_only:
                tablet_previous_point = self.last_point
                self._queue_instanced_stroke_segment(
                    self.last_point, position, start_pressure, pressure
                )
                self.tools.brush.pressure = pressure
                self.last_point = position
                self._last_tablet_tilt = current_tilt
                self._repaint_brush_dirty_rect(
                    self._brush_dirty_rect(tablet_previous_point, position)
                )
                event.accept()
                return

            if self._async_brush_handle is not None:
                self._queue_async_brush(self.last_point, position, start_pressure, pressure,
                                        self._last_tablet_tilt, current_tilt)
                if self.gpu_instanced_stroke.active:
                    self._queue_instanced_stroke_segment(self.last_point, position, start_pressure, pressure)
                    self.update()
                self.tools.brush.pressure = pressure
                self.last_point = position
                self._last_tablet_tilt = current_tilt
                event.accept()
                return

            # Compute the dirty rect once — reused by lock-alpha restore,
            # sync_gpu_layer, and the repaint below.
            dirty_rect = self._brush_dirty_rect(self.last_point, position)

            if self.tools.current_tool in ("blur", "sharpen"):
                active_layer = self.get_active_layer()
                if active_layer is not None:
                    self._apply_filter_segment(
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
                    if active_layer is not None and getattr(active_layer, "lock_alpha", False):
                        self._restore_locked_alpha(cpp_image, dirty_rect)
                    self.sync_gpu_layer(dirty_rect)
                else:
                    self._cpp_end_stroke()
            else:
                self._cpp_end_stroke()

            self.tools.brush.pressure = pressure

            tablet_previous_point = self.last_point
            self.last_point = position
            self._last_tablet_tilt = current_tilt

            self._repaint_brush_dirty_rect(dirty_rect)

        elif (
            event.type()
            == QTabletEvent.Type.TabletRelease
        ):

            if self.drawing:
                if self._async_brush_handle is not None:
                    self.cpp_brush_library.cs_brush_async_finish(self._async_brush_handle)
                    for _sh, _tsx, _tsy in self._async_symmetry_handles:
                        self.cpp_brush_library.cs_brush_async_finish(_sh)
                    if self.gpu_instanced_stroke.active:
                        self.gpu_instanced_stroke.request_finish()
                elif self.gpu_instanced_stroke.active:
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
