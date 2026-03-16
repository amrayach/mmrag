import logging
import os
import shutil

from fastapi import APIRouter

from .. import config

logger = logging.getLogger("controlcenter.routes.system")

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/config")
async def system_config():
    """Effective env vars with secrets masked."""
    env_vars = {}
    for key, val in sorted(os.environ.items()):
        # Skip internal/system vars
        if key.startswith("_") or key in ("PATH", "HOME", "HOSTNAME", "PWD", "SHLVL", "TERM"):
            continue
        # Mask secrets
        if any(pat in key.upper() for pat in config.SECRET_PATTERNS):
            env_vars[key] = "****"
        else:
            env_vars[key] = val
    return {"env": env_vars}


@router.get("/disk-usage")
async def disk_usage():
    """Disk usage for mounted data directories."""
    data_dir = config.PROJECT_DATA_DIR
    dirs = {}

    for name in ["inbox", "processed", "assets", "error"]:
        path = os.path.join(data_dir, name)
        if os.path.isdir(path):
            total_size = 0
            file_count = 0
            try:
                for dirpath, _dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            total_size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            pass
            except OSError:
                pass
            dirs[name] = {"size": total_size, "files": file_count}
        else:
            dirs[name] = {"size": 0, "files": 0, "missing": True}

    # Overall disk usage for data partition
    try:
        usage = shutil.disk_usage(data_dir)
        partition = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total > 0 else 0,
        }
    except OSError:
        partition = None

    return {"directories": dirs, "partition": partition}


@router.get("/service-graph")
async def service_graph():
    """Service dependency graph data for visualization."""
    return {"nodes": [
        {"id": "postgres", "label": "PostgreSQL", "type": "database"},
        {"id": "ollama", "label": "Ollama", "type": "gpu"},
        {"id": "n8n", "label": "n8n", "type": "workflow"},
        {"id": "pdf_ingest", "label": "PDF Ingest", "type": "service"},
        {"id": "rss_ingest", "label": "RSS Ingest", "type": "service"},
        {"id": "rag_gateway", "label": "RAG Gateway", "type": "service"},
        {"id": "openwebui", "label": "OpenWebUI", "type": "frontend"},
        {"id": "filebrowser", "label": "FileBrowser", "type": "frontend"},
        {"id": "assets", "label": "Assets", "type": "frontend"},
        {"id": "adminer", "label": "Adminer", "type": "frontend"},
        {"id": "controlcenter", "label": "Control Center", "type": "service"},
    ], "edges": [
        {"from": "n8n", "to": "postgres"},
        {"from": "n8n", "to": "ollama"},
        {"from": "pdf_ingest", "to": "postgres"},
        {"from": "pdf_ingest", "to": "ollama"},
        {"from": "rss_ingest", "to": "postgres"},
        {"from": "rss_ingest", "to": "ollama"},
        {"from": "rag_gateway", "to": "n8n"},
        {"from": "rag_gateway", "to": "ollama"},
        {"from": "openwebui", "to": "rag_gateway"},
        {"from": "adminer", "to": "postgres"},
        {"from": "controlcenter", "to": "postgres"},
    ]}
