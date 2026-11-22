"""Output paths and active-campaign resolution. No credentials live here.

The campaign id selects all creator-specific rules. The default remains
``kreekcraft`` so existing commands keep working unchanged; set ``GTA_CAMPAIGN``
to ``dylan_page`` (or pass ``--campaign`` where supported) for the marathon.
"""
import os

from campaigns import get as get_profile, default_id
from campaigns.registry import DEFAULT_ID

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OUTPUT = os.path.join(ROOT, "output")
CANDIDATES = os.path.join(OUTPUT, "candidates")
FINAL = os.path.join(OUTPUT, "final")
METADATA = os.path.join(OUTPUT, "metadata")
THUMBNAILS = os.path.join(OUTPUT, "thumbnails")
LOGS = os.path.join(OUTPUT, "logs")
WORK = os.path.join(ROOT, "work", "campaign")

SUBDIRS = (CANDIDATES, FINAL, METADATA, THUMBNAILS, LOGS, WORK)

CAMPAIGN_ID = default_id()
CAMPAIGN_CAPTION = get_profile(CAMPAIGN_ID).captions.exact_phrase
HASHTAGS = get_profile(CAMPAIGN_ID).captions.required_hashtags

DEFAULT_CLIP_LEN = 30
DEFAULT_LEAD_IN = 6
DEFAULT_TOP = 5
DEFAULT_MIN_SCORE = 0.0
DEFAULT_STEP = 5.0          # seconds between coarse candidate windows
SCAN_HOP = 0.25             # seconds per RMS level
SCAN_BLOCK_SECONDS = 20.0   # audio decoded per ffmpeg read block
SAMPLE_RATE = 16000
AUDIO_FORMAT_ID = "139"     # low-bitrate audio-only track for the VOD scan


def ensure_dirs():
    for folder in SUBDIRS:
        os.makedirs(folder, exist_ok=True)


def active_profile(campaign_id=None):
    """Return the profile for an explicit id or the GTA_CAMPAIGN environment."""
    return get_profile(campaign_id or os.environ.get("GTA_CAMPAIGN") or CAMPAIGN_ID)


def logo_path(override=None, campaign_id=None):
    """Resolve a campaign's official overlay from CLI, env or a repo-local asset.

    No hardcoded Windows path: operators set KREEKCRAFT_LOGO (or pass --logo), or
    place the asset at the path declared by the KreekCraft profile.
    """
    profile = active_profile(campaign_id)
    if not profile.editing.logo_required:
        return None
    env_name = profile.editing.logo_env
    path = override or (os.environ.get(env_name) if env_name else None)
    if not path and profile.editing.logo_asset:
        candidate = os.path.join(ROOT, *profile.editing.logo_asset.split("/"))
        if os.path.isfile(candidate):
            path = candidate
    if not path:
        raise ValueError(
            f"{profile.name} requires an official logo. Set {env_name} or pass --logo.")
    return os.path.abspath(path)


def output_stem(name):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name)).strip("-")
    return safe or "source"


def timeline_path(source_key: str, campaign_id: str | None = None,
                  prefer_existing: bool = True) -> str:
    """Campaign-scoped gameplay timeline path.

    Only the legacy Kreek campaign falls back to the old unprefixed filename:
    that file predates campaign stamps and must never be reused for Dylan. New
    timelines are always written to the campaign-scoped path.
    """
    profile = active_profile(campaign_id)
    key = output_stem(source_key)
    scoped = os.path.join(METADATA, f"{profile.clip_prefix}-{key}-gameplay-timeline.json")
    legacy = os.path.join(METADATA, f"{key}-gameplay-timeline.json")
    if (prefer_existing and profile.id == DEFAULT_ID and not os.path.isfile(scoped)
            and os.path.isfile(legacy)):
        return legacy
    return scoped
