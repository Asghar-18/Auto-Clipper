"""Resolve a local sample or an authorized VOD into a scannable audio file."""
import glob
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import clip

from . import config


@dataclass
class Source:
    key: str
    label: str
    file: Optional[str]
    url: Optional[str]
    title: str
    channel: str
    duration: float
    media_path: Optional[str]
    is_local: bool
    info: dict


def resolve(file=None, url=None) -> Source:
    """Read metadata only. Nothing is downloaded or recorded here."""
    if bool(file) == bool(url):
        raise ValueError("Pass exactly one of --file or --url.")
    if file:
        path = os.path.abspath(file)
        if not os.path.isfile(path):
            raise ValueError("Input file not found: " + path)
        stem = os.path.splitext(os.path.basename(path))[0]
        return Source(
            key="local-" + config.output_stem(stem),
            label=os.path.basename(path),
            file=path,
            url=None,
            title=stem,
            channel="local test source",
            duration=clip.media_duration(path),
            media_path=path,
            is_local=True,
            info={},
        )
    info = clip.stream_info(url)
    video_id = info.get("id") or config.output_stem(info.get("title", "vod"))
    return Source(
        key=config.output_stem(video_id),
        label=info.get("title") or video_id,
        file=None,
        url=url,
        title=info.get("title") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        duration=float(info.get("duration") or 0.0),
        media_path=None,
        is_local=False,
        info=info,
    )


def prepare_audio(source: Source, work_dir=None) -> str:
    """Local files are used as-is; for a VOD fetch only the low-bitrate audio track."""
    if source.is_local:
        return source.media_path
    folder = os.path.abspath(work_dir or config.WORK)
    os.makedirs(folder, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(folder, "vod_audio.*")))
    if existing:
        return existing[0]
    template = os.path.join(folder, "vod_audio.%(ext)s")
    fmt = f"{config.AUDIO_FORMAT_ID}/bestaudio/worst"
    command = clip.ytdlp_cmd("-f", fmt, "--no-playlist", "--no-warnings",
                             "-o", template, source.url)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Could not download VOD audio:\n" + result.stderr[-500:])
    files = sorted(glob.glob(os.path.join(folder, "vod_audio.*")))
    if not files:
        raise RuntimeError("yt-dlp finished but no audio file was written.")
    return files[0]


def download_section(url: str, start: float, length: float, out_path: str) -> str:
    """Download only the chosen VOD section. Used by the later render stage."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    section = f"*{max(0.0, start):.2f}-{max(0.0, start) + max(1.0, length):.2f}"
    command = clip.ytdlp_cmd("-f", "bv[height<=1080]+ba/b[height<=720]/b", "--no-playlist",
                             "--download-sections", section, "--force-keyframes-at-cuts",
                             "--no-warnings", "-o", out_path, url)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Could not download section:\n" + result.stderr[-500:])
    if not os.path.isfile(out_path):
        candidates = glob.glob(os.path.splitext(out_path)[0] + ".*")
        if not candidates:
            raise RuntimeError("Section download produced no file at " + out_path)
        return candidates[0]
    return out_path
