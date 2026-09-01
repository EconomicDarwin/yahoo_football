"""Shared entry-point helpers.

Configuration problems (no credentials yet, a season that hasn't been pulled)
and Yahoo authorization problems are expected states with actionable fixes, not
crashes, so they print as plain text instead of a traceback.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional

from .config import ConfigError

# Yahoo's response when the OAuth token is valid but the app has not been
# granted Fantasy Sports access. The handshake succeeds and only the fantasy
# endpoints reject, so this is easy to mistake for a credentials problem.
FANTASY_ACCESS_MARKER = "additional_authorization_required"

FANTASY_ACCESS_HELP = """
Yahoo accepted your login, but this app is not authorized for Fantasy Sports data.

Yahoo removed the Fantasy Sports permission from the app creation form and now
gates the API behind a review. Nothing is wrong with your credentials or setup:
the OAuth handshake completed and your tokens are saved, so once access is
granted these same credentials will work with no need to log in again.

  Apply here:  https://sports.yahoo.com/developer/access/

Draft answers written for this project are in SETUP.md, under
"Fantasy Sports API access". Yahoo closes vague submissions without replying,
so be specific and say plainly that this is personal, single-league use.
"""


def looks_unauthorized(exc: BaseException) -> bool:
    """True if this exception is Yahoo refusing fantasy access, not a real bug."""
    text = str(exc)
    if FANTASY_ACCESS_MARKER in text:
        return True
    has_code = any(c in text for c in ("401", "403", "Unauthorized", "Forbidden"))
    mentions_auth = "credential" in text.lower() or "auth" in text.lower()
    return has_code and mentions_auth


def run(
    main_fn: Callable[[Optional[List[str]]], int], argv: Optional[List[str]] = None
) -> int:
    try:
        return main_fn(argv)
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - translate the one expected API refusal
        if looks_unauthorized(exc):
            print(FANTASY_ACCESS_HELP, file=sys.stderr)
            return 2
        raise
