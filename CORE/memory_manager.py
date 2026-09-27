from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import tempfile
import shutil
import atexit

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QLabel


MIB = 1024 * 1024


@dataclass(frozen=True)
class MemorySnapshot:
    process_bytes: int
    document_bytes: int
    history_bytes: int
    composition_cache_bytes: int
    gpu_texture_bytes: int
    limit_bytes: int


class _SwapSignals(QObject):
    finished = Signal(object)
    tile_finished = Signal(object)


def _physical_memory_mb() -> int:
    """RAM physique de la machine, 0 si indeterminable."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        return int(pages * os.sysconf("SC_PAGE_SIZE")) // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            pass
    return 0


def _default_memory_limit_mb() -> int:
    """Budget par defaut : 60% de la RAM physique.

    Le 2048 MB fixe d'origine etait un contresens dans les deux directions :
    sur une machine a 32 GB il bridait l'application a 6% de la RAM
    disponible et declenchait du swap disque en permanence ; sur une machine
    a 4 GB il autorisait un depassement qui finissait en OOM.
    """
    physical = _physical_memory_mb()
    if physical <= 0:
        return 2048
    return max(512, min(49152, physical * 60 // 100))


def _process_resident_bytes() -> int:
    """Current resident set size, without requiring psutil."""
    try:
        fields = Path("/proc/self/statm").read_text().split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        try:
            import psutil
            return int(psutil.Process().memory_info().rss)
        except (ImportError, OSError):
            return 0


def _image_bytes(image) -> int:
    if image is None or image.isNull():
        return 0
    try:
        return int(image.sizeInBytes())
    except (AttributeError, RuntimeError):
        return 0


def _create_swap_directory() -> Path:
    """Create ephemeral scratch under a disk-backed cache, not /tmp by default.

    On Linux, /tmp is commonly a tmpfs. Paging canvas tiles there can therefore
    increase memory pressure instead of relieving it. XDG_CACHE_HOME is the
    user-overridable location; ~/.cache is the conventional fallback.
    """
    cache_roots = []
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        cache_roots.append(Path(xdg_cache).expanduser())
    cache_roots.append(Path.home() / ".cache")

    for cache_root in cache_roots:
        try:
            scratch_root = cache_root / "creativesystem" / "scratch"
            scratch_root.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="tile-swap-", dir=scratch_root))
        except OSError:
            continue

    # Last resort for locked-down systems where the user cache is unavailable.
    return Path(tempfile.mkdtemp(prefix="creativesystem-tile-swap-"))


class MemoryManager(QObject):
    """Live application memory accounting and conservative pressure relief."""

    # Nombre de tuiles triees d'avance par balayage. Assez grand pour amortir
    # le cout du tri, assez petit pour que la file ne soit pas trop perimee.
    EVICTION_BATCH = 256

    def __init__(self, canvas, status_bar, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.settings = QSettings("CreativeSystem", "CreativeSystem")
        self.limit_mb = max(256, min(65536, self.settings.value(
            "performance/memory_limit_mb", _default_memory_limit_mb(), int
        )))
        self._pressure_active = False
        self._swap_dir = _create_swap_directory()
        configured_scratch = str(self.settings.value("performance/scratch_directory", "") or "").strip()
        self._scratch_dir = Path(configured_scratch).expanduser() if configured_scratch else self._swap_dir / "tiles"
        try:
            self._scratch_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A preference may refer to an old removable disk or a directory
            # that is no longer writable. Never let that prevent the UI from
            # starting; use the already validated per-session cache instead.
            self._scratch_dir = self._swap_dir / "tiles"
            self._scratch_dir.mkdir(parents=True, exist_ok=True)
        self._scratch_configuration = None
        # Le premier recalcul du scratch peut invalider la file d'éviction.
        # Initialiser la file avant _configure_tile_scratch(), car cette
        # méthode est appelée dès la construction du MemoryManager.
        self._eviction_queue: list = []
        self._configure_tile_scratch()
        atexit.register(shutil.rmtree, self._swap_dir, ignore_errors=True)
        self._swap_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tile-swap")
        self._swap_signals = _SwapSignals(self)
        self._swap_signals.finished.connect(self._on_swap_finished)
        self._swap_signals.tile_finished.connect(self._on_tile_swap_finished)
        self._swap_in_progress = False
        self._shutting_down = False
        self._last_snapshot = MemorySnapshot(0, 0, 0, 0, 0, self.limit_mb * MIB)
        self.label = QLabel("RAM — | GPU —")
        self.label.setObjectName("memoryUsageIndicator")
        self.label.setToolTip(
            "Mémoire du processus CreativeSystem et estimation de la mémoire des textures GPU"
        )
        status_bar.addPermanentWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_limit_mb(self, limit_mb: int) -> None:
        self.limit_mb = max(256, min(65536, int(limit_mb)))
        self.settings.setValue("performance/memory_limit_mb", self.limit_mb)
        self.refresh()

    def set_scratch_directory(self, directory: str) -> None:
        value = str(directory or "").strip()
        self.settings.setValue("performance/scratch_directory", value)
        self._scratch_dir = Path(value).expanduser() if value else self._swap_dir / "tiles"
        try:
            self._scratch_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._scratch_dir = self._swap_dir / "tiles"
            self._scratch_dir.mkdir(parents=True, exist_ok=True)
        self._configure_tile_scratch()

    def _configure_tile_scratch(self) -> None:
        layers = tuple(getattr(getattr(self.canvas, "document", None), "layers", ()))
        signature = (tuple(layer.id for layer in layers), str(self._scratch_dir), self.limit_mb)
        if signature == self._scratch_configuration:
            return
        try:
            for layer in layers:
                layer.tile_store.set_scratch_directory(self._scratch_dir / layer.id)
        except OSError:
            # The configured root can exist while its per-layer children are
            # no longer writable (removed drive, read-only mount, etc.).
            self._scratch_dir = self._swap_dir / "tiles"
            self._scratch_dir.mkdir(parents=True, exist_ok=True)
            for layer in layers:
                layer.tile_store.set_scratch_directory(self._scratch_dir / layer.id)

        self._scratch_configuration = signature
        # La composition des calques a change : la file reference peut-etre
        # des stores qui n'existent plus.
        self._eviction_queue.clear()
        occupied = [max(0, int(layer.tile_store.allocated_bytes())) for layer in layers]
        total_occupied = sum(occupied)
        total_budget = self.limit_mb * 1024 * 1024
        for index, layer in enumerate(layers):
            if total_occupied:
                share = total_budget * occupied[index] // total_occupied
            else:
                share = total_budget // max(1, len(layers))
            layer.tile_store.set_memory_limit(max(1, share))

    def snapshot(self) -> MemorySnapshot:
        document = self.canvas.document
        document_bytes = sum(layer.tile_store.allocated_bytes()
                             + _image_bytes(getattr(layer, "_image_cache", None))
                             for layer in document.layers)
        document_bytes += _image_bytes(document.selection.image)
        for image in getattr(document, "reference_images", ()):
            document_bytes += _image_bytes(getattr(image, "image", image))

        history_bytes = 0
        history = getattr(self.canvas, "tile_history", None)
        if history is not None:
            for step in history.steps:
                history_bytes += int(getattr(step, "native_state_bytes", 0))
                if hasattr(step.tiles, "native_storage_bytes"):
                    history_bytes += step.tiles.native_storage_bytes
                else:
                    for pair in step.tiles.values():
                        history_bytes += sum(_image_bytes(tile) for tile in pair)
                for state in (step.before, step.after):
                    history_bytes += sum(
                        _image_bytes(getattr(image, "image", image))
                        for image in state.get("reference_images", ())
                    )
            pending = history._pending
            if pending is not None:
                history_bytes += sum(_image_bytes(image) for image in pending.get("images", {}).values())
                history_bytes += sum(_image_bytes(tile) for tile in pending.get("before_tiles", {}).values())
                state = pending.get("state", {})
                history_bytes += sum(
                    _image_bytes(getattr(image, "image", image))
                    for image in state.get("reference_images", ())
                )

        from DOCUMENTS.blend_modes import composition_cache_size_bytes
        projection_store = getattr(self.canvas, "projection_store", None)
        cache_bytes = composition_cache_size_bytes()
        cache_bytes += sum(group.cache_size_bytes()
                           for group in getattr(document, "layer_groups", ()))
        if projection_store is not None:
            cache_bytes += projection_store.allocated_bytes()

        renderer = getattr(self.canvas, "gpu_renderer", None)
        gpu_bytes = 0
        if renderer is not None:
            gpu_bytes = sum(max(0, int(item.width)) * max(0, int(item.height)) * 4
                            for item in renderer.textures.values())

        return MemorySnapshot(
            process_bytes=_process_resident_bytes(),
            document_bytes=document_bytes,
            history_bytes=history_bytes,
            composition_cache_bytes=cache_bytes,
            gpu_texture_bytes=gpu_bytes,
            limit_bytes=self.limit_mb * MIB,
        )

    def refresh(self) -> None:
        snapshot = self.snapshot()
        self._last_snapshot = snapshot
        process_mb = snapshot.process_bytes / MIB
        limit_mb = snapshot.limit_bytes / MIB
        gpu_mb = snapshot.gpu_texture_bytes / MIB
        self.label.setText(f"RAM {process_mb:.0f}/{limit_mb:.0f} MB · GPU {gpu_mb:.0f} MB")
        self.label.setToolTip(
            "RAM du processus (RSS): "
            f"{process_mb:.1f} MB / {limit_mb:.0f} MB\n"
            f"Calques et sélection: {snapshot.document_bytes / MIB:.1f} MB\n"
            f"Historique undo: {snapshot.history_bytes / MIB:.1f} MB\n"
            f"Cache composition: {snapshot.composition_cache_bytes / MIB:.1f} MB\n"
            f"Textures GPU estimées: {gpu_mb:.1f} MB"
        )
        if snapshot.process_bytes > snapshot.limit_bytes:
            self._pressure_active = True
            self._relieve_pressure(snapshot)
        elif snapshot.process_bytes < snapshot.limit_bytes * 0.85:
            self._pressure_active = False
            self._eviction_queue.clear()

    def _relieve_pressure(self, snapshot: MemorySnapshot) -> None:
        """Free caches, then swap old undo tiles before trimming history."""
        # Reconcile layer stores only when pressure relief is actually needed;
        # the regular status refresh must remain lightweight and non-blocking.
        self._configure_tile_scratch()
        from DOCUMENTS.blend_modes import clear_composition_cache
        clear_composition_cache()
        for group in getattr(self.canvas.document, "layer_groups", ()):
            group.invalidate()

        # First swap allocated tiles that do not intersect the current view.
        # Keep the active layer resident to avoid stalls during a stroke.
        canvas = self.canvas
        document = canvas.document
        visible = canvas.visible_document_tile_keys()
        active = document.get_active_layer()
        stroke_open = (getattr(getattr(canvas, "tile_history", None), "_pending", None)
                       is not None)
        projection_store = getattr(canvas, "projection_store", None)
        if projection_store is not None:
            for tx, ty in projection_store.resident_keys():
                if (tx, ty) in visible:
                    continue
                projection_store.remove_resident_tile(tx, ty)
                canvas._projection_tile_signatures.pop((tx, ty), None)
                canvas._projection_ready_tiles.discard((tx, ty))
                canvas._projection_tile_generation.pop((tx, ty), None)
        # File d'eviction : on ne rebalaye pas l'integralite des tuiles pour
        # n'en evincer qu'une seule. L'ancien code faisait un scan O(n) de
        # tous les calques a chaque tuile evincee, donc O(n^2) au total, et
        # ce scan tournait sur le thread UI pendant que l'utilisateur dessine
        # (~16 600 tuiles pour un 4K a 8 calques, ~51 500 pour un A3 300 dpi
        # a 12 calques). On trie une fois, puis on consomme la file.
        if not self._eviction_queue and not self._swap_in_progress:
            candidates = []
            for layer in document.layers:
                if stroke_open and layer is active:
                    continue
                store = layer.tile_store
                for tx, ty in store.resident_keys():
                    if (tx, ty) not in visible:
                        candidates.append((store.tile_last_access(tx, ty), store, tx, ty))
            # Les plus anciennement accedees d'abord (LRU).
            candidates.sort(key=lambda item: item[0])
            self._eviction_queue = [(entry[1], entry[2], entry[3])
                                    for entry in candidates[:self.EVICTION_BATCH]]

        while self._eviction_queue and not self._swap_in_progress:
            store, tx, ty = self._eviction_queue.pop(0)
            # La file a pu etre invalidee entre-temps : la tuile peut etre
            # redevenue visible. Le cas "deja evincee" est couvert par
            # tile_swap_payload(), qui renvoie None ; on evite ainsi un appel
            # a resident_keys() par tuile, qui reconstruit un set complet et
            # nous ramenerait au cout quadratique qu'on vient de supprimer.
            if (tx, ty) in visible:
                continue
            payload = store.tile_swap_payload(tx, ty)
            if payload is None:
                continue
            self._swap_in_progress = True
            future = self._swap_executor.submit(store.write_tile_payload, payload)

            def finish_tile(result_future, target=store, tile_x=tx, tile_y=ty, data=payload):
                try:
                    result = (target, tile_x, tile_y, str(data[1]), data[2], result_future.result(), None)
                except Exception as error:
                    result = (target, tile_x, tile_y, str(data[1]), data[2], 0, error)
                if not self._shutting_down:
                    self._swap_signals.tile_finished.emit(result)

            future.add_done_callback(finish_tile)
            return

        history = getattr(self.canvas, "tile_history", None)
        if history is None or history._pending is not None:
            return
        if self._swap_in_progress:
            return
        candidate = next((step for step in history.steps if step.tiles), None)
        if candidate is not None:
            path = self._swap_dir / f"step-{id(candidate):x}.zip"
            self._swap_in_progress = True
            future = self._swap_executor.submit(history.write_step_swap, candidate, path)

            def finish(result_future, step=candidate, swap_path=path):
                try:
                    result = (step, str(swap_path), result_future.result(), None)
                except Exception as error:
                    result = (step, str(swap_path), 0, error)
                self._swap_signals.finished.emit(result)

            future.add_done_callback(finish)
            return

        # Keep a smaller usable undo history only after disk swapping has
        # already moved tile payloads out of RAM.
        target_steps = max(1, history.max_steps // 2)
        if (len(history.steps) > target_steps
                and snapshot.process_bytes > snapshot.limit_bytes * 1.15):
            history.discard_oldest(len(history.steps) - target_steps)
        self.canvas.history = history.steps
        self.canvas.history_index = history.index

    def _on_swap_finished(self, result) -> None:
        step, path, _encoded_bytes, error = result
        self._swap_in_progress = False
        if self._shutting_down:
            shutil.rmtree(self._swap_dir, ignore_errors=True)
            return
        history = getattr(self.canvas, "tile_history", None)
        if error is not None:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            return
        if history is not None and step in history.steps:
            history.attach_step_swap(step, path)
        else:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        if self._pressure_active:
            self._relieve_pressure(self._last_snapshot)
        self.refresh()

    def _on_tile_swap_finished(self, result) -> None:
        store, tx, ty, path, revision, _written, error = result
        self._swap_in_progress = False
        if error is None:
            if not store.commit_tile_eviction(tx, ty, path, revision):
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        if self._pressure_active:
            # Continue draining pressure immediately; waiting for the next
            # 1.5 s timer tick made large overruns take hours to recover.
            self._relieve_pressure(self._last_snapshot)
        self.refresh()

    def shutdown(self) -> None:
        self._shutting_down = True
        self.timer.stop()
        self._swap_executor.shutdown(wait=False, cancel_futures=True)
        if not self._swap_in_progress:
            shutil.rmtree(self._swap_dir, ignore_errors=True)

    @property
    def last_snapshot(self) -> MemorySnapshot:
        return self._last_snapshot
