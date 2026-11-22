"""Publishing preflight: campaign, video, caption, thumbnail, platform, approval.

This runs before any network call. It reuses the same profile rule helpers as
campaign validation so a clip cannot be validated under one campaign's rules and
published under another's. It never sends a post and never touches engagement.
"""
import os

from campaigns.base import rule_check
from shared import storage, thumbnails


VIDEO_CHECK_NAMES = ("resolution_1080x1920", "duration_in_range", "audio_stream_present")


def preflight(metadata: dict, profile, platforms, name: str = "") -> list[dict]:
    checks = []
    try:
        campaign_id = storage.require_campaign(metadata, name, expected=profile.id)
        checks.append(rule_check("campaign_matches_profile", True, campaign_id))
    except ValueError as error:
        checks.append(rule_check("campaign_matches_profile", False, str(error)))

    validation = metadata.get("validation") or {}
    checks.append(rule_check(
        "validation_passed", validation.get("passed") is True,
        "validation report passed" if validation.get("passed") is True
        else "no passing validation report"))
    recorded = {item.get("name"): bool(item.get("passed"))
                for item in validation.get("checks", []) if isinstance(item, dict)}
    legacy_ok = all(name in recorded for name in ("resolution_1080x1920", "duration_5_to_60s"))
    video_ok = all(recorded.get(name, False) for name in VIDEO_CHECK_NAMES) or legacy_ok
    checks.append(rule_check("video_validated", video_ok,
                             "recorded validation covers video format/audio"
                             if video_ok else "video checks missing or failed"))

    review = metadata.get("review") or {}
    approved = metadata.get("approved") is True and (
        not isinstance(review, dict) or review.get("status") == "approved")
    checks.append(rule_check("explicit_manual_approval", approved,
                             "approved by operator" if approved else "not explicitly approved"))
    checks.append(rule_check(
        "not_rejected_or_test", not metadata.get("rejected") and not metadata.get("test"),
        "rejected" if metadata.get("rejected") else "test clip" if metadata.get("test") else "ok"))

    checks.extend(profile.caption_checks(metadata))
    checks.extend(profile.thumbnail_checks(metadata.get("thumbnail"),
                                           storage.known_thumbnails()))
    checks.extend(thumbnails.thumbnail_file_checks(metadata.get("thumbnail")))
    checks.extend(profile.platform_checks(platforms))

    missing = [env for platform in platforms
               for env in [profile.publishing.account_env.get(platform)]
               if env and not os.environ.get(env)]
    checks.append(rule_check(
        "platform_accounts_configured", not missing,
        f"not configured: {', '.join(missing)}" if missing else "all selected accounts configured"))
    return checks


def assert_ready(metadata: dict, profile, platforms, name: str = "") -> list[dict]:
    checks = preflight(metadata, profile, platforms, name)
    failed = [item for item in checks if not item["passed"]]
    if failed:
        detail = "; ".join(f"{item['name']}: {item['detail']}" for item in failed)
        raise ValueError("publishing preflight failed: " + detail)
    return checks
