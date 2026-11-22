"""Preview or schedule one reviewed clip to its campaign's Zernio platforms.

The official `zernio-sdk` (`from zernio import Zernio`) is used. The API key and
account IDs are read only from the private environment / gitignored .env; they
are never stored in metadata, prompts, logs, or source files.

Before any network call, the publisher validates the clip's campaign, video,
caption, thumbnail, allowed platforms, missing connections, and explicit human
approval. Dry-run is the default; the pipeline itself never calls this script.

Supported Zernio platform keys: youtube, instagram, tiktok, twitter (X).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import requests
from late.client.exceptions import LateError
from zernio import Zernio

from campaigns import get as get_profile
from shared import storage
from shared.publishing import preflight

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PLATFORMS = (
    ("youtube", "ZERNIO_YOUTUBE_ACCOUNT_ID"),
    ("instagram", "ZERNIO_INSTAGRAM_ACCOUNT_ID"),
    ("tiktok", "ZERNIO_TIKTOK_ACCOUNT_ID"),
    ("twitter", "ZERNIO_X_ACCOUNT_ID"),
)
PLATFORM_ENV = dict(PLATFORMS)
PLATFORM_ALIASES = {"x": "twitter"}
CAPTION_FIELDS = {
    "youtube": "youtube_description",
    "instagram": "instagram_caption",
    "tiktok": "tiktok_caption",
    "twitter": "x_caption",
}
# Only these names are ever read from a local .env; real environment values win.
ENV_NAMES = frozenset({
    "ZERNIO_API_KEY", "LATE_API_KEY", "GTA_CAMPAIGN", "GTA_UNATTENDED_POSTS",
    *PLATFORM_ENV.values(),
})


def load_dotenv(path=None):
    """Load Zernio settings from a local .env into os.environ, without printing."""
    path = Path(path) if path else Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name in ENV_NAMES and value and name not in os.environ:
            os.environ[name] = value


def client():
    """Build the SDK client; it reads ZERNIO_API_KEY from the environment."""
    try:
        return Zernio()
    except ValueError as error:
        raise ValueError(
            "Set ZERNIO_API_KEY in your private environment. "
            "Do not put it in a prompt, log, metadata, or source file."
        ) from error


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_metadata(path, metadata):
    with path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)


def normalise_platform(name):
    key = str(name).strip().lower()
    return PLATFORM_ALIASES.get(key, key)


def load_metadata(path, campaign_id=None, name=None):
    """Load one final clip and resolve the single campaign it belongs to."""
    with path.open(encoding="utf-8") as file:
        metadata = json.load(file)
    if not metadata.get("title") or not metadata.get("youtube_description") \
            or not metadata.get("instagram_caption"):
        raise ValueError("metadata needs a title, YouTube description, and Instagram caption")
    if metadata.get("test"):
        raise ValueError("test clips cannot be published")
    if metadata.get("rejected"):
        raise ValueError("rejected clips cannot be published")
    review = metadata.get("review") or {}
    if isinstance(review, dict) and review.get("status") == "rejected":
        raise ValueError("clip was rejected during human review")
    integrity = metadata.get("integrity") or {}
    expected_hash = integrity.get("content_sha256")
    if metadata.get("approved") and not expected_hash:
        raise ValueError("approved clip has no validation integrity stamp; refusing to publish")
    if expected_hash:
        video = path.with_suffix(".mp4")
        if not video.is_file():
            raise ValueError("expected MP4 not found; refusing to publish")
        if sha256_file(video) != expected_hash:
            raise ValueError("MP4 changed since validation/approval; refusing to publish")

    resolved = storage.require_campaign(metadata, name or path.stem, expected=campaign_id)
    metadata["campaign_id"] = resolved
    metadata.setdefault("campaign", {"id": resolved, "name": get_profile(resolved).name})
    return metadata


def post_state(metadata, platform):
    """Return this platform's publish record, migrating legacy single-post state."""
    posts = metadata.setdefault("zernio_posts", {})
    state = posts.get(platform)
    if state is None:
        state = {}
        if platform == "youtube" and metadata.get("zernio_post_id"):
            state = {
                "post_id": metadata["zernio_post_id"],
                "status": metadata.get("zernio_status"),
                "idempotency_key": metadata.get("zernio_idempotency_key"),
                "scheduled_for": metadata.get("scheduled_for"),
            }
        posts[platform] = state
    return state


def publishing_status(metadata, targets):
    """Distinguish scheduled posts from already-published ones in metadata."""
    states = [post_state(metadata, platform) for platform, _ in targets]
    if not all(state.get("post_id") for state in states):
        return "partial"
    statuses = {str(state.get("status", "")).lower() for state in states}
    if "scheduled" in statuses:
        return "scheduled" if statuses == {"scheduled"} else "mixed"
    # Zernio can report short-lived states such as "publishing"; once every
    # platform has an accepted post ID, the post has been handed off successfully.
    return "published"


def list_accounts():
    """Read-only connectivity/auth check. Prints account IDs; publishes nothing."""
    result = client().accounts.list()
    accounts = list(getattr(result, "accounts", []) or [])
    if not accounts:
        print("No connected Zernio accounts found. Connect them at https://zernio.com")
        return
    print("Connected Zernio accounts (use the ID in the matching environment variable):")
    for account in accounts:
        platform = getattr(account.platform, "value", account.platform)
        print(f"  {platform:<12} {account.field_id}  {getattr(account, 'username', '') or ''}")


def scheduled_local_time(value):
    when = dt.datetime.fromisoformat(value)
    if when.tzinfo is None:
        raise ValueError("schedule time must include a timezone offset, e.g. 2026-11-18T12:00:00+05:30")
    return when.astimezone(IST).replace(tzinfo=None).isoformat(timespec="seconds")


def post_url(post):
    """Return a publication URL only when Zernio actually supplied one."""
    for key in ("url", "publicUrl", "postUrl", "shareUrl"):
        value = post.get(key)
        if value:
            return str(value)
    return None


def caption_for(platform, metadata):
    """Use the platform's own campaign-correct caption; never cross-contaminate."""
    field = CAPTION_FIELDS.get(normalise_platform(platform), "caption_text")
    return str(metadata.get(field) or metadata.get("caption_text") or "")


def platform_entry(platform, account_id, metadata):
    entry = {
        "platform": normalise_platform(platform),
        "accountId": account_id,
        "customContent": caption_for(platform, metadata),
    }
    if entry["platform"] == "youtube":
        entry["platformSpecificData"] = {
            "title": metadata["title"][:100],
            "visibility": "public",
            "categoryId": "20",
            "madeForKids": False,
        }
    # 9:16 video is handled as Shorts/Reels by Zernio. No platform-specific
    # branding is added here; campaign artwork stays in the rendered clip.
    return entry


def post_body(metadata, media_url, targets, schedule):
    """Build the SDK create_post kwargs for one upload and its selected platforms."""
    body = {
        "content": caption_for(targets[0][0], metadata) if targets else "",
        "media_items": [{"type": "video", "url": media_url}],
        "platforms": [platform_entry(platform, account_id, metadata)
                      for platform, account_id in targets],
        "title": metadata["title"][:100],
        "timezone": "Asia/Kolkata",
        "hashtags": list(metadata.get("hashtags", [])),
    }
    if schedule == "now":
        body["publish_now"] = True
    else:
        body["scheduled_for"] = schedule
    return body


def selected_accounts(names, profile):
    """Resolve account IDs for this campaign, reporting every missing connection."""
    targets = []
    missing = []
    disallowed = []
    for raw in names:
        platform = normalise_platform(raw)
        if platform not in profile.publishing.platforms:
            disallowed.append(platform)
            continue
        env_name = profile.publishing.account_env.get(platform) or PLATFORM_ENV.get(platform)
        account_id = os.environ.get(env_name, "") if env_name else ""
        if not account_id:
            missing.append(env_name or f"(no account variable for {platform})")
            continue
        targets.append((platform, account_id))
    if disallowed:
        raise ValueError(f"{profile.name} does not allow platform(s): {', '.join(disallowed)}")
    if missing:
        raise ValueError(
            "Missing Zernio account connection(s): " + ", ".join(missing)
            + ". Connect them in Zernio and set the matching private environment variable.")
    return targets


def requested_platforms(value, profile):
    """Parse --platform, including legacy 'both' and campaign-wide 'all'."""
    raw = [item.strip().lower() for item in str(value).split(",") if item.strip()]
    if raw in (["both"],):
        return ["youtube", "instagram"]
    if raw in (["all"], ["campaign"]):
        return list(profile.publishing.platforms)
    result = []
    for item in raw:
        platform = normalise_platform(item)
        if platform not in PLATFORM_ENV:
            raise ValueError(f"Unknown platform {item!r}. Choose from: "
                             + ", ".join(dict(PLATFORM_ENV)) + ", both, all")
        if platform not in result:
            result.append(platform)
    if not result:
        raise ValueError("Select at least one platform.")
    return result


def upload_and_schedule(zernio, video_path, metadata_path, metadata, targets, schedule, retry=False):
    """Upload once, then create one post per selected platform, sequentially."""
    size = video_path.stat().st_size
    signed = zernio.media.get_media_presigned_url(video_path.name, "video/mp4", size=size)
    with video_path.open("rb") as file:
        requests.put(signed["uploadUrl"], data=file,
                     headers={"Content-Type": "video/mp4"}, timeout=900).raise_for_status()

    results = []
    for platform, account_id in targets:
        state = post_state(metadata, platform)
        if state.get("post_id"):
            raise ValueError(f"{platform} already has post {state['post_id']}; refusing to republish")
        if state.get("error") and not retry:
            raise ValueError(f"{platform} has an uncertain previous attempt: {state['error']}. "
                             "Check Zernio, then re-run with --retry to reuse its idempotency key.")
        idempotency_key = state.get("idempotency_key") or str(uuid.uuid4())
        state["idempotency_key"] = idempotency_key
        payload = post_body(metadata, signed["publicUrl"], [(platform, account_id)], schedule)

        # Persist the key before the call so a failed/uncertain attempt is reusable.
        save_metadata(metadata_path, metadata)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            result = zernio.posts.create_post(idempotency_key=idempotency_key, **payload)
        except Exception as error:
            state["error"] = f"{type(error).__name__}: {error}"
            state["last_attempt_at"] = now
            save_metadata(metadata_path, metadata)
            raise
        post = result.get("post") or {}
        post_id = post.get("_id") or post.get("field_id") or post.get("id")
        if not post_id:
            state["error"] = "Zernio did not return a post ID; check the dashboard before retrying"
            state["last_attempt_at"] = now
            save_metadata(metadata_path, metadata)
            raise RuntimeError(state["error"])
        url = post_url(post)
        state.update({
            "post_id": post_id,
            "status": post.get("status", "accepted"),
            "scheduled_for": post.get("scheduledFor") or schedule,
            "published_at": now,
        })
        if url:
            state["url"] = url
            metadata.setdefault("publication_urls", {})[platform] = url
        state.pop("error", None)
        save_metadata(metadata_path, metadata)
        results.append((platform, post_id, state["status"]))

    metadata["publishing"] = {
        "status": publishing_status(metadata, targets),
        "post_ids": {platform: post_state(metadata, platform).get("post_id")
                     for platform, _ in targets},
        "publication_urls": metadata.get("publication_urls", {}),
    }
    save_metadata(metadata_path, metadata)
    return results


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
        except (AttributeError, ValueError):
            pass
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", nargs="?", type=Path,
                        help="clip path without extension or path to its .mp4/.json")
    parser.add_argument("--accounts", action="store_true",
                        help="read-only: verify auth and list connected account IDs")
    parser.add_argument("--campaign", help="expected campaign id; otherwise read from clip metadata")
    parser.add_argument("--platform", default="both",
                        help="youtube, instagram, tiktok, twitter/x, a comma-separated list, "
                             "'both' (legacy), or 'all'/'campaign' (default: both)")
    parser.add_argument("--scheduled-for", help="ISO time with offset, for example 2026-11-18T12:00:00+05:30")
    parser.add_argument("--now", action="store_true", help="publish immediately instead of scheduling")
    parser.add_argument("--publish", action="store_true", help="send the post to Zernio; otherwise only preview")
    parser.add_argument("--retry", action="store_true",
                        help="reuse a stored idempotency key after an uncertain attempt; never creates a new one")
    parser.add_argument("--unattended", action="store_true",
                        help="legacy opt-in for authorized source lists; each clip still needs approved=true")
    args = parser.parse_args()

    if args.accounts:
        try:
            list_accounts()
        except (LateError, ValueError) as error:
            sys.exit(str(error))
        return
    if args.clip is None:
        sys.exit("Provide a clip path, or use --accounts for a read-only auth check.")

    base = args.clip.with_suffix("") if args.clip.suffix.lower() in {".mp4", ".json"} else args.clip
    video_path, metadata_path = base.with_suffix(".mp4"), base.with_suffix(".json")
    if not video_path.is_file() or not metadata_path.is_file():
        sys.exit("Clip files not found. Expected matching .mp4 and .json files.")
    try:
        metadata = load_metadata(metadata_path, args.campaign, base.name)
        profile = get_profile(metadata["campaign_id"])
        names = requested_platforms(args.platform, profile)
        schedule = "now" if args.now else (scheduled_local_time(args.scheduled_for) if args.scheduled_for else None)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        sys.exit(str(error))
    if args.now and args.scheduled_for:
        sys.exit("Use either --now or --scheduled-for, not both.")
    if args.unattended and args.now:
        sys.exit("Unattended mode only schedules future posts; it cannot publish immediately.")
    if args.publish and not schedule:
        sys.exit("Choose --scheduled-for or --now before publishing.")
    if not metadata.get("approved"):
        sys.exit("Clip metadata is not approved. Review this individual clip, then set approved=true.")
    if args.unattended and os.environ.get("GTA_UNATTENDED_POSTS") != "1":
        sys.exit("Set GTA_UNATTENDED_POSTS=1 in your private environment to use legacy unattended mode.")

    try:
        checks = preflight(metadata, profile, names, base.name)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    failed = [item for item in checks if not item["passed"]]
    if failed:
        print("Publishing preflight failed:")
        for item in failed:
            print(f"  FAIL {item['name']}: {item['detail']}")
        sys.exit("Fix the clip/profile mismatch or missing approval before publishing.")
    try:
        targets = selected_accounts(names, profile)
    except ValueError as error:
        sys.exit(str(error))

    # Check every selected platform before any network call, so a partial request
    # can never start when one of the requested platforms is already published.
    for platform, _ in targets:
        state = post_state(metadata, platform)
        if state.get("post_id"):
            sys.exit(f"{platform} is already published (post {state['post_id']}); refusing to republish. "
                     "Use --platform to select only the unpublished platform.")
        if state.get("error") and not args.retry:
            sys.exit(f"{platform} has an uncertain previous attempt: {state['error']}. "
                     "Check Zernio, then re-run with --retry to reuse its idempotency key.")

    destinations = ', '.join(p for p, _ in targets)
    plan = f"{base.name} [{metadata['campaign_id']}]: {schedule or 'DRY RUN — no schedule sent'} -> {destinations}"
    print(plan)
    if not args.publish:
        print("No post sent. Add --publish to schedule or publish this clip.")
        return
    try:
        results = upload_and_schedule(client(), video_path, metadata_path, metadata,
                                      targets, schedule, retry=args.retry)
    except (LateError, requests.RequestException, ValueError, RuntimeError,
            OSError, KeyError, TypeError) as error:
        sys.exit(f"Zernio request failed ({type(error).__name__}: {error}). "
                 "Check the Zernio dashboard before retrying; do not duplicate the post.")
    for platform, post_id, status in results:
        print(f"Zernio accepted {platform} post {post_id} with status {status}.")


if __name__ == "__main__":
    main()
