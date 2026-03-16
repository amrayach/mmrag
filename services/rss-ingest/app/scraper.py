import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

import feedparser
from bs4 import BeautifulSoup

from app.config import FETCH_TIMEOUT, USER_AGENT
from app.feeds import DEFAULT_SELECTOR, FeedConfig

logger = logging.getLogger("rss-ingest")

# ---------------------------------------------------------------------------
# Scrapling / fallback imports
# ---------------------------------------------------------------------------
_USE_SCRAPLING = False
try:
    from scrapling.fetchers import StealthyFetcher
    _USE_SCRAPLING = True
    logger.info("Scrapling StealthyFetcher available — using headless Chromium")
except ImportError:
    logger.warning("Scrapling not available — falling back to requests + BeautifulSoup")
    import requests as _requests


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def parse_feed(feed_config: FeedConfig) -> List[Dict]:
    """Parse an RSS/Atom feed and return entries with normalized fields."""
    feed = feedparser.parse(feed_config.feed_url)
    entries = []
    for entry in feed.entries:
        url = entry.get("link", "")
        if not url:
            continue
        # Extract content:encoded or summary
        content_encoded = ""
        if hasattr(entry, "content") and entry.content:
            content_encoded = entry.content[0].get("value", "")
        entries.append({
            "url": url,
            "title": entry.get("title", ""),
            "author": entry.get("author", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
            "content_encoded": content_encoded,
        })
    return entries


# ---------------------------------------------------------------------------
# Article fetching
# ---------------------------------------------------------------------------


def fetch_article(url: str, feed_config: FeedConfig) -> Optional[object]:
    """Fetch article page. Returns a Scrapling Response or BeautifulSoup object."""
    try:
        if _USE_SCRAPLING:
            page = StealthyFetcher.fetch(url, headless=True, timeout=FETCH_TIMEOUT * 1000)
            if page.status == 200:
                return page
            logger.warning("Fetch %s returned status %s", url, page.status)
            return None
        else:
            resp = _requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=FETCH_TIMEOUT,
            )
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            logger.warning("Fetch %s returned status %s", url, resp.status_code)
            return None
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def extract_article_content(
    page, feed_config: FeedConfig, fallback_summary: str, content_encoded: str
) -> Tuple[str, List[str]]:
    """
    Extract article text and image URLs from a fetched page.
    3-tier fallback: CSS selectors -> content:encoded -> description/summary.
    Returns (text, image_urls).
    """
    text = ""
    image_urls: List[str] = []

    if page is not None:
        text = _extract_with_selectors(page, feed_config)

    # Tier 2: content:encoded from RSS
    if len(text) < 100 and content_encoded:
        text = _clean_html_to_text(content_encoded)
        logger.info("CSS extraction insufficient, using content:encoded (%d chars)", len(text))

    # Tier 3: RSS description/summary
    if len(text) < 100 and fallback_summary:
        text = _clean_html_to_text(fallback_summary)
        logger.info("Using RSS summary fallback (%d chars)", len(text))

    # Extract image URLs if page available
    if page is not None and feed_config.img_selector:
        image_urls = _extract_image_urls(page, feed_config)

    return text.strip(), image_urls


def _extract_with_selectors(page, feed_config: FeedConfig) -> str:
    """Try CSS selectors from feed config to extract article body text."""
    selectors = feed_config.article_selector.split(",")
    selectors.append(DEFAULT_SELECTOR)

    for selector in selectors:
        selector = selector.strip()
        if not selector:
            continue
        try:
            if _USE_SCRAPLING:
                elements = page.css(selector)
                if elements:
                    parts = []
                    for el in elements:
                        # get_all_text() is the Scrapling 0.4 API for deep text
                        raw = el.get_all_text() or ""
                        parts.append(raw)
                    text = "\n\n".join(p.strip() for p in parts if p.strip())
                    # Strip unwanted content via BeautifulSoup on the joined text
                    # (Scrapling 0.4 elements don't support .remove())
                    if feed_config.strip_selectors and text and len(text) >= 100:
                        text = _strip_selectors_from_html(
                            el.html_content if len(elements) == 1 else text,
                            feed_config,
                            is_html=(len(elements) == 1),
                        )
                    if len(text) >= 100:
                        return text
            else:
                # BeautifulSoup path
                elements = page.select(selector)
                if elements:
                    parts = []
                    for el in elements:
                        for strip_sel in feed_config.strip_selectors:
                            for bad in el.select(strip_sel):
                                bad.decompose()
                        parts.append(el.get_text(separator="\n"))
                    text = "\n\n".join(p.strip() for p in parts if p.strip())
                    if len(text) >= 100:
                        return text
        except Exception as e:
            logger.debug("Selector '%s' failed: %s", selector, e)
            continue

    return ""


def _strip_selectors_from_html(content: str, feed_config: FeedConfig, is_html: bool) -> str:
    """Use BeautifulSoup to strip unwanted selectors from HTML content."""
    if not is_html:
        return content
    try:
        soup = BeautifulSoup(content, "html.parser")
        for strip_sel in feed_config.strip_selectors:
            for bad in soup.select(strip_sel):
                bad.decompose()
        return soup.get_text(separator="\n").strip()
    except Exception:
        return content


_JUNK_URL_PATTERNS = (".svg", "vgwort.de", "/pixel", "/tracking", "/beacon")
MIN_IMAGE_BYTES = 5000


def _is_junk_image_url(url: str) -> bool:
    """Filter out SVGs, tracking pixels, and analytics beacons."""
    lower = url.lower()
    return any(p in lower for p in _JUNK_URL_PATTERNS)


import re

# CDN resize patterns to strip for URL normalization
_CDN_SIZE_RE = re.compile(
    r'_w\d+'           # _w520, _w960
    r'|_r[\d.]+'       # _r1.5, _r1.33
    r'|_fpx[\d.]+'     # _fpx29
    r'|_fpy[\d.]+'     # _fpy46
)
_CDN_WIDTH_RE = re.compile(r'_w(\d+)')


def _normalize_image_url(url: str) -> str:
    """Strip CDN resize/crop parameters to get the base image identity."""
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(url)
    # Strip size-related path components (SPIEGEL pattern)
    clean_path = _CDN_SIZE_RE.sub('', parsed.path)
    # Strip common query params for width/height
    if parsed.query:
        params = parse_qs(parsed.query)
        for key in ('w', 'h', 'width', 'height', 'resize', 'size', 'q'):
            params.pop(key, None)
        clean_query = urlencode(params, doseq=True)
    else:
        clean_query = ''
    return urlunparse((parsed.scheme, parsed.netloc, clean_path, '', clean_query, ''))


def _extract_cdn_width(url: str) -> int:
    """Extract width from CDN URL, or 0 if not found."""
    m = _CDN_WIDTH_RE.search(url)
    return int(m.group(1)) if m else 0


def _dedup_image_urls(urls: List[str]) -> List[str]:
    """Deduplicate image URLs that are the same image at different sizes.

    Groups by normalized URL, keeps the widest version per group.
    """
    groups: Dict[str, List[str]] = {}
    for url in urls:
        key = _normalize_image_url(url)
        groups.setdefault(key, []).append(url)

    result = []
    for key, group in groups.items():
        # Pick the URL with the largest width, or the first one
        best = max(group, key=lambda u: _extract_cdn_width(u))
        result.append(best)
    return result


def _extract_image_urls(page, feed_config: FeedConfig) -> List[str]:
    """Extract image URLs from the page using feed-specific selector."""
    urls: List[str] = []
    try:
        if _USE_SCRAPLING:
            imgs = page.css(feed_config.img_selector)
            for img in imgs:
                src = img.attrib.get("src", "") or img.attrib.get("data-src", "")
                if src and src.startswith("http") and not _is_junk_image_url(src):
                    urls.append(src)
        else:
            imgs = page.select(feed_config.img_selector)
            for img in imgs:
                src = img.get("src", "") or img.get("data-src", "")
                if src and src.startswith("http") and not _is_junk_image_url(src):
                    urls.append(src)
    except Exception as e:
        logger.debug("Image extraction failed: %s", e)
    return _dedup_image_urls(urls)


def _clean_html_to_text(html: str) -> str:
    """Strip HTML tags and return clean text."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n").strip()


def sha256_text(text: str) -> str:
    """Compute SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
