"""Rank keeper candidates by draft-capital surplus.

The league rule this encodes:

  * You keep one player off your end-of-year roster.
  * The cost is the round that player was drafted in last season *by anybody*,
    not necessarily by you.
  * A player nobody drafted costs a 15th.
  * A player you already kept once cannot be kept again.

Surplus is the whole game: what a player would cost in this year's draft (his
current ADP) minus what the keeper rule charges you.

Counting that surplus in *rounds* is misleading, though, because draft value is
convex. Turning a 15th into a 7th is eight rounds but moves you between two
cheap picks, while turning a 6th into a 2nd is four rounds but buys a genuine
first-round-caliber player. So the ranking sorts on curve-adjusted value, and
prints the raw round difference alongside it for sanity.

Usage:
    python -m ffball.keepers --season 2025
    python -m ffball.keepers --season 2025 --offline
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import cli, client, config

# Draft pick value decays roughly exponentially. TAU is the number of picks over
# which value falls by 1/e. About 40 picks (a bit over 3 rounds in a 12-team league)
# reproduces the usual shape of fantasy auction values well enough to rank
# keepers. Override per league with "pick_value_tau" in leagues.json.
DEFAULT_PICK_VALUE_TAU = 40.0


def pick_value(pick: float, tau: float = DEFAULT_PICK_VALUE_TAU) -> float:
    """Relative value of a draft pick, normalized so pick 1 == 1.0."""
    return math.exp(-(float(pick) - 1.0) / tau)


def round_to_pick(round_number: float, num_teams: int) -> float:
    """Convert a round to a representative overall pick (its midpoint)."""
    return (float(round_number) - 0.5) * num_teams


@dataclass
class Candidate:
    player_id: str
    name: str
    position: str
    cost_round: int
    was_drafted: bool
    num_teams: int = 12
    tau: float = DEFAULT_PICK_VALUE_TAU
    adp_pick: Optional[float] = None
    adp_round: Optional[float] = None
    percent_drafted: Optional[float] = None
    ineligible_reason: Optional[str] = None

    @property
    def cost_pick(self) -> float:
        return round_to_pick(self.cost_round, self.num_teams)

    @property
    def surplus_rounds(self) -> Optional[float]:
        """Raw round difference. Easy to read, but treats all rounds as equal."""
        if self.adp_round is None:
            return None
        return self.cost_round - self.adp_round

    @property
    def surplus_value(self) -> Optional[float]:
        """Curve-adjusted surplus: value acquired minus draft capital spent."""
        if self.adp_pick is None:
            return None
        return pick_value(self.adp_pick, self.tau) - pick_value(self.cost_pick, self.tau)


def _text(value: Any) -> str:
    """yfpy returns some strings as bytes and some names as nested dicts."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        for key in ("full", "ascii_full", "first", "value"):
            if value.get(key):
                return _text(value[key])
        return ""
    return "" if value is None else str(value)


def _load(path: Path) -> Any:
    if not path.exists():
        raise config.ConfigError(
            f"Missing {path}.\nRun:  python -m ffball.pull --season {path.parent.name}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def draft_cost_by_player(season_dir: Path) -> Dict[str, int]:
    """Map player_id -> round drafted, from the season's draft board."""
    results = _load(season_dir / "draft_results.json")
    costs: Dict[str, int] = {}
    for pick in results:
        if not isinstance(pick, dict):
            continue
        player_key = pick.get("player_key")
        rnd = pick.get("round")
        if not player_key or not rnd:
            continue
        costs[client.player_id_of(player_key)] = int(rnd)
    return costs


def my_roster(season_dir: Path, my_team_name: str) -> List[Dict[str, Any]]:
    """Pull the end-of-year roster for the configured team."""
    roster_files = sorted(season_dir.glob("rosters_week_*.json"))
    if not roster_files:
        raise config.ConfigError(
            f"No roster file in {season_dir}.\n"
            f"Run:  python -m ffball.pull --season {season_dir.name} --include rosters"
        )
    # Highest week number = end of year.
    latest = max(roster_files, key=lambda p: int(p.stem.rsplit("_", 1)[-1]))
    rosters = _load(latest)

    wanted = my_team_name.strip().lower()
    for entry in rosters.values():
        if _text(entry.get("team_name")).strip().lower() == wanted:
            return (entry.get("roster") or {}).get("players", []) or []

    names = ", ".join(sorted(_text(e.get("team_name")) for e in rosters.values()))
    raise config.ConfigError(
        f"No team named {my_team_name!r} in {latest.name}.\n"
        f"Teams found: {names}\n"
        f"Fix my_team_name in {config.LEAGUES_FILE.name}."
    )


def build_candidates(
    players: List[Dict[str, Any]],
    costs: Dict[str, int],
    undrafted_cost: int,
    already_kept: List[str],
    num_teams: int = 12,
    tau: float = DEFAULT_PICK_VALUE_TAU,
) -> List[Candidate]:
    kept_lower = {n.strip().lower() for n in already_kept if n}
    candidates = []
    for player in players:
        player_id = _text(player.get("player_id")) or client.player_id_of(
            _text(player.get("player_key"))
        )
        name = _text(player.get("name")) or _text(player.get("full_name"))
        candidate = Candidate(
            player_id=player_id,
            name=name,
            position=_text(player.get("display_position"))
            or _text(player.get("primary_position")),
            cost_round=costs.get(player_id, undrafted_cost),
            was_drafted=player_id in costs,
            num_teams=num_teams,
            tau=tau,
        )
        if name.strip().lower() in kept_lower:
            candidate.ineligible_reason = "already kept once"
        candidates.append(candidate)
    return candidates


def attach_adp(
    candidates: List[Candidate], upcoming_season: int, league: str
) -> bool:
    """Fill in current-season ADP. Returns False if Yahoo has none yet."""
    cfg = config.league_config(league)
    num_teams = int(cfg.get("num_teams") or 12)

    # ADP lives on the *upcoming* season's game, so this query is not pinned to
    # the completed season the rest of the analysis reads.
    query = client.make_query(game_code=cfg.get("game_code", "nfl"))
    try:
        game_key = query.get_game_key_by_season(int(upcoming_season))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not resolve {upcoming_season} game key: {exc}", file=sys.stderr)
        return False

    got_any = False
    for candidate in candidates:
        if candidate.ineligible_reason:
            continue
        try:
            player = query.get_player_draft_analysis(
                f"{game_key}.p.{candidate.player_id}"
            )
        except Exception as exc:  # noqa: BLE001 - one missing player shouldn't kill the run
            print(f"  ! ADP for {candidate.name}: {exc}", file=sys.stderr)
            continue

        analysis = getattr(player, "draft_analysis", None)
        if not analysis:
            continue
        pick = getattr(analysis, "average_pick", None)
        rnd = getattr(analysis, "average_round", None)
        pct = getattr(analysis, "percent_drafted", None)

        if pick:
            candidate.adp_pick = float(pick)
            got_any = True
        if rnd:
            candidate.adp_round = float(rnd)
        elif pick:
            candidate.adp_round = math.ceil(float(pick) / num_teams)
        if pct:
            candidate.percent_drafted = float(pct)

    return got_any


def rank(candidates: List[Candidate]) -> List[Candidate]:
    """Eligible candidates, best keeper value first."""
    eligible = [c for c in candidates if not c.ineligible_reason]
    return sorted(
        eligible,
        key=lambda c: (
            c.surplus_value if c.surplus_value is not None else float("-inf"),
            c.cost_round,
        ),
        reverse=True,
    )


def report(candidates: List[Candidate], upcoming_season: int, have_adp: bool) -> None:
    ranked = rank(candidates)

    print(f"\nKeeper candidates for {upcoming_season}")
    print("=" * 80)
    print(
        f"{'Player':<26}{'Pos':<6}{'Cost':<7}{'ADP rd':<9}"
        f"{'+/- rds':<10}{'Value':<9}%Drafted"
    )
    print("-" * 80)
    for c in ranked:
        cost = f"R{c.cost_round}" + ("" if c.was_drafted else "*")
        adp = f"{c.adp_round:.1f}" if c.adp_round is not None else "-"
        rounds = f"{c.surplus_rounds:+.1f}" if c.surplus_rounds is not None else "-"
        value = f"{c.surplus_value:+.3f}" if c.surplus_value is not None else "-"
        pct = f"{c.percent_drafted:.0%}" if c.percent_drafted is not None else "-"
        print(f"{c.name:<26}{c.position:<6}{cost:<7}{adp:<9}{rounds:<10}{value:<9}{pct}")

    print("-" * 80)
    print("* charged the undrafted-player round (nobody drafted him last season).")
    print("Value = curve-adjusted surplus, which is what the ranking sorts on.")

    ineligible = [c for c in candidates if c.ineligible_reason]
    if ineligible:
        print("\nIneligible:")
        for c in ineligible:
            print(f"  {c.name} ({c.ineligible_reason})")

    if not have_adp:
        print(
            "\nNo ADP available from Yahoo yet, so surplus cannot be computed."
            "\nRe-run closer to the draft once the new season's board opens."
        )
        return

    if ranked and ranked[0].surplus_value is not None:
        best = ranked[0]
        print(
            f"\nBest value: {best.name}, costs R{best.cost_round}, "
            f"going around round {best.adp_round:.1f} "
            f"({best.surplus_rounds:+.1f} rounds)."
        )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="The completed season that sets keeper cost and roster, e.g. 2025",
    )
    parser.add_argument(
        "--for-season",
        type=int,
        default=None,
        help="Upcoming draft season (default: --season + 1)",
    )
    parser.add_argument(
        "--league",
        default=config.DEFAULT_LEAGUE,
        help=f"Which configured league (default: {config.DEFAULT_LEAGUE})",
    )
    parser.add_argument(
        "--team",
        default=None,
        help="Team name to analyze (default: my_team_name from leagues.json)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the ADP lookup and list keeper costs only",
    )
    args = parser.parse_args(argv)

    upcoming = args.for_season or args.season + 1
    cfg = config.league_config(args.league)
    rules = cfg.get("keeper_rules", {})
    undrafted_cost = int(rules.get("undrafted_cost_round", 15))
    num_teams = int(cfg.get("num_teams") or 12)
    tau = float(cfg.get("pick_value_tau") or DEFAULT_PICK_VALUE_TAU)

    team_name = args.team or cfg.get("my_team_name") or ""
    if not team_name:
        print("Set my_team_name in leagues.json or pass --team.", file=sys.stderr)
        return 1

    season_dir = config.season_dir(args.season, args.league)
    costs = draft_cost_by_player(season_dir)
    players = my_roster(season_dir, team_name)

    already_kept: List[str] = []
    if not rules.get("repeat_keeps_allowed", False):
        already_kept = list(cfg.get("keeper_history", {}).values())

    candidates = build_candidates(
        players, costs, undrafted_cost, already_kept, num_teams, tau
    )
    if not candidates:
        print(f"No players on {team_name}'s end-of-year roster.", file=sys.stderr)
        return 1

    have_adp = False if args.offline else attach_adp(candidates, upcoming, args.league)

    report(candidates, upcoming, have_adp)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli.run(main))
