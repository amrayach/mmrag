import base64
import logging
import time
from typing import List

import requests

from app.config import EMBED_MODEL, OLLAMA_BASE, VISION_MODEL

logger = logging.getLogger("rss-ingest")

CAPTION_PROMPTS = {
    "de": "Beschreibe dieses Bild kurz und präzise auf Deutsch (1-2 Sätze).",
    "en": "Describe this image briefly and precisely in English (1-2 sentences).",
    "fr": "Décrivez cette image brièvement et précisément en français (1-2 phrases).",
}

CONTEXTUAL_CAPTION_PROMPTS = {
    "de": (
        'Dieses Bild stammt aus dem Artikel "{title}" ({feed}).'
        " Beschreibe was das Bild zeigt und wie es zum Artikelthema passt (2-3 Sätze)."
    ),
    "en": (
        'This image is from the article "{title}" ({feed}).'
        " Describe what the image shows and how it relates to the article topic (2-3 sentences)."
    ),
}


def _retry(fn, max_retries=3, backoff=(2, 4, 8)):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except (requests.RequestException, requests.Timeout, ConnectionError) as e:
            if attempt == max_retries:
                raise
            delay = backoff[min(attempt, len(backoff) - 1)]
            logger.warning(
                "Ollama call failed (attempt %d/%d), retrying in %ds: %s",
                attempt + 1, max_retries, delay, e,
            )
            time.sleep(delay)


def ollama_embeddings(text: str) -> List[float]:
    resp = requests.post(
        f"{OLLAMA_BASE}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def ollama_caption_image(image_bytes: bytes, lang: str = "de") -> str:
    prompt = CAPTION_PROMPTS.get(lang, CAPTION_PROMPTS["de"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return (resp.json().get("message", {}) or {}).get("content", "").strip()


def ollama_caption_image_contextual(
    image_bytes: bytes, title: str, feed_name: str, lang: str = "de",
) -> str:
    """Caption an image with article context for better semantic relevance."""
    template = CONTEXTUAL_CAPTION_PROMPTS.get(lang, CONTEXTUAL_CAPTION_PROMPTS["de"])
    prompt = template.format(title=title[:120], feed=feed_name[:30])
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return (resp.json().get("message", {}) or {}).get("content", "").strip()


def enriched_image_embedding_text(caption: str, title: str, feed_name: str) -> str:
    """Build enriched text for image embedding: [feed] title — caption."""
    return f"[{feed_name}] {title} — {caption}"
