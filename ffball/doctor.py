"""Check the setup and say exactly what is wrong and how to fix it.

Run this after each setup step. It checks everything it can offline, and with
--online also makes one real API call to prove the credentials work.

Usage:
    python -m ffball.doctor
    python -m ffball.doctor --online
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import cli, config

OK, WARN, FAIL = "ok", "warn", "FAIL"

# Yahoo client IDs are long and start with "dj0y"; secrets are 40 hex chars.
EXPECTED_KEY_PREFIX = "dj0y"
EXPECTED_SECRET_LEN = 40


class Report:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []
        self.failed = False

    def add(self, status: str, label: str, detail: str = "") -> None:
        self.rows.append((status, label, detail))
        if status == FAIL:
            self.failed = True

    def render(self) -> None:
        width = max(len(label) for _s, label, _d in self.rows) + 2
        for status, label, detail in self.rows:
            marker = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}[status]
            print(f"{marker} {label:<{width}}{detail}")


def has_bom() -> bool:
    """A UTF-8 BOM silently breaks the FIRST variable in the file.

    python-dotenv reads .env as plain UTF-8, so a leading BOM becomes part of
    the first key's name and that variable is never found. Notepad and
    PowerShell's `Out-File -Encoding utf8` both write one by default, which
    makes this an easy mistake with a very confusing symptom.
    """
    return config.ENV_FILE.read_bytes()[:3] == b"\xef\xbb\xbf"


def read_env_lines() -> List[str]:
    # utf-8-sig so the rest of the checks still work on a BOM'd file; has_bom()
    # reports the problem separately.
    return config.ENV_FILE.read_text(encoding="utf-8-sig").splitlines()


def env_value(lines: List[str], name: str) -> Optional[str]:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value
    return None


def check_dependencies(report: Report) -> None:
    report.add(OK, "Python", f"{sys.version.split()[0]} at {Path(sys.executable).name}")
    try:
        import yfpy  # noqa: F401
        from importlib.metadata import version

        report.add(OK, "yfpy installed", version("yfpy"))
    except Exception as exc:  # noqa: BLE001
        report.add(
            FAIL,
            "yfpy installed",
            f"{exc} — run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt",
        )

    if ".venv" not in sys.executable:
        report.add(
            WARN,
            "using the project venv",
            "you are on a different interpreter; use .\\.venv\\Scripts\\python.exe",
        )
    else:
        report.add(OK, "using the project venv", "")


def check_env_file(report: Report) -> bool:
    if not config.ENV_FILE.exists():
        report.add(
            FAIL,
            ".env exists",
            "not found — see SETUP.md step 2 for the BOM-free command that creates it",
        )
        return False
    report.add(OK, ".env exists", str(config.ENV_FILE))

    lines = read_env_lines()
    ready = True

    if has_bom():
        report.add(
            FAIL,
            ".env encoding",
            "file starts with a UTF-8 BOM, which hides the first variable — "
            "rewrite it with: Set-Content .env -Encoding ascii",
        )
        ready = False
    else:
        report.add(OK, ".env encoding", "no BOM")

    for name, expectation in (
        ("YAHOO_CONSUMER_KEY", EXPECTED_KEY_PREFIX),
        ("YAHOO_CONSUMER_SECRET", None),
    ):
        raw = env_value(lines, name)
        if raw is None:
            report.add(FAIL, name, "missing from .env")
            ready = False
            continue

        value = raw.strip()
        if not value or "paste-your" in value:
            report.add(FAIL, name, "still the placeholder — paste the real value")
            ready = False
            continue
        if raw != raw.strip():
            report.add(WARN, name, "has surrounding whitespace; remove it")
        if value[0] in "\"'" or value[-1] in "\"'":
            report.add(FAIL, name, "wrapped in quotes — remove them")
            ready = False
            continue

        if expectation and not value.startswith(expectation):
            report.add(
                WARN,
                name,
                f"does not start with {expectation!r}; double-check you copied the Client ID",
            )
        elif name == "YAHOO_CONSUMER_SECRET" and len(value) != EXPECTED_SECRET_LEN:
            report.add(
                WARN,
                name,
                f"is {len(value)} chars, expected {EXPECTED_SECRET_LEN}; double-check the Client Secret",
            )
        else:
            report.add(OK, name, f"set ({len(value)} chars)")

    token = env_value(lines, "YAHOO_ACCESS_TOKEN") or env_value(
        lines, "YAHOO_ACCESS_TOKEN_JSON"
    )
    if token and token.strip():
        report.add(OK, "logged in", "access token present")
    else:
        report.add(
            WARN,
            "logged in",
            "no token yet — run: python -m ffball.discover --save",
        )
    return ready


def check_gitignore(report: Report) -> None:
    try:
        result = subprocess.run(
            ["git", "check-ignore", str(config.ENV_FILE)],
            capture_output=True,
            text=True,
            cwd=config.PROJECT_ROOT,
        )
    except FileNotFoundError:
        report.add(WARN, ".env is gitignored", "git not on PATH; could not verify")
        return

    if result.returncode == 0:
        report.add(OK, ".env is gitignored", "credentials will not be committed")
    else:
        report.add(
            FAIL,
            ".env is gitignored",
            "NOT ignored — do not commit until fixed",
        )


def check_leagues(report: Report) -> None:
    try:
        leagues = config.load_leagues()
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "leagues.json parses", str(exc))
        return
    report.add(OK, "leagues.json parses", f"{len(leagues)} league(s) configured")

    seasons = leagues.get(config.DEFAULT_LEAGUE, {}).get("seasons", {})
    if seasons:
        years = sorted(seasons)
        report.add(
            OK,
            "seasons recorded",
            f"{len(years)} ({years[0]}-{years[-1]})",
        )
    else:
        report.add(
            WARN,
            "seasons recorded",
            "none yet — run: python -m ffball.discover --save",
        )


def check_online(report: Report) -> None:
    # get_current_user() hits fantasysports.yahooapis.com, so it doubles as a
    # test of whether this account actually has Fantasy Sports API access.
    try:
        from . import client

        query = client.make_query()
        user = query.get_current_user()
        name = getattr(user, "guid", None) or "authenticated"
        report.add(OK, "live API call", f"Yahoo answered ({name})")
        report.add(OK, "fantasy API access", "granted")
    except Exception as exc:  # noqa: BLE001
        if cli.looks_unauthorized(exc):
            report.add(OK, "live API call", "reached Yahoo; credentials accepted")
            report.add(
                FAIL,
                "fantasy API access",
                "NOT granted — apply at https://sports.yahoo.com/developer/access/ "
                "(see SETUP.md)",
            )
        else:
            report.add(FAIL, "live API call", f"{type(exc).__name__}: {exc}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--online",
        action="store_true",
        help="Also make one real Yahoo API call to prove the credentials work",
    )
    args = parser.parse_args(argv)

    report = Report()
    print(f"\nChecking {config.PROJECT_ROOT}\n")

    check_dependencies(report)
    creds_ready = check_env_file(report)
    check_gitignore(report)
    check_leagues(report)

    if args.online:
        if creds_ready:
            check_online(report)
        else:
            report.add(WARN, "live API call", "skipped — fix the credential errors first")

    report.render()

    if report.failed:
        print("\nSomething needs fixing above before the next step.\n")
        return 1
    print("\nAll good.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli.run(main))
