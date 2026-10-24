"""Ciclo de vida del servidor de escritorio: arranca con --desktop y se cierra cuando muere el proceso padre."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_exits_when_parent_dies(tmp_path):
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "pospy", "--port", str(port), "--data-dir", str(tmp_path), "--desktop",
                               "--parent-pid", str(parent.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310
                    assert b'"desktop":true' in r.read()
                    break
            except OSError:
                time.sleep(0.3)
        else:
            raise AssertionError("el servidor no arrancó")
        parent.kill()
        assert server.wait(timeout=20) == 0
    finally:
        parent.kill()
        server.kill()
