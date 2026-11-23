"""Read-only probe of one Boeshi Twitch VOD. Renders nothing, publishes nothing.

Usage (from the project root):
    python tools/boeshi_vod_probe.py https://www.twitch.tv/videos/2935956182

Writes everything to work/boeshi-probe/<vod id>/:
  info.txt         metadata, formats, which format each selector picks
  storyboard.txt   what the sb0 storyboard looks like (tile size, image type, timing)
  frames.jpg       8 real frames across the VOD at the best available height
"""
import email
import json
import os
import subprocess
import sys

import cv2
import numpy as np

YTDLP = [sys.executable, "-m", "yt_dlp", "--no-warnings"]


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def main(url):
    info = json.loads(run(YTDLP + ["-J", "--no-download", url], check=True).stdout)
    out = os.path.join("work", "boeshi-probe", str(info["id"]))
    os.makedirs(out, exist_ok=True)
    lines = [f"{k}: {info.get(k)}" for k in (
        "id", "title", "uploader", "uploader_id", "channel", "upload_date", "timestamp",
        "duration", "extractor_key", "webpage_url_domain", "is_live", "availability")]
    lines.append("\nformats (id | height | vcodec | acodec | protocol):")
    for f in info.get("formats", []):
        lines.append(f"  {f.get('format_id')} | {f.get('height')} | {f.get('vcodec')} | "
                     f"{f.get('acodec')} | {f.get('protocol')}")
    lines.append("\nselector picks:")
    for selector in ("bv[height<=1080]+ba/b[height<=720]/b",   # current download_section
                     "b[height<=1080]/bv[height<=1080]+ba/b",  # proposed
                     "139/bestaudio/worst"):                   # current audio scan
        picked = run(YTDLP + ["-f", selector, "--simulate", "--print",
                              "%(format_id)s height=%(height)s", url])
        lines.append(f"  {selector}  ->  {(picked.stdout or picked.stderr).strip()[-200:]}")
    with open(os.path.join(out, "info.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    # Storyboard: does gameplay.py's YouTube-style parser have anything to read?
    sb_path = os.path.join(out, "storyboard.mhtml")
    sb = run(YTDLP + ["-f", "sb0", "-o", sb_path, url])
    report = []
    if sb.returncode or not os.path.isfile(sb_path):
        report.append("sb0 download FAILED: " + sb.stderr[-400:])
    else:
        with open(sb_path, "rb") as handle:
            message = email.message_from_binary_file(handle)
        parts = [p for p in message.walk() if p.get_content_maintype() == "image"]
        types = sorted({p.get_content_type() for p in parts})
        report.append(f"image parts: {len(parts)}  content types: {types}")
        for index, part in enumerate(parts[:3] + parts[-1:]):
            data = np.frombuffer(part.get_payload(decode=True) or b"", dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
            shape = None if image is None else image.shape[:2]
            report.append(f"  part {index}: {part.get_content_type()} sheet(h,w)={shape} "
                          f"X.yt-dlp.Duration={part.get('X.yt-dlp.Duration')}")
        fmt = next((f for f in info.get("formats", []) if f.get("format_id") == "sb0"), {})
        report.append(f"sb0 spec: width={fmt.get('width')} height={fmt.get('height')} "
                      f"rows={fmt.get('rows')} columns={fmt.get('columns')} fps={fmt.get('fps')}")
    with open(os.path.join(out, "storyboard.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(report) + "\n")

    # Eight real frames, to see the stream layout (webcam position, gameplay vs chatting).
    stream = run(YTDLP + ["-f", "b[height<=1080]/b", "-g", url], check=True).stdout.split()[0]
    duration = float(info.get("duration") or 0)
    tiles = []
    for i in range(8):
        t = duration * (i + 0.5) / 8
        jpg = os.path.join(out, f"frame_{int(t)}.jpg")
        run(["ffmpeg", "-v", "error", "-ss", f"{t:.0f}", "-i", stream, "-frames:v", "1",
             "-y", jpg], timeout=180)
        frame = cv2.imread(jpg)
        if frame is None:
            continue
        frame = cv2.resize(frame, (960, 540))
        cv2.putText(frame, f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}",
                    (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
        tiles.append(frame)
    if tiles:
        while len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
        cv2.imwrite(os.path.join(out, "frames.jpg"), np.vstack(rows))
    print("Wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
