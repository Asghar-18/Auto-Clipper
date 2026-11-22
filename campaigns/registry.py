"""Campaign registry. Adding a campaign means adding one profile and one entry."""
import os

from campaigns.base import CampaignProfile
from campaigns.dylan_page import PROFILE as DYLAN_PAGE
from campaigns.kreekcraft import PROFILE as KREEKCRAFT

_PROFILES: dict[str, CampaignProfile] = {
    KREEKCRAFT.id: KREEKCRAFT,
    DYLAN_PAGE.id: DYLAN_PAGE,
}

DEFAULT_ID = "kreekcraft"


def ids() -> tuple[str, ...]:
    return tuple(_PROFILES)


def list_campaigns() -> tuple[CampaignProfile, ...]:
    return tuple(_PROFILES.values())


def default_id() -> str:
    """Environment override, falling back to the legacy KreekCraft campaign."""
    configured = os.environ.get("GTA_CAMPAIGN", DEFAULT_ID).strip().lower()
    return configured if configured in _PROFILES else DEFAULT_ID


def get(campaign_id: str | None = None) -> CampaignProfile:
    """Resolve a profile by id; ``None`` uses GTA_CAMPAIGN / legacy default."""
    key = (campaign_id or default_id()).strip().lower()
    if key not in _PROFILES:
        raise ValueError(f"Unknown campaign {campaign_id!r}. Available: {', '.join(ids())}")
    return _PROFILES[key]
