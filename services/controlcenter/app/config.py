import os

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_HOST = os.getenv("DATABASE_HOST", "postgres")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_NAME = os.getenv("DATABASE_NAME", "rag")
DATABASE_USER = os.getenv("DATABASE_USER", "rag_user")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "qwen2.5:7b-instruct")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# ---------------------------------------------------------------------------
# Internal service URLs
# ---------------------------------------------------------------------------
N8N_BASE_URL = "http://n8n:5678"
N8N_CHAT_WEBHOOK_URL = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://n8n:5678/webhook/rag-chat")
PDF_INGEST_URL = "http://pdf-ingest:8001"
RSS_INGEST_URL = "http://rss-ingest:8002"
RAG_GATEWAY_URL = "http://rag-gateway:8000"

# ---------------------------------------------------------------------------
# Public URLs
# ---------------------------------------------------------------------------
PUBLIC_ASSETS_BASE_URL = os.getenv("PUBLIC_ASSETS_BASE_URL", "")
TAILNET_HOST = os.getenv("TAILNET_HOST", "")

# ---------------------------------------------------------------------------
# Docker container prefix (safety filter)
# ---------------------------------------------------------------------------
CONTAINER_PREFIX = "ammer_mmragv2_"
CRITICAL_CONTAINERS = {"ammer_mmragv2_postgres", "ammer_mmragv2_ollama", "ammer_mmragv2_n8n"}

# ---------------------------------------------------------------------------
# Service health endpoints (container_name -> health URL)
# ---------------------------------------------------------------------------
SERVICE_HEALTH_URLS = {
    "ammer_mmragv2_n8n": "http://n8n:5678/healthz",
    "ammer_mmragv2_ollama": "http://ollama:11434/api/version",
    "ammer_mmragv2_rag_gateway": "http://rag-gateway:8000/health/ready",
    "ammer_mmragv2_pdf_ingest": "http://pdf-ingest:8001/health/ready",
    "ammer_mmragv2_rss_ingest": "http://rss-ingest:8002/health/ready",
    "ammer_mmragv2_controlcenter": "http://localhost:8000/health",
}

# ---------------------------------------------------------------------------
# Tailscale port map (for display)
# ---------------------------------------------------------------------------
TAILSCALE_PORT_MAP = {
    "ammer_mmragv2_n8n": 8450,
    "ammer_mmragv2_openwebui": 8451,
    "ammer_mmragv2_filebrowser": 8452,
    "ammer_mmragv2_adminer": 8453,
    "ammer_mmragv2_assets": 8454,
    "ammer_mmragv2_controlcenter": 8455,
}

# ---------------------------------------------------------------------------
# httpx timeout presets (seconds)
# ---------------------------------------------------------------------------
TIMEOUT_SHORT = 5
TIMEOUT_STANDARD = 30
TIMEOUT_LONG = 180
TIMEOUT_N8N_WEBHOOK = 300

# ---------------------------------------------------------------------------
# Env var blocklist for exposure filtering
# ---------------------------------------------------------------------------
SECRET_PATTERNS = ("PASSWORD", "SECRET", "KEY", "ENCRYPTION")

# ---------------------------------------------------------------------------
# Internal asset proxy
# ---------------------------------------------------------------------------
ASSETS_INTERNAL_URL = "http://assets:80"

# ---------------------------------------------------------------------------
# Data paths (mounted read-only)
# ---------------------------------------------------------------------------
PROJECT_DOCS_DIR = "/app/project-docs"
PROJECT_DATA_DIR = "/app/project-data"
