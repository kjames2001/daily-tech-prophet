#!/usr/bin/env python3
"""
Reddit Subreddit Watcher — fetches hot/top posts from configured subreddits.

Primary path (2026-09-07): ONE combined multi-sub feed request
(r/A+B+C/hot/.rss) — Reddit throttles unauthenticated RSS to ~1 req/min
per IP since June 2026 (was ~100/10min), so per-sub sweeps bled 429s.
Per-entry subreddit attribution survives in the merged feed.

Legacy per-sub sweep (stagger + waves + retries) is kept as an
automatic fallback in case the multi-sub syntax is ever closed.

Outputs a formatted digest of posts from the last 24 hours with content snippets.
"""

import sys
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── Configuration ──────────────────────────────────────────────
SUBREDDITS = [
    # Core homelab & self-hosting
    "selfhosted",
    "homelab",
    "HomeAssistant",
    "Proxmox",
    # AI & local LLM
    "LocalLLaMA",
    "ollama",
    "StableDiffusion",
    "singularity",
    # Hermes Agent community
    "hermesagent",
    # Docker & infrastructure
    "docker",
    "linuxadmin",
    # 3D printing
    "BambuLab",
    "openbambu",
    "3Dprinting",
    # Storage & NAS
    "datahoarder",
    # Networking & other infra
    "unraid",
    "OpenWrt",
]

try:
    from reddit_newspaper_config import REDDIT_USERNAME, SUBREDDITS as _CFG_SUBS
    if _CFG_SUBS:
        SUBREDDITS[:] = _CFG_SUBS
except ImportError:
    REDDIT_USERNAME = "your_reddit_username"  # set in reddit_newspaper_config.py
USER_AGENT = f"linux:hermes-digest:v1.1 (by /u/{REDDIT_USERNAME})"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}
CUTOFF_HOURS = 24
# Canonical subreddit spelling (SUBREDDITS entries) — the merged feed's
# entry links may carry different casing (r/homeassistant vs
# r/HomeAssistant); normalize so a sub never appears as two sections.
_CANON = {s.lower(): s for s in SUBREDDITS}
MAX_POSTS_PER_SUB = 8
SNIPPET_MAX_CHARS = 300
# Stagger fetches to avoid Reddit's unauthenticated RSS rate limit
# (~10 req/min/IP). 16 subs * 7s = 112s total, well under cron timeout.
# ── Primary: combined multi-sub feed ──────────────────────────
# ONE request for all subreddits (r/A+B+.../hot/.rss) — sidesteps the
# ~1 req/min/IP unauthenticated throttle entirely. Verified 2026-09-07:
# combined feed returned 20 entries with per-entry attribution in 1.2s
# while the single-sub request beside it got an instant 429.
COMBINED_LIMIT = 100
# Legacy per-sub sweep settings (fallback when combined feed fails)
FETCH_STAGGER_SECONDS = 25.0  # reduced from 45s to fit 600s cron timeout; 17 subs × 25s + 2×60s waves ≈ 545s
# Wave breaks: pause BEFORE the listed 0-indexed sub to let Reddit's IP-level
# rate-limit window reset. The 30s-stagger dry-run showed a hard cluster-fail
# at sub 10 (first 9 succeeded, subs 10–17 429'd). Splitting into 3 waves of
# ~6 subs with 60s pauses between waves dodges the sliding window.
WAVE_BREAKS = (5, 11)  # pause before sub 6 and before sub 12
WAVE_BREAK_PAUSE_SECONDS = 60.0  # extra wait at each wave break
# Retry pass: failed subreddits get a second (and third) chance after a
# cool-down. 429s from the first pass have usually cleared by then.
RETRY_PASSES = 2              # extra attempts after the initial sweep
RETRY_COOLDOWN_SECONDS = 75.0  # wait before each retry pass (429 window)
# ───────────────────────────────────────────────────────────────


class _HTMLStripper(HTMLParser):
    """Strip HTML tags, keep text content."""
    def __init__(self):
        super().__init__()
        self._parts = []
    def handle_data(self, data):
        self._parts.append(data)
    def get_text(self):
        return " ".join(self._parts)


def strip_html(html_str: str) -> str:
    """Convert HTML to plain text."""
    if not html_str:
        return ""
    s = _HTMLStripper()
    try:
        s.feed(html_str)
    except Exception:
        return ""
    text = s.get_text().strip()
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text


# ── Invisible-unicode stripper (cron scanner bypass) ──────────
# Reddit RSS content occasionally contains zero-width / bidirectional
# / format codepoints (U+200B, U+200C, U+200D, U+2060, U+FEFF and the
# bidi/isolate controls U+202A-202E, U+2066-2069). The hermes cron
# scanner blocks the entire assembled prompt if it sees these, so we
# strip them at the trust boundary before printing.
_INVISIBLE_CPS = frozenset([
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x2060,  # WORD JOINER
    0xFEFF,  # BYTE ORDER MARK / ZERO WIDTH NO-BREAK SPACE
    0x200E,  # LEFT-TO-RIGHT MARK
    0x200F,  # RIGHT-TO-LEFT MARK
    0x202A,  # LEFT-TO-RIGHT EMBEDDING
    0x202B,  # RIGHT-TO-LEFT EMBEDDING
    0x202C,  # POP DIRECTIONAL FORMATTING
    0x202D,  # LEFT-TO-RIGHT OVERRIDE
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2067,  # RIGHT-TO-LEFT ISOLATE
    0x2068,  # FIRST STRONG ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
])
_INVISIBLE_RE = re.compile("[" + "".join(chr(c) for c in _INVISIBLE_CPS) + "]")


def sanitize(text: str) -> str:
    """Strip zero-width and bidirectional-control codepoints.

    Reddit RSS feeds occasionally carry invisible Unicode in user-generated
    content (titles, snippets, author fields). The hermes cron scanner
    blocks any prompt containing these characters, so we strip them at
    the trust boundary before passing data to the LLM.
    """
    if not text:
        return text
    return _INVISIBLE_RE.sub("", text)


# ── Threat-pattern filter (cron scanner bypass) ───────────────
# The hermes cron scanner blocks prompts containing destructive shell
# commands, pipe-to-shell chains, URL shorteners, and common
# prompt-injection phrases. Reddit posts occasionally contain these as
# legitimate content (PSAs, demos, "don't do this" warnings), but when
# they appear in a digest prompt they trip the scanner and block the
# entire run. We drop affected posts at the trust boundary instead.
#
# These patterns mirror tools/cronjob_tools.py::_CRON_THREAT_PATTERNS
# for the patterns that have actually fired in the wild on Reddit RSS
# feeds. Keep in sync if the canonical list is extended.
_THREAT_FIELD_PATTERNS: list[re.Pattern] = [
    # Destructive shell commands
    re.compile(r"\brm\s+-[rf]{1,2}\b", re.IGNORECASE),       # rm -rf, rm -fr
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b", re.IGNORECASE),    # mkfs, mkfs.ext4
    re.compile(r"\bdd\s+if=", re.IGNORECASE),                # dd if=...
    re.compile(r">\s*/dev/(sd|hd|nvme|vd)", re.IGNORECASE), # >/dev/sda
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", re.IGNORECASE),  # fork bomb
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/", re.IGNORECASE), # chmod -R 777 /
    re.compile(r"\bcurl\s+[^\n]*\|\s*(ba)?sh\b", re.IGNORECASE), # curl|sh
    re.compile(r"\bwget\s+[^\n]*\|\s*(ba)?sh\b", re.IGNORECASE), # wget|sh
    re.compile(r"\b(base64\s+)?-d[ecode]+\s*[^\n]*\|\s*(ba)?sh\b", re.IGNORECASE),  # b64 -d | sh
    # URL shorteners (often used to mask malicious links in PSAs)
    re.compile(r"\bbit\.ly/\S+", re.IGNORECASE),
    re.compile(r"\btinyurl\.com/\S+", re.IGNORECASE),
    re.compile(r"\bt\.co/\S+", re.IGNORECASE),
    re.compile(r"\bgoo\.gl/\S+", re.IGNORECASE),
    re.compile(r"\b(is\.gd|ow\.ly|buff\.ly|shorturl\.at|rb\.gy)\/\S+", re.IGNORECASE),
    # Common prompt-injection phrases
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"</?(system|assistant|user|tool|human)\b", re.IGNORECASE),  # role tag injection
    re.compile(r"<\|im_start\|>", re.IGNORECASE),  # chat template token
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
]


def matches_threat(title: str, snippet: str) -> bool:
    """Return True if the post's title or snippet matches any threat pattern."""
    blob = f"{title or ''}\n{snippet or ''}"
    return any(rx.search(blob) for rx in _THREAT_FIELD_PATTERNS)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def extract_reddit_id(entry) -> str:
    """Extract Reddit post ID from the atom:id field (e.g. 't3_1sey9ch')."""
    id_el = entry.find("atom:id", ATOM_NS)
    if id_el is not None and id_el.text:
        return id_el.text.replace("t3_", "")
    return ""


def extract_media(content_html: str) -> dict | None:
    """Extract the best media item from RSS content HTML.

    Priority: animated GIF > video > static image.
    - GIF:  img src containing .gif (preview.redd.it / i.redd.it)
    - Video: v.redd.it link -> converted to Reddit's official player embed URL
    - Image: first reddit-hosted <img src> (preview.redd.it / external-preview)

    URLs are unescaped (&amp; -> &) for direct browser use.
    Returns {"type": "gif"|"video"|"image", "url": str} or None.
    """
    if not content_html:
        return None

    # GIF first: animated images from i.redd.it / preview.redd.it
    img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', content_html)
    reddit_imgs = [u.replace("&amp;", "&") for u in img_srcs if "redd.it" in u]
    for img in reddit_imgs:
        if ".gif" in img.lower():
            return {"type": "gif", "url": img}

    # Video: v.redd.it link in content -> official player embed
    video_ids = re.findall(r"https://v\.redd\.it/([a-z0-9]+)", content_html)
    if video_ids:
        return {
            "type": "video",
            "url": f"https://www.reddit.com/video/{video_ids[0]}/player",
        }

    # Static image fallback
    if reddit_imgs:
        return {"type": "image", "url": reddit_imgs[0]}

    return None


def _fetch_rss_xml(url: str) -> str | None:
    """Fetch an RSS URL, return XML text or None."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except (URLError, HTTPError, Exception) as e:
        print(f"[reddit_watcher] fetch failed {url}: {e}", file=sys.stderr)
        return None


def _parse_atom_entries(xml_data: str, fallback_sub: str) -> tuple[list[dict], list[str]]:
    """Parse atom entries into post dicts; return (posts, errors).

    Per-entry subreddit attribution comes from the entry link
    (reddit.com/r/<sub>/comments/...); falls back to fallback_sub.
    """
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        return [], [f"{fallback_sub}: XML parse error: {e}"]

    entries = root.findall("atom:entry", ATOM_NS)
    posts = []
    errors = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

    _sub_from_link = re.compile(r"https://www\.reddit\.com/r/([A-Za-z0-9_]+)/comments/")

    for entry in entries:
        title_el = entry.find("atom:title", ATOM_NS)
        link_el = entry.find("atom:link", ATOM_NS)
        updated_el = entry.find("atom:updated", ATOM_NS)
        content_el = entry.find("atom:content", ATOM_NS)
        author_el = entry.find("atom:author/atom:name", ATOM_NS)

        title = title_el.text if title_el is not None else "(no title)"
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated_str = updated_el.text if updated_el is not None else ""
        content_html = content_el.text if content_el is not None else ""
        author = author_el.text if author_el is not None else "unknown"

        try:
            updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            updated = datetime.now(timezone.utc)

        if updated < cutoff:
            continue

        m = _sub_from_link.match(link)
        subreddit = m.group(1) if m else fallback_sub
        subreddit = _CANON.get(subreddit.lower(), subreddit)

        snippet = truncate(strip_html(content_html), SNIPPET_MAX_CHARS)
        post = {
            "title": title,
            "link": link,
            "updated": updated.isoformat(),
            "subreddit": subreddit,
            "snippet": snippet,
            "author": author,
            "post_id": extract_reddit_id(entry),
        }
        media = extract_media(content_html)
        if media:
            post["media"] = media
        posts.append(post)

    return posts, errors


def fetch_rss(subreddit: str, limit: int = 25) -> list[dict]:
    """Fetch hot posts from ONE subreddit via RSS (legacy path)."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit={limit}"
    xml_data = _fetch_rss_xml(url)
    if xml_data is None:
        return [{"error": "fetch failed", "subreddit": subreddit}]
    posts, errors = _parse_atom_entries(xml_data, subreddit)
    for e in errors:
        print(f"[reddit_watcher] {e}", file=sys.stderr)
    return posts[:MAX_POSTS_PER_SUB] or ([{"error": "no posts in 24h", "subreddit": subreddit}] if not posts else [])


def main():
    import json as _json
    use_json = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]
    now = datetime.now(timezone.utc)

    all_posts = {}
    errors = []

    # ── Primary path: ONE combined multi-sub feed request ──────────
    # Reddit's unauthenticated RSS is throttled to ~1 req/min/IP since
    # June 2026 — a single r/A+B+.../hot/.rss request sidesteps that.
    subs_joined = "+".join(SUBREDDITS)
    combined_url = f"https://www.reddit.com/r/{subs_joined}/hot/.rss?limit={COMBINED_LIMIT}"
    print(f"[reddit_watcher] primary: combined feed, {len(SUBREDDITS)} subs, "
          f"limit={COMBINED_LIMIT}", file=sys.stderr)
    xml_data = _fetch_rss_xml(combined_url)

    if xml_data is not None:
        posts, _ = _parse_atom_entries(xml_data, fallback_sub="")
        # Per-sub caps, preserving feed order (hot interleaves subs)
        per_sub: dict[str, list[dict]] = {}
        for p in posts:
            sub = p.get("subreddit") or "(unknown)"
            per_sub.setdefault(sub, []).append(p)
        for sub, plist in per_sub.items():
            kept = plist[:MAX_POSTS_PER_SUB]
            if kept:
                all_posts[sub] = kept
        covered = len(all_posts)
        print(f"[reddit_watcher] combined feed: {sum(len(v) for v in all_posts.values())} posts "
              f"across {covered}/{len(SUBREDDITS)} subreddits", file=sys.stderr)
    else:
        print("[reddit_watcher] combined feed failed; falling back to per-sub sweep",
              file=sys.stderr)

    # ── Fallback: legacy per-sub sweep for subs missing above ──────
    missing = [s for s in SUBREDDITS if s not in all_posts]
    failed_subs: list[str] = []
    if missing:
        if xml_data is not None:
            # Combined feed succeeded; the IP window is consumed (1 QPM),
            # so pace catch-up requests one per ~65s — sleep BEFORE each
            # attempt (the combined request just consumed the window) —
            # no wave breaks, no retry ladder. Bounded: typically 1-2 subs.
            errors.append(f"  combined feed missed {len(missing)} sub(s): {', '.join(missing)}")
            for i, sub in enumerate(missing):
                time.sleep(65.0)
                posts = fetch_rss(sub)
                valid_posts = [p for p in posts if "error" not in p]
                if valid_posts:
                    all_posts[sub] = valid_posts
                    print(f"[reddit_watcher] catch-up: r/{sub} recovered "
                          f"({len(valid_posts)} posts)", file=sys.stderr)
                else:
                    failed_subs.append(sub)
        else:
            # Combined feed itself failed — full legacy sweep with waves.
            for i, sub in enumerate(missing):
                if i > 0:
                    time.sleep(FETCH_STAGGER_SECONDS)
                if i in WAVE_BREAKS:
                    wave_num = WAVE_BREAKS.index(i) + 1
                    print(f"[reddit_watcher] wave-{wave_num} complete; "
                          f"pausing {WAVE_BREAK_PAUSE_SECONDS}s for rate-limit window reset",
                          file=sys.stderr)
                    time.sleep(WAVE_BREAK_PAUSE_SECONDS)
                posts = fetch_rss(sub)
                errors_in_sub = [p for p in posts if "error" in p]
                valid_posts = [p for p in posts if "error" not in p]

                if errors_in_sub:
                    for e in errors_in_sub:
                        errors.append(f"  r/{sub}: {e['error']}")
                    failed_subs.append(sub)
                if valid_posts:
                    all_posts[sub] = valid_posts

    # ── Retry passes: re-fetch failed subreddits after cool-downs ──
    for attempt in range(1, RETRY_PASSES + 1):
        if not failed_subs:
            break
        print(f"[reddit_watcher] retry pass {attempt}/{RETRY_PASSES} for "
              f"{len(failed_subs)} failed sub(s): {', '.join(failed_subs)}",
              file=sys.stderr)
        time.sleep(RETRY_COOLDOWN_SECONDS)

        still_failed: list[str] = []
        for j, sub in enumerate(failed_subs):
            if j > 0:
                time.sleep(FETCH_STAGGER_SECONDS)
            posts = fetch_rss(sub)
            errors_in_sub = [p for p in posts if "error" in p]
            valid_posts = [p for p in posts if "error" not in p]

            if errors_in_sub:
                for e in errors_in_sub:
                    errors.append(f"  r/{sub} (retry {attempt}): {e['error']}")
                still_failed.append(sub)

            if valid_posts:
                all_posts[sub] = valid_posts
                print(f"[reddit_watcher] retry {attempt}: r/{sub} recovered "
                      f"({len(valid_posts)} posts)", file=sys.stderr)

        failed_subs = still_failed

    if failed_subs:
        print(f"[reddit_watcher] subreddits still failing after retries: "
              f"{', '.join(failed_subs)}", file=sys.stderr)

    # ── Threat-pattern filter (drop posts that would trip scanner) ──
    # Some Reddit posts contain text the hermes cron scanner flags as
    # injection — usually PSAs or "don't run this" demos that quote
    # destructive shell commands. Drop them at the trust boundary so
    # the cron scanner doesn't block the entire digest. The dropped
    # count is reported to stderr for visibility.
    dropped = 0
    for sub in list(all_posts.keys()):
        kept = []
        for p in all_posts[sub]:
            if matches_threat(p.get("title", ""), p.get("snippet", "")):
                dropped += 1
                continue
            kept.append(p)
        all_posts[sub] = kept
        if not kept:
            del all_posts[sub]
    if dropped:
        print(f"[reddit_watcher] dropped {dropped} post(s) matching cron threat patterns",
              file=sys.stderr)

    # ── Sanitize trust boundary ─────────────────────────────────
    # Strip invisible Unicode from all user-generated content fields
    # before printing. The cron scanner blocks prompts containing
    # zero-width / bidi-control codepoints.
    _SANE_FIELDS = ("title", "author", "snippet", "link")
    for sub, posts in all_posts.items():
        for p in posts:
            for f in _SANE_FIELDS:
                if f in p and isinstance(p[f], str):
                    p[f] = sanitize(p[f])
            # Media URLs: sanitize too (they go into HTML attrs)
            if "media" in p and isinstance(p["media"], dict):
                p["media"]["url"] = sanitize(p["media"]["url"])

    # Recompute total after threat filter
    total = sum(len(posts) for posts in all_posts.values())

    if use_json:
        # Machine-readable mode for the consolidated newspaper cron:
        # emits the exact schema reddit_tech_prophet.py consumes.
        sections = []
        for sub, posts in all_posts.items():
            arts = []
            for p in posts:
                a = {
                    "title": p["title"],
                    "summary": p.get("snippet", ""),
                    "link": p["link"],
                    "author": p.get("author", "unknown"),
                    "subreddit": f"r/{sub}",
                }
                if p.get("media"):
                    a["media"] = p["media"]
                arts.append(a)
            sections.append({"name": f"r/{sub}", "lead": False, "articles": arts})
        payload = {
            "date": now.strftime("%Y-%m-%d"),
            "total_posts": total,
            "total_subs": len(all_posts),
            "fetcher_notes": "\n".join(e.strip() for e in errors),
            "sections": sections,
            "integration_ideas": [],
        }
        print(_json.dumps(payload, ensure_ascii=False))
        return

    # ── Format output (text mode — legacy format, byte-compatible) ──
    lines = []
    lines.append(f"Reddit Daily Digest")
    lines.append(f"{now.strftime('%Y-%m-%d %H:%M UTC')} | Last {CUTOFF_HOURS}h")
    lines.append(f"{total} posts across {len(all_posts)} subreddits")
    lines.append("")

    if not all_posts:
        lines.append("No new posts found in the last 24 hours.")
    else:
        for sub, posts in all_posts.items():
            lines.append(f"=== r/{sub} ({len(posts)} posts) ===")
            for p in posts:
                title = p["title"][:150] + ("..." if len(p["title"]) > 150 else "")
                lines.append(f"* {title}")
                lines.append(f"  Author: {p['author']}")
                if p["snippet"]:
                    lines.append(f"  Preview: {p['snippet']}")
                lines.append(f"  Link: {p['link']}")
                if "media" in p:
                    m = p["media"]
                    lines.append(f"  Media: {m['type']} | {m['url']}")
                lines.append("")

    if errors:
        lines.append("Errors:")
        for e in errors:
            lines.append(e)

    print("\n".join(lines))


if __name__ == "__main__":
    main()
