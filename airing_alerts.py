#!/usr/bin/env python3
"""Tokyo Airing Radar: AniList reminders, schedule intelligence and weekly reports."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from anime_intelligence import (
    DEFAULT_PREFERENCES,
    build_statistics,
    normalize_preferences,
    normalize_schedule_history,
    normalize_sent_reminders,
    observe_schedules,
    select_due_reminder,
    should_track,
    weekly_report_due,
    weekly_report_embed,
    weekly_report_key,
)
from radar_v22 import (
    collect_overnight_airings,
    morning_digest_embed,
    weekly_calendar_due,
    weekly_calendar_embed,
    weekly_calendar_key,
    update_delivery_analytics,
)

RUN_METRICS = {
    "anilist_requests": 0,
    "anilist_errors": 0,
    "anilist_retries": 0,
    "discord_requests": 0,
    "discord_successes": 0,
    "discord_errors": 0,
    "discord_retries": 0,
}

API = "https://graphql.anilist.co"
USERNAME = os.getenv("ANILIST_USERNAME", "Orewatokyo").strip()
TOKEN = os.getenv("ANILIST_TARGET_TOKEN", "").strip()
WEBHOOK = os.getenv("DISCORD_AIRING_WEBHOOK", "").strip()
ALERT_FILE = Path("db_anime_airing.json")
CACHE_FILE = Path("airing_cache.json")
BOARD_FILE = Path("daily_board.json")
PREFERENCES_FILE = Path("anime_preferences.json")
SCHEDULE_HISTORY_FILE = Path("schedule_history.json")
STATS_FILE = Path("anime_stats.json")
IST = ZoneInfo("Asia/Kolkata")
CACHE_TTL, TIMEOUT, RETRIES = 12 * 3600, 20, 4
LOOKAHEAD_SECONDS = 7 * 24 * 3600
LIST_QUERY = '''query ($name: String, $page: Int) { Page(page:$page,perPage:50) { pageInfo { hasNextPage } mediaList(userName:$name,type:ANIME) { mediaId status } } }'''
AIRING_QUERY = '''query ($page:Int,$ids:[Int],$from:Int,$to:Int) { Page(page:$page,perPage:50) { pageInfo { hasNextPage } airingSchedules(mediaId_in:$ids,airingAt_greater:$from,airingAt_lesser:$to,sort:TIME) { id airingAt episode media { id title { romaji english } coverImage { extraLarge color } } } } }'''


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, type(default)) else default


def write_json(path: Path, value):
    """Atomic replacement so interrupted runs do not truncate state files."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


HTTP = requests.Session()
HTTP.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
if TOKEN:
    HTTP.headers["Authorization"] = f"Bearer {TOKEN}"


def graphql(query: str, variables: dict):
    for attempt in range(RETRIES):
        RUN_METRICS["anilist_requests"] += 1
        try:
            response = HTTP.post(API, json={"query": query, "variables": variables}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            RUN_METRICS["anilist_errors"] += 1
            if attempt == RETRIES - 1:
                raise RuntimeError(f"AniList network error: {exc}") from exc
            if attempt < RETRIES - 1:
                RUN_METRICS["anilist_retries"] += 1
            time.sleep(min(2 ** attempt, 16))
            continue
        if response.status_code == 200:
            body = response.json()
            if body.get("errors"):
                RUN_METRICS["anilist_errors"] += 1
                raise RuntimeError(f"AniList GraphQL error: {body['errors']}")
            return body.get("data") or {}
        RUN_METRICS["anilist_errors"] += 1
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < RETRIES - 1:
                RUN_METRICS["anilist_retries"] += 1
            try:
                delay = max(float(response.headers.get("Retry-After", 0)), min(2 ** attempt, 20))
            except (TypeError, ValueError):
                delay = min(2 ** attempt, 20)
            time.sleep(delay)
            continue
        response.raise_for_status()
    raise RuntimeError("AniList request exhausted retries")

def get_media_entries(now: int) -> dict[int, str]:
    """Return media ID -> AniList list status; upgrade the old ID-only cache in place."""
    cache = read_json(CACHE_FILE, {})
    cached_entries = cache.get("media_entries") if isinstance(cache, dict) else None
    fresh = (
        isinstance(cached_entries, list)
        and cache.get("username") == USERNAME
        and now - int(cache.get("updated_at", 0)) < CACHE_TTL
    )
    if fresh:
        entries = {}
        for item in cached_entries:
            if isinstance(item, dict):
                try:
                    entries[int(item["media_id"])] = str(item["status"]).upper()
                except (KeyError, TypeError, ValueError):
                    continue
        if entries:
            logging.info("Using cached AniList entries: %d", len(entries))
            return entries

    entries: dict[int, str] = {}
    page = 1
    while True:
        data = graphql(LIST_QUERY, {"name": USERNAME, "page": page}).get("Page") or {}
        for item in data.get("mediaList", []):
            try:
                media_id = int(item["mediaId"])
                status = str(item.get("status") or "CURRENT").upper()
                if media_id > 0:
                    entries[media_id] = status
            except (KeyError, TypeError, ValueError):
                continue
        if not (data.get("pageInfo") or {}).get("hasNextPage"):
            break
        page += 1
    if not entries:
        raise RuntimeError(f"AniList returned no anime entries for {USERNAME}")
    ordered = sorted(entries)
    write_json(CACHE_FILE, {
        "username": USERNAME,
        "updated_at": int(now),
        "media_ids": ordered,
        "media_entries": [{"media_id": mid, "status": entries[mid]} for mid in ordered],
    })
    logging.info("Refreshed AniList cache: %d IDs with list statuses", len(entries))
    return entries


def get_airings(ids: list[int], start: int, end: int) -> list[dict]:
    if not ids:
        return []
    found = {}
    for offset in range(0, len(ids), 500):
        page, batch = 1, ids[offset:offset + 500]
        while True:
            data = graphql(AIRING_QUERY, {"page": page, "ids": batch, "from": start, "to": end}).get("Page") or {}
            for item in data.get("airingSchedules", []):
                media = item.get("media") or {}
                title = media.get("title") or {}
                cover = media.get("coverImage") or {}
                try:
                    media_id = int(media.get("id") or 0)
                    if not media_id:
                        continue
                    name = title.get("english") or title.get("romaji") or f"Anime {media_id}"
                    airing = {
                        "schedule_id": str(item.get("id") or ""),
                        "media_id": media_id,
                        "title": name,
                        "romaji": title.get("romaji") or name,
                        "episode": int(item["episode"]),
                        "airing_at": int(item["airingAt"]),
                        "cover": cover.get("extraLarge"),
                        "color": cover.get("color"),
                    }
                    found[(media_id, airing["episode"])] = airing
                except (KeyError, TypeError, ValueError):
                    continue
            if not (data.get("pageInfo") or {}).get("hasNextPage"):
                break
            page += 1
    return sorted(found.values(), key=lambda item: item["airing_at"])


def webhook_request(method: str, url: str, payload: dict):
    for attempt in range(RETRIES):
        RUN_METRICS["discord_requests"] += 1
        try:
            response = HTTP.request(method, url, json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            RUN_METRICS["discord_errors"] += 1
            if attempt == RETRIES - 1:
                logging.error("Discord request failed: %s", exc)
                return None
            RUN_METRICS["discord_retries"] += 1
            time.sleep(min(2 ** attempt, 16))
            continue
        if response.status_code in (200, 201):
            RUN_METRICS["discord_successes"] += 1
            try:
                return response.json()
            except ValueError:
                return {}
        if response.status_code == 204:
            RUN_METRICS["discord_successes"] += 1
            return {}
        if response.status_code == 429 or response.status_code >= 500:
            RUN_METRICS["discord_errors"] += 1
            if attempt < RETRIES - 1:
                RUN_METRICS["discord_retries"] += 1
            try:
                delay = max(float(response.headers.get("Retry-After", 0)), float(response.json().get("retry_after", 0)))
            except (ValueError, TypeError):
                delay = min(2 ** attempt, 16)
            time.sleep(max(delay, min(2 ** attempt, 16)))
            continue
        RUN_METRICS["discord_errors"] += 1
        logging.error("Discord HTTP %s: %s", response.status_code, response.text[:300])
        return None
    return None

def alert_embed(airing: dict, kind: str) -> dict:
    labels = {"3h": "AIRING SOON", "1h": "1-HOUR WARNING", "30m": "30-MINUTE WARNING"}
    colors = {"3h": 0x5865F2, "1h": 0xF0B232, "30m": 0xED4245}
    stamp = airing["airing_at"]
    category = str(airing.get("category", "other")).upper()
    embed = {
        "author": {"name": f"📡 TOKYO AIRING RADAR / {labels[kind]}"},
        "title": airing["title"][:256],
        "url": f"https://anilist.co/anime/{airing['media_id']}/",
        "description": f"**EPISODE {airing['episode']}** · **{category}**\n*{airing['romaji']}*\n\n⏳ **Airs <t:{stamp}:R>**",
        "color": colors[kind],
        "fields": [
            {"name": "🗓️ BROADCAST", "value": f"<t:{stamp}:F>", "inline": True},
            {"name": "🔔 REMINDER", "value": labels[kind], "inline": True},
        ],
        "footer": {"text": "ANILIST • AUTOMATIC AIRING TRACKER"},
    }
    if airing.get("cover"):
        embed["thumbnail"] = {"url": airing["cover"]}
    return embed


def send_due_alerts(airings: list[dict], state: dict, now: int) -> int:
    pending = []
    for airing in airings:
        key = f"{airing['media_id']}_ep{airing['episode']}"
        kind = select_due_reminder(airing["airing_at"], now, state.get(key, []))
        if kind:
            pending.append((key, kind, alert_embed(airing, kind)))
    sent = 0
    for index in range(0, len(pending), 10):
        group = pending[index:index + 10]
        result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [item[2] for item in group]})
        if result is None:
            continue
        for key, kind, _ in group:
            old = normalize_sent_reminders(state.get(key, []))
            state[key] = sorted(old | {kind})
            sent += 1
    return sent


def update_daily_board(airings: list[dict], now: int):
    local = datetime.fromtimestamp(now, IST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    todays = [item for item in airings if start.timestamp() <= item["airing_at"] < end.timestamp()]
    lines = [
        f"**<t:{item['airing_at']}:t>** • [{item['title'][:90]}](https://anilist.co/anime/{item['media_id']}/) — Ep. **{item['episode']}**"
        for item in todays[:35]
    ]
    if len(todays) > 35:
        lines.append(f"…and {len(todays) - 35} more.")
    embed = {
        "author": {"name": "📅 TOKYO'S DAILY AIRING BOARD"},
        "title": local.strftime("%A • %d %B %Y"),
        "description": ("\n".join(lines) if lines else "No upcoming episodes are listed for today. Enjoy your anime-free hours! 🍵")[:4000],
        "color": 0x2ECC71,
        "footer": {"text": f"{len(todays)} episode(s) • AniList • Times shown in India (IST)"},
    }
    if todays and todays[0].get("cover"):
        embed["thumbnail"] = {"url": todays[0]["cover"]}
    state = read_json(BOARD_FILE, {})
    if state.get("date") == local.date().isoformat() and state.get("message_id"):
        result = webhook_request("PATCH", WEBHOOK.rstrip("/") + f"/messages/{state['message_id']}", {"embeds": [embed]})
        if result is not None:
            return
    result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [embed]})
    if result and result.get("id"):
        write_json(BOARD_FILE, {"date": local.date().isoformat(), "message_id": str(result["id"])})


def prune_alert_history(state: dict, ids: list[int], airings: list[dict]):
    active = set(ids)
    newest = {}
    for item in airings:
        newest[item["media_id"]] = max(newest.get(item["media_id"], 0), item["episode"])
    for key in list(state):
        try:
            media_id, episode = key.split("_ep", 1)
            media_id, episode = int(media_id), int(episode)
        except (ValueError, AttributeError):
            continue
        if media_id not in active or (media_id in newest and episode < newest[media_id] - 3):
            del state[key]


def intelligence_event_embed(event: dict) -> dict:
    event_type = event.get("type")
    titles = {
        "delay": "⏰ AIRING DELAY DETECTED",
        "moved_earlier": "⚡ AIRING MOVED EARLIER",
        "schedule_replaced": "🔄 AIRING SCHEDULE REPLACED",
        "missing": "❓ AIRING SCHEDULE MISSING",
        "restored": "✅ AIRING SCHEDULE RESTORED",
    }
    description = f"**{event.get('title', 'Unknown anime')} · Episode {event.get('episode', '?')}**"
    old_time, new_time = event.get("old_airing_at"), event.get("new_airing_at")
    if old_time:
        description += f"\nPrevious: <t:{int(old_time)}:F>"
    if new_time:
        description += f"\nCurrent: <t:{int(new_time)}:F>"
    if event_type in {"delay", "moved_earlier"}:
        minutes = abs(int(event.get("delta_seconds", 0))) // 60
        description += f"\nSchedule shift: **{minutes} minutes**"
    if event_type == "missing":
        description += "\nAniList no longer returns this upcoming schedule after repeated checks. It may be temporarily unlisted or rescheduled."
    return {
        "author": {"name": "🧠 TOKYO AIRING RADAR / ANIME INTELLIGENCE"},
        "title": titles.get(event_type, "📡 SCHEDULE UPDATE"),
        "description": description[:4000],
        "color": 0xED4245 if event_type in {"delay", "missing"} else 0x5865F2,
        "footer": {"text": "AniList schedule monitoring • Asia/Kolkata"},
    }


def send_pending_intelligence_events(history: dict) -> int:
    pending = history.get("pending_events", [])
    sent_ids = set()
    sent = 0
    for index in range(0, len(pending), 10):
        group = pending[index:index + 10]
        result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [intelligence_event_embed(item) for item in group]})
        if result is None:
            break
        sent_ids.update(item.get("event_id") for item in group if isinstance(item, dict))
        sent += len(group)
    history["pending_events"] = [item for item in pending if item.get("event_id") not in sent_ids]
    return sent


def send_morning_catchup(stats_state: dict, schedule_history: dict, alert_history: dict, now: int, last_successful_run: int, current_airings: list[dict]) -> bool:
    """Send exactly one overnight digest; retain a pending payload if Discord is unavailable."""
    local = datetime.fromtimestamp(now, IST)
    pending = stats_state.get("pending_morning_digest")
    if not isinstance(pending, dict):
        gap = now - int(last_successful_run or 0)
        if not last_successful_run or gap < 6 * 3600 or not (10 <= local.hour < 22):
            return False
        if stats_state.get("last_morning_digest_date") == local.date().isoformat():
            return False
        items, missed = collect_overnight_airings(
            schedule_history, alert_history, last_successful_run, now, current_airings=current_airings
        )
        local_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        upcoming_today = [
            item for item in current_airings
            if now < int(item["airing_at"]) < int((local_start + timedelta(days=1)).timestamp())
        ]
        changes = [
            event for event in schedule_history.get("pending_events", [])
            if isinstance(event, dict)
            and last_successful_run <= int(event.get("created_at", 0) or 0) <= now
        ]
        pending = {
            "date": local.date().isoformat(),
            "from_at": int(last_successful_run),
            "to_at": int(now),
            "embed": morning_digest_embed(
                items, missed, last_successful_run, now,
                upcoming_today=upcoming_today, schedule_changes=changes,
            ),
        }
        stats_state["pending_morning_digest"] = pending
        logging.info("Prepared morning catch-up: %d overnight episodes, %d without recorded reminders", len(items), missed)

    result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [pending["embed"]]})
    if result is None:
        logging.warning("Morning catch-up delivery failed; digest remains queued for retry.")
        return False
    stats_state["last_morning_digest_date"] = pending["date"]
    stats_state.pop("pending_morning_digest", None)
    logging.info("Morning catch-up digest sent for %s", pending["date"])
    return True


def save_statistics_and_report(
    entries: dict[int, str],
    airings: list[dict],
    history: dict,
    preferences: dict,
    now: int,
    stats_state: dict,
    reminders_sent: int,
    intelligence_events_sent: int,
    morning_digest_sent: bool,
    calendar_sent: bool,
):
    stats = build_statistics(entries, airings, history, now, preferences)
    stats_state["latest_snapshot"] = stats
    update_delivery_analytics(
        stats_state,
        now,
        RUN_METRICS,
        reminders_sent,
        intelligence_events_sent,
        morning_digest_sent,
        calendar_sent,
    )
    stats_state["updated_at"] = int(now)

    # The weekly report includes the accumulated notification/API health totals.
    report_stats = dict(stats)
    report_stats["delivery_health"] = stats_state.get("delivery", {})

    if weekly_report_due(now, stats_state):
        week_key = weekly_report_key(now)
        result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [weekly_report_embed(report_stats, week_key)]})
        if result is not None:
            stats_state["last_weekly_report"] = week_key
            reports = stats_state.get("weekly_reports", [])
            if not isinstance(reports, list):
                reports = []
            reports.append(report_stats)
            stats_state["weekly_reports"] = reports[-12:]
            logging.info("Weekly anime report sent: %s", week_key)
        else:
            logging.warning("Weekly anime report was not delivered; it will be retried on the next run.")

    write_json(STATS_FILE, stats_state)
    return stats

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s UTC | %(levelname)s | %(message)s")
    if not USERNAME or not WEBHOOK:
        raise RuntimeError("Missing AniList username or DISCORD_AIRING_WEBHOOK secret")

    now = int(time.time())
    stats_state = read_json(STATS_FILE, {})
    if not isinstance(stats_state, dict):
        stats_state = {}
    last_successful_run = int(stats_state.get("updated_at", 0) or 0)

    entries = get_media_entries(now)
    preferences = normalize_preferences(read_json(PREFERENCES_FILE, DEFAULT_PREFERENCES))
    write_json(PREFERENCES_FILE, preferences)
    tracked = {media_id: status for media_id, status in entries.items() if should_track(media_id, status, preferences)}
    ids = sorted(tracked)
    airings = get_airings(ids, now - 60, now + LOOKAHEAD_SECONDS)
    favourite_ids = set(preferences["favourite_media_ids"])
    for item in airings:
        item["category"] = "favourite" if item["media_id"] in favourite_ids else (
            "watching" if tracked.get(item["media_id"]) in {"CURRENT", "REPEATING"} else "other"
        )

    alert_history = read_json(ALERT_FILE, {})
    schedule_history = normalize_schedule_history(read_json(SCHEDULE_HISTORY_FILE, {}))

    # Compare last night's snapshot with today's AniList feed before preparing the recap.
    schedule_history = observe_schedules(schedule_history, airings, now)

    # Morning catch-up uses the persisted pre-break times plus the refreshed schedule.
    morning_digest_sent = send_morning_catchup(
        stats_state, schedule_history, alert_history, now, last_successful_run, airings
    )

    prune_alert_history(alert_history, sorted(entries), airings)
    reminders_sent = send_due_alerts(airings, alert_history, now)
    write_json(ALERT_FILE, alert_history)

    events_sent = send_pending_intelligence_events(schedule_history)
    write_json(SCHEDULE_HISTORY_FILE, schedule_history)

    update_daily_board(airings, now)

    calendar_sent = False
    if weekly_calendar_due(now, stats_state):
        week_key = weekly_calendar_key(now)
        result = webhook_request("POST", WEBHOOK + "?wait=true", {"embeds": [weekly_calendar_embed(airings, now)]})
        if result is not None:
            stats_state["last_weekly_calendar"] = week_key
            calendar_sent = True
            logging.info("Weekly calendar sent: %s", week_key)
        else:
            logging.warning("Weekly calendar was not delivered; it will be retried on the next run.")

    stats = save_statistics_and_report(
        entries,
        airings,
        schedule_history,
        preferences,
        now,
        stats_state,
        reminders_sent,
        events_sent,
        morning_digest_sent,
        calendar_sent,
    )
    logging.info(
        "HEALTH OK | list=%d | tracked=%d | next-7d=%d | reminders=%d | schedule-events=%d | morning-digest=%s | calendar=%s | anilist-errors=%d | discord-errors=%d",
        len(entries), len(tracked), len(airings), reminders_sent, events_sent,
        morning_digest_sent, calendar_sent, RUN_METRICS["anilist_errors"], RUN_METRICS["discord_errors"],
    )

if __name__ == "__main__":
    main()
