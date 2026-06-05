"""FastAPI entry point.

Week 1: health + DB connectivity only. Routers for /query, /benchmark,
/history are wired up in later weeks (stubs imported defensively)."""
import logging

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("t2sql")

app = FastAPI(
    title="Text-to-SQL Platform",
    description="Natural language to SQL with multi-LLM benchmarking and RAG self-correction.",
    version="0.1.0",
)

# React dev server (Week 7) will run on :5173 (Vite) or :3000 (CRA).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness probe — does the app respond at all?"""
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/db")
def health_db() -> dict:
    """Readiness probe — can we reach both application databases?"""
    results = {}
    for name, dsn in (
        ("metadata", settings.metadata_dsn),
        ("spider", settings.spider_admin_dsn),
    ):
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    version = cur.fetchone()[0]
            results[name] = {"reachable": True, "server": version.split(",")[0]}
        except Exception as exc:  # noqa: BLE001 - report any failure to caller
            log.warning("DB %s unreachable: %s", name, exc)
            results[name] = {"reachable": False, "error": str(exc)}

    all_ok = all(r["reachable"] for r in results.values())
    return {"status": "ok" if all_ok else "degraded", "databases": results}


@app.get("/")
def root() -> dict:
    return {
        "service": "text-to-sql",
        "docs": "/docs",
        "health": "/health",
    }
