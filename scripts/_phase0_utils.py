"""Shared helpers for Phase 0 retrieval diagnostic scripts.

- Re-execs into an existing ``.venv-phase0/`` when invoked via the host system
  Python and ``psycopg`` is missing. It does not install packages itself.
- Loads project ``.env`` variables.
- Builds Postgres connections via TCP ``host=127.0.0.1`` (NEVER Unix socket /
  peer auth) using the canonical project env vars: ``POSTGRES_USER``,
  ``POSTGRES_PASSWORD``, ``RAG_DB``, ``PORT_PG``.
- Provides Phase 0 output paths under ``data/eval/phase0_baseline/``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv-phase0" / "bin" / "python"


def ensure_venv() -> None:
    """Re-exec the current script under ``.venv-phase0`` python if psycopg is
    missing in the active interpreter. Compares ``sys.prefix`` (not the
    executable symlink) to detect whether we're already inside the venv —
    venv ``python`` typically symlinks to the system interpreter, so resolving
    the executable path collapses both to the same physical file."""
    try:
        import psycopg  # noqa: F401
        return
    except ImportError:
        pass
    venv_root = ROOT / ".venv-phase0"
    if Path(sys.prefix).resolve() == venv_root.resolve():
        # Already inside the venv but psycopg is still missing — surface a clear
        # ImportError to the caller instead of looping.
        return
    if VENV_PY.exists():
        os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse the project ``.env`` file. Only handles ``KEY=VALUE`` lines —
    no quoting, no interpolation. Lines starting with ``#`` and blank lines
    are skipped. Returns a dict; does NOT mutate ``os.environ``."""
    if path is None:
        path = ROOT / ".env"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip optional surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        out[key] = value
    return out


def db_conninfo() -> str:
    """Return a libpq conninfo string that uses TCP ``host=127.0.0.1``.

    Pulls user/password/db/port from the project ``.env`` file with a fallback
    to the current process environment. Never relies on the in-container
    ``DATABASE_HOST=postgres`` value because diagnostic scripts run on the
    host where ``postgres`` is not resolvable.
    """
    env = load_env_file()
    user = env.get("POSTGRES_USER") or os.environ.get("POSTGRES_USER") or "rag_user"
    password = (
        env.get("POSTGRES_PASSWORD")
        or os.environ.get("POSTGRES_PASSWORD")
        or ""
    )
    dbname = env.get("RAG_DB") or os.environ.get("RAG_DB") or "rag"
    port = env.get("PORT_PG") or os.environ.get("PORT_PG") or "56154"
    host = "127.0.0.1"
    return (
        f"host={host} port={port} dbname={dbname} "
        f"user={user} password={password}"
    )


def open_db_connection():
    """Open a psycopg connection using ``db_conninfo()``."""
    import psycopg  # type: ignore[import-not-found]
    return psycopg.connect(db_conninfo())


def phase0_baseline_dir() -> Path:
    p = ROOT / "data" / "eval" / "phase0_baseline"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gateway_url() -> str:
    return os.environ.get("RAG_GATEWAY_URL", "http://127.0.0.1:56155")


def trace_jsonl_path() -> Path:
    """Host path of the rag-gateway trace file (volume-mounted)."""
    return ROOT / "data" / "rag-traces" / "retrieval.jsonl"
