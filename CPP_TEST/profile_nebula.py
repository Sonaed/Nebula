"""Profile Nebula pendant une vraie session d'utilisation.

Usage (racine du projet) :  python CPP_TEST/profile_nebula.py
Lancez, reproduisez la lenteur (tracez des traits, zoomez, déplacez...) pendant
20-30 s, puis quittez normalement.  Le résumé est écrit dans nebula_profile.txt
et affiché ; envoyez-moi ce fichier.  cProfile ralentit tout, mais les proportions
entre fonctions restent fiables.  Seul le thread principal (l'interface) est
mesuré ; les workers natifs n'apparaissent pas.
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(profile: cProfile.Profile, limit: int = 45) -> str:
    out = io.StringIO()
    for title, key in (("PAR TEMPS PROPRE (où le CPU est brûlé)", "tottime"),
                       ("PAR TEMPS CUMULÉ (qui appelle le coût)", "cumulative")):
        out.write(f"\n===== {title} =====\n")
        stats = pstats.Stats(profile, stream=out)
        stats.sort_stats(key).print_stats(limit)
    return out.getvalue()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    profile = cProfile.Profile()
    sys.argv = [str(ROOT / "main.py")]
    try:
        profile.runcall(runpy.run_path, str(ROOT / "main.py"), run_name="__main__")
    except SystemExit:
        pass
    text = summarize(profile)
    (ROOT / "nebula_profile.txt").write_text(text, encoding="utf-8")
    print(text)
    print("\nÉcrit dans", ROOT / "nebula_profile.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
