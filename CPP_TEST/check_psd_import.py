"""Vérifie qu'un PSD s'ouvre dans Nebula et ressemble au rendu de Photoshop.

    python CPP_TEST/check_psd_import.py ~/Images/mon_fichier.psd

Ouvre le fichier exactement comme « Fichier > Ouvrir » (DOCUMENTS.format_nebula
.load_document), compose le document avec CreativeCore puis compare le résultat à
l'image composite que Photoshop enregistre dans le PSD.  Écarts attendus : quelques
niveaux (sur 255) sous les courbes de transfert de dégradé ; rien ailleurs.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    import numpy as np
    from PySide6.QtGui import QGuiApplication, QImage
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841

    from CORE.native_filters import load_filters
    from DOCUMENTS.blend_modes import composite_document
    from DOCUMENTS.format_nebula import load_document
    from DOCUMENTS.psd_reader import read_psd

    filters = load_filters()
    abi = getattr(filters, "abi_version", 0)
    print(f"CreativeCore filtres ABI {abi}" + ("" if abi >= 5 else "  <-- recompilez (cmake --build)"))

    path = argv[1]
    start = time.perf_counter()
    document = load_document(path)
    if document is None:
        print("ÉCHEC : Nebula n'a pas pu ouvrir le fichier")
        return 1
    print(f"Ouverture : {time.perf_counter() - start:.1f} s")
    print("Rapport :", getattr(document, "psd_import_report", {}))
    warning = getattr(document, "psd_import_warning", "")
    if warning:
        print("Remarques :\n  " + warning.replace("\n", "\n  "))

    start = time.perf_counter()
    image = composite_document(document).convertToFormat(QImage.Format.Format_RGBA8888)
    print(f"Composition : {time.perf_counter() - start:.1f} s")
    stride = image.bytesPerLine()
    raw = np.frombuffer(bytes(image.constBits()), np.uint8).reshape(image.height(), stride)
    ours = raw[:, :image.width() * 4].reshape(image.height(), image.width(), 4).astype(np.int16)

    reference = read_psd(path).composite
    if reference is None:
        print("Pas d'image composite Photoshop dans le fichier : comparaison impossible")
        return 0
    reference = reference.astype(np.int16)
    alpha = reference[..., 3:4] / 255.0
    ours_rgb = ours[..., :3] * (ours[..., 3:4] / 255.0)
    ref_rgb = reference[..., :3] * alpha
    diff = np.abs(ours_rgb - ref_rgb).max(axis=-1)
    p99 = float(np.percentile(diff, 99))
    print(f"Écart avec Photoshop : moyenne {diff.mean():.2f}, 99e centile {p99:.1f}, "
          f"max {diff.max():.0f} (sur 255)")
    verdict = p99 <= 12 and diff.mean() <= 2
    print("OK" if verdict else "ÉCART IMPORTANT : envoyez ce rapport")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
