"""Campaign registry. Adding a campaign means adding one profile and one entry.

Campaign selection is strict: there is no default campaign. Every command must
name one (``--campaign``), and stamped clips carry their own ``campaign_id``.
Guessing a campaign could give a clip another creator's caption, logo or
accounts, so an unknown or missing id is always an error.

Cross-campaign guards are derived here, not hand-maintained per profile: each
profile automatically forbids every other profile's exact phrase, required
hashtags and required caption links (except markers it requires itself).
"""
import dataclasses

from campaigns.base import CampaignProfile
from campaigns.boeshi import PROFILE as BOESHI
from campaigns.dylan_page import PROFILE as DYLAN_PAGE
from campaigns.kreekcraft import PROFILE as KREEKCRAFT

# Id of the campaign whose pre-campaign files have no prefix or stamp. Only used
# for read-only legacy compatibility (config.timeline_path); never a default.
LEGACY_ID = "kreekcraft"


def _with_foreign_guards(profile: CampaignProfile,
                         others: tuple[CampaignProfile, ...]) -> CampaignProfile:
    own_tags = set(profile.captions.required_hashtags)
    own_phrases = {profile.captions.exact_phrase, *profile.captions.required_substrings}
    tags = list(profile.captions.forbidden_hashtags)
    phrases = list(profile.captions.forbidden_phrases)
    for other in others:
        for tag in other.captions.required_hashtags:
            if tag not in own_tags and tag not in tags:
                tags.append(tag)
        for phrase in (other.captions.exact_phrase, *other.captions.required_substrings):
            if phrase and phrase not in own_phrases and phrase not in phrases:
                phrases.append(phrase)
    captions = dataclasses.replace(profile.captions, forbidden_hashtags=tuple(tags),
                                   forbidden_phrases=tuple(phrases))
    return dataclasses.replace(profile, captions=captions)


_BASE = (KREEKCRAFT, DYLAN_PAGE, BOESHI)
_PROFILES: dict[str, CampaignProfile] = {
    profile.id: _with_foreign_guards(profile, tuple(o for o in _BASE if o.id != profile.id))
    for profile in _BASE
}


def ids() -> tuple[str, ...]:
    return tuple(_PROFILES)


def list_campaigns() -> tuple[CampaignProfile, ...]:
    return tuple(_PROFILES.values())


def get(campaign_id: str | None) -> CampaignProfile:
    """Resolve a profile by explicit id. Missing or unknown ids are errors."""
    key = (campaign_id or "").strip().lower()
    if not key:
        raise ValueError("No campaign selected. Pass --campaign "
                         f"({' | '.join(ids())}); there is no default campaign.")
    if key not in _PROFILES:
        raise ValueError(f"Unknown campaign {campaign_id!r}. Available: {', '.join(ids())}")
    return _PROFILES[key]
