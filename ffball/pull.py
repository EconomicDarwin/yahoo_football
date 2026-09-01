"""Archive a season of league data from Yahoo to local JSON.

Everything downstream (keeper math, record books, power rankings) reads these
files rather than hitting the API again, so analysis stays fast, reproducible,
and works offline. It also guards against Yahoo aging out old seasons.

Backfilling ~16 seasons is several hundred requests, so this is built to be a
polite trickle rather than a flood: every call is paced, and anything already on
disk is skipped, which makes an interrupted backfill resumable without
re-requesting what it already has.

Usage:
    python -m ffball.pull --season 2025
    python -m ffball.pull --season 2025 --include core rosters
    python -m ffball.pull --all-seasons
    python -m ffball.pull --all-seasons --delay 2 --include core rosters matchups
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import cli, client, config

# Seconds to wait between API calls. A full backfill is a one-time cost and
# there is no reason to hurry it.
DEFAULT_DELAY_SECONDS = 1.0

# "core" is cheap: a handful of calls. rosters/matchups are per-team or
# per-week, so they cost one request each and are opt-in.
CORE_ENDPOINTS: Dict[str, Callable[[Any], Any]] = {
    "metadata": lambda q: q.get_league_metadata(),
    "settings": lambda q: q.get_league_settings(),
    "standings": lambda q: q.get_league_standings(),
    "teams": lambda q: q.get_league_teams(),
    "draft_results": lambda q: q.get_league_draft_results(),
    "transactions": lambda q: q.get_league_transactions(),
}


class Pacer:
    """Spaces out API calls and counts them.

    Call :meth:`wait` immediately before each request. The first request goes
    out straight away; every later one waits ``delay`` seconds.
    """

    def __init__(self, delay: float = DEFAULT_DELAY_SECONDS) -> None:
        self.delay = max(0.0, float(delay))
        self.requests = 0

    def wait(self) -> None:
        if self.requests and self.delay:
            time.sleep(self.delay)
        self.requests += 1


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )


def pull_core(query: Any, out_dir: Path, pacer: Pacer, force: bool) -> None:
    for name, fetch in CORE_ENDPOINTS.items():
        target = out_dir / f"{name}.json"
        if target.exists() and not force:
            print(f"  = {name}.json (already archived)")
            continue
        pacer.wait()
        try:
            payload = client.serialize(fetch(query))
        except Exception as exc:  # noqa: BLE001 - keep going; some are season-dependent
            print(f"  ! {name}: {exc}", file=sys.stderr)
            continue
        write_json(target, payload)
        print(f"  + {name}.json")


def final_week(query: Any, out_dir: Path, pacer: Pacer, default: int = 17) -> int:
    """Last scoring week of the season.

    Prefers the already-archived metadata so a resumed backfill does not spend a
    request rediscovering something it has on disk.
    """
    archived = out_dir / "metadata.json"
    if archived.exists():
        try:
            meta = json.loads(archived.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = None
        if isinstance(meta, dict):
            for key in ("end_week", "current_week"):
                try:
                    if meta.get(key):
                        return int(meta[key])
                except (TypeError, ValueError):
                    continue

    pacer.wait()
    try:
        meta_obj = query.get_league_metadata()
    except Exception:  # noqa: BLE001
        return default
    for attr in ("end_week", "current_week"):
        value = getattr(meta_obj, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return default


def _team_name(team: Any) -> str:
    name = getattr(team, "name", "")
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return str(name)


def pull_rosters(
    query: Any, out_dir: Path, week: Optional[int], pacer: Pacer, force: bool
) -> None:
    """Save each team's roster for a week (default: the last week of the season).

    The final-week roster is what keeper eligibility is judged against, so this
    is the file the keeper analysis depends on.
    """
    week = week or final_week(query, out_dir, pacer)
    target = out_dir / f"rosters_week_{week}.json"
    if target.exists() and not force:
        print(f"  = rosters_week_{week}.json (already archived)")
        return

    pacer.wait()
    try:
        teams = query.get_league_teams()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! teams: {exc}", file=sys.stderr)
        return

    rosters = {}
    for team in teams:
        team_id = getattr(team, "team_id", None)
        if team_id is None:
            continue
        pacer.wait()
        try:
            roster = query.get_team_roster_by_week(team_id, week)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! roster for team {team_id}: {exc}", file=sys.stderr)
            continue
        rosters[str(team_id)] = {
            "team_id": str(team_id),
            "team_name": _team_name(team),
            "week": week,
            "roster": client.serialize(roster),
        }

    write_json(target, rosters)
    print(f"  + rosters_week_{week}.json ({len(rosters)} teams)")


def pull_matchups(
    query: Any, out_dir: Path, through_week: Optional[int], pacer: Pacer, force: bool
) -> None:
    target = out_dir / "scoreboards.json"
    if target.exists() and not force:
        print("  = scoreboards.json (already archived)")
        return

    through = through_week or final_week(query, out_dir, pacer)
    weeks = {}
    for week in range(1, through + 1):
        pacer.wait()
        try:
            weeks[str(week)] = client.serialize(
                query.get_league_scoreboard_by_week(week)
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! week {week}: {exc}", file=sys.stderr)
    write_json(target, weeks)
    print(f"  + scoreboards.json ({len(weeks)} weeks)")


def pull_season(
    season: int,
    league: str,
    include: List[str],
    pacer: Pacer,
    week: Optional[int] = None,
    force: bool = False,
) -> None:
    out_dir = config.season_dir(season, league)
    print(f"\n{league} {season} -> {out_dir}")
    query = client.for_league(season, league)

    if "core" in include:
        pull_core(query, out_dir, pacer, force)
    if "rosters" in include:
        pull_rosters(query, out_dir, week, pacer, force)
    if "matchups" in include:
        pull_matchups(query, out_dir, week, pacer, force)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, help="Season to pull, e.g. 2025")
    parser.add_argument(
        "--all-seasons",
        action="store_true",
        help="Pull every season recorded in leagues.json",
    )
    parser.add_argument(
        "--league",
        default=config.DEFAULT_LEAGUE,
        help=f"Which configured league (default: {config.DEFAULT_LEAGUE})",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        default=["core", "rosters"],
        choices=["core", "rosters", "matchups"],
        help="Which data sets to pull (default: core rosters)",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Week for rosters/matchups (default: last week of the season)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between API calls (default: {DEFAULT_DELAY_SECONDS})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-request files that are already archived (default: skip them)",
    )
    args = parser.parse_args(argv)

    if args.all_seasons:
        seasons = sorted(
            int(s) for s in config.league_config(args.league).get("seasons", {})
        )
        if not seasons:
            print(
                "No seasons recorded yet. Run: python -m ffball.discover --save",
                file=sys.stderr,
            )
            return 1
    elif args.season:
        seasons = [args.season]
    else:
        parser.error("Pass --season YEAR or --all-seasons")
        return 2

    pacer = Pacer(args.delay)
    started = time.monotonic()
    for season in seasons:
        pull_season(season, args.league, args.include, pacer, args.week, args.force)

    elapsed = time.monotonic() - started
    print(
        f"\nDone. {pacer.requests} request(s) across {len(seasons)} season(s) "
        f"in {elapsed:.0f}s."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli.run(main))
