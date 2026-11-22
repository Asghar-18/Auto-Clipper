"""Generate truthful, campaign-specific captions and metadata from clip content.

The caption rules come from the clip's campaign profile, never from a global
constant, so a Dylan Page clip can never inherit the KreekCraft sentence or
hashtags (and vice versa). Titles/hooks come only from the real transcript.
"""
import re

from . import config

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)


def hook_from_transcript(transcript, words=8):
    cleaned = " ".join((transcript or "").split()[:words]).strip(" ,.!?")
    return cleaned


def build(report, src, campaign_id=None):
    """Build metadata for exactly one campaign. No invented reactions or claims."""
    profile = config.active_profile(campaign_id or report.get("campaign_id"))
    transcript = report.get("transcript", "")
    hook = hook_from_transcript(transcript)
    rules = profile.captions
    parts = []
    if rules.exact_phrase:
        parts.append(rules.exact_phrase)
    if hook and rules.accurate_description_required and not rules.exact_phrase:
        parts.append(f'"{hook}"')
    if rules.required_hashtags:
        parts.append(" ".join(rules.required_hashtags))
    caption = "\n\n".join(part for part in parts if part)
    title = f'{profile.name}: "{hook}"' if hook else f"{profile.name} clip"
    title = title[:100]
    description_parts = [caption]
    if src.get("channel"):
        description_parts.append(
            f"Source: {src['channel']} (source attribution; rights confirmed separately).")
    description = "\n\n".join(part for part in description_parts if part)
    source_platform = (src.get("platform") or "").lower() or None
    return {
        "campaign_id": profile.id,
        "campaign": {"id": profile.id, "name": profile.name},
        "clip_id": report.get("clip_id"),
        "video_path": report.get("video_path"),
        "srt_path": report.get("srt_path"),
        "platforms": list(profile.publishing.platforms),
        "publishing": {"status": "not_published", "publication_urls": {}},
        "publication_urls": {},
        "title": title,
        "youtube_description": description,
        "instagram_caption": caption,
        "tiktok_caption": caption,
        "x_caption": caption,
        "caption_text": caption,
        "caption_language": report.get("caption_language") or rules.language,
        "campaign_phrase": rules.exact_phrase,
        "hashtags": list(rules.required_hashtags),
        "source_url": src.get("url") or src.get("file"),
        "source_platform": source_platform,
        "source_timestamps": {
            "start": report.get("source_start"),
            "end": report.get("source_end"),
        },
        "detection_score": report.get("detection_score"),
        "streamer": src.get("channel"),
        "credit": src.get("channel"),
        "channel": "gta",
        "approved": False,
        "posted": {},
        "test": bool(report.get("test")),
    }
