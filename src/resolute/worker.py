"""Background worker — runs graph jobs from a Redis queue.

In production this polls Redis for ticket jobs and processes them through
the LangGraph support graph.  For now it serves as the Docker CMD target
for the worker container.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from resolute.config import settings


async def _run() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    print(f"worker: listening (offline={settings.offline})", flush=True)  # noqa: T201
    await stop.wait()
    print("worker: shutting down", flush=True)  # noqa: T201


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
