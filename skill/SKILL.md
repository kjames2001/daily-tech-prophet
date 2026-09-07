---
name: daily-tech-prophet
description: Operate, test, or deploy the Daily Tech Prophet pipeline — Harry-Potter-style Reddit newspaper rendered from a combined RSS feed, published as an HTML artifact and delivered via cron
version: 1.0.0
author: kjames2001
license: MIT
category: projects
---

# Daily Tech Prophet — Reddit Newspaper Pipeline

**Trigger:** use when asked to run, test, troubleshoot, or deploy the
daily Reddit newspaper ("Daily Tech Prophet"), or when setting this
pipeline up on a new Hermes instance.

A self-contained pipeline: Reddit hot posts → digest JSON → curated
Harry-Potter-style multi-page HTML newspaper → artifact server →
message with the edition link. Python 3 stdlib only (Pillow optional,
for texture regeneration).

```
reddit_watcher.py --json ──▶ curator (LLM) ──▶ reddit_tech_prophet.py ──▶ artifact server ──▶ URL
      combined RSS feed        digest JSON        media + renderer             │
                                                                            ▼
                                                     cron final response = the message
```

## Layout & paths

Scripts live in the pipeline repo (this skill's repository). Default
locations on an existing deployment: `~/.hermes/scripts/` (legacy
install) or the repo clone. Repo-relative:

- `scripts/reddit_watcher.py` — fetch; `--json` emits the digest schema
- `scripts/reddit_media_fetcher.py` — downloads GIF/video/image at
  fetch time → artifact server `/media/` route
- `scripts/reddit_newspaper_renderer.py` — digest JSON → newspaper HTML
- `scripts/reddit_tech_prophet.py` — orchestrator; prints
  `SUCCESS: artifact_id=<id> url=<public-url>`
- `scripts/reddit_newspaper_config.py` — deployment config (username,
  subreddits, artifact server, public host); created from
  `reddit_newspaper_config.example.py`
- `assets/` — newsprint texture, ink grain, IM Fell English fonts

## Operating the pipeline (full run)

1. **Fetch** (background; takes 1–10 min because of Reddit's
   1-request/minute RSS throttle):

   ```bash
   python3 <scripts-dir>/reddit_watcher.py --json \
     > /tmp/reddit_digest_raw.json 2> /tmp/reddit_digest_raw.err
   ```
   Poll the .err file every 45–60 s until exit. Verify: valid JSON,
   `total_posts >= 10`, sections non-empty. Do not curate stale files.

2. **Curate** to the digest schema (`references/digest.schema.json`):
   pick 10–15 articles, TOP PICKS first with `lead: true` and
   `relevance` notes, media fields copied verbatim (never invented),
   1–2 sentence summaries, 2–3 `integration_ideas`. Write to
   `/tmp/reddit_digest.json`.

3. **Render + publish**:

   ```bash
   python3 <scripts-dir>/reddit_tech_prophet.py /tmp/reddit_digest.json
   ```

4. **Deliver**: final response = short plain-text message with the URL.
   On fetch failure: report the error, produce nothing.

## Cron deployment

One consolidated job (fetch+curate+render+deliver), schedule `35 6 * * *`,
delivery target per platform. The full prompt is in
`references/cron-prompt.md` — paste as the job prompt, set the bracketed
values. Include `[SILENT]` semantics so failed runs don't deliver.

## Pitfalls & hard-won knowledge

- **Reddit RSS is throttled to ~1 req/min per IP** (June 2026, was
  ~100/10 min). The combined multi-sub feed
  (`r/sub1+sub2+.../hot/.rss?limit=100`) is the only sane fetch shape;
  per-entry subreddit attribution survives via each entry's link. If a
  sub is missing, one 65-second-spaced catch-up request recovers it —
  do not hammer.
- **Media must be fetched at pipeline time** (fetch-time download →
  `/media/` route). Never hotlink: `preview.redd.it` 403s from
  datacenter IPs; `v.redd.it` needs DASH playlist resolution (handled
  in `reddit_media_fetcher.py`). Never invent media URLs.
- **Renderer is Force-Dark-proof by architecture** (inverted world,
  `filter: invert(1)`). Do not add `will-change` inside the filtered
  ancestor, do not add synthetic bold (all weights pinned 400; visual
  weight comes from `feMorphology` in SVG filters), no 3D transforms.
- **Scroll stability**: `paginate()` anchors the viewport element and
  ignores height-only resizes (Android URL bar). Keep the anchor math
  sign: `scrollTo(0, scrollY + delta)`.
- **Localize-then-render is one-way**: re-running the orchestrator on
  already-localized JSON crashes (`/media/...` is not a fetchable URL).
  For test renders, import and call `register_artifact(html, title)`
  directly.
- The cron's final response IS the delivered message on most
  platforms — keep it plain text and short.

## References

- `references/cron-prompt.md` — consolidated cron job prompt
- `references/digest.schema.json` — digest JSON schema + example