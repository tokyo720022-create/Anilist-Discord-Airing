"""Overnight digest, weekly calendar, preference actions and health analytics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
REMINDER_TYPES = {"3h", "1h", "30m"}


def _sent_values(value: Any) -> set[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item) for item in value if str(item) in REMINDER_TYPES}


def collect_overnight_airings(
    schedule_history: dict[str, Any],
    alert_history: dict[str, Any],
    start_at: int,
    end_at: int,
    current_airings: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Collect expected overnight episodes, excluding schedules now moved into the future."""
    current_times = {}
    for current in current_airings or []:
        try:
            current_times[(int(current["media_id"]), int(current["episode"]))] = int(current["airing_at"])
        except (KeyError, TypeError, ValueError):
            continue
    found: dict[tuple[int, int], dict[str, Any]] = {}
    for record in (schedule_history.get("airings") or {}).values():
        if not isinstance(record, dict):
            continue
        try:
            stamp = int(record.get("airing_at", 0))
            media_id = int(record["media_id"])
            episode = int(record["episode"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (start_at < stamp <= end_at):
            continue
        refreshed_time = current_times.get((media_id, episode))
        if refreshed_time is not None and abs(refreshed_time - stamp) >= 60:
            # AniList now lists this same episode at a different time; do not report
            # the stale snapshot as an episode that definitely aired overnight.
            continue
        item = {
            "media_id": media_id,
            "episode": episode,
            "title": record.get("title") or f"Anime {media_id}",
            "airing_at": stamp,
        }
        key = f"{media_id}_ep{episode}"
        item["reminders_sent"] = sorted(_sent_values(alert_history.get(key, [])))
        item["reminder_missed"] = not item["reminders_sent"]
        found[(media_id, episode)] = item
    items = sorted(found.values(), key=lambda entry: entry["airing_at"])
    missed = sum(1 for item in items if item["reminder_missed"])
    return items, missed


def morning_digest_embed(
    items: list[dict[str, Any]],
    missed_reminders: int,
    start_at: int,
    end_at: int,
) -> dict[str, Any]:
    """Build one compact morning catch-up summary for the inactive period."""
    start = datetime.fromtimestamp(start_at, IST)
    end = datetime.fromtimestamp(end_at, IST)
    if not items:
        description = "Nothing from your tracked schedule was recorded as airing during the break. Your normal radar checks are back online."
    else:
        lines = []
        for item in items[:16]:
            title = str(item.get("title", "Unknown anime"))[:88]
            stamp = int(item["airing_at"])
            badge = "⚠️ No reminder recorded" if item.get("reminder_missed") else "✅ Reminder sent"
            lines.append(
                f"• <t:{stamp}:t> — **[{title}](https://anilist.co/anime/{item['media_id']}/)** · Ep. {item['episode']}\n  {badge}"
            )
        if len(items) > 16:
            lines.append(f"…and {len(items) - 16} more episodes.")
        description = "\n".join(lines)
    return {
        "author": {"name": "🌅 TOKYO AIRING RADAR / MORNING CATCH-UP"},
        "title": f"Overnight digest · {end.strftime('%A, %d %B')}",
        "description": description[:4000],
        "color": 0xF0B232,
        "fields": [
            {"name": "REST PERIOD", "value": f"<t:{int(start_at)}:t> → <t:{int(end_at)}:t> IST", "inline": True},
            {"name": "EPISODES AIRED", "value": str(len(items)), "inline": True},
            {"name": "MISSED REMINDERS", "value": str(missed_reminders), "inline": True},
        ],
        "footer": {"text": "Overnight recap from saved AniList schedules • Asia/Kolkata"},
    }


def weekly_calendar_embed(airings: list[dict[str, Any]], now: int, days: int = 7) -> dict[str, Any]:
    """Create a seven-day, India-time schedule grouped by day."""
    start_day = datetime.fromtimestamp(now, IST).date()
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for item in airings:
        local = datetime.fromtimestamp(int(item["airing_at"]), IST)
        if 0 <= (local.date() - start_day).days < days:
            grouped[local.date()].append(item)

    fields = []
    total = 0
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        day_items = sorted(grouped.get(day, []), key=lambda entry: int(entry["airing_at"]))
        total += len(day_items)
        lines = [
            f"<t:{int(item['airing_at'])}:t> · [{str(item['title'])[:75]}](https://anilist.co/anime/{int(item['media_id'])}/) · Ep. {int(item['episode'])}"
            for item in day_items[:6]
        ]
        if len(day_items) > 6:
            lines.append(f"…plus {len(day_items) - 6} more.")
        fields.append({
            "name": day.strftime("%a · %d %b"),
            "value": "\n".join(lines) if lines else "No tracked episodes scheduled",
            "inline": False,
        })
    return {
        "author": {"name": "🗓️ TOKYO AIRING RADAR / WEEKLY CALENDAR"},
        "title": f"Upcoming anime · {start_day.strftime('%d %b')} – {(start_day + timedelta(days=days - 1)).strftime('%d %b %Y')}",
        "color": 0x2ECC71,
        "fields": fields,
        "footer": {"text": f"{total} tracked episodes • India Standard Time"},
    }


def weekly_calendar_key(now: int) -> str:
    return datetime.fromtimestamp(now, IST).strftime("%G-W%V")


def weekly_calendar_due(now: int, stats_state: dict[str, Any]) -> bool:
    local = datetime.fromtimestamp(now, IST)
    return local.weekday() == 0 and stats_state.get("last_weekly_calendar") != weekly_calendar_key(now)


def apply_preference_action(
    raw_preferences: Any,
    action: str,
    media_id: int | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    """Apply a validated GitHub Actions control-panel operation."""
    from anime_intelligence import DEFAULT_PREFERENCES, VALID_STATUSES, normalize_preferences

    prefs = normalize_preferences(raw_preferences)
    favourites = set(prefs["favourite_media_ids"])
    muted = set(prefs["muted_media_ids"])
    action = str(action or "").strip().lower()

    id_actions = {"add_favourite", "remove_favourite", "add_muted", "remove_muted"}
    if action in id_actions:
        if media_id is None or int(media_id) <= 0:
            raise ValueError("A positive AniList media_id is required for this action.")
        media_id = int(media_id)
        if action == "add_favourite":
            favourites.add(media_id)
            muted.discard(media_id)
        elif action == "remove_favourite":
            favourites.discard(media_id)
        elif action == "add_muted":
            muted.add(media_id)
        elif action == "remove_muted":
            muted.discard(media_id)
    elif action == "set_status_filter":
        if not statuses:
            raise ValueError("Provide one or more AniList statuses.")
        selected = {str(value).upper().strip() for value in statuses}
        invalid = selected - VALID_STATUSES
        if invalid or not selected:
            raise ValueError(f"Invalid or empty AniList status selection: {sorted(invalid)}")
        prefs["list_status_filter"] = sorted(selected)
    elif action == "reset_status_filter":
        prefs["list_status_filter"] = DEFAULT_PREFERENCES["list_status_filter"]
    else:
        raise ValueError(f"Unsupported preference action: {action}")

    prefs["favourite_media_ids"] = sorted(favourites)
    prefs["muted_media_ids"] = sorted(muted)
    return prefs


def update_delivery_analytics(
    stats_state: dict[str, Any],
    now: int,
    runtime_metrics: dict[str, int],
    reminders_sent: int,
    intelligence_events_sent: int,
    morning_digest_sent: bool,
    calendar_sent: bool,
) -> dict[str, Any]:
    """Accumulate message delivery and API health counters while bounding history."""
    delivery = stats_state.get("delivery") if isinstance(stats_state.get("delivery"), dict) else {}
    counters = (
        "anilist_requests", "anilist_errors", "anilist_retries", "discord_requests",
        "discord_successes", "discord_errors", "discord_retries",
    )
    for key in counters:
        delivery[key] = int(delivery.get(key, 0)) + int(runtime_metrics.get(key, 0))
    delivery["reminders_sent"] = int(delivery.get("reminders_sent", 0)) + int(reminders_sent)
    delivery["intelligence_events_sent"] = int(delivery.get("intelligence_events_sent", 0)) + int(intelligence_events_sent)
    delivery["morning_digests_sent"] = int(delivery.get("morning_digests_sent", 0)) + int(bool(morning_digest_sent))
    delivery["weekly_calendars_sent"] = int(delivery.get("weekly_calendars_sent", 0)) + int(bool(calendar_sent))
    delivery["last_run_at"] = int(now)
    delivery["last_run_api_errors"] = int(runtime_metrics.get("anilist_errors", 0))
    delivery["last_run_discord_errors"] = int(runtime_metrics.get("discord_errors", 0))
    stats_state["delivery"] = delivery

    history = stats_state.get("run_history", [])
    if not isinstance(history, list):
        history = []
    history.append({
        "at": int(now),
        "anilist_requests": int(runtime_metrics.get("anilist_requests", 0)),
        "anilist_errors": int(runtime_metrics.get("anilist_errors", 0)),
        "discord_requests": int(runtime_metrics.get("discord_requests", 0)),
        "discord_errors": int(runtime_metrics.get("discord_errors", 0)),
        "reminders_sent": int(reminders_sent),
        "intelligence_events_sent": int(intelligence_events_sent),
        "morning_digest_sent": bool(morning_digest_sent),
        "weekly_calendar_sent": bool(calendar_sent),
    })
    stats_state["run_history"] = history[-100:]
    return stats_state
