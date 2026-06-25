#!/usr/bin/env python3
"""
Fetches RSS/Atom/RDF feeds configured in feeds.yaml, deduplicates entries,
and writes the result to data/news.json.

Run from the repo root:
    python scripts/fetch_news.py

Optional env vars:
    MAX_AGE_DAYS   - skip articles older than this many days (default: 3)
    FEEDS_FILE     - path to feeds config (default: feeds.yaml)
    OUTPUT_FILE    - path to write JSON output (default: data/news.json)
    ERRORS_FILE    - path to write feed error log (default: data/feed_errors.json)
"""

import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from dateutil import parser as dateutil_parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
FEEDS_FILE = Path(os.environ.get("FEEDS_FILE", REPO_ROOT / "feeds.yaml"))
OUTPUT_FILE = Path(os.environ.get("OUTPUT_FILE", REPO_ROOT / "data" / "news.json"))
ERRORS_FILE = Path(os.environ.get("ERRORS_FILE", REPO_ROOT / "data" / "feed_errors.json"))
MAX_AGE_DAYS = int(os.environ.get("MAX_AGE_DAYS", "3"))

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "WorldNewsAggregator/1.0 (https://github.com/ragerin/worldnews; "
    "aggregator bot that respects robots.txt)"
)

FALLBACK_PATHS = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml"]

# XML namespace prefixes used across RSS/Atom/RDF feeds
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "rss10": "http://purl.org/rss/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "media": "http://search.yahoo.com/mrss/",
}

_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def truncate(text: str, limit: int = 500) -> str:
    text = strip_tags(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def load_feeds(path: Path) -> list[dict]:
    with open(path) as f:
        config = yaml.safe_load(f)
    return [feed for feed in config.get("feeds", []) if feed.get("enabled", True)]


def http_get(url: str) -> requests.Response | None:
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except Exception as exc:
        log.debug("GET failed %s: %s", url, exc)
        return None


def is_xml(content: bytes) -> bool:
    snip = content[:512].lstrip()
    return (
        snip.startswith(b"<?xml")
        or snip.startswith(b"<rss")
        or snip.startswith(b"<feed")
        or snip.startswith(b"<rdf:")
        or snip.startswith(b"<RDF")
    )


def resolve_feed_url(url: str) -> str | None:
    """Try the configured URL; fall back to common paths and homepage link-tag discovery."""
    resp = http_get(url)
    if resp and is_xml(resp.content):
        return url

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    for path in FALLBACK_PATHS:
        candidate = base + path
        resp = http_get(candidate)
        if resp and is_xml(resp.content):
            log.info("Resolved via fallback path: %s -> %s", url, candidate)
            return candidate

    home = http_get(base)
    if home:
        m = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
            home.text,
            re.IGNORECASE,
        )
        if m:
            discovered = urljoin(base, m.group(1))
            log.info("Resolved via link tag: %s -> %s", url, discovered)
            return discovered

    return None


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = dateutil_parser.parse(raw.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _text(el: ET.Element, *tags: str, ns: dict | None = None) -> str:
    """Return stripped text from the first matching sub-element."""
    ns = ns or {}
    for tag in tags:
        child = el.find(tag, ns)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def parse_rss2(root: ET.Element, feed_meta: dict, cutoff: datetime) -> list[dict]:
    articles = []
    channel = root.find("channel")
    if channel is None:
        channel = root
    for item in channel.findall("item"):
        link = _text(item, "link")
        title = _text(item, "title")
        if not link or not title:
            continue
        pub_raw = _text(item, "pubDate") or _text(item, "dc:date", NS)
        pub_dt = parse_date(pub_raw)
        if pub_dt and pub_dt < cutoff:
            continue
        summary_raw = (
            _text(item, "description")
            or _text(item, "content:encoded", NS)
            or ""
        )
        articles.append({
            "title": title,
            "link": link,
            "source": feed_meta["name"],
            "category": feed_meta["category"],
            "published": pub_dt.isoformat() if pub_dt else None,
            "summary": truncate(summary_raw),
        })
    return articles


def parse_atom(root: ET.Element, feed_meta: dict, cutoff: datetime) -> list[dict]:
    articles = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find("a:link[@rel='alternate']", ns) or entry.find("a:link", ns)
        link = (link_el.get("href") or "").strip() if link_el is not None else ""
        if not link or not title:
            continue
        pub_raw = _text(entry, "a:published", ns) or _text(entry, "a:updated", ns)
        pub_dt = parse_date(pub_raw)
        if pub_dt and pub_dt < cutoff:
            continue
        summary_el = entry.find("a:summary", ns) or entry.find("a:content", ns)
        summary_raw = (summary_el.text or "") if summary_el is not None else ""
        articles.append({
            "title": title,
            "link": link,
            "source": feed_meta["name"],
            "category": feed_meta["category"],
            "published": pub_dt.isoformat() if pub_dt else None,
            "summary": truncate(summary_raw),
        })
    return articles


def parse_rdf(root: ET.Element, feed_meta: dict, cutoff: datetime) -> list[dict]:
    """RDF/RSS 1.0 - used by AllAfrica."""
    articles = []
    rss_ns = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
    items = root.findall("rss:item", rss_ns)
    if not items:
        # Try without namespace
        items = root.findall("item")
    for item in items:
        link = _text(item, "rss:link", rss_ns) or _text(item, "link")
        title = _text(item, "rss:title", rss_ns) or _text(item, "title")
        if not link or not title:
            continue
        pub_raw = _text(item, "dc:date", rss_ns) or _text(item, "pubDate")
        pub_dt = parse_date(pub_raw)
        if pub_dt and pub_dt < cutoff:
            continue
        summary_raw = _text(item, "rss:description", rss_ns) or _text(item, "description") or ""
        articles.append({
            "title": title,
            "link": link,
            "source": feed_meta["name"],
            "category": feed_meta["category"],
            "published": pub_dt.isoformat() if pub_dt else None,
            "summary": truncate(summary_raw),
        })
    return articles


def parse_feed(url: str, feed_meta: dict, cutoff: datetime) -> list[dict]:
    resp = http_get(url)
    if not resp:
        raise ValueError(f"Failed to fetch {url}")

    # Strip XML declaration byte order marks and fix encoding
    content = resp.content
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        # Try stripping encoding declaration that conflicts with declared charset
        cleaned = re.sub(rb'<\?xml[^>]+\?>', b'', content, count=1).lstrip()
        root = ET.fromstring(cleaned)

    tag = root.tag.lower()
    if "rss" in tag or root.tag == "rss":
        return parse_rss2(root, feed_meta, cutoff)
    elif "feed" in tag:
        return parse_atom(root, feed_meta, cutoff)
    elif "rdf" in tag:
        return parse_rdf(root, feed_meta, cutoff)
    else:
        # Fallback: try RSS 2.0 parser
        return parse_rss2(root, feed_meta, cutoff)


def main() -> None:
    feeds = load_feeds(FEEDS_FILE)
    log.info("Loaded %d enabled feed(s) from %s", len(feeds), FEEDS_FILE)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    log.info("Skipping articles published before %s", cutoff.isoformat())

    all_articles: list[dict] = []
    seen_links: set[str] = set()
    errors: list[dict] = []

    for feed_meta in feeds:
        name = feed_meta["name"]
        url = feed_meta["url"]
        log.info("Processing: %s (%s)", name, url)
        try:
            resolved = resolve_feed_url(url)
            if not resolved:
                raise ValueError("Could not resolve a valid feed URL after fallbacks")

            articles = parse_feed(resolved, feed_meta, cutoff)
            new_count = 0
            for article in articles:
                if article["link"] not in seen_links:
                    seen_links.add(article["link"])
                    all_articles.append(article)
                    new_count += 1
            log.info("  -> %d new article(s)", new_count)

        except Exception as exc:
            log.warning("FAILED %s: %s", name, exc)
            errors.append({
                "name": name,
                "url": url,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    all_articles.sort(key=lambda a: a.get("published") or "0000", reverse=True)

    categories: dict[str, list[dict]] = {}
    for article in all_articles:
        categories.setdefault(article["category"], []).append(article)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count": len(all_articles),
        "categories": categories,
        "articles": all_articles,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info("Wrote %d articles to %s", len(all_articles), OUTPUT_FILE)

    if errors:
        with open(ERRORS_FILE, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        log.warning("Wrote %d feed error(s) to %s", len(errors), ERRORS_FILE)
    elif ERRORS_FILE.exists():
        ERRORS_FILE.unlink()

    if errors and not all_articles:
        log.error("All feeds failed - exiting with error")
        sys.exit(1)


if __name__ == "__main__":
    main()
