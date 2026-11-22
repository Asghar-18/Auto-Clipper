"""Stage 4: campaign-aware quality/compliance checks before manual promotion."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone

from . import config, gameplay
from campaigns.base import rule_check
from shared import focus as focus_module
from shared import storage
from shared import thumbnails as thumbnail_module

TIME_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")


def seconds(match, start):
    h, m, s, ms = (int(match.group(i + start)) for i in range(4))
    return h * 3600 + m * 60 + s + ms / 1000.0


def srt_intervals(path):
    intervals = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = TIME_RE.search(line)
            if match:
                intervals.append((seconds(match, 1), seconds(match, 5)))
    return intervals


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,codec_name",
         "-of", "json", os.path.abspath(path)],
        capture_output=True, text=True)
    if result.returncode:
        return {}
    return json.loads(result.stdout)


def check(name, passed, detail):
    return rule_check(name, passed, detail)


def sha256_file(path):
    """Return the SHA-256 of a file, streamed so large MP4s do not load into RAM."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integrity_record(report, paths):
    """Fingerprint the exact candidate that was validated, including media hashes."""
    video = paths.get("video")
    srt = paths.get("srt")
    src = report.get("source", {})
    if not video or not os.path.isfile(video):
        return None
    identity = {
        "campaign_id": report.get("campaign_id"),
        "source_key": src.get("key"),
        "source_url": src.get("url"),
        "source_start": report.get("source_start"),
        "source_end": report.get("source_end"),
        "video": os.path.basename(video),
        "srt": os.path.basename(srt) if srt else None,
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False)
    return {
        "candidate_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
        **identity,
        "content_sha256": sha256_file(video),
        "srt_sha256": sha256_file(srt) if srt and os.path.isfile(srt) else None,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def validate(report, meta, paths, final_dir=None, current_name=None, timeline=None,
             focus=None, known_thumbnails=None, campaign_id=None):
    """Return a validation dict; no file is moved or published here."""
    profile = config.active_profile(campaign_id or report.get("campaign_id")
                                    or meta.get("campaign_id"))
    checks = []
    checks.extend(profile.campaign_checks(
        campaign_id, report.get("campaign_id"), meta.get("campaign_id"),
        (report.get("campaign") or {}).get("id"),
        (meta.get("campaign") or {}).get("id")))
    if timeline and timeline.get("campaign_id"):
        checks.extend(profile.campaign_checks(timeline["campaign_id"]))
    src = report.get("source", {})
    video = paths["video"]
    info = probe(video)
    streams = {item.get("codec_type"): item for item in info.get("streams", [])}
    video_stream = streams.get("video", {})
    duration = float(info.get("format", {}).get("duration") or 0.0)
    checks.append(check("video_exists", os.path.isfile(video), video))
    checks.extend(profile.video_checks(info))
    checks.append(check("duration_5_to_60s",
                        5.0 <= duration <= 60.0, f"{duration:.2f}s"))
    stats = report.get("gameplay") or {}
    if timeline and not report.get("test"):
        stats = gameplay.window_stats(report.get("source_start", 0.0),
                                      report.get("source_end", 0.0), timeline)
    coverage = float(stats.get("gameplay_coverage_percentage", 0.0) or 0.0)
    raw_static = stats.get("static_screen_percentage", 100.0)
    static_pct = 100.0 if raw_static is None else float(raw_static)
    waiting = bool(stats.get("waiting_screen_detected", True))
    checks.append(check("gameplay_detected", coverage > 0 and bool(stats) and not report.get("test"),
                        f"coverage={coverage}%"))
    checks.append(check("gameplay_coverage_percentage", coverage >= 95.0,
                        f"{coverage}% (minimum 95%)"))
    checks.append(check("static_screen_percentage", static_pct <= 20.0,
                        f"{static_pct}% (maximum 20%)"))
    checks.append(check("waiting_screen_detected", not waiting,
                        "waiting/menu screen present" if waiting else "none"))
    srt = paths["srt"]
    intervals = srt_intervals(srt) if os.path.isfile(srt) else []
    checks.append(check("srt_present_nonempty", bool(intervals), f"{len(intervals)} cues"))
    overlaps = sum(1 for first, second in zip(intervals, intervals[1:]) if second[0] < first[1] - 0.002)
    checks.append(check("srt_no_overlap", overlaps == 0, f"{overlaps} overlap(s)"))
    checks.append(check("hook_in_first_2s", bool(intervals) and intervals[0][0] <= 1.0,
                        f"first cue at {intervals[0][0]:.2f}s" if intervals else "no cues"))

    # Campaign-specific caption, source and editing rules (no cross-profile leakage).
    checks.extend(profile.caption_checks(meta))
    checks.extend(profile.source_checks(src, bool(report.get("test"))))

    report_for_rules = report
    if profile.editing.logo_required and report.get("logo_overlay") and not report.get("logo_file"):
        report_for_rules = dict(report)
        try:
            report_for_rules["logo_file"] = config.logo_path(report.get("logo_overlay"), profile.id)
        except ValueError:
            pass
    checks.extend(profile.editing_checks(report_for_rules))

    focus_result = None
    if profile.editing.subject_focus_required:
        if focus is None:
            focus_result = focus_module.analyze_focus(video, 0.0, duration)
        else:
            focus_result = focus
        checks.extend(focus_module.focus_checks(focus_result, profile))

    thumb = meta.get("thumbnail")
    known = known_thumbnails if known_thumbnails is not None else storage.known_thumbnails()
    checks.extend(profile.thumbnail_checks(thumb, known))
    checks.extend(thumbnail_module.thumbnail_file_checks(thumb))

    transcript_words = [word.strip(".,!?\"'").lower() for word in (report.get("transcript") or "").split()]
    checks.append(check("transcript_present", bool(transcript_words),
                        f"{len(transcript_words)} words"))
    unique_words = len(set(transcript_words))
    checks.append(check("transcript_substance", len(transcript_words) >= 12 and unique_words >= 8,
                        f"{len(transcript_words)} words, {unique_words} unique"))
    duplicate = False
    duplicate_detail = "no existing final clips"
    if final_dir and os.path.isdir(final_dir):
        for name in os.listdir(final_dir):
            if not name.lower().endswith(".json"):
                continue
            if current_name and name == current_name + ".json":
                continue
            try:
                with open(os.path.join(final_dir, name), encoding="utf-8") as handle:
                    other = json.load(handle)
            except (OSError, ValueError):
                continue
            if storage.infer_campaign(other, name) != profile.id:
                continue
            other_src = other.get("source", {})
            if (other_src.get("url") == src.get("url")
                    and abs(float(other.get("source_start") or 0) - float(report.get("source_start") or 0)) < 20):
                duplicate = True
                duplicate_detail = "overlaps " + name
                break
    checks.append(check("not_near_duplicate", not duplicate, duplicate_detail))
    checks.append(check("requires_manual_approval", meta.get("approved") is False,
                        "approved stays False until you review it"))
    warnings = [item for item in checks if not item["passed"]]
    return {
        "stage": "validate",
        "campaign_id": profile.id,
        "campaign": {"id": profile.id, "name": profile.name},
        "video": os.path.basename(video),
        "passed": not warnings,
        "checks": checks,
        "warnings": warnings,
        "gameplay": stats,
        "focus": focus_result,
        "thumbnail": thumb,
        "integrity": integrity_record(report, paths),
        "operational_guides": [
            {"name": name, "status": "operator-supplied original required; not in repository"}
            for name in profile.operational_guides
        ],
        "human_review_still_required": list(profile.manual_review),
    }


def write_report(validation, name):
    os.makedirs(config.METADATA, exist_ok=True)
    path = os.path.join(config.METADATA, name + "-validation.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(validation, handle, indent=2, ensure_ascii=False)
    return path
