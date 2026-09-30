"""Safely convert a legacy Nebula-supported document to `.nebula`.

Usage: python TOOLS/migrate_nebula.py source.csd [destination.nebula]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DOCUMENTS.format_nebula import NebulaFormat


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Migrer un document vers le format Nebula natif")
    parser.add_argument("source", type=Path, help="document CSD, Atlas, PSD, PSB ou NBL source")
    parser.add_argument("destination", type=Path, nargs="?", help="nouveau fichier .nebula")
    args = parser.parse_args(argv)
    try:
        target = NebulaFormat.migrate(args.source, args.destination)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
