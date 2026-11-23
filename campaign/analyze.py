"""Stage 1: scan audio and propose timestamp windows, without rendering anything.

Audio is decoded in blocks, so an 11-hour VOD never has to be held in memory.
For a VOD, only the low-bitrate audio track is downloaded.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

import clip

from campaigns import ids

from . import config, gameplay, source as source_module


def load_gameplay_timeline(path, campaign_id=None):
    """Load a human-confirmed timeline; refuse to rank audio peaks without one."""
    with open(path, encoding="utf-8") as handle:
        timeline = json.load(handle)
    stamped = timeline.get("campaign_id")
    if stamped and campaign_id and stamped != campaign_id:
        raise ValueError(
            f"timeline belongs to campaign {stamped!r}, not {campaign_id!r}; "
            "generate a campaign-specific gameplay timeline")
    if not timeline.get("confirmed_segments"):
        raise ValueError(f"{path} is not confirmed; run campaign.gameplay --confirm START-END first")
    return timeline


def timeline_path(src, explicit=None, campaign_id=None):
    """Resolve an explicit timeline path or this campaign's scoped/legacy file."""
    if explicit:
        return os.path.abspath(explicit)
    return config.timeline_path(src.key, campaign_id or src.campaign_id)


def filter_to_gameplay(candidates, timeline, min_coverage, margin):
    """Drop windows that are not entirely inside verified gameplay segments."""
    kept = []
    for row in candidates:
        stats = gameplay.window_stats(row["start"], row["end"], timeline)
        row["gameplay"] = stats
        if gameplay.is_gameplay_window(row["start"], row["end"], timeline,
                                       min_coverage=min_coverage, margin=margin):
            kept.append(row)
    for rank, row in enumerate(kept, 1):
        row["rank"] = rank
    return kept


def audio_levels(path, start=0.0, end=None, hop=config.SCAN_HOP,
                 block_seconds=config.SCAN_BLOCK_SECONDS):
    """Return dB levels per `hop` seconds, decoded as a stream."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if start and start > 0:
        command += ["-ss", f"{start:.2f}"]
    command += ["-i", os.path.abspath(path)]
    if end is not None and end > start:
        command += ["-t", f"{end - start:.2f}"]
    command += ["-vn", "-ac", "1", "-ar", str(config.SAMPLE_RATE), "-f", "f32le", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    hop_samples = int(round(config.SAMPLE_RATE * hop))
    block_samples = int(config.SAMPLE_RATE * block_seconds)
    pieces = []
    carry = np.empty(0, dtype=np.float32)
    try:
        while True:
            raw = process.stdout.read(block_samples * 4)
            if not raw:
                break
            chunk = np.frombuffer(raw, dtype=np.float32)
            data = np.concatenate((carry, chunk)) if carry.size else chunk
            usable = (data.size // hop_samples) * hop_samples
            if usable:
                frames = data[:usable].reshape(-1, hop_samples)
                pieces.append(20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6))
                carry = data[usable:]
            else:
                carry = data
        process.stdout.close()
        errors = process.stderr.read().decode("utf-8", "replace")
        process.wait()
        if process.returncode:
            raise RuntimeError("ffmpeg audio scan failed: " + errors[-400:])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float64)


def find_candidates(levels, offset, source_duration, clip_len, top, min_score,
                    lead_in, step, hop=config.SCAN_HOP):
    """Rank coarse audio-energy windows and return deduplicated absolute timestamps."""
    if levels.size == 0:
        return []
    duration = levels.size * hop
    if duration < clip_len:
        return []
    median = float(np.median(levels))
    mad = float(np.median(np.abs(levels - median))) + 1.0
    spike = (levels - median) / mad
    starts = np.arange(0, max(0.0, duration - clip_len) + 0.1, step)
    ranked = []
    for window_start in starts:
        a = int(window_start / hop)
        b = min(levels.size, int((window_start + clip_len) / hop))
        if b <= a:
            continue
        segment = spike[a:b]
        count = max(3, segment.size // 10)
        loud = float(np.sort(segment)[-count:].mean())
        if loud < min_score:
            continue
        peak_index = a + int(np.argmax(segment))
        peak_abs = offset + peak_index * hop
        ranked.append({
            "score": round(loud, 2),
            "window_start": round(offset + float(window_start), 2),
            "peak": round(peak_abs, 2),
            "peak_db": round(float(levels[peak_index]), 2),
            "mean_db": round(float(levels[a:b].mean()), 2),
        })
    ranked.sort(key=lambda row: (row["score"], row["window_start"]), reverse=True)
    chosen = []
    for row in ranked:
        start = clip.select_clip_start(row["peak"], lead_in, clip_len, source_duration)
        if any(abs(start - item["start"]) < clip_len for item in chosen):
            continue
        chosen.append({
            "start": round(float(start), 2),
            "end": round(min(float(start) + clip_len, source_duration), 2),
            **row,
        })
        if len(chosen) >= top:
            break
    for rank, item in enumerate(chosen, 1):
        item["rank"] = rank
    return chosen


def build_report(src, audio_path, levels, candidates, params, gameplay_info=None):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "analyze",
        "campaign_id": src.campaign_id,
        "source": {
            "key": src.key,
            "label": src.label,
            "title": src.title,
            "channel": src.channel,
            "url": src.url,
            "file": src.file,
            "duration": round(src.duration, 2),
            "platform": source_module.platform_name(src.info),
            "upload_date": src.info.get("upload_date"),
            "source_type": "local test" if src.is_local else "remote VOD",
            "authorization_note": "operator must confirm this source is authorized for the campaign",
        },
        "scan": {
            "audio_file": os.path.basename(audio_path),
            "levels": int(levels.size),
            "hop_seconds": config.SCAN_HOP,
            **params,
        },
        "gameplay": gameplay_info or {"applied": False},
        "candidates": candidates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="local sample video (fast pipeline tests)")
    parser.add_argument("--url", help="authorized VOD URL for the active campaign")
    parser.add_argument("--campaign", required=True, help="campaign id (required): " + " | ".join(ids()))
    parser.add_argument("--clip-len", type=float, default=config.DEFAULT_CLIP_LEN)
    parser.add_argument("--lead-in", type=float, default=config.DEFAULT_LEAD_IN)
    parser.add_argument("--top", type=int, default=config.DEFAULT_TOP)
    parser.add_argument("--min-score", type=float, default=config.DEFAULT_MIN_SCORE)
    parser.add_argument("--step", type=float, default=config.DEFAULT_STEP)
    parser.add_argument("--start", type=float, default=0.0, help="scan from this source second")
    parser.add_argument("--end", type=float, default=None, help="scan up to this source second")
    parser.add_argument("--timeline", default=None, help="confirmed gameplay timeline JSON")
    parser.add_argument("--min-gameplay-coverage", type=float, default=95.0,
                        help="minimum verified gameplay coverage per candidate")
    parser.add_argument("--gameplay-margin", type=float, default=2.0,
                        help="allowed transition margin at each end, in seconds")
    parser.add_argument("--out", default=None, help="report JSON path")
    args = parser.parse_args(argv)
    config.ensure_dirs()
    try:
        profile = config.active_profile(args.campaign)
        src = source_module.resolve(file=args.file, url=args.url, campaign_id=profile.id)
        audio_path = source_module.prepare_audio(src)
        timeline = None
        timeline_file = None
        if args.timeline or not src.is_local:
            timeline_file = timeline_path(src, args.timeline, profile.id)
            timeline = load_gameplay_timeline(timeline_file, profile.id)
        levels = audio_levels(audio_path, args.start, args.end)
        params = {
            "clip_len": args.clip_len, "lead_in": args.lead_in, "top": args.top,
            "min_score": args.min_score, "step": args.step,
            "scan_start": args.start, "scan_end": args.end,
            "min_gameplay_coverage": args.min_gameplay_coverage,
            "gameplay_margin": args.gameplay_margin,
        }
        candidates = find_candidates(levels, args.start, src.duration, args.clip_len,
                                     args.top, args.min_score, args.lead_in, args.step)
        gameplay_info = {"applied": False}
        if timeline:
            before = len(candidates)
            candidates = filter_to_gameplay(candidates, timeline,
                                            args.min_gameplay_coverage, args.gameplay_margin)
            gameplay_info = {
                "applied": True,
                "timeline": timeline_file,
                "confirmed_segments": timeline["confirmed_segments"],
                "candidates_before": before,
                "candidates_after": len(candidates),
                "min_coverage_percentage": args.min_gameplay_coverage,
                "margin_seconds": args.gameplay_margin,
            }
        report = build_report(src, audio_path, levels, candidates, params, gameplay_info)
    except (ValueError, RuntimeError) as error:
        sys.exit(str(error))
    out = os.path.abspath(args.out or os.path.join(
        config.CANDIDATES, f"{profile.clip_prefix}-{src.key}-timestamps.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(config.LOGS, "analyze-" + src.key + ".log"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"report": out, **params}, indent=2) + "\n")
        for item in candidates:
            handle.write(f"{item['rank']:>2}. {item['start']:>10.2f}-{item['end']:<10.2f} "
                         f"score={item['score']:<7} peak={item['peak']}\n")
    print(f"source: {src.label} ({src.channel}) duration={src.duration:.1f}s")
    print(f"scanned {levels.size} levels from {os.path.basename(audio_path)}")
    if not candidates:
        print("no candidates above --min-score")
    for item in candidates:
        print(f"  #{item['rank']} {item['start']:.2f}-{item['end']:.2f}s  "
              f"score={item['score']}  peak={item['peak']:.2f}s  mean_db={item['mean_db']}")
    print("report:", out)
    return report


if __name__ == "__main__":
    main()
