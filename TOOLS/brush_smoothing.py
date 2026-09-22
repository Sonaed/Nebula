import math

from PySide6.QtCore import QPointF


class BrushSmoothing:
    """
    Stabilisateur fluide pour les traits de dessin.

    Fonctionnement :
    - conserve une position cible issue de la tablette ;
    - déplace progressivement la position de sortie vers cette cible ;
    - utilise une composante de vitesse pour garder un mouvement réactif ;
    - évite les gros retards des simples moyennes glissantes.
    """

    def __init__(
        self,
        strength: float = 0.0,
        buffer_size: int = 6
    ) -> None:

        self.strength = self.clamp(
            strength,
            0.0,
            1.0
        )

        self.buffer_size = max(
            2,
            int(buffer_size)
        )

        self.points: list[QPointF] = []

        self.last_output: QPointF | None = None

        self.last_input: QPointF | None = None

        self.velocity_x: float = 0.0
        self.velocity_y: float = 0.0

        self.in_stroke: bool = False

    # =========================================================
    # UTILITAIRES
    # =========================================================

    @staticmethod
    def clamp(
        value: float,
        minimum: float,
        maximum: float
    ) -> float:

        return max(
            minimum,
            min(
                maximum,
                value
            )
        )

    @staticmethod
    def distance(
        first: QPointF,
        second: QPointF
    ) -> float:

        return math.hypot(
            second.x() - first.x(),
            second.y() - first.y()
        )

    # =========================================================
    # CONFIGURATION
    # =========================================================

    def set_strength(
        self,
        strength: float
    ) -> None:

        self.strength = self.clamp(
            strength,
            0.0,
            1.0
        )

    def set_buffer_size(
        self,
        buffer_size: int
    ) -> None:

        self.buffer_size = max(
            2,
            int(buffer_size)
        )

        if len(self.points) > self.buffer_size:

            self.points = self.points[
                -self.buffer_size:
            ]

    # =========================================================
    # DÉBUT DE TRAIT
    # =========================================================

    def begin_stroke(
        self
    ) -> None:

        self.reset()

        self.in_stroke = True

    # =========================================================
    # FIN DE TRAIT
    # =========================================================

    def end_stroke(
        self
    ) -> None:

        self.in_stroke = False

        self.reset()

    # =========================================================
    # RESET
    # =========================================================

    def reset(self) -> None:

        self.points.clear()

        self.last_output = None

        self.last_input = None

        self.velocity_x = 0.0

        self.velocity_y = 0.0

    # =========================================================
    # CALCUL DU LISSAGE
    # =========================================================

    def add_point(
        self,
        point: QPointF
    ) -> QPointF:

        current = QPointF(
            point
        )

        # -----------------------------------------------------
        # Pas de lissage
        # -----------------------------------------------------

        if self.strength <= 0.0:

            self.last_input = QPointF(
                current
            )

            self.last_output = QPointF(
                current
            )

            return QPointF(
                current
            )

        self.points.append(
            current
        )

        if len(self.points) > self.buffer_size:

            self.points.pop(
                0
            )

        # -----------------------------------------------------
        # Premier point
        # -----------------------------------------------------

        if self.last_input is None:

            self.last_input = QPointF(
                current
            )

            self.last_output = QPointF(
                current
            )

            return QPointF(
                current
            )

        # -----------------------------------------------------
        # Mouvement brut de la tablette
        # -----------------------------------------------------

        input_dx = (
            current.x()
            - self.last_input.x()
        )

        input_dy = (
            current.y()
            - self.last_input.y()
        )

        input_distance = math.hypot(
            input_dx,
            input_dy
        )

        # -----------------------------------------------------
        # Vitesse filtrée
        # -----------------------------------------------------

        velocity_mix = (
            0.55
            + self.strength * 0.25
        )

        self.velocity_x = (
            self.velocity_x
            * (1.0 - velocity_mix)
            + input_dx
            * velocity_mix
        )

        self.velocity_y = (
            self.velocity_y
            * (1.0 - velocity_mix)
            + input_dy
            * velocity_mix
        )

        # -----------------------------------------------------
        # Réactivité
        #
        # Plus le lissage est élevé, plus la position est
        # stabilisée. La vitesse permet de récupérer une partie
        # du mouvement et d'éviter une sensation de retard.
        # -----------------------------------------------------

        smoothing = self.clamp(
            self.strength,
            0.0,
            1.0
        )

        responsiveness = (
            0.72
            - smoothing * 0.48
        )

        responsiveness = self.clamp(
            responsiveness,
            0.18,
            0.72
        )

        # -----------------------------------------------------
        # Grand mouvement :
        # on augmente automatiquement la réactivité.
        #
        # Cela évite que les déplacements rapides soient
        # trop freinés.
        # -----------------------------------------------------

        if input_distance > 20.0:

            responsiveness += min(
                0.20,
                input_distance / 250.0
            )

            responsiveness = self.clamp(
                responsiveness,
                0.18,
                0.88
            )

        # -----------------------------------------------------
        # Position cible
        #
        # Une petite prédiction basée sur la vitesse permet
        # de suivre naturellement les changements de direction.
        # -----------------------------------------------------

        prediction = (
            0.18
            + smoothing * 0.12
        )

        target_x = (
            current.x()
            + self.velocity_x * prediction
        )

        target_y = (
            current.y()
            + self.velocity_y * prediction
        )

        # -----------------------------------------------------
        # Position précédente
        # -----------------------------------------------------

        if self.last_output is None:

            self.last_output = QPointF(
                current
            )

        # -----------------------------------------------------
        # Mouvement vers la cible
        # -----------------------------------------------------

        output_x = (
            self.last_output.x()
            + (
                target_x
                - self.last_output.x()
            )
            * responsiveness
        )

        output_y = (
            self.last_output.y()
            + (
                target_y
                - self.last_output.y()
            )
            * responsiveness
        )

        output = QPointF(
            output_x,
            output_y
        )

        # -----------------------------------------------------
        # Petite correction contre les micro-tremblements
        # -----------------------------------------------------

        micro_motion = 0.45 * smoothing

        if input_distance < 3.0:

            output = QPointF(
                output.x()
                * (1.0 - micro_motion)
                + self.last_output.x()
                * micro_motion,

                output.y()
                * (1.0 - micro_motion)
                + self.last_output.y()
                * micro_motion
            )

        # -----------------------------------------------------
        # Mise à jour
        # -----------------------------------------------------

        self.last_input = QPointF(
            current
        )

        self.last_output = QPointF(
            output
        )

        return QPointF(
            output
        )

    # =========================================================
    # TRAITEMENT D'UNE LISTE DE POINTS
    # =========================================================

    def smooth_points(
        self,
        points: list[QPointF]
    ) -> list[QPointF]:

        self.begin_stroke()

        smoothed: list[QPointF] = []

        for point in points:

            smoothed.append(
                self.add_point(
                    point
                )
            )

        self.end_stroke()

        return smoothed
