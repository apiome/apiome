"""Serve an ASGI app with Uvicorn on a free loopback port for the length of a test module.

Shared by the suites that need the real HTTP stack (``test_agent_runtime_http``,
``test_agent_self_conformance``): a background thread runs the server with ``lifespan="on"``, so
each mounted FastMCP app opens its own lifespan exactly as ``apiome-mcp serve --transport http``.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import uvicorn


def free_port() -> int:
    """A TCP port on 127.0.0.1 that was free a moment ago."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def serve_http_app(app: Any, *, startup_timeout: float = 15.0) -> Generator[str, None, None]:
    """Run ``app`` until the block exits; yield its root URL (``http://127.0.0.1:<port>``).

    Args:
        app: The ASGI app (e.g. :func:`apiome_mcp.http_app.build_http_app`'s result).
        startup_timeout: Seconds to wait for Uvicorn to report it started.

    Raises:
        RuntimeError: If the server does not start in time.
    """
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    ready = threading.Event()
    stop = threading.Event()

    def _run() -> None:
        async def _serve() -> None:
            task = asyncio.ensure_future(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            server.should_exit = True
            await task

        asyncio.run(_serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    if not ready.wait(timeout=startup_timeout):
        raise RuntimeError(f"HTTP app did not start within {startup_timeout:g} s")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop.set()
        thread.join(timeout=5)
