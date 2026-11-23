"""Campaign B: Dylan Page GTA 6 Marathon (from 2026-11-19).

Accepted sources are marathon livestreams, VODs and clips from Dylan Page's GTA VI
marathon. Dylan must remain the main focus; no added watermark or third-party
branding, strict 1080x1920 vertical, English captions, a unique real-frame
thumbnail per clip, and #DylanPage in every caption.

X (Twitter) is accepted here but not for KreekCraft. The KreekCraft caption
sentence and hashtags are explicitly forbidden for this campaign.

Face analysis in this project measures visible-person presence only. It does not
verify identity, so uncertain focus results are flagged for manual review and
never auto-approved.
"""
from campaigns.base import (
    CampaignProfile, CaptionRules, EditingRules, PublishingRules,
    SourcePolicy, ThumbnailRules, VideoRules,
)

KREEK_PHRASE = "Watch KreekCraft on YouTube and Twitch"
KREEK_HASHTAGS = ("#GTA6", "#KreekCraft", "#GrandTheftAutoVI")

PROFILE = CampaignProfile(
    id="dylan_page",
    name="Dylan Page GTA 6 Marathon",
    clip_prefix="dylan",
    source=SourcePolicy(
        platforms=("youtube", "twitch"),
        allowed_channels=("dylan page", "dylanpage"),
        forbidden_channels=("kreek", "kreekcraft"),
        topic="Dylan Page GTA VI marathon streams, VODs and clips",
        waiting_template_end=None,
        start_date="2026-11-19",
        notes=(
            "Reject unrelated Dylan footage, other creators' edits and any source "
            "outside the marathon starting 2026-11-19. Keep original timestamps.",
        ),
    ),
    video=VideoRules(
        layout="adaptive-stacked",
        caption_language="English",
        auto_subtitles_allowed=True,
        no_added_watermarks=True,
        no_third_party_branding=True,
        original_branding_allowed=True,
        # Operator-confirmed on 1920x1080 sources (9:8 regions, shown whole):
        # top = webcam window + stream timer (1316,0,604,537); bottom = gameplay
        # ending just before the webcam (101,0,1215,1080).
        stacked_top_region=(1316 / 1920, 0.0, 604 / 1920, 537 / 1080),
        stacked_top_overrides=(
            # "120 Hours Marathon Best Moments" (1200,0,640,569). Excluded from the
            # campaign set: its webcam moves between edits; burned-in subtitles.
            ("i1zUT_gKQzA", (1200 / 1920, 0.0, 640 / 1920, 569 / 1080)),
        ),
        stacked_bottom_region=(101 / 1920, 0.0, 1215 / 1920, 1.0),
        notes=(
            "Strict 9:16 vertical. A fixed upper panel shows the stream's webcam "
            "window and timer without panning; a lower panel shows gameplay that "
            "stops just before the webcam, so the face is not shown twice. "
            "The verified fit layout is the fallback when no confident face is detected. "
            "Logos already in the original footage are allowed; no added watermarks or "
            "third-party branding.",
        ),
    ),
    editing=EditingRules(
        logo_required=False,
        subject_focus_required=True,
        max_subject_absence_seconds=6.0,
        min_subject_presence_ratio=0.7,
        preserve_context=True,
        no_ai_media=True,
        no_fabricated_reactions=True,
        no_near_duplicates=True,
        notes=(
            "Clips where Dylan only appears in the introduction are rejected. "
            "No collab posts, fake reactions, AI footage/voices or engagement manipulation.",
        ),
    ),
    captions=CaptionRules(
        required_hashtags=("#DylanPage",),
        forbidden_hashtags=KREEK_HASHTAGS,
        forbidden_phrases=(KREEK_PHRASE,),
        language="English",
        notes=("English only; captions must accurately describe the actual clip.",),
    ),
    thumbnails=ThumbnailRules(
        notes=("Every clip needs its own thumbnail, generated from a real clip frame.",),
    ),
    publishing=PublishingRules(
        platforms=("tiktok", "instagram", "twitter", "youtube"),
        account_env={
            "tiktok": "ZERNIO_TIKTOK_ACCOUNT_ID",
            "instagram": "ZERNIO_INSTAGRAM_ACCOUNT_ID",
            "twitter": "ZERNIO_X_ACCOUNT_ID",
            "youtube": "ZERNIO_YOUTUBE_ACCOUNT_ID",
        },
        notes=("The Zernio platform key for X/Twitter is 'twitter'.",),
    ),
    manual_review=(
        "Dylan remains the main focus; no intro-only or long-absence clips",
        "no added watermark or third-party branding (original logos allowed)",
        "English captions and subtitles accurately describe the clip",
        "unique thumbnail accurately represents this clip",
        "no fabricated reactions, AI footage or AI voices",
        "no misleading edits, context removal, reposted edits, collab posts, botting or bought engagement",
    ),
    notes=("AI-generated footage, voices or fabricated reactions can cause a permanent campaign ban.",),
)
