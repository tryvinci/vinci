"""Container entry: run daemon with persistence wired through FastAPI lifespan."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    home = Path(os.environ.get("VINCI_HOME", "/data/.vinci")).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("VINCI_HOME", str(home))
    os.environ.setdefault("VINCI_SELFHOST", "1")

    host = os.environ.get("VINCI_DAEMON_HOST", "0.0.0.0")
    port = int(os.environ.get("VINCI_DAEMON_PORT", "8080"))
    import uvicorn

    uvicorn.run(
        "vinci_daemon.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level=os.environ.get("VINCI_LOG_LEVEL", "info"),
        timeout_graceful_shutdown=int(os.environ.get("VINCI_GRACEFUL_SHUTDOWN_SEC", "150")),
    )


if __name__ == "__main__":
    main()
