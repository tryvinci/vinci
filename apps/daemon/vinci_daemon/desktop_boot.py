"""Desktop launcher hooks: parent watch and stdout readiness marker."""

from __future__ import annotations

import os
import threading
import time


def configure_desktop(launch_nonce: str, parent_pid: int) -> None:
    os.environ["VINCI_DESKTOP"] = "1"
    if launch_nonce:
        os.environ["VINCI_LAUNCH_NONCE"] = launch_nonce
    if parent_pid > 0:
        start_parent_watch(parent_pid)


def start_parent_watch(parent_pid: int) -> None:
    def _watch() -> None:
        while True:
            if os.getppid() != parent_pid:
                os._exit(0)
            try:
                os.kill(parent_pid, 0)
            except OSError:
                os._exit(0)
            time.sleep(0.5)

    threading.Thread(target=_watch, name="vinci-parent-watch", daemon=True).start()


def emit_ready(port: int, launch_nonce: str) -> None:
    nonce = launch_nonce or os.environ.get("VINCI_LAUNCH_NONCE", "")
    print(f"READY {port} {nonce}", flush=True)
