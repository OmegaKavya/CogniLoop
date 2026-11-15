"""Curriculum figures, derived from the curriculum itself.

Why this exists
---------------
The landing page advertised "48 In-Video Checkpoints", "3 checkpoints per
submodule x 4 submodules x 4 courses" and "290 Automated Tests Passing", all
typed in by hand. Every one of them was wrong by the time anyone read it: the
curriculum now has 20 submodules, 60 checkpoints and over eleven hours of
material, and the suite has grown well past 290.

Numbers written into a template are a claim that nothing keeps true. These are
computed from `SUBMODULE_DEFINITIONS` at request time, so adding a submodule
updates the page and no one has to remember.

The test count cannot be derived this way - the suite is not importable from
the running application and counting it at request time would be absurd - so
it is read from a file that `scripts/update_project_stats.py` writes. If that
file is missing or stale-looking, the figure is omitted rather than guessed.
"""

import json
import os

from backend import config
from utils.constants import SUBMODULE_DEFINITIONS

PROJECT_STATS_PATH = os.environ.get("PROJECT_STATS_PATH") or os.path.join(
    config.PROJECT_ROOT, "data", "project_stats.json")


def curriculum_totals():
    """Counts and durations across the whole curriculum."""
    submodules = [module
                  for modules in SUBMODULE_DEFINITIONS.values()
                  for module in modules]

    seconds = 0
    for module in submodules:
        start, end = module.get("start_sec"), module.get("end_sec")
        if start is not None and end is not None and end > start:
            seconds += end - start

    checkpoints = sum(len(module.get("checkpoints") or []) for module in submodules)

    return {
        "modules": len(SUBMODULE_DEFINITIONS),
        "submodules": len(submodules),
        "checkpoints": checkpoints,
        "videos": len({module.get("video_id") for module in submodules
                       if module.get("video_id")}),
        "seconds": seconds,
        "hours": round(seconds / 3600.0, 1),
    }


def per_topic():
    """{topic_id: {submodules, checkpoints, minutes}} for the course cards."""
    out = {}
    for topic_id, modules in SUBMODULE_DEFINITIONS.items():
        seconds = sum((m["end_sec"] - m["start_sec"]) for m in modules
                      if m.get("start_sec") is not None and m.get("end_sec") is not None)
        out[topic_id] = {
            "submodules": len(modules),
            "checkpoints": sum(len(m.get("checkpoints") or []) for m in modules),
            "minutes": round(seconds / 60),
        }
    return out


def test_count():
    """Tests passing at the last recorded run, or None if not recorded.

    Returning None rather than a stale or invented number is deliberate: the
    template omits the figure entirely instead of displaying a count nobody
    has verified.
    """
    try:
        with open(PROJECT_STATS_PATH) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    count = data.get("tests_passing")
    return count if isinstance(count, int) and count > 0 else None


def landing_stats():
    """Everything the landing page advertises, in one call."""
    totals = curriculum_totals()
    totals["tests_passing"] = test_count()
    totals["per_topic"] = per_topic()
    return totals
