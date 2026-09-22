"""Explicit Python-only parity oracles for CreativeCore benchmarks.

These routines are test references, never imported by the application canvas.
They intentionally preserve the old approximation so native output can be
compared without reintroducing a production fallback.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient


def clone_segment(image: QImage, source: QImage, offset: QPoint,
                  settings: dict, start: QPoint, end: QPoint,
                  start_pressure: float = 1.0,
                  end_pressure: float = 1.0) -> QImage:
    if source is None or offset is None:
        return image
    size = max(1.0, float(settings.get("size", 10.0)))
    spacing = max(0.01, float(settings.get("spacing", 0.15)))
    dx, dy = end.x() - start.x(), end.y() - start.y()
    distance = math.hypot(dx, dy)
    steps = max(1, math.ceil(distance / max(0.5, size * spacing)))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for index in range(steps + 1):
        t = index / steps
        pressure = start_pressure + (end_pressure - start_pressure) * t
        minimum_size = min(1.0, max(0.0, float(settings.get("minimumSize", 0.01)))) * size
        dab_size = (minimum_size + (size - minimum_size) * pressure
                    if settings.get("pressureSize") else size)
        dab_size = max(1.0, dab_size)
        dab_rect = QRect(round(start.x() + dx * t - dab_size / 2),
                         round(start.y() + dy * t - dab_size / 2),
                         max(1, math.ceil(dab_size)), max(1, math.ceil(dab_size)))
        patch = QImage(dab_rect.size(), QImage.Format.Format_ARGB32)
        patch.fill(Qt.GlobalColor.transparent)
        source_painter = QPainter(patch)
        source_painter.drawImage(
            QPoint(-offset.x() - dab_rect.x(), -offset.y() - dab_rect.y()), source)
        source_painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn)
        mask = QImage(dab_rect.size(), QImage.Format.Format_ARGB32)
        mask.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask)
        hardness = min(1.0, max(0.0, float(settings.get("hardness", 0.8))))
        gradient = QRadialGradient(QPointF(mask.width() / 2, mask.height() / 2),
                                   max(1.0, dab_size / 2))
        gradient.setColorAt(0.0, QColor(255, 255, 255, 255))
        gradient.setColorAt(hardness, QColor(255, 255, 255, 255))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        mask_painter.setPen(Qt.PenStyle.NoPen)
        mask_painter.setBrush(gradient)
        mask_painter.drawEllipse(QRectF(0, 0, mask.width(), mask.height()))
        mask_painter.end()
        source_painter.drawImage(0, 0, mask)
        source_painter.end()
        opacity_pressure = pressure if settings.get("pressureOpacity") else 1.0
        painter.setOpacity(float(settings.get("opacity", 1.0)) *
                           float(settings.get("flow", 1.0)) * opacity_pressure)
        painter.drawImage(dab_rect.topLeft(), patch)
    painter.end()
    return image


def filter_segments(image: QImage, segments, settings: dict,
                    start_pressure: float, end_pressure: float,
                    sharpen: bool) -> None:
    size = max(1.0, float(settings.get("size", 10.0)))
    spacing = max(0.02, float(settings.get("spacing", 0.15)))
    opacity = min(1.0, max(0.0, float(settings.get("opacity", 1.0)) *
                           float(settings.get("flow", 1.0))))
    filter_radius = max(1, min(5, round(size * 0.06)))
    for start, end in segments:
        dx, dy = end.x() - start.x(), end.y() - start.y()
        distance = math.hypot(dx, dy)
        steps = max(1, math.ceil(distance / max(0.5, size * spacing)))
        for step in range(steps + 1):
            t = step / steps
            pressure = min(1.0, max(0.05, start_pressure +
                                    (end_pressure - start_pressure) * t))
            cx, cy = start.x() + dx * t, start.y() + dy * t
            radius = max(1, math.ceil(size * pressure * 0.5))
            bounds = QRect(round(cx) - radius, round(cy) - radius,
                           radius * 2 + 1, radius * 2 + 1).intersected(image.rect())
            source_rect = bounds.adjusted(-filter_radius, -filter_radius,
                                          filter_radius, filter_radius).intersected(image.rect())
            snapshot = image.copy(source_rect)
            src, dst = snapshot.constBits(), image.bits()
            stride = snapshot.bytesPerLine()
            for y in range(bounds.top(), bounds.bottom() + 1):
                for x in range(bounds.left(), bounds.right() + 1):
                    distance_to_center = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                    if distance_to_center >= radius:
                        continue
                    coverage = opacity * pressure * (1.0 - distance_to_center / radius)
                    sums = [0.0, 0.0, 0.0, 0.0]
                    premul = [0.0, 0.0, 0.0]
                    count = 0
                    for oy in range(-filter_radius, filter_radius + 1):
                        sy = min(image.height() - 1, max(0, y + oy))
                        for ox in range(-filter_radius, filter_radius + 1):
                            sx = min(image.width() - 1, max(0, x + ox))
                            local = (sy - source_rect.y()) * stride + (sx - source_rect.x()) * 4
                            alpha = src[local + 3] / 255.0
                            for channel in range(3):
                                premul[channel] += src[local + channel] * alpha
                            sums[3] += src[local + 3]
                            count += 1
                    local = (y - source_rect.y()) * stride + (x - source_rect.x()) * 4
                    target = y * image.bytesPerLine() + x * 4
                    for channel in range(3):
                        blurred = (premul[channel] * 255 / sums[3]
                                   if sums[3] else src[local + channel])
                        value = (src[local + channel] +
                                 0.85 * (src[local + channel] - blurred)
                                 if sharpen else blurred)
                        dst[target + channel] = round(max(
                            0, min(255, src[local + channel] +
                                   (value - src[local + channel]) * coverage)))
                    if not sharpen:
                        alpha_blur = sums[3] / count
                        dst[target + 3] = round(
                            src[local + 3] + (alpha_blur - src[local + 3]) * coverage)
