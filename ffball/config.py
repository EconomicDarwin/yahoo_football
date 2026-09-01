"""Project paths and league configuration.

League identity (which Yahoo league_id maps to which season) lives in
``leagues.json`` so that the code stays league-agnostic and a new league is a
config change rather than a code change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# yfpy takes the *directory* holding .env, not the file itself.
ENV_DIR = PROJECT_ROOT
ENV_FILE = PROJECT_ROOT / ".env"

DATA_DIR = PROJECT_ROOT / "data"
LEAGUES_FILE = PROJECT_ROOT / "leagues.json"

DEFAULT_LEAGUE = "fourth_and_2wenty"


class ConfigError(RuntimeError):
    """Raised when the on-disk configuration cannot satisfy a request."""


def load_leagues() -> Dict[str, Any]:
    if not LEAGUES_FILE.exists():
        raise ConfigError(f"Missing {LEAGUES_FILE}. See README.md.")
    return json.loads(LEAGUES_FILE.read_text(encoding="utf-8"))


def save_leagues(leagues: Dict[str, Any]) -> None:
    LEAGUES_FILE.write_text(
        json.dumps(leagues, indent=2) + "\n", encoding="utf-8"
    )


def league_config(name: str = DEFAULT_LEAGUE) -> Dict[str, Any]:
    leagues = load_leagues()
    if name not in leagues:
        known = ", ".join(sorted(leagues)) or "(none)"
        raise ConfigError(f"Unknown league {name!r}. Configured leagues: {known}")
    return leagues[name]


def league_id_for_season(season: int, name: str = DEFAULT_LEAGUE) -> str:
    """Return the Yahoo league_id for a season, or explain how to populate it."""
    seasons = league_config(name).get("seasons", {})
    league_id = seasons.get(str(season))
    if not league_id:
        raise ConfigError(
            f"No league_id recorded for {name} season {season}.\n"
            f"Run:  python -m ffball.discover --save\n"
            f"to look up your league IDs and write them into {LEAGUES_FILE.name}."
        )
    return str(league_id)


def season_dir(season: int, name: str = DEFAULT_LEAGUE) -> Path:
    return DATA_DIR / name / str(season)


def env_is_configured() -> bool:
    """True if .env exists and carries a consumer key that is not the placeholder."""
    if not ENV_FILE.exists():
        return False
    text = ENV_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("YAHOO_CONSUMER_KEY="):
            value = line.split("=", 1)[1].strip()
            return bool(value) and "paste-your" not in value
    return False
