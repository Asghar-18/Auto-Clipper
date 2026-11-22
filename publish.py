r"""Campaign-aware Zernio publisher wrapper with generic variable names.

Usage:  python publish.py output\final\CLIP --publish --unattended --scheduled-for FUTURE_ISO_TIME
Generic PUBLISH_* names are mapped to the ZERNIO_* names used by zernio_publish.py.
"""
import os

for new, old in (
    ("PUBLISH_API_KEY", "ZERNIO_API_KEY"),
    ("PUBLISH_YOUTUBE_ACCOUNT_ID", "ZERNIO_YOUTUBE_ACCOUNT_ID"),
    ("PUBLISH_INSTAGRAM_ACCOUNT_ID", "ZERNIO_INSTAGRAM_ACCOUNT_ID"),
    ("PUBLISH_TIKTOK_ACCOUNT_ID", "ZERNIO_TIKTOK_ACCOUNT_ID"),
    ("PUBLISH_X_ACCOUNT_ID", "ZERNIO_X_ACCOUNT_ID"),
):
    if os.environ.get(new) and not os.environ.get(old):
        os.environ[old] = os.environ[new]

import zernio_publish

if __name__ == "__main__":
    zernio_publish.main()
