"""Regression test for the keeper math, using the real 2025 Fourth and 2wenty board.

Run it directly (no pytest needed):

    python tests/test_keepers.py

The draft fixture is deliberately partial: it holds only the picks that landed
on the 2025 end-of-year roster, since those are the only ones keeper cost
depends on. Everyone else is correctly treated as undrafted.

The 2026 ADP numbers below are ESTIMATES used to exercise the ranking, not
Yahoo data. Once OAuth is wired up, `python -m ffball.keepers --season 2025`
replaces them with real ADP.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffball import keepers  # noqa: E402

NUM_TEAMS = 12
UNDRAFTED_COST = 15

# name -> round drafted in 2025 by anybody (None = nobody drafted him)
ROSTER_2025 = {
    "Josh Allen": ("QB", 2),
    "CeeDee Lamb": ("WR", 1),
    "Chris Olave": ("WR", 6),
    "Josh Jacobs": ("RB", 3),
    "Courtland Sutton": ("WR", 5),
    "Jordan Love": ("QB", 13),
    "Ka'imi Fairbairn": ("K", 13),
    "Trey Benson": ("RB", 15),
    "Michael Carter": ("RB", None),
    "Harold Fannin Jr.": ("TE", None),
    "Taysom Hill": ("TE", None),
    "Woody Marks": ("RB", None),
    "Darren Waller": ("TE", None),
    "Keaton Mitchell": ("RB", None),
    "Seahawks": ("DEF", None),
    "Saints": ("DEF", None),
}

# Estimated 2026 ADP round. Not Yahoo data — see module docstring.
ESTIMATED_ADP_ROUND = {
    "CeeDee Lamb": 2.0,
    "Chris Olave": 2.0,
    "Josh Allen": 3.0,
    "Courtland Sutton": 6.5,
    "Harold Fannin Jr.": 7.0,
    "Woody Marks": 9.0,
    "Jordan Love": 11.0,
    "Trey Benson": 13.0,
    "Ka'imi Fairbairn": 14.0,
}

GAME_KEY = "461"


def build_fixture(root: Path) -> Path:
    """Write draft results and an end-of-year roster in the shape pull.py emits."""
    season_dir = root / "fourth_and_2wenty" / "2025"
    season_dir.mkdir(parents=True)

    player_ids = {name: str(1000 + i) for i, name in enumerate(sorted(ROSTER_2025))}

    draft_results = [
        {
            "pick": None,
            "round": rnd,
            "team_key": f"{GAME_KEY}.l.1.t.1",
            "player_key": f"{GAME_KEY}.p.{player_ids[name]}",
        }
        for name, (_pos, rnd) in ROSTER_2025.items()
        if rnd is not None
    ]
    (season_dir / "draft_results.json").write_text(
        json.dumps(draft_results, indent=2), encoding="utf-8"
    )

    players = [
        {
            "player_id": player_ids[name],
            "player_key": f"{GAME_KEY}.p.{player_ids[name]}",
            "name": {"full": name},
            "display_position": pos,
        }
        for name, (pos, _rnd) in ROSTER_2025.items()
    ]
    rosters = {
        "1": {
            "team_id": "1",
            "team_name": "Si Se Puede",
            "week": 17,
            "roster": {"coverage_type": "week", "week": 17, "players": players},
        },
        "2": {
            "team_id": "2",
            "team_name": "Chase'n Th...",
            "week": 17,
            "roster": {"coverage_type": "week", "week": 17, "players": []},
        },
    }
    (season_dir / "rosters_week_17.json").write_text(
        json.dumps(rosters, indent=2), encoding="utf-8"
    )
    return season_dir


def check(label: str, actual, expected) -> None:
    status = "ok  " if actual == expected else "FAIL"
    print(f"  [{status}] {label}: {actual!r}")
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        season_dir = build_fixture(Path(tmp))

        costs = keepers.draft_cost_by_player(season_dir)
        players = keepers.my_roster(season_dir, "Si Se Puede")
        candidates = keepers.build_candidates(
            players,
            costs,
            undrafted_cost=UNDRAFTED_COST,
            already_kept=["Josh Jacobs"],
            num_teams=NUM_TEAMS,
        )
        by_name = {c.name: c in candidates and c for c in candidates}

        print("\nKeeper cost parsing")
        check("roster size", len(candidates), len(ROSTER_2025))
        check("Chris Olave cost round", by_name["Chris Olave"].cost_round, 6)
        check("Chris Olave was drafted", by_name["Chris Olave"].was_drafted, True)
        check("Josh Allen cost round", by_name["Josh Allen"].cost_round, 2)
        check("Harold Fannin Jr. cost round", by_name["Harold Fannin Jr."].cost_round, 15)
        check("Harold Fannin Jr. was drafted", by_name["Harold Fannin Jr."].was_drafted, False)
        # Love was drafted by another manager; cost basis is "any team".
        check("Jordan Love cost round", by_name["Jordan Love"].cost_round, 13)

        print("\nEligibility")
        check(
            "Josh Jacobs ineligible",
            by_name["Josh Jacobs"].ineligible_reason,
            "already kept once",
        )
        check(
            "eligible count",
            len([c for c in candidates if not c.ineligible_reason]),
            len(ROSTER_2025) - 1,
        )

        # Inject estimated ADP the way attach_adp() would.
        for candidate in candidates:
            adp_round = ESTIMATED_ADP_ROUND.get(candidate.name)
            if adp_round is None:
                continue
            candidate.adp_round = adp_round
            candidate.adp_pick = keepers.round_to_pick(adp_round, NUM_TEAMS)

        ranked = keepers.rank(candidates)

        print("\nRanking (curve-adjusted surplus)")
        for i, c in enumerate(ranked[:5], 1):
            if c.surplus_value is None:
                continue
            print(
                f"  {i}. {c.name:<22} cost R{c.cost_round:<3} "
                f"adp R{c.adp_round:<5} rounds {c.surplus_rounds:+.1f}  "
                f"value {c.surplus_value:+.3f}"
            )

        check("best keeper", ranked[0].name, "Chris Olave")
        check("runner up", ranked[1].name, "Harold Fannin Jr.")

        print("\nSanity checks on the value curve")
        # Fannin wins on raw rounds but loses on value: the whole reason the
        # ranking is curve-adjusted rather than a round subtraction.
        fannin = by_name["Harold Fannin Jr."]
        olave = by_name["Chris Olave"]
        check("Fannin beats Olave on raw rounds", fannin.surplus_rounds > olave.surplus_rounds, True)
        check("Olave beats Fannin on value", olave.surplus_value > fannin.surplus_value, True)
        # Keeping a player at roughly his market price is not a bargain.
        check("Josh Allen surplus is negative", by_name["Josh Allen"].surplus_value < 0, True)
        check("CeeDee Lamb surplus is negative", by_name["CeeDee Lamb"].surplus_value < 0, True)

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
