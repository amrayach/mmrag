from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FeedConfig:
    key: str
    name: str
    feed_url: str
    article_selector: str
    strip_selectors: List[str] = field(default_factory=list)
    img_selector: Optional[str] = None


# ---------------------------------------------------------------------------
# 10 German RSS feeds with best-effort CSS selectors
# ---------------------------------------------------------------------------

FEEDS: Dict[str, FeedConfig] = {}


def _add(fc: FeedConfig):
    FEEDS[fc.key] = fc


_add(FeedConfig(
    key="spiegel",
    name="SPIEGEL",
    feed_url="https://www.spiegel.de/schlagzeilen/tops/index.rss",
    article_selector="article .RichText, article [data-area='body']",
    strip_selectors=["aside", "figure figcaption", ".ad-container"],
    img_selector="article figure img",
))

_add(FeedConfig(
    key="tagesschau",
    name="Tagesschau",
    feed_url="https://www.tagesschau.de/index~rss2.xml",
    article_selector="article .textabsatz, article .m-ten",
    strip_selectors=[".modul", ".infobox", ".social-media"],
    img_selector="article picture img",
))

_add(FeedConfig(
    key="heise",
    name="heise online",
    feed_url="https://www.heise.de/rss/heise-atom.xml",
    article_selector=".article-content, .article__content",
    strip_selectors=[".ad", "aside", ".a-teaser"],
    img_selector=".article-content img",
))

_add(FeedConfig(
    key="spektrum",
    name="Spektrum der Wissenschaft",
    feed_url="https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/996406",
    article_selector=".article__body, .content-article",
    strip_selectors=[".ad", "aside", ".info-box"],
    img_selector=".article__body img",
))

_add(FeedConfig(
    key="zdf",
    name="ZDF heute",
    feed_url="https://www.zdfheute.de/rss/zdf/nachrichten",
    article_selector="article .paragraph, .article-section",
    strip_selectors=["aside", ".ad", ".teaser", ".related"],
    img_selector="article picture img, article figure img",
))

_add(FeedConfig(
    key="dw",
    name="Deutsche Welle",
    feed_url="https://rss.dw.com/xml/rss-de-all",
    article_selector="article .longText, .rich-text",
    strip_selectors=["aside", ".ad", ".related"],
    img_selector="article img",
))

_add(FeedConfig(
    key="faz",
    name="FAZ",
    feed_url="https://www.faz.net/rss/aktuell/",
    article_selector="article .atc-Text, .body-elements",
    strip_selectors=["aside", ".ad", ".related", ".paywall"],
    img_selector="article figure img, article picture img",
))

# Fallback config used when no site-specific selector matches
DEFAULT_SELECTOR = "article, main"


def get_enabled_feeds(enabled_keys: str = "all") -> List[FeedConfig]:
    """Return feed configs filtered by RSS_FEEDS_ENABLED env var."""
    if enabled_keys.strip().lower() == "all":
        return list(FEEDS.values())
    keys = [k.strip() for k in enabled_keys.split(",") if k.strip()]
    return [FEEDS[k] for k in keys if k in FEEDS]
