"""Per-clip thumbnails generated from real decoded frames.

No AI imagery, no fabricated reactions: a thumbnail is a frame from the actual
rendered clip. Each clip gets its own id-based filename, and the stored SHA-256
lets promotion/publishing detect a swapped or reused image.
"""
import hashlib
import os
from datetime import datetime, timezone

import numpy as np

from campaign import config


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_thumbnail(video_path: str, clip_id: str, out_dir: str | None = None,
                       sample_count: int = 5) -> dict | None:
    """Pick the sharpest of several real frames and write a unique JPEG."""
    try:
        import cv2
    except ImportError:
        return None
    capture = cv2.VideoCapture(os.path.abspath(video_path))
    if not capture.isOpened():
        return None
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    duration = frames / fps if fps > 0 else 0.0
    records = []
    try:
        for index in range(max(1, sample_count)):
            fraction = (index + 1) / (sample_count + 1)
            moment = max(0.0, duration * fraction)
            capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            records.append((sharpness, moment, frame.copy()))
    finally:
        capture.release()
    if not records:
        return None
    _sharpness, moment, frame = max(records, key=lambda item: item[0])
    folder = os.path.abspath(out_dir or config.THUMBNAILS)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{clip_id}-thumb.jpg")
    if not cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        return None
    height, width = frame.shape[:2]
    return {
        "clip_id": clip_id,
        "path": path,
        "filename": os.path.basename(path),
        "sha256": sha256_file(path),
        "width": int(width),
        "height": int(height),
        "source_time": round(float(moment), 2),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "from_source_frame": True,
        "ai_generated": False,
    }


def thumbnail_file_checks(record: dict | None) -> list[dict]:
    """Physical file checks; campaign rule checks live on the profile."""
    from campaigns.base import rule_check

    record = record or {}
    path = record.get("path")
    exists = bool(path) and os.path.isfile(path)
    expected = record.get("sha256")
    intact = exists and bool(expected) and sha256_file(path) == expected
    size_ok = exists and record.get("width", 0) >= 480 and record.get("height", 0) >= 854
    return [
        rule_check("thumbnail_file_exists", exists, path or "missing"),
        rule_check("thumbnail_hash_matches", intact, "matches" if intact else "missing or changed"),
        rule_check("thumbnail_resolution", size_ok,
                   f"{record.get('width')}x{record.get('height')}"),
    ]
