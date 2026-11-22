"""Independent campaign profiles for the Gameflux GTA clip pipeline.

A profile owns every campaign-specific rule. Shared pipeline code reads profiles
through this package; it never hardcodes a creator's caption, logo or platforms.
Legacy clips without a ``campaign_id`` are handled by :mod:`shared.storage`.
"""
from .registry import get, list_campaigns, ids, default_id

__all__ = ["get", "list_campaigns", "ids", "default_id"]
