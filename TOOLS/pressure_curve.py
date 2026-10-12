"""Global stylus pressure curve (the tablet response, like Krita's or Photoshop's).

The curve maps raw pen pressure (0–1) to the pressure the brush engine sees.
It is defined by a few control points joined by a monotone cubic spline
(Fritsch–Carlson), so the response never dips back down between points, and
evaluated through a 1024-entry lookup table on every pen sample.
"""
from __future__ import annotations

from bisect import bisect_right

SETTINGS_KEY = "tablet/pressure_curve"

PRESETS: dict[str, tuple[tuple[float, float], ...]] = {
    "Linéaire": ((0.0, 0.0), (1.0, 1.0)),
    "Doux": ((0.0, 0.0), (0.35, 0.55), (1.0, 1.0)),
    "Très doux": ((0.0, 0.0), (0.25, 0.60), (1.0, 1.0)),
    "Ferme": ((0.0, 0.0), (0.55, 0.35), (1.0, 1.0)),
    "Courbe en S": ((0.0, 0.0), (0.30, 0.15), (0.70, 0.85), (1.0, 1.0)),
}


class PressureCurve:
    LUT_SIZE = 1024

    def __init__(self, points=None) -> None:
        self.points: list[tuple[float, float]] = []
        self._lut: list[float] = []
        self.set_points(points or PRESETS["Linéaire"])

    # ── definition ─────────────────────────────────────────────────────────

    def set_points(self, points) -> None:
        cleaned: dict[float, float] = {}
        for x, y in points:
            x = min(1.0, max(0.0, float(x)))
            cleaned[round(x, 4)] = min(1.0, max(0.0, float(y)))
        cleaned.setdefault(0.0, 0.0)
        cleaned.setdefault(1.0, 1.0)
        self.points = sorted(cleaned.items())
        self._build_lut()

    def is_linear(self) -> bool:
        return all(abs(x - y) < 1e-4 for x, y in self.points)

    # ── evaluation ─────────────────────────────────────────────────────────

    def _tangents(self) -> list[float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        n = len(xs)
        if n == 2:
            slope = (ys[1] - ys[0]) / max(1e-6, xs[1] - xs[0])
            return [slope, slope]
        deltas = [(ys[i + 1] - ys[i]) / max(1e-6, xs[i + 1] - xs[i]) for i in range(n - 1)]
        tangents = [deltas[0]] + [
            0.0 if deltas[i - 1] * deltas[i] <= 0 else (deltas[i - 1] + deltas[i]) / 2
            for i in range(1, n - 1)
        ] + [deltas[-1]]
        for i, delta in enumerate(deltas):
            if delta == 0.0:
                tangents[i] = tangents[i + 1] = 0.0
                continue
            a, b = tangents[i] / delta, tangents[i + 1] / delta
            length = a * a + b * b
            if length > 9.0:
                scale = 3.0 / length ** 0.5
                tangents[i], tangents[i + 1] = scale * a * delta, scale * b * delta
        return tangents

    def _evaluate(self, x: float) -> float:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        index = min(len(xs) - 2, max(0, bisect_right(xs, x) - 1))
        x0, x1 = xs[index], xs[index + 1]
        h = max(1e-6, x1 - x0)
        t = (x - x0) / h
        m0, m1 = self._tangents_cache[index], self._tangents_cache[index + 1]
        t2, t3 = t * t, t * t * t
        value = ((2 * t3 - 3 * t2 + 1) * ys[index] + (t3 - 2 * t2 + t) * h * m0
                 + (-2 * t3 + 3 * t2) * ys[index + 1] + (t3 - t2) * h * m1)
        return min(1.0, max(0.0, value))

    def _build_lut(self) -> None:
        self._tangents_cache = self._tangents()
        last = self.LUT_SIZE - 1
        self._lut = [self._evaluate(i / last) for i in range(self.LUT_SIZE)]

    def map(self, pressure: float) -> float:
        """Raw pen pressure → curved pressure (linear interpolation in the LUT)."""
        position = min(1.0, max(0.0, float(pressure))) * (self.LUT_SIZE - 1)
        index = int(position)
        if index >= self.LUT_SIZE - 1:
            return self._lut[-1]
        fraction = position - index
        return self._lut[index] + (self._lut[index + 1] - self._lut[index]) * fraction

    # ── persistence ────────────────────────────────────────────────────────

    def serialize(self) -> str:
        return ";".join(f"{x:.4f},{y:.4f}" for x, y in self.points)

    @classmethod
    def parse(cls, text) -> "PressureCurve":
        points = []
        for chunk in str(text or "").split(";"):
            try:
                x, y = chunk.split(",")
                points.append((float(x), float(y)))
            except ValueError:
                continue
        return cls(points if len(points) >= 2 else None)

    @classmethod
    def load(cls, settings) -> "PressureCurve":
        return cls.parse(settings.value(SETTINGS_KEY, ""))

    def save(self, settings) -> None:
        settings.setValue(SETTINGS_KEY, self.serialize())


__all__ = ["PressureCurve", "PRESETS", "SETTINGS_KEY"]
