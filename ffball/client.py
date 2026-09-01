"""Authenticated Yahoo Fantasy API client.

Wraps :class:`yfpy.query.YahooFantasySportsQuery` so callers never have to think
about where credentials live or how a past season's league key is built.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from yfpy.query import YahooFantasySportsQuery

from . import config

# yfpy requires a league_id at construction time, but the user/game endpoints
# used for discovery do not consult it.
PLACEHOLDER_LEAGUE_ID = "0"

SETUP_HINT = (
    "Yahoo credentials are not configured yet.\n"
    f"  1. Copy {config.PROJECT_ROOT / '.env.example'} to "
    f"{config.ENV_FILE}\n"
    "  2. Fill in YAHOO_CONSUMER_KEY and YAHOO_CONSUMER_SECRET from your Yahoo app\n"
    "See README.md -> 'One-time Yahoo setup' for how to create the app."
)


def make_query(
    league_id: str = PLACEHOLDER_LEAGUE_ID,
    season: Optional[int] = None,
    game_code: str = "nfl",
) -> YahooFantasySportsQuery:
    """Build an authenticated query object.

    The first call opens a browser for Yahoo's consent screen and then writes
    the resulting tokens back into ``.env``; later calls refresh silently.

    Args:
        league_id: Yahoo league_id (the bare number, not the full league key).
        season: If given, pin the query to that season's league key so that
            past seasons can be read. Without it Yahoo answers for the current
            season only.
    """
    if not config.env_is_configured():
        raise config.ConfigError(SETUP_HINT)

    query = YahooFantasySportsQuery(
        league_id=str(league_id),
        game_code=game_code,
        env_file_location=config.ENV_DIR,
        save_token_data_to_env_file=True,
        browser_callback=True,
    )

    if season is not None:
        # get_league_key(season) resolves the season's game key and composes
        # "<game_key>.l.<league_id>". Assigning it makes every later league or
        # team call resolve against that season instead of the current one.
        query.league_key = query.get_league_key(int(season))

    return query


def for_league(
    season: int, name: str = config.DEFAULT_LEAGUE
) -> YahooFantasySportsQuery:
    """Build a query pinned to a configured league's given season."""
    cfg = config.league_config(name)
    return make_query(
        league_id=config.league_id_for_season(season, name),
        season=season,
        game_code=cfg.get("game_code", "nfl"),
    )


def serialize(obj: Any) -> Any:
    """Convert yfpy model objects (or lists of them) into plain JSON types."""
    if isinstance(obj, list):
        return [serialize(item) for item in obj]
    if hasattr(obj, "serialized"):
        return obj.serialized()
    if hasattr(obj, "to_json"):
        return json.loads(obj.to_json())
    return obj


def player_id_of(player_key: str) -> str:
    """Strip the season-specific game prefix off a player key.

    Yahoo player keys look like ``461.p.31883``. The game key changes every
    season, so only the trailing player id is stable across years.
    """
    return str(player_key).rsplit(".", 1)[-1]


def my_team(query: YahooFantasySportsQuery) -> Optional[Any]:
    """Return the team in the current league owned by the logged-in user."""
    for team in query.get_league_teams():
        if getattr(team, "is_owned_by_current_login", 0):
            return team
    return None


def teams(query: YahooFantasySportsQuery) -> List[Any]:
    return query.get_league_teams()
