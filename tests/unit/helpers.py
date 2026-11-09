# Shared by the unit tests: the monitor's modules on the path, no .pyc in the repo, a fixed
# time zone (log times are shown in local time) · imported first by every test file.
import os
import sys
import time

sys.dont_write_bytecode = True
os.environ["TZ"] = "UTC"
time.tzset()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmux"))

from tui import ANSI  # noqa: E402


def plain(s):
    """The text without its escape codes."""
    return ANSI.sub("", s)
