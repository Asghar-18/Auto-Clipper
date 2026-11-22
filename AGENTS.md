# Instructions for AI agents

Use this repository's commands as documented in [README.md](README.md) and
[docs/CAMPAIGNS.md](docs/CAMPAIGNS.md). Keep all API keys in the local
environment; never print, ask the user to paste, or write keys into prompts,
logs, metadata, or tracked files.

## Clip workflow

1. Run `python find_streams.py "GTA 6" --max 25 --json` and show the returned candidates. The ranking is YouTube's view-count search order, not current concurrent viewers.
2. Use a stream only when the user has authorized its use or has a standing source list that includes it. In the campaign pipeline, KreekCraft accepts only official KreekCraft YouTube/Twitch footage and Dylan Page accepts only marathon footage from 2026-11-19 onward. If rights are unclear, ask the user and do not capture it.
3. Run `python clip.py URL --max-seconds 0 --clip-len 30 --lead-in 6 --top 2`. Stop after the requested review period or when the user stops the run. For campaign VODs, pass `--campaign kreekcraft|dylan_page` to the `campaign.*` stages.
4. Inspect each MP4 and its JSON. Confirm the highlight includes its lead-in and payoff, gameplay is centered, captions are legible and in sync, the audio is intelligible, and metadata is accurate. For Dylan, check the focus report and thumbnail as well; uncertain focus must stay in manual review.
5. Draft truthful titles, descriptions, captions, and hashtags from the clip. Never mix campaign copy: Kreek requires the exact caption sentence and hashtags with no URLs; Dylan requires `#DylanPage` and English captions. Do not invent reactions, events, creator approval, or viewership data.
6. Run `zernio_publish.py` without `--publish` to preview. The publisher refuses mismatched campaigns, failed validation, missing thumbnails, disallowed platforms or missing account connections. Publish only when the user authorized this specific clip or previously enabled unattended publishing for authorized sources. For unattended use, require `GTA_UNATTENDED_POSTS=1`, the account ID for each selected platform, and `--unattended`. X is `--platform twitter` (alias `x`) and is allowed only for Dylan.
7. After posting, report the Zernio post ID and status. If a request errors after upload, check Zernio before retrying.

The clipper itself never posts. A `--test` output is not publishable. The live-capture source allowlist was intentionally removed; campaign source policies are enforced instead, and the agent must still respect the user's rights policy.
