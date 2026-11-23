"""Data model and reusable rule checks for campaign profiles.

Profiles are plain data. Every campaign-specific decision (caption, logo,
platforms, source policy, manual review) lives here so shared pipeline code can
ask a profile what is required instead of carrying creator-specific branches.

These checks are pure functions over metadata/dicts. They never touch the
network, credentials, or files, so both validation and publishing preflight can
use exactly the same rules.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)


def rule_check(name: str, passed: bool, detail: Any = "", manual_review: bool = False) -> dict:
    """One compliance result. ``manual_review`` marks checks automation cannot prove."""
    return {
        "name": name,
        "passed": bool(passed),
        "detail": str(detail),
        "manual_review": bool(manual_review),
    }


@dataclass(frozen=True)
class SourcePolicy:
    platforms: tuple[str, ...] = ("youtube",)
    allowed_channels: tuple[str, ...] = ()
    forbidden_channels: tuple[str, ...] = ()
    topic: str = "GTA VI gameplay"
    start_date: str | None = None          # YYYY-MM-DD; marathon/series start
    # True: a missing start_date fails validation instead of skipping the check.
    start_date_required: bool = False
    require_url: bool = True
    allow_local_tests: bool = True
    reject_unofficial_reuploads: bool = True
    # Source-specific storyboard template window. Only set for a campaign whose
    # pre-game screen was human-confirmed; None disables template matching.
    waiting_template_end: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoRules:
    width: int = 1080
    height: int = 1920
    min_duration: float = 5.0
    max_duration: float = 60.0
    layout: str = "fit"
    caption_language: str = "English"
    auto_subtitles_allowed: bool = True
    no_added_watermarks: bool = False
    no_third_party_branding: bool = False
    original_branding_allowed: bool = True
    # Stacked-layout crops as (x, y, w, h) fractions of the source frame. Owned
    # by the profile so no other campaign can inherit them.
    stacked_top_region: tuple[float, float, float, float] | None = None
    stacked_top_overrides: tuple[tuple[str, tuple[float, float, float, float]], ...] = ()
    stacked_bottom_region: tuple[float, float, float, float] | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditingRules:
    logo_required: bool = False
    logo_env: str | None = None
    logo_asset: str | None = None          # repo-relative asset path, if provided
    max_reposts: int | None = None
    preserve_context: bool = True
    no_ai_media: bool = True
    no_fabricated_reactions: bool = True
    no_near_duplicates: bool = True
    subject_focus_required: bool = False
    max_subject_absence_seconds: float | None = None
    min_subject_presence_ratio: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptionRules:
    exact_phrase: str | None = None
    # Text every caption must contain (e.g. a creator link), checked
    # case-insensitively. Allowed even when urls_forbidden is False.
    required_substrings: tuple[str, ...] = ()
    # Caption lines the generator rotates through; each must contain every
    # required substring (enforced by tests).
    templates: tuple[str, ...] = ()
    required_hashtags: tuple[str, ...] = ()
    forbidden_hashtags: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    urls_forbidden: bool = False
    language: str = "English"
    accurate_description_required: bool = True
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThumbnailRules:
    required: bool = True
    unique_per_clip: bool = True
    from_source_frame: bool = True
    no_ai_imagery: bool = True
    accurate_representation_required: bool = True
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishingRules:
    platforms: tuple[str, ...] = ()
    account_env: dict[str, str] = field(default_factory=dict)
    require_public_days: int | None = None
    likes_visible_required: bool = False
    min_engagement_rate: float | None = None
    min_tier1_audience_pct: float | None = None
    tier1_countries: tuple[str, ...] = ()
    no_engagement_manipulation: bool = True
    # False: zernio_publish refuses --unattended for this campaign outright.
    allow_unattended: bool = True
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignProfile:
    id: str
    name: str
    clip_prefix: str
    source: SourcePolicy
    video: VideoRules
    editing: EditingRules
    captions: CaptionRules
    thumbnails: ThumbnailRules
    publishing: PublishingRules
    manual_review: tuple[str, ...] = ()
    operational_guides: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    # ---- rule helpers (shared by validation and publishing preflight) ----

    def text_fields(self, meta: dict) -> str:
        return " ".join(str(meta.get(key, "") or "") for key in (
            "title", "caption_text", "youtube_description", "instagram_caption",
            "tiktok_caption", "x_caption", "twitter_caption"))

    def campaign_checks(self, *values: str | None) -> list[dict]:
        """Every stamped campaign id must be this profile's id (or absent)."""
        stamped = [str(value) for value in values if value]
        return [rule_check(
            "campaign_id_matches", bool(stamped) and all(value == self.id for value in stamped),
            f"expected {self.id}, found {stamped}" if stamped else "no campaign stamp")]

    def caption_checks(self, meta: dict) -> list[dict]:
        """Caption rules for this campaign only. Never reads another profile."""
        text = self.text_fields(meta)
        checks = []
        if self.captions.exact_phrase:
            checks.append(rule_check(
                "exact_campaign_phrase", self.captions.exact_phrase in text,
                self.captions.exact_phrase))
        if self.captions.required_substrings:
            absent = [item for item in self.captions.required_substrings
                      if item.lower() not in text.lower()]
            checks.append(rule_check(
                "required_caption_text_present", not absent,
                f"missing: {absent}" if absent else "all present"))
        missing = [tag for tag in self.captions.required_hashtags if tag not in text]
        checks.append(rule_check(
            "required_hashtags_present", not missing,
            f"missing: {missing}" if missing else "all present"))
        wrong = [tag for tag in self.captions.forbidden_hashtags if tag in text]
        checks.append(rule_check(
            "foreign_hashtags_absent", not wrong,
            f"foreign tags: {wrong}" if wrong else "none"))
        borrowed = [phrase for phrase in self.captions.forbidden_phrases
                    if phrase.lower() in text.lower()]
        checks.append(rule_check(
            "foreign_caption_phrase_absent", not borrowed,
            f"foreign phrases: {borrowed}" if borrowed else "none"))
        if self.captions.urls_forbidden:
            urls = URL_PATTERN.findall(text)
            checks.append(rule_check("no_urls_in_captions", not urls,
                                     f"found {urls}" if urls else "none"))
        if self.captions.language:
            stated = meta.get("caption_language") or self.captions.language
            checks.append(rule_check(
                "caption_language", stated == self.captions.language,
                f"{stated} (requires {self.captions.language})"))
        return checks

    def platform_checks(self, platforms: Iterable[str]) -> list[dict]:
        selected = list(platforms)
        allowed = set(self.publishing.platforms)
        disallowed = [name for name in selected if name not in allowed]
        return [rule_check(
            "platforms_allowed_for_campaign", not disallowed,
            f"disallowed: {disallowed}" if disallowed else ", ".join(selected) or "none")]

    def source_checks(self, src: dict, test: bool = False) -> list[dict]:
        checks = []
        if test and self.source.allow_local_tests:
            checks.append(rule_check("source_authorized", True,
                                     "local test source; not publishable"))
            return checks
        channel = str(src.get("channel") or "").strip().lower()
        allowed = {item.lower() for item in self.source.allowed_channels}
        checks.append(rule_check(
            "source_authorized", bool(src.get("url")) and channel in allowed,
            f"{src.get('channel') or 'unknown'} / {src.get('url') or 'no URL'}"))
        forbidden = {item.lower() for item in self.source.forbidden_channels}
        clash = sorted(forbidden & {channel}) if channel else []
        checks.append(rule_check(
            "foreign_creator_source_absent", not clash,
            f"foreign channels: {clash}" if clash else "none"))
        source_platform = str(src.get("platform") or "").lower()
        if self.source.platforms:
            checks.append(rule_check(
                "source_platform_allowed",
                source_platform in self.source.platforms,
                source_platform or "not stated in metadata; manual review",
                manual_review=not source_platform))
        if not self.source.start_date and self.source.start_date_required:
            checks.append(rule_check(
                "source_within_campaign_window", False,
                "campaign cutoff date not configured in the profile yet"))
        if self.source.start_date:
            date = str(src.get("upload_date") or "")
            if len(date) == 8 and date.isdigit():
                normalised = f"{date[:4]}-{date[4:6]}-{date[6:]}"
                checks.append(rule_check(
                    "source_within_campaign_window", normalised >= self.source.start_date,
                    f"{normalised} (campaign starts {self.source.start_date})"))
            else:
                checks.append(rule_check(
                    "source_within_campaign_window", False,
                    "stream date unavailable; operator must confirm it belongs to the marathon",
                    manual_review=True))
        return checks

    def video_checks(self, info: dict) -> list[dict]:
        """``info`` is ffprobe JSON (streams + format)."""
        streams = {item.get("codec_type"): item for item in info.get("streams", [])}
        video = streams.get("video", {})
        duration = float(info.get("format", {}).get("duration") or 0.0)
        size = (video.get("width"), video.get("height"))
        return [
            rule_check("resolution_1080x1920",
                       size == (self.video.width, self.video.height), f"{size[0]}x{size[1]}"),
            rule_check("duration_in_range",
                       self.video.min_duration <= duration <= self.video.max_duration,
                       f"{duration:.2f}s ({self.video.min_duration}-{self.video.max_duration}s)"),
            rule_check("audio_stream_present", "audio" in streams,
                       "audio stream present" if "audio" in streams else "no audio stream"),
        ]

    def editing_checks(self, report: dict) -> list[dict]:
        checks = []
        if self.editing.logo_required:
            logo = report.get("logo_overlay")
            checks.append(rule_check(
                "logo_overlay_applied", bool(logo) and bool(report.get("logo_file")),
                report.get("logo_file") or "missing"))
        if self.video.no_added_watermarks:
            checks.append(rule_check(
                "no_added_watermark",
                not report.get("added_watermark") and not report.get("logo_overlay"),
                report.get("added_watermark") or report.get("logo_overlay") or "none"))
        if self.video.no_third_party_branding:
            checks.append(rule_check(
                "no_added_third_party_branding",
                not report.get("added_branding") and not report.get("logo_overlay"),
                report.get("added_branding") or report.get("logo_overlay") or "none"))
        if self.editing.no_ai_media:
            ai_used = bool(report.get("ai_generated_media") or report.get("ai_generated_voice"))
            checks.append(rule_check(
                "no_ai_generated_media", not ai_used,
                "declared original source frames and voice" if not ai_used
                else "AI-generated media or voice declared"))
        if self.editing.no_fabricated_reactions:
            checks.append(rule_check(
                "no_fabricated_reactions", not report.get("fabricated_reaction"),
                "source audio retained" if not report.get("fabricated_reaction")
                else "fabricated reaction declared"))
        return checks

    def thumbnail_checks(self, record: dict | None, known: Iterable[dict] = ()) -> list[dict]:
        if not self.thumbnails.required:
            return []
        record = record or {}
        path = record.get("path")
        checks = [rule_check("thumbnail_present", bool(path), path or "missing")]
        if self.thumbnails.from_source_frame:
            checks.append(rule_check(
                "thumbnail_from_source_frame", bool(record.get("from_source_frame")),
                "generated from a decoded clip frame" if record.get("from_source_frame")
                else "provenance not recorded"))
        if self.thumbnails.unique_per_clip:
            digest = record.get("sha256")
            clash = [other.get("clip_id") for other in known
                     if other.get("sha256") and digest and other["sha256"] == digest
                     and other.get("clip_id") != record.get("clip_id")]
            checks.append(rule_check("thumbnail_unique", not clash,
                                     f"reused by {clash}" if clash else "unique"))
        return checks
