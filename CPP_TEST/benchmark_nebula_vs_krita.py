"""Reproducible Nebula/Krita comparison on the installed Wayland desktop.

This benchmark deliberately separates comparable process workflows from
engine-internal measurements. Krita exposes no supported headless API for
driving brush/layer/mask gestures, so those cases are reported as unavailable
instead of being replaced by an unfair proxy.

Run from the project root:
    QT_QPA_PLATFORM=wayland python CPP_TEST/benchmark_nebula_vs_krita.py
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from DOCUMENTS.document import Document
from DOCUMENTS.format_csd import CSDFormat
from DOCUMENTS.blend_modes import composite_document
from CPP_TEST.benchmark_stroke_rendering import measure as measure_stroke
from CANVAS.canvas import Canvas


REPEATS = 3


def median_process(command: list[str], env: dict[str, str], cwd: Path) -> dict:
    values = []
    stderr = ""
    for _ in range(REPEATS):
        started = time.perf_counter_ns()
        result = subprocess.run(command, cwd=cwd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=90)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if result.returncode != 0:
            raise RuntimeError(f"Commande échouée ({result.returncode}): "
                               f"{' '.join(command)}\n{result.stderr}")
        values.append(elapsed)
        stderr = result.stderr[-500:]
    return {"median_ms": round(statistics.median(values), 3),
            "samples_ms": [round(value, 3) for value in values],
            "stderr_tail": stderr}


def make_input(path: Path, size: int = 1024) -> None:
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    for y in range(size):
        for x in range(size):
            image.setPixelColor(x, y, QColor((x * 255) // (size - 1),
                                             (y * 255) // (size - 1),
                                             ((x + y) * 127) // (2 * size), 255))
    if not image.save(str(path), "PNG"):
        raise RuntimeError("Impossible de créer l'entrée PNG")


def nebula_core_workflow(input_path: Path, output_path: Path,
                         csd_path: Path) -> dict:
    image = QImage(str(input_path))
    document = Document(image.width(), image.height())
    document.get_active_layer().image = image
    document.get_active_layer().commit_image_cache()
    extra = document.add_layer("Benchmark")
    extra.image.fill(QColor(20, 80, 210, 96))
    extra.commit_image_cache()

    started = time.perf_counter_ns()
    composite = composite_document(document)
    if not composite.save(str(output_path), "PNG"):
        raise RuntimeError("Nebula ne peut pas exporter le PNG")
    export_ms = (time.perf_counter_ns() - started) / 1_000_000

    started = time.perf_counter_ns()
    if not CSDFormat.save(document, csd_path):
        raise RuntimeError("Nebula ne peut pas sauvegarder le CSD")
    save_ms = (time.perf_counter_ns() - started) / 1_000_000

    started = time.perf_counter_ns()
    reopened = CSDFormat.load(csd_path)
    load_ms = (time.perf_counter_ns() - started) / 1_000_000
    if reopened is None:
        raise RuntimeError("Nebula ne peut pas rouvrir son CSD")
    return {"png_export_ms": round(export_ms, 3),
            "csd_save_ms": round(save_ms, 3),
            "csd_reopen_ms": round(load_ms, 3)}


def nebula_process_worker(input_path: Path, output_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    image = QImage(str(input_path))
    document = Document(image.width(), image.height())
    document.get_active_layer().image = image
    document.get_active_layer().commit_image_cache()
    output = composite_document(document)
    if not output.save(str(output_path), "PNG"):
        raise SystemExit("Nebula worker: export PNG impossible")
    app.quit()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="nebula-krita-benchmark-") as tmp:
        directory = Path(tmp)
        source = directory / "source.png"
        krita_output = directory / "krita.png"
        krita_kra = directory / "krita.kra"
        krita_reopen_output = directory / "krita-reopen.png"
        nebula_output = directory / "nebula.png"
        csd_output = directory / "nebula.csd"
        make_input(source)

        clean_env = os.environ.copy()
        clean_env["QT_QPA_PLATFORM"] = "wayland"
        krita = median_process(
            ["krita", "--nosplash", str(source), "--export",
             "--export-filename", str(krita_output)], clean_env, ROOT)
        krita_save_kra = median_process(
            ["krita", "--nosplash", str(source), "--export",
             "--export-filename", str(krita_kra)], clean_env, ROOT)
        krita_reopen_kra = median_process(
            ["krita", "--nosplash", str(krita_kra), "--export",
             "--export-filename", str(krita_reopen_output)], clean_env, ROOT)
        nebula_process = median_process(
            [sys.executable, str(Path(__file__).resolve()), "--worker",
             str(source), str(nebula_output)], clean_env, ROOT)
        canvas = Canvas()
        try:
            stroke_cases = [
                measure_stroke(canvas, "fine_dense", 8.0, 0.10, 240, "wave", samples=3),
                measure_stroke(canvas, "medium_diagonal", 24.0, 0.15, 160, "diagonal", samples=3),
            ]
            nebula = nebula_core_workflow(source, nebula_output, csd_output)
        finally:
            canvas.close()
        print(json.dumps({
            "benchmark": "Nebula vs Krita",
            "date": time.strftime("%Y-%m-%d"),
            "platform": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "krita_version": subprocess.check_output(["krita", "--version"],
                                                       text=True).strip(),
            "document": {"input": "1024x1024 RGBA PNG", "repeats": REPEATS},
            "comparable_workflow": {
                "krita_open_png_export_png": krita,
                "krita_open_png_save_kra": krita_save_kra,
                "krita_reopen_kra_export_png": krita_reopen_kra,
                "nebula_open_png_export_png": nebula_process,
                "nebula_composite_export_and_csd": nebula,
            },
            "nebula_engine_only": {
                "brush_strokes": stroke_cases,
                "gpu_wayland": "validated separately by smoke_gpu_compositor.py and smoke_gpu_instanced_stroke.py",
            },
            "not_automated_fairly": [
                "Krita brush gesture throughput",
                "Krita mask editing and alpha-lock latency",
                "Krita layer/group/clipping operation latency",
                "Krita Undo/Redo internals",
            ],
        }, indent=2))
        app.quit()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        nebula_process_worker(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()
