# Three-campaign pipeline

One application serves three independent campaigns. The clipper code, FFmpeg
helpers, storyboard gating, Whisper captions, review workflow and Zernio client
are shared. Creator-specific decisions live in `campaigns/`:

| Campaign id | Source policy | Publishing platforms | Caption rule | Branding |
| --- | --- | --- | --- | --- |
| `kreekcraft` | Official KreekCraft GTA VI YouTube/Twitch only; no reuploads | TikTok, Instagram Reels, YouTube Shorts (X rejected) | Exact phrase `Watch KreekCraft on YouTube and Twitch` plus `#GTA6 #KreekCraft #GrandTheftAutoVI`; no URLs | Official KreekCraft overlay required throughout |
| `dylan_page` | Dylan Page GTA VI marathon streams/VODs dated 2026-11-19 or later | TikTok, Instagram Reels, X, YouTube Shorts | `#DylanPage` in every caption; English; Kreek template/hashtags forbidden | No added watermark or third-party branding; original footage logos allowed |
| `boeshi` (DRAFT) | Boeshi's own recent GTA VI Twitch VODs (twitch.tv/darealboeshi); cutoff date not set yet, so validation fails until it is | None yet (publishing blocked); own `ZERNIO_BOESHI_*` account variables; unattended mode refused | `twitch.tv/darealboeshi` in every caption, from rotating templates; English | Campaign overlay mandatory and visible throughout (`BOESHI_OVERLAY` or `assets/boeshi/overlay.png`); position not decided |

Cross-campaign caption guards are derived in `campaigns/registry.py`: every
profile automatically forbids the other profiles' exact phrases, required
hashtags and required caption links.

Add or change a campaign in `campaigns/<id>/profile.py` and register it in
`campaigns/registry.py`. Do not add creator branches to the shared pipeline.

## Invariants

1. A clip has exactly one `campaign_id`. `campaign.metadata.build()` stamps it;
   `campaign.validate.validate()`, `campaign.finalize.verify_clip_integrity()`
   and the publisher all refuse mismatches.
2. Legacy clips without a field are inferred read-only from their `kreek-` or
   `dylan-` filename / caption markers (`shared/storage.py`). Ambiguous clips
   are not publishable until an operator supplies the campaign.
3. Audio caches, timelines, VOD sections, candidate filenames and exclusion
   ranges are campaign/source scoped (`campaign/source.py`, `campaign/config.py`,
   `campaign/select.py`). The old shared `vod_audio.*` cache is never read.
4. The Kreek pre-game waiting card template is only used by the Kreek profile.
   Other campaigns disable it (`SourcePolicy.waiting_template_end = None`).
5. Validation and publishing use the same profile rule helpers. No clip is
   published with a failed check, missing approval, rejected status or test flag.
6. Focus analysis reports *visible-person presence*, not identity. It never
   auto-approves a Dylan clip; uncertainty sets `manual_review` and blocks
   promotion/publishing.
7. Dylan's 1080x1920 render uses a stacked layout when the face is large and
   stable enough: a fixed upper panel shows the stream's webcam window and timer
   (1316,0,604,537 on 1920x1080) without panning; a lower panel shows gameplay
   ending just before the webcam (101,0,1215,1080). These regions live on the
   Dylan profile (`VideoRules.stacked_*`), so no other campaign can inherit
   them; a profile with no regions falls back to the fit layout. Kreek always
   keeps the fit layout plus its official overlay.
8. There is no default campaign. Every `campaign.*` command requires
   `--campaign`; `GTA_CAMPAIGN` is no longer read. Unknown ids are errors.

## Commands

Every command must name its campaign with `--campaign` (there is no default).

```powershell

python -m campaign.gameplay --url "VIDEO_URL" --campaign dylan_page
python -m campaign.analyze --url "VIDEO_URL" --campaign dylan_page --start 0
python -m campaign.select --url "VIDEO_URL" --campaign dylan_page --start 0 --top 5
python -m campaign.render --url "VIDEO_URL" --campaign dylan_page --timestamps "...alternatives.json" --rank 1
python -m campaign.finalize --campaign dylan_page --select output/candidates
python -m campaign.finalize review-status output/final/dylan-CLIP --status approved --reviewer "Initials" --approve

python zernio_publish.py output/final/dylan-CLIP --platform all --scheduled-for "2026-11-22T12:00:00+05:30"
```

Use `--platform both` for the legacy YouTube+Instagram selection, a comma-separated
list (for example `tiktok,twitter`), or `all`/`campaign` for the profile's full
allowlist. X is the `twitter` Zernio platform key; the `x` alias is accepted by
the CLI. Every dry run prints preflight failures and missing account connections
before any network request.

`python publish.py` is the same command with generic `PUBLISH_*` environment
variable aliases. See `.env.example` for variable names; copy it to the
gitignored `.env` or set real values in the terminal. Never commit keys or paste
them into prompts, logs, metadata or issues.

## Metadata written per clip

Final JSON includes: `clip_id`/name, `campaign_id` and `campaign`, `source`
(platform, URL, channel, key), `source_start`/`source_end`, video and SRT paths,
`thumbnail` (path, SHA-256, dimensions, source time, provenance), platform-specific
captions, hashtags, `validation` (checks plus manual-review items), `review`,
`approved`, `rejected`, `integrity`, `zernio_posts`, and publication URLs/IDs
when a post is accepted. Publication URLs are recorded only after Zernio returns
them; do not invent them before posting.

## Validation details

- Video: ffprobe checks 1080x1920, 5-60 s, audio stream.
- Gameplay: human-confirmed storyboard timeline, >=95% coverage, no waiting/menu screen.
- Captions: profile phrase/hashtags/language, foreign-campaign copy forbidden, Kreek URLs forbidden.
- Thumbnail: generated from a decoded final frame, unique SHA-256, file hash verified.
- Source: channel/platform/date policies; date/rights uncertainty is a manual-review failure.
- Dylan focus: YuNet face presence (Haar fallback), longest absence and presence ratio,
  sampled positions, `identity_verified: false`, uncertainty flagged for a human.
- Editing: no added branding for Dylan, no AI-generated media or fabricated reactions,
  no near-duplicate source windows.

## Operational requirements that automation cannot prove

Kreek account requirements are recorded in the profile and in validation's
`human_review_still_required` list: public for 30 days, visible likes, >=0.8%
engagement, and >=40% Tier-1 audience from US/UK/CA/AU. The warmup, approval and
USA-targeting guides are **not in this repository**; the pipeline reports that
operator-supplied originals are required and does not invent their contents.
Engagement manipulation, botting, repost abuse and misleading edits are prohibited.

## Azure migration TODO (later)

- Move `output/` to durable campaign-scoped blob storage and keep SHA-256 integrity.
- Store secrets in a managed secret store; remove local `.env` reliance.
- Replace the local manual review file state with an approval service/queue while
  keeping the explicit per-clip approval gate.
- Keep Zernio preflight and campaign rule checks server-side before any publish call.
