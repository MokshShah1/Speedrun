# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Version helper for wheel builds."""

import pathlib

# Read version from .version file in project root
_version_file = pathlib.Path(__file__).parent.parent / ".version"
_raw = _version_file.read_text().strip()

# The Speedrun fork marks its version as e.g. "26.05-speedrun". PEP 440 (used by
# the wheel build backend and pip's dependency resolver) does not allow a
# "-<label>" suffix, so packaging uses only the numeric release ("26.05"). The
# app itself reads .version directly (rslib/src/version.rs -> build_flavor()),
# so its displayed "26.05-speedrun" fork marker is unchanged.
__version__ = _raw.split("-", 1)[0]
