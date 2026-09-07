# The Daily Tech Prophet

A self-contained pipeline that turns Reddit's hottest posts from your
favourite subreddits into a **Harry-Potter-style daily newspaper**,
rendered as a multi-page HTML artifact and delivered as a link to any
messaging platform (Telegram, WeChat, Discord...).

Runs entirely on Python 3 stdlib — **no pip dependencies** for the
pipeline itself (PIL/Pillow is only needed if you regenerate the
background textures).

Built with [Hermes Agent](https://github.com/NousResearch/hermes-agent)
as the daily 06:35 edition in a real deployment; packaged here so any
other Hermes instance (or plain cron + curl setup) can run it.

```
        ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
        │  reddit_watcher  │ ──▶ │   curator (LLM   │ ──▶ │ reddit_tech_     │
        │  .py --json      │     │   or human)      │     │ prophet.py       │
        │  combined RSS    │     │  digest JSON     │     │ media + renderer │
        └──────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                                   │ register
                                                                   ▼
                                                    artifact server ── public URL
```

## How it works

1. **Fetch** — `reddit_watcher.py --json` pulls hot posts via **one
   combined multi-sub RSS request**
   (`https://www.reddit.com/r/sub1+sub2+.../hot/.rss?limit=100`).
   Reddit throttles unauthenticated RSS to ~1 request/minute per IP
   (since June 2026), so the combined feed is the only sane shape. Any
   sub the merged feed misses gets a 65-second-spaced catch-up request;
   a legacy staggered sweep is the last-resort fallback. Per-entry
   subreddit attribution survives in the merged feed.

2. **Curate** — the digest JSON (schema in
   [`docs/digest.schema.json`](docs/digest.schema.json)) is curated to
   10–15 picks. With Hermes, the cron agent does this with its LLM;
   manually, just edit the JSON.

3. **Render + publish** — `reddit_tech_prophet.py` downloads all
   article media at fetch time (so editions never hotlink Reddit CDNs),
   runs `reddit_newspaper_renderer.py` to produce the newspaper HTML,
   and registers it with the artifact server. Prints
   `SUCCESS: artifact_id=<id> url=<public-url>`.

4. **Deliver** — the cron's final response *is* the message: plain
   text with the edition URL.

## Setup

```bash
git clone <this repo>
cd daily-tech-prophet

# 1. Configure
cp scripts/reddit_newspaper_config.example.py scripts/reddit_newspaper_config.py
$EDITOR scripts/reddit_newspaper_config.py   # username, subs, artifact server

# 2. Serve media (any static file server with the /media/ route)
#    The Hermes artifact server (artifact-server.py) already does this.
#    Otherwise: nginx/caddy serving ./assets + your generated media dir.

# 3. Smoke test the fetch:
python3 scripts/reddit_watcher.py --json > /tmp/digest.json
python3 -m json.tool /tmp/digest.json | head

# 4. Smoke test render+publish (edit the JSON's articles first, or use it raw):
python3 scripts/reddit_tech_prophet.py /tmp/digest.json
#  → SUCCESS: artifact_id=... url=https://<your-funnel-host>/artifact/...
```

### The cron job (Hermes)

One consolidated job does fetch → curate → render → deliver. Create it
with `hermes` (or paste into `~/.hermes/cron/jobs.json` via the
cronjob tool):

- **Schedule**: `35 6 * * *`
- **Prompt**: the full text is in
  [`docs/cron-prompt.md`](docs/cron-prompt.md) — it walks the agent
  through Step 0 (fetch, background + poll), Step 1 (curate to the
  schema), Step 2 (render + publish), Step 3 (final response = the
  message, `[SILENT]` on failure).
- **Delivery target**: whatever platform suits you (Telegram, WeChat,
  Discord — Hermes `deliver:` field).

Non-Hermes alternative: cron + curl + any LLM CLI with a file-writing
tool; the pipeline scripts are plain argv/stdout programs.

## Design notes (the hard-won bits)

- **Force Dark defense**: Telegram/WeChat Android webviews re-colour
  pages at paint time. The renderer's "inverted world" architecture
  (negative colours + `filter: invert(1)` on the world container) is
  the only pixel-verified defense. Keep it intact.
- **No synthetic bold**: IM Fell English has no bold face; browser
  fake-bold turns to mud under the ink filters. All weights pinned to
  400; visual weight comes from `feMorphology` dilate in SVG filters.
- **Media is downloaded at fetch time** to the artifact server's
  `/media/` route; never hotlink Reddit (preview.redd.it 403s from
  datacenter IPs; v.redd.it needs DASH resolution — handled in
  `reddit_media_fetcher.py`).
- **Scroll stability**: pagination preserves the viewport anchor and
  ignores height-only resizes (Android URL bar) — see
  `paginate()` in the renderer.

## Asset licenses & provenance

| Asset | Source | License |
|---|---|---|
| IM Fell English (2 woff2) | Google Fonts / Igino Marini's Fell Type revival | SIL OFL 1.1 |
| `newsprint_bg_grainy_v3.jpg` | generated by `scripts/make_newsprint_bg.py` from [Texturelabs PAPER_290](https://texturelabs.org) | generated; source texture free from Texturelabs |
| `ink_grain_v4.png` | generated (deterministic seed) | same as repo |

The generator scripts are included, so all textures are reproducible.

## Files

```
scripts/
  reddit_watcher.py             fetch: combined RSS → digest JSON (--json flag)
  reddit_media_fetcher.py       download GIF/video/image → /media/ route
  reddit_newspaper_renderer.py  JSON → newspaper HTML (the typographic beast)
  reddit_tech_prophet.py        orchestrator: media + render + register
  make_newsprint_bg.py          regenerate newsprint tile from Texturelabs source
  newsprint_texture.py          alternate procedural newsprint (data URI)
  reddit_newspaper_config.example.py
assets/                         shipped textures + fonts (renderer's exact deps)
docs/cron-prompt.md             the consolidated cron job prompt, ready to paste
docs/digest.schema.json         digest JSON schema with example
skill/                          drop-in Hermes skill package (see skill/README)
```

## Requirements

- Python 3.10+ (stdlib only for the pipeline; Pillow for texture
  regeneration)
- An artifact server with a `/media/` static route (any static file
  server works; the Hermes telegram-artifacts server is one)
- A publicly reachable host for edition URLs (Tailscale Funnel, VPS,
  etc.)
- For Hermes cron delivery: any connected platform adapter

## License

MIT for the code. Font and texture licenses as tabled above.