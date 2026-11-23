Read `docs/HANDOFF.md` first (current state, hard rules, next steps), then
`AGENTS.md` and `docs/CAMPAIGNS.md`.

- Never publish, schedule or approve a clip without the operator's explicit OK
  for that clip; never print or write API keys or account IDs.
- Every `campaign.*` command needs `--campaign kreekcraft|dylan_page|boeshi`.
- Run `python -m unittest discover -s tests` before and after changes.
