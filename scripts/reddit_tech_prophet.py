#!/usr/bin/env python3
"""
Reddit Daily Tech Prophet — end-to-end pipeline script.

Takes a JSON digest file, renders it as a Harry Potter newspaper HTML,
and registers it with the artifact server. The public artifact URL is
printed on SUCCESS so the calling cron agent can deliver it to any
platform (currently: WeChat via the cron's final response).

Usage:
  python3 reddit_tech_prophet.py <json_file>

Output (stdout): SUCCESS: artifact_id=<id> url=<public-url>
"""
import json
import sys
import os
import urllib.request

# ── Paths ──────────────────────────────────────────────────
RENDERER = os.path.join(os.path.dirname(__file__), "reddit_newspaper_renderer.py")
MEDIA_FETCHER = os.path.join(os.path.dirname(__file__), "reddit_media_fetcher.py")
HTML_OUTPUT = "/tmp/reddit_newspaper_daily.html"
try:
    from reddit_newspaper_config import ARTIFACT_SERVER, PUBLIC_HOST
except ImportError:
    ARTIFACT_SERVER = "http://localhost:9877"  # artifact-server.py default
    PUBLIC_HOST = os.environ.get("HERMES_DASHBOARD_HOST", "http://localhost:9877")


def localize_media(data: dict) -> dict:
    """Download all article media to the local media server (per the
    pipeline design: fetch-time download so the artifact never hits
    Reddit CDNs).

    Rewrites each article's media url to /media/<file> (served by the
    artifact server). Falls back to the original URL if download fails.
    """
    sys.path.insert(0, os.path.dirname(MEDIA_FETCHER))
    try:
        from reddit_media_fetcher import download_media
    except ImportError:
        print("[warn] media fetcher unavailable; keeping remote URLs", file=sys.stderr)
        return data

    downloaded = failed = 0
    for section in data.get("sections", []):
        for i, article in enumerate(section.get("articles", [])):
            media = article.get("media")
            if not media:
                continue
            # Derive a stable per-post id from the link
            link = article.get("link", "") or ""
            m = link.rstrip("/").rsplit("/", 1)
            post_id = m[-1] if m else f"unk{abs(hash(link)) % 10**6}"
            local = download_media(media, post_id)
            if local:
                article["media"] = local
                downloaded += 1
            else:
                failed += 1
                # Keep remote URL as fallback (may still render in webview)
    print(f"[media] downloaded={downloaded} fallback-remote={failed}", file=sys.stderr)
    return data


def render_html(json_path: str) -> str:
    """Run the renderer script to produce HTML from JSON."""
    import subprocess
    result = subprocess.run(
        [sys.executable, RENDERER, json_path, HTML_OUTPUT],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"ERROR: Renderer failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    
    with open(HTML_OUTPUT, "r") as f:
        return f.read()


def register_artifact(html: str, title: str) -> str:
    """Register HTML with the artifact server and return the artifact ID."""
    payload = json.dumps({"title": title, "html": html}).encode()
    req = urllib.request.Request(
        f"{ARTIFACT_SERVER}/artifact",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("id", "")
    except Exception as e:
        print(f"ERROR: Artifact server registration failed: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: reddit_tech_prophet.py <json_file>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]

    # Read JSON to get date for title
    with open(json_path) as f:
        data = json.load(f)
    date_str = data.get("date", "today")

    # Download all media locally (artifact server /media/ route) before render
    data = localize_media(data)
    # Persist the localized JSON so the renderer reads the /media/ URLs
    localized_path = "/tmp/reddit_digest_localized.json"
    with open(localized_path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    json_path = localized_path

    # Render HTML
    html = render_html(json_path)

    # Register artifact
    title = f"The Daily Tech Prophet — {date_str}"
    artifact_id = register_artifact(html, title)
    if not artifact_id:
        print("ERROR: No artifact ID returned", file=sys.stderr)
        sys.exit(1)

    public_url = f"https://{PUBLIC_HOST}/artifact/{artifact_id}"
    print(f"SUCCESS: artifact_id={artifact_id} url={public_url}")


if __name__ == "__main__":
    main()