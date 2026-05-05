"""Dev/smoke entry point: ``python -m iguanatrader.api`` boots uvicorn.

Used by the manual smoke step (slice 4 task 7.6). Production deployment
uses a process supervisor (TBD — slice T4 lands the systemd unit), not
this shim.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("IGUANATRADER_API_HOST", "127.0.0.1")
    port = int(os.getenv("IGUANATRADER_API_PORT", "8000"))
    uvicorn.run(
        "iguanatrader.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    main()
