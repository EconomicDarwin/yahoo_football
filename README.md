# Fourth and 2wenty — league history and analytics

A personal, read-only toolkit for one Yahoo fantasy football keeper league that
has been running for about sixteen years with largely the same group of friends.

The point is the **historical record**. Yahoo's own interface is built around the
current season; everything before it is buried, and sixteen years of drafts,
trades, blowouts and grudges are effectively unqueryable. This archives the whole
league history to local JSON and builds analysis on top of it — an all-time
record book, head-to-head rivalries, luck-adjusted standings, draft and trade
retrospectives — plus the yearly keeper decision that started the project.

Not a product. Not hosted, not distributed, no users beyond the one running it.

> **Status: waiting on Yahoo API access.** Setup and OAuth work end to end, but
> Yahoo now gates the Fantasy Sports API behind a review, and new apps are
> refused with `additional_authorization_required`. An access application is in
> flight. See [SETUP.md](SETUP.md).

## Why archive locally

Yahoo does not keep old league seasons available forever, and there is no export.
A sixteen-year record that lives only on their servers is one product decision
away from being gone. `pull` writes every season to JSON on disk, and that
archive — not the API — is what the analysis reads. Fast, reproducible, offline,
and durable.

## Shipped today

### Keeper valuation

The league's keeper rule:

- Keep **one** player off your end-of-year roster.
- The cost is the round that player was drafted in last season **by anybody**,
  not necessarily by you.
- A player nobody drafted costs a **15th**.
- A player you already kept once **cannot be kept again**.

So each August: which player gives the most value relative to the pick you give
up? That means comparing every rostered player's keeper cost against what he
would actually cost in this year's draft.

**Why it isn't just round subtraction.** Counting surplus in *rounds* is
misleading, because draft value is convex. Turning a 15th into a 7th is eight
rounds, but it moves you between two cheap picks. Turning a 6th into a 2nd is
only four rounds, but it buys a genuine first-round-caliber player — worth much
more.

So `keepers.py` converts rounds to overall picks and scores them on a decay
curve, `value(pick) = exp(-(pick - 1) / TAU)` with `TAU = 40` picks. The ranking
sorts on curve-adjusted surplus and prints the raw round difference beside it as
a sanity check. Tune per league with `pick_value_tau` in `leagues.json`.

A worked example — the two candidates that mattered in 2025:

| Player | Keeper cost | Market | Rounds | Curve-adjusted |
| --- | --- | --- | --- | --- |
| Chris Olave | R6 | ~R2 | +4.0 | **+0.457** |
| Harold Fannin Jr. | R15 (undrafted) | ~R7 | +8.0 | +0.133 |

Fannin wins on raw rounds and loses badly on value. Olave was the keep.
`tests/test_keepers.py` runs the real board through this and asserts the
outcome, so a change to the scoring cannot silently flip the answer.

### Archive and discovery

`discover` maps season → league_id across the account's whole league history.
`pull` archives each season's settings, standings, teams, rosters, draft board,
transactions and weekly scoreboards.

## Roadmap

Everything below is derivable from what `pull` already archives.

**Record book.** All-time standings by manager (W-L-T, points for and against,
win %), championships and runner-ups, playoff appearances, highest and lowest
single-week scores, biggest blowout, closest game, longest streaks, best and
worst seasons.

**Head-to-head.** A full H2H matrix across sixteen years, per-rivalry pages with
record and average margin, and each manager's all-time nemesis and favourite
victim.

**Luck vs. skill.** The interesting one. An *all-play* record — what your record
would have been if you played every team every week — separates real performance
from schedule luck. Add close-game record (games decided by a few points),
points-against luck, and the gap between expected and actual wins, and you can
finally settle who has actually been good versus who has been fortunate.

**Manager efficiency.** Optimal lineup versus the lineup actually started, per
week, per season. Points left on the bench is one of the most quietly damning
stats in fantasy and nobody in a league ever has it.

**Draft retrospectives.** Points returned per draft slot, best and worst picks in
league history, hit rate by round, and whether each year's keepers actually paid
off — which closes the loop on the tool's original purpose.

**Transactions and trades.** Waiver-wire ROI (points a player scored *after*
being added), trade retrospectives scoring what each side actually got, and
activity leaderboards.

**Fun.** "This week in league history", manager career arcs, power rankings over
time.

### Known modeling problems

Worth writing down before building any of the above:

- **Manager identity across sixteen years.** Team names change constantly, so
  they are useless as a key. Yahoo exposes a stable manager GUID on
  `Team.managers` — everything historical must join on that, not on team or
  display name.
- **Scoring settings changed over the years.** Raw points are not comparable
  across eras. Cross-season comparisons need normalizing (z-scores within a
  season, or restating under current scoring).
- **Roster and lineup slots changed too**, which affects any optimal-lineup
  calculation; it has to use that season's actual slot configuration.
- **Old seasons may be thin.** Yahoo's coverage of the earliest years is
  untested and some endpoints may return nothing. Worth probing before promising
  a complete record book.

## Layout

```
├── SETUP.md              # first-time setup, step by step
├── ffball/
│   ├── config.py         # paths + leagues.json access
│   ├── client.py         # authenticated Yahoo API client
│   ├── cli.py            # shared clean-exit wrapper
│   ├── doctor.py         # verify the setup, diagnose what's wrong
│   ├── discover.py       # find league IDs across seasons
│   ├── pull.py           # archive a season to data/
│   └── keepers.py        # rank keeper candidates
├── tests/test_keepers.py # keeper math regression test
├── data/                 # pulled league JSON (created by pull)
└── leagues.json          # league identity, rules, season -> league_id
```

## Setup

See **[SETUP.md](SETUP.md)**. Short version:

1. Register a Yahoo app as a **Confidential Client** with redirect URI
   `https://localhost:8080`.
2. Put the Client ID and Secret in `.env` (BOM-free — SETUP.md has the exact
   command; a UTF-8 BOM silently hides the first variable from `python-dotenv`).
3. `python -m ffball.discover --save` to log in and record league IDs.

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Check where you stand at any point:

```
python -m ffball.doctor            # offline checks
python -m ffball.doctor --online   # plus one live API call
```

`doctor` only reports; it never changes anything.

## Commands

| Command | What it does |
| --- | --- |
| `python -m ffball.doctor [--online]` | Verify the setup and diagnose what's wrong |
| `python -m ffball.discover [--save] [--match NAME]` | List leagues by season; record their IDs |
| `python -m ffball.pull --season 2025` | Archive one season to `data/` |
| `python -m ffball.pull --all-seasons` | Archive every recorded season |
| `python -m ffball.pull --all-seasons --delay 2` | Same, pacing calls 2s apart |
| `python -m ffball.pull --season 2025 --force` | Re-request files already archived |
| `python -m ffball.keepers --season 2025` | Rank keeper candidates for the next draft |
| `python -m ffball.keepers --season 2025 --offline` | Same, without the ADP lookup |
| `python tests/test_keepers.py` | Keeper math regression test |
| `python tests/test_pull.py` | Archive pacing and resume test |

`pull --include core` is cheap (six requests). `rosters` costs one request per
team and `matchups` one per week, so they are opt-in.

The backfill is built to be a polite trickle. Every call is paced (1s apart by
default, `--delay` to change it), and anything already on disk is skipped, so an
interrupted backfill resumes without re-requesting what it already has. `pull`
reports the total requests it made. Use `--force` only when you want to refresh
data that is already archived.

## Notes

- Yahoo player keys (`461.p.31883`) carry a per-season game key prefix, so only
  the trailing player id is stable year over year. `client.player_id_of()`
  normalizes this; anything joining across seasons must use it.
- Past seasons need the query pinned via `client.for_league(season)`. A bare
  query answers for the current season only.
- ADP is only published once Yahoo opens the new season's draft board. Before
  that, `keepers.py` says so and falls back to listing costs.
- `.env` holds live credentials. It is gitignored, and `doctor` verifies that on
  every run.

Built on [yfpy](https://github.com/uberfastman/yfpy). Fantasy data provided by
Yahoo Fantasy.

## License

MIT — see [LICENSE](LICENSE).
