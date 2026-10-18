"""Shared "run a fake HTTP server for the duration of one test" helper --
used by `test_generation.py`, `test_news.py` and anything else that needs a
fake OpenAI/feed server on a local port, without those modules importing
each other (which both `test_generation.py`'s fake OpenAI server and
`test_news.py`'s fake feed/responses servers need)."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI


@contextlib.asynccontextmanager
async def _running_http(app: FastAPI, port: int) -> AsyncIterator[str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("fake server did not start in time")
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
