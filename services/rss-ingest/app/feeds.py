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
    key="tagesspiegel",
    name="Tagesspiegel",
    feed_url="https://www.tagesspiegel.de/contentexport/feed/home",
    article_selector="article .article-body, .ts-article-body",
    strip_selectors=["aside", ".ad", ".related-articles"],
    img_selector="article img",
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
    key="golem",
    name="Golem.de",
    feed_url="https://rss.golem.de/rss.php?feed=RSS2.0",
    article_selector="article .formatted, .article-content",
    strip_selectors=[".ad", "aside"],
    img_selector="article img",
))

_add(FeedConfig(
    key="t3n",
    name="t3n",
    feed_url="https://t3n.de/rss.xml",
    article_selector=".article-content, article .c-entry__content",
    strip_selectors=[".ad", "aside", ".related"],
    img_selector=".article-content img",
))

_add(FeedConfig(
    key="wiwo",
    name="WirtschaftsWoche",
    feed_url="https://www.wiwo.de/contentexport/feed/rss/schlagzeilen",
    article_selector=".c-leadtext + .c-richText, .article__body",
    strip_selectors=[".ad", "aside"],
    img_selector="article img",
))

_add(FeedConfig(
    key="handelsblatt",
    name="Handelsblatt",
    feed_url="https://www.handelsblatt.com/contentexport/feed/schlagzeilen",
    article_selector=".vhb-article-area--text, .article__body",
    strip_selectors=[".ad", "aside"],
    img_selector="article img",
))

_add(FeedConfig(
    key="wissenschaft_de",
    name="wissenschaft.de",
    feed_url="https://www.wissenschaft.de/feed/",
    article_selector=".entry-content, .post-content",
    strip_selectors=[".ad", "aside", ".sharedaddy"],
    img_selector=".entry-content img",
))

_add(FeedConfig(
    key="scinexx",
    name="scinexx",
    feed_url="https://www.scinexx.de/feed/",
    article_selector=".entry-content, .post-content",
    strip_selectors=[".ad", "aside"],
    img_selector=".entry-content img",
))

_add(FeedConfig(
    key="spektrum",
    name="Spektrum der Wissenschaft",
    feed_url="https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/996406",
    article_selector=".article__body, .content-article",
    strip_selectors=[".ad", "aside", ".info-box"],
    img_selector=".article__body img",
))

# Fallback config used when no site-specific selector matches
DEFAULT_SELECTOR = "article, main"


def get_enabled_feeds(enabled_keys: str = "all") -> List[FeedConfig]:
    """Return feed configs filtered by RSS_FEEDS_ENABLED env var."""
    if enabled_keys.strip().lower() == "all":
        return list(FEEDS.values())
    keys = [k.strip() for k in enabled_keys.split(",") if k.strip()]
    return [FEEDS[k] for k in keys if k in FEEDS]
