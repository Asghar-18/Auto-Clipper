"""Campaign constants and output paths. No credentials belong in this file."""
import os

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

CAMPAIGN_CAPTION = "Watch KreekCraft on YouTube and Twitch"
HASHTAGS = ("#GTA6", "#KreekCraft", "#GrandTheftAutoVI")

DEFAULT_LOGO = r"C:\Users\Microsoft\Downloads\KreekCraft Overlay.png"
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


def logo_path(override=None):
    """Resolve the official overlay asset from CLI, env, or the known local path."""
    path = override or os.environ.get("KREEKCRAFT_LOGO") or DEFAULT_LOGO
    return os.path.abspath(path)


def output_stem(name):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name)).strip("-")
    return safe or "source"
