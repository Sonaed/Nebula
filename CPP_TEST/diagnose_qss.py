"""Trouve ce que Qt reproche à la feuille de style de Nebula.

Usage (depuis la racine du projet) :  python CPP_TEST/diagnose_qss.py

Applique la feuille de style rendue par ThemeManager, affiche TOUS les messages
Qt qu'elle provoque (« Unknown property ... », « Could not parse ... »), puis, si
l'analyse échoue, cherche par dichotomie la première règle fautive.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def split_rules(css: str) -> list[str]:
    """Découpe en règles de premier niveau (accolades équilibrées)."""
    rules, depth, start = [], 0, 0
    for index, char in enumerate(css):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append(css[start:index + 1].strip())
                start = index + 1
    tail = css[start:].strip()
    if tail:
        rules.append(tail)  # texte résiduel = accolade non fermée ou déchet
    return [rule for rule in rules if rule]


def first_bad_rule(rules: list[str], parses) -> int | None:
    """Indice de la première règle qui fait échouer l'analyse d'un préfixe.

    ``parses(text) -> bool``.  L'échec est monotone : une règle fautive fait
    échouer tout préfixe qui la contient.
    """
    if parses("\n".join(rules)):
        return None
    low, high = 0, len(rules)  # préfixe [0, high) échoue, [0, low) passe
    while high - low > 1:
        middle = (low + high) // 2
        if parses("\n".join(rules[:middle])):
            low = middle
        else:
            high = middle
    return high - 1


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QApplication, QWidget
    from UI.theme import ThemeManager

    messages: list[str] = []
    qInstallMessageHandler(lambda _mode, _context, text: messages.append(text))
    app = QApplication([])

    def apply(text: str) -> list[str]:
        messages.clear()
        app.setStyleSheet(text)
        widget = QWidget()
        widget.ensurePolished()
        widget.deleteLater()
        return list(messages)

    def parses(text: str) -> bool:
        return not any("Could not parse" in m for m in apply(text))

    css = ThemeManager.stylesheet()
    everything = apply(css)
    print(f"{len(everything)} message(s) Qt pour la feuille complète :")
    for message in sorted(set(everything)):
        print("  ", message)
    rules = split_rules(strip_comments(css))
    print(f"\n{len(rules)} règles de premier niveau.")
    bad = first_bad_rule(rules, parses)
    if bad is None:
        print("L'analyse réussit sur la feuille rendue par ThemeManager.")
        print("Le message vient donc d'AILLEURS : un autre app.setStyleSheet(...) ou un "
              "setStyleSheet de widget.  Cherchez-les avec :  grep -rn setStyleSheet --include=*.py .")
    else:
        print("\nPremière règle fautive :\n")
        print(rules[bad])
        print("\nSeule, elle passe-t-elle ?", parses(rules[bad]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
