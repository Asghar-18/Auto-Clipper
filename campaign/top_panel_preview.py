"""Dylan top-panel preview sheet (review aid only; renders nothing publishable).

For each source frame it draws an 8x8 labeled grid (rows A-H, columns 1-8,
each cell 1/8 of the frame), a red outline of the configured FACEBOX_REGION,
and a green outline of the part that actually appears in the 1080x960 top
panel. Beside the frame it shows the real top-panel output, built with the same
filter chain the renderer uses.

Use it to name the grid cells that hold Dylan's webcam, e.g. "B6:D8".

    python -m campaign.top_panel_preview --dylan-vods
    python -m campaign.top_panel_preview --source URL_OR_FILE --at 12130
    python -m campaign.top_panel_preview --dylan-vods --cells B6:D8   # try a region
"""
import argparse
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

from . import dylan_layout, source as source_module

GRID = 8
ROWS = "ABCDEFGH"
# User-confirmed gameplay starts; sample 10 s in so the frame is mid-gameplay.
DYLAN_VODS = [
    ("xFcI47X15Lo", "DAY 2", 12120),
    ("FI5ZXVYuD04", "DAY 2 Part 2", 7800),
    ("tvT6ZVHOtWs", "DAY 3", 6000),
    ("-6PVU387zOo", "DAY 3 Part 2", 14100),
    ("cq7OxWhmgHA", "DAY 4", 2000),
    ("LEAdEczRNEc", "DAY 4 Part 2", 13200),
    ("i1zUT_gKQzA", "120h Best Moments", 420),
]
SAMPLE_OFFSET = 10


def parse_cells(spec):
    """``"B6:D8"`` -> fractional ``(x, y, w, h)`` covering those whole cells."""
    match = re.fullmatch(r"\s*([A-H])([1-8])\s*:\s*([A-H])([1-8])\s*", spec.upper())
    if not match:
        raise ValueError(f"cells must look like B6:D8, got {spec!r}")
    r1, c1, r2, c2 = match.groups()
    top, bottom = sorted((ROWS.index(r1), ROWS.index(r2)))
    left, right = sorted((int(c1) - 1, int(c2) - 1))
    return (left / GRID, top / GRID, (right - left + 1) / GRID, (bottom - top + 1) / GRID)


def region_box(region, width, height):
    fx, fy, fw, fh = region
    return (int(width * fx), int(height * fy), int(width * fw), int(height * fh))


def grab_frame(media, at, out_png):
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", media,
                    "-frames:v", "1", "-y", out_png], check=True)
    return out_png


def top_panel(frame_png, box, out_png):
    subprocess.run(["ffmpeg", "-v", "error", "-i", frame_png,
                    "-vf", dylan_layout.top_panel_chain(box),
                    "-frames:v", "1", "-y", out_png], check=True)
    return out_png


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(frame_png, box, label):
    frame = Image.open(frame_png).convert("RGB")
    width, height = frame.size
    draw = ImageDraw.Draw(frame)
    font = _font(max(14, height // 40))
    cw, ch = width / GRID, height / GRID
    for i in range(1, GRID):
        draw.line([(i * cw, 0), (i * cw, height)], fill=(255, 255, 0), width=2)
        draw.line([(0, i * ch), (width, i * ch)], fill=(255, 255, 0), width=2)
    for r in range(GRID):
        for c in range(GRID):
            draw.text((c * cw + 6, r * ch + 4), f"{ROWS[r]}{c + 1}",
                      fill=(255, 255, 0), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    x, y, w, h = box
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 0, 0), width=6)
    vx, vy, vw, vh = dylan_layout.visible_source_box(box)
    draw.rectangle([vx, vy, vx + vw - 1, vy + vh - 1], outline=(0, 255, 0), width=6)
    big = _font(max(20, height // 22))
    draw.text((12, height - big.size - 16), label, fill=(255, 255, 255), font=big,
              stroke_width=3, stroke_fill=(0, 0, 0))
    return frame


def build_row(media, at, label, region, work):
    stem = re.sub(r"[^A-Za-z0-9]+", "_", label)
    frame_png = grab_frame(media, at, os.path.join(work, stem + "_frame.png"))
    width, height = Image.open(frame_png).size
    box = region_box(region, width, height)
    panel = Image.open(top_panel(frame_png, box, os.path.join(work, stem + "_top.png")))
    frame = annotate(frame_png, box, label).resize((1920, 1080))
    panel = panel.resize((1215, 1080))  # 1080x960 shown at the same height as the frame
    row = Image.new("RGB", (1920 + 30 + 1215, 1080), (30, 30, 30))
    row.paste(frame, (0, 0))
    row.paste(panel, (1950, 0))
    return row


def fetch(url, start, work, name):
    out = os.path.join(work, name + ".mp4")
    return source_module.download_section(url, start, 3, out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dylan-vods", action="store_true",
                        help="sample all seven confirmed Dylan VODs")
    parser.add_argument("--source", action="append", default=[],
                        help="URL or local video file (repeatable; pair with --at)")
    parser.add_argument("--at", action="append", type=float, default=[],
                        help="timestamp in seconds for each --source")
    parser.add_argument("--cells", help="preview a grid region instead of FACEBOX_REGION, e.g. B6:D8")
    parser.add_argument("--out", default=os.path.join(
        "output", "thumbnails", "top-panel-preview", "top-panel-preview.jpg"))
    args = parser.parse_args(argv)
    if len(args.source) != len(args.at):
        parser.error("give one --at for every --source")

    region = parse_cells(args.cells) if args.cells else dylan_layout.FACEBOX_REGION
    jobs = []
    if args.dylan_vods:
        jobs += [(f"https://www.youtube.com/watch?v={vid}", start + SAMPLE_OFFSET, f"{label} ({vid})")
                 for vid, label, start in DYLAN_VODS]
    jobs += [(src, at, os.path.basename(src)[:40]) for src, at in zip(args.source, args.at)]
    if not jobs:
        parser.error("pass --dylan-vods or at least one --source/--at pair")

    rows = []
    with tempfile.TemporaryDirectory() as work:
        for index, (src, at, label) in enumerate(jobs):
            print(f"[{index + 1}/{len(jobs)}] {label} @ {at:.0f}s")
            try:
                if os.path.isfile(src):
                    media, seek = src, at
                else:
                    media, seek = fetch(src, at, work, f"src{index}"), 0.5
                rows.append(build_row(media, seek, label, region, work))
            except Exception as error:  # keep going; one bad VOD shouldn't block the sheet
                print(f"  skipped: {error}")
    if not rows:
        raise SystemExit("No frames could be sampled.")

    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows) + 20 * (len(rows) - 1)),
                      (0, 0, 0))
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height + 20
    scale = 1600 / sheet.width
    sheet = sheet.resize((1600, int(sheet.height * scale)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sheet.save(args.out, quality=88)
    print("Region:", args.cells or "FACEBOX_REGION", region)
    print("Red = selected region, green = what the top panel really shows.")
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
