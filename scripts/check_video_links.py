"""
Verify that every curriculum video still resolves on YouTube.

Why this exists
---------------
Curriculum videos are third-party content and go away without warning: a
creator unlists a video, a channel is removed, a rights claim takes it down.
When that happens the player simply shows "unavailable" and the submodule is
silently useless, which is not visible from the application's own logs.

Run this periodically, and before any demo:

    python3 scripts/check_video_links.py          # report
    python3 scripts/check_video_links.py --quiet  # exit status only, for CI

Exit status is 0 when every video resolves and 1 when any does not, so it can
be wired into CI or a scheduled job.

It uses YouTube's public oembed endpoint, which needs no API key. Note that the
`url` parameter must be percent-encoded; passing the watch URL raw makes the
inner `?v=` terminate the query string and every lookup fails, which looks
exactly like mass link rot.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config  # noqa: E402

OEMBED = "https://www.youtube.com/oembed"
TIMEOUT = 25


def resolve(video_id):
    """Return (ok, detail). detail is the title when ok, else the failure."""
    query = urllib.parse.urlencode({
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "format": "json",
    })
    try:
        with urllib.request.urlopen(f"{OEMBED}?{query}", timeout=TIMEOUT) as response:
            payload = json.load(response)
        return True, f"{payload.get('title', '')} — {payload.get('author_name', '')}"
    except urllib.error.HTTPError as exc:
        # 404 and 401 both mean the video is not publicly playable.
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # network trouble is not the same as link rot
        return None, f"{type(exc).__name__}: {exc}"


def collect():
    """Every (topic, label, video_id) the curriculum refers to."""
    from utils.constants import SUBMODULE_DEFINITIONS

    try:
        with open(config.VIDEOS_PATH) as handle:
            topics = json.load(handle)
    except (OSError, ValueError):
        topics = []

    seen, entries = set(), []
    for topic in topics:
        vid = topic.get("video_id")
        if vid and vid not in seen:
            seen.add(vid)
            entries.append((topic.get("id", "?"), f"topic: {topic.get('title', '')}", vid))

    for topic_id, modules in SUBMODULE_DEFINITIONS.items():
        for module in modules:
            vid = module.get("video_id")
            if vid and vid not in seen:
                seen.add(vid)
                entries.append((topic_id, module.get("title", ""), vid))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true",
                        help="print only failures and set the exit status")
    args = parser.parse_args()

    entries = collect()
    dead, errored = [], []

    for topic_id, label, video_id in entries:
        ok, detail = resolve(video_id)
        if ok is None:
            errored.append((topic_id, label, video_id, detail))
            status = "ERROR"
        elif ok:
            status = "ok"
        else:
            dead.append((topic_id, label, video_id, detail))
            status = "DEAD"
        if not args.quiet or status != "ok":
            print(f"  {status:<5} {video_id:<12} {topic_id:<5} {label[:46]}")
            if not args.quiet and ok:
                print(f"        {'':<12} {'':<5} {detail[:70]}")

    print(f"\n{len(entries)} videos checked, {len(dead)} unavailable, "
          f"{len(errored)} could not be reached")

    if dead:
        print("\nUnavailable, needs a replacement video id:")
        for topic_id, label, video_id, detail in dead:
            print(f"  {topic_id}: {label} ({video_id}, {detail})")
        print("\nSubmodule ids live in utils/constants.py (SUBMODULE_DEFINITIONS);")
        print("topic-level ids live in the videos data file.")

    if errored:
        print("\nCould not be reached. This usually means a network problem rather")
        print("than link rot, so it is not treated as a failure:")
        for topic_id, label, video_id, detail in errored:
            print(f"  {topic_id}: {label} ({video_id}) {detail}")

    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
