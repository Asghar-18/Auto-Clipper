"""Campaign A: KreekCraft GTA 6.

Only official KreekCraft GTA VI streams/VODs (YouTube or Twitch) are accepted.
The campaign logo must stay visible; the exact caption sentence and hashtags are
mandatory. X is deliberately not an accepted platform for this campaign.

Account-level requirements (public 30 days, visible likes, >=0.8% engagement,
>=40% Tier-1 audience) cannot be guaranteed by a local clipper. They are
recorded here and surfaced as operator/manual-review requirements, never as
automated pipeline claims. The warmup, approval and USA-targeting guides are not
present in this repository; their contents are not invented.
"""
from campaigns.base import (
    CampaignProfile, CaptionRules, EditingRules, PublishingRules,
    SourcePolicy, ThumbnailRules, VideoRules,
)

PHRASE = "Watch KreekCraft on YouTube and Twitch"
HASHTAGS = ("#GTA6", "#KreekCraft", "#GrandTheftAutoVI")

PROFILE = CampaignProfile(
    id="kreekcraft",
    name="KreekCraft GTA 6",
    clip_prefix="kreek",
    source=SourcePolicy(
        platforms=("youtube", "twitch"),
        allowed_channels=("kreek", "kreekcraft"),
        forbidden_channels=("dylan page", "dylanpage"),
        topic="official GTA VI streams and VODs from KreekCraft's YouTube/Twitch accounts",
        waiting_template_end=75.0,
        notes=(
            "Reject unofficial reuploads, other creators' edits, unverified footage "
            "and unrelated footage. Keep source URL and metadata for traceability.",
        ),
    ),
    video=VideoRules(
        layout="fit",
        caption_language="English",
        notes=("Official campaign logo overlay must remain visible throughout.",),
    ),
    editing=EditingRules(
        logo_required=True,
        logo_env="KREEKCRAFT_LOGO",
        logo_asset="assets/kreekcraft/logo.png",
        max_reposts=5,
        preserve_context=True,
        no_ai_media=True,
        no_fabricated_reactions=True,
        no_near_duplicates=True,
    ),
    captions=CaptionRules(
        exact_phrase=PHRASE,
        required_hashtags=HASHTAGS,
        forbidden_hashtags=("#DylanPage",),
        urls_forbidden=True,
        language="English",
        notes=("Every caption must contain the exact sentence and all hashtags; no URLs.",),
    ),
    thumbnails=ThumbnailRules(
        notes=("Follow the campaign's review requirements; generate from real clip frames.",),
    ),
    publishing=PublishingRules(
        platforms=("tiktok", "instagram", "youtube"),
        account_env={
            "tiktok": "ZERNIO_TIKTOK_ACCOUNT_ID",
            "instagram": "ZERNIO_INSTAGRAM_ACCOUNT_ID",
            "youtube": "ZERNIO_YOUTUBE_ACCOUNT_ID",
        },
        require_public_days=30,
        likes_visible_required=True,
        min_engagement_rate=0.8,
        min_tier1_audience_pct=40.0,
        tier1_countries=("United States", "United Kingdom", "Canada", "Australia"),
        notes=(
            "X/Twitter is not accepted. These account metrics are campaign requirements, "
            "not pipeline guarantees; do not manipulate engagement or demographics.",
        ),
    ),
    manual_review=(
        "KreekCraft is the primary focus throughout",
        "official logo is visibly present throughout",
        "context is accurate and the hook does not mislead",
        "caption sentence, hashtags and no URLs",
        "same clip is reposted no more than 5 times",
        "post stays public at least 30 days with likes visible",
        ">=0.8% engagement and >=40% Tier-1 audience (US/UK/CA/AU) after publication",
        "warmup, approval and USA-targeting guides: operator-supplied originals required",
    ),
    operational_guides=("warmup", "approval", "USA-targeting"),
    notes=("The same clip may be reposted at most 5 times under campaign rules.",),
)
