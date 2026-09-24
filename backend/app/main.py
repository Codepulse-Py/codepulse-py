"""CodePulse-Py API stub.

Event ingestion (Socket.IO, 100 ms batches) lands in #20; this only exposes a
health endpoint so the Compose stack and CI have something to probe.
"""

import os

from fastapi import FastAPI

app = FastAPI(title="CodePulse-Py API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "api",
        "deps": {
            "database": bool(os.getenv("DATABASE_URL")),
            "redis": bool(os.getenv("REDIS_URL")),
            "sandbox": bool(os.getenv("SANDBOX_URL")),
            "llm": bool(os.getenv("LLM_URL")),
        },
    }
