# KreekCraft campaign pipeline

Additive modules in `campaign/`. They reuse `clip.py` helpers but do not change it,
and they never publish. Only use sources you are authorized to record and repost.

This document describes the original KreekCraft walkthrough. For the current
campaign rules, profiles, CLI flags and publishing policy, see
[CAMPAIGNS.md](CAMPAIGNS.md). The pipeline is profile-driven; every command now
requires `--campaign` (pass `--campaign kreekcraft` for this walkthrough).

## Why stage 0 exists

Audio peaks are not gameplay. An early "Woo!" chant and a later conversation both
scored highly while the screen showed the pre-game waiting card. Every VOD clip
must now pass a **visual gameplay gate before** audio ranking:

1. Download only YouTube's `sb0` storyboard (~25 MB, one 160x90 frame every ~2.5 s).
   No full-quality video download and no paid vision API.
2. Compute frame signals: motion, text-like edge density, darkness, flatness, and
   perceptual match against confirmed waiting-screen templates.
3. Generate labelled contact sheets for human review.
4. Confirm the real gameplay range with `--confirm START-END`. The automatic
   proposal is never authoritative on its own.

For `dy-oCN2NxfA`, the waiting screen (0-90 s) matches the templates, the game
boots at 10,504 s, the settings menu runs to ~10,655 s, and gameplay starts at
**10,660 s**. The old 46-minute rank-2 window was also waiting/menu, not gameplay.

## Stages

```powershell
# 0. Build the visual timeline and review the contact sheets.
python -m campaign.gameplay --url "YOUTUBE_VOD_URL"
python -m campaign.gameplay --url "YOUTUBE_VOD_URL" --range-start 240 --range-end 420 --range-step 6

# Confirm the real gameplay range (repeat --confirm for multiple ranges).
python -m campaign.gameplay --url "YOUTUBE_VOD_URL" --confirm 10660-42102

# 1. Scan audio ONLY inside verified gameplay. A VOD without a confirmed timeline is refused.
python -m campaign.analyze --url "YOUTUBE_VOD_URL" --start 10660 --clip-len 30 --top 10 --min-score 0 --lead-in 6

# 2. Re-anchor to early speech and re-check gameplay coverage.
python -m campaign.refine --url "YOUTUBE_VOD_URL" --timestamps "output\campaign-clean\gameplay-timestamps.json" --clip-len 30

# 2b. Alternative moments: rank gameplay windows by transcript interest and
#     automatically exclude ranges of every existing clip.
python -m campaign.select --url "YOUTUBE_VOD_URL" --start 10660 --top-audio 60 --transcribe 30 --top 5 \
  --exclude 16818-16848 --out "output\campaign-clean\alternatives.json"

# 3. Render one candidate. Downloads only that ~30 s video section.
python -m campaign.render --url "YOUTUBE_VOD_URL" --timestamps "output\campaign-clean\gameplay-refined.json" --rank 1 --length 30

# 4. Validate one candidate and write its contact sheet (no promotion).
python -m campaign.finalize --candidate "output\candidates\NAME.json"

# 4a. Promote one passing candidate to output/final for review.
python -m campaign.finalize --candidate "output\candidates\NAME.json" --promote

# 4b. Promote multiple independently validated candidates in one command.
python -m campaign.finalize --select "output\candidates\alternatives" --promote
python -m campaign.finalize --candidate "A.json" --candidate "B.json" --promote
python -m campaign.finalize --candidates-from "chosen.txt" --promote
```

Every candidate is validated independently. Only candidates that pass **all**
technical, campaign and gameplay checks are promoted. An existing final clip is
never overwritten: if a same-named MP4, SRT or JSON already exists, that clip is
skipped/reported as an error. Add `--allow-existing` to skip already-promoted
names intentionally.

`--min-gameplay-coverage` (default 95%) and `--gameplay-margin` (default 2 s)
control how much of a window must be verified gameplay. Local test files use
`--file` and are marked `test: true`; they are never publishable.

## Outputs

- `output/candidates/` — timestamp reports, rendered MP4 + SRT + JSON
- `output/metadata/` — canonical metadata, gameplay timeline, validation reports
- `output/final/` — MP4 + SRT + JSON for review only
- `output/thumbnails/` — timeline, transition-range, and per-candidate contact sheets
- `output/logs/`, `work/campaign/` — logs and cached audio/storyboard/sections

Every candidate JSON now includes source timestamps, detection score, gameplay
coverage, static-screen percentage, waiting-screen flag, transcript, and the
validation report.

## Requirements

- `fit` layout is the safe default; smart crop is not used.
- Logo: official PNG, full width, pinned near the top. Override with `--logo` or
  `KREEKCRAFT_LOGO`.
- Captions use `campaign/captions.py`: **VAD must stay off** on this machine, and
  `faster-whisper==1.0.3` / `ctranslate2==3.24.0` are pinned in `requirements.txt`.
  `ctranslate2` 4.x crashes when loading any model on the i5-6500 runner.

## Validation checks

Beyond format, SRT timing, campaign phrase/hashtags, no URLs, logo, transcript
substance, authorization and duplicates, promotion now requires:

- `gameplay_detected`
- `gameplay_coverage_percentage` (>= 95% inside confirmed gameplay)
- `static_screen_percentage` (<= 20%)
- `waiting_screen_detected` (must be false)

## Multi-clip review and approval

Each promoted clip in `output/final/` is independent:

- `<name>.mp4`
- `<name>.srt`
- `<name>.json` — metadata plus `validation`, `review`, `approved`, `approved_by`,
  `approved_at`, `rejected` and `rejection_reason`
- `output/metadata/<name>-validation.json` — its own validation report
- `output/thumbnails/<name>-contact.jpg` — its own review sheet

Promotion never approves a clip. Newly promoted clips start with
`"review": {"status": "pending"}`, `"approved": false` and `"rejected": false`.

### Integrity seal (anti-swap)

At validation time, `campaign/validate.py` records an `integrity` block containing:
- the source key/URL and exact `source_start`/`source_end`,
- the MP4 and SRT filenames,
- SHA-256 hashes of both media files,
- a short `candidate_id` derived from those identity fields.

This record is written to the validation report and the candidate metadata, and
copied into the final metadata at promotion. Promotion itself re-hashes the copied
media and refuses to write metadata if a copy differs.

The `review-status` command re-verifies this before it records **any** review
decision. It refuses to proceed if:
- the MP4/SRT filenames do not match the validated candidate (metadata swapped),
- the metadata's source identity does not match the validated window,
- the current MP4/SRT SHA-256 differs from the validated hash (file replaced after
  validation), or
- no validation-time integrity record exists.

On success it stamps the verified integrity record into the final JSON.
`zernio_publish.py` re-checks the MP4 hash as a final defense in depth. For older
clips without an integrity record, re-run validation first:

```powershell
python -m campaign.finalize --candidate "output\candidates\NAME.json"
```

Record a human decision separately for each clip:

```powershell
# Review passed: explicitly approve this one clip for publishing.
python -m campaign.finalize review-status "output\final\NAME.json" `
  --status approved --reviewer "Your Name" --notes "contact sheet + MP4 reviewed" --approve

# Review failed: permanently exclude this clip from publishing.
python -m campaign.finalize review-status "output\final\NAME.json" `
  --status rejected --reviewer "Your Name" --notes "hook/logo/context issue" --reject
```

A rejected clip cannot be re-approved; generate a new candidate instead. Passing
validation is necessary, **not sufficient**. A human must still review the contact
sheet and MP4 for KreekCraft focus, logo visibility, accurate context, captions,
audio, and the first-2-second hook.

## Zernio integration

Publishing is a separate manual step and requires explicit per-clip approval. It
uses the official `zernio-sdk` (`from zernio import Zernio`). Credentials are read
**only** from your private environment, never from prompts, logs, metadata, or
tracked files:

- `ZERNIO_API_KEY` — required for any API call.
- `ZERNIO_YOUTUBE_ACCOUNT_ID` and/or `ZERNIO_INSTAGRAM_ACCOUNT_ID` — the connected
  account IDs to target when publishing.

These may be set as real environment variables, or placed in a local `.env` file
in the repository root (copy `.env.example`). `.env` is gitignored; the script
reads only the Zernio-related names from it, and real environment variables take
precedence. No value is ever printed.

```powershell
python zernio_publish.py --accounts                                                              # read-only auth/account check
python zernio_publish.py "output\final\NAME" --platform instagram --now                          # preview Instagram only
python zernio_publish.py "output\final\NAME" --platform instagram --now --publish               # publish Instagram only
python zernio_publish.py "output\final\NAME" --platform both --now --publish                    # publish both platforms
```

`--platform` accepts `youtube`, `instagram`, or `both` (default `both`). Vertical
9:16 clips are published as Shorts/Reels automatically; no special flag is set.

`--accounts` only lists connected account IDs; it publishes nothing. With
`--publish`, the MP4 is uploaded through Zernio's presign flow
(`media.get_media_presigned_url` followed by an HTTP PUT), then one
`posts.create_post(idempotency_key=...)` call is made per selected platform,
sequentially. Each platform gets its **own** idempotency key and post record
under `zernio_posts` in the clip JSON, so a clip already published on YouTube can
later be published to Instagram without republishing or reusing a key. Legacy
single-post records are migrated into `zernio_posts.youtube` on first use. The
returned post ID, status, schedule, and publish time are recorded per platform.
Use `--now` instead of `--scheduled-for` to publish immediately. `--unattended`
still requires `GTA_UNATTENDED_POSTS=1` and an explicit `approved=true` on every
individual clip.

`zernio_publish.py` refuses clips that are `test`, `rejected`, review-rejected,
not explicitly `approved`, missing the validation integrity stamp, or whose MP4
hash no longer matches the validation record. It also refuses to publish any
platform that already has a recorded post ID, and checks all selected platforms
before uploading so a partial request cannot start. Nothing is sent in preview
mode; `--publish` plus a schedule (or `--now`) is mandatory. There is no batch
publish command; approve and publish each clip individually. If a request fails
or returns no post ID, the error and the same idempotency key are recorded; check
the Zernio dashboard first, then re-run with `--retry` to reuse that key. Never
blindly retry with a new key, since that could duplicate a post.
