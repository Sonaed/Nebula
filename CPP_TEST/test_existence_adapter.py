import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExistenceAdapterTests(unittest.TestCase):
    def run_adapter(self, *args, input_text=""):
        return subprocess.run(
            [sys.executable, "-m", "EXISTENCE.adapter", *args],
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_manifest_exposes_universe_contract(self):
        result = self.run_adapter("--manifest")
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["id"], "nebula")
        self.assertEqual(manifest["app_kind"], "universe")
        self.assertIn("brush_engine_cpp", manifest["capabilities"])
        self.assertEqual(manifest["resource_namespace"], "resource://existence/nebula")

    def test_main_entrypoint_can_serve_manifest_headlessly(self):
        result = subprocess.run(
            [sys.executable, "main.py", "--existence-manifest"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["id"], "nebula")

    def test_json_lines_handshake_and_ping(self):
        result = self.run_adapter(
            "--message",
            input_text=json.dumps({"request_id": "t1", "message": "ping"}) + "\n",
        )
        response = json.loads(result.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["message"], "pong")
        self.assertEqual(response["request_id"], "t1")

    def test_open_resource_is_deferred_to_gui(self):
        result = self.run_adapter(
            "--message",
            input_text=json.dumps(
                {"message": "open_as_raster", "payload": {"resource": "atlas/image/42"}}
            ) + "\n",
        )
        response = json.loads(result.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["disposition"], "deferred_to_gui")
        self.assertEqual(response["resource"], "resource://existence/nebula/atlas/image/42")

    @staticmethod
    def socket_request(client, payload):
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buffer = b""
        while b"\n" not in buffer:
            buffer += client.recv(4096)
        return json.loads(buffer.split(b"\n", 1)[0].decode("utf-8"))

    def test_unix_socket_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "nebula.sock"
            process = subprocess.Popen(
                [sys.executable, "-m", "EXISTENCE.adapter", "--socket", str(socket_path)],
                cwd=ROOT,
            )
            client = None
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if socket_path.exists():
                        try:
                            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            client.connect(str(socket_path))
                            break
                        except OSError:
                            client.close()
                            client = None
                    time.sleep(0.02)
                self.assertIsNotNone(client, "Nebula socket did not become available")
                self.assertTrue(self.socket_request(client, {"type": "handshake"})["ok"])
                self.assertEqual(self.socket_request(client, {"type": "ping"})["message"], "pong")
                state = self.socket_request(client, {"type": "describe"})
                self.assertEqual(state["lifecycle_state"], "available")
                sent = self.socket_request(
                    client,
                    {"type": "send_resource", "payload": {"resource": "atlas/image/42"}},
                )
                self.assertEqual(sent["disposition"], "deferred_to_gui")
                self.assertEqual(self.socket_request(client, {"type": "close"})["lifecycle_state"], "closed")
                client.close()
                self.assertEqual(process.wait(timeout=3), 0)
                self.assertFalse(socket_path.exists())
            finally:
                if client is not None:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)

    def test_unix_socket_closes_when_universe_crashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "nebula-crash.sock"
            process = subprocess.Popen(
                [sys.executable, "-m", "EXISTENCE.adapter", "--socket", str(socket_path)],
                cwd=ROOT,
            )
            client = None
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and client is None:
                    if socket_path.exists():
                        try:
                            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            client.connect(str(socket_path))
                        except OSError:
                            client.close()
                            client = None
                    time.sleep(0.02)
                self.assertIsNotNone(client, "Nebula crash test could not connect")
                process.terminate()
                self.assertEqual(process.wait(timeout=3), -15)
                self.assertEqual(client.recv(1), b"")
            finally:
                if client is not None:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
