"""Dylan-only adaptive vertical composition.

This module uses generic face-position sampling to build a smoothed crop path for
a 1080x1920 render. ``adaptive-face`` fills the frame with a tight facecam crop;
``adaptive-stacked`` keeps Dylan prominent in a *fixed* upper panel while a lower
panel shows the full source width so gameplay stays readable. The face samples
choose one static crop position; the panel never pans. It is deliberately not an
identity system: ``identity_verified`` stays false and uncertain clips still go
to manual review. When no confident face signal exists, callers keep the
campaign's existing fit renderer as the fallback.
"""
import re
import subprocess
from statistics import median

from shared import focus

CROP_W = 1080
CROP_H = 1920
SAMPLE_INTERVAL = 1.0
MIN_FACE_AREA = 0.001       # fraction of the source frame; smaller faces are not tracked
MIN_FACE_SAMPLES = 8
MIN_PRESENCE_RATIO = 0.7
MAX_CROP_SPEED = 0.16       # fraction of scaled width per second
# Operator-selected region: grid cells A3+A4+B3+B4, i.e. the top-right half
# of the source frame. Fractions are (x, y, width, height).
FACEBOX_REGION = (0.5, 0.0, 0.5, 0.5)


def source_dimensions(video_path):
    """Probe a video's source width/height, with a 1920x1080 last resort."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
         video_path], capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"(\d+)x(\d+)", line.strip())
        if match:
            width, height = (int(value) for value in match.groups())
            if width > 0 and height > 0:
                return width, height
    return 1920, 1080


def crop_offset_for_x(face_x, source_width=1920, source_height=1080):
    """Return the 0..1 crop offset that centres ``face_x`` after scaling to 1920 high."""
    if source_width <= 0 or source_height <= 0:
        return 0.5
    scale = CROP_H / float(source_height)
    scaled_width = source_width * scale
    available = scaled_width - CROP_W
    if available <= 0:
        return 0.5
    offset = (float(face_x) * scale - CROP_W / 2) / available
    return min(1.0, max(0.0, offset))


def smooth_offsets(keys, default=0.5, max_speed=MAX_CROP_SPEED):
    """Median-filter and speed-limit a list of ``(time, offset)`` keyframes."""
    if not keys:
        return []
    times = [float(pair[0]) for pair in keys]
    values = [float(pair[1]) for pair in keys]
    # Preserve the first/last observed positions; median-filter only interior points.
    smoothed = ([values[0]] +
                [median(values[index - 1:index + 2])
                 for index in range(1, len(values) - 1)] +
                [values[-1]])
    out = [smoothed[0] if smoothed[0] is not None else float(default)]
    for index in range(1, len(smoothed)):
        dt = max(1e-3, times[index] - times[index - 1])
        step = max(-max_speed * dt, min(max_speed * dt, smoothed[index] - out[-1]))
        out.append(out[-1] + step)
    return list(zip(times, out))


def crop_x_expression(keys, out_w=CROP_W):
    """ffmpeg crop-x expression for a piecewise-linear pan through ``keys``."""
    if len(keys) < 2:
        raise ValueError("adaptive crop needs at least two keyframes")

    def at(offset):
        return f"(iw*{offset:.4f}-{out_w // 2})"

    expression = at(keys[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        if t1 <= t0:
            continue
        segment = f"({at(x0)}+({at(x1)}-{at(x0)})*(t-{t0:.2f})/{t1 - t0:.2f})"
        expression = f"if(lt(t\\,{t1:.2f})\\,{segment}\\,{expression})"
    return f"max(0\\,min(iw-{out_w}\\,{expression}))"


def build_filter(ass_name, keys):
    """Build a logo-free 9:16 fill filtergraph that pans with ``keys``."""
    expression = crop_x_expression(keys)
    return ("[0:v]setpts=PTS-STARTPTS,"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920:'{expression}':(ih-1920)/2,"
            f"ass={ass_name}[out]")


def facecam_box(video_path, start, length, sample_interval=SAMPLE_INTERVAL):
    """Return the operator-selected fixed region as ``(x, y, w, h)``.

    The region is grid cells A3+A4+B3+B4: the top-right half of the source
    frame. It never pans or resizes. Face sampling still gates whether the
    stacked layout is used at all, but it does not move this crop.
    """
    width, height = source_dimensions(video_path)
    fx, fy, fw, fh = FACEBOX_REGION
    return (int(width * fx), int(height * fy),
            int(width * fw), int(height * fh))


TOP_PANEL_W = 1080
TOP_PANEL_H = 960


def top_panel_chain(box):
    """ffmpeg filter chain that turns the source frame into the 1080x960 top panel."""
    x, y, width, height = box
    return (f"crop={width}:{height}:{x}:{y},"
            f"scale={TOP_PANEL_W}:{TOP_PANEL_H}:force_original_aspect_ratio=increase,"
            f"crop={TOP_PANEL_W}:{TOP_PANEL_H}")


def visible_source_box(box):
    """Source-pixel ``(x, y, w, h)`` that actually appears in the top panel.

    ``top_panel_chain`` scales to cover 1080x960 and centre-crops, so a region
    whose aspect is not 9:8 loses its edges. A 960x540 region keeps only its
    middle ~607 px of width.
    """
    x, y, width, height = box
    scale = max(TOP_PANEL_W / float(width), TOP_PANEL_H / float(height))
    vis_w = TOP_PANEL_W / scale
    vis_h = TOP_PANEL_H / scale
    return (x + (width - vis_w) / 2.0, y + (height - vis_h) / 2.0, vis_w, vis_h)


def build_stacked_filter(ass_name, box):
    """Dylan-only 9:16 stack: tight fixed facecam over a wide gameplay panel.

    The upper 1080x960 panel crops the operator-selected top-right source region
    and never pans. The lower 1080x960 panel shows the full source width. No
    branding or blurred filler is added.
    """
    graph = (
        "[0:v]setpts=PTS-STARTPTS,split=2[face][game];"
        f"[face]{top_panel_chain(box)}[top];"
        "[game]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom];"
        f"[top][bottom]vstack=inputs=2,ass={ass_name}[out]"
    )
    return graph


def adaptive_keys(video_path, start, length, sample_interval=SAMPLE_INTERVAL):
    """Return smoothed ``(time, crop_offset)`` keys, or ``None`` for fit fallback."""
    analysis = focus.analyze_focus(video_path, start, length, sample_interval)
    if analysis.get("status") != "ok":
        return None
    if analysis.get("presence_ratio", 0.0) < MIN_PRESENCE_RATIO:
        return None
    width, height = source_dimensions(video_path)
    raw = []
    for item in analysis.get("observations", []):
        cx = item.get("cx")
        area = item.get("area", 0.0)
        if item.get("faces") and cx is not None and area >= MIN_FACE_AREA:
            raw.append((float(item["time"]), crop_offset_for_x(cx, width, height)))
    if len(raw) < MIN_FACE_SAMPLES:
        return None
    return smooth_offsets(raw)
