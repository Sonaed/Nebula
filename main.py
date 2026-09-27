import sys


def _run_existence_adapter() -> bool:
    """Serve Existence metadata/messages without starting a second Qt app."""
    if len(sys.argv) < 2 or sys.argv[1] not in {
        "--existence-manifest",
        "--existence-handshake",
        "--existence-message",
        "--existence-socket",
    }:
        return False
    from EXISTENCE.adapter import main as adapter_main

    command = {
        "--existence-manifest": "--manifest",
        "--existence-handshake": "--handshake",
        "--existence-message": "--message",
        "--existence-socket": "--socket",
    }[sys.argv[1]]
    arguments = [command]
    if sys.argv[1] == "--existence-socket":
        if len(sys.argv) < 3:
            raise SystemExit("--existence-socket requires a path")
        arguments.append(sys.argv[2])
    raise SystemExit(adapter_main(arguments))

CRASH_DIR = None


def _install_crash_reporting() -> None:
    """Un plantage laisse toujours une trace lisible, même un SIGSEGV de Qt.

    * faulthandler écrit la pile Python de TOUS les threads dans crash.log ;
    * une exception Python non gérée est journalisée au lieu de disparaître ;
    * si la session précédente ne s'est pas fermée proprement, on le note pour
      que l'interface reparte d'un agencement sûr.
    """
    global CRASH_DIR
    import faulthandler
    import os
    import time
    import traceback
    from pathlib import Path

    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    CRASH_DIR = Path(base) / "CreativeSystem" / "nebula"
    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    running = CRASH_DIR / "running"
    if running.exists():
        (CRASH_DIR / "previous_session_crashed").write_text(running.read_text(encoding="utf-8"), encoding="utf-8")
    running.write_text(f"pid={os.getpid()} start={time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    log = open(CRASH_DIR / "crash.log", "a", encoding="utf-8")
    log.write(f"\n=== Nebula démarré {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} ===\n")
    log.flush()
    faulthandler.enable(file=log, all_threads=True)

    def hook(kind, value, tb):
        log.write("".join(traceback.format_exception(kind, value, tb)))
        log.flush()
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = hook


def _mark_clean_exit() -> None:
    if CRASH_DIR is not None:
        try:
            (CRASH_DIR / "running").unlink()
        except OSError:
            pass


def main():
    _run_existence_adapter()
    # Keep PySide6 and the Qt application strictly on the GUI path. Existence
    # can query Nebula's manifest or exchange JSON-lines messages headlessly.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    from CORE.application import CreativeSystem
    from UI.theme import ThemeManager

    # QOpenGLTextureBlitter has a legacy GLSL-ES shader path which can try to
    # compile ``layout(blend_support_*)`` qualifiers on drivers exposing
    # GL_KHR_blend_equation_advanced.  On a desktop Linux session this may
    # result in GLSL 1.00 compile errors (and a transparent/flickering canvas).
    # Request a desktop compatibility context before QApplication is created;
    # the renderer still keeps its CPU fallback when no such context exists.
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
        True,
    )

    surface_format = QSurfaceFormat()
    surface_format.setRenderableType(
        QSurfaceFormat.RenderableType.OpenGL
    )
    surface_format.setVersion(3, 3)
    surface_format.setProfile(
        QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile
    )
    surface_format.setSwapBehavior(
        QSurfaceFormat.SwapBehavior.DoubleBuffer
    )
    surface_format.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface_format)

    _install_crash_reporting()
    app = QApplication(sys.argv)
    # Apply Nebula before any dialog, dock or detached popup is constructed.
    # Applying it only to the main window left certain top-level dialogs with
    # the platform palette, which made the Nebula identity appear to vanish.
    ThemeManager.apply(app)

    window = CreativeSystem()
    window.run()

    code = app.exec()
    _mark_clean_exit()
    sys.exit(code)


if __name__ == "__main__":
    main()
