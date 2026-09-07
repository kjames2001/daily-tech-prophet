#!/usr/bin/env python3
"""
Reddit media proxy/downloader for the Daily Tech Prophet.

Downloads GIF/video/image assets from Reddit at fetch time (per the
pipeline design) so the newspaper artifact serves media from the local artifact
server instead of hitting Reddit's CDNs (which 403/block some endpoints
from browser contexts, e.g. v.redd.it DASH mp4s).

Strategy per media type:
  - image: try preview.redd.it URL, then i.redd.it (strip query), then
           external-preview.redd.it as-is
  - gif:   preview.redd.it .gif URL (may be mp4-muxed; browser <img> handles
           both when served with correct type) then i.redd.it .gif
  - video: resolve v.redd.it ID -> DASHPlaylist.mpd -> pick a mid-res CMAF mp4
           (silent, loops like a gif) -> download to /mp4/

Assets are stored under the artifact server's serving tree so they are
reachable at https://<host>/media/<file>. If the artifact server does not
serve /media/, files are base64-inlined instead (renderer decides).

Return shape: {"type": ..., "url": <public-url-or-data-uri>} or None.
"""

import json
import re
import sys
import base64
import urllib.request
from pathlib import Path

try:
    from reddit_newspaper_config import MEDIA_DIR as _CFG_MEDIA_DIR
    MEDIA_DIR = Path(_CFG_MEDIA_DIR)
except ImportError:
    MEDIA_DIR = Path(os.environ.get("HOME", "/root")) / ".hermes/artifacts/media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

try:
    from reddit_newspaper_config import REDDIT_USERNAME
except ImportError:
    REDDIT_USERNAME = "your_reddit_username"
BOT_UA = f"linux:hermes-digest:v1.1 (by /u/{REDDIT_USERNAME})"
MAX_BYTES = 8 * 1024 * 1024  # 8MB per asset


def _fetch(url: str, max_bytes: int = MAX_BYTES) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": BOT_UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
        return data
    except Exception:
        return None


def _guess_mime(data: bytes, url: str) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if url.endswith(".mp4"):
        return "video/mp4"
    if url.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def _resolve_video_mp4(v_id: str) -> str | None:
    """Resolve a v.redd.it ID to a directly-downloadable CMAF mp4 URL."""
    # Try common resolutions directly first (fast, no MPD parse)
    for res in (360, 480, 220, 270, 720):
        url = f"https://v.redd.it/{v_id}/CMAF_{res}.mp4"
        if _fetch(url, max_bytes=1) is not None:
            # HEAD-ish probe worked (206 range). Verify with real range fetch.
            req = urllib.request.Request(url, headers={"User-Agent": BOT_UA, "Range": "bytes=0-64"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status in (200, 206):
                        return url
            except Exception:
                continue
    # Fall back to parsing the MPD
    mpd_url = f"https://v.redd.it/{v_id}/DASHPlaylist.mpd"
    mpd_bytes = _fetch(mpd_url, max_bytes=256 * 1024)
    if not mpd_bytes:
        return None
    mpd = mpd_bytes.decode("utf-8", "ignore")
    reps = re.findall(r"<Representation.*?</Representation>", mpd, re.DOTALL)
    best = None
    for rep in reps:
        base = re.search(r"<BaseURL>(CMAF_\d+\.mp4)</BaseURL>", rep)
        height = re.search(r'height="(\d+)"', rep)
        if base and height:
            h = int(height.group(1))
            if best is None or abs(h - 480) < abs(best[1] - 480):
                best = (base.group(1), h)
    if best:
        return f"https://v.redd.it/{v_id}/{best[0]}"
    return None


def download_media(media: dict, post_id: str) -> dict | None:
    """Download a media item and store it locally.

    Returns {"type": ..., "url": "/media/<file>"} on success.
    The artifact server must serve /media/ from MEDIA_DIR.
    """
    if not media:
        return None

    mtype = media.get("type", "")
    url = media.get("url", "")
    if not url:
        return None

    ext_map = {"gif": ".gif", "video": ".mp4", "image": ".img"}
    ext = ext_map.get(mtype, ".bin")

    candidates = []

    if mtype == "video":
        # url is https://www.reddit.com/video/<id>/player — extract ID
        m = re.search(r"/video/([a-z0-9]+)/player", url)
        if not m:
            return None
        v_id = m.group(1)
        mp4_url = _resolve_video_mp4(v_id)
        if not mp4_url:
            return None
        candidates.append(mp4_url)
        fname = f"{post_id}_{v_id}{ext}"
    else:
        # image/gif: try the URL as given, then i.redd.it without query
        candidates.append(url)
        m = re.search(r"redd\.it/([a-z0-9]+\.(?:gif|png|jpe?g|webp))", url)
        if m:
            candidates.append(f"https://i.redd.it/{m.group(1)}")
        # strip extension guess: preview URL keeps original extension in path
        base = url.split("?")[0]
        if base != url and "redd.it/" in base:
            candidates.append(base)
        fname = f"{post_id}_{abs(hash(url)) % 10**8}{ext}"

    out_path = MEDIA_DIR / fname
    if out_path.exists() and out_path.stat().st_size > 0:
        return {"type": mtype, "url": f"/media/{fname}"}

    for cand in candidates:
        data = _fetch(cand)
        if not data:
            continue
        mime = _guess_mime(data, cand)
        if mime == "application/octet-stream":
            continue
        # If a .gif URL actually returned mp4 data (reddit mux), keep mp4 mime
        if mtype == "gif" and mime == "video/mp4":
            out_path = out_path.with_suffix(".mp4")
            fname = out_path.name
        out_path.write_bytes(data)
        return {"type": mtype, "url": f"/media/{fname}"}

    return None


def main():
    """CLI test: download one media item, print result JSON."""
    media = json.loads(sys.argv[1])
    post_id = sys.argv[2] if len(sys.argv) > 2 else "test"
    result = download_media(media, post_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()