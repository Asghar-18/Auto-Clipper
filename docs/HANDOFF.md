# Handoff — where things stand (2026-11-23)

Read this, then `AGENTS.md`, then `docs/CAMPAIGNS.md`, before changing anything.
The operator is Umer (Windows PC, project at `D:\New folder\GTA-Auto-Clipper`).

## Hard rules (never break)

1. Never publish, schedule or approve a clip without the operator's explicit OK
   for that specific clip. Always preview `zernio_publish.py` without `--publish`
   first. No unattended publishing.
2. Never print, request or write API keys/account IDs into prompts, logs,
   metadata or tracked files. `.env` stays private.
3. Do not change KreekCraft behaviour. Do not change Dylan Page output (a test
   pins Dylan's exact filtergraph).
4. One clip = one `campaign_id`. Every `campaign.*` command needs `--campaign`.
5. Do not reintroduce face-detection-based or panning crops for Dylan; the
   operator rejected them. Crops are fixed regions confirmed on preview sheets.
6. Uncertain focus or context stays in manual review. Facts in captions and
   titles come from the real clip only.
7. X/Twitter and YouTube *integration work* is out of scope unless asked.
8. Show the operator a preview/review sheet and get a yes before re-rendering,
   archiving or promoting.

## Branches

| Branch | Contents |
| --- | --- |
| `main` (`2b03bfb`) | Campaign profiles + first Dylan stacked layout |
| `top-panel-preview` (`b520551`) | Dylan crop work: preview tool, confirmed webcam crop, gameplay crop, Best Moments excluded |
| `boeshi-isolation` (this branch, built on top of `top-panel-preview`) | Strict campaign selection, three-way caption guards, Dylan regions moved into the Dylan profile, draft Boeshi profile, VOD probe, docs |

Nothing has been merged to `main`. Run `python -m unittest discover -s tests`
(86 tests) before and after any change.

## Dylan Page (active until Boeshi is ready)

- Confirmed layout: top panel = stream webcam window + timer
  (1316,0,604,537 on 1920x1080); bottom = gameplay 101,0,1215,1080 (no second
  copy of the webcam). Values live in `campaigns/dylan_page/profile.py`.
- Sources: five live marathon VODs with confirmed gameplay starts —
  `xFcI47X15Lo` 12120, `FI5ZXVYuD04` 7800, `tvT6ZVHOtWs` 6000,
  `-6PVU387zOo` 14100, `LEAdEczRNEc` 13200.
- `cq7OxWhmgHA` (DAY 4): silent audio and a "WAKING SOON" screen — stays in
  manual review, never promoted.
- `i1zUT_gKQzA` (Best Moments): excluded (webcam moves between edits,
  burned-in subtitles).
- Last step asked of the operator: re-render the five into
  `output\candidates\dylan-final-layout\` and make a review sheet with frames at
  5/15/25 s per clip. **Check whether that was done and confirmed.** After the
  operator confirms: archive the six current finals in `output\final\` (they use
  the old cropped panel, and one is Best Moments) to
  `output\archive\dylan-superseded-quadrant-final\`, then
  `python -m campaign.finalize --campaign dylan_page --promote --candidate ...`
  for the five. Nothing approved or published.

## Boeshi GTA 6 (new campaign, draft)

Full audit (12 sections, P0/P1/P2 gaps, file list):
https://claude.ai/artifact/PT5x4LPCPpceykmtHf73x7 — the operator can export it
as Markdown into this repo if needed.

Campaign rules (from the brief): Boeshi's own recent GTA 6 Twitch VODs only
(twitch.tv/darealboeshi); process whole VODs; mandatory overlay visible the whole
clip; every caption contains `twitch.tv/darealboeshi` (style examples are the
templates in `campaigns/boeshi/profile.py`); English; content priorities: funny
high-retention moments, voice-joke bits, mewing when focused/scared, "Chad"
moments, meme-format relatable captions, accurate storytelling. Anti-spam: original
edits, no 1:1 copies, same clip posted at most 5 times, no clickbait, fake
context, deceptive thumbnails, view inflation or algorithm gaming. Metrics
(campaign requirements, never computed or promised by us): $1 CPM on eligible
views, $300 max per clip, $1,750 budget, >=40% Tier-1 audience (US/UK/CA/AU),
>=0.8% engagement, posts live >=30 days.

Done on this branch:
- `campaigns/boeshi/profile.py`: Twitch-only source `darealboeshi`; caption link
  rule + rotating templates; overlay required (`BOESHI_OVERLAY` env or
  `assets/boeshi/overlay.png`); separate `ZERNIO_BOESHI_*` account variables;
  `platforms=()` so nothing can publish; cutoff required (validation fails until
  `start_date` is set); unattended refused; max 5 reposts recorded.
- No default campaign; registry-derived three-way caption guards; Dylan crop
  regions now on the Dylan profile (Boeshi has none, so it falls back to fit).
- `tools/boeshi_vod_probe.py` — read-only probe of one VOD.

Inputs still missing (ask the operator; do not invent):
1. "Recent" cutoff date.
2. Publishing platforms and which accounts (must be separate variables).
3. The three Notion guides (warmup, ClipLaunch approval, Tier-1 targeting) —
   not readable from here; the operator must paste/export them.
4. Campaign's definitions of "engagement rate" and "eligible views".
5. Whether non-gameplay moments (just chatting) are allowed — today every clip
   must be >=95% confirmed gameplay.
6. Overlay position. The asset was supplied: PNG 2172x724 RGBA, transparent
   background, badge at 170,148–2001,587 (Twitch glyph + "@darealboeshi").
   Trim to the badge before use; it is not in the repo yet (place it at
   `assets/boeshi/overlay.png` locally).

Next steps, in order:
1. Run `python tools/boeshi_vod_probe.py https://www.twitch.tv/videos/2935956182`
   and review `work\boeshi-probe\2935956182\info.txt`, `storyboard.txt`,
   `frames.jpg`: uploader/upload_date readable? which resolution each format
   selector picks (current one likely stops at 720p)? does the `sb0` storyboard
   exist and what are its tile size/type? where is Boeshi's webcam?
2. Adapt `campaign/gameplay.py storyboard_frames()` for Twitch (it assumes
   YouTube 160x90 WebP tiles), or add a frame-sampling fallback. Test on that VOD.
3. Overlay on every layout as the last filter step (today only the fit layout
   draws a logo, pinned full-width at y=24) + pixel-level visibility check across
   the whole clip; show placement options on a preview sheet first.
4. Boeshi composition (webcam/gameplay crops) via the preview tool:
   `python -m campaign.top_panel_preview --campaign boeshi --source URL --at T --region x,y,w,h`.
5. Full-VOD transcript cache + full ranked moment list + human triage sheet
   (today `select` transcribes only ~30 windows).
6. Repost ledger (max 5), wider near-duplicate check, read-only metrics sync.
   The pinned Zernio SDK has `analytics` (incl. `get_analytics`,
   `get_instagram_demographics`); the account's Analytics add-on is unverified.
7. Only after platforms/accounts/cutoff are confirmed: enable publishing in the
   profile, dry-run preflight, and publish one clip at a time with explicit OK.
