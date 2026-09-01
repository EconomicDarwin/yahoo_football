# Fourth and 2wenty — league tools

A personal, read-only command-line tool for a single Yahoo fantasy football
keeper league. It archives the league's own data to local JSON and analyzes it —
principally **keeper valuation**, deciding which player is worth retaining under
the league's keeper rules.

Not a product. Not hosted, not distributed, no users beyond the one running it.
It exists because working this out by squinting at screenshots of the draft
board every August got old.

> **Status: waiting on Yahoo API access.** Setup and OAuth work end to end, but
> Yahoo now gates the Fantasy Sports API behind a review, and new apps are
> refused with `additional_authorization_required`. An access application is in
> flight. See [SETUP.md](SETUP.md).

## The problem it solves

The league's keeper rule:

- Keep **one** player off your end-of-year roster.
- The cost is the round that player was drafted in last season **by anybody**,
  not necessarily by you.
- A player nobody drafted costs a **15th**.
- A player you already kept once **cannot be kept again**.

So the question each August is: which player gives the most value relative to
the pick you give up? That means comparing every rostered player's keeper cost
against what he would actually cost in this year's draft.

### Why it isn't just round subtraction

Counting surplus in *rounds* is misleading, because draft value is convex.
Turning a 15th into a 7th is eight rounds, but it moves you between two cheap
picks. Turning a 6th into a 2nd is only four rounds, but it buys a genuine
first-round-caliber player — worth much more.

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
| `python -m ffball.keepers --season 2025` | Rank keeper candidates for the next draft |
| `python -m ffball.keepers --season 2025 --offline` | Same, without the ADP lookup |
| `python tests/test_keepers.py` | Run the keeper math regression test |

`pull --include core` is cheap (six requests). `rosters` costs one request per
team and `matchups` one per week, so they are opt-in.

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
