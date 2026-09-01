# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Read-only Yahoo Fantasy Sports API tooling for one ~16-year fantasy football
keeper league. The goal is the **historical record** — an all-time record book,
head-to-head rivalries, luck-adjusted standings, draft and trade retrospectives.
Keeper valuation is the first shipped feature, not the point. See README.md for
the roadmap.

**Currently blocked:** Yahoo gates the Fantasy Sports API behind a review, and
this app is refused with `oauth_problem="additional_authorization_required"`.
OAuth itself works and tokens are saved. An access application is submitted.
Until it is granted, every live API call fails — build and test offline.

## Commands

Always use the venv interpreter explicitly. Bare `python` is a different
install and will not have `yfpy`.

```powershell
.\.venv\Scripts\python.exe -m ffball.doctor            # verify setup, offline
.\.venv\Scripts\python.exe -m ffball.doctor --online   # + one live API call
.\.venv\Scripts\python.exe -m ffball.discover --save   # map season -> league_id
.\.venv\Scripts\python.exe -m ffball.pull --all-seasons
.\.venv\Scripts\python.exe -m ffball.keepers --season 2025
```

Tests are plain scripts with asserts — there is no pytest, no runner config.
Run one directly:

```powershell
.\.venv\Scripts\python.exe tests\test_keepers.py
.\.venv\Scripts\python.exe tests\test_pull.py
```

`doctor` is the diagnostic entry point for anything environment-related. It only
reports; it never changes state.

## Architecture

**Season pinning.** `leagues.json` maps each season to its Yahoo `league_id`.
Yahoo's league key is `<game_key>.l.<league_id>` and the game key changes every
year, so a bare query answers for the *current* season only. `client.for_league(
season)` resolves and assigns `query.league_key` — anything touching a past
season must go through it.

**Two shapes of the same data.** Live yfpy calls return model objects read by
attribute (`team.team_id`). `client.serialize()` converts them to plain dicts,
and that is what `pull` writes to `data/`. Every analysis module reads the dict
form, not the object form. Mixing them up is the easiest bug to write here —
`tests/test_pull.py` has a `StubModel` that deliberately models both halves.

**Player identity across seasons.** Player keys (`461.p.31883`) carry a
season-specific game prefix; only the trailing id is stable year to year. Use
`client.player_id_of()` for anything that joins across seasons.

**Manager identity across seasons.** Not yet implemented, and it is the
precondition for the whole record book: team names change every year and are
useless as a key. Join on the stable manager GUID from `Team.managers`.

**Error translation.** `cli.run()` wraps every entry point. `ConfigError` is the
"expected state with an actionable fix" exception and prints as plain text.
`cli.looks_unauthorized()` recognizes Yahoo's fantasy-access refusal — note the
marker string is `additional_authorization_required`, not a 401/403.

**Archive is the source of truth.** Analysis reads `data/`, never the API.
Yahoo does not keep old seasons forever and offers no export, so the local JSON
is the durable copy. `data/` is committed on purpose in the private league repo.

## Things that will bite you

**Keeper surplus is curve-adjusted on purpose.** Do not "simplify"
`Candidate.surplus_value` into a round subtraction. Draft value is convex: a
15th→7th is more rounds than a 6th→2nd but far less value, and raw rounds rank
the wrong player first. `tests/test_keepers.py` pins this against a real board.

**`pull` pacing and resume are a commitment, not an optimization.** The Yahoo
API access application states the ~16-season backfill will run gradually.
Requests are paced by `Pacer`, and already-archived files are skipped so an
interrupted run resumes. Do not remove either.

**PowerShell 5.1 mangles UTF-8. This has caused two real bugs here.**
- `Set-Content -Encoding utf8` and `Out-File` write a **BOM**. `python-dotenv`
  silently drops the *first* variable of a BOM'd `.env` (symptom: "no consumer
  key found" on a file that looks perfect), and `json.loads` fails outright on a
  BOM'd `leagues.json`.
- A `Get-Content -Raw` → `Set-Content` round-trip reads UTF-8 as Windows-1252
  and corrupts non-ASCII — em-dashes become `â€"`.
- To edit files from PowerShell, use .NET: `[System.IO.File]::WriteAllText($p,
  $text, (New-Object System.Text.UTF8Encoding($false)))`. For pure-ASCII files
  like `.env`, `-Encoding ascii` is also safe.

**PowerShell has no heredocs.** `<<'EOF'` is a parse error. Use a here-string
`@'` ... `'@` with the closing `'@` at column 0.

**Live API calls cost something.** `discover`, `pull`, and `doctor --online`
hit Yahoo. Do not run them to "check something" — they currently fail anyway.
Everything else is testable offline against stubs and fixtures.

**`.env` holds live credentials and OAuth tokens.** Gitignored, and `doctor`
verifies that on every run. Do not print its values.

## Related

The league's private artifacts — draft-board screenshots, keeper decision log,
other managers' rosters — live in a separate private repo at
`../personal/fantasy_football`. Analysis code belongs here; league data and
decisions belong there.
