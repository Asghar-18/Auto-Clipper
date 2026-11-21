"""Stage 3: render one candidate with the fit layout, official logo and captions.

Reuses clip.py's caption writer; never publishes anything.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import clip

from . import captions, config, source as source_module


def srt_time(seconds):
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def write_srt(path, words, start, length):
    """Short phrase groups with non-overlapping timings relative to the clip."""
    inside = [word for word in words if start <= word[0] < start + length]
    groups = []
    group = []
    for item in inside + [(None, None, None)]:
        if group and (item[0] is None or item[0] - group[-1][1] > 0.6 or len(group) >= 3
                      or sum(len(part[2]) + 1 for part in group) > 18):
            groups.append(group)
            group = []
        if item[0] is not None:
            group.append(item)
    lines = []
    for index, group in enumerate(groups, 1):
        end = group[-1][1] + 0.2
        if index < len(groups):
            end = min(end, groups[index][0][0] - 0.001)
        end = min(end, start + length)
        if end <= group[0][0]:
            continue
        text = " ".join(clip.mask_word(part[2]) for part in group)
        lines.append(f"{index}\n{srt_time(group[0][0] - start)} --> "
                     f"{srt_time(end - start)}\n{text}\n")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def build_filter(ass_name, logo_supported=True):
    """fit layout + logo pinned across the top. Mirrors clip.py's proven fit branch."""
    base = ("[0:v]split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=30:5[bg];"
            "[b]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setpts=PTS-STARTPTS,"
            f"ass={ass_name}[captioned]")
    if not logo_supported:
        return base + "[captioned]null[out]"
    return (base + ";" +
            "[1:v]scale=1080:-2[logo];"
            "[captioned][logo]overlay=0:24:shortest=0[out]")


def render_candidate(src, media_path, candidate, logo, out_dir, spoken_language="en",
                     source_start=None):
    """Render one window. Returns paths to the MP4, SRT and render report."""
    clip._forced_language = None if spoken_language == "auto" else spoken_language
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"kreek-{src.key}-{stamp}-{candidate['rank']:02d}"
    mp4 = os.path.join(out_dir, name + ".mp4")
    srt = os.path.join(out_dir, name + ".srt")
    ass_path = os.path.join(out_dir, "cap_" + name + ".ass")
    start, length = float(candidate["start"]), float(candidate["end"]) - float(candidate["start"])

    # Transcribe only this short window, then shift word times back to source time.
    segment_audio = os.path.join(out_dir, "seg_" + name + ".wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.2f}", "-i", os.path.abspath(media_path),
                    "-t", f"{length:.2f}", "-vn", "-ac", "1", "-ar", "16000",
                    segment_audio], check=True, capture_output=True, text=True)
    raw_words = captions.transcribe_words(clip.load_audio(segment_audio), spoken_language)
    words = clip.WordTimings([(float(w[0]) + start, float(w[1]) + start, w[2]) for w in raw_words],
                             raw_words.spoken_language, raw_words.caption_language,
                             raw_words.caption_fallback_reason)
    os.remove(segment_audio)

    margin = clip.caption_margin_for_video(media_path, crop=False, source_roi=None)
    clip.write_ass(ass_path, words, start, length, credit=None, caption_margin_v=margin)
    write_srt(srt, words, start, length)

    has_logo = bool(logo) and os.path.isfile(logo)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{start:.2f}", "-i", os.path.abspath(media_path)]
    if has_logo:
        command += ["-loop", "1", "-i", os.path.abspath(logo)]
    command += ["-t", f"{length:.2f}", "-filter_complex", build_filter(os.path.basename(ass_path), has_logo),
                "-map", "[out]", "-map", "0:a:0?", "-af", "asetpts=PTS-STARTPTS",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", mp4]
    result = subprocess.run(command, capture_output=True, text=True, cwd=out_dir)
    if os.path.exists(ass_path):
        os.remove(ass_path)
    if result.returncode:
        raise RuntimeError("render failed: " + result.stderr[-500:])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "render",
        "video": os.path.basename(mp4),
        "srt": os.path.basename(srt),
        "source": {"key": src.key, "url": src.url, "file": src.file,
                   "title": src.title, "channel": src.channel},
        "source_start": round(source_start if source_start is not None else start, 2),
        "source_end": round((source_start if source_start is not None else start) + length, 2),
        "duration": round(length, 2),
        "detection_score": candidate["score"],
        "gameplay": candidate.get("gameplay"),
        "logo_overlay": os.path.basename(logo) if has_logo else None,
        "logo_file": os.path.abspath(logo) if has_logo else None,
        "spoken_language": words.spoken_language,
        "caption_language": words.caption_language,
        "transcript": " ".join(word[2] for word in words),
        "layout": "fit-9x16",
        "test": src.is_local,
        "approved": False,
        "posted": {},
    }
    json_path = os.path.join(out_dir, name + ".json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return mp4, srt, json_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file")
    parser.add_argument("--url")
    parser.add_argument("--timestamps", help="timestamps JSON from campaign.analyze")
    parser.add_argument("--rank", type=int, default=1, help="candidate rank to render")
    parser.add_argument("--start", type=float, help="override candidate start (source seconds)")
    parser.add_argument("--length", type=float, help="override clip length")
    parser.add_argument("--logo", help="override official logo PNG path")
    parser.add_argument("--spoken-language", default="en", choices=("en", "hi", "auto"))
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    config.ensure_dirs()
    try:
        src = source_module.resolve(file=args.file, url=args.url)
        if args.timestamps:
            with open(args.timestamps, encoding="utf-8") as handle:
                report = json.load(handle)
            matches = [row for row in report["candidates"] if row["rank"] == args.rank]
            if not matches:
                raise ValueError(f"No candidate with rank {args.rank} in {args.timestamps}")
            candidate = matches[0]
        elif args.start is not None:
            candidate = {"rank": args.rank, "start": args.start,
                         "end": args.start + (args.length or config.DEFAULT_CLIP_LEN),
                         "score": None, "peak": args.start}
        else:
            raise ValueError("Pass --timestamps or --start.")
        length = args.length or (candidate["end"] - candidate["start"])
        source_start = float(candidate["start"])
        candidate = dict(candidate, end=source_start + length)
        out_dir = os.path.abspath(args.out_dir or config.CANDIDATES)
        logo = config.logo_path(args.logo)
        if src.is_local:
            media = source_module.prepare_audio(src)
        else:
            pad = 2.0
            section_start = max(0.0, source_start - pad)
            section_end = source_start + length + pad
            section_path = os.path.join(config.WORK,
                                        f"{src.key}-{int(section_start)}-{int(section_end)}.mp4")
            matching = [path for path in glob.glob(os.path.splitext(section_path)[0] + ".*")
                        if os.path.getsize(path) > 0]
            if matching:
                media = matching[0]
            else:
                print(f"downloading VOD section {section_start:.1f}s-{section_end:.1f}s ...")
                media = source_module.download_section(src.url, section_start,
                                                       section_end - section_start, section_path)
            relative_start = source_start - section_start
            candidate = dict(candidate, start=relative_start, end=relative_start + length)
        mp4, srt, json_path = render_candidate(src, media, candidate, logo, out_dir,
                                               args.spoken_language, source_start=source_start)
    except (ValueError, RuntimeError, OSError) as error:
        sys.exit(str(error))
    print("rendered:", mp4)
    print("subtitles:", srt)
    print("metadata:", json_path)


if __name__ == "__main__":
    main()
