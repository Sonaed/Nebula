"""Viewport-aware residency policy for Nebula's independently bounded caches."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CacheBudgets:
    projection_tiles: int = 4096
    layer_tiles: int = 8192
    group_tiles: int = 2048
    gpu_bytes: int = 512 * 1024 * 1024
    undo_bytes: int = 512 * 1024 * 1024
    scratch_bytes: int = 0  # disk capacity is external; 0 means unbounded here


class TileCacheManager:
    """Classifies tile demand without owning pixels or blocking the UI.

    TileStore remains authoritative. This policy layer only says which tiles
    should be visible, retained as recent, prefetched, or allowed to become
    cold. Its small OrderedDict lets the renderer retain an older projection
    while a replacement is loading, avoiding a blank viewport.
    """

    def __init__(self, budgets: CacheBudgets | None = None) -> None:
        self.budgets = budgets or CacheBudgets()
        self.visible: set[tuple[int, int]] = set()
        self.prefetch: set[tuple[int, int]] = set()
        self.active_group: set[tuple[int, int]] = set()
        self._recent: OrderedDict[tuple[int, int], None] = OrderedDict()
        self.pan_vector = (0.0, 0.0)
        self.zoom = 1.0
        self.metrics = {"visible": 0, "recent": 0, "prefetch": 0, "cold": 0,
                        "requests": 0, "ready": 0, "retained_frames": 0}

    @property
    def recent(self) -> set[tuple[int, int]]:
        return set(self._recent)

    def update(self, visible: Iterable[tuple[int, int]], *, pan_delta=(0.0, 0.0), zoom=1.0,
               all_keys: Iterable[tuple[int, int]] = (), active_group_keys: Iterable[tuple[int, int]] = ()) -> set[tuple[int, int]]:
        self.visible = set(visible); self.active_group = set(active_group_keys); self.zoom = max(.01, float(zoom))
        dx, dy = float(pan_delta[0]), float(pan_delta[1]); self.pan_vector = (dx, dy)
        speed = abs(dx) + abs(dy)
        # Slow pan needs a small all-round halo. Fast pan earns a directional
        # band; zoomed-out views favor the already available projection mipmap.
        radius = 1 if speed < 40 else 0
        lead = 0 if self.zoom < .5 else (3 if speed >= 40 else 1)
        prefetch = set()
        for tx, ty in self.visible:
            for oy in range(-radius, radius + 1):
                for ox in range(-radius, radius + 1): prefetch.add((tx + ox, ty + oy))
            if lead:
                sx = 1 if dx < 0 else -1 if dx > 0 else 0
                sy = 1 if dy < 0 else -1 if dy > 0 else 0
                for step in range(1, lead + 1): prefetch.add((tx + sx * step, ty + sy * step))
        valid = set(all_keys) if all_keys else None
        self.prefetch = (prefetch if valid is None else prefetch & valid) - self.visible
        for key in self.visible | self.prefetch | self.active_group:
            self._recent[key] = None; self._recent.move_to_end(key)
        while len(self._recent) > self.budgets.projection_tiles: self._recent.popitem(last=False)
        self.metrics.update({"visible": len(self.visible), "recent": len(self._recent), "prefetch": len(self.prefetch),
                             "cold": max(0, len(valid or ()) - len(self._recent))})
        return self.visible | self.prefetch

    def should_retain(self, key: tuple[int, int]) -> bool: return key in self._recent
    def mark_request(self, key: tuple[int, int]) -> None:
        self.metrics["requests"] += 1
        if key in self._recent: self.metrics["retained_frames"] += 1

    def mark_ready(self, key: tuple[int, int]) -> None:
        self.metrics["ready"] += 1; self._recent[key] = None; self._recent.move_to_end(key)

    def snapshot(self) -> dict: return {**self.metrics, "pan": self.pan_vector, "zoom": self.zoom}
