"""Stage 2b: rank alternative gameplay moments by transcript interest.

Reuses the confirmed gameplay timeline and cached low-bitrate audio. Loudness alone
picks reactions over waiting screens, so this stage scores dialogue variety,
laughter, excitement, gameplay language and visual activity, then penalizes
repetition, long gaps and any overlap with clips already rendered.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

import clip

from . import analyze, captions, config, gameplay, source as source_module
from shared import storage

STOPWORDS = set("""a an the and or but if of to in on at for with is are was were be been being
it its this that these those i me my we our you your he she they them his her their do does did
have has had will would can could should just so up out about into over then than there here what
who how when where why all not no yes oh uh um like really very gonna gonna gonna""".split())
EXCITEMENT = set("""wow crazy insane holy damn amazing unbelievable awesome sick wild fun excited
stop wait no way let's go bro dude jeez geez lol haha laugh hilarious great nice good god""".split())
GAMEPLAY = set("""car cars drive driving driver mission missions police cop cops shoot shooting gun
weapon map minimap snapmatic phone shop buy buy buying vehicle road house story jason lucia game
controller button buttons play playing level mission""".split())
LAUGHTER = set("haha hehe lol laugh laughing hilarious".split())


def transcript_features(text, words):
    tokens = re.findall(r"[a-z']+", (text or "").lower())
    content = [token for token in tokens if token not in STOPWORDS and len(token) > 2]
    counts = collections.Counter(content)
    total = max(1, len(content))
    unique_ratio = len(counts) / total if content else 0.0
    repetition = (counts.most_common(1)[0][1] / total) if content else 1.0
    top3 = sum(count for _, count in counts.most_common(3)) / total if content else 1.0
    excitement = sum(1 for token in tokens if token.strip("'") in EXCITEMENT)
    laughter = sum(1 for token in tokens if token.strip("'") in LAUGHTER)
    gameplay_terms = sum(1 for token in tokens if token.strip("'") in GAMEPLAY)
    exclamations = sum(1 for word in words if "!" in word[2])
    if words:
        speech_coverage = (max(word[1] for word in words) - min(word[0] for word in words)) / 30.0
        gaps = [max(0.0, second[0] - first[1]) for first, second in zip(words, words[1:])]
        longest_gap = max(gaps) if gaps else 30.0
    else:
        speech_coverage, longest_gap = 0.0, 30.0
    return {
        "words": len(tokens),
        "unique_content_words": len(counts),
        "unique_ratio": round(unique_ratio, 3),
        "repetition": round(repetition, 3),
        "top3_ratio": round(top3, 3),
        "excitement": excitement,
        "laughter": laughter,
        "gameplay_terms": gameplay_terms,
        "exclamations": exclamations,
        "speech_coverage": round(speech_coverage, 3),
        "longest_gap_seconds": round(longest_gap, 2),
    }


def interest_score(features, audio_rank, motion):
    """0-10 score: what to say + how it is said + visible activity, minus dead time."""
    positive = (
        0.25 * audio_rank
        + 0.20 * min(1.0, features["unique_ratio"] / 0.75)
        + 0.12 * min(1.0, features["excitement"] / 3.0)
        + 0.10 * min(1.0, features["laughter"] / 2.0)
        + 0.08 * min(1.0, features["gameplay_terms"] / 3.0)
        + 0.07 * min(1.0, features["exclamations"] / 3.0)
        + 0.08 * min(1.0, motion / 60.0)
        + 0.10 * min(1.0, features["speech_coverage"] / 0.85)
    )
    penalty = (
        0.25 * max(0.0, features["repetition"] - 0.18)
        + 0.15 * max(0.0, features["top3_ratio"] - 0.45)
        + 0.12 * max(0.0, 0.55 - features["speech_coverage"])
        + 0.10 * min(1.0, features["longest_gap_seconds"] / 5.0)
    )
    return round(max(0.0, positive - penalty) * 10.0, 2)


def existing_ranges(extra_exclude, source_key=None, source_url=None, campaign_id=None):
    """Collect windows to avoid, isolated by campaign and source.

    With no filters this keeps the legacy "all clips" behaviour for callers that
    want a global view. The campaign CLI always passes the filters, so a Kreek
    clip can no longer exclude a Dylan moment (or vice versa).
    """
    ranges = []
    folders = (config.CANDIDATES, config.FINAL)
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    row = json.load(handle)
            except (OSError, ValueError):
                continue
            if campaign_id and storage.infer_campaign(row, os.path.splitext(name)[0]) != campaign_id:
                continue
            src = row.get("source") or {}
            if source_key and src.get("key") != source_key:
                continue
            if source_url and src.get("url") != source_url:
                continue
            start, end = row.get("source_start"), row.get("source_end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                ranges.append((float(start), float(end), name))
    for item in extra_exclude or []:
        start, end = item.split("-", 1)
        ranges.append((float(start), float(end), "user exclusion"))
    return ranges


def overlaps_existing(start, end, ranges, tolerance=5.0):
    for other_start, other_end, name in ranges:
        if min(end, other_end) - max(start, other_start) > -tolerance:
            return name
    return None


def bucket_motion(start, end, timeline):
    rows = [row for row in timeline.get("buckets", [])
            if row["end"] > start and row["start"] < end]
    if not rows:
        return 0.0
    return float(np.mean([row["motion_median"] for row in rows]))


def transcribe_window(audio_path, start, length, work_name):
    wav = os.path.join(config.WORK, work_name + ".wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.2f}", "-i", os.path.abspath(audio_path),
                    "-t", f"{length:.2f}", "-vn", "-ac", "1", "-ar", "16000", wav],
                   check=True, capture_output=True, text=True)
    try:
        words = captions.transcribe_words(clip.load_audio(wav), "en")
    finally:
        if os.path.isfile(wav):
            os.remove(wav)
    return list(words)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--campaign", help="campaign id (default: GTA_CAMPAIGN or kreekcraft)")
    parser.add_argument("--start", type=float, default=0.0,
                        help="start of the confirmed gameplay range")
    parser.add_argument("--timeline", default=None)
    parser.add_argument("--clip-len", type=float, default=config.DEFAULT_CLIP_LEN)
    parser.add_argument("--lead-in", type=float, default=config.DEFAULT_LEAD_IN)
    parser.add_argument("--top-audio", type=int, default=60)
    parser.add_argument("--transcribe", type=int, default=30)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=1.5)
    parser.add_argument("--exclude", action="append", default=[],
                        help="source range START-END to exclude (repeatable)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    config.ensure_dirs()
    try:
        profile = config.active_profile(args.campaign)
        src = source_module.resolve(url=args.url, campaign_id=profile.id)
        timeline_file = analyze.timeline_path(src, args.timeline, profile.id)
        timeline = analyze.load_gameplay_timeline(timeline_file, profile.id)
        audio = source_module.prepare_audio(src)
        levels = analyze.audio_levels(audio, args.start)
        rows = analyze.find_candidates(levels, args.start, src.duration, args.clip_len,
                                       args.top_audio, args.min_score, args.lead_in,
                                       config.DEFAULT_STEP)
    except (ValueError, RuntimeError, OSError) as error:
        sys.exit(str(error))

    excluded = existing_ranges(args.exclude, source_key=src.key,
                               source_url=src.url, campaign_id=profile.id)
    eligible = []
    for row in rows:
        stats = gameplay.window_stats(row["start"], row["end"], timeline)
        if not gameplay.is_gameplay_window(row["start"], row["end"], timeline,
                                           min_coverage=95.0, margin=2.0):
            continue
        previous = overlaps_existing(row["start"], row["end"], excluded)
        if previous:
            row["excluded_by"] = previous
            continue
        row["gameplay"] = stats
        row["visual_motion"] = round(bucket_motion(row["start"], row["end"], timeline), 2)
        eligible.append(row)

    # Audio score is only a weak prior; normalise it to a rank percentile.
    ordered = sorted(eligible, key=lambda row: row["score"])
    for index, row in enumerate(ordered):
        row["audio_rank"] = index / max(1, len(ordered) - 1)
    ordered.sort(key=lambda row: (row["score"], row["start"]), reverse=True)
    ordered = ordered[:args.transcribe]

    ranked = []
    for row in ordered:
        words = transcribe_window(audio, row["start"], args.clip_len, f"select_{src.key}_{row['start']:.0f}")
        text = " ".join(word[2] for word in words).strip()
        features = transcript_features(text, words)
        if features["words"] < 8 or features["unique_content_words"] < 5:
            continue
        score = interest_score(features, row["audio_rank"], row["visual_motion"])
        ranked.append({**row, "audio_score": row["score"], "interest_score": score,
                       "transcript": text, "features": features})
    ranked.sort(key=lambda row: (row["interest_score"], row["score"]), reverse=True)

    chosen = []
    for row in ranked:
        if any(abs(row["start"] - item["start"]) < args.clip_len for item in chosen):
            continue
        chosen.append(row)
        if len(chosen) >= args.top:
            break
    for rank, row in enumerate(chosen, 1):
        row["rank"] = rank
        row["score"] = row["interest_score"]

    out = os.path.abspath(args.out or os.path.join(
        config.CANDIDATES, f"{profile.clip_prefix}-{src.key}-alternatives.json"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "select",
        "campaign_id": profile.id,
        "source": {"key": src.key, "url": src.url, "title": src.title, "channel": src.channel,
                   "platform": source_module.platform_name(src.info),
                   "upload_date": src.info.get("upload_date")},
        "timeline": timeline_file,
        "method": "audio-window + verified-gameplay gate + transcript-interest ranking",
        "clip_len": args.clip_len,
        "excluded_ranges": excluded,
        "audio_windows": len(rows),
        "gameplay_eligible": len(eligible),
        "transcribed": len(ordered),
        "candidates": chosen,
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    print(f"audio windows={len(rows)} gameplay-eligible={len(eligible)} transcribed={len(ordered)}")
    for row in chosen:
        print(f"  #{row['rank']} {row['start']:.2f}-{row['end']:.2f}s "
              f"score={row['interest_score']} audio={row['audio_score']} "
              f"coverage={row['gameplay']['gameplay_coverage_percentage']}%")
        print(f"     {row['transcript'][:180]}")
    print("alternatives:", out)
    return report


if __name__ == "__main__":
    main()
