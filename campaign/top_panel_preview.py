"""Dylan top-panel preview sheet (review aid only; renders nothing publishable).

For each source frame it draws an 8x8 labeled grid (rows A-H, columns 1-8,
each cell 1/8 of the frame), a red outline of the configured region (the
campaign's per-video override when one exists, else its default region),
a green outline of the part that actually appears in the 1080x960 top panel,
and a blue outline of the gameplay (bottom) panel. Beside the frame it shows the
full 1080x1920 output (without captions), built with the renderer's filter chains.

Use it to name the grid cells that hold Dylan's webcam, e.g. "B6:D8".

    python -m campaign.top_panel_preview --campaign dylan_page --dylan-vods
    python -m campaign.top_panel_preview --campaign dylan_page --source URL_OR_FILE --at 12130
    python -m campaign.top_panel_preview --campaign dylan_page --dylan-vods --cells B6:D8   # try a region
    python -m campaign.top_panel_preview --campaign dylan_page --dylan-vods --region 1316,0,604,537
    python -m campaign.top_panel_preview --campaign dylan_page --dylan-vods --gameplay-region 101,0,1215,1080
"""
import argparse
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

from campaigns import ids

from . import config, dylan_layout, source as source_module

GRID = 8
ROWS = "ABCDEFGH"
# User-confirmed gameplay starts; sample 10 s in so the frame is mid-gameplay.
# i1zUT_gKQzA (Best Moments) is excluded: moving webcam, burned-in subtitles.
DYLAN_VODS = [
    ("xFcI47X15Lo", "DAY 2", 12120),
    ("FI5ZXVYuD04", "DAY 2 Part 2", 7800),
    ("tvT6ZVHOtWs", "DAY 3", 6000),
    ("-6PVU387zOo", "DAY 3 Part 2", 14100),
    ("cq7OxWhmgHA", "DAY 4", 2000),
    ("LEAdEczRNEc", "DAY 4 Part 2", 13200),
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


def parse_region(spec):
    """``"1316,0,604,537"`` (pixels on a 1920x1080 frame) -> fractional region."""
    parts = [int(v) for v in re.split(r"\s*,\s*", spec.strip())]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError(f"region must be x,y,w,h in 1920x1080 pixels, got {spec!r}")
    x, y, w, h = parts
    if x < 0 or y < 0 or x + w > 1920 or y + h > 1080:
        raise ValueError(f"region {spec!r} runs outside the 1920x1080 frame")
    return (x / 1920, y / 1080, w / 1920, h / 1080)


def region_box(region, width, height):
    fx, fy, fw, fh = region
    return (int(width * fx), int(height * fy), int(width * fw), int(height * fh))


def grab_frame(media, at, out_png):
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", media,
                    "-frames:v", "1", "-y", out_png], check=True)
    return out_png


def stacked_frame(frame_png, box, game_box, out_png):
    """The real 1080x1920 composition (no captions) for one frame."""
    graph = (f"[0:v]split=2[a][b];[a]{dylan_layout.top_panel_chain(box)}[t];"
             f"[b]{dylan_layout.bottom_panel_chain(game_box)}[g];[t][g]vstack=inputs=2[out]")
    subprocess.run(["ffmpeg", "-v", "error", "-i", frame_png, "-filter_complex", graph,
                    "-map", "[out]", "-frames:v", "1", "-y", out_png], check=True)
    return out_png


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(frame_png, box, label, game_box=None):
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
    if game_box is None:  # default bottom panel: full-height 9:8 centre crop
        gw = height * dylan_layout.TOP_PANEL_W / dylan_layout.TOP_PANEL_H
        game_box = ((width - gw) / 2, 0, gw, height)
    gx, gy, gw, gh = dylan_layout.visible_source_box(game_box) if len(game_box) == 4 else game_box
    draw.rectangle([gx + 3, gy + 3, gx + gw - 4, gy + gh - 4], outline=(0, 160, 255), width=6)
    big = _font(max(20, height // 22))
    draw.text((12, height - big.size - 16), label, fill=(255, 255, 255), font=big,
              stroke_width=3, stroke_fill=(0, 0, 0))
    return frame


def build_row(media, at, label, region, work, game_region):
    stem = re.sub(r"[^A-Za-z0-9]+", "_", label)
    frame_png = grab_frame(media, at, os.path.join(work, stem + "_frame.png"))
    width, height = Image.open(frame_png).size
    box = region_box(region, width, height)
    game_box = dylan_layout.gameplay_box(width, height, game_region)
    stacked = Image.open(stacked_frame(frame_png, box, game_box,
                                       os.path.join(work, stem + "_stack.png")))
    frame = annotate(frame_png, box, label, game_box).resize((1920, 1080))
    stacked = stacked.resize((608, 1080))  # full 9:16 output at the frame's height
    row = Image.new("RGB", (1920 + 30 + 608, 1080), (30, 30, 30))
    row.paste(frame, (0, 0))
    row.paste(stacked, (1950, 0))
    return row


def fetch(url, start, work, name):
    out = os.path.join(work, name + ".mp4")
    return source_module.download_section(url, start, 3, out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", required=True, help="campaign id (required): " + " | ".join(ids()))
    parser.add_argument("--dylan-vods", action="store_true",
                        help="sample all seven confirmed Dylan VODs")
    parser.add_argument("--source", action="append", default=[],
                        help="URL or local video file (repeatable; pair with --at)")
    parser.add_argument("--at", action="append", type=float, default=[],
                        help="timestamp in seconds for each --source")
    parser.add_argument("--cells", help="preview a grid region instead of the configured region, e.g. B6:D8")
    parser.add_argument("--region", help="preview a pixel region x,y,w,h on a 1920x1080 "
                        "frame, e.g. 1316,0,604,537 (use a 9:8 shape to avoid side cropping)")
    parser.add_argument("--gameplay-region", help="bottom-panel pixel region x,y,w,h on a "
                        "1920x1080 frame (9:8 shape), e.g. 101,0,1215,1080 to leave out the webcam")
    parser.add_argument("--out", default=os.path.join(
        "output", "thumbnails", "top-panel-preview", "top-panel-preview.jpg"))
    args = parser.parse_args(argv)
    if len(args.source) != len(args.at):
        parser.error("give one --at for every --source")

    if args.cells and args.region:
        parser.error("use --cells or --region, not both")
    if args.region:
        forced = parse_region(args.region)
    elif args.cells:
        forced = parse_cells(args.cells)
    else:
        forced = None

    rules = config.active_profile(args.campaign).video
    game_region = (parse_region(args.gameplay_region) if args.gameplay_region
                   else rules.stacked_bottom_region)

    def region_for(video_id):
        region = forced or dylan_layout.facebox_region(rules, video_id)
        if region is None:
            parser.error(f"campaign {args.campaign!r} has no top-panel region; pass --region")
        return region

    jobs = []
    if args.dylan_vods:
        jobs += [(f"https://www.youtube.com/watch?v={vid}", start + SAMPLE_OFFSET,
                  f"{label} ({vid})", region_for(vid))
                 for vid, label, start in DYLAN_VODS]
    for src, at in zip(args.source, args.at):
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", src)
        jobs.append((src, at, os.path.basename(src)[:40],
                     region_for(match.group(1) if match else None)))
    if not jobs:
        parser.error("pass --dylan-vods or at least one --source/--at pair")

    rows = []
    with tempfile.TemporaryDirectory() as work:
        for index, (src, at, label, region) in enumerate(jobs):
            print(f"[{index + 1}/{len(jobs)}] {label} @ {at:.0f}s")
            try:
                if os.path.isfile(src):
                    media, seek = src, at
                else:
                    media, seek = fetch(src, at, work, f"src{index}"), 0.5
                rows.append(build_row(media, seek, label, region, work, game_region))
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
    print("Region:", args.region or args.cells or "per-video configured regions")
    print("Red = top-panel region, green = what the top panel really shows, "
          "blue = gameplay panel. Right: full 9:16 output (no captions).")
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
