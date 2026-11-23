"""Campaign C: Boeshi GTA 6 (DRAFT -- not publishable yet).

Accepted sources are Boeshi's own recent GTA VI Twitch VODs
(twitch.tv/darealboeshi). The campaign overlay is mandatory and must stay
visible for the whole clip. Every caption must contain his Twitch link.

Deliberately incomplete until the operator supplies the missing inputs:
- the "recent" cutoff date (validation fails until ``start_date`` is set);
- publishing platforms/accounts (``platforms`` is empty, so nothing can post);
- overlay position (the shared fit renderer currently pins it across the top);
- the warmup, ClipLaunch approval and Tier-1 targeting guides (not in repo).

Account metrics (CPM, payout caps, budget, engagement, Tier-1 audience, 30 days
live) are campaign requirements, never pipeline guarantees, and are not
computed here.
"""
from campaigns.base import (
    CampaignProfile, CaptionRules, EditingRules, PublishingRules,
    SourcePolicy, ThumbnailRules, VideoRules,
)

TWITCH_LINK = "twitch.tv/darealboeshi"
CAPTION_TEMPLATES = (
    "FULL STREAM at twitch.tv/darealboeshi",
    "Watch the full stream \U0001F449 twitch.tv/darealboeshi",
    "Full stream at twitch.tv/darealboeshi",
    "Catch Boeshi LIVE at twitch.tv/darealboeshi",
    "Full VOD on twitch.tv/darealboeshi \U0001F3AE",
)

PROFILE = CampaignProfile(
    id="boeshi",
    name="Boeshi GTA 6",
    clip_prefix="boeshi",
    source=SourcePolicy(
        platforms=("twitch",),
        allowed_channels=("darealboeshi",),
        topic="Boeshi's recent GTA VI Twitch VODs",
        start_date=None,
        start_date_required=True,
        waiting_template_end=None,
        notes=(
            "Only Boeshi's own Twitch VODs; no reuploads, other creators' edits or "
            "1:1 copies of existing edits. Twitch VODs expire: cache before processing.",
        ),
    ),
    video=VideoRules(
        layout="fit",
        caption_language="English",
        notes=(
            "Campaign overlay is mandatory and must stay visible throughout. "
            "Overlay position and any stacked webcam layout are not decided yet; "
            "no stacked regions are defined, so no other campaign's crop can apply.",
        ),
    ),
    editing=EditingRules(
        logo_required=True,
        logo_env="BOESHI_OVERLAY",
        logo_asset="assets/boeshi/overlay.png",
        max_reposts=5,
        preserve_context=True,
        no_ai_media=True,
        no_fabricated_reactions=True,
        no_near_duplicates=True,
        notes=(
            "Original edits only; edits inspired by others must be meaningfully different. "
            "Strong hook, pacing and clean subtitles; quality over quantity.",
        ),
    ),
    captions=CaptionRules(
        required_substrings=(TWITCH_LINK,),
        templates=CAPTION_TEMPLATES,
        urls_forbidden=False,
        language="English",
        notes=("Every caption contains twitch.tv/darealboeshi; titles and hooks must "
               "describe the real moment accurately (no fake context or clickbait).",),
    ),
    thumbnails=ThumbnailRules(
        notes=("Real clip frame; no deceptive thumbnails.",),
    ),
    publishing=PublishingRules(
        platforms=(),  # not decided: nothing can be published for Boeshi yet
        account_env={
            "tiktok": "ZERNIO_BOESHI_TIKTOK_ACCOUNT_ID",
            "instagram": "ZERNIO_BOESHI_INSTAGRAM_ACCOUNT_ID",
            "youtube": "ZERNIO_BOESHI_YOUTUBE_ACCOUNT_ID",
            "twitter": "ZERNIO_BOESHI_X_ACCOUNT_ID",
        },
        require_public_days=30,
        min_engagement_rate=0.8,
        min_tier1_audience_pct=40.0,
        tier1_countries=("United States", "United Kingdom", "Canada", "Australia"),
        allow_unattended=False,
        notes=(
            "CPM $1 per 1,000 eligible views, max $300 per clip, $1,750 budget: "
            "tracked from the campaign's own reports, never estimated. "
            "No story boosting, artificial views or algorithm gaming.",
        ),
    ),
    manual_review=(
        "campaign overlay is clearly visible for the entire clip",
        "caption contains twitch.tv/darealboeshi and describes the real moment",
        "hook, pacing and subtitles are clean; context is accurate",
        "original edit, meaningfully different from any reference edit",
        "same or nearly identical clip posted no more than 5 times",
        "no story boosting, artificial views, misleading clickbait or deceptive thumbnail",
        "post stays live at least 30 days",
        ">=0.8% engagement and >=40% Tier-1 audience (US/UK/CA/AU), as the campaign defines them",
        "warmup, ClipLaunch approval and Tier-1 targeting guides: operator-supplied originals required",
    ),
    operational_guides=("warmup", "ClipLaunch approval", "Tier-1 targeting"),
    notes=("Draft profile: publishing stays blocked until platforms, accounts and the "
           "cutoff date are confirmed.",),
)
