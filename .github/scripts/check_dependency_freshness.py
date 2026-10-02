"""Report when newer stable Home Assistant / test-harness releases are available.

CI runs against uv.lock, so the versions under test are exactly what the
lockfile says - which is not necessarily what users run, because new stable
releases appear between lock refreshes and nobody is forced to take them.

This script is run on a schedule. It compares the locked versions against the
latest *stable* releases on PyPI and exits non-zero when an update is worth
considering, so the drift is visible instead of hidden.

Note this repository pins a *stable* Home Assistant, so the "lock is on a
pre-release" branch below normally does not trigger. It is kept because the
sibling ha-solar-ac-controller repository does pin a pre-release, and the
comparison logic is shared. uv.lock may legitimately contain more than one
homeassistant entry for different resolution markers; the highest is used.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from packaging.version import InvalidVersion, Version

PYPI = "https://pypi.org/pypi/{package}/json"


def latest_stable(package: str) -> str | None:
    """Return the newest non-prerelease version of ``package``."""
    with urllib.request.urlopen(PYPI.format(package=package), timeout=30) as resp:
        data = json.load(resp)

    candidates = []
    for raw in data["releases"]:
        try:
            ver = Version(raw)
        except InvalidVersion:
            continue
        if ver.is_prerelease or ver.is_devrelease:
            continue
        candidates.append(ver)
    return str(max(candidates)) if candidates else None


def locked_version(package: str) -> str | None:
    """Return the highest version of ``package`` present in uv.lock."""
    with open("uv.lock", encoding="utf-8") as handle:
        lock = handle.read()

    versions = re.findall(rf'\[\[package\]\]\nname = "{re.escape(package)}"\nversion = "([^"]+)"', lock)
    parsed = []
    for raw in versions:
        try:
            parsed.append(Version(raw))
        except InvalidVersion:
            continue
    return str(max(parsed)) if parsed else None


def main() -> int:
    stale: list[str] = []
    prerelease: list[str] = []

    for package in ("homeassistant", "pytest-homeassistant-custom-component"):
        locked = locked_version(package)
        latest = latest_stable(package)

        print(f"{package}:")
        print(f"  locked in uv.lock : {locked}")
        print(f"  latest stable     : {latest}")

        if locked is None or latest is None:
            print("  -> could not compare")
            continue

        locked_v, latest_v = Version(locked), Version(latest)

        if latest_v > locked_v:
            # A newer stable exists than the one we test against.
            stale.append(f"{package}: locked {locked}, stable {latest} is available")
            print("  -> NEWER STABLE RELEASE AVAILABLE")
        elif locked_v.is_prerelease:
            # Expected situation: the test harness pins a pre-release of HA so
            # that CI is forward-compatible. Not drift, but worth surfacing
            # because users are most likely on the stable release.
            prerelease.append(f"{package}: locked {locked} (pre-release), stable is {latest}")
            print(f"  -> lock is on a pre-release, ahead of stable {latest}")
        else:
            print("  -> up to date with latest stable")

    if prerelease:
        print("\nNote (not a failure):")
        for item in prerelease:
            print(f"  * {item}")
        print(
            "  CI intentionally tests a pre-release because "
            "pytest-homeassistant-custom-component pins Home Assistant exactly.\n"
            "  Users on the stable release are covered by the previous stable lock."
        )

    if stale:
        print("\nDependency drift detected:")
        for item in stale:
            print(f"  * {item}")
        print(
            "\nTo adopt the newer stable release:\n"
            "  uv lock --upgrade-package pytest-homeassistant-custom-component\n"
            "The harness pins Home Assistant exactly, so bumping the harness is\n"
            "what unlocks a newer stable HA."
        )
        return 1

    if not prerelease:
        print("\nNo newer stable releases available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
