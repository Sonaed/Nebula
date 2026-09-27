"""Algorithmes du module Pixel Art (sans Qt, testables seuls).

Tout est en coordonnées entières : un point = un pixel du document.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Sequence

Color = tuple[int, int, int]

# ── palettes intégrées ────────────────────────────────────────
BUILTIN_PALETTES: dict[str, list[str]] = {
    "PICO-8": ["000000", "1D2B53", "7E2553", "008751", "AB5236", "5F574F", "C2C3C7", "FFF1E8",
               "FF004D", "FFA300", "FFEC27", "00E436", "29ADFF", "83769C", "FF77A8", "FFCCAA"],
    "DawnBringer 16": ["140C1C", "442434", "30346D", "4E4A4E", "854C30", "346524", "D04648", "757161",
                       "597DCE", "D27D2C", "8595A1", "6DAA2C", "D2AA99", "6DC2CA", "DAD45E", "DEEED6"],
    "Game Boy": ["0F380F", "306230", "8BAC0F", "9BBC0F"],
    "1-bit": ["000000", "FFFFFF"],
    "Niveaux de gris 8": ["000000", "242424", "494949", "6D6D6D", "929292", "B6B6B6", "DBDBDB", "FFFFFF"],
}


def hex_to_rgb(value: str) -> Color:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(color: Color) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


# ── tracés ────────────────────────────────────────────────────
def line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham : ligne 1 px sans trou ni doublon."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def pixel_perfect(points: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Supprime les « coins en L » d'un tracé à main levée (style Aseprite).

    Un point est retiré quand il touche orthogonalement le précédent ET le
    suivant, alors que ceux-ci se touchent en diagonale.
    """
    out: list[tuple[int, int]] = []
    for point in points:
        if out and out[-1] == point:
            continue
        out.append(point)
        if len(out) >= 3:
            (ax, ay), (bx, by), (cx, cy) = out[-3], out[-2], out[-1]
            ortho_ab = abs(ax - bx) + abs(ay - by) == 1
            ortho_bc = abs(bx - cx) + abs(by - cy) == 1
            diagonal = abs(ax - cx) == 1 and abs(ay - cy) == 1
            if ortho_ab and ortho_bc and diagonal:
                del out[-2]
    return out


def stamp(size: int, shape: str = "square") -> list[tuple[int, int]]:
    """Décalages d'une pointe de ``size`` pixels (carrée ou ronde pixel)."""
    size = max(1, int(size))
    start = -(size // 2)
    offsets = []
    radius = size / 2.0
    for dy in range(start, start + size):
        for dx in range(start, start + size):
            if shape == "round" and size > 2:
                cx = dx - start + 0.5 - radius
                cy = dy - start + 0.5 - radius
                if cx * cx + cy * cy > radius * radius + 0.25:
                    continue
            offsets.append((dx, dy))
    return offsets


def expand(points: Iterable[tuple[int, int]], offsets: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    seen, out = set(), []
    for x, y in points:
        for dx, dy in offsets:
            p = (x + dx, y + dy)
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def wrap(points: Iterable[tuple[int, int]], width: int, height: int) -> list[tuple[int, int]]:
    """Mode tuile : ce qui sort d'un bord réapparaît de l'autre côté."""
    seen, out = set(), []
    for x, y in points:
        p = (x % width, y % height)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def clip(points: Iterable[tuple[int, int]], width: int, height: int) -> list[tuple[int, int]]:
    return [(x, y) for x, y in points if 0 <= x < width and 0 <= y < height]


# ── tramage (dithering ordonné) ───────────────────────────────
BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def dither_on(x: int, y: int, density: float) -> bool:
    """Vrai si le pixel (x, y) reçoit la couleur principale pour une densité 0..1."""
    if density >= 1.0:
        return True
    if density <= 0.0:
        return False
    return BAYER4[y % 4][x % 4] < density * 16


def checker_on(x: int, y: int) -> bool:
    return (x + y) % 2 == 0


# ── palettes ─────────────────────────────────────────────────
def _weighted_distance(a: Color, b: Color) -> float:
    """Distance « redmean » : bien plus proche de la perception que RGB brut."""
    rmean = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db


def nearest(color: Color, palette: Sequence[Color]) -> Color:
    if not palette:
        return color
    return min(palette, key=lambda p: _weighted_distance(color, p))


class PaletteMapper:
    """Remappe des couleurs sur une palette avec un cache (images entières)."""

    def __init__(self, palette: Sequence[Color]) -> None:
        self.palette = list(palette)
        self.cache: dict[Color, Color] = {}

    def __call__(self, color: Color) -> Color:
        found = self.cache.get(color)
        if found is None:
            found = nearest(color, self.palette)
            self.cache[color] = found
        return found


def unique_colors(pixels: Iterable[tuple[int, int, int, int]], limit: int = 256,
                  alpha_threshold: int = 16) -> list[Color]:
    """Couleurs distinctes (opaques) d'un calque, par fréquence décroissante."""
    counts: dict[Color, int] = {}
    for r, g, b, a in pixels:
        if a < alpha_threshold:
            continue
        key = (r, g, b)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts, key=lambda c: -counts[c])
    return ordered[:limit]


def tiles(width: int, height: int, tile_w: int, tile_h: int) -> Iterator[tuple[int, int, int, int]]:
    """Rectangles (x, y, w, h) d'une grille de tuiles, ligne par ligne."""
    tile_w, tile_h = max(1, tile_w), max(1, tile_h)
    for y in range(0, height - tile_h + 1, tile_h):
        for x in range(0, width - tile_w + 1, tile_w):
            yield x, y, tile_w, tile_h


def next_integer_zoom(zoom: float, direction: int, minimum: int = 1, maximum: int = 64) -> float:
    """Zoom entier suivant (×1, ×2, ×3, ×4, ×6, ×8, ×12, ×16, ×24, ×32, ×48, ×64)."""
    steps = [z for z in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64) if minimum <= z <= maximum]
    if zoom < 1:
        steps = [0.25, 0.5] + steps
    if direction > 0:
        return next((z for z in steps if z > zoom + 1e-6), steps[-1])
    return next((z for z in reversed(steps) if z < zoom - 1e-6), steps[0])
