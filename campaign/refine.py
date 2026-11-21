"""Stage 2: re-anchor candidate windows to early speech and drop dead space.

Uses the already-downloaded low-bitrate audio, so no extra VOD download.
"""
import argparse
import json
import os
import subprocess
import sys

import clip

from . import captions, config, gameplay, source as source_module


def refine_candidates(src, audio_path, report, clip_len, language="en", pad=10.0,
                      timeline=None, min_coverage=95.0, margin=2.0):
    rows = []
    for row in report.get("candidates", []):
        window_start = max(0.0, float(row["start"]) - pad)
        window_length = clip_len + 2 * pad
        segment = os.path.join(config.WORK, "refine_" + src.key + "_" + str(row["rank"]) + ".wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{window_start:.2f}", "-i", os.path.abspath(audio_path),
                        "-t", f"{window_length:.2f}", "-vn", "-ac", "1", "-ar", "16000",
                        segment], check=True, capture_output=True, text=True)
        words = captions.transcribe_words(clip.load_audio(segment), language)
        os.remove(segment)
        first = min((word[0] for word in words if word[0] >= 0), default=None)
        updated = dict(row)
        if first is not None:
            first_absolute = window_start + float(first)
            updated["first_speech"] = round(first_absolute, 2)
            updated["speech_delay"] = round(max(0.0, first_absolute - float(row["start"])), 2)
            new_start = max(window_start, first_absolute - 1.0)
            updated["start"] = round(new_start, 2)
            updated["end"] = round(min(src.duration, new_start + clip_len), 2)
            updated["refined_score"] = round(float(row["score"]) - 0.02 * updated["speech_delay"], 2)
        else:
            updated["first_speech"] = None
            updated["speech_delay"] = None
            updated["refined_score"] = float(row["score"])
        rows.append(updated)
    rows.sort(key=lambda item: (item["refined_score"], item.get("speech_delay") or 99), reverse=True)
    if timeline:
        eligible = []
        for row in rows:
            stats = gameplay.window_stats(row["start"], row["end"], timeline)
            row["gameplay"] = stats
            if gameplay.is_gameplay_window(row["start"], row["end"], timeline,
                                           min_coverage=min_coverage, margin=margin):
                eligible.append(row)
        rows = eligible
    chosen = []
    for row in rows:
        if any(abs(row["start"] - item["start"]) < clip_len for item in chosen):
            continue
        chosen.append(row)
    for rank, row in enumerate(chosen, 1):
        row["rank"] = rank
        row["score"] = row["refined_score"]
    return chosen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file")
    parser.add_argument("--url")
    parser.add_argument("--timestamps", required=True)
    parser.add_argument("--clip-len", type=float, default=config.DEFAULT_CLIP_LEN)
    parser.add_argument("--spoken-language", default="en", choices=("en", "hi", "auto"))
    parser.add_argument("--timeline", default=None, help="confirmed gameplay timeline JSON")
    parser.add_argument("--min-gameplay-coverage", type=float, default=95.0)
    parser.add_argument("--gameplay-margin", type=float, default=2.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    config.ensure_dirs()
    try:
        src = source_module.resolve(file=args.file, url=args.url)
        with open(args.timestamps, encoding="utf-8") as handle:
            report = json.load(handle)
        audio = source_module.prepare_audio(src)
        language = None if args.spoken_language == "auto" else args.spoken_language
        timeline = None
        if args.timeline or not src.is_local:
            from .analyze import load_gameplay_timeline
            timeline = load_gameplay_timeline(os.path.abspath(args.timeline or os.path.join(
                config.METADATA, src.key + "-gameplay-timeline.json")))
        candidates = refine_candidates(src, audio, report, args.clip_len, language,
                                       timeline=timeline,
                                       min_coverage=args.min_gameplay_coverage,
                                       margin=args.gameplay_margin)
    except (ValueError, RuntimeError, OSError) as error:
        sys.exit(str(error))
    refined = dict(report)
    refined["stage"] = "refine"
    refined["candidates"] = candidates
    out = os.path.abspath(args.out or os.path.join(config.CANDIDATES, src.key + "-refined.json"))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(refined, handle, indent=2, ensure_ascii=False)
    for row in candidates:
        print(f"  #{row['rank']} {row['start']:.2f}-{row['end']:.2f}s "
              f"score={row['score']} first_speech={row.get('first_speech')} "
              f"delay={row.get('speech_delay')}")
    print("refined:", out)


if __name__ == "__main__":
    main()
