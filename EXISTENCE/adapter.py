"""Small, process-safe adapter for the Existence environment.

Existence currently validates and routes messages itself. This adapter gives it
an explicit Nebula endpoint now, so the transport can evolve from catalogue
events to real process communication without coupling the painting engine to
the hub. Every response is one JSON object, suitable for JSON-lines transport.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_DIR / "manifest.json"
PROJECT_ROOT = PACKAGE_DIR.parent


def load_manifest() -> dict[str, Any]:
    """Load Nebula's immutable Existence identity from the local package."""
    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    manifest["working_dir"] = str(PROJECT_ROOT)
    return manifest


def _resource_uri(resource_id: str) -> str:
    value = str(resource_id).strip().strip("/")
    if value.startswith("resource://"):
        return value
    return f"resource://existence/nebula/{value or 'current'}"


def _response(request_id: Any, ok: bool, **payload: Any) -> dict[str, Any]:
    return {
        "protocol": "existence.nebula.v1",
        "request_id": request_id,
        "ok": ok,
        "time": time.time(),
        **payload,
    }


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    """Handle a side-effect-light Existence request.

    Opening a document is intentionally acknowledged as *deferred*: the GUI
    process owns the Qt event loop and will consume the routed resource. This
    keeps the headless bridge deterministic and prevents a second QApplication
    from being created by the hub.
    """
    manifest = load_manifest()
    request_id = message.get("request_id")
    kind = str(message.get("message", message.get("type", ""))).strip()
    payload = message.get("payload") or {}

    if kind == "ping":
        return _response(request_id, True, message="pong", app=manifest["id"])
    if kind in {"get_state", "describe"}:
        return _response(
            request_id,
            True,
            app=manifest["id"],
            lifecycle_state=manifest["lifecycle_state"],
            capabilities=manifest["capabilities"],
            resource_namespace=manifest["resource_namespace"],
        )
    if kind == "handshake":
        return _response(
            request_id,
            True,
            handshake=True,
            app=manifest["id"],
            manifest=manifest,
            transport="unix-json-lines",
        )
    if kind == "close":
        return _response(request_id, True, lifecycle_state="closed")
    if kind in {"open_as_raster", "send_resource"}:
        resource = payload.get("resource", message.get("resource", ""))
        if not resource:
            return _response(request_id, False, error="resource is required")
        return _response(
            request_id,
            True,
            accepted_message=kind,
            resource=_resource_uri(resource),
            disposition="deferred_to_gui",
            working_dir=str(PROJECT_ROOT),
        )
    return _response(
        request_id,
        False,
        error=f"unsupported message: {kind or '<empty>'}",
        accepted_messages=manifest["accepted_messages"],
    )


def _write(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve_unix_socket(socket_path: str | os.PathLike[str]) -> int:
    """Serve the same JSON-lines protocol over a private Unix socket."""
    path = Path(socket_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.settimeout(0.25)
    try:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(8)
        running = True
        while running:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                connection_file = connection.makefile("rwb")
                try:
                    for raw_line in connection_file:
                        if not raw_line.strip():
                            continue
                        try:
                            request = json.loads(raw_line.decode("utf-8"))
                            response = handle_message(request)
                            if request.get("message", request.get("type")) == "close":
                                running = False
                        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                            response = _response(None, False, error=f"invalid json request: {exc}")
                        connection_file.write(
                            (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                        )
                        connection_file.flush()
                finally:
                    connection_file.close()
    finally:
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nebula <-> Existence adapter")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--manifest", action="store_true")
    group.add_argument("--handshake", action="store_true")
    group.add_argument("--message", action="store_true")
    parser.add_argument("--socket", metavar="PATH", help="serve JSON Lines over a Unix socket")
    args = parser.parse_args(argv)

    if not args.socket and not (args.manifest or args.handshake or args.message):
        parser.error("one of --manifest, --handshake, --message or --socket is required")

    if args.socket:
        return serve_unix_socket(args.socket)

    manifest = load_manifest()
    if args.manifest:
        _write(manifest)
        return 0
    if args.handshake:
        _write({"protocol": "existence.nebula.v1", "manifest": manifest})
        return 0

    for line in sys.stdin:
        if line.strip():
            try:
                _write(handle_message(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                _write(_response(None, False, error=f"invalid json request: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
