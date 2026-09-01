"""Discover which Yahoo leagues this account has played in, and when.

Yahoo identifies a league by a per-season key like ``461.l.123456``. The
``123456`` half is usually stable year to year, but the game-key half is not,
and leagues that were re-created will change entirely. So rather than guessing,
this asks Yahoo directly and records the answer in ``leagues.json``.

Usage:
    python -m ffball.discover
    python -m ffball.discover --save
    python -m ffball.discover --save --match "fourth"
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Tuple

from . import cli, client, config


def collect(game_code: str = "nfl") -> List[Tuple[int, str, str]]:
    """Return (season, league_id, league_name) for every league on the account."""
    query = client.make_query(game_code=game_code)

    found: List[Tuple[int, str, str]] = []
    for game in query.get_user_games():
        game_key = getattr(game, "game_key", None)
        season = getattr(game, "season", None)
        if not game_key:
            continue
        try:
            leagues = query.get_user_leagues_by_game_key(game_key)
        except Exception as exc:  # noqa: BLE001 - a dead season shouldn't abort the sweep
            print(f"  ! could not read season {season}: {exc}", file=sys.stderr)
            continue

        for league in leagues or []:
            league_key = getattr(league, "league_key", "") or ""
            # "461.l.123456" -> "123456"
            league_id = league_key.rsplit(".", 1)[-1]
            name = getattr(league, "name", "") or "(unnamed)"
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            found.append((int(season), league_id, name))

    found.sort()
    return found


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--league",
        default=config.DEFAULT_LEAGUE,
        help=f"Config key to write under (default: {config.DEFAULT_LEAGUE})",
    )
    parser.add_argument(
        "--match",
        default=None,
        help="Case-insensitive substring of the league name, when the account "
        "has more than one league in a season.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Write the discovered season -> league_id map into leagues.json",
    )
    args = parser.parse_args(argv)

    cfg = config.league_config(args.league)
    rows = collect(cfg.get("game_code", "nfl"))

    if not rows:
        print("No leagues found for this Yahoo account.")
        return 1

    print(f"{'Season':<8}{'League ID':<12}League name")
    print("-" * 52)
    for season, league_id, name in rows:
        print(f"{season:<8}{league_id:<12}{name}")

    if not args.save:
        print("\nRe-run with --save to record these in leagues.json.")
        return 0

    needle = (args.match or "").lower()
    by_season: Dict[str, str] = {}
    ambiguous: List[int] = []
    for season, league_id, name in rows:
        if needle and needle not in name.lower():
            continue
        key = str(season)
        if key in by_season and by_season[key] != league_id:
            ambiguous.append(season)
        by_season[key] = league_id

    if ambiguous:
        seasons = ", ".join(str(s) for s in sorted(set(ambiguous)))
        print(
            f"\nMore than one league matched in season(s) {seasons}.\n"
            "Re-run with --match <part of the league name> to disambiguate.",
            file=sys.stderr,
        )
        return 2

    leagues = config.load_leagues()
    leagues[args.league].setdefault("seasons", {})
    leagues[args.league]["seasons"] = dict(sorted(by_season.items()))
    config.save_leagues(leagues)

    print(f"\nSaved {len(by_season)} season(s) to {config.LEAGUES_FILE.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli.run(main))
