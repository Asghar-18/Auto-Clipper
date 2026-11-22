"""Stage 4 CLI: validate one candidate and optionally promote it for review.

This never publishes. Approval stays a manual step.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import cv2
import numpy as np

from . import config, metadata, validate
from shared import storage, thumbnails as thumbnail_module


def candidate_contact_sheet(video, report, out_path, columns=4, rows=3):
    """Sample the rendered clip so a human can review gameplay and logo placement."""
    capture = cv2.VideoCapture(os.path.abspath(video))
    if not capture.isOpened():
        return None
    duration = float(report.get("duration") or 0.0)
    count = columns * rows
    step = max(0.5, duration / count)
    tiles = []
    for index in range(count):
        moment = min(duration - 0.05, index * step)
        capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        tile = cv2.resize(frame, (216, 384))
        source_time = float(report.get("source_start") or 0.0) + moment
        label = f"{moment:.1f}s | src {int(source_time // 60):02d}:{int(source_time % 60):02d}"
        cv2.putText(tile, label, (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(tile, label, (6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
    capture.release()
    if not tiles:
        return None
    canvas = np.zeros((rows * 384, columns * 216, 3), dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row, col = divmod(index, columns)
        canvas[row * 384:(row + 1) * 384, col * 216:(col + 1) * 216] = tile
    cv2.imwrite(out_path, canvas)
    return out_path


def load_candidate(path):
    """Load one render JSON and return its name, report and source paths."""
    candidate = os.path.abspath(path)
    with open(candidate, encoding="utf-8") as handle:
        report = json.load(handle)
    name = os.path.splitext(os.path.basename(candidate))[0]
    folder = os.path.dirname(candidate)
    paths = {
        "video": os.path.join(folder, report.get("video", name + ".mp4")),
        "srt": os.path.join(folder, report.get("srt", name + ".srt")),
    }
    return name, report, paths


def _final_paths(name, paths):
    return (
        os.path.join(config.FINAL, os.path.basename(paths["video"])),
        os.path.join(config.FINAL, os.path.basename(paths["srt"])),
        os.path.join(config.FINAL, name + ".json"),
    )


def _existing_final_names():
    if not os.path.isdir(config.FINAL):
        return set()
    return {os.path.splitext(name)[0] for name in os.listdir(config.FINAL)
            if name.lower().endswith(".json")}


def _promote_one(name, report, paths, enriched, validation):
    """Copy one passing candidate into output/final without overwriting anything."""
    final_video, final_srt, final_json = _final_paths(name, paths)
    existing = [path for path in (final_video, final_srt, final_json) if os.path.exists(path)]
    if existing:
        raise FileExistsError("refusing to overwrite existing final clip: " + ", ".join(existing))
    shutil.copy2(paths["video"], final_video)
    shutil.copy2(paths["srt"], final_srt)
    integrity = enriched.get("integrity") or {}
    if integrity.get("content_sha256") and validate.sha256_file(final_video) != integrity["content_sha256"]:
        raise ValueError("promoted MP4 failed integrity verification; refusing to record final metadata")
    if integrity.get("srt_sha256") and validate.sha256_file(final_srt) != integrity["srt_sha256"]:
        raise ValueError("promoted SRT failed integrity verification; refusing to record final metadata")
    record = dict(enriched)
    record["clip_id"] = name
    record["video_path"] = os.path.abspath(final_video)
    record["srt_path"] = os.path.abspath(final_srt)
    with open(final_json, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    return final_video, final_srt, final_json


def validate_candidate(path, campaign_id=None):
    """Validate one candidate and write its metadata/validation reports."""
    name, report, paths = load_candidate(path)
    stamped = report.get("campaign_id") or (report.get("campaign") or {}).get("id")
    inferred = stamped or storage.infer_campaign(report, name)
    if campaign_id and inferred and inferred != campaign_id:
        raise ValueError(
            f"candidate belongs to campaign {inferred!r}, not {campaign_id!r}")
    effective = campaign_id or inferred
    if not effective:
        raise ValueError(
            "candidate has no unambiguous campaign; pass --campaign or stamp the render JSON")
    meta = metadata.build(report, report.get("source", {}), effective)
    profile = config.active_profile(meta["campaign_id"])
    timeline = None
    if not report.get("test") and report.get("source", {}).get("url"):
        from .analyze import load_gameplay_timeline
        src_key = report["source"]["key"]
        timeline_file = config.timeline_path(src_key, profile.id)
        timeline = load_gameplay_timeline(timeline_file, profile.id)
    contact = candidate_contact_sheet(paths["video"], report, os.path.join(
        config.THUMBNAILS, name + "-contact.jpg"))
    # Every clip gets a real-frame thumbnail before validation/publishing.
    meta["thumbnail"] = thumbnail_module.generate_thumbnail(paths["video"], name)
    validation = validate.validate(report, meta, paths, config.FINAL,
                                   current_name=name, timeline=timeline,
                                   campaign_id=profile.id)
    validation_path = validate.write_report(validation, name)
    enriched = dict(report)
    enriched.update(meta)
    enriched["validation"] = validation
    enriched["contact_sheet"] = contact
    enriched["gameplay"] = validation.get("gameplay", {})
    enriched["integrity"] = validation.get("integrity")
    # Review and approval are independent and always start unset for a new final clip.
    enriched.setdefault("review", {
        "status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "notes": "",
    })
    enriched.setdefault("approved", False)
    enriched.setdefault("approved_by", None)
    enriched.setdefault("approved_at", None)
    enriched.setdefault("rejected", False)
    enriched.setdefault("rejection_reason", None)
    enriched.setdefault("posted", {})
    metadata_path = os.path.join(config.METADATA, name + ".json")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2, ensure_ascii=False)
    return {
        "name": name,
        "report": report,
        "paths": paths,
        "meta": meta,
        "validation": validation,
        "validation_path": validation_path,
        "enriched": enriched,
        "metadata_path": metadata_path,
    }


def _print_result(result):
    validation = result["validation"]
    print("campaign:", result["meta"]["campaign_id"])
    print("title:", result["meta"]["title"])
    print("caption:", result["meta"]["caption_text"].replace("\n", " | "))
    print("checks:", sum(1 for item in validation["checks"] if item["passed"]),
          "/", len(validation["checks"]), "passed")
    for item in validation["warnings"]:
        print("  FAIL", item["name"], "-", item["detail"])
    print("validation:", result["validation_path"])
    print("metadata:", result["metadata_path"])
    if result["enriched"].get("contact_sheet"):
        print("contact sheet:", result["enriched"]["contact_sheet"])


def _selected_paths(args):
    """Return unique absolute candidate JSON paths from repeatable selectors."""
    selected = list(args.candidate or [])
    for list_path in args.candidates_from or []:
        with open(os.path.abspath(list_path), encoding="utf-8") as handle:
            selected.extend(line.strip() for line in handle
                            if line.strip() and not line.lstrip().startswith("#"))
    if args.select:
        if not os.path.isdir(args.select):
            sys.exit(f"Selection directory not found: {args.select}")
        selected.extend(os.path.join(args.select, name)
                        for name in sorted(os.listdir(args.select))
                        if name.lower().endswith(".json"))
    if not selected:
        sys.exit("Select at least one candidate with --candidate, --candidates-from, or --select.")
    seen, paths = set(), []
    for path in selected:
        absolute = os.path.abspath(path)
        if absolute not in seen:
            seen.add(absolute)
            paths.append(absolute)
    return paths


def _metadata_value(data, name):
    """Read an identity field whether it is top-level or nested under source."""
    if name in data:
        return data[name]
    source = data.get("source") or {}
    return source.get({"source_key": "key", "source_url": "url"}.get(name, name))


def verify_clip_integrity(path, data=None):
    """Prove the MP4/SRT still match the exact candidate that was validated.

    Raises ValueError if the media was replaced, the metadata describes a
    different candidate, or no validation-time integrity record exists.
    """
    path = os.path.abspath(path)
    if not path.lower().endswith(".json"):
        path += ".json"
    if data is None:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    stem = os.path.splitext(os.path.basename(path))[0]
    folder = os.path.dirname(path)
    video_path = os.path.join(folder, stem + ".mp4")
    srt_path = os.path.join(folder, stem + ".srt")
    if not os.path.isfile(video_path):
        raise ValueError(f"expected MP4 not found: {video_path}")

    validation_path = os.path.join(config.METADATA, stem + "-validation.json")
    if not os.path.isfile(validation_path):
        raise ValueError(f"validation report not found: {validation_path}")
    with open(validation_path, encoding="utf-8") as handle:
        validation = json.load(handle)
    recorded = validation.get("integrity") or {}
    if not recorded.get("content_sha256"):
        raise ValueError("validation report has no integrity record; re-run campaign.finalize validation")
    campaign_id = (data.get("campaign_id") or (data.get("campaign") or {}).get("id"))
    if recorded.get("campaign_id") and campaign_id and recorded["campaign_id"] != campaign_id:
        raise ValueError("clip campaign does not match the campaign that was validated")

    # 1. The metadata must describe the same source window that was validated.
    for key in ("source_key", "source_url", "source_start", "source_end"):
        expected, actual = recorded.get(key), _metadata_value(data, key)
        if expected is not None and actual is not None and expected != actual:
            raise ValueError(f"metadata identity mismatch for {key}: "
                             f"metadata={actual!r} validated={expected!r}")

    # 2. The media filenames must be the ones recorded at validation.
    video_name = os.path.basename(video_path)
    if recorded.get("video") and recorded["video"] != video_name:
        raise ValueError(f"MP4 belongs to a different candidate: metadata says "
                         f"{recorded['video']}, found {video_name}")
    srt_name = os.path.basename(srt_path)
    if recorded.get("srt") and recorded["srt"] != srt_name:
        raise ValueError(f"SRT belongs to a different candidate: metadata says "
                         f"{recorded['srt']}, found {srt_name}")

    # 3. The media bytes must be unchanged since validation.
    actual_hash = validate.sha256_file(video_path)
    if actual_hash != recorded["content_sha256"]:
        raise ValueError(f"MP4 changed since validation; refusing approval "
                         f"(expected {recorded['content_sha256']}, got {actual_hash})")
    if recorded.get("srt_sha256") and os.path.isfile(srt_path):
        actual_srt = validate.sha256_file(srt_path)
        if actual_srt != recorded["srt_sha256"]:
            raise ValueError(f"SRT changed since validation; refusing approval "
                             f"(expected {recorded['srt_sha256']}, got {actual_srt})")

    # 4. A final-copy integrity stamp, if present, must agree with validation.
    stamped = data.get("integrity") or {}
    if stamped.get("content_sha256") and stamped["content_sha256"] != recorded["content_sha256"]:
        raise ValueError("final metadata integrity does not match validation report")

    # Stamp the verified record so publishing can re-check it independently.
    data["integrity"] = recorded
    return recorded


def review_clip(path, status, reviewer=None, notes=None, approve=False, reject=False):
    """Record independent human-review/approval state for one final clip."""
    path = os.path.abspath(path)
    if not path.lower().endswith(".json"):
        path += ".json"
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("rejected") and status != "rejected":
        raise ValueError("a rejected clip cannot be re-approved; generate a new candidate")
    if not data.get("validation", {}).get("passed", True):
        raise ValueError("clip validation did not pass; cannot approve or mark reviewed")
    verify_clip_integrity(path, data)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["review"] = {
        "status": status,
        "reviewed_by": reviewer,
        "reviewed_at": now if status in {"approved", "rejected"} else None,
        "notes": notes or "",
    }
    if approve:
        data["approved"] = True
        data["approved_by"] = reviewer
        data["approved_at"] = now
        data["rejected"] = False
        data["rejection_reason"] = None
    elif reject:
        data["approved"] = False
        data["approved_by"] = None
        data["approved_at"] = None
        data["rejected"] = True
        data["rejection_reason"] = notes or f"rejected during human review ({status})"
    else:
        data["approved"] = False
        data["approved_by"] = None
        data["approved_at"] = None
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    return path, data


def review_status(argv=None):
    parser = argparse.ArgumentParser(description="Record independent review/approval for one final clip.")
    parser.add_argument("clip", help="final clip JSON path or base name")
    parser.add_argument("--status", required=True,
                        choices=("pending", "approved", "rejected", "needs-changes"),
                        help="independent human-review result")
    parser.add_argument("--reviewer", help="name or initials of the reviewer")
    parser.add_argument("--notes", default="", help="review notes")
    parser.add_argument("--approve", action="store_true", help="explicitly allow publishing this clip")
    parser.add_argument("--reject", action="store_true", help="permanently exclude this clip from publishing")
    args = parser.parse_args(argv)
    config.ensure_dirs()
    if args.approve and args.status != "approved":
        sys.exit("--approve requires --status approved")
    if args.reject and args.status not in {"rejected", "needs-changes"}:
        sys.exit("--reject requires --status rejected or needs-changes")
    if args.approve and args.reject:
        sys.exit("Use either --approve or --reject, not both.")
    path = args.clip
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(config.FINAL, path)
    try:
        path, data = review_clip(path, args.status, args.reviewer, args.notes,
                                 args.approve, args.reject)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        sys.exit(str(error))
    print("review status:", data["review"]["status"])
    print("approved:", data.get("approved"), "rejected:", data.get("rejected"))
    print("updated:", path)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", help="campaign id (default: GTA_CAMPAIGN or kreekcraft)")
    parser.add_argument("--candidate", action="append", default=[],
                        help="render JSON from campaign.render (repeatable)")
    parser.add_argument("--candidates-from", action="append", default=[],
                        help="text file listing candidate JSON paths, one per line (repeatable)")
    parser.add_argument("--select", help="promote all passing *.json candidates in this directory")
    parser.add_argument("--promote", action="store_true",
                        help="copy passing candidates into output/final for independent review")
    parser.add_argument("--allow-existing", action="store_true",
                        help="skip names already in output/final instead of failing")
    args = parser.parse_args(argv)
    config.ensure_dirs()

    paths = _selected_paths(args)
    candidates = []
    for path in paths:
        try:
            result = validate_candidate(path, args.campaign)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            sys.exit(f"Could not validate {path}: {error}")
        candidates.append(result)
        _print_result(result)

    if not args.promote:
        print("Candidates not promoted. Nothing published.")
        return [item["validation"] for item in candidates]

    existing = _existing_final_names()
    promoted, skipped, failures = [], [], []
    for result in candidates:
        validation = result["validation"]
        if not validation["passed"]:
            failures.append((result["name"], "validation failed"))
            continue
        if result["name"] in existing:
            if args.allow_existing:
                skipped.append(result["name"])
                continue
            failures.append((result["name"], "a final clip with this name already exists"))
            continue
        try:
            video, _srt, _json = _promote_one(
                result["name"], result["report"], result["paths"],
                result["enriched"], validation)
        except FileExistsError as error:
            failures.append((result["name"], str(error)))
            continue
        existing.add(result["name"])
        promoted.append((result["name"], video))

    for name, reason in failures:
        print(f"NOT PROMOTED {name}: {reason}")
    for name in skipped:
        print(f"SKIPPED {name}: already exists in output/final")
    for name, video in promoted:
        print(f"promoted to: {video}")
    print(f"promoted {len(promoted)} of {len(candidates)} selected candidates. "
          "Each needs independent human review and explicit approval. Nothing published.")
    if failures:
        sys.exit(1)
    return [item["validation"] for item in candidates]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "review-status":
        review_status(sys.argv[2:])
    else:
        main()
