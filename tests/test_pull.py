"""Tests for archive pacing and resumability.

A ~16-season backfill is several hundred requests, so two properties matter and
are easy to regress: calls are spaced out, and anything already on disk is not
requested again. Both are checked here against a stub query, with no network.

Run it directly (no pytest needed):

    python tests/test_pull.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffball import pull  # noqa: E402


class StubModel:
    """Stands in for a yfpy model: readable as attributes, serializes to a dict.

    Both halves matter. Code that has the live object reads attributes, while
    anything reading the archive gets whatever `client.serialize` wrote, and
    those are different shapes.
    """

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)

    def serialized(self) -> dict:
        return dict(self.__dict__)


class StubQuery:
    """Counts calls so tests can assert what was and wasn't requested."""

    def __init__(self, end_week: int = 17, teams: int = 12) -> None:
        self.calls: list[str] = []
        self._end_week = end_week
        self._teams = teams

    def _record(self, name: str):
        self.calls.append(name)

    def get_league_metadata(self):
        self._record("metadata")
        return StubModel(end_week=self._end_week, current_week=self._end_week)

    def get_league_settings(self):
        self._record("settings")
        return {"scoring": "half-ppr"}

    def get_league_standings(self):
        self._record("standings")
        return {"teams": []}

    def get_league_teams(self):
        self._record("teams")
        return [
            StubModel(team_id=i, name=f"Team {i}") for i in range(1, self._teams + 1)
        ]

    def get_league_draft_results(self):
        self._record("draft_results")
        return [{"round": 1, "pick": 1, "player_key": "461.p.1"}]

    def get_league_transactions(self):
        self._record("transactions")
        return []

    def get_team_roster_by_week(self, team_id, week):
        self._record(f"roster:{team_id}:{week}")
        return {"players": []}

    def get_league_scoreboard_by_week(self, week):
        self._record(f"scoreboard:{week}")
        return {"week": week}


def check(label: str, actual, expected) -> None:
    status = "ok  " if actual == expected else "FAIL"
    print(f"  [{status}] {label}: {actual!r}")
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


def main() -> int:
    print("\nPacer")
    pacer = pull.Pacer(delay=0.05)
    start = time.monotonic()
    for _ in range(4):
        pacer.wait()
    elapsed = time.monotonic() - start
    check("counts every request", pacer.requests, 4)
    # First call is immediate, the next three each wait.
    check("first call is not delayed", elapsed >= 0.15, True)
    check("does not over-wait", elapsed < 0.5, True)
    check("delay=0 disables pacing", pull.Pacer(0).delay, 0.0)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "2019"

        print("\nFirst pull writes everything")
        q = StubQuery()
        pacer = pull.Pacer(0)
        pull.pull_core(q, out, pacer, force=False)
        check("one request per core endpoint", len(q.calls), len(pull.CORE_ENDPOINTS))
        check("files written", sorted(p.name for p in out.glob("*.json")),
              sorted(f"{n}.json" for n in pull.CORE_ENDPOINTS))

        print("\nRe-running skips what is archived")
        q2 = StubQuery()
        pull.pull_core(q2, out, pull.Pacer(0), force=False)
        check("no requests made", q2.calls, [])

        print("\n--force re-requests")
        q3 = StubQuery()
        pull.pull_core(q3, out, pull.Pacer(0), force=True)
        check("all endpoints re-requested", len(q3.calls), len(pull.CORE_ENDPOINTS))

        print("\nfinal_week prefers the archived metadata")
        q4 = StubQuery()
        week = pull.final_week(q4, out, pull.Pacer(0))
        check("week read from disk", week, 17)
        check("no request spent", q4.calls, [])

        print("\nfinal_week falls back to the API when nothing is archived")
        empty = Path(tmp) / "empty"
        empty.mkdir()
        q5 = StubQuery(end_week=16)
        check("week from API", pull.final_week(q5, empty, pull.Pacer(0)), 16)
        check("one request spent", q5.calls, ["metadata"])

        print("\nRosters: one request for teams, then one per team")
        q6 = StubQuery(teams=12)
        pull.pull_rosters(q6, out, week=17, pacer=pull.Pacer(0), force=False)
        check("teams + 12 rosters", len(q6.calls), 13)
        check("roster file written", (out / "rosters_week_17.json").exists(), True)

        print("\nRosters skip on re-run")
        q7 = StubQuery(teams=12)
        pull.pull_rosters(q7, out, week=17, pacer=pull.Pacer(0), force=False)
        check("no requests made", q7.calls, [])

        print("\nMatchups: one request per week")
        q8 = StubQuery()
        pull.pull_matchups(q8, out, through_week=5, pacer=pull.Pacer(0), force=False)
        check("5 weekly requests", len(q8.calls), 5)
        saved = json.loads((out / "scoreboards.json").read_text(encoding="utf-8"))
        check("5 weeks saved", sorted(saved), ["1", "2", "3", "4", "5"])

        print("\nA failing endpoint does not abort the rest")
        broken = Path(tmp) / "broken"
        q9 = StubQuery()
        q9.get_league_standings = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        pull.pull_core(q9, broken, pull.Pacer(0), force=False)
        written = sorted(p.stem for p in broken.glob("*.json"))
        check("standings skipped, rest written", "standings" in written, False)
        check("other endpoints still written", len(written), len(pull.CORE_ENDPOINTS) - 1)

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
