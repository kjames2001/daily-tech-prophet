# ── Daily Tech Prophet — deployment config ──────────────────
# Copy this file to reddit_newspaper_config.py (same directory as the
# scripts) and fill in your values. Every value has a working default
# in the scripts themselves; this file only overrides them.

# Your Reddit username — REQUIRED. Reddit blocks default/empty
# User-Agents and per-IP rate limits are friendlier to an identified UA.
# NEVER use an API-secret or password here.
REDDIT_USERNAME = "your_reddit_username"

# Subreddits to harvest (case-insensitive matching; keep the spelling
# you want to see as section names).
SUBREDDITS = [
    "selfhosted",
    "homelab",
    "HomeAssistant",
    "Proxmox",
    "LocalLLaMA",
    "ollama",
    "StableDiffusion",
    "singularity",
    "docker",
    "linuxadmin",
    "BambuLab",
    "3Dprinting",
    "datahoarder",
    "unraid",
    "OpenWrt",
]

# Artifact server: where HTML editions are registered and served.
# Default: the Hermes artifact server on localhost:9877
# (https://github.com/<you>/hermes-telegram-artifacts or any static host).
ARTIFACT_SERVER = "http://localhost:9877"

# Public host that fronts the artifact server (used to build the final
# edition URL). The script prepends "https://" itself, so give the
# BARE HOSTNAME (no scheme): e.g. "your-funnel-host.ts.net".
# Must be reachable from a plain browser (WeChat/Telegram in-app).
PUBLIC_HOST = "your-funnel-host.ts.net"

# Directory where downloaded Reddit media is stored and served from
# (must match the artifact server's /media/ route target). Common
# default: ~/.hermes/artifacts/media when using the Hermes artifact
# server; adjust to wherever your static server serves /media/ from.
MEDIA_DIR = "/home/you/.hermes/artifacts/media"