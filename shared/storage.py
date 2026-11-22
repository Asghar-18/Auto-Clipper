"""Clip metadata storage helpers and campaign isolation.

The existing flat ``output/final`` layout is preserved. Campaign isolation is
enforced by the ``campaign_id`` field recorded on every new clip, plus the
clip-name prefix. Legacy clips created before the field existed are inferred
read-only; they are never silently rewritten.
"""
import glob
import json
import os
import re

from campaign import config

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)

LEGACY_PREFIXES = {
    "kreek": "kreekcraft",
    "dylan": "dylan_page",
}
LEGACY_MARKERS = {
    "kreekcraft": ("Watch KreekCraft on YouTube and Twitch", "#KreekCraft"),
    "dylan_page": ("#DylanPage",),
}


def clip_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def final_clips(final_dir: str | None = None) -> list[dict]:
    """Load all final clip metadata records that can be read."""
    folder = final_dir or config.FINAL
    records = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                records.append(json.load(handle))
        except (OSError, ValueError):
            continue
    return records


def infer_campaign(metadata: dict, name: str = "") -> str | None:
    """Best-effort, read-only campaign inference for legacy clips.

    Never guesses when the metadata and filename disagree: ambiguity is treated
    as no campaign, and callers must ask the operator to supply one.
    """
    explicit = {str(value) for value in (
        metadata.get("campaign_id"), (metadata.get("campaign") or {}).get("id")) if value}
    if len(explicit) > 1:
        return None  # conflicting stamps are ambiguous, never pick one silently
    if explicit:
        return explicit.pop()
    candidates = set()
    base = name or str(metadata.get("video") or "").rsplit(".", 1)[0]
    for prefix, campaign_id in LEGACY_PREFIXES.items():
        if base.lower().startswith(prefix + "-"):
            candidates.add(campaign_id)
    text = " ".join(str(metadata.get(key, "") or "") for key in (
        "caption_text", "youtube_description", "instagram_caption", "title"))
    for campaign_id, markers in LEGACY_MARKERS.items():
        if any(marker.lower() in text.lower() for marker in markers):
            candidates.add(campaign_id)
    if len(candidates) == 1:
        return candidates.pop()
    return None


def require_campaign(metadata: dict, name: str = "", expected: str | None = None) -> str:
    """Return the single campaign id for a clip, or raise a clear error.

    An explicit ``expected`` id may disambiguate a legacy clip that has no
    stamp/prefix, but it can never override a different recorded campaign.
    """
    from campaigns import ids as valid_ids
    valid = valid_ids()
    campaign_id = infer_campaign(metadata, name)
    if not campaign_id:
        if not expected:
            raise ValueError(
                "clip has no unambiguous campaign_id; set it in the clip JSON or pass --campaign")
        if expected not in valid:
            raise ValueError(f"unknown campaign_id {expected!r}; expected one of {valid}")
        return expected
    if campaign_id not in valid:
        raise ValueError(f"unknown campaign_id {campaign_id!r}; expected one of {valid}")
    if expected and campaign_id != expected:
        raise ValueError(
            f"campaign mismatch: clip belongs to {campaign_id!r}, requested {expected!r}")
    return campaign_id


def known_thumbnails(final_dir: str | None = None) -> list[dict]:
    """Thumbnail records from existing final clips, for uniqueness checks."""
    found = []
    for record in final_clips(final_dir):
        thumb = record.get("thumbnail")
        if isinstance(thumb, dict) and thumb:
            found.append(thumb)
    return found


def output_path(*parts: str) -> str:
    """Build an output path from the configured root without hardcoded drives."""
    return os.path.join(config.OUTPUT, *parts)
