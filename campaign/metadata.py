"""Generate truthful campaign captions and metadata from the actual clip content."""
import re

from . import config

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)


def hook_from_transcript(transcript, words=8):
    cleaned = " ".join((transcript or "").split()[:words]).strip(" ,.!?")
    return cleaned


def build(report, src):
    """src is the render report's source dict. No invented reactions or claims."""
    transcript = report.get("transcript", "")
    hook = hook_from_transcript(transcript)
    phrase = config.CAMPAIGN_CAPTION
    hashtags = " ".join(config.HASHTAGS)
    caption = f"{phrase}\n\n{hashtags}"
    title = f'KreekCraft GTA 6: "{hook}"' if hook else "KreekCraft GTA 6clip"
    title = title[:100]
    description = (f"{phrase}\n\n"
                   f"Clip from {src.get('channel') or 'Kreek'}'s authorized GTA 6 stream replay.\n\n"
                   f"{hashtags}")
    return {
        "title": title,
        "youtube_description": description,
        "instagram_caption": caption,
        "caption_text": caption,
        "campaign_phrase": phrase,
        "hashtags": list(config.HASHTAGS),
        "source_url": src.get("url") or src.get("file"),
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
