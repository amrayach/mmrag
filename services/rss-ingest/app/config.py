import os

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME", "rag")
DB_USER = os.getenv("DATABASE_USER", "rag_user")
DB_PASS = os.getenv("DATABASE_PASSWORD", "")

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))

# ---------------------------------------------------------------------------
# Ingestion limits
# ---------------------------------------------------------------------------
MAX_ARTICLES_PER_FEED = int(os.getenv("MAX_ARTICLES_PER_FEED", "20"))
MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "50"))

# ---------------------------------------------------------------------------
# Image captioning (OFF by default to avoid vision model swap thrash)
# ---------------------------------------------------------------------------
CAPTION_IMAGES = os.getenv("CAPTION_IMAGES", "false").lower() == "true"
MAX_IMAGES_PER_ARTICLE = int(os.getenv("MAX_IMAGES_PER_ARTICLE", "3"))

# ---------------------------------------------------------------------------
# Rate limiting / politeness
# ---------------------------------------------------------------------------
FETCH_DELAY_SECS = float(os.getenv("FETCH_DELAY_SECS", "2.0"))
FEED_DELAY_SECS = float(os.getenv("FEED_DELAY_SECS", "5.0"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "30"))
USER_AGENT = os.getenv("USER_AGENT", "MMRAG-RSS-Bot/1.0 (internal-research-demo)")

# ---------------------------------------------------------------------------
# Lock / assets / feeds
# ---------------------------------------------------------------------------
LOCK_FILE = os.getenv("LOCK_FILE", "/tmp/rss_ingest.lock")
ASSETS_DIR = os.getenv("ASSETS_DIR", "/kb/assets")
RSS_FEEDS_ENABLED = os.getenv("RSS_FEEDS_ENABLED", "all")
