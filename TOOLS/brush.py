from PySide6.QtGui import QColor
from types import SimpleNamespace

from TOOLS.brush_smoothing import BrushSmoothing


class Brush:

    def __init__(self) -> None:

        # =====================================================
        # PROPRIÉTÉS DE BASE
        # =====================================================

        self.color: QColor = QColor(
            0,
            0,
            0,
        )

        self.size: float = 10.0

        self.opacity: float = 1.0

        self.flow: float = 1.0

        self.pressure: float = 1.0

        self.pressure_size: float = 1.0

        self.pressure_opacity: float = 0.0

        self.pressure_flow: float = 0.0

        self.minimum_size: float = 0.1

        self.spacing: float = 0.15

        self.hardness: float = 0.35

        self.eraser: bool = False

        self.antialiasing: bool = True

        # =====================================================
        # STABILISATION
        # =====================================================

        self.smoothing: float = 0.0
        # ``none`` is a real mode, rather than just a zero-valued slider:
        # changing the global smoothing amount must not unexpectedly turn a
        # deliberately disabled stabilizer back on.
        self.smoothing_mode: str = "basic"

        self.smoother = BrushSmoothing(
            strength=self.smoothing,
            buffer_size=6,
        )

        # État léger pour les contrôles d’interface et le bridge. Le rendu et
        # l’évaluation des dynamiques appartiennent exclusivement à CreativeCore.
        self.dynamics = SimpleNamespace(
            pressure_size=1.0, pressure_opacity=0.0, pressure_flow=0.0,
            speed_size=0.0, speed_opacity=0.0, speed_flow=0.0,
            tilt_size=0.0, tilt_opacity=0.0,
            random_size=0.0, random_opacity=0.0,
        )
        self.tip = SimpleNamespace(hardness=0.78)
        self.texture = SimpleNamespace(seed=0)
        self.color_engine = SimpleNamespace(seed=0)
        self.paint = SimpleNamespace()

        # =====================================================
        # PRESSION
        # =====================================================

        self.last_pressure: float = 1.0

        # =====================================================
        # VITESSE
        # =====================================================

        self.speed_sensitivity: float = 0.35

    # =========================================================
    # UTILITAIRES
    # =========================================================

    @staticmethod
    def clamp(
        value: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:

        return max(
            minimum,
            min(
                maximum,
                value,
            ),
        )

    # =========================================================
    # DÉBUT DE TRAIT
    # =========================================================

    def begin_stroke(
        self
    ) -> None:

        self.smoother.begin_stroke()

        self.last_pressure = self.clamp(
            self.pressure,
        )

        self.color_engine.seed += 1

        self.texture.seed += 1

    # =========================================================
    # FIN DE TRAIT
    # =========================================================

    def end_stroke(
        self
    ) -> None:

        self.smoother.end_stroke()

        self.last_pressure = 1.0

    # =========================================================
    # LISSAGE
    # =========================================================

    def set_smoothing(
        self,
        strength: float,
    ) -> None:

        self.smoothing = self.clamp(
            strength,
        )

        self.smoother.set_strength(self.smoothing if self.smoothing_mode != "none" else 0.0)

    def set_smoothing_mode(self, mode: str) -> None:
        """Select the stabilizer response while retaining the user's amount."""
        mode = str(mode).lower()
        self.smoothing_mode = mode if mode in {"none", "basic", "weighted", "stabilize"} else "basic"
        self.smoother.set_mode("basic" if self.smoothing_mode == "none" else self.smoothing_mode)
        self.smoother.set_strength(self.smoothing if self.smoothing_mode != "none" else 0.0)

    # =========================================================
    # SYNCHRONISATION DU MOTEUR
    # =========================================================

    def sync_engine(
        self
    ) -> None:

        self.dynamics.pressure_size = (
            self.pressure_size
        )

        self.dynamics.pressure_opacity = (
            self.pressure_opacity
        )

        self.dynamics.pressure_flow = (
            self.pressure_flow
        )

        self.tip.hardness = (
            self.hardness
        )

    # =========================================================
    # TAILLE
    # =========================================================

    # =========================================================
    # OPACITÉ
    # =========================================================

    def get_opacity(
        self,
        pressure: float | None = None,
    ) -> float:

        if pressure is None:
            pressure = self.pressure

        pressure = self.clamp(
            pressure,
        )

        factor = (
            (1.0 - self.pressure_opacity)
            + pressure
            * self.pressure_opacity
        )

        return self.clamp(
            self.opacity
            * factor
            * self.flow,
        )

    # =========================================================
    # COULEUR
    # =========================================================

    def get_color(
        self,
        pressure: float | None = None,
    ) -> QColor:

        color = QColor(
            self.color,
        )

        color.setAlphaF(
            self.get_opacity(
                pressure,
            ),
        )

        return color

    # =========================================================
    # DESSIN
    # =========================================================

    def draw(
        self,
        image,
        start_point,
        end_point,
    ) -> None:
        raise RuntimeError(
            "Le rendu des traits passe exclusivement par CreativeCore"
        )
