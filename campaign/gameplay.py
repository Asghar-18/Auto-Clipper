"""Stage 0: build a visual gameplay timeline from YouTube storyboard frames.

No full video download and no paid API. YouTube's sb0 storyboard gives one
160x90 frame roughly every 2.5 seconds for the entire VOD (~25 MB here).

The automatic pass is only a PROPOSAL. Statistical features cannot reliably
tell GTA gameplay from an animated waiting card. A human confirms the real
gameplay ranges from a labelled contact sheet; those confirmed ranges become
the authoritative gate for candidate generation and validation.
"""
import argparse
import email
import json
import os
import struct
import subprocess
import sys
from datetime import datetime, timezone

import cv2
import numpy as np

import clip

from . import config, source as source_module

TILE_W, TILE_H = 160, 90
BUCKET_SECONDS = 30.0
MIN_GAMEPLAY_SECONDS = 60.0

# Tunable proposal thresholds. Confirmation overrides these in practice.
MOTION_MIN = 2.0
MOTION_MAX = 80.0
TEXT_EDGE_THRESHOLD = 0.30
STATIC_THRESHOLD = 0.55
DARK_THRESHOLD = 0.70
WAITING_TEMPLATE_END = 75.0     # source seconds confirmed to be the pre-game screen
WAITING_MATCH_RATIO = 0.35      # bucket fraction matching a waiting template -> non-gameplay
WAITING_CLEAR_RATIO = 0.10      # bucket fraction required before proposing gameplay
FLAT_EDGE_MAX = 0.04            # low detail: menus, loading screens, pause cards
FLAT_CONTRAST_MAX = 15.0
FLAT_SATURATION_MAX = 45.0
FLAT_RATIO_MAX = 0.35


def ensure_storyboard(url, key):
    path = os.path.join(config.WORK, key + "-storyboard.mhtml")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    result = subprocess.run(clip.ytdlp_cmd("-f", "sb0", "--no-warnings", "-o", path, url),
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("storyboard download failed: " + result.stderr[-500:])
    if not os.path.isfile(path):
        raise RuntimeError("storyboard file was not written: " + path)
    return path


def decode_sheet(payload):
    """yt-dlp's MHTML payloads are occasionally 1-2 bytes short of their RIFF size."""
    if len(payload) < 12 or payload[:4] != b"RIFF":
        return None
    declared = struct.unpack("<I", payload[4:8])[0] + 8
    if declared > len(payload):
        payload += b"\x00" * (declared - len(payload))
    return cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)


def frame_signature(tile):
    """Compact perceptual signature: dHash + normalized HSV histogram."""
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    tiny = cv2.resize(gray, (17, 9), interpolation=cv2.INTER_AREA)
    dhash = (tiny[:, 1:] > tiny[:, :-1]).flatten()
    hsv = cv2.cvtColor(tile, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return dhash, hist.flatten().astype(np.float32)


def signature_distance(left, right):
    dhash_l, hist_l = left
    dhash_r, hist_r = right
    hamming = float(np.count_nonzero(dhash_l != dhash_r)) / dhash_l.size
    correlation = float(cv2.compareHist(hist_l.reshape(-1, 1), hist_r.reshape(-1, 1),
                                        cv2.HISTCMP_CORREL))
    return hamming, correlation


def waiting_match(distance):
    hamming, correlation = distance
    return hamming <= 0.22 and correlation >= 0.80


def frame_features(tile, previous):
    """Visual signals at one sample. `previous` holds the prior grayscale tile."""
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (80, 45), interpolation=cv2.INTER_AREA).astype(np.float32)
    motion = 0.0 if previous is None else float(np.abs(small - previous).mean())
    hsv = cv2.cvtColor(tile, cv2.COLOR_BGR2HSV)
    edge = float(cv2.Canny(gray, 50, 150).mean() / 255.0)
    features = {
        "motion": round(motion, 2),
        "edge": round(edge, 3),
        "saturation": round(float(hsv[:, :, 1].mean()), 2),
        "brightness": round(float(hsv[:, :, 2].mean()), 2),
        "contrast": round(float(gray.std()), 2),
        "dark_fraction": round(float((gray < 30).mean()), 3),
    }
    return features, small


def storyboard_frames(path):
    """Return (frames, thumbnails, signatures); thumbnails are JPEG review bytes."""
    with open(path, "rb") as handle:
        message = email.message_from_binary_file(handle)
    parts = [part for part in message.walk() if part.get_content_type() == "image/webp"]
    frames = []
    thumbnails = []
    signatures = []
    cursor = 0.0
    previous = None
    for part in parts:
        sheet = decode_sheet(part.get_payload(decode=True))
        if sheet is None:
            continue
        duration = float(part.get("X.yt-dlp.Duration") or 0.0)
        if duration <= 0:
            continue
        height, width = sheet.shape[:2]
        columns, rows = width // TILE_W, height // TILE_H
        count = max(1, columns * rows)
        for index in range(count):
            row, column = divmod(index, columns)
            tile = sheet[row * TILE_H:(row + 1) * TILE_H, column * TILE_W:(column + 1) * TILE_W]
            features, previous = frame_features(tile, previous)
            ok, encoded = cv2.imencode(".jpg", tile, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            thumbnails.append(encoded.tobytes() if ok else b"")
            signatures.append(frame_signature(tile))
            frames.append((cursor + duration * index / count, features))
        cursor += duration
    return frames, thumbnails, signatures


def bucketize(frames, waiting_flags, bucket_seconds=BUCKET_SECONDS):
    buckets = []
    current, end = [], bucket_seconds
    for index, (timestamp, features) in enumerate(frames):
        if timestamp >= end and current:
            buckets.append(current)
            current = []
            end += bucket_seconds
        current.append((timestamp, features, waiting_flags[index]))
    if current:
        buckets.append(current)
    result = []
    for index, rows in enumerate(buckets):
        values = [item[1] for item in rows]
        flags = [item[2] for item in rows]
        static = float(np.mean([value["motion"] < 1.5 for value in values]))
        textlike = float(np.mean([value["edge"] > TEXT_EDGE_THRESHOLD for value in values]))
        dark = float(np.mean([value["brightness"] < 30 for value in values]))
        waiting = float(np.mean(flags))
        flat = float(np.mean([value["edge"] < FLAT_EDGE_MAX
                              and value["contrast"] < FLAT_CONTRAST_MAX
                              and value["saturation"] < FLAT_SATURATION_MAX
                              for value in values]))
        motion = float(np.median([value["motion"] for value in values]))
        if (waiting > WAITING_MATCH_RATIO or flat > FLAT_RATIO_MAX
                or static > STATIC_THRESHOLD or dark > DARK_THRESHOLD or textlike > 0.55):
            label = "non_gameplay"
        elif (motion >= MOTION_MIN and waiting < WAITING_CLEAR_RATIO and flat < 0.10
              and static < 0.20 and textlike < 0.35 and dark < 0.30):
            label = "gameplay"
        else:
            label = "uncertain"
        result.append({
            "start": round(index * bucket_seconds, 2),
            "end": round((index + 1) * bucket_seconds, 2),
            "label": label,
            "motion_median": round(motion, 2),
            "waiting_match_ratio": round(waiting, 3),
            "flat_screen_ratio": round(flat, 3),
            "static_ratio": round(static, 3),
            "text_edge_ratio": round(textlike, 3),
            "dark_ratio": round(dark, 3),
            "edge_mean": round(float(np.mean([value["edge"] for value in values])), 3),
            "brightness_mean": round(float(np.mean([value["brightness"] for value in values])), 2),
            "contrast_mean": round(float(np.mean([value["contrast"] for value in values])), 2),
            "saturation_mean": round(float(np.mean([value["saturation"] for value in values])), 2),
            "frames": len(rows),
        })
    return result


def waiting_flags_for(frames, signatures, template_end=WAITING_TEMPLATE_END):
    """Flag every frame that visually matches the confirmed pre-game waiting screen."""
    templates = [signature for (timestamp, _), signature in zip(frames, signatures)
                 if timestamp <= template_end]
    if not templates:
        return [False] * len(signatures)
    flags = []
    for signature in signatures:
        matched = False
        for template in templates:
            if waiting_match(signature_distance(signature, template)):
                matched = True
                break
        flags.append(matched)
    return flags


def build_segments(buckets, minimum=MIN_GAMEPLAY_SECONDS):
    segments = []
    run = []
    sentinel = {"label": "end", "start": buckets[-1]["end"] if buckets else 0.0}
    for bucket in buckets + [sentinel]:
        if bucket["label"] == "gameplay":
            run.append(bucket)
            continue
        if run:
            start, end = run[0]["start"], run[-1]["end"]
            label = "gameplay" if end - start >= minimum else "uncertain"
            segments.append({"start": start, "end": end, "label": label})
            run = []
    return segments


def _tile(thumbnails, index, label):
    if index < 0 or index >= len(thumbnails) or not thumbnails[index]:
        return None
    image = cv2.imdecode(np.frombuffer(thumbnails[index], dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    image = cv2.resize(image, (TILE_W * 2, TILE_H * 2))
    cv2.putText(image, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(image, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2, cv2.LINE_AA)
    return image


def _label(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _write_sheet(picks, out_path, columns=5):
    if not picks:
        return
    rows = (len(picks) + columns - 1) // columns
    canvas = np.zeros((rows * TILE_H * 2, columns * TILE_W * 2, 3), dtype=np.uint8)
    for index, (image, label) in enumerate(picks):
        if image is None:
            continue
        row, col = divmod(index, columns)
        canvas[row * TILE_H * 2:(row + 1) * TILE_H * 2,
               col * TILE_W * 2:(col + 1) * TILE_W * 2] = image
    cv2.imwrite(out_path, canvas)
    print("contact sheet:", out_path)


def make_contact_sheet(frames, thumbnails, out_path, columns=6, rows=4):
    wanted = columns * rows
    picks = []
    for index in range(wanted):
        source_index = min(len(frames) - 1, int(len(frames) * (index + 0.5) / wanted))
        timestamp = frames[source_index][0]
        picks.append((_tile(thumbnails, source_index, _label(timestamp)), _label(timestamp)))
    _write_sheet(picks, out_path, columns)


def write_range_contact_sheet(frames, thumbnails, start, end, step, out_path, columns=5, limit=60):
    """Dense labelled sheet for a source-time range, used to confirm transitions."""
    picks = []
    moment = start
    while moment <= end and len(picks) < limit:
        index = min(range(len(frames)), key=lambda i: abs(frames[i][0] - moment))
        timestamp = frames[index][0]
        picks.append((_tile(thumbnails, index, _label(timestamp)), _label(timestamp)))
        moment += step
    _write_sheet(picks, out_path, columns)


def parse_confirm(values):
    segments = []
    for value in values or []:
        try:
            start, end = value.split("-", 1)
            start, end = float(start), float(end)
        except (ValueError, AttributeError):
            raise ValueError(f"invalid --confirm range: {value!r}; use START-END")
        if end <= start:
            raise ValueError(f"invalid --confirm range: {value!r}; END must follow START")
        segments.append({"start": start, "end": end, "label": "gameplay"})
    return segments


def authoritative_segments(timeline):
    confirmed = timeline.get("confirmed_segments")
    return confirmed if confirmed else timeline.get("segments", [])


def window_stats(start, end, timeline):
    """Coverage/static/waiting metrics for a source-time window."""
    span = max(0.001, float(end) - float(start))
    covered = 0.0
    for segment in authoritative_segments(timeline):
        if segment.get("label") != "gameplay":
            continue
        covered += max(0.0, min(float(end), float(segment["end"])) - max(float(start), float(segment["start"])))
    buckets = [row for row in timeline.get("buckets", [])
               if row["end"] > start and row["start"] < end]
    for row in buckets:
        if row["label"] == "non_gameplay":
            covered -= max(0.0, min(float(end), float(row["end"])) - max(float(start), float(row["start"])))
    covered = max(0.0, covered)
    static = float(np.mean([row["static_ratio"] for row in buckets])) if buckets else 1.0
    waiting = any(row.get("waiting_match_ratio", 0) > WAITING_MATCH_RATIO
                  or row.get("flat_screen_ratio", 0) > FLAT_RATIO_MAX for row in buckets)
    return {
        "gameplay_coverage_percentage": round(min(100.0, 100.0 * covered / span), 1),
        "static_screen_percentage": round(100.0 * static, 1),
        "waiting_screen_detected": waiting,
        "buckets_in_window": len(buckets),
        "confirmed": bool(timeline.get("confirmed_segments")),
    }


def is_gameplay_window(start, end, timeline, min_coverage=95.0, max_static=20.0, margin=2.0):
    """Check a whole clip (plus transition margin) against the authoritative timeline."""
    stats = window_stats(start - margin, end + margin, timeline)
    return (stats["gameplay_coverage_percentage"] >= min_coverage
            and stats["static_screen_percentage"] <= max_static
            and not stats["waiting_screen_detected"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--range-start", type=float, help="dense contact sheet from this source second")
    parser.add_argument("--range-end", type=float, help="dense contact sheet to this source second")
    parser.add_argument("--range-step", type=float, default=15.0)
    parser.add_argument("--range-sheet", default=None, help="path for the dense contact sheet")
    parser.add_argument("--confirm", action="append", default=[],
                        help="verified gameplay range START-END (repeatable)")
    parser.add_argument("--confirm-source", default="operator-supplied",
                        help="how the confirmed ranges were verified")
    args = parser.parse_args(argv)
    config.ensure_dirs()
    try:
        segments = parse_confirm(args.confirm)
        src = source_module.resolve(url=args.url)
        storyboard = ensure_storyboard(args.url, src.key)
        frames, thumbnails, signatures = storyboard_frames(storyboard)
        flags = waiting_flags_for(frames, signatures)
        buckets = bucketize(frames, flags)
        proposed = build_segments(buckets)
    except (ValueError, RuntimeError, OSError) as error:
        sys.exit(str(error))
    out = os.path.abspath(args.out or os.path.join(config.METADATA, src.key + "-gameplay-timeline.json"))
    contact = os.path.join(config.THUMBNAILS, src.key + "-gameplay-contact.jpg")
    timeline = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "gameplay-timeline",
        "source": {"key": src.key, "url": src.url, "title": src.title, "channel": src.channel},
        "method": "youtube-storyboard-sb0-visual-signals",
        "sample_interval_seconds": round((frames[-1][0] - frames[0][0]) / max(1, len(frames) - 1), 2) if frames else 0,
        "sample_count": len(frames),
        "contact_sheet": contact,
        "confirmed_by_human": bool(segments),
        "confirmation_basis": args.confirm_source if segments else None,
        "confirmed_segments": segments,
        "segments": proposed,
        "buckets": buckets,
    }
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as handle:
            previous = json.load(handle)
        if previous.get("confirmed_segments") and not segments:
            timeline["confirmed_segments"] = previous["confirmed_segments"]
            timeline["confirmed_by_human"] = True
            timeline["confirmation_basis"] = previous.get("confirmation_basis", "preserved")
    make_contact_sheet(frames, thumbnails, contact)
    if args.range_start is not None and args.range_end is not None:
        range_sheet = os.path.abspath(args.range_sheet or os.path.join(
            config.THUMBNAILS, src.key + f"-range-{int(args.range_start)}-{int(args.range_end)}.jpg"))
        write_range_contact_sheet(frames, thumbnails, args.range_start, args.range_end,
                                  args.range_step, range_sheet)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(timeline, handle, indent=2, ensure_ascii=False)
    print(f"sampled {len(frames)} frames across {frames[-1][0] / 60:.1f} min" if frames else "no frames")
    print(f"proposed gameplay segments: {len(proposed)}")
    for segment in proposed[:10]:
        print(f"  {segment['label']:<12} {segment['start'] / 60:7.1f}-{segment['end'] / 60:7.1f} min")
    if timeline["confirmed_segments"]:
        print("human-confirmed ranges:")
        for segment in timeline["confirmed_segments"]:
            print(f"  {segment['start'] / 60:7.1f}-{segment['end'] / 60:7.1f} min")
    else:
        print("NOT confirmed: review the contact sheet before using this timeline to gate clips")
    print("timeline:", out)


if __name__ == "__main__":
    main()
