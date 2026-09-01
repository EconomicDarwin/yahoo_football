"""Archive a season of league data from Yahoo to local JSON.

Everything downstream (keeper math, record books, power rankings) reads these
files rather than hitting the API again, so analysis stays fast, reproducible,
and works offline. It also guards against Yahoo aging out old seasons.

Usage:
    python -m ffball.pull --season 2025
    python -m ffball.pull --season 2025 --include core rosters
    python -m ffball.pull --all-seasons
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import cli, client, config

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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )


def pull_core(query: Any, out_dir: Path) -> List[str]:
    written = []
    for name, fetch in CORE_ENDPOINTS.items():
        try:
            payload = client.serialize(fetch(query))
        except Exception as exc:  # noqa: BLE001 - keep going; some are season-dependent
            print(f"  ! {name}: {exc}", file=sys.stderr)
            continue
        write_json(out_dir / f"{name}.json", payload)
        written.append(name)
        print(f"  + {name}.json")
    return written


def final_week(query: Any, default: int = 17) -> int:
    """Best guess at the last scoring week of the season."""
    try:
        meta = query.get_league_metadata()
    except Exception:  # noqa: BLE001
        return default
    for attr in ("end_week", "current_week"):
        value = getattr(meta, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return default


def pull_rosters(query: Any, out_dir: Path, week: int | None) -> None:
    """Save each team's roster for a week (default: the last week of the season).

    The final-week roster is what keeper eligibility is judged against, so this
    is the file the keeper analysis depends on.
    """
    week = week or final_week(query)
    rosters = {}
    for team in query.get_league_teams():
        team_id = getattr(team, "team_id", None)
        if team_id is None:
            continue
        name = getattr(team, "name", "")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        try:
            roster = query.get_team_roster_by_week(team_id, week)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! roster for team {team_id}: {exc}", file=sys.stderr)
            continue
        rosters[str(team_id)] = {
            "team_id": str(team_id),
            "team_name": name,
            "week": week,
            "roster": client.serialize(roster),
        }

    write_json(out_dir / f"rosters_week_{week}.json", rosters)
    print(f"  + rosters_week_{week}.json ({len(rosters)} teams)")


def pull_matchups(query: Any, out_dir: Path, through_week: int | None) -> None:
    through = through_week or final_week(query)
    weeks = {}
    for week in range(1, through + 1):
        try:
            weeks[str(week)] = client.serialize(
                query.get_league_scoreboard_by_week(week)
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! week {week}: {exc}", file=sys.stderr)
    write_json(out_dir / "scoreboards.json", weeks)
    print(f"  + scoreboards.json ({len(weeks)} weeks)")


def pull_season(
    season: int,
    league: str,
    include: List[str],
    week: int | None = None,
) -> None:
    out_dir = config.season_dir(season, league)
    print(f"\n{league} {season} -> {out_dir}")
    query = client.for_league(season, league)

    if "core" in include:
        pull_core(query, out_dir)
    if "rosters" in include:
        pull_rosters(query, out_dir, week)
    if "matchups" in include:
        pull_matchups(query, out_dir, week)


def main(argv: List[str] | None = None) -> int:
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

    for season in seasons:
        pull_season(season, args.league, args.include, args.week)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli.run(main))
