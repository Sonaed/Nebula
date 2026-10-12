"""Brush stabiliser — three modes like Krita.

Modes
-----
basic
    The original inertia-based smoother.  Fast, low latency.  Good for
    general painting.

weighted
    A weighted-average smoother: the output position is pulled toward the
    target with a weight inversely proportional to distance.  Produces the
    characteristic "rope-pull" feel of Krita's *Weighted* stabilizer —
    lines are very smooth with no visible jitter even at low speeds.

stabilize
    A sample-accumulation stabilizer that holds the emitted point until the
    accumulated average has moved at least *min_dist* pixels.  Krita's
    *Stabilize* mode — extremely smooth but with a noticeable delay tail
    that must be flushed on pen-lift.
"""
from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def _lerp_pt(a: QPointF, b: QPointF, t: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * t,
                   a.y() + (b.y() - a.y()) * t)


# ─────────────────────────────────────────────────────────────────────────────
# BrushSmoothing
# ─────────────────────────────────────────────────────────────────────────────

class BrushSmoothing:
    """Plug-in stabiliser used by the canvas stroke pipeline.

    Parameters
    ----------
    strength:    0.0 = pass-through, 1.0 = maximum smoothing.
    buffer_size: sample buffer depth for *basic* mode.
    mode:        "basic" | "weighted" | "stabilize"
    """

    # ── initialise ────────────────────────────────────────────────────────────

    def __init__(
        self,
        strength: float = 0.0,
        buffer_size: int = 6,
        mode: str = "basic",
    ) -> None:
        self.strength = self.clamp(strength, 0.0, 1.0)
        self.buffer_size = max(2, int(buffer_size))
        self.mode = mode if mode in ("basic", "weighted", "stabilize") else "basic"

        # basic mode: fixed-length FIFO; deque auto-evicts oldest when full
        self.points: deque[QPointF] = deque(maxlen=self.buffer_size)
        self.last_output: QPointF | None = None
        self.last_input: QPointF | None = None
        self.velocity_x: float = 0.0
        self.velocity_y: float = 0.0
        self.in_stroke: bool = False

        # weighted mode state
        self._w_ghost: QPointF | None = None   # the "rope end" that the stroke follows

        # stabilize mode state
        self._stab_buf: deque[QPointF] = deque()
        self._stab_sx: float = 0.0             # running sum of x — avoids O(n) pass
        self._stab_sy: float = 0.0             # running sum of y — avoids O(n) pass
        self._stab_emitted: QPointF | None = None
        self._stab_tail: list[QPointF] = []    # points to flush on pen-lift

    # ── utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def distance(first: QPointF, second: QPointF) -> float:
        return _dist(first, second)

    # ── configuration ─────────────────────────────────────────────────────────

    def set_strength(self, strength: float) -> None:
        self.strength = self.clamp(strength, 0.0, 1.0)

    def set_mode(self, mode: str) -> None:
        if mode in ("basic", "weighted", "stabilize"):
            self.mode = mode

    # ── stroke lifecycle ──────────────────────────────────────────────────────

    def begin_stroke(self) -> None:
        self.reset()
        self.in_stroke = True

    def end_stroke(self) -> None:
        self.in_stroke = False
        self.reset()

    def reset(self) -> None:
        self.points = deque(maxlen=self.buffer_size)
        self.last_output = None
        self.last_input = None
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self._w_ghost = None
        self._stab_buf.clear()
        self._stab_sx = 0.0
        self._stab_sy = 0.0
        self._stab_emitted = None
        self._stab_tail = []

    # ── main entry point ──────────────────────────────────────────────────────

    def add_point(self, point: QPointF) -> QPointF:
        """Return the stabilised position for *point*."""
        if self.strength <= 0.0:
            self.last_input = self.last_output = QPointF(point)
            return QPointF(point)

        if self.mode == "weighted":
            return self._weighted(point)
        if self.mode == "stabilize":
            return self._stabilize(point)
        return self._basic(point)

    def flush_tail(self) -> list[QPointF]:
        """Advance a delayed stabilizer smoothly to the lifted pen point.

        The previous implementation returned raw samples evicted from the
        averaging window.  Those points can lie *behind* the last emitted
        centroid, causing a subtle backward hook at the end of a slow line.
        Replacing the oldest buffered samples with the final input instead
        makes the centroid travel forward until it reaches that point.
        """
        if self.mode != "stabilize" or not self._stab_buf:
            self._stab_tail = []
            return []
        target = QPointF(self.last_input if self.last_input is not None else self._stab_buf[-1])
        points: list[QPointF] = []
        while self._stab_buf:
            evicted = self._stab_buf.popleft()
            self._stab_sx -= evicted.x()
            self._stab_sy -= evicted.y()
            self._stab_buf.append(QPointF(target))
            self._stab_sx += target.x()
            self._stab_sy += target.y()
            centroid = QPointF(self._stab_sx / len(self._stab_buf),
                               self._stab_sy / len(self._stab_buf))
            if (self._stab_emitted is None or _dist(self._stab_emitted, centroid) >= 0.05):
                self._stab_emitted = QPointF(centroid)
                points.append(QPointF(centroid))
            # Every original sample has now been replaced; retaining only the
            # final point lets ``end_stroke`` clear state without a stale tail.
            if all(_dist(point, target) < 1e-6 for point in self._stab_buf):
                break
        self._stab_tail = []
        return points

    # ── basic mode (original inertia smoother) ────────────────────────────────

    def _basic(self, point: QPointF) -> QPointF:
        # deque(maxlen=buffer_size) auto-evicts the oldest entry — no pop(0).
        current = QPointF(point)
        self.points.append(current)

        if self.last_input is None:
            self.last_input = self.last_output = QPointF(current)
            return QPointF(current)

        input_dx = current.x() - self.last_input.x()
        input_dy = current.y() - self.last_input.y()
        input_distance = math.hypot(input_dx, input_dy)

        velocity_mix = 0.55 + self.strength * 0.25
        self.velocity_x = self.velocity_x * (1.0 - velocity_mix) + input_dx * velocity_mix
        self.velocity_y = self.velocity_y * (1.0 - velocity_mix) + input_dy * velocity_mix

        smoothing = self.clamp(self.strength, 0.0, 1.0)
        responsiveness = self.clamp(0.72 - smoothing * 0.48, 0.18, 0.72)

        if input_distance > 20.0:
            responsiveness = self.clamp(
                responsiveness + min(0.20, input_distance / 250.0), 0.18, 0.88)

        prediction = 0.18 + smoothing * 0.12
        target_x = current.x() + self.velocity_x * prediction
        target_y = current.y() + self.velocity_y * prediction

        if self.last_output is None:
            self.last_output = QPointF(current)

        output_x = self.last_output.x() + (target_x - self.last_output.x()) * responsiveness
        output_y = self.last_output.y() + (target_y - self.last_output.y()) * responsiveness
        output = QPointF(output_x, output_y)

        micro_motion = 0.45 * smoothing
        if input_distance < 3.0:
            output = QPointF(
                output.x() * (1.0 - micro_motion) + self.last_output.x() * micro_motion,
                output.y() * (1.0 - micro_motion) + self.last_output.y() * micro_motion)

        self.last_input = QPointF(current)
        self.last_output = QPointF(output)
        return QPointF(output)

    # ── weighted mode (Krita "Weighted") ─────────────────────────────────────

    def _weighted(self, point: QPointF) -> QPointF:
        """Rope-pull smoother.

        The *ghost cursor* lags behind the tablet at a distance controlled by
        *strength*.  The stroke follows the ghost, so drawing is smooth but
        the direction change is natural.

        Algorithm:
        • ghost moves toward the input at speed proportional to 1/distance,
          so it "catches up" but never overshoots.
        • The factor is:  move_frac = (1 - strength) + clamp(k/d, 0, 1)*strength
          giving full tracking when the pen is fast/far and lag when slow/close.
        """
        current = QPointF(point)

        if self._w_ghost is None:
            self._w_ghost = QPointF(current)
            self.last_output = QPointF(current)
            self.last_input = QPointF(current)
            return QPointF(current)

        d = _dist(self._w_ghost, current)
        # k controls the "rope length" — at strength=1, k≈4 px for half-speed
        k = 2.0 + self.strength * 18.0   # effective rope length in pixels
        if d < 0.1:
            self.last_input = QPointF(current)
            return QPointF(self._w_ghost)

        # fraction to move toward the target this step
        frac = self.clamp((1.0 - self.strength) + self.strength * k / d, 0.05, 1.0)
        new_ghost = _lerp_pt(self._w_ghost, current, frac)
        self._w_ghost = new_ghost
        self.last_input = QPointF(current)
        self.last_output = QPointF(new_ghost)
        return QPointF(new_ghost)

    # ── stabilize mode (Krita "Stabilize") ───────────────────────────────────

    def _stabilize(self, point: QPointF) -> QPointF:
        """Sample-accumulation stabilizer.

        Holds samples in a FIFO buffer of length *buffer_size*.  The emitted
        point is the centroid of the buffer.  On each input event the oldest
        sample is evicted and the new sample is enqueued; the output only
        moves when the centroid has shifted by at least *min_dist* pixels.

        Running sums (_stab_sx/_stab_sy) are maintained incrementally so
        centroid computation is O(evictions) per call, not O(buffer_size).

        ``flush_tail()`` advances the remaining centroid window to the lifted
        point, so the canvas can finish the stroke without a blunt segment.
        """
        buf_size = max(2, int(self.buffer_size + self.strength * 20))

        # Enqueue new sample and add to running sums.
        pt = QPointF(point)
        self.last_input = QPointF(pt)
        self._stab_buf.append(pt)
        self._stab_sx += pt.x()
        self._stab_sy += pt.y()

        # Evict oldest samples until within buf_size, updating sums.
        while len(self._stab_buf) > buf_size:
            evicted = self._stab_buf.popleft()
            self._stab_sx -= evicted.x()
            self._stab_sy -= evicted.y()
            self._stab_tail.append(evicted)

        n = len(self._stab_buf)
        centroid = QPointF(self._stab_sx / n, self._stab_sy / n)

        if self._stab_emitted is None:
            self._stab_emitted = QPointF(centroid)
            return QPointF(centroid)

        min_dist = 0.5 + self.strength * 3.0
        if _dist(self._stab_emitted, centroid) >= min_dist:
            self._stab_emitted = QPointF(centroid)
        return QPointF(self._stab_emitted)

    # ── batch helper ──────────────────────────────────────────────────────────
