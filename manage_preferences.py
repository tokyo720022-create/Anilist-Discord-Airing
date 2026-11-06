#!/usr/bin/env python3
"""GitHub Actions form handler for Tokyo Airing Radar preferences."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from radar_v22 import apply_preference_action

PREFERENCES_FILE = Path("anime_preferences.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", default=os.getenv("PREFERENCE_ACTION", ""))
    parser.add_argument("--media-id", default=os.getenv("MEDIA_ID", ""))
    parser.add_argument("--statuses", default=os.getenv("LIST_STATUSES", ""))
    args = parser.parse_args()

    raw = {}
    if PREFERENCES_FILE.exists():
        with PREFERENCES_FILE.open(encoding="utf-8") as stream:
            raw = json.load(stream)

    media_id = int(args.media_id) if str(args.media_id).strip() else None
    statuses = [value.strip() for value in str(args.statuses).split(",") if value.strip()]
    updated = apply_preference_action(raw, args.action, media_id=media_id, statuses=statuses)
    tmp = PREFERENCES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PREFERENCES_FILE)

    print(f"Preference action applied: {args.action}")
    print(f"Favourite IDs: {len(updated['favourite_media_ids'])}")
    print(f"Muted IDs: {len(updated['muted_media_ids'])}")
    print(f"Allowed statuses: {', '.join(updated['list_status_filter'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
