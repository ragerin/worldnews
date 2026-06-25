# World News Aggregator

**Live site: https://ragerin.github.io/worldnews/**

A static news site that pulls headlines from curated global RSS feeds, with an
emphasis on non-Western-centric sources. Rebuilt daily via GitHub Actions and
served free on GitHub Pages. No backend, no database, no paid services.

## How it works

1. A GitHub Actions workflow runs daily at 06:00 UTC.
2. `scripts/fetch_news.py` fetches all enabled feeds, deduplicates entries, and
   writes `data/news.json`.
3. Eleventy builds static HTML from `data/news.json`.
4. The built `_site/` is deployed to GitHub Pages.

## Quick start (local)

**Fetch articles:**

```sh
pip install -r requirements.txt
python scripts/fetch_news.py
# Output: data/news.json
```

**Build and serve the site:**

```sh
npm install
npm start       # dev server with live reload at http://localhost:8080
npm run build   # one-shot build to _site/
```

## Configuration

Edit `feeds.yaml` to add, remove, or toggle feeds:

- Set `enabled: false` to disable a feed without deleting its config.
- `confidence` values are `high` / `medium` / `low` — URLs marked `medium` or
  `low` should be manually verified before enabling.

## GitHub Pages setup

In your repo **Settings → Pages**, set the source to **"GitHub Actions"**
(not "Deploy from branch"). The workflow handles deployment automatically.

## Known verification gaps

The following feed URLs were included but need manual verification before
being marked `enabled: true`:

| Feed | Issue |
|------|-------|
| Anadolu Agency | URL from a 2004 help page — likely stale |
| Channel News Asia | URL inferred from third-party listing, not confirmed |
| China Daily | Not directly checked — source was aggregator listings |
| Kyodo News | Exact filename path (`all.xml`) inferred, not confirmed |

## Attribution

Africa headlines are provided by [allAfrica.com](https://allafrica.com) and
require attribution per their RSS terms. This is built into the site footer.

TASS is intentionally excluded — their terms of use prohibit redistribution
via RSS on third-party sites without written consent.

RT (Russia Today) is present in `feeds.yaml` but disabled by default — enable
it deliberately after considering the editorial and jurisdictional context.
