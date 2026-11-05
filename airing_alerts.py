#!/usr/bin/env python3
"""Hourly AniList airing alerts for Discord."""

import json
import logging
import os
import time
from pathlib import Path

import requests

API = "https://graphql.anilist.co"
USERNAME = os.getenv("ANILIST_USERNAME", "Orewatokyo").strip()
TOKEN = os.getenv("ANILIST_TARGET_TOKEN", "").strip()
WEBHOOK = os.getenv("DISCORD_AIRING_WEBHOOK", "").strip()
STATE_FILE = Path("db_anime_airing.json")
TIMEOUT = 25
RETRIES = 4

QUERY = """
query ($userName: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    mediaList(userName: $userName, type: ANIME, sort: [UPDATED_TIME_DESC]) {
      mediaId
      media {
        id
        type
        title { romaji english }
        coverImage { extraLarge color }
        nextAiringEpisode { airingAt episode }
      }
    }
  }
}
"""


def load_state():
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open(encoding="utf-8") as stream:
        state = json.load(stream)
    if not isinstance(state, dict):
        raise ValueError(f"{STATE_FILE} must contain a JSON object")
    return state


def save_state(state):
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    temp.replace(STATE_FILE)


def anilist_session():
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    if TOKEN:
        session.headers["Authorization"] = f"Bearer {TOKEN}"
    return session


def graphql(session, page):
    payload = {"query": QUERY, "variables": {"userName": USERNAME, "page": page}}
    for attempt in range(RETRIES):
        try:
            response = session.post(API, json=payload, timeout=TIMEOUT)
        except requests.RequestException as error:
            if attempt == RETRIES - 1:
                raise RuntimeError(f"AniList request failed: {error}") from error
            time.sleep(min(2 ** attempt, 20))
            continue

        if response.status_code == 200:
            body = response.json()
            if body.get("errors"):
                raise RuntimeError(f"AniList GraphQL error: {body['errors']}")
            return body
        if response.status_code == 429 or response.status_code >= 500:
            try:
                delay = max(float(response.headers.get("Retry-After", 0)), min(2 ** attempt, 20))
            except (TypeError, ValueError):
                delay = min(2 ** attempt, 20)
            logging.warning("AniList returned %s; retrying in %.1fs", response.status_code, delay)
            time.sleep(delay)
            continue
        response.raise_for_status()
    raise RuntimeError("AniList request failed after all retries")


def fetch_airings():
    session = anilist_session()
    page = 1
    results = []
    while True:
        page_data = graphql(session, page).get("data", {}).get("Page") or {}
        for entry in page_data.get("mediaList") or []:
            media = entry.get("media") or {}
            if media.get("type") != "ANIME":
                continue
            next_ep = media.get("nextAiringEpisode") or {}
            try:
                media_id = int(entry.get("mediaId") or media["id"])
                episode = int(next_ep["episode"])
                airing_at = int(next_ep["airingAt"])
            except (KeyError, TypeError, ValueError):
                continue
            titles = media.get("title") or {}
            cover = media.get("coverImage") or {}
            title = titles.get("english") or titles.get("romaji") or f"Anime {media_id}"
            results.append({
                "media_id": media_id,
                "title": title,
                "romaji": titles.get("romaji") or title,
                "episode": episode,
                "airing_at": airing_at,
                "cover": cover.get("extraLarge"),
                "color": cover.get("color"),
            })
        if not (page_data.get("pageInfo") or {}).get("hasNextPage"):
            break
        page += 1
        time.sleep(1)
    results.sort(key=lambda item: item["airing_at"])
    logging.info("Found %d upcoming anime airings across %d page(s)", len(results), page)
    return results


def discord_send(airing, alert_type):
    warning = "3-HOUR" if alert_type == "3h" else "FINAL 1-HOUR"
    color = 0x5865F2
    raw_color = str(airing.get("color") or "").lstrip("#")
    if len(raw_color) == 6:
        try:
            color = int(raw_color, 16)
        except ValueError:
            pass

    embed = {
        "title": f"{'🕒' if alert_type == '3h' else '🚨'} {warning} AIRING WARNING · Episode {airing['episode']}"[:256],
        "description": (
            f"**{airing['title']}**\n"
            f"Episode **{airing['episode']}** is scheduled to air <t:{airing['airing_at']}:R>."
        ),
        "color": color,
        "fields": [
            {"name": "🇯🇵 Romaji", "value": str(airing["romaji"])[:1024], "inline": False},
            {"name": "📺 Telecast Time", "value": f"<t:{airing['airing_at']}:F>", "inline": False},
            {"name": "⏳ Countdown", "value": f"<t:{airing['airing_at']}:R>", "inline": True},
        ],
        "footer": {"text": "AniList · Hourly Airing Monitor"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if airing.get("cover"):
        embed["thumbnail"] = {"url": airing["cover"]}

    for attempt in range(RETRIES):
        try:
            response = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=TIMEOUT)
        except requests.RequestException as error:
            if attempt == RETRIES - 1:
                logging.error("Discord delivery failed for %s: %s", airing["title"], error)
                return False
            time.sleep(min(2 ** attempt, 20))
            continue
        if response.status_code in (200, 201, 204):
            logging.info("Sent %s alert: %s episode %s", alert_type, airing["title"], airing["episode"])
            return True
        if response.status_code == 429 or response.status_code >= 500:
            try:
                delay = max(float(response.headers.get("Retry-After", 0)), min(2 ** attempt, 20))
            except (TypeError, ValueError):
                delay = min(2 ** attempt, 20)
            time.sleep(delay)
            continue
        logging.error("Discord rejected alert (%s): %s", response.status_code, response.text[:500])
        return False
    logging.error("Discord delivery failed after retries for %s", airing["title"])
    return False


def check_alerts(airings, state, now):
    sent = failed = 0
    changed = False
    for airing in airings:
        remaining = airing["airing_at"] - now
        if remaining <= 0:
            continue
        key = f"{airing['media_id']}_ep{airing['episode']}"
        status = state.get(key, "none")
        alert = None
        if 3600 < remaining <= 10800 and status == "none":
            alert = "3h"
        elif 0 < remaining <= 3600 and status in ("none", "3h"):
            alert = "1h"
        if not alert:
            continue
        if discord_send(airing, alert):
            state[key] = alert
            sent += 1
            changed = True
        else:
            failed += 1
    if changed:
        save_state(state)
    return sent, failed


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s UTC | %(levelname)s | %(message)s")
    if not USERNAME:
        raise RuntimeError("ANILIST_USERNAME is empty")
    if not WEBHOOK:
        raise RuntimeError("Missing required GitHub Actions secret: DISCORD_AIRING_WEBHOOK")
    state = load_state()
    airings = fetch_airings()
    sent, failed = check_alerts(airings, state, int(time.time()))
    logging.info("Check complete: %d alert(s) sent, %d delivery failure(s)", sent, failed)


if __name__ == "__main__":
    main()
