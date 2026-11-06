"""Pure helpers for Tokyo Airing Radar's Anime Intelligence layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
VALID_STATUSES = {"CURRENT", "PLANNING", "COMPLETED", "DROPPED", "PAUSED", "REPEATING"}
DEFAULT_PREFERENCES = {
    "version": 1,
    "favourite_media_ids": [],
    "muted_media_ids": [],
    "list_status_filter": sorted(VALID_STATUSES),
}


def _int_set(values: Any) -> set[int]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    result: set[int] = set()
    for value in values:
        try:
            number = int(value)
            if number > 0:
                result.add(number)
        except (TypeError, ValueError):
            continue
    return result


def normalize_preferences(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    statuses = raw.get("list_status_filter", DEFAULT_PREFERENCES["list_status_filter"])
    if not isinstance(statuses, (list, tuple, set)):
        statuses = DEFAULT_PREFERENCES["list_status_filter"]
    statuses = sorted({str(item).upper() for item in statuses} & VALID_STATUSES)
    return {
        "version": 1,
        "favourite_media_ids": sorted(_int_set(raw.get("favourite_media_ids", []))),
        "muted_media_ids": sorted(_int_set(raw.get("muted_media_ids", []))),
        "list_status_filter": statuses,
    }


def anime_category(media_id: int, status: str, preferences: dict[str, Any]) -> str:
    favourites = set(preferences.get("favourite_media_ids", []))
    muted = set(preferences.get("muted_media_ids", []))
    if media_id in muted:
        return "muted"
    if media_id in favourites:
        return "favourite"
    if status in {"CURRENT", "REPEATING"}:
        return "watching"
    return "other"


def should_track(media_id: int, status: str, preferences: dict[str, Any]) -> bool:
    if media_id in set(preferences.get("muted_media_ids", [])):
        return False
    if media_id in set(preferences.get("favourite_media_ids", [])):
        return True
    return status in set(preferences.get("list_status_filter", []))


def normalize_sent_reminders(value: Any) -> set[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    return {str(item) for item in values if str(item) in {"3h", "1h", "30m"}}


def select_due_reminder(airing_at: int, now: int, already_sent: Any) -> str | None:
    """Choose the nearest useful reminder; late runs skip stale earlier windows."""
    remaining = int(airing_at) - int(now)
    sent = normalize_sent_reminders(already_sent)
    if remaining <= 0:
        return None
    if remaining <= 30 * 60:
        return None if "30m" in sent else "30m"
    if remaining <= 60 * 60:
        return None if "1h" in sent else "1h"
    if remaining <= 3 * 60 * 60:
        return None if "3h" in sent else "3h"
    return None


def empty_schedule_history() -> dict[str, Any]:
    return {"version": 1, "updated_at": 0, "airings": {}, "pending_events": []}


def normalize_schedule_history(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    airings = raw.get("airings", {})
    if not isinstance(airings, dict):
        airings = {}
    pending = raw.get("pending_events", [])
    if not isinstance(pending, list):
        pending = []
    return {
        "version": 1,
        "updated_at": int(raw.get("updated_at", 0) or 0),
        "airings": airings,
        "pending_events": pending,
    }


def _queue_event(history: dict[str, Any], event: dict[str, Any]) -> None:
    event_id = event["event_id"]
    pending = history["pending_events"]
    if not any(isinstance(item, dict) and item.get("event_id") == event_id for item in pending):
        pending.append(event)
    if len(pending) > 200:
        del pending[:-200]


def observe_schedules(
    raw_history: Any,
    airings: list[dict[str, Any]],
    now: int,
    missing_after: int = 3,
) -> dict[str, Any]:
    """Track schedule snapshots and queue change/missing events after repeated misses."""
    history = normalize_schedule_history(raw_history)
    records: dict[str, Any] = history["airings"]
    seen: set[str] = set()

    for airing in airings:
        media_id = int(airing["media_id"])
        episode = int(airing["episode"])
        key = f"{media_id}_ep{episode}"
        seen.add(key)
        timestamp = int(airing["airing_at"])
        schedule_id = str(airing.get("schedule_id") or "")
        previous = records.get(key)
        if not isinstance(previous, dict):
            records[key] = {
                "media_id": media_id,
                "episode": episode,
                "title": airing.get("title", f"Anime {media_id}"),
                "schedule_id": schedule_id,
                "airing_at": timestamp,
                "first_seen_at": int(now),
                "last_seen_at": int(now),
                "status": "scheduled",
                "missing_checks": 0,
                "changes": [],
            }
            continue

        previous_timestamp = int(previous.get("airing_at", timestamp))
        previous_id = str(previous.get("schedule_id") or "")
        old_status = previous.get("status", "scheduled")
        if abs(timestamp - previous_timestamp) >= 60:
            delta = timestamp - previous_timestamp
            event_type = "delay" if delta > 0 else "moved_earlier"
            event = {
                "event_id": f"{key}:{event_type}:{now}:{previous_timestamp}:{timestamp}",
                "type": event_type,
                "media_id": media_id,
                "episode": episode,
                "title": airing.get("title", previous.get("title", f"Anime {media_id}")),
                "old_airing_at": previous_timestamp,
                "new_airing_at": timestamp,
                "delta_seconds": delta,
                "created_at": int(now),
            }
            _queue_event(history, event)
            changes = previous.get("changes", [])
            if not isinstance(changes, list):
                changes = []
            changes.append(event)
            previous["changes"] = changes[-20:]
        elif schedule_id and previous_id and schedule_id != previous_id:
            event = {
                "event_id": f"{key}:schedule_replaced:{now}:{previous_id}:{schedule_id}",
                "type": "schedule_replaced",
                "media_id": media_id,
                "episode": episode,
                "title": airing.get("title", previous.get("title", f"Anime {media_id}")),
                "old_airing_at": previous_timestamp,
                "new_airing_at": timestamp,
                "created_at": int(now),
            }
            _queue_event(history, event)
            changes = previous.get("changes", [])
            if not isinstance(changes, list):
                changes = []
            changes.append(event)
            previous["changes"] = changes[-20:]

        if old_status == "missing":
            event = {
                "event_id": f"{key}:restored:{now}:{timestamp}",
                "type": "restored",
                "media_id": media_id,
                "episode": episode,
                "title": airing.get("title", previous.get("title", f"Anime {media_id}")),
                "old_airing_at": previous_timestamp,
                "new_airing_at": timestamp,
                "created_at": int(now),
            }
            _queue_event(history, event)

        previous.update({
            "title": airing.get("title", previous.get("title", f"Anime {media_id}")),
            "schedule_id": schedule_id or previous_id,
            "airing_at": timestamp,
            "last_seen_at": int(now),
            "status": "scheduled",
            "missing_checks": 0,
        })

    for key, record in list(records.items()):
        if key in seen or not isinstance(record, dict) or record.get("status") != "scheduled":
            continue
        old_time = int(record.get("airing_at", 0) or 0)
        if old_time < now - 6 * 3600:
            record["status"] = "elapsed"
            continue
        if old_time > now + 7 * 24 * 3600:
            continue
        checks = int(record.get("missing_checks", 0) or 0) + 1
        record["missing_checks"] = checks
        if checks >= max(1, int(missing_after)):
            record["status"] = "missing"
            event = {
                "event_id": f"{key}:missing:{now}:{old_time}",
                "type": "missing",
                "media_id": int(record.get("media_id", 0)),
                "episode": int(record.get("episode", 0)),
                "title": record.get("title", f"Anime {record.get('media_id', '')}"),
                "old_airing_at": old_time,
                "new_airing_at": None,
                "created_at": int(now),
            }
            _queue_event(history, event)
            changes = record.get("changes", [])
            if not isinstance(changes, list):
                changes = []
            changes.append(event)
            record["changes"] = changes[-20:]

    cutoff = now - 90 * 24 * 3600
    for key, record in list(records.items()):
        if isinstance(record, dict) and int(record.get("airing_at", 0) or 0) < cutoff:
            del records[key]
    history["updated_at"] = int(now)
    return history


def build_statistics(
    entries: dict[int, str],
    airings: list[dict[str, Any]],
    history: dict[str, Any],
    now: int,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    status_counts = {status: 0 for status in sorted(VALID_STATUSES)}
    categories = {"favourite": 0, "watching": 0, "muted": 0, "other": 0}
    tracked_count = 0
    for media_id, status in entries.items():
        status_counts[status] = status_counts.get(status, 0) + 1
        categories[anime_category(media_id, status, preferences)] += 1
        if should_track(media_id, status, preferences):
            tracked_count += 1
    upcoming_24h = sum(1 for item in airings if int(item["airing_at"]) <= now + 86400)
    changes_7d = {name: 0 for name in ("delay", "moved_earlier", "schedule_replaced", "missing", "restored")}
    for record in history.get("airings", {}).values():
        if not isinstance(record, dict):
            continue
        for event in record.get("changes", []):
            if isinstance(event, dict) and int(event.get("created_at", 0) or 0) >= now - 7 * 86400:
                kind = event.get("type")
                if kind in changes_7d:
                    changes_7d[kind] += 1
    return {
        "generated_at": int(now),
        "list_anime": len(entries),
        "tracked_anime": tracked_count,
        "status_counts": status_counts,
        "category_counts": categories,
        "upcoming_next_24h": upcoming_24h,
        "upcoming_next_7d": len(airings),
        "schedule_events_last_7d": changes_7d,
    }


def weekly_report_key(now: int) -> str:
    return datetime.fromtimestamp(now, IST).strftime("%G-W%V")


def weekly_report_due(now: int, stats_state: dict[str, Any]) -> bool:
    local = datetime.fromtimestamp(now, IST)
    return local.weekday() == 0 and stats_state.get("last_weekly_report") != weekly_report_key(now)


def weekly_report_embed(stats: dict[str, Any], week_key: str) -> dict[str, Any]:
    statuses = stats.get("status_counts", {})
    categories = stats.get("category_counts", {})
    events = stats.get("schedule_events_last_7d", {})
    return {
        "author": {"name": "📊 TOKYO AIRING RADAR / WEEKLY INTELLIGENCE"},
        "title": f"Anime weekly report • {week_key}",
        "color": 0x5865F2,
        "fields": [
            {"name": "Tracked anime", "value": str(stats.get("tracked_anime", 0)), "inline": True},
            {"name": "Episodes in 7 days", "value": str(stats.get("upcoming_next_7d", 0)), "inline": True},
            {"name": "Episodes in 24 hours", "value": str(stats.get("upcoming_next_24h", 0)), "inline": True},
            {"name": "Categories", "value": f"⭐ Favourite: {categories.get('favourite', 0)}\n▶️ Watching: {categories.get('watching', 0)}\n🔕 Muted: {categories.get('muted', 0)}\n📚 Other: {categories.get('other', 0)}", "inline": True},
            {"name": "AniList statuses", "value": "\n".join(f"{name.title()}: {count}" for name, count in statuses.items())[:1024] or "No list entries", "inline": True},
            {"name": "Schedule intelligence (7d)", "value": f"Delays: {events.get('delay', 0)}\nMoved earlier: {events.get('moved_earlier', 0)}\nReplaced: {events.get('schedule_replaced', 0)}\nMissing: {events.get('missing', 0)}\nRestored: {events.get('restored', 0)}", "inline": True},
        ],
        "footer": {"text": "Tokyo Airing Radar • AniList • Asia/Kolkata"},
    }
